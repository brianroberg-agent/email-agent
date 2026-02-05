"""Cloud LLM client for email classification.

Provides person detection and full classification using
configurable cloud LLM providers (OpenAI-compatible APIs).
"""

import json
import logging
import re
from typing import Optional

import httpx

from config import get_config

logger = logging.getLogger(__name__)

# System prompt for person detection (metadata only, no body)
PERSON_DETECTION_PROMPT = """You are analyzing email metadata to determine if this email is from a real person or an automated system.

Analyze the sender address, subject line, and snippet to make your determination.

Indicators of AUTOMATED/NON-PERSON emails:
- Sender addresses containing: noreply, no-reply, notifications, alerts, mailer, updates, newsletter, support@, info@, team@
- Domains like: github.com, notifications.*, alerts.*, *.noreply.*, marketing.*, campaign.*
- Subject lines with: "Your order", "Your receipt", "Password reset", "Verify your", "Welcome to", "[ACTION", automatic numbering patterns
- Marketing language, promotional content, automated notifications

Indicators of PERSON emails:
- Personal name in sender (e.g., "John Smith <john@company.com>")
- Conversational subject lines
- Personal email domains (gmail.com, outlook.com, company employee addresses)
- References to personal matters, meetings, questions directed at the recipient

Respond with ONLY valid JSON in this exact format:
{"is_person": true, "confidence": 0.95, "reasoning": "brief explanation"}

where is_person is true if from a real person, false if automated/marketing/system.
confidence is 0.0 to 1.0.

If uncertain, default to is_person: true (err on the side of privacy)."""

# System prompt for full email classification (includes body)
CLASSIFICATION_PROMPT = """You are classifying an email for a busy professional. Analyze the full email and categorize it.

Respond with ONLY valid JSON in this exact format:
{
  "category": "one of: personal, work, transactional, marketing, notification, newsletter, spam",
  "priority": "one of: high, medium, low",
  "summary": "1-2 sentence summary",
  "action_needed": true or false,
  "reasoning": "brief explanation of classification"
}

Categories:
- personal: From friends, family, personal contacts
- work: Work-related correspondence, colleagues, clients
- transactional: Receipts, order confirmations, shipping updates
- marketing: Promotional emails, sales, advertisements
- notification: System alerts, app notifications, status updates
- newsletter: Subscribed content, digests, updates
- spam: Unwanted, unsolicited emails

Priority signals:
- high: Urgent, deadlines, direct requests, important senders
- medium: Regular correspondence, informational
- low: FYI, can be processed later"""


class CloudLLMClient:
    """Client for cloud LLM operations."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """Initialize cloud LLM client.

        Args:
            base_url: API base URL (OpenAI-compatible).
            api_key: API key for authentication.
            model: Model name to use.
        """
        config = get_config()
        self.base_url = (base_url or config.cloud_llm_url).rstrip("/")
        self.api_key = api_key or config.cloud_llm_api_key
        self.model = model or config.cloud_llm_model

        if not self.api_key:
            logger.warning("CLOUD_LLM_API_KEY not set - cloud classification disabled")

    async def _call_llm(
        self,
        system_prompt: str,
        user_content: str,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> str:
        """Make a call to the cloud LLM.

        Args:
            system_prompt: System prompt for the LLM.
            user_content: User content to process.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLM response text.

        Raises:
            httpx.HTTPError: On API errors.
        """
        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks.

        Args:
            text: Raw LLM response text.

        Returns:
            Parsed JSON dict.

        Raises:
            json.JSONDecodeError: If JSON parsing fails.
        """
        # Strip markdown code blocks if present
        text = text.strip()
        if text.startswith("```"):
            # Remove opening fence (with optional language specifier)
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            # Remove closing fence
            text = re.sub(r"\n?```\s*$", "", text)

        return json.loads(text)

    async def detect_person(
        self,
        from_addr: str,
        subject: str,
        snippet: str,
    ) -> dict:
        """Detect if an email is from a real person.

        Uses only metadata (no body) for privacy.

        Args:
            from_addr: Sender address.
            subject: Email subject line.
            snippet: Email snippet (~100 chars).

        Returns:
            Dict with is_person (bool), confidence (float), reasoning (str).
        """
        if not self.api_key:
            # Default to person if cloud LLM not configured (privacy-preserving)
            return {
                "is_person": True,
                "confidence": 0.0,
                "reasoning": "Cloud LLM not configured, defaulting to person",
            }

        user_content = f"""Sender: {from_addr}
Subject: {subject}
Snippet: {snippet}"""

        try:
            response = await self._call_llm(
                PERSON_DETECTION_PROMPT,
                user_content,
                max_tokens=256,
                temperature=0.1,  # Low temperature for consistency
            )

            result = self._parse_json_response(response)

            # Validate response structure
            if "is_person" not in result:
                logger.warning(f"Invalid person detection response: {response}")
                return {
                    "is_person": True,
                    "confidence": 0.0,
                    "reasoning": "Invalid response, defaulting to person",
                }

            return {
                "is_person": bool(result.get("is_person", True)),
                "confidence": float(result.get("confidence", 0.5)),
                "reasoning": str(result.get("reasoning", "")),
            }

        except Exception as e:
            logger.error(f"Person detection failed: {e}")
            # Default to person on error (privacy-preserving)
            return {
                "is_person": True,
                "confidence": 0.0,
                "reasoning": f"Detection failed: {e}",
            }

    async def classify_email(
        self,
        from_addr: str,
        subject: str,
        body: str,
    ) -> dict:
        """Classify an email using full content.

        Args:
            from_addr: Sender address.
            subject: Email subject line.
            body: Full email body.

        Returns:
            Dict with category, priority, summary, action_needed, reasoning.
        """
        if not self.api_key:
            return {
                "category": "unknown",
                "priority": "medium",
                "summary": "Cloud LLM not configured",
                "action_needed": False,
                "reasoning": "Cloud LLM API key not set",
            }

        # Truncate body if too long
        max_body_length = 3000
        if len(body) > max_body_length:
            body = body[:max_body_length] + "..."

        user_content = f"""From: {from_addr}
Subject: {subject}

Body:
{body}"""

        try:
            response = await self._call_llm(
                CLASSIFICATION_PROMPT,
                user_content,
                max_tokens=512,
                temperature=0.3,
            )

            result = self._parse_json_response(response)

            return {
                "category": result.get("category", "unknown"),
                "priority": result.get("priority", "medium"),
                "summary": result.get("summary", ""),
                "action_needed": bool(result.get("action_needed", False)),
                "reasoning": result.get("reasoning", ""),
            }

        except Exception as e:
            logger.error(f"Email classification failed: {e}")
            return {
                "category": "unknown",
                "priority": "medium",
                "summary": f"Classification failed: {e}",
                "action_needed": False,
                "reasoning": str(e),
            }


# Singleton instance
_client: Optional[CloudLLMClient] = None


def get_cloud_llm_client() -> CloudLLMClient:
    """Get or create the cloud LLM client singleton."""
    global _client
    if _client is None:
        _client = CloudLLMClient()
    return _client
