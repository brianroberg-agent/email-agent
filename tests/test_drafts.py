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
        """thread_id is forwarded so the draft attaches to its Gmail conversation."""
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
        assert response.json()["success"] is True
        assert mock_proxy.create_draft.call_args.kwargs["thread_id"] == "thread_abc"

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
