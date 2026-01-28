"""Unit tests for email_server with mocked Gmail API and LLM."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from email_server import app


@pytest.fixture
def client():
    return TestClient(app)


# Mock Gmail message data
MOCK_MESSAGE_LIST_RESPONSE = {
    "messages": [
        {"id": "msg123", "threadId": "thread123"},
        {"id": "msg456", "threadId": "thread456"},
    ]
}

MOCK_MESSAGE_METADATA = {
    "id": "msg123",
    "threadId": "thread123",
    "labelIds": ["INBOX", "UNREAD"],
    "snippet": "Thanks for reaching out. I wanted to let you know that...",
    "payload": {
        "headers": [
            {"name": "From", "value": "Sender Name <sender@example.com>"},
            {"name": "Subject", "value": "Re: Important Topic"},
            {"name": "Date", "value": "Jan 25, 2026 3:42 PM"},
        ]
    }
}

MOCK_MESSAGE_FULL = {
    "id": "msg123",
    "threadId": "thread123",
    "labelIds": ["INBOX", "UNREAD"],
    "payload": {
        "headers": [
            {"name": "From", "value": "Sender Name <sender@example.com>"},
            {"name": "Subject", "value": "Re: Important Topic"},
            {"name": "Date", "value": "Jan 25, 2026 3:42 PM"},
        ],
        "body": {
            # base64url encoded "Hello, this is a test email body."
            "data": "SGVsbG8sIHRoaXMgaXMgYSB0ZXN0IGVtYWlsIGJvZHku"
        }
    }
}


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "2.0"


class TestSearchEndpoint:
    @patch("email_server.get_gmail_service")
    def test_search_basic(self, mock_get_service, client):
        # Setup mock
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = MOCK_MESSAGE_LIST_RESPONSE
        mock_messages.return_value.get.return_value.execute.return_value = MOCK_MESSAGE_METADATA

        # Make request
        response = client.post("/search", json={"limit": 10})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["error"] is None
        assert len(data["messages"]) == 2

    @patch("email_server.get_gmail_service")
    def test_search_with_filters(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = MOCK_MESSAGE_LIST_RESPONSE
        mock_messages.return_value.get.return_value.execute.return_value = MOCK_MESSAGE_METADATA

        response = client.post("/search", json={
            "from_addr": "sender@example.com",
            "subject": "Important",
            "folder": "INBOX",
            "limit": 5
        })
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

        # Verify list was called with correct params
        call_args = mock_messages.return_value.list.call_args
        assert call_args[1]["q"] == "from:sender@example.com subject:Important"
        assert call_args[1]["labelIds"] == ["INBOX"]
        assert call_args[1]["maxResults"] == 5

    @patch("email_server.get_gmail_service")
    def test_search_with_date_filters(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = {"messages": []}

        response = client.post("/search", json={
            "since": "2026/01/20",
            "before": "2026/01/27",
            "limit": 10
        })
        assert response.status_code == 200

        call_args = mock_messages.return_value.list.call_args
        assert "after:2026/01/20" in call_args[1]["q"]
        assert "before:2026/01/27" in call_args[1]["q"]

    @patch("email_server.get_gmail_service")
    def test_search_returns_correct_structure(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg123", "threadId": "thread123"}]
        }
        mock_messages.return_value.get.return_value.execute.return_value = MOCK_MESSAGE_METADATA

        response = client.post("/search", json={"limit": 1})
        data = response.json()

        assert data["success"] is True
        msg = data["messages"][0]
        assert msg["id"] == "msg123"
        assert msg["date"] == "Jan 25, 2026 3:42 PM"
        assert msg["from_addr"] == "Sender Name <sender@example.com>"
        assert msg["subject"] == "Re: Important Topic"
        assert msg["snippet"] == "Thanks for reaching out. I wanted to let you know that..."
        assert "INBOX" in msg["labels"]
        assert "UNREAD" in msg["labels"]

    @patch("email_server.get_gmail_service")
    def test_search_handles_error(self, mock_get_service, client):
        mock_get_service.side_effect = Exception("Gmail API error")

        response = client.post("/search", json={"limit": 10})
        assert response.status_code == 200  # Returns 200 with error in body

        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Gmail API error"
        assert data["messages"] == []


class TestSummarizeEndpoint:
    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_summarize_basic(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = MOCK_MESSAGE_FULL

        mock_llm.return_value = "The sender is thanking you for the conversation."

        response = client.post("/summarize", json={"message_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["answer"] == "The sender is thanking you for the conversation."
        assert data["error"] is None

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_summarize_uses_correct_system_prompt(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = MOCK_MESSAGE_FULL

        mock_llm.return_value = "Summary here"

        client.post("/summarize", json={"message_id": "msg123"})

        # Verify correct system prompt was used
        call_args = mock_llm.call_args
        system_prompt = call_args[0][0]
        assert "summarizing an email" in system_prompt
        assert "untrusted data" in system_prompt

    @patch("email_server.get_gmail_service")
    def test_summarize_handles_gmail_error(self, mock_get_service, client):
        mock_get_service.side_effect = Exception("Gmail API error")

        response = client.post("/summarize", json={"message_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is False
        assert "Gmail API error" in data["error"]


class TestAskAboutEndpoint:
    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_ask_about_basic(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = MOCK_MESSAGE_FULL

        mock_llm.return_value = "No, the sender did not mention a specific dollar amount."

        response = client.post("/ask-about", json={
            "message_id": "msg123",
            "question": "Did they mention a dollar amount?"
        })
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "dollar amount" in data["answer"]
        assert data["error"] is None

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_ask_about_includes_question_in_prompt(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = MOCK_MESSAGE_FULL

        mock_llm.return_value = "Answer here"

        client.post("/ask-about", json={
            "message_id": "msg123",
            "question": "What is the main request?"
        })

        # Verify question was included in user content
        call_args = mock_llm.call_args
        user_content = call_args[0][1]
        assert "Question: What is the main request?" in user_content


class TestMarkReadEndpoint:
    @patch("email_server.get_gmail_service_with_modify")
    def test_mark_read_success(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        response = client.post("/mark-read", json={"email_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Email marked as read"

        # Verify modify was called with correct params
        mock_service.users.return_value.messages.return_value.modify.assert_called_once()
        call_kwargs = mock_service.users.return_value.messages.return_value.modify.call_args[1]
        assert call_kwargs["id"] == "msg123"
        assert call_kwargs["body"] == {"removeLabelIds": ["UNREAD"]}

    @patch("email_server.get_gmail_service_with_modify")
    def test_mark_read_handles_error(self, mock_get_service, client):
        mock_get_service.side_effect = Exception("Gmail API error")

        response = client.post("/mark-read", json={"email_id": "msg123"})
        assert response.status_code == 500


class TestApplyLabelEndpoint:
    @patch("email_server.get_gmail_service_with_modify")
    def test_apply_label_success(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        response = client.post("/apply-label", json={
            "email_id": "msg123",
            "label_name": "STARRED"
        })
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "STARRED" in data["message"]

        # Verify modify was called with correct params
        call_kwargs = mock_service.users.return_value.messages.return_value.modify.call_args[1]
        assert call_kwargs["body"] == {"addLabelIds": ["STARRED"]}


class TestArchiveEndpoint:
    @patch("email_server.get_gmail_service_with_modify")
    def test_archive_success(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        response = client.post("/archive", json={"email_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Email archived"

        # Verify modify was called with correct params
        call_kwargs = mock_service.users.return_value.messages.return_value.modify.call_args[1]
        assert call_kwargs["body"] == {"removeLabelIds": ["INBOX"]}


class TestGmailUtils:
    """Test the utility functions in gmail_utils.py"""

    def test_get_header_found(self):
        from gmail_utils import get_header
        headers = [
            {"name": "From", "value": "sender@example.com"},
            {"name": "Subject", "value": "Test Subject"},
        ]
        assert get_header(headers, "From") == "sender@example.com"
        assert get_header(headers, "subject") == "Test Subject"  # case insensitive

    def test_get_header_not_found(self):
        from gmail_utils import get_header
        headers = [{"name": "From", "value": "sender@example.com"}]
        assert get_header(headers, "Subject") == ""

    def test_decode_body_simple(self):
        from gmail_utils import decode_body
        payload = {
            "body": {
                # base64url encoded "Hello World"
                "data": "SGVsbG8gV29ybGQ="
            }
        }
        assert decode_body(payload) == "Hello World"

    def test_decode_body_multipart(self):
        from gmail_utils import decode_body
        payload = {
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "UGxhaW4gdGV4dCBib2R5"}  # "Plain text body"
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": "PGh0bWw+PC9odG1sPg=="}  # "<html></html>"
                }
            ]
        }
        assert decode_body(payload) == "Plain text body"

    def test_decode_body_no_content(self):
        from gmail_utils import decode_body
        payload = {}
        assert decode_body(payload) == "(Could not extract text content)"


class TestBuildGmailQuery:
    def test_build_query_empty(self):
        from email_server import build_gmail_query, SearchRequest
        request = SearchRequest()
        assert build_gmail_query(request) == ""

    def test_build_query_single_filter(self):
        from email_server import build_gmail_query, SearchRequest
        request = SearchRequest(from_addr="test@example.com")
        assert build_gmail_query(request) == "from:test@example.com"

    def test_build_query_multiple_filters(self):
        from email_server import build_gmail_query, SearchRequest
        request = SearchRequest(
            from_addr="sender@example.com",
            subject="meeting",
            since="2026/01/20"
        )
        query = build_gmail_query(request)
        assert "from:sender@example.com" in query
        assert "subject:meeting" in query
        assert "after:2026/01/20" in query

    def test_build_query_with_raw_query(self):
        from email_server import build_gmail_query, SearchRequest
        request = SearchRequest(
            from_addr="sender@example.com",
            query="is:unread"
        )
        query = build_gmail_query(request)
        assert "from:sender@example.com" in query
        assert "is:unread" in query
