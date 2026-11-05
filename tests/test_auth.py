"""Tests for auth.py: parsing the token settings and deciding a request.

Every token in this file is synthetic. Nothing here is a real credential.
"""

import pytest

import auth

TOKEN_A = "synthetic-token-aaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN_B = "synthetic-token-bbbbbbbbbbbbbbbbbbbbbbbb"
TOKEN_C = "synthetic-token-cccccccccccccccccccccccc"


class TestParseApiKeys:
    def test_single_pair_gives_one_named_key(self):
        keys = auth.parse_api_keys(f"alpha:{TOKEN_A}")

        assert [key.name for key in keys] == ["alpha"]
        assert keys[0].matches(TOKEN_A)
        assert not keys[0].matches(TOKEN_B)

    def test_several_pairs_keep_their_order_and_their_own_tokens(self):
        keys = auth.parse_api_keys(f"alpha:{TOKEN_A},beta:{TOKEN_B}")

        assert [key.name for key in keys] == ["alpha", "beta"]
        assert keys[0].matches(TOKEN_A) and not keys[0].matches(TOKEN_B)
        assert keys[1].matches(TOKEN_B) and not keys[1].matches(TOKEN_A)

    def test_whitespace_around_entries_names_and_tokens_is_ignored(self):
        keys = auth.parse_api_keys(f"  alpha : {TOKEN_A} ,\n beta:{TOKEN_B}  ")

        assert [key.name for key in keys] == ["alpha", "beta"]
        assert keys[0].matches(TOKEN_A)
        assert keys[1].matches(TOKEN_B)

    def test_blank_entries_from_stray_commas_are_skipped(self):
        keys = auth.parse_api_keys(f"alpha:{TOKEN_A},,beta:{TOKEN_B},")

        assert [key.name for key in keys] == ["alpha", "beta"]

    @pytest.mark.parametrize("raw", [None, "", "   ", ",", " , "])
    def test_unset_or_blank_setting_gives_no_keys(self, raw):
        assert auth.parse_api_keys(raw) == ()

    def test_a_token_may_contain_colons(self):
        token = "synthetic:token:with:colons:dddddddddddd"
        keys = auth.parse_api_keys(f"alpha:{token}")

        assert keys[0].name == "alpha"
        assert keys[0].matches(token)


# Each case: (setting value, text the error must contain). The values are
# built so that no part of them is a valid configuration.
MALFORMED_KEYS = {
    "entry without a colon": (TOKEN_A, "entry 1"),
    "entry with an empty name": (f":{TOKEN_A}", "entry 1"),
    "empty token": ("alpha:", "entry 1"),
    "whitespace-only token": ("alpha:   ", "entry 1"),
    "duplicate name": (f"alpha:{TOKEN_A},beta:{TOKEN_B},alpha:{TOKEN_C}", "entry 3"),
    "duplicate token": (f"alpha:{TOKEN_A},beta:{TOKEN_A}", "entry 2"),
    "token shorter than the minimum": ("alpha:synthetic-short-token", "entry 1"),
    "token one character short": ("alpha:" + "s" * 31, "entry 1"),
    "token with a space inside": (f"alpha:synthetic token {TOKEN_A}", "entry 1"),
    "token with a non-ASCII character": (f"alpha:{TOKEN_A}é", "entry 1"),
    "name with a space": (f"al pha:{TOKEN_A}", "entry 1"),
    "name with a control character": (f"al\x1bpha:{TOKEN_A}", "entry 1"),
    "name as long as a token": (f"{TOKEN_B}:{TOKEN_A}", "entry 1"),
    "name of 32 characters": (f"{'n' * 32}:{TOKEN_A}", "entry 1"),
    "second entry malformed": (f"alpha:{TOKEN_A},beta", "entry 2"),
}


class TestParseApiKeysRejectsMalformedSettings:
    @pytest.mark.parametrize("case", sorted(MALFORMED_KEYS))
    def test_malformed_setting_is_a_configuration_error(self, case):
        raw, expected = MALFORMED_KEYS[case]

        with pytest.raises(auth.AuthConfigError) as excinfo:
            auth.parse_api_keys(raw)

        message = str(excinfo.value)
        assert "EMAIL_AGENT_API_KEYS" in message
        assert expected in message

    @pytest.mark.parametrize("case", sorted(MALFORMED_KEYS))
    def test_error_message_echoes_nothing_from_the_setting(self, case):
        """The message names the entry by position. It repeats no name and no
        token, because a token pasted in the wrong place would otherwise be
        printed at start-up."""
        raw, _ = MALFORMED_KEYS[case]

        with pytest.raises(auth.AuthConfigError) as excinfo:
            auth.parse_api_keys(raw)

        message = str(excinfo.value)
        for entry in raw.split(","):
            for piece in entry.split(":"):
                piece = piece.strip()
                if len(piece) >= 4:
                    assert piece not in message

    def test_a_token_of_exactly_the_minimum_length_is_accepted(self):
        token = "s" * auth.MIN_TOKEN_LENGTH

        assert auth.MIN_TOKEN_LENGTH == 32
        assert auth.parse_api_keys(f"alpha:{token}")[0].matches(token)

    def test_a_name_of_31_characters_is_accepted(self):
        name = "n" * 31

        assert auth.parse_api_keys(f"{name}:{TOKEN_A}")[0].name == name

    def test_key_repr_shows_the_name_and_not_the_token_or_digest(self):
        key = auth.parse_api_keys(f"alpha:{TOKEN_A}")[0]

        assert "alpha" in repr(key)
        assert TOKEN_A not in repr(key)
        assert "digest" not in repr(key)


class TestLoadAuthSettings:
    def test_mode_defaults_to_required(self):
        settings = auth.load_auth_settings({"EMAIL_AGENT_API_KEYS": f"alpha:{TOKEN_A}"})

        assert settings.mode is auth.AuthMode.REQUIRED
        assert [key.name for key in settings.keys] == ["alpha"]

    def test_a_blank_mode_is_treated_as_unset(self):
        settings = auth.load_auth_settings(
            {"EMAIL_AGENT_AUTH": "  ", "EMAIL_AGENT_API_KEYS": f"alpha:{TOKEN_A}"}
        )

        assert settings.mode is auth.AuthMode.REQUIRED

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("required", "REQUIRED"),
            ("optional", "OPTIONAL"),
            ("off", "OFF"),
            ("Optional", "OPTIONAL"),
            (" OFF ", "OFF"),
        ],
    )
    def test_each_mode_value_is_recognised(self, value, expected):
        settings = auth.load_auth_settings(
            {"EMAIL_AGENT_AUTH": value, "EMAIL_AGENT_API_KEYS": f"alpha:{TOKEN_A}"}
        )

        assert settings.mode is auth.AuthMode[expected]

    def test_an_unknown_mode_is_a_configuration_error_that_does_not_echo_it(self):
        with pytest.raises(auth.AuthConfigError) as excinfo:
            auth.load_auth_settings(
                {"EMAIL_AGENT_AUTH": TOKEN_B, "EMAIL_AGENT_API_KEYS": f"alpha:{TOKEN_A}"}
            )

        message = str(excinfo.value)
        assert "EMAIL_AGENT_AUTH" in message
        for mode in ("required", "optional", "off"):
            assert mode in message
        assert TOKEN_B not in message

    @pytest.mark.parametrize(
        "environ",
        [
            {},
            {"EMAIL_AGENT_AUTH": "required"},
            {"EMAIL_AGENT_AUTH": "required", "EMAIL_AGENT_API_KEYS": ""},
            {"EMAIL_AGENT_API_KEYS": " , "},
        ],
    )
    def test_required_mode_without_tokens_is_refused_naming_both_settings(self, environ):
        with pytest.raises(auth.AuthConfigError) as excinfo:
            auth.load_auth_settings(environ)

        message = str(excinfo.value)
        assert "EMAIL_AGENT_API_KEYS" in message
        assert "EMAIL_AGENT_AUTH" in message

    @pytest.mark.parametrize("mode", ["optional", "off"])
    def test_optional_and_off_load_without_tokens(self, mode):
        settings = auth.load_auth_settings({"EMAIL_AGENT_AUTH": mode})

        assert settings.mode is auth.AuthMode(mode)
        assert settings.keys == ()

    @pytest.mark.parametrize("mode", ["required", "optional", "off"])
    def test_a_malformed_key_list_is_refused_in_every_mode(self, mode):
        with pytest.raises(auth.AuthConfigError) as excinfo:
            auth.load_auth_settings(
                {"EMAIL_AGENT_AUTH": mode, "EMAIL_AGENT_API_KEYS": "alpha:too-short"}
            )

        assert "entry 1" in str(excinfo.value)

    def test_settings_repr_holds_no_token(self):
        settings = auth.load_auth_settings(
            {"EMAIL_AGENT_API_KEYS": f"alpha:{TOKEN_A},beta:{TOKEN_B}"}
        )

        assert TOKEN_A not in repr(settings)
        assert TOKEN_B not in repr(settings)


def _settings(mode: str, keys: str = f"alpha:{TOKEN_A},beta:{TOKEN_B}") -> "auth.AuthSettings":
    return auth.load_auth_settings({"EMAIL_AGENT_AUTH": mode, "EMAIL_AGENT_API_KEYS": keys})


# Authorization header values that are present but are not a configured
# bearer token. Each must be refused wherever a token is checked.
WRONG_CREDENTIALS = {
    "an unknown token": [f"Bearer {TOKEN_C}"],
    "a configured token cut short": [f"Bearer {TOKEN_A[:-1]}"],
    "a configured token with a suffix": [f"Bearer {TOKEN_A}x"],
    "a configured token in different case": [f"Bearer {TOKEN_A.upper()}"],
    "the token with no scheme": [TOKEN_A],
    "another scheme": [f"Basic {TOKEN_A}"],
    "the scheme with no token": ["Bearer"],
    "the scheme and a space": ["Bearer "],
    "an empty header": [""],
    "a third word after the token": [f"Bearer {TOKEN_A} extra"],
    "a caller name instead of a token": ["Bearer alpha"],
    "two headers, both valid": [f"Bearer {TOKEN_A}", f"Bearer {TOKEN_B}"],
}


class TestDecide:
    @pytest.mark.parametrize("name, token", [("alpha", TOKEN_A), ("beta", TOKEN_B)])
    @pytest.mark.parametrize("mode", ["required", "optional"])
    def test_a_configured_token_is_allowed_and_names_its_caller(self, mode, name, token):
        decision = auth.decide(_settings(mode), [f"Bearer {token}"])

        assert decision.allowed is True
        assert decision.caller == name
        assert decision.credential == "valid"

    @pytest.mark.parametrize("header", [f"bearer {TOKEN_A}", f"BEARER {TOKEN_A}", f"Bearer   {TOKEN_A}  "])
    def test_scheme_case_and_extra_spaces_do_not_matter(self, header):
        decision = auth.decide(_settings("required"), [header])

        assert decision.allowed is True
        assert decision.caller == "alpha"

    def test_required_mode_refuses_a_request_with_no_header(self):
        decision = auth.decide(_settings("required"), [])

        assert decision.allowed is False
        assert decision.caller is None
        assert decision.credential == "none"

    def test_optional_mode_allows_a_request_with_no_header_without_a_caller(self):
        decision = auth.decide(_settings("optional"), [])

        assert decision.allowed is True
        assert decision.caller is None
        assert decision.credential == "none"

    @pytest.mark.parametrize("case", sorted(WRONG_CREDENTIALS))
    @pytest.mark.parametrize("mode", ["required", "optional"])
    def test_a_wrong_credential_is_refused(self, mode, case):
        decision = auth.decide(_settings(mode), WRONG_CREDENTIALS[case])

        assert decision.allowed is False
        assert decision.caller is None
        assert decision.credential == "invalid"

    def test_optional_mode_with_no_keys_refuses_any_token(self):
        decision = auth.decide(_settings("optional", keys=""), [f"Bearer {TOKEN_A}"])

        assert decision.allowed is False
        assert decision.credential == "invalid"

    @pytest.mark.parametrize(
        "headers", [[], [f"Bearer {TOKEN_A}"], [f"Bearer {TOKEN_C}"], ["Basic nonsense"]]
    )
    def test_off_mode_allows_everything_and_checks_nothing(self, headers, monkeypatch):
        def fail(*args):
            raise AssertionError("off mode compared a token")

        settings = _settings("off")
        monkeypatch.setattr(auth.hmac, "compare_digest", fail)

        decision = auth.decide(settings, headers)

        assert decision.allowed is True
        assert decision.caller is None
        assert decision.credential == "unchecked"

    @pytest.mark.parametrize("presented", [TOKEN_A, TOKEN_B, TOKEN_C])
    def test_every_key_is_compared_in_constant_time_with_no_early_exit(
        self, presented, monkeypatch
    ):
        """The comparison is hmac.compare_digest, on equal-length digests,
        once per configured key whichever one matches (or none)."""
        import hmac as real_hmac

        real_compare = real_hmac.compare_digest
        calls = []

        def spy(a, b):
            calls.append((a, b))
            return real_compare(a, b)

        settings = _settings("required", keys=f"alpha:{TOKEN_A},beta:{TOKEN_B},gamma:{'g' * 40}")
        monkeypatch.setattr(auth.hmac, "compare_digest", spy)

        auth.decide(settings, [f"Bearer {presented}"])

        assert len(calls) == 3
        for a, b in calls:
            assert isinstance(a, bytes) and isinstance(b, bytes)
            assert len(a) == len(b) == 32


def _wrapped_app(mode: str = "required"):
    """A two-route application (one HTTP, one WebSocket) behind the
    middleware, with nothing exempt."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route, WebSocketRoute

    async def page(request):
        return PlainTextResponse("served")

    async def socket(websocket):
        await websocket.accept()
        await websocket.send_text("served")
        await websocket.close()

    inner = Starlette(routes=[Route("/page", page), WebSocketRoute("/socket", socket)])
    settings = _settings(mode)
    return auth.BearerAuthMiddleware(inner, get_settings=lambda: settings, exempt_paths=())


class TestMiddleware:
    def test_a_websocket_without_a_token_is_closed_before_it_is_accepted(self):
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        client = TestClient(_wrapped_app())

        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/socket"):
                pass

        assert excinfo.value.code == 1008

    def test_a_websocket_with_the_right_token_is_served(self):
        from starlette.testclient import TestClient

        client = TestClient(_wrapped_app())

        with client.websocket_connect(
            "/socket", headers={"Authorization": f"Bearer {TOKEN_A}"}
        ) as websocket:
            assert websocket.receive_text() == "served"

    async def test_a_request_with_no_client_address_is_refused_and_logged(self, caplog):
        sent = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {"type": "http", "method": "GET", "path": "/page", "headers": []}
        with caplog.at_level("INFO", logger="email_agent.auth"):
            await _wrapped_app()(scope, receive, send)

        assert sent[0]["status"] == 401
        assert "GET /page from an unknown address" in caplog.text
