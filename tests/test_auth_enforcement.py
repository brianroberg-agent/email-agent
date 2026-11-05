"""The bearer-token requirement, exercised through the real application.

The route lists here are read from the application object, never typed out,
so a route added later is covered without this file changing.
"""

import logging
import re
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from email_server import app
from tests.conftest import TEST_API_TOKEN, TEST_CALLER, WRONG_API_TOKEN

# The only operation that answers without a token. Deliberately written out
# here rather than imported from the application: if the application's
# exempt list grows, the route walk below fails until this line is changed
# on purpose.
OPEN_OPERATIONS = {("GET", "/health")}

UNAUTHORIZED_BODY = {"detail": "Missing or invalid bearer token"}


def registered_operations() -> list[tuple[str, str]]:
    """Every (method, path) the application registers, path parameters
    filled with a placeholder."""
    operations = []
    for route in app.routes:
        assert isinstance(route, Route), (
            f"{route!r} is a kind of route this walk does not understand; "
            "teach it before adding one"
        )
        path = re.sub(r"\{[^}]+\}", "example-id", route.path)
        operations.extend((method, path) for method in sorted(route.methods))
    return operations


ALL_OPERATIONS = registered_operations()
PROTECTED_OPERATIONS = [op for op in ALL_OPERATIONS if op not in OPEN_OPERATIONS]


def _ids(operations):
    return [f"{method} {path}" for method, path in operations]


def assert_unauthorized(response, method="GET"):
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    if method != "HEAD":
        assert response.json() == UNAUTHORIZED_BODY


class TestRouteWalk:
    def test_the_walk_sees_the_api_and_the_documentation_routes(self):
        paths = {path for _, path in ALL_OPERATIONS}

        assert {"/health", "/labels", "/search", "/openapi.json", "/docs", "/redoc"} <= paths
        assert OPEN_OPERATIONS <= set(ALL_OPERATIONS)

    @pytest.mark.parametrize("method, path", PROTECTED_OPERATIONS, ids=_ids(PROTECTED_OPERATIONS))
    def test_route_refuses_a_request_with_no_token(self, method, path, anonymous_client):
        with patch("email_server.get_gmail_client") as gmail, patch(
            "email_server.call_local_llm"
        ) as llm:
            response = anonymous_client.request(method, path)

        assert_unauthorized(response, method)
        assert not gmail.called and not llm.called

    @pytest.mark.parametrize("method, path", PROTECTED_OPERATIONS, ids=_ids(PROTECTED_OPERATIONS))
    def test_route_refuses_a_request_with_a_wrong_token(self, method, path, anonymous_client):
        with patch("email_server.get_gmail_client") as gmail, patch(
            "email_server.call_local_llm"
        ) as llm:
            response = anonymous_client.request(
                method, path, headers={"Authorization": f"Bearer {WRONG_API_TOKEN}"}
            )

        assert_unauthorized(response, method)
        assert not gmail.called and not llm.called

    @pytest.mark.parametrize("method, path", ALL_OPERATIONS, ids=_ids(ALL_OPERATIONS))
    def test_only_the_health_check_answers_without_a_token(self, method, path, anonymous_client):
        with patch("email_server.get_gmail_client"), patch("email_server.call_local_llm"):
            response = anonymous_client.request(method, path)

        served = response.status_code != 401
        assert served == ((method, path) in OPEN_OPERATIONS)

    @pytest.mark.parametrize("method, path", PROTECTED_OPERATIONS, ids=_ids(PROTECTED_OPERATIONS))
    def test_route_is_reached_with_the_right_token(self, method, path, client):
        """With a configured token the request gets past the check to the
        route: whatever it answers (a result, a validation error for the
        empty body sent here, an upstream failure), it is not a 401."""
        with patch("email_server.get_gmail_client", side_effect=RuntimeError("no upstream in tests")):
            response = client.request(method, path)

        assert response.status_code != 401
        assert "www-authenticate" not in response.headers

    @pytest.mark.parametrize("path", ["/no-such-route", "/health/", "/healthz", "//health", "/health/x"])
    def test_a_path_that_is_not_registered_is_refused_before_routing(self, path, anonymous_client):
        response = anonymous_client.get(path, follow_redirects=False)

        assert_unauthorized(response)

    def test_an_unregistered_path_is_a_404_with_the_right_token(self, client):
        assert client.get("/no-such-route").status_code == 404


AUTH_LOGGER = "email_agent.auth"
BEARER = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
WRONG_BEARER = {"Authorization": f"Bearer {WRONG_API_TOKEN}"}
EMPTY_LABELS = {"success": True, "labels": [], "error": None}


@pytest.fixture
def gmail():
    """A fake Gmail client with no labels, so GET /labels has a normal
    answer to give without any upstream."""
    with patch("email_server.get_gmail_client") as get_client:
        get_client.return_value = AsyncMock()
        get_client.return_value.list_labels.return_value = {"labels": []}
        yield get_client


@pytest.fixture
def auth_log(caplog):
    caplog.set_level(logging.INFO, logger=AUTH_LOGGER)
    return caplog


def auth_records(caplog):
    return [record for record in caplog.records if record.name == AUTH_LOGGER]


def set_mode(monkeypatch, mode):
    monkeypatch.setenv("EMAIL_AGENT_AUTH", mode)


class TestHealthIsOpen:
    @pytest.mark.parametrize("mode", ["required", "optional", "off"])
    @pytest.mark.parametrize("headers", [{}, WRONG_BEARER, BEARER], ids=["no token", "wrong token", "right token"])
    def test_health_answers_in_every_mode_whatever_the_token(
        self, mode, headers, monkeypatch, anonymous_client, auth_log
    ):
        set_mode(monkeypatch, mode)

        response = anonymous_client.get("/health", headers=headers)

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": "2.0"}
        assert auth_records(auth_log) == []


class TestRequiredMode:
    def test_the_right_token_gets_the_routes_normal_answer(self, gmail, anonymous_client):
        response = anonymous_client.get("/labels", headers=BEARER)

        assert response.status_code == 200
        assert response.json() == EMPTY_LABELS
        assert gmail.called

    def test_an_authenticated_request_is_logged_with_the_callers_name(
        self, gmail, anonymous_client, auth_log
    ):
        anonymous_client.get("/labels", headers=BEARER)

        (record,) = auth_records(auth_log)
        assert record.levelno == logging.INFO
        message = record.getMessage()
        assert "GET /labels" in message
        assert TEST_CALLER in message
        assert "testclient" in message

    @pytest.mark.parametrize(
        "headers, reason", [({}, "no token"), (WRONG_BEARER, "invalid token")]
    )
    def test_a_refusal_is_logged_once_as_a_warning_with_the_route_and_reason(
        self, headers, reason, anonymous_client, auth_log
    ):
        response = anonymous_client.post("/search", json={}, headers=headers)

        assert_unauthorized(response)
        (record,) = auth_records(auth_log)
        assert record.levelno == logging.WARNING
        message = record.getMessage()
        assert "refused" in message
        assert "POST /search" in message
        assert "testclient" in message
        assert reason in message

    def test_the_401_body_is_the_same_for_a_missing_and_a_wrong_token(self, anonymous_client):
        missing = anonymous_client.get("/labels")
        wrong = anonymous_client.get("/labels", headers=WRONG_BEARER)

        assert missing.status_code == wrong.status_code == 401
        assert missing.content == wrong.content
        assert missing.headers["content-type"] == "application/json"


class TestOptionalMode:
    def test_a_request_with_no_token_is_served(self, monkeypatch, gmail, anonymous_client):
        set_mode(monkeypatch, "optional")

        response = anonymous_client.get("/labels")

        assert response.status_code == 200
        assert response.json() == EMPTY_LABELS

    def test_a_request_with_no_token_is_logged_once_as_a_warning_naming_the_route(
        self, monkeypatch, gmail, anonymous_client, auth_log
    ):
        set_mode(monkeypatch, "optional")

        anonymous_client.get("/labels")

        (record,) = auth_records(auth_log)
        assert record.levelno == logging.WARNING
        message = record.getMessage()
        assert "unauthenticated" in message
        assert "GET /labels" in message
        assert "testclient" in message

    def test_a_wrong_token_is_refused(self, monkeypatch, gmail, anonymous_client):
        set_mode(monkeypatch, "optional")

        response = anonymous_client.get("/labels", headers=WRONG_BEARER)

        assert_unauthorized(response)
        assert not gmail.called

    def test_the_right_token_is_served_and_logged_under_its_name_not_as_a_warning(
        self, monkeypatch, gmail, anonymous_client, auth_log
    ):
        set_mode(monkeypatch, "optional")

        response = anonymous_client.get("/labels", headers=BEARER)

        assert response.json() == EMPTY_LABELS
        (record,) = auth_records(auth_log)
        assert record.levelno == logging.INFO
        assert TEST_CALLER in record.getMessage()

    def test_with_no_tokens_configured_tokenless_is_served_and_any_token_refused(
        self, monkeypatch, gmail, anonymous_client
    ):
        set_mode(monkeypatch, "optional")
        monkeypatch.setenv("EMAIL_AGENT_API_KEYS", "")

        assert anonymous_client.get("/labels").status_code == 200
        assert_unauthorized(anonymous_client.get("/labels", headers=BEARER))


class TestOffMode:
    @pytest.mark.parametrize("headers", [{}, WRONG_BEARER, BEARER], ids=["no token", "wrong token", "right token"])
    def test_every_request_is_served_and_none_is_logged(
        self, headers, monkeypatch, gmail, anonymous_client, auth_log
    ):
        set_mode(monkeypatch, "off")

        response = anonymous_client.get("/labels", headers=headers)

        assert response.status_code == 200
        assert response.json() == EMPTY_LABELS
        assert auth_records(auth_log) == []

    def test_off_serves_without_any_tokens_configured(self, monkeypatch, gmail, anonymous_client):
        set_mode(monkeypatch, "off")
        monkeypatch.delenv("EMAIL_AGENT_API_KEYS")

        assert anonymous_client.get("/labels").status_code == 200


class TestRequestLogContent:
    def test_the_query_string_is_not_logged(self, anonymous_client, auth_log):
        anonymous_client.get("/labels?note=query-text-that-must-not-be-logged")

        (record,) = auth_records(auth_log)
        assert "GET /labels " in record.getMessage()
        assert "query-text" not in record.getMessage()

    def test_control_characters_in_the_path_cannot_start_a_new_log_line(
        self, anonymous_client, auth_log
    ):
        anonymous_client.get("/labels%0Aauth: forged line%0D%1B[0m")

        (record,) = auth_records(auth_log)
        message = record.getMessage()
        assert "\n" not in message and "\r" not in message and "\x1b" not in message
        assert "forged line" in message


class TestNoTokenLeaks:
    @patch("email_server.call_local_llm", side_effect=RuntimeError("no LLM in tests"))
    @patch("email_server.get_gmail_client", side_effect=RuntimeError("no upstream in tests"))
    def test_no_token_text_reaches_a_log_a_response_or_the_console(
        self, _gmail, _llm, monkeypatch, caplog, capsys
    ):
        """Send right, wrong and misplaced tokens to every route in every
        mode, then look for either token in everything the service wrote:
        every log record from every logger, stdout, stderr, and each
        response's body and headers."""
        caplog.set_level(logging.DEBUG)
        client = TestClient(app, raise_server_exceptions=False)
        credentials = [
            None,
            f"Bearer {TEST_API_TOKEN}",
            f"Bearer {WRONG_API_TOKEN}",
            f"Basic {TEST_API_TOKEN}",
            TEST_API_TOKEN,
            f"Bearer {TEST_API_TOKEN} {WRONG_API_TOKEN}",
        ]
        written = []
        for mode in ("required", "optional", "off"):
            set_mode(monkeypatch, mode)
            for method, path in ALL_OPERATIONS + [("GET", "/no-such-route")]:
                for credential in credentials:
                    headers = {} if credential is None else {"Authorization": credential}
                    response = client.request(method, path, headers=headers)
                    written.append(response.text)
                    written.append(repr(response.headers))
        console = capsys.readouterr()
        written += [caplog.text, console.out, console.err]
        written += [record.getMessage() for record in caplog.records]

        # The check logged these requests, so the search below is of real output.
        assert len(auth_records(caplog)) > len(ALL_OPERATIONS)
        for text in written:
            assert TEST_API_TOKEN not in text
            assert WRONG_API_TOKEN not in text


class TestMisconfigurationWithoutStartup:
    """If the application is driven without its start-up hook (which is
    where a bad configuration normally stops the service), a request is
    still not served."""

    @pytest.mark.parametrize("headers", [{}, BEARER], ids=["no token", "a token"])
    def test_required_mode_with_no_tokens_serves_no_request(
        self, headers, monkeypatch, gmail, anonymous_client
    ):
        import auth

        monkeypatch.setenv("EMAIL_AGENT_API_KEYS", "")

        with pytest.raises(auth.AuthConfigError):
            anonymous_client.get("/labels", headers=headers)

        assert not gmail.called

    def test_the_health_check_still_answers(self, monkeypatch, anonymous_client):
        monkeypatch.setenv("EMAIL_AGENT_API_KEYS", "")

        assert anonymous_client.get("/health").status_code == 200
