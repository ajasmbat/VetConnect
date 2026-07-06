"""Tiny SQLite layer for caching results and logging user questions.

Two tables live here:
  * `search_cache` — keyed by an arbitrary string, holds a JSON blob and a
    timestamp. Anything older than `CACHE_TTL_SECONDS` is treated as expired.
  * `searches`     — an append-only log of the questions users ask, useful for
    iterating on the assistant prompt. Contains no PHI.

The file lives at the path in `Settings.sqlite_path` (default: `vetconnect.db`).
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from .config import get_settings

# Cached items are considered fresh for 15 minutes. Short enough to reflect VA
# data changes; long enough that a quick user session avoids repeat network hops.
CACHE_TTL_SECONDS = 15 * 60


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection, commit on success, always close.

    Used as a `with _conn() as c:` block internally. Not part of the public
    API — everything goes through the helper functions below.

    Yields:
        sqlite3.Connection: a live connection with `Row` factory enabled.
    """
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the tables if they don't already exist.

    Safe to call every process start; called from FastAPI's lifespan hook in
    `main.py`.

    Returns:
        None.
    """
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
    """Look up a cached value by key.

    Args:
        key: Any string uniquely identifying the query (callers hash their
            query params into a JSON string; see `main._cache_key`).

    Returns:
        The stored value (already JSON-decoded), or `None` if there was no
        row or the row is older than `CACHE_TTL_SECONDS`.
    """
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
    """Store a value in the cache under `key`, overwriting anything already there.

    Args:
        key:     The lookup key (same string you'll pass to `get_cached`).
        payload: Any JSON-serializable value.

    Returns:
        None.
    """
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO search_cache (key, payload, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload), int(time.time())),
        )


def log_question(
    question: str, parsed_service: Optional[str], parsed_location: Optional[str]
) -> None:
    """Append a user question to the `searches` table.

    We store the raw question plus whatever the parser thought it meant. This
    is a development aid — it lets us look at real questions the parser got
    wrong and improve the prompt/aliases.

    Args:
        question:        The exact text the user submitted.
        parsed_service:  Service the parser matched, or None.
        parsed_location: Location the parser extracted, or None.

    Returns:
        None.
    """
    with _conn() as c:
        c.execute(
            "INSERT INTO searches (question, parsed_service, parsed_location, created_at) VALUES (?, ?, ?, ?)",
            (question, parsed_service, parsed_location, int(time.time())),
        )
