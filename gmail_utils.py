"""Gmail utility functions for email server v2.

These functions handle parsing of Gmail API message data.
They have no framework or authentication dependencies.
"""

import base64


def get_header(headers: list, name: str) -> str:
    """Extract a header value from Gmail message headers.

    Args:
        headers: List of header dicts with 'name' and 'value' keys
        name: Header name to find (case-insensitive)

    Returns:
        Header value or empty string if not found
    """
    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]
    return ""


def decode_body(payload: dict) -> str:
    """Decode base64url email body from Gmail API payload.

    Handles both simple messages and multipart messages.
    Prefers text/plain content.

    Args:
        payload: Gmail message payload dict

    Returns:
        Decoded email body text
    """
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                if part["body"].get("data"):
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            elif mime_type.startswith("multipart/"):
                result = decode_body(part)
                if result:
                    return result
    return "(Could not extract text content)"
