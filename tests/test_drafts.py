"""Tests for draft operations and message builder."""

import base64
import email
from unittest.mock import patch, AsyncMock

import pytest

from tests.conftest import SAMPLE_MESSAGES


# =============================================================================
# MESSAGE BUILDER TESTS
# =============================================================================


class TestBuildRFC2822:
    """Tests for message_builder.build_rfc2822."""

    def test_basic_message(self):
        from message_builder import build_rfc2822

        raw = build_rfc2822(
            to=["alice@example.com"],
            subject="Test Subject",
            body="Hello, world!",
        )

        # Parse the RFC 2822 message to verify structure
        msg_bytes = base64.urlsafe_b64decode(raw)
        msg = email.message_from_bytes(msg_bytes)
        assert msg["To"] == "alice@example.com"
        assert msg["Subject"] == "Test Subject"
        assert msg.get_payload(decode=True).decode("utf-8") == "Hello, world!"

    def test_multiple_recipients(self):
        from message_builder import build_rfc2822

        raw = build_rfc2822(
            to=["alice@example.com", "bob@example.com"],
            subject="Group message",
            body="Hi all",
        )

        decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
        assert "alice@example.com" in decoded
        assert "bob@example.com" in decoded

    def test_cc_and_bcc(self):
        from message_builder import build_rfc2822

        raw = build_rfc2822(
            to=["alice@example.com"],
            subject="Test",
            body="Body",
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
        )

        decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
        assert "Cc: cc@example.com" in decoded
        assert "Bcc: bcc@example.com" in decoded

    def test_reply_threading_headers(self):
        from message_builder import build_rfc2822

        raw = build_rfc2822(
            to=["alice@example.com"],
            subject="Re: Original",
            body="My reply",
            in_reply_to="<original-id@example.com>",
            references=["<original-id@example.com>", "<earlier@example.com>"],
        )

        decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
        assert "In-Reply-To: <original-id@example.com>" in decoded
        assert "References: <original-id@example.com> <earlier@example.com>" in decoded

    def test_no_optional_headers_when_none(self):
        from message_builder import build_rfc2822

        raw = build_rfc2822(
            to=["alice@example.com"],
            subject="Test",
            body="Body",
        )

        decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
        assert "Cc:" not in decoded
        assert "Bcc:" not in decoded
        assert "In-Reply-To:" not in decoded
        assert "References:" not in decoded

    def test_empty_to_raises(self):
        from message_builder import build_rfc2822

        with pytest.raises(ValueError, match="At least one recipient"):
            build_rfc2822(to=[], subject="Test", body="Body")

    def test_empty_subject_raises(self):
        from message_builder import build_rfc2822

        with pytest.raises(ValueError, match="Subject is required"):
            build_rfc2822(to=["a@b.com"], subject="", body="Body")

    def test_empty_body_raises(self):
        from message_builder import build_rfc2822

        with pytest.raises(ValueError, match="Body is required"):
            build_rfc2822(to=["a@b.com"], subject="Test", body="")

    def test_output_is_valid_base64url(self):
        from message_builder import build_rfc2822

        raw = build_rfc2822(
            to=["alice@example.com"],
            subject="Test",
            body="Body",
        )

        # Should not raise
        decoded = base64.urlsafe_b64decode(raw)
        assert len(decoded) > 0

    def test_utf8_body(self):
        from message_builder import build_rfc2822

        raw = build_rfc2822(
            to=["alice@example.com"],
            subject="Test",
            body="Hello café résumé naïve",
        )

        # Parse and decode the body to verify UTF-8 content is preserved
        msg_bytes = base64.urlsafe_b64decode(raw)
        msg = email.message_from_bytes(msg_bytes)
        body = msg.get_payload(decode=True).decode("utf-8")
        assert "Hello café résumé naïve" == body


# =============================================================================
# CREATE DRAFT ENDPOINT TESTS
# =============================================================================


class TestCreateDraftEndpoint:
    """Tests for POST /drafts/create."""

    @patch("email_server.get_gmail_client")
    def test_create_draft_success(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {
            "id": "r123",
            "message": {"id": "msg456", "threadId": "t789"},
        }

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Meeting follow-up",
            "body": "Thanks for the meeting.",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["draft_id"] == "r123"
        assert "r123" in data["message"]

        # Verify create_draft was called with a base64 string
        mock_proxy.create_draft.assert_called_once()
        raw_msg = mock_proxy.create_draft.call_args[0][0]
        decoded = base64.urlsafe_b64decode(raw_msg).decode("utf-8")
        assert "alice@example.com" in decoded
        assert "Meeting follow-up" in decoded

    @patch("email_server.get_gmail_client")
    def test_create_draft_with_cc_bcc(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {"id": "r456"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Test",
            "body": "Body",
            "cc": ["cc@example.com"],
            "bcc": ["bcc@example.com"],
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

        raw_msg = mock_proxy.create_draft.call_args[0][0]
        decoded = base64.urlsafe_b64decode(raw_msg).decode("utf-8")
        assert "Cc: cc@example.com" in decoded
        assert "Bcc: bcc@example.com" in decoded

    @patch("email_server.get_gmail_client")
    def test_create_draft_with_threading(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.return_value = {"id": "r789"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
            "references": ["<msg123@example.com>"],
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

        raw_msg = mock_proxy.create_draft.call_args[0][0]
        decoded = base64.urlsafe_b64decode(raw_msg).decode("utf-8")
        assert "In-Reply-To: <msg123@example.com>" in decoded

    @patch("email_server.get_gmail_client")
    def test_create_draft_with_thread_id(self, mock_get_client, client):
        """An explicit thread_id is forwarded as-is, with no lookup."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {"id": "r790"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
            "references": ["<msg123@example.com>"],
            "thread_id": "thread_abc",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] == "thread_abc"
        mock_proxy.list_messages.assert_not_called()
        # The result lacks a message stub; the requested thread is reported
        # rather than a null that would contradict thread_attached=true.
        assert data["thread_id"] == "thread_abc"
        assert data["thread_attached"] is True

    @patch("email_server.get_gmail_client")
    def test_create_draft_without_thread_id(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {"id": "r791"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Test",
            "body": "Body",
        })

        assert response.status_code == 200
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] is None
        mock_proxy.list_messages.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_create_draft_resolves_thread_id_from_in_reply_to(self, mock_get_client, client):
        """When in_reply_to is given without thread_id, the original message's
        Gmail thread is looked up so the draft lands in that conversation."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.return_value = {
            "id": "r800",
            "message": {"id": "m800", "threadId": "t_orig"},
        }

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_id"] == "t_orig"
        assert data["thread_attached"] is True

        mock_proxy.list_messages.assert_called_once()
        assert (
            mock_proxy.list_messages.call_args.kwargs["q"]
            == "rfc822msgid:msg123@example.com in:anywhere"
        )
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] == "t_orig"

    @patch("email_server.get_gmail_client")
    def test_create_draft_wraps_bare_message_id_in_brackets(self, mock_get_client, client):
        """Gmail's rfc822msgid: operator expects the angle-bracket form."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.return_value = {"id": "r801"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "msg123@example.com",
        })

        assert response.status_code == 200
        assert (
            mock_proxy.list_messages.call_args.kwargs["q"]
            == "rfc822msgid:msg123@example.com in:anywhere"
        )

    @patch("email_server.get_gmail_client")
    def test_create_draft_warns_when_reply_target_not_found(self, mock_get_client, client):
        """If the replied-to message can't be located, the draft is still
        created (RFC headers thread on the recipient's side) but the response
        warns that it is not attached to a Gmail conversation."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {"messages": []}
        mock_proxy.create_draft.return_value = {
            "id": "r802",
            "message": {"id": "m802", "threadId": "t_new_standalone"},
        }

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<gone@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "not attached" in data["message"]
        assert data["thread_attached"] is False
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] is None

    @patch("email_server.get_gmail_client")
    def test_create_draft_survives_thread_lookup_failure(self, mock_get_client, client):
        """Thread resolution is best-effort: a proxy error during the lookup
        must not abort draft creation — the draft is created standalone."""
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.side_effect = ProxyError("proxy 502")
        mock_proxy.create_draft.return_value = {
            "id": "r803",
            "message": {"id": "m803", "threadId": "t_new"},
        }

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["draft_id"] == "r803"
        assert data["thread_attached"] is False
        assert "lookup failed" in data["message"]
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] is None

    @patch("email_server.get_gmail_client")
    def test_create_draft_query_injection_neutralized(self, mock_get_client, client):
        """Only the first Message-ID-shaped token reaches the Gmail query, so
        operators smuggled into in_reply_to cannot match arbitrary messages."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {"messages": []}
        mock_proxy.create_draft.return_value = {"id": "r804"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<nonexistent@x> OR newer_than:1d",
        })

        assert response.status_code == 200
        assert (
            mock_proxy.list_messages.call_args.kwargs["q"]
            == "rfc822msgid:nonexistent@x in:anywhere"
        )

    @patch("email_server.get_gmail_client")
    def test_create_draft_multiple_message_ids_uses_first(self, mock_get_client, client):
        """RFC 5322 allows several msg-ids in In-Reply-To: the first is used
        for the Gmail lookup, but the header keeps the verbatim multi-id
        value — truncating it would drop reply-parent information."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.return_value = {"id": "r805"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<first@example.com> <second@example.com>",
        })

        assert response.status_code == 200
        assert (
            mock_proxy.list_messages.call_args.kwargs["q"]
            == "rfc822msgid:first@example.com in:anywhere"
        )
        raw_msg = mock_proxy.create_draft.call_args[0][0]
        decoded = base64.urlsafe_b64decode(raw_msg).decode("utf-8")
        assert "In-Reply-To: <first@example.com> <second@example.com>" in decoded

    @patch("email_server.get_gmail_client")
    def test_create_draft_unparseable_in_reply_to_skips_lookup(self, mock_get_client, client):
        """Input with no Message-ID-shaped token never reaches the Gmail
        query, and the warning says the id is invalid — not that the
        message could not be found (no lookup happened)."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {"id": "r806"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "not a message id",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_attached"] is False
        assert "no Message-ID usable" in data["message"]
        assert "could not find" not in data["message"]
        mock_proxy.list_messages.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_create_draft_metacharacter_message_id_skips_lookup(self, mock_get_client, client):
        """Ids containing Gmail query metacharacters (quotes, braces) fail
        the strict grammar and never reach the search query."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {"id": "r811"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": '<{a@b} OR "c>',
        })

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_proxy.list_messages.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_create_draft_thread_id_wins_over_attach_to_thread_false(self, mock_get_client, client):
        """attach_to_thread=false disables the lookup, but an explicitly
        supplied thread_id is always honored."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {
            "id": "r812",
            "message": {"id": "m812", "threadId": "t_abc"},
        }

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
            "thread_id": "t_abc",
            "attach_to_thread": False,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["thread_attached"] is True
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] == "t_abc"
        mock_proxy.list_messages.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_create_draft_resolves_thread_from_references(self, mock_get_client, client):
        """With no in_reply_to, the references chain (newest first) is used
        to locate the conversation."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.return_value = {
            "id": "r813",
            "message": {"id": "m813", "threadId": "t_orig"},
        }

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "references": ["<root@example.com>", "<latest@example.com>"],
        })

        assert response.status_code == 200
        data = response.json()
        assert data["thread_attached"] is True
        assert (
            mock_proxy.list_messages.call_args.kwargs["q"]
            == "rfc822msgid:latest@example.com in:anywhere"
        )
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] == "t_orig"

    @patch("email_server.get_gmail_client")
    def test_create_draft_references_only_miss_warns(self, mock_get_client, client):
        """A references-only reply that can't be located gets the same
        not-attached warning as the in_reply_to path."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {"messages": []}
        mock_proxy.create_draft.return_value = {"id": "r814"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "references": ["<gone@example.com>"],
        })

        assert response.status_code == 200
        data = response.json()
        assert data["thread_attached"] is False
        assert "not attached" in data["message"]

    @patch("email_server.get_gmail_client")
    def test_create_draft_bare_references_bracketed_in_header(self, mock_get_client, client):
        """Bare ids in references get the same bracket-wrapping as
        in_reply_to, so the sent reply threads for recipients."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.return_value = {"id": "r815"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "references": ["msg123@example.com"],
        })

        assert response.status_code == 200
        raw_msg = mock_proxy.create_draft.call_args[0][0]
        decoded = base64.urlsafe_b64decode(raw_msg).decode("utf-8")
        assert "References: <msg123@example.com>" in decoded

    @patch("email_server.get_gmail_client")
    def test_create_draft_empty_threadid_stub_treated_as_miss(self, mock_get_client, client):
        """A search stub with a falsy threadId must not report attachment:
        the proxy client drops falsy threadIds from the Gmail request."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": ""}]
        }
        mock_proxy.create_draft.return_value = {"id": "r816"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["thread_attached"] is False
        assert "not attached" in data["message"]
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] is None

    @patch("email_server.get_gmail_client")
    def test_create_draft_null_proxy_result_reports_error(self, mock_get_client, client):
        """A 2xx create response with no draft id is an error the caller can
        react to, not a success with draft_id null."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = None

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Test",
            "body": "Body",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "draft id" in data["error"]

    @patch("email_server.get_gmail_client")
    def test_create_draft_lookup_error_tries_next_candidate(self, mock_get_client, client):
        """A transient failure on one candidate lookup degrades to the next
        candidate, not to a standalone draft."""
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.side_effect = [
            ProxyError("proxy 502"),
            {"messages": [{"id": "orig1", "threadId": "t_orig"}]},
        ]
        mock_proxy.create_draft.return_value = {
            "id": "r817",
            "message": {"id": "m817", "threadId": "t_orig"},
        }

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<gone@example.com>",
            "references": ["<older@example.com>"],
        })

        assert response.status_code == 200
        data = response.json()
        assert data["thread_attached"] is True
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] == "t_orig"

    @patch("email_server.get_gmail_client")
    def test_create_draft_dedups_candidates_after_normalization(self, mock_get_client, client):
        """A bare in_reply_to and its bracketed twin in references are one
        candidate, so the lookup budget reaches older references."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {"messages": []}
        mock_proxy.create_draft.return_value = {"id": "r818"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "msg1@x.com",
            "references": ["<oldest@x.com>", "<r2@x.com>", "<msg1@x.com>"],
        })

        assert response.status_code == 200
        queries = [
            call.kwargs["q"] for call in mock_proxy.list_messages.call_args_list
        ]
        assert queries == [
            "rfc822msgid:msg1@x.com in:anywhere",
            "rfc822msgid:r2@x.com in:anywhere",
            "rfc822msgid:oldest@x.com in:anywhere",
        ]

    @patch("email_server.get_gmail_client")
    def test_create_draft_reference_header_string_newest_first(self, mock_get_client, client):
        """A references item holding a whole header string is searched
        newest-id-first, matching the documented chain order."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {"messages": []}
        mock_proxy.create_draft.return_value = {"id": "r819"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "references": ["<root@x.com> <mid@x.com> <latest@x.com>"],
        })

        assert response.status_code == 200
        first_query = mock_proxy.list_messages.call_args_list[0].kwargs["q"]
        assert first_query == "rfc822msgid:latest@x.com in:anywhere"

    @patch("email_server.get_gmail_client")
    def test_create_draft_timeout_stops_candidate_iteration(self, mock_get_client, client):
        """A hanging proxy (timeout) stops the candidate loop instead of
        serially burning a full timeout per candidate."""
        import httpx
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.side_effect = httpx.ReadTimeout("hang")
        mock_proxy.create_draft.return_value = {"id": "r821"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<a@x.com>",
            "references": ["<b@x.com>", "<c@x.com>"],
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_attached"] is False
        assert "lookup failed" in data["message"]
        assert mock_proxy.list_messages.call_count == 1

    @patch("email_server.get_gmail_client")
    def test_create_draft_retries_standalone_when_attach_rejected(self, mock_get_client, client):
        """Best-effort attach: if Gmail rejects the auto-resolved thread,
        the documented 'draft is still created' promise holds."""
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.side_effect = [
            ProxyError("threading criteria not met"),
            {"id": "r822", "message": {"id": "m822", "threadId": "t_new"}},
        ]

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["draft_id"] == "r822"
        assert data["thread_attached"] is False
        assert "rejected" in data["message"]
        assert mock_proxy.create_draft.call_count == 2
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] is None

    @patch("email_server.get_gmail_client")
    def test_create_draft_no_standalone_retry_for_explicit_thread_id(self, mock_get_client, client):
        """An explicit thread_id expresses intent — a rejected attach is an
        error, not something to silently drop."""
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.side_effect = ProxyError("threading criteria not met")

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "thread_id": "t_abc",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert mock_proxy.create_draft.call_count == 1

    @patch("email_server.get_gmail_client")
    def test_create_draft_no_standalone_retry_on_human_rejection(self, mock_get_client, client):
        """A human-in-the-loop 403 rejects the draft itself — retrying
        standalone would bypass that decision."""
        from proxy_client import ProxyForbiddenError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.side_effect = ProxyForbiddenError("rejected by user")

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert mock_proxy.create_draft.call_count == 1

    @patch("email_server.get_gmail_client")
    def test_create_draft_thread_attached_false_on_thread_mismatch(self, mock_get_client, client):
        """If the result's message landed in a different thread than
        requested, thread_attached must not claim success."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {
            "id": "r823",
            "message": {"id": "m823", "threadId": "t_other"},
        }

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "thread_id": "t_abc",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "t_other"
        assert data["thread_attached"] is False
        # The mismatch must be loud: this is how a proxy that silently
        # drops threadId (the E2E failure on issue #2) gets noticed.
        assert "instead of requested" in data["message"]

    @patch("email_server.get_gmail_client")
    def test_create_draft_caps_lookups_at_three(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {"messages": []}
        mock_proxy.create_draft.return_value = {"id": "r820"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "references": [f"<ref{i}@x.com>" for i in range(5)],
        })

        assert response.status_code == 200
        assert mock_proxy.list_messages.call_count == 3

    @patch("email_server.get_gmail_client")
    def test_create_draft_attach_to_thread_false_skips_resolution(self, mock_get_client, client):
        """attach_to_thread=false keeps a reply-headered draft standalone —
        e.g. a 'New topic (was: Old thread)' draft that references an old
        message without joining its conversation."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {"id": "r807"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "New topic (was: Old thread)",
            "body": "Fresh conversation",
            "in_reply_to": "<msg123@example.com>",
            "attach_to_thread": False,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_attached"] is False
        assert "warning" not in data["message"]
        mock_proxy.list_messages.assert_not_called()
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] is None

    @patch("email_server.get_gmail_client")
    def test_create_draft_empty_thread_id_triggers_resolution(self, mock_get_client, client):
        """An empty-string thread_id is treated as absent, not as an opt-out."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.return_value = {"id": "r808"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "<msg123@example.com>",
            "thread_id": "",
        })

        assert response.status_code == 200
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] == "t_orig"

    @patch("email_server.get_gmail_client")
    def test_create_draft_bare_in_reply_to_header_normalized(self, mock_get_client, client):
        """A bare Message-ID is bracket-wrapped in the RFC In-Reply-To header,
        not just in the Gmail query, so recipients' clients thread the reply."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_messages.return_value = {
            "messages": [{"id": "orig1", "threadId": "t_orig"}]
        }
        mock_proxy.create_draft.return_value = {"id": "r809"}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Reply body",
            "in_reply_to": "msg123@example.com",
        })

        assert response.status_code == 200
        raw_msg = mock_proxy.create_draft.call_args[0][0]
        decoded = base64.urlsafe_b64decode(raw_msg).decode("utf-8")
        assert "In-Reply-To: <msg123@example.com>" in decoded

    @patch("email_server.get_gmail_client")
    def test_create_draft_null_message_in_result(self, mock_get_client, client):
        """A proxy response of message: null must not crash after creation."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.return_value = {"id": "r810", "message": None}

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Test",
            "body": "Body",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_id"] is None

    def test_create_draft_missing_to(self, client):
        response = client.post("/drafts/create", json={
            "subject": "Test",
            "body": "Body",
        })
        assert response.status_code == 422

    def test_create_draft_missing_subject(self, client):
        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "body": "Body",
        })
        assert response.status_code == 422

    def test_create_draft_missing_body(self, client):
        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Test",
        })
        assert response.status_code == 422

    @patch("email_server.get_gmail_client")
    def test_create_draft_proxy_error(self, mock_get_client, client):
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.create_draft.side_effect = ProxyError("Backend error")

        response = client.post("/drafts/create", json={
            "to": ["alice@example.com"],
            "subject": "Test",
            "body": "Body",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Proxy error" in data["error"]


# =============================================================================
# LIST DRAFTS ENDPOINT TESTS
# =============================================================================


class TestMessageIdNormalization:
    """Tests for the strict Message-ID grammar in gmail_utils."""

    def test_bracketed_id_passes_through(self):
        from gmail_utils import normalize_message_id
        assert normalize_message_id("<a@example.com>") == "<a@example.com>"

    def test_bare_id_is_wrapped(self):
        from gmail_utils import normalize_message_id
        assert normalize_message_id("a@example.com") == "<a@example.com>"

    def test_multi_id_returns_first(self):
        from gmail_utils import normalize_message_id
        assert normalize_message_id("<a@x.com> <b@y.com>") == "<a@x.com>"

    def test_garbage_returns_none(self):
        from gmail_utils import normalize_message_id
        assert normalize_message_id("not a message id") is None

    @pytest.mark.parametrize("bad", ['<a@b"c>', "<{a@b}>", "<a(b)@c.com>"])
    def test_gmail_metacharacters_rejected(self, bad):
        """Quotes, braces, and parens would alter the meaning of the Gmail
        query the id is interpolated into."""
        from gmail_utils import normalize_message_id
        assert normalize_message_id(bad) is None

    def test_reply_header_bare_id_wrapped(self):
        from gmail_utils import normalize_reply_header
        assert normalize_reply_header("a@example.com") == "<a@example.com>"

    def test_reply_header_multi_id_kept_verbatim(self):
        from gmail_utils import normalize_reply_header
        value = "<first@x.com> <second@y.com>"
        assert normalize_reply_header(value) == value

    def test_reply_header_garbage_kept_verbatim(self):
        from gmail_utils import normalize_reply_header
        assert normalize_reply_header("not a message id") == "not a message id"

    def test_extract_message_ids_in_order(self):
        from gmail_utils import extract_message_ids
        assert extract_message_ids("<a@x.com> <b@y.com>") == ["<a@x.com>", "<b@y.com>"]

    def test_extract_message_ids_bare(self):
        from gmail_utils import extract_message_ids
        assert extract_message_ids("a@x.com") == ["<a@x.com>"]

    def test_extract_message_ids_none(self):
        from gmail_utils import extract_message_ids
        assert extract_message_ids("not a message id") == []

    def test_extract_message_ids_mixed_bracketed_and_bare(self):
        from gmail_utils import extract_message_ids
        assert extract_message_ids("<old@x.com> newest@y.com") == [
            "<old@x.com>",
            "<newest@y.com>",
        ]

    def test_extract_message_ids_multiple_bare(self):
        from gmail_utils import extract_message_ids
        assert extract_message_ids("a@x.com b@y.com") == ["<a@x.com>", "<b@y.com>"]

    def test_extract_message_ids_domain_literal(self):
        """Domain-literal ids (RFC 5322) produced by some MTAs are usable."""
        from gmail_utils import extract_message_ids
        assert extract_message_ids("<abc@[192.168.1.1]>") == ["<abc@[192.168.1.1]>"]

    def test_pipe_metacharacter_rejected(self):
        """'|' is Gmail's OR operator and must not reach the query."""
        from gmail_utils import normalize_message_id
        assert normalize_message_id("<abc|def@x.com>") is None

    def test_reply_header_multiple_bare_ids_wrapped(self):
        from gmail_utils import normalize_reply_header
        assert normalize_reply_header("a@x.com b@y.com") == "<a@x.com> <b@y.com>"


class TestListDraftsEndpoint:
    """Tests for GET /drafts."""

    @patch("email_server.get_gmail_client")
    def test_list_drafts_success(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_drafts.return_value = {
            "drafts": [{"id": "r123"}, {"id": "r456"}],
        }
        mock_proxy.get_draft.side_effect = [
            {
                "id": "r123",
                "message": {
                    "snippet": "Hello...",
                    "payload": {
                        "headers": [
                            {"name": "To", "value": "alice@example.com"},
                            {"name": "Subject", "value": "Draft 1"},
                        ],
                    },
                },
            },
            {
                "id": "r456",
                "message": {
                    "snippet": "Meeting notes...",
                    "payload": {
                        "headers": [
                            {"name": "To", "value": "bob@example.com"},
                            {"name": "Subject", "value": "Draft 2"},
                        ],
                    },
                },
            },
        ]

        response = client.get("/drafts")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["drafts"]) == 2
        assert data["drafts"][0]["id"] == "r123"
        assert data["drafts"][0]["subject"] == "Draft 1"
        assert "alice@example.com" in data["drafts"][0]["to"]

    @patch("email_server.get_gmail_client")
    def test_list_drafts_empty(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.list_drafts.return_value = {"resultSizeEstimate": 0}

        response = client.get("/drafts")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["drafts"] == []


# =============================================================================
# GET DRAFT ENDPOINT TESTS
# =============================================================================


class TestGetDraftEndpoint:
    """Tests for GET /drafts/{draft_id}."""

    @patch("email_server.get_gmail_client")
    def test_get_draft_success(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.return_value = {
            "id": "r123",
            "message": {
                "threadId": "t789",
                "payload": {
                    "headers": [
                        {"name": "To", "value": "alice@example.com"},
                        {"name": "Subject", "value": "Test Draft"},
                        {"name": "Cc", "value": "cc@example.com"},
                        {"name": "In-Reply-To", "value": "<msg@example.com>"},
                    ],
                    "body": {
                        "data": base64.urlsafe_b64encode(b"Draft body text").decode(),
                    },
                },
            },
        }

        response = client.get("/drafts/r123")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["draft_id"] == "r123"
        assert "alice@example.com" in data["to"]
        assert data["subject"] == "Test Draft"
        assert data["body"] == "Draft body text"
        assert data["in_reply_to"] == "<msg@example.com>"
        assert data["thread_id"] == "t789"

    @patch("email_server.get_gmail_client")
    def test_get_draft_quoted_display_name_not_split(self, mock_get_client, client):
        """Recipient display names containing commas parse as one address."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.return_value = {
            "id": "r124",
            "message": {
                "payload": {
                    "headers": [
                        {"name": "To", "value": '"Doe, John" <j@x.com>, jane@y.com'},
                        {"name": "Subject", "value": "Test Draft"},
                    ],
                    "body": {
                        "data": base64.urlsafe_b64encode(b"Draft body text").decode(),
                    },
                },
            },
        }

        response = client.get("/drafts/r124")
        data = response.json()
        assert data["success"] is True
        assert data["to"] == ['"Doe, John" <j@x.com>', "jane@y.com"]

    @patch("email_server.get_gmail_client")
    def test_get_draft_proxy_error(self, mock_get_client, client):
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.side_effect = ProxyError("Not found")

        response = client.get("/drafts/r999")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Proxy error" in data["error"]


# =============================================================================
# UPDATE DRAFT ENDPOINT TESTS
# =============================================================================


class TestUpdateDraftEndpoint:
    """Tests for POST /drafts/{draft_id}/update."""

    @patch("email_server.get_gmail_client")
    def test_update_draft_success(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.return_value = {
            "id": "r123",
            "message": {"id": "msg456", "threadId": "t_keep"},
        }
        mock_proxy.update_draft.return_value = {
            "id": "r123",
            "message": {"id": "msg456"},
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["draft_id"] == "r123"

        mock_proxy.update_draft.assert_called_once()
        call_args = mock_proxy.update_draft.call_args
        assert call_args[0][0] == "r123"
        raw_msg = call_args[0][1]
        decoded = base64.urlsafe_b64decode(raw_msg).decode("utf-8")
        assert "bob@example.com" in decoded
        assert "Updated subject" in decoded

    @patch("email_server.get_gmail_client")
    def test_update_draft_id_mismatch_warns_and_reports_new_id(self, mock_get_client, client):
        """Issue #3 documented drafts.update reissuing a new draft id while
        the response still looked like a success. If that ever recurs, the
        caller must be told the id changed and given the new one to use --
        not silently handed back the stale id it asked for."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.update_draft.return_value = {
            "id": "r999-new",
            "message": {"id": "msg456", "threadId": "t_keep"},
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["draft_id"] == "r999-new"
        assert "r999-new" in data["message"]
        assert "r123" in data["message"]
        assert "warning" in data["message"]

    @patch("email_server.get_gmail_client")
    def test_update_draft_id_match_no_warning(self, mock_get_client, client):
        """The common case -- proxy echoes back the same draft id -- must
        not be flagged as a mismatch."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.update_draft.return_value = {
            "id": "r123",
            "message": {"id": "msg456", "threadId": "t_keep"},
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        data = response.json()
        assert data["draft_id"] == "r123"
        assert "warning" not in data["message"]

    @patch("email_server.get_gmail_client")
    def test_update_draft_no_id_in_result_keeps_requested_id(self, mock_get_client, client):
        """If the update result carries no id at all, fall back to the
        requested path id rather than reporting None -- there's nothing to
        compare against, so no mismatch warning either."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.update_draft.return_value = {"message": {"id": "msg456"}}

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        data = response.json()
        assert data["draft_id"] == "r123"
        assert "warning" not in data["message"]

    @patch("email_server.get_gmail_client")
    def test_update_draft_content_mismatch_subject_warns(self, mock_get_client, client):
        """Issue #3's Case 2 was a draft gutted to a different subject/body
        behind a success response. When the update result embeds the
        message's headers, cross-check the Subject against what was sent."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.update_draft.return_value = {
            "id": "r123",
            "message": {
                "id": "msg456",
                "threadId": "t_keep",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Something else entirely"},
                    ]
                },
            },
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        data = response.json()
        assert data["success"] is True
        assert "warning" in data["message"]
        assert "Updated subject" in data["message"]
        assert "Something else entirely" in data["message"]

    @patch("email_server.get_gmail_client")
    def test_update_draft_content_match_subject_no_warning(self, mock_get_client, client):
        """A result whose embedded Subject header matches the request must
        not be flagged."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.update_draft.return_value = {
            "id": "r123",
            "message": {
                "id": "msg456",
                "threadId": "t_keep",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Updated subject"},
                    ]
                },
            },
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        data = response.json()
        assert data["success"] is True
        assert "warning" not in data["message"]

    @patch("email_server.get_gmail_client")
    def test_update_draft_no_embedded_headers_no_content_warning(self, mock_get_client, client):
        """A sparse update result with no embedded message headers cannot be
        content-checked -- absence of headers is not itself suspicious, so
        no warning should be raised (this is the shape most of the other
        update tests' mocks already use)."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.update_draft.return_value = {"id": "r123"}

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        data = response.json()
        assert data["success"] is True
        assert "warning" not in data["message"]

    @patch("email_server.get_gmail_client")
    def test_update_draft_with_thread_id(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.update_draft.return_value = {"id": "r123"}

        response = client.post("/drafts/r123/update", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Updated reply",
            "thread_id": "thread_abc",
        })

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert mock_proxy.update_draft.call_args.kwargs["thread_id"] == "thread_abc"
        mock_proxy.list_messages.assert_not_called()
        mock_proxy.get_draft.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_update_draft_preserves_existing_thread_without_threading_fields(self, mock_get_client, client):
        """drafts.update replaces the whole message resource, so the current
        threadId is re-sent — a plain body edit never detaches the draft."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.return_value = {
            "id": "r123",
            "message": {"id": "msg456", "threadId": "t_keep"},
        }
        mock_proxy.update_draft.return_value = {
            "id": "r123",
            "message": {"id": "msg456", "threadId": "t_keep"},
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_attached"] is True
        assert mock_proxy.update_draft.call_args.kwargs["thread_id"] == "t_keep"
        assert "warning" not in data["message"]

    @patch("email_server.get_gmail_client")
    def test_update_draft_fails_when_current_thread_unreadable(self, mock_get_client, client):
        """If the current thread can't be read, the update fails — even a
        successful reply lookup could relocate a deliberately detached or
        moved draft, so there is no lookup rescue on update."""
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.side_effect = ProxyError("proxy 502")

        response = client.post("/drafts/r123/update", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Updated reply",
            "in_reply_to": "<msg123@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Proxy error" in data["error"]
        mock_proxy.list_messages.assert_not_called()
        mock_proxy.update_draft.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_update_draft_non_dict_message_in_result(self, mock_get_client, client):
        """A 2xx update result whose 'message' is not a dict (e.g. an
        acknowledgment string) must not turn a successful write into a
        reported failure."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.return_value = {
            "id": "r123",
            "message": {"id": "msg456", "threadId": "t_keep"},
        }
        mock_proxy.update_draft.return_value = {"message": "ok"}

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_id"] == "t_keep"

    @patch("email_server.get_gmail_client")
    def test_update_draft_fails_when_current_thread_lookup_errors(self, mock_get_client, client):
        """If the draft's current thread can't be read, the update fails
        rather than proceeding and silently detaching the draft."""
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.side_effect = ProxyError("proxy 502")

        response = client.post("/drafts/r123/update", json={
            "to": ["bob@example.com"],
            "subject": "Updated subject",
            "body": "Updated body",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Proxy error" in data["error"]
        mock_proxy.update_draft.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_update_draft_attach_to_thread_false_detaches(self, mock_get_client, client):
        """attach_to_thread=false on update is the deliberate way to detach
        a draft: no lookup, no preservation, no threadId sent."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.update_draft.return_value = {
            "id": "r123",
            "message": {"id": "msg456", "threadId": "t_new"},
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["alice@example.com"],
            "subject": "New topic (was: Old thread)",
            "body": "Fresh conversation",
            "in_reply_to": "<msg123@example.com>",
            "attach_to_thread": False,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_attached"] is False
        assert mock_proxy.update_draft.call_args.kwargs["thread_id"] is None
        mock_proxy.list_messages.assert_not_called()
        mock_proxy.get_draft.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_update_draft_bare_in_reply_to_header_normalized(self, mock_get_client, client):
        """Update applies the same bracket-wrapping as create."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.return_value = {
            "id": "r123",
            "message": {"id": "m123", "threadId": "t_keep"},
        }
        mock_proxy.update_draft.return_value = {"id": "r123"}

        response = client.post("/drafts/r123/update", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Updated reply",
            "in_reply_to": "msg123@example.com",
        })

        assert response.status_code == 200
        raw_msg = mock_proxy.update_draft.call_args[0][1]
        decoded = base64.urlsafe_b64decode(raw_msg).decode("utf-8")
        assert "In-Reply-To: <msg123@example.com>" in decoded

    @patch("email_server.get_gmail_client")
    def test_update_draft_prefers_current_thread_over_lookup(self, mock_get_client, client):
        """The draft's current thread embodies past threading decisions
        (including a deliberate detach or explicit thread_id), so an update
        echoing in_reply_to must not re-resolve and relocate the draft."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.return_value = {
            "id": "r123",
            "message": {"id": "m123", "threadId": "t_keep"},
        }
        mock_proxy.update_draft.return_value = {
            "id": "r123",
            "message": {"id": "m123", "threadId": "t_keep"},
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Updated reply",
            "in_reply_to": "<msg123@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["thread_id"] == "t_keep"
        assert data["thread_attached"] is True
        assert mock_proxy.update_draft.call_args.kwargs["thread_id"] == "t_keep"
        mock_proxy.list_messages.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_update_draft_never_runs_reply_lookup(self, mock_get_client, client):
        """Updates never re-resolve reply headers, even when the draft has
        no current thread to preserve — Gmail gives every message a
        threadId, so a lookup here would be unreachable in production and
        moving a draft must be explicit (thread_id)."""
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.get_draft.return_value = {
            "id": "r123",
            "message": {"id": "m123"},
        }
        mock_proxy.update_draft.return_value = {
            "id": "r123",
            "message": {"id": "m123", "threadId": "t_new"},
        }

        response = client.post("/drafts/r123/update", json={
            "to": ["alice@example.com"],
            "subject": "Re: Thread",
            "body": "Updated reply",
            "in_reply_to": "<msg123@example.com>",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_proxy.list_messages.assert_not_called()
        assert mock_proxy.update_draft.call_args.kwargs["thread_id"] is None

    def test_update_draft_missing_fields(self, client):
        response = client.post("/drafts/r123/update", json={
            "subject": "Test",
        })
        assert response.status_code == 422


# =============================================================================
# DELETE DRAFT ENDPOINT TESTS
# =============================================================================


class TestDeleteDraftEndpoint:
    """Tests for DELETE /drafts/{draft_id}."""

    @patch("email_server.get_gmail_client")
    def test_delete_draft_success(self, mock_get_client, client):
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.delete_draft.return_value = None

        response = client.delete("/drafts/r123")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "r123" in data["message"]

    @patch("email_server.get_gmail_client")
    def test_delete_draft_error(self, mock_get_client, client):
        from proxy_client import ProxyError
        mock_proxy = AsyncMock()
        mock_get_client.return_value = mock_proxy
        mock_proxy.delete_draft.side_effect = ProxyError("Draft not found")

        response = client.delete("/drafts/r999")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Proxy error" in data["message"]
