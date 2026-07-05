"""Tiny SQLite layer for caching search results and logging user questions.

Only public facility metadata is cached. Questions are stored to help iterate on
the assistant; they should not contain PHI and the frontend does not collect any.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from .config import get_settings

CACHE_TTL_SECONDS = 15 * 60


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS search_cache (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                parsed_service TEXT,
                parsed_location TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )


def get_cached(key: str) -> Optional[Any]:
    with _conn() as c:
        row = c.execute(
            "SELECT payload, created_at FROM search_cache WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return None
    if time.time() - row["created_at"] > CACHE_TTL_SECONDS:
        return None
    return json.loads(row["payload"])


def set_cached(key: str, payload: Any) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO search_cache (key, payload, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload), int(time.time())),
        )


def log_question(
    question: str, parsed_service: Optional[str], parsed_location: Optional[str]
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO searches (question, parsed_service, parsed_location, created_at) VALUES (?, ?, ?, ?)",
            (question, parsed_service, parsed_location, int(time.time())),
        )
