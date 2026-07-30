"""
State tracking and idempotency storage using SQLite for Telegram Bot Service.
"""

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional, List


class StateManager:
    """Thread-safe SQLite state manager for transcription requests and idempotency."""

    def __init__(self, db_path: Path | str = "telegram_bot.db"):
        self.db_path = str(db_path)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Create database table and indexes if they do not exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    update_id INTEGER UNIQUE,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    status_message_id INTEGER,
                    file_id TEXT,
                    workflow_run_id INTEGER,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_status ON requests (user_id, status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_update_id ON requests (update_id)"
            )
            conn.commit()

    def get_by_update_id(self, update_id: int) -> Optional[Dict[str, Any]]:
        """Fetch request record by Telegram update_id for duplicate check."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM requests WHERE update_id = ?",
                (update_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_by_request_id(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Fetch request record by UUID request_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM requests WHERE request_id = ?",
                (request_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def has_active_request_for_user(self, user_id: int) -> bool:
        """Check if user has an active (queued/dispatching/running) transcription."""
        active_statuses = ("received", "dispatching", "queued", "running")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND status IN (?, ?, ?, ?)
                """,
                (user_id, *active_statuses),
            )
            count = cursor.fetchone()[0]
            return count > 0

    def create_request(
        self,
        request_id: str,
        update_id: int,
        user_id: int,
        chat_id: int,
        status_message_id: Optional[int] = None,
        file_id: Optional[str] = None,
        status: str = "received",
    ) -> bool:
        """
        Record a new transcription request.
        Returns True if inserted successfully, False if update_id or request_id already exists.
        """
        now = time.time()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO requests (
                        request_id, update_id, user_id, chat_id, 
                        status_message_id, file_id, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        update_id,
                        user_id,
                        chat_id,
                        status_message_id,
                        file_id,
                        status,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def update_request_status(
        self,
        request_id: str,
        status: str,
        workflow_run_id: Optional[int] = None,
        status_message_id: Optional[int] = None,
    ) -> bool:
        """Update request state and optional workflow run ID."""
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if workflow_run_id is not None and status_message_id is not None:
                cursor.execute(
                    """
                    UPDATE requests 
                    SET status = ?, workflow_run_id = ?, status_message_id = ?, updated_at = ?
                    WHERE request_id = ?
                    """,
                    (status, workflow_run_id, status_message_id, now, request_id),
                )
            elif workflow_run_id is not None:
                cursor.execute(
                    """
                    UPDATE requests 
                    SET status = ?, workflow_run_id = ?, updated_at = ?
                    WHERE request_id = ?
                    """,
                    (status, workflow_run_id, now, request_id),
                )
            elif status_message_id is not None:
                cursor.execute(
                    """
                    UPDATE requests 
                    SET status = ?, status_message_id = ?, updated_at = ?
                    WHERE request_id = ?
                    """,
                    (status, status_message_id, now, request_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE requests 
                    SET status = ?, updated_at = ?
                    WHERE request_id = ?
                    """,
                    (status, now, request_id),
                )
            conn.commit()
            return cursor.rowcount > 0
