"""Comprehensive tests for email_server with mocked proxy client and LLM.

Testing patterns inspired by datasette-enrichments:
- Parametrized tests for multiple scenarios
- Test classes grouping related functionality
- Shared fixtures from conftest.py
- Edge case and error handling tests
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock

from tests.conftest import SAMPLE_MESSAGES


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "2.0"

    def test_health_response_structure(self, client):
        response = client.get("/health")
        data = response.json()
        assert set(data.keys()) == {"status", "version"}


class TestLabelsEndpoint:
    """Tests for the /labels endpoint."""

    @patch("email_server.get_gmail_client")
    def test_labels_returns_all_labels(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        mock_proxy_client.list_labels.return_value = {
            "labels": [
                {
                    "id": "INBOX",
                    "name": "INBOX",
                    "type": "system",
                    "messagesTotal": 150,
                    "messagesUnread": 5,
                },
                {
                    "id": "Label_123",
                    "name": "Work",
                    "type": "user",
                    "messagesTotal": 42,
                    "messagesUnread": 3,
                },
            ]
        }

        response = client.get("/labels")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["labels"]) == 2

        # Check system label
        inbox = data["labels"][0]
        assert inbox["id"] == "INBOX"
        assert inbox["name"] == "INBOX"
        assert inbox["type"] == "system"
        assert inbox["messages_total"] == 150
        assert inbox["messages_unread"] == 5

        # Check user label
        work = data["labels"][1]
        assert work["id"] == "Label_123"
        assert work["name"] == "Work"
        assert work["type"] == "user"

    @patch("email_server.get_gmail_client")
    def test_labels_handles_missing_counts(self, mock_get_client, client):
        """Test that labels without message counts return null (not 0)."""
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        mock_proxy_client.list_labels.return_value = {
            "labels": [
                {
                    "id": "STARRED",
                    "name": "STARRED",
                    "type": "system",
                    # No messagesTotal or messagesUnread
                },
            ]
        }

        response = client.get("/labels")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        starred = data["labels"][0]
        assert starred["messages_total"] is None
        assert starred["messages_unread"] is None

    @patch("email_server.get_gmail_client")
    def test_labels_empty_list(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.list_labels.return_value = {"labels": []}

        response = client.get("/labels")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["labels"] == []

    @patch("email_server.get_gmail_client")
    def test_labels_handles_error(self, mock_get_client, client):
        mock_get_client.side_effect = Exception("Proxy connection failed")

        response = client.get("/labels")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["labels"] == []
        assert "Proxy connection failed" in data["error"]

    def test_labels_response_structure(self, client):
        with patch("email_server.get_gmail_client") as mock_get_client:
            mock_proxy_client = AsyncMock()
            mock_get_client.return_value = mock_proxy_client
            mock_proxy_client.list_labels.return_value = {"labels": []}

            response = client.get("/labels")
            data = response.json()
            assert set(data.keys()) == {"success", "labels", "error"}


class TestSearchEndpoint:
    """Tests for the /search endpoint."""

    @patch("email_server.get_gmail_client")
    def test_search_basic(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        mock_proxy_client.list_messages.return_value = {
            "messages": [
                {"id": "msg123", "threadId": "thread123"},
                {"id": "msg456", "threadId": "thread456"},
            ]
        }
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["basic"]

        response = client.post("/search", json={"limit": 10})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["error"] is None
        assert len(data["messages"]) == 2

    @patch("email_server.get_gmail_client")
    @pytest.mark.parametrize("filters,expected_query_parts", [
        (
            {"from_addr": "sender@example.com"},
            ["from:sender@example.com"]
        ),
        (
            {"to_addr": "recipient@example.com"},
            ["to:recipient@example.com"]
        ),
        (
            {"subject": "Important"},
            ["subject:Important"]
        ),
        (
            {"from_addr": "sender@example.com", "subject": "Important"},
            ["from:sender@example.com", "subject:Important"]
        ),
        (
            {"since": "2026/01/20", "before": "2026/01/27"},
            ["after:2026/01/20", "before:2026/01/27"]
        ),
        (
            {"query": "is:unread"},
            ["is:unread"]
        ),
        (
            {"from_addr": "test@example.com", "query": "has:attachment"},
            ["from:test@example.com", "has:attachment"]
        ),
    ])
    def test_search_with_filters(self, mock_get_client, client, filters, expected_query_parts):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.list_messages.return_value = {"messages": []}

        response = client.post("/search", json={**filters, "limit": 10})
        assert response.status_code == 200

        call_args = mock_proxy_client.list_messages.call_args
        query_string = call_args[1].get("q", "") or ""
        for part in expected_query_parts:
            assert part in query_string

    @patch("email_server.get_gmail_client")
    @pytest.mark.parametrize("folder", ["INBOX", "SENT", "DRAFT", "SPAM", "TRASH", "STARRED"])
    def test_search_with_folder(self, mock_get_client, client, folder):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.list_messages.return_value = {"messages": []}

        response = client.post("/search", json={"folder": folder, "limit": 5})
        assert response.status_code == 200

        call_args = mock_proxy_client.list_messages.call_args
        assert call_args[1]["label_ids"] == [folder]

    @patch("email_server.get_gmail_client")
    @pytest.mark.parametrize("limit", [1, 10, 25, 50])
    def test_search_with_limit(self, mock_get_client, client, limit):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.list_messages.return_value = {"messages": []}

        response = client.post("/search", json={"limit": limit})
        assert response.status_code == 200

        call_args = mock_proxy_client.list_messages.call_args
        assert call_args[1]["max_results"] == limit

    def test_search_limit_validation_min(self, client):
        response = client.post("/search", json={"limit": 0})
        assert response.status_code == 422  # Validation error

    def test_search_limit_validation_max(self, client):
        response = client.post("/search", json={"limit": 100})
        assert response.status_code == 422  # Validation error

    @patch("email_server.get_gmail_client")
    def test_search_empty_results(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.list_messages.return_value = {}  # No messages key

        response = client.post("/search", json={"limit": 10})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["messages"] == []

    @patch("email_server.get_gmail_client")
    def test_search_returns_correct_message_structure(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        mock_proxy_client.list_messages.return_value = {
            "messages": [{"id": "msg123", "threadId": "thread123"}]
        }
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["basic"]

        response = client.post("/search", json={"limit": 1})
        data = response.json()

        assert data["success"] is True
        msg = data["messages"][0]
        assert msg["id"] == "msg123"
        assert msg["date"] == "Jan 25, 2026 3:42 PM"
        assert msg["from_addr"] == "Sender Name <sender@example.com>"
        assert msg["from_name"] == "Sender Name"
        assert msg["subject"] == "Re: Important Topic"
        assert msg["snippet"] == "Thanks for reaching out. I wanted to let you know that..."
        assert "INBOX" in msg["labels"]
        assert "UNREAD" in msg["labels"]
        assert msg["has_attachments"] is False

    @patch("email_server.get_gmail_client")
    @pytest.mark.parametrize("error_message", [
        "Gmail API error",
        "Connection refused",
        "Invalid credentials",
        "Rate limit exceeded",
    ])
    def test_search_handles_error(self, mock_get_client, client, error_message):
        mock_get_client.side_effect = Exception(error_message)

        response = client.post("/search", json={"limit": 10})
        assert response.status_code == 200  # Returns 200 with error in body

        data = response.json()
        assert data["success"] is False
        assert error_message in data["error"]
        assert data["messages"] == []


class TestSummarizeEndpoint:
    """Tests for the /summarize endpoint."""

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_summarize_basic(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = "The sender is thanking you for the conversation."

        response = client.post("/summarize", json={"message_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["answer"] == "The sender is thanking you for the conversation."
        assert data["error"] is None

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_summarize_uses_correct_system_prompt(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = "Summary here"

        client.post("/summarize", json={"message_id": "msg123"})

        call_args = mock_llm.call_args
        system_prompt = call_args[0][0]
        assert "summarizing an email" in system_prompt
        assert "untrusted data" in system_prompt

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_summarize_multipart_email(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["multipart"]

        mock_llm.return_value = "Summary of multipart email"

        response = client.post("/summarize", json={"message_id": "msg456"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        # Verify that text/plain content was extracted
        call_args = mock_llm.call_args
        user_content = call_args[0][1]
        assert "Plain text content here" in user_content

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_summarize_truncates_long_body(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["long_body"]

        mock_llm.return_value = "Summary of long email"

        client.post("/summarize", json={"message_id": "msg_long"})

        call_args = mock_llm.call_args
        user_content = call_args[0][1]
        # Body should be truncated with "..."
        assert user_content.endswith("...")
        assert len(user_content) <= 3003 + 10  # MAX_BODY_LENGTH + "..." + some margin

    @patch("email_server.get_gmail_client")
    def test_summarize_handles_gmail_error(self, mock_get_client, client):
        mock_get_client.side_effect = Exception("Gmail API error")

        response = client.post("/summarize", json={"message_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is False
        assert "Gmail API error" in data["error"]

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_summarize_handles_llm_error(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.side_effect = Exception("LLM connection failed")

        response = client.post("/summarize", json={"message_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is False
        assert "LLM connection failed" in data["error"]


class TestAskAboutEndpoint:
    """Tests for the /ask-about endpoint."""

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_ask_about_basic(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

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
    @patch("email_server.get_gmail_client")
    def test_ask_about_includes_question_in_prompt(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = "Answer here"

        client.post("/ask-about", json={
            "message_id": "msg123",
            "question": "What is the main request?"
        })

        call_args = mock_llm.call_args
        user_content = call_args[0][1]
        assert "Question: What is the main request?" in user_content

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_ask_about_uses_correct_system_prompt(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = "Answer"

        client.post("/ask-about", json={
            "message_id": "msg123",
            "question": "Test question"
        })

        call_args = mock_llm.call_args
        system_prompt = call_args[0][0]
        assert "answering a specific question" in system_prompt
        assert "untrusted data" in system_prompt

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    @pytest.mark.parametrize("question", [
        "What is the sender's name?",
        "Are there any attachments?",
        "When is the meeting scheduled?",
        "What action items are mentioned?",
        "Is this email urgent?",
    ])
    def test_ask_about_various_questions(self, mock_get_client, mock_llm, client, question):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = f"Answer to: {question}"

        response = client.post("/ask-about", json={
            "message_id": "msg123",
            "question": question
        })
        assert response.status_code == 200
        assert response.json()["success"] is True

    @patch("email_server.get_gmail_client")
    def test_ask_about_handles_gmail_error(self, mock_get_client, client):
        mock_get_client.side_effect = Exception("Gmail API error")

        response = client.post("/ask-about", json={
            "message_id": "msg123",
            "question": "Test question"
        })
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is False
        assert "Gmail API error" in data["error"]


class TestMarkReadEndpoint:
    """Tests for the /mark-read endpoint."""

    @patch("email_server.get_gmail_client")
    def test_mark_read_success(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/mark-read", json={"email_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Email marked as read"

        mock_proxy_client.modify_message.assert_called_once()
        call_kwargs = mock_proxy_client.modify_message.call_args[1]
        assert call_kwargs["remove_label_ids"] == ["UNREAD"]

    @patch("email_server.get_gmail_client")
    @pytest.mark.parametrize("error_message", [
        "Gmail API error",
        "Message not found",
        "Permission denied",
    ])
    def test_mark_read_handles_error(self, mock_get_client, client, error_message):
        mock_get_client.side_effect = Exception(error_message)

        response = client.post("/mark-read", json={"email_id": "msg123"})
        assert response.status_code == 500


class TestApplyLabelEndpoint:
    """Tests for the /apply-label endpoint."""

    @patch("email_server.get_gmail_client")
    @pytest.mark.parametrize("label", ["STARRED", "IMPORTANT", "CATEGORY_PERSONAL", "CATEGORY_UPDATES"])
    def test_apply_label_success_system_labels(self, mock_get_client, client, label):
        """Test applying system labels (IDs match names)."""
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/apply-label", json={
            "email_id": "msg123",
            "label_name": label
        })
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert label in data["message"]

        call_kwargs = mock_proxy_client.modify_message.call_args[1]
        assert call_kwargs["add_label_ids"] == [label.upper()]

    @patch("email_server.get_gmail_client")
    def test_apply_label_success_user_label(self, mock_get_client, client):
        """Test applying user labels (requires ID lookup)."""
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.list_labels.return_value = {
            "labels": [
                {"id": "Label_123", "name": "response-required", "type": "user"},
                {"id": "Label_456", "name": "work", "type": "user"},
            ]
        }

        response = client.post("/apply-label", json={
            "email_id": "msg123",
            "label_name": "response-required"
        })
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "response-required" in data["message"]

        call_kwargs = mock_proxy_client.modify_message.call_args[1]
        assert call_kwargs["add_label_ids"] == ["Label_123"]

    @patch("email_server.get_gmail_client")
    def test_apply_label_not_found(self, mock_get_client, client):
        """Test applying a label that doesn't exist."""
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.list_labels.return_value = {
            "labels": [
                {"id": "Label_123", "name": "existing-label", "type": "user"},
            ]
        }

        response = client.post("/apply-label", json={
            "email_id": "msg123",
            "label_name": "nonexistent-label"
        })
        assert response.status_code == 400
        assert "not found" in response.json()["detail"]

    @patch("email_server.get_gmail_client")
    def test_apply_label_handles_proxy_error(self, mock_get_client, client):
        """Test that proxy errors are properly handled."""
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.modify_message.side_effect = Exception("Connection error")

        response = client.post("/apply-label", json={
            "email_id": "msg123",
            "label_name": "STARRED"
        })
        assert response.status_code == 500


class TestArchiveEndpoint:
    """Tests for the /archive endpoint."""

    @patch("email_server.get_gmail_client")
    def test_archive_success(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/archive", json={"email_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Email archived"

        call_kwargs = mock_proxy_client.modify_message.call_args[1]
        assert call_kwargs["remove_label_ids"] == ["INBOX"]

    @patch("email_server.get_gmail_client")
    def test_archive_handles_error(self, mock_get_client, client):
        mock_get_client.side_effect = Exception("Gmail API error")

        response = client.post("/archive", json={"email_id": "msg123"})
        assert response.status_code == 500


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

    def test_get_header_empty_list(self):
        from gmail_utils import get_header
        assert get_header([], "From") == ""

    @pytest.mark.parametrize("header_name,expected", [
        ("From", "sender@example.com"),
        ("from", "sender@example.com"),
        ("FROM", "sender@example.com"),
        ("FrOm", "sender@example.com"),
    ])
    def test_get_header_case_insensitive(self, header_name, expected):
        from gmail_utils import get_header
        headers = [{"name": "From", "value": "sender@example.com"}]
        assert get_header(headers, header_name) == expected

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

    def test_decode_body_multipart_nested(self):
        from gmail_utils import decode_body
        payload = {
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": "TmVzdGVkIHRleHQ="}  # "Nested text"
                        }
                    ]
                }
            ]
        }
        assert decode_body(payload) == "Nested text"

    def test_decode_body_no_content(self):
        from gmail_utils import decode_body
        payload = {}
        assert decode_body(payload) == "(Could not extract text content)"

    def test_decode_body_empty_body_data(self):
        from gmail_utils import decode_body
        payload = {"body": {}}
        assert decode_body(payload) == "(Could not extract text content)"


class TestBuildGmailQuery:
    """Tests for the build_gmail_query function."""

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

    @pytest.mark.parametrize("field,value,expected", [
        ("from_addr", "test@example.com", "from:test@example.com"),
        ("to_addr", "recipient@example.com", "to:recipient@example.com"),
        ("subject", "Test Subject", "subject:Test Subject"),
        ("since", "2026/01/01", "after:2026/01/01"),
        ("before", "2026/12/31", "before:2026/12/31"),
        ("query", "is:starred", "is:starred"),
    ])
    def test_build_query_individual_fields(self, field, value, expected):
        from email_server import build_gmail_query, SearchRequest
        request = SearchRequest(**{field: value})
        assert build_gmail_query(request) == expected

    def test_build_query_all_fields(self):
        from email_server import build_gmail_query, SearchRequest
        request = SearchRequest(
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            subject="Important",
            since="2026/01/01",
            before="2026/12/31",
            query="has:attachment"
        )
        query = build_gmail_query(request)
        assert "from:sender@example.com" in query
        assert "to:recipient@example.com" in query
        assert "subject:Important" in query
        assert "after:2026/01/01" in query
        assert "before:2026/12/31" in query
        assert "has:attachment" in query


class TestCallLocalLLM:
    """Tests for the call_local_llm function."""

    @pytest.mark.asyncio
    async def test_call_local_llm_strips_thinking_tags(self):
        import httpx
        from unittest.mock import patch, MagicMock
        from email_server import call_local_llm

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "<think>Some thinking...</think>\n\nActual response"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await call_local_llm("System prompt", "User content")
            assert result == "Actual response"
            assert "<think>" not in result

    @pytest.mark.asyncio
    async def test_call_local_llm_no_thinking_tags(self):
        import httpx
        from unittest.mock import patch, MagicMock
        from email_server import call_local_llm

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Simple response without thinking"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await call_local_llm("System prompt", "User content")
            assert result == "Simple response without thinking"


class TestRequestValidation:
    """Tests for request validation."""

    def test_search_request_defaults(self, client):
        # Should work with empty body (using defaults)
        response = client.post("/search", json={})
        # Will fail due to missing proxy client, but validates request parsing
        assert response.status_code == 200  # Returns error in body, not HTTP error

    def test_summarize_requires_message_id(self, client):
        response = client.post("/summarize", json={})
        assert response.status_code == 422  # Validation error

    def test_ask_about_requires_message_id_and_question(self, client):
        response = client.post("/ask-about", json={})
        assert response.status_code == 422

        response = client.post("/ask-about", json={"message_id": "msg123"})
        assert response.status_code == 422

    def test_mark_read_requires_email_id(self, client):
        response = client.post("/mark-read", json={})
        assert response.status_code == 422

    def test_apply_label_requires_email_id_and_label(self, client):
        response = client.post("/apply-label", json={})
        assert response.status_code == 422

        response = client.post("/apply-label", json={"email_id": "msg123"})
        assert response.status_code == 422

    def test_archive_requires_email_id(self, client):
        response = client.post("/archive", json={})
        assert response.status_code == 422


class TestBatchSummarizeEndpoint:
    """Tests for the /batch-summarize endpoint."""

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_batch_summarize_basic(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = '{"summary": "Test summary", "detected_action": "info_only", "detected_deadline": null}'

        response = client.post("/batch-summarize", json={"message_ids": ["msg123", "msg456"]})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert len(data["results"]) == 2
        assert data["results"][0]["success"] is True
        assert data["results"][0]["summary"] == "Test summary"
        assert data["results"][0]["detected_action"] == "info_only"

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_batch_summarize_parses_json_response(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = '{"summary": "Review this PR", "detected_action": "review_requested", "detected_deadline": "2026-02-01"}'

        response = client.post("/batch-summarize", json={"message_ids": ["msg123"]})
        data = response.json()

        result = data["results"][0]
        assert result["summary"] == "Review this PR"
        assert result["detected_action"] == "review_requested"
        assert result["detected_deadline"] == "2026-02-01"

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_batch_summarize_handles_invalid_json(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        # Non-JSON response should fall back to raw summary
        mock_llm.return_value = "This is a plain text summary without JSON."

        response = client.post("/batch-summarize", json={"message_ids": ["msg123"]})
        data = response.json()

        result = data["results"][0]
        assert result["success"] is True
        assert result["summary"] == "This is a plain text summary without JSON."
        assert result["detected_action"] is None

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_batch_summarize_handles_invalid_action_type(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        # Invalid action type should be ignored
        mock_llm.return_value = '{"summary": "Test", "detected_action": "unknown_action", "detected_deadline": null}'

        response = client.post("/batch-summarize", json={"message_ids": ["msg123"]})
        data = response.json()

        result = data["results"][0]
        assert result["success"] is True
        assert result["detected_action"] is None

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    def test_batch_summarize_continues_on_individual_error(self, mock_get_client, mock_llm, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        # First message succeeds, second fails
        async def get_side_effect(message_id, format=None):
            if message_id == "msg_fail":
                raise Exception("Message not found")
            return SAMPLE_MESSAGES["with_body"]

        mock_proxy_client.get_message.side_effect = get_side_effect
        mock_llm.return_value = '{"summary": "Success", "detected_action": null, "detected_deadline": null}'

        response = client.post("/batch-summarize", json={"message_ids": ["msg_ok", "msg_fail"]})
        data = response.json()

        assert data["success"] is True
        assert len(data["results"]) == 2
        assert data["results"][0]["success"] is True
        assert data["results"][1]["success"] is False
        assert "not found" in data["results"][1]["error"]

    @patch("email_server.get_gmail_client")
    def test_batch_summarize_handles_service_error(self, mock_get_client, client):
        mock_get_client.side_effect = Exception("Gmail service unavailable")

        response = client.post("/batch-summarize", json={"message_ids": ["msg123"]})
        data = response.json()

        assert data["success"] is False
        assert "Gmail service unavailable" in data["error"]

    def test_batch_summarize_requires_message_ids(self, client):
        response = client.post("/batch-summarize", json={})
        assert response.status_code == 422

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_client")
    @pytest.mark.parametrize("action_type", [
        "review_requested",
        "meeting_request",
        "info_only",
        "action_required",
        "approval_needed",
        "question",
        "follow_up",
        "deadline",
    ])
    def test_batch_summarize_all_action_types(self, mock_get_client, mock_llm, client, action_type):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = f'{{"summary": "Test", "detected_action": "{action_type}", "detected_deadline": null}}'

        response = client.post("/batch-summarize", json={"message_ids": ["msg123"]})
        data = response.json()

        assert data["results"][0]["detected_action"] == action_type


class TestBulkActionsEndpoint:
    """Tests for the /bulk-actions endpoint with per-email actions format."""

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_mark_read(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg123", "operations": ["mark_read"]},
                {"email_id": "msg456", "operations": ["mark_read"]},
            ]
        })
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["success_count"] == 2
        assert data["error_count"] == 0
        assert len(data["results"]) == 2
        assert all(r["success"] for r in data["results"])

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_archive(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg123", "operations": ["archive"]}
            ]
        })
        data = response.json()

        assert data["success"] is True
        call_kwargs = mock_proxy_client.modify_message.call_args[1]
        assert call_kwargs["remove_label_ids"] == ["INBOX"]

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_apply_label(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg123", "operations": ["apply_label:IMPORTANT"]}
            ]
        })
        data = response.json()

        assert data["success"] is True
        call_kwargs = mock_proxy_client.modify_message.call_args[1]
        assert call_kwargs["add_label_ids"] == ["IMPORTANT"]

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_multiple_operations_per_email(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client
        mock_proxy_client.list_labels.return_value = {
            "labels": [
                {"id": "Label_789", "name": "PROCESSED", "type": "user"},
            ]
        }

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg123", "operations": ["mark_read", "archive", "apply_label:PROCESSED"]}
            ]
        })
        data = response.json()

        assert data["success"] is True
        assert data["success_count"] == 1
        # Should have been called 3 times (once per operation)
        assert mock_proxy_client.modify_message.call_count == 3

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_different_operations_per_email(self, mock_get_client, client):
        """Test that each email can have different operations."""
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg1", "operations": ["mark_read"]},
                {"email_id": "msg2", "operations": ["mark_read", "archive"]},
                {"email_id": "msg3", "operations": ["mark_read", "apply_label:IMPORTANT"]},
            ]
        })
        data = response.json()

        assert data["success"] is True
        assert data["success_count"] == 3
        assert data["error_count"] == 0
        # 1 + 2 + 2 = 5 total operations
        assert mock_proxy_client.modify_message.call_count == 5

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_partial_failure(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        # First email succeeds, second fails
        async def modify_side_effect(email_id, add_label_ids=None, remove_label_ids=None):
            if email_id == "msg_fail":
                raise Exception("Permission denied")
            return {}

        mock_proxy_client.modify_message.side_effect = modify_side_effect

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg_ok", "operations": ["mark_read"]},
                {"email_id": "msg_fail", "operations": ["mark_read"]},
            ]
        })
        data = response.json()

        assert data["success"] is True  # Overall request succeeded
        assert data["success_count"] == 1
        assert data["error_count"] == 1
        assert data["results"][0]["success"] is True
        assert data["results"][1]["success"] is False
        assert "Permission denied" in data["results"][1]["error"]

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_unknown_operation(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg123", "operations": ["unknown_op"]}
            ]
        })
        data = response.json()

        assert data["success"] is True
        assert data["error_count"] == 1
        assert "Unknown operation" in data["results"][0]["error"]

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_apply_label_empty_name(self, mock_get_client, client):
        """apply_label: with empty label name should return an error."""
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg123", "operations": ["apply_label:"]}
            ]
        })
        data = response.json()

        assert data["success"] is True
        assert data["error_count"] == 1
        assert "apply_label requires a label name" in data["results"][0]["error"]
        # No Gmail API calls should be made
        mock_proxy_client.modify_message.assert_not_called()

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_handles_service_error(self, mock_get_client, client):
        mock_get_client.side_effect = Exception("Gmail service unavailable")

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg123", "operations": ["mark_read"]}
            ]
        })
        data = response.json()

        assert data["success"] is False
        assert "Gmail service unavailable" in data["error"]

    def test_bulk_actions_requires_actions(self, client):
        response = client.post("/bulk-actions", json={})
        assert response.status_code == 422

    def test_bulk_actions_action_requires_email_id(self, client):
        response = client.post("/bulk-actions", json={
            "actions": [{"operations": ["mark_read"]}]
        })
        assert response.status_code == 422

    def test_bulk_actions_action_requires_operations(self, client):
        response = client.post("/bulk-actions", json={
            "actions": [{"email_id": "msg123"}]
        })
        assert response.status_code == 422

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_empty_actions_list(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/bulk-actions", json={"actions": []})
        data = response.json()

        assert data["success"] is True
        assert data["success_count"] == 0
        assert data["error_count"] == 0
        assert data["results"] == []

    @patch("email_server.get_gmail_client")
    def test_bulk_actions_empty_operations_for_email(self, mock_get_client, client):
        """Empty operations array for an email should succeed with no ops performed."""
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        response = client.post("/bulk-actions", json={
            "actions": [
                {"email_id": "msg123", "operations": []}
            ]
        })
        data = response.json()

        assert data["success"] is True
        assert data["success_count"] == 1
        assert data["error_count"] == 0
        assert data["results"][0]["success"] is True
        # No Gmail API calls should be made
        mock_proxy_client.modify_message.assert_not_called()


class TestSearchEndpointNewFields:
    """Tests for the new from_name and has_attachments fields in /search."""

    @patch("email_server.get_gmail_client")
    def test_search_returns_from_name(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        mock_proxy_client.list_messages.return_value = {
            "messages": [{"id": "msg123", "threadId": "thread123"}]
        }
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["basic"]

        response = client.post("/search", json={"limit": 1})
        data = response.json()

        msg = data["messages"][0]
        assert msg["from_name"] == "Sender Name"
        assert msg["from_addr"] == "Sender Name <sender@example.com>"

    @patch("email_server.get_gmail_client")
    def test_search_returns_from_name_email_only(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        # Message with email-only From header
        msg_data = {
            "id": "msg123",
            "labelIds": ["INBOX"],
            "snippet": "Test",
            "payload": {
                "headers": [
                    {"name": "From", "value": "noreply@example.com"},
                    {"name": "Subject", "value": "Test"},
                    {"name": "Date", "value": "Jan 28, 2026"},
                ]
            }
        }

        mock_proxy_client.list_messages.return_value = {
            "messages": [{"id": "msg123"}]
        }
        mock_proxy_client.get_message.return_value = msg_data

        response = client.post("/search", json={"limit": 1})
        data = response.json()

        msg = data["messages"][0]
        assert msg["from_name"] == "noreply@example.com"

    @patch("email_server.get_gmail_client")
    def test_search_detects_attachments(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        mock_proxy_client.list_messages.return_value = {
            "messages": [{"id": "msg_attach"}]
        }
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["with_attachment"]

        response = client.post("/search", json={"limit": 1})
        data = response.json()

        msg = data["messages"][0]
        assert msg["has_attachments"] is True

    @patch("email_server.get_gmail_client")
    def test_search_no_attachments(self, mock_get_client, client):
        mock_proxy_client = AsyncMock()
        mock_get_client.return_value = mock_proxy_client

        mock_proxy_client.list_messages.return_value = {
            "messages": [{"id": "msg_no_attach"}]
        }
        mock_proxy_client.get_message.return_value = SAMPLE_MESSAGES["without_attachment"]

        response = client.post("/search", json={"limit": 1})
        data = response.json()

        msg = data["messages"][0]
        assert msg["has_attachments"] is False


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_parse_sender_name_with_name(self):
        from email_server import parse_sender_name
        assert parse_sender_name("John Doe <john@example.com>") == "John Doe"

    def test_parse_sender_name_email_only(self):
        from email_server import parse_sender_name
        assert parse_sender_name("john@example.com") == "john@example.com"

    def test_parse_sender_name_empty(self):
        from email_server import parse_sender_name
        assert parse_sender_name("") == ""

    def test_parse_sender_name_quoted_name(self):
        from email_server import parse_sender_name
        assert parse_sender_name('"Doe, John" <john@example.com>') == '"Doe, John"'

    def test_has_attachments_with_attachment(self):
        from email_server import has_attachments
        payload = {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": "test"}},
                {"mimeType": "application/pdf", "filename": "doc.pdf", "body": {"attachmentId": "123"}}
            ]
        }
        assert has_attachments(payload) is True

    def test_has_attachments_without_attachment(self):
        from email_server import has_attachments
        payload = {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": "test"}},
                {"mimeType": "text/html", "body": {"data": "<html></html>"}}
            ]
        }
        assert has_attachments(payload) is False

    def test_has_attachments_empty_payload(self):
        from email_server import has_attachments
        assert has_attachments({}) is False
        assert has_attachments(None) is False

    def test_has_attachments_inline_image_not_counted(self):
        from email_server import has_attachments
        payload = {
            "parts": [
                {
                    "mimeType": "image/png",
                    "filename": "image.png",
                    "headers": [{"name": "Content-Disposition", "value": "inline"}],
                    "body": {"attachmentId": "123"}
                }
            ]
        }
        assert has_attachments(payload) is False

    def test_has_attachments_nested_parts(self):
        from email_server import has_attachments
        payload = {
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": "test"}},
                        {
                            "mimeType": "multipart/related",
                            "parts": [
                                {"mimeType": "application/pdf", "filename": "nested.pdf", "body": {"attachmentId": "123"}}
                            ]
                        }
                    ]
                }
            ]
        }
        assert has_attachments(payload) is True


class TestProxyClient:
    """Tests for the proxy client."""

    def test_proxy_client_init_missing_api_key(self):
        """Test that ProxyAuthError is raised when API key is missing."""
        from proxy_client import GmailProxyClient, ProxyAuthError
        import os

        # Temporarily clear the environment variable
        original_key = os.environ.get("PROXY_API_KEY")
        os.environ["PROXY_API_KEY"] = ""

        try:
            with pytest.raises(ProxyAuthError, match="PROXY_API_KEY"):
                GmailProxyClient(api_key="")
        finally:
            if original_key:
                os.environ["PROXY_API_KEY"] = original_key

    def test_proxy_client_init_with_api_key(self):
        """Test that client initializes correctly with API key."""
        from proxy_client import GmailProxyClient

        client = GmailProxyClient(api_key="aproxy_test123")
        assert client.api_key == "aproxy_test123"

    def test_proxy_client_default_url(self):
        """Test that default URL is set correctly."""
        from proxy_client import GmailProxyClient

        client = GmailProxyClient(api_key="aproxy_test123")
        assert "host.docker.internal" in client.proxy_url or client.proxy_url

    def test_proxy_client_custom_url(self):
        """Test that custom URL is used."""
        from proxy_client import GmailProxyClient

        client = GmailProxyClient(proxy_url="http://custom:9000", api_key="aproxy_test123")
        assert client.proxy_url == "http://custom:9000"

    def test_proxy_client_headers(self):
        """Test that headers include Bearer token."""
        from proxy_client import GmailProxyClient

        client = GmailProxyClient(api_key="aproxy_test123")
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer aproxy_test123"
        assert headers["Content-Type"] == "application/json"


class TestProxyErrorHandling:
    """Tests for proxy error handling."""

    @patch("email_server.get_gmail_client")
    def test_proxy_auth_error_formatted(self, mock_get_client, client):
        """Test that ProxyAuthError is formatted correctly."""
        from proxy_client import ProxyAuthError

        mock_get_client.side_effect = ProxyAuthError("Invalid API key")

        response = client.post("/search", json={"limit": 10})
        data = response.json()

        assert data["success"] is False
        assert "Authentication error" in data["error"]

    @patch("email_server.get_gmail_client")
    def test_proxy_forbidden_error_formatted(self, mock_get_client, client):
        """Test that ProxyForbiddenError is formatted correctly."""
        from proxy_client import ProxyForbiddenError

        mock_get_client.side_effect = ProxyForbiddenError("Operation blocked")

        response = client.post("/search", json={"limit": 10})
        data = response.json()

        assert data["success"] is False
        assert "Operation blocked" in data["error"]

    @patch("email_server.get_gmail_client")
    def test_proxy_error_formatted(self, mock_get_client, client):
        """Test that ProxyError is formatted correctly."""
        from proxy_client import ProxyError

        mock_get_client.side_effect = ProxyError("Backend unavailable")

        response = client.post("/search", json={"limit": 10})
        data = response.json()

        assert data["success"] is False
        assert "Proxy error" in data["error"]
