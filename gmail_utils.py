"""Gmail utility functions for email server v2.

These functions handle parsing of Gmail API message data.
They have no framework or authentication dependencies.
"""

import base64
import re
from email.utils import formataddr, getaddresses

# Angle-bracketed Message-IDs, e.g. "<abc@example.com>"
_MESSAGE_ID_PATTERN = re.compile(r"<[^<>]+>")


def parse_references(header_value: str) -> list[str]:
    """Extract Message-IDs from a References (or In-Reply-To) header value.

    Tolerates the separator variations found in real mail: whitespace,
    commas, CFWS comments, folding remnants, and adjacent angle-bracket
    ids with no separator at all.

    Args:
        header_value: Raw header value (may be empty)

    Returns:
        List of angle-bracketed Message-IDs, in order
    """
    if not header_value:
        return []
    return _MESSAGE_ID_PATTERN.findall(header_value)


def parse_address_list(header_value: str) -> list[str]:
    """Split an address header (To/Cc/Bcc) into individual addresses.

    Uses RFC 2822-aware parsing so display names containing commas
    (e.g. '"Doe, John" <j@x.com>') stay intact.

    Args:
        header_value: Raw header value (may be empty)

    Returns:
        List of formatted addresses, e.g. ['Jane <jane@x.com>', 'b@y.com']
    """
    if not header_value:
        return []
    return [formataddr(pair) for pair in getaddresses([header_value]) if pair[0] or pair[1]]


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
