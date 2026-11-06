"""SQLite memory for the active session and a short long-term summary.

Session rows keep the conversation across turns and process restarts.
Long-term rows keep a few lines per user so a new session still knows what
that person has been working on. Negative feedback is read back into the next
prompt as a steer toward shorter, cited answers.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from app.config import get_settings

_LOCK = threading.Lock()
_READY = False


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    settings.resolved_memory_db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.resolved_memory_db, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    global _READY
    with _LOCK:
        if _READY:
            return
        with _connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS long_term (
                    user_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
        _READY = True


def ensure_session(session_id: str, user_id: str) -> None:
    init_db()
    with _LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT user_id FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO sessions (session_id, user_id, created_at) VALUES (?, ?, ?)",
                (session_id, user_id, _now()),
            )
            return
        if row["user_id"] != user_id:
            from app.errors import AppError

            raise AppError("forbidden", "That session belongs to another user.", 403)


def add_message(session_id: str, user_id: str, role: str, content: str) -> None:
    init_db()
    with _LOCK, _connect() as connection:
        connection.execute(
            "INSERT INTO messages (session_id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, role, content, _now()),
        )


def recent_messages(session_id: str, user_id: str, limit: int = 8) -> list[dict]:
    init_db()
    with _LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT role, content, created_at FROM messages
            WHERE session_id = ? AND user_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (session_id, user_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def long_term_summary(user_id: str) -> str:
    init_db()
    with _LOCK, _connect() as connection:
        row = connection.execute("SELECT summary FROM long_term WHERE user_id = ?", (user_id,)).fetchone()
    return row["summary"] if row else ""


def remember(user_id: str, line: str) -> str:
    """Append one line and keep the latest twenty."""

    init_db()
    current = long_term_summary(user_id)
    lines = [item for item in current.splitlines() if item.strip()]
    lines.append(line.strip())
    summary = "\n".join(lines[-20:])
    with _LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO long_term (user_id, summary, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at
            """,
            (user_id, summary, _now()),
        )
    return summary


def add_feedback(session_id: str, user_id: str, rating: int, comment: str) -> None:
    init_db()
    with _LOCK, _connect() as connection:
        connection.execute(
            "INSERT INTO feedback (session_id, user_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, rating, comment.strip(), _now()),
        )


def latest_feedback(user_id: str) -> dict | None:
    init_db()
    with _LOCK, _connect() as connection:
        row = connection.execute(
            """
            SELECT rating, comment, created_at FROM feedback
            WHERE user_id = ? ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def feedback_note(user_id: str) -> str:
    latest = latest_feedback(user_id)
    if latest and int(latest["rating"]) <= 2:
        return (
            "The user rated a recent answer poorly. Prefer a shorter answer, cite only "
            "retrieved documents, and say so when the evidence is incomplete."
        )
    return ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
