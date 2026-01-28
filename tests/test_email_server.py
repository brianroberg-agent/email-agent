"""Comprehensive tests for email_server with mocked Gmail API and LLM.

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


class TestSearchEndpoint:
    """Tests for the /search endpoint."""

    @patch("email_server.get_gmail_service")
    def test_search_basic(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = {
            "messages": [
                {"id": "msg123", "threadId": "thread123"},
                {"id": "msg456", "threadId": "thread456"},
            ]
        }
        mock_messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["basic"]

        response = client.post("/search", json={"limit": 10})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["error"] is None
        assert len(data["messages"]) == 2

    @patch("email_server.get_gmail_service")
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
    def test_search_with_filters(self, mock_get_service, client, filters, expected_query_parts):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = {"messages": []}

        response = client.post("/search", json={**filters, "limit": 10})
        assert response.status_code == 200

        call_args = mock_messages.return_value.list.call_args
        query_string = call_args[1].get("q", "")
        for part in expected_query_parts:
            assert part in query_string

    @patch("email_server.get_gmail_service")
    @pytest.mark.parametrize("folder", ["INBOX", "SENT", "DRAFT", "SPAM", "TRASH", "STARRED"])
    def test_search_with_folder(self, mock_get_service, client, folder):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = {"messages": []}

        response = client.post("/search", json={"folder": folder, "limit": 5})
        assert response.status_code == 200

        call_args = mock_messages.return_value.list.call_args
        assert call_args[1]["labelIds"] == [folder]

    @patch("email_server.get_gmail_service")
    @pytest.mark.parametrize("limit", [1, 10, 25, 50])
    def test_search_with_limit(self, mock_get_service, client, limit):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = {"messages": []}

        response = client.post("/search", json={"limit": limit})
        assert response.status_code == 200

        call_args = mock_messages.return_value.list.call_args
        assert call_args[1]["maxResults"] == limit

    def test_search_limit_validation_min(self, client):
        response = client.post("/search", json={"limit": 0})
        assert response.status_code == 422  # Validation error

    def test_search_limit_validation_max(self, client):
        response = client.post("/search", json={"limit": 100})
        assert response.status_code == 422  # Validation error

    @patch("email_server.get_gmail_service")
    def test_search_empty_results(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = {}  # No messages key

        response = client.post("/search", json={"limit": 10})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["messages"] == []

    @patch("email_server.get_gmail_service")
    def test_search_returns_correct_message_structure(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        mock_messages = mock_service.users.return_value.messages
        mock_messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg123", "threadId": "thread123"}]
        }
        mock_messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["basic"]

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
    @pytest.mark.parametrize("error_message", [
        "Gmail API error",
        "Connection refused",
        "Invalid credentials",
        "Rate limit exceeded",
    ])
    def test_search_handles_error(self, mock_get_service, client, error_message):
        mock_get_service.side_effect = Exception(error_message)

        response = client.post("/search", json={"limit": 10})
        assert response.status_code == 200  # Returns 200 with error in body

        data = response.json()
        assert data["success"] is False
        assert data["error"] == error_message
        assert data["messages"] == []


class TestSummarizeEndpoint:
    """Tests for the /summarize endpoint."""

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_summarize_basic(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["with_body"]

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
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = "Summary here"

        client.post("/summarize", json={"message_id": "msg123"})

        call_args = mock_llm.call_args
        system_prompt = call_args[0][0]
        assert "summarizing an email" in system_prompt
        assert "untrusted data" in system_prompt

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_summarize_multipart_email(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["multipart"]

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
    @patch("email_server.get_gmail_service")
    def test_summarize_truncates_long_body(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["long_body"]

        mock_llm.return_value = "Summary of long email"

        client.post("/summarize", json={"message_id": "msg_long"})

        call_args = mock_llm.call_args
        user_content = call_args[0][1]
        # Body should be truncated with "..."
        assert user_content.endswith("...")
        assert len(user_content) <= 3003 + 10  # MAX_BODY_LENGTH + "..." + some margin

    @patch("email_server.get_gmail_service")
    def test_summarize_handles_gmail_error(self, mock_get_service, client):
        mock_get_service.side_effect = Exception("Gmail API error")

        response = client.post("/summarize", json={"message_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is False
        assert "Gmail API error" in data["error"]

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_summarize_handles_llm_error(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.side_effect = Exception("LLM connection failed")

        response = client.post("/summarize", json={"message_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is False
        assert "LLM connection failed" in data["error"]


class TestAskAboutEndpoint:
    """Tests for the /ask-about endpoint."""

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_ask_about_basic(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["with_body"]

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
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = "Answer here"

        client.post("/ask-about", json={
            "message_id": "msg123",
            "question": "What is the main request?"
        })

        call_args = mock_llm.call_args
        user_content = call_args[0][1]
        assert "Question: What is the main request?" in user_content

    @patch("email_server.call_local_llm", new_callable=AsyncMock)
    @patch("email_server.get_gmail_service")
    def test_ask_about_uses_correct_system_prompt(self, mock_get_service, mock_llm, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["with_body"]

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
    @patch("email_server.get_gmail_service")
    @pytest.mark.parametrize("question", [
        "What is the sender's name?",
        "Are there any attachments?",
        "When is the meeting scheduled?",
        "What action items are mentioned?",
        "Is this email urgent?",
    ])
    def test_ask_about_various_questions(self, mock_get_service, mock_llm, client, question):
        mock_service = Mock()
        mock_get_service.return_value = mock_service
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = SAMPLE_MESSAGES["with_body"]

        mock_llm.return_value = f"Answer to: {question}"

        response = client.post("/ask-about", json={
            "message_id": "msg123",
            "question": question
        })
        assert response.status_code == 200
        assert response.json()["success"] is True

    @patch("email_server.get_gmail_service")
    def test_ask_about_handles_gmail_error(self, mock_get_service, client):
        mock_get_service.side_effect = Exception("Gmail API error")

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

    @patch("email_server.get_gmail_service_with_modify")
    def test_mark_read_success(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        response = client.post("/mark-read", json={"email_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Email marked as read"

        mock_service.users.return_value.messages.return_value.modify.assert_called_once()
        call_kwargs = mock_service.users.return_value.messages.return_value.modify.call_args[1]
        assert call_kwargs["id"] == "msg123"
        assert call_kwargs["body"] == {"removeLabelIds": ["UNREAD"]}

    @patch("email_server.get_gmail_service_with_modify")
    @pytest.mark.parametrize("error_message", [
        "Gmail API error",
        "Message not found",
        "Permission denied",
    ])
    def test_mark_read_handles_error(self, mock_get_service, client, error_message):
        mock_get_service.side_effect = Exception(error_message)

        response = client.post("/mark-read", json={"email_id": "msg123"})
        assert response.status_code == 500


class TestApplyLabelEndpoint:
    """Tests for the /apply-label endpoint."""

    @patch("email_server.get_gmail_service_with_modify")
    @pytest.mark.parametrize("label", ["STARRED", "IMPORTANT", "CATEGORY_PERSONAL", "CATEGORY_WORK"])
    def test_apply_label_success(self, mock_get_service, client, label):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        response = client.post("/apply-label", json={
            "email_id": "msg123",
            "label_name": label
        })
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert label in data["message"]

        call_kwargs = mock_service.users.return_value.messages.return_value.modify.call_args[1]
        assert call_kwargs["body"] == {"addLabelIds": [label]}

    @patch("email_server.get_gmail_service_with_modify")
    def test_apply_label_handles_error(self, mock_get_service, client):
        mock_get_service.side_effect = Exception("Label not found")

        response = client.post("/apply-label", json={
            "email_id": "msg123",
            "label_name": "NONEXISTENT"
        })
        assert response.status_code == 500


class TestArchiveEndpoint:
    """Tests for the /archive endpoint."""

    @patch("email_server.get_gmail_service_with_modify")
    def test_archive_success(self, mock_get_service, client):
        mock_service = Mock()
        mock_get_service.return_value = mock_service

        response = client.post("/archive", json={"email_id": "msg123"})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Email archived"

        call_kwargs = mock_service.users.return_value.messages.return_value.modify.call_args[1]
        assert call_kwargs["body"] == {"removeLabelIds": ["INBOX"]}

    @patch("email_server.get_gmail_service_with_modify")
    def test_archive_handles_error(self, mock_get_service, client):
        mock_get_service.side_effect = Exception("Gmail API error")

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
        # Will fail due to missing Gmail service, but validates request parsing
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
