"""Configuration management for email agent.

Centralizes configuration loading from environment variables
with validation and sensible defaults.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Email agent configuration."""

    # Existing settings (proxy and MLX)
    proxy_url: str = field(default_factory=lambda: os.environ.get(
        "PROXY_URL", "http://host.docker.internal:8000"
    ))
    proxy_api_key: str = field(default_factory=lambda: os.environ.get(
        "PROXY_API_KEY", ""
    ))
    mlx_url: str = field(default_factory=lambda: os.environ.get(
        "MLX_URL", "http://localhost:8080/v1/chat/completions"
    ))
    mlx_model: str = field(default_factory=lambda: os.environ.get(
        "MLX_MODEL", "qwen/qwen3-14b"
    ))

    # Cloud LLM settings
    cloud_llm_url: str = field(default_factory=lambda: os.environ.get(
        "CLOUD_LLM_URL", "https://api.novita.ai/v3/openai"
    ))
    cloud_llm_api_key: str = field(default_factory=lambda: os.environ.get(
        "CLOUD_LLM_API_KEY", ""
    ))
    cloud_llm_model: str = field(default_factory=lambda: os.environ.get(
        "CLOUD_LLM_MODEL", "minimax/minimax-m2.1"
    ))

    # Sender whitelist (always route to MLX)
    sender_whitelist: list[str] = field(default_factory=list)

    # Queue settings
    queue_db_path: str = field(default_factory=lambda: os.environ.get(
        "QUEUE_DB_PATH", "/app/data/classification.db"
    ))
    queue_retention_days: int = field(default_factory=lambda: int(os.environ.get(
        "QUEUE_RETENTION_DAYS", "7"
    )))

    # Worker settings
    worker_batch_size: int = field(default_factory=lambda: int(os.environ.get(
        "WORKER_BATCH_SIZE", "5"
    )))
    worker_poll_interval: int = field(default_factory=lambda: int(os.environ.get(
        "WORKER_POLL_INTERVAL", "10"
    )))

    def __post_init__(self):
        """Parse whitelist from environment after initialization."""
        whitelist_str = os.environ.get("SENDER_WHITELIST", "")
        if whitelist_str:
            # Parse comma-separated list, strip whitespace
            self.sender_whitelist = [
                addr.strip().lower()
                for addr in whitelist_str.split(",")
                if addr.strip()
            ]

    def is_whitelisted(self, sender_email: str) -> bool:
        """Check if a sender email matches the whitelist.

        Supports exact email matches and domain patterns (@domain.com).
        """
        if not sender_email:
            return False

        sender_lower = sender_email.lower()

        for pattern in self.sender_whitelist:
            # Domain pattern (e.g., @company.com)
            if pattern.startswith("@"):
                if sender_lower.endswith(pattern):
                    return True
            # Exact email match
            elif sender_lower == pattern:
                return True

        return False


# Singleton config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the config singleton."""
    global _config
    if _config is None:
        _config = Config()
    return _config
