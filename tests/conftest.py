"""Shared test fixtures for email server tests."""

import base64
import pytest
from unittest.mock import Mock, AsyncMock
from fastapi.testclient import TestClient

from email_server import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_gmail_service():
    """Create a mock Gmail service with standard method chains."""
    service = Mock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": []
    }
    service.users.return_value.messages.return_value.get.return_value.execute.return_value = {}
    service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}
    return service


def _encode_body(text: str) -> str:
    """Encode text as base64url for Gmail API format."""
    return base64.urlsafe_b64encode(text.encode()).decode()


# Sample Gmail API response data for testing
SAMPLE_MESSAGES = {
    "basic": {
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
    },
    "with_body": {
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
                "data": _encode_body("Hello, this is a test email body.")
            }
        }
    },
    "multipart": {
        "id": "msg456",
        "threadId": "thread456",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "another@example.com"},
                {"name": "Subject", "value": "Multipart Email"},
                {"name": "Date", "value": "Jan 26, 2026 10:00 AM"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encode_body("Plain text content here.")}
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _encode_body("<html></html>")}
                }
            ]
        }
    },
    "no_body": {
        "id": "msg789",
        "threadId": "thread789",
        "labelIds": ["SENT"],
        "payload": {
            "headers": [
                {"name": "From", "value": "me@example.com"},
                {"name": "Subject", "value": "Empty Email"},
                {"name": "Date", "value": "Jan 27, 2026 9:00 AM"},
            ]
        }
    },
    "starred": {
        "id": "msg_starred",
        "threadId": "thread_starred",
        "labelIds": ["INBOX", "STARRED"],
        "snippet": "This is a starred message",
        "payload": {
            "headers": [
                {"name": "From", "value": "vip@example.com"},
                {"name": "Subject", "value": "VIP Message"},
                {"name": "Date", "value": "Jan 28, 2026 11:00 AM"},
            ]
        }
    },
    "long_body": {
        "id": "msg_long",
        "threadId": "thread_long",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "verbose@example.com"},
                {"name": "Subject", "value": "Long Email"},
                {"name": "Date", "value": "Jan 28, 2026 12:00 PM"},
            ],
            "body": {
                # 5000 'A' characters - will be truncated
                "data": _encode_body("A" * 5000)
            }
        }
    },
}
