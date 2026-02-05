"""SQLite-backed classification queue for MLX processing.

Provides async queue operations for emails that need to be classified
by the local MLX model. Handles persistence, retries, and cleanup.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite

# Schema version for migrations
SCHEMA_VERSION = 1

SCHEMA = """
-- Classification queue for emails awaiting MLX processing
CREATE TABLE IF NOT EXISTS classification_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    from_addr TEXT NOT NULL,
    subject TEXT NOT NULL,
    snippet TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_started_at TIMESTAMP NULL,
    processed_at TIMESTAMP NULL,
    classification_result TEXT NULL,
    error TEXT NULL,
    retries INTEGER DEFAULT 0
);

-- Index for finding unprocessed items efficiently
CREATE INDEX IF NOT EXISTS idx_pending
    ON classification_queue(processed_at, processing_started_at)
    WHERE processed_at IS NULL;

-- Index for cleanup by age
CREATE INDEX IF NOT EXISTS idx_created_at
    ON classification_queue(created_at);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""


class ClassificationQueue:
    """Async SQLite queue for email classification tasks."""

    def __init__(self, db_path: str):
        """Initialize queue with database path.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._initialized = False

    async def init(self) -> None:
        """Initialize the database schema.

        Creates tables and indexes if they don't exist.
        Safe to call multiple times.
        """
        if self._initialized:
            return

        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for better concurrent access
            await db.execute("PRAGMA journal_mode=WAL")

            # Execute schema
            await db.executescript(SCHEMA)

            # Track schema version
            await db.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,)
            )
            await db.commit()

        self._initialized = True

    async def enqueue(
        self,
        message_id: str,
        from_addr: str,
        subject: str,
        snippet: str,
    ) -> int:
        """Add an email to the classification queue.

        Args:
            message_id: Gmail message ID.
            from_addr: Sender email address.
            subject: Email subject line.
            snippet: Email snippet (first ~100 chars).

        Returns:
            Queue entry ID.

        Raises:
            sqlite3.IntegrityError: If message_id already exists.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO classification_queue
                    (message_id, from_addr, subject, snippet)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, from_addr, subject, snippet)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_pending(self, limit: int = 10, stale_timeout_minutes: int = 30) -> list[dict]:
        """Get pending classification tasks and mark them as in-progress.

        Returns oldest unprocessed entries first. Items that have been
        processing for longer than stale_timeout_minutes are considered
        abandoned and will be returned again.

        Args:
            limit: Maximum number of entries to return.
            stale_timeout_minutes: Minutes after which a processing item is considered stale.

        Returns:
            List of queue entries as dicts.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Get items that are either not started or stale
            cursor = await db.execute(
                """
                SELECT id, message_id, from_addr, subject, snippet,
                       created_at, retries
                FROM classification_queue
                WHERE processed_at IS NULL
                  AND (processing_started_at IS NULL
                       OR processing_started_at < datetime('now', ?))
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (f"-{stale_timeout_minutes} minutes", limit)
            )
            rows = await cursor.fetchall()
            entries = [dict(row) for row in rows]

            # Mark these items as in-progress
            if entries:
                message_ids = [e["message_id"] for e in entries]
                placeholders = ",".join("?" * len(message_ids))
                await db.execute(
                    f"""
                    UPDATE classification_queue
                    SET processing_started_at = CURRENT_TIMESTAMP
                    WHERE message_id IN ({placeholders})
                    """,
                    message_ids
                )
                await db.commit()

            return entries

    async def mark_processed(
        self,
        message_id: str,
        classification_result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        """Mark a queue entry as processed.

        Args:
            message_id: Gmail message ID.
            classification_result: Classification result dict (JSON-serializable).
            error: Error message if processing failed.
        """
        result_json = json.dumps(classification_result) if classification_result else None

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE classification_queue
                SET processed_at = CURRENT_TIMESTAMP,
                    classification_result = ?,
                    error = ?
                WHERE message_id = ?
                """,
                (result_json, error, message_id)
            )
            await db.commit()

    async def increment_retry(self, message_id: str) -> int:
        """Increment retry count for a failed entry.

        Args:
            message_id: Gmail message ID.

        Returns:
            New retry count.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE classification_queue
                SET retries = retries + 1
                WHERE message_id = ?
                """,
                (message_id,)
            )
            await db.commit()

            cursor = await db.execute(
                "SELECT retries FROM classification_queue WHERE message_id = ?",
                (message_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def cleanup_old_entries(self, days: int = 7) -> int:
        """Delete processed entries older than specified days.

        Args:
            days: Delete entries older than this many days.

        Returns:
            Number of deleted entries.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM classification_queue
                WHERE processed_at IS NOT NULL
                  AND created_at < ?
                """,
                (cutoff.isoformat(),)
            )
            await db.commit()
            return cursor.rowcount

    async def get_stats(self) -> dict:
        """Get queue statistics.

        Returns:
            Dict with pending, processed, failed counts.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Pending count
            cursor = await db.execute(
                "SELECT COUNT(*) FROM classification_queue WHERE processed_at IS NULL"
            )
            pending = (await cursor.fetchone())[0]

            # Processed count (successful)
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM classification_queue
                WHERE processed_at IS NOT NULL AND error IS NULL
                """
            )
            processed = (await cursor.fetchone())[0]

            # Failed count
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM classification_queue
                WHERE processed_at IS NOT NULL AND error IS NOT NULL
                """
            )
            failed = (await cursor.fetchone())[0]

            # Oldest pending
            cursor = await db.execute(
                """
                SELECT created_at FROM classification_queue
                WHERE processed_at IS NULL
                ORDER BY created_at ASC LIMIT 1
                """
            )
            oldest_row = await cursor.fetchone()
            oldest_pending = oldest_row[0] if oldest_row else None

            return {
                "pending": pending,
                "processed": processed,
                "failed": failed,
                "oldest_pending": oldest_pending,
            }

    async def exists(self, message_id: str) -> bool:
        """Check if a message is already in the queue.

        Args:
            message_id: Gmail message ID.

        Returns:
            True if message exists in queue.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM classification_queue WHERE message_id = ?",
                (message_id,)
            )
            return await cursor.fetchone() is not None


# Singleton instance with thread-safe initialization
_queue: Optional[ClassificationQueue] = None
_queue_lock = asyncio.Lock()


async def get_queue(db_path: Optional[str] = None) -> ClassificationQueue:
    """Get or create the queue singleton.

    Thread-safe initialization using asyncio.Lock.

    Args:
        db_path: Database path (only used on first call).

    Returns:
        Initialized ClassificationQueue instance.
    """
    global _queue
    async with _queue_lock:
        if _queue is None:
            from config import get_config
            path = db_path or get_config().queue_db_path
            _queue = ClassificationQueue(path)
            await _queue.init()
    return _queue
