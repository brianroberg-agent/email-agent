"""RFC 2822 email message construction for Gmail drafts.

This module builds properly formatted email messages from structured fields,
encoding them as base64url strings for the Gmail API.
"""

import base64
from email.mime.text import MIMEText
from email.utils import formataddr


def build_rfc2822(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
) -> str:
    """Build an RFC 2822 message and return it as a base64url-encoded string.

    Args:
        to: Recipient email addresses (required, at least one).
        subject: Email subject line (required).
        body: Plain text email body (required).
        cc: Carbon copy recipients.
        bcc: Blind carbon copy recipients.
        in_reply_to: Message-ID of the email being replied to (for threading).
        references: List of Message-IDs in the conversation thread.

    Returns:
        Base64url-encoded RFC 2822 message string for the Gmail API.

    Raises:
        ValueError: If required fields are missing or empty.
    """
    if not to:
        raise ValueError("At least one recipient is required")
    if not subject:
        raise ValueError("Subject is required")
    if not body:
        raise ValueError("Body is required")

    msg = MIMEText(body, "plain", "utf-8")

    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)

    # Threading headers for replies
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)

    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
