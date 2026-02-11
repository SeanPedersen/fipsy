"""SQLite storage for discovered IPNS keys."""

import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".config" / "fipsy" / "discovered.db"


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the database schema."""
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS discovered (
                node_id TEXT NOT NULL,
                ipns_name TEXT NOT NULL,
                name TEXT,
                PRIMARY KEY (node_id, ipns_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS published (
                path TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                added TEXT NOT NULL
            )
        """)
        conn.commit()


def upsert_discovered(node_id: str, ipns_name: str, name: str | None = None) -> None:
    """Insert or update a discovered IPNS key or peer index."""
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO discovered (node_id, ipns_name, name)
            VALUES (?, ?, ?)
            ON CONFLICT(node_id, ipns_name) DO UPDATE SET
                name = excluded.name
            """,
            (node_id, ipns_name, name),
        )
        conn.commit()


def list_discovered() -> list[dict]:
    """List all discovered IPNS names."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT node_id, ipns_name, name FROM discovered ORDER BY node_id, name"
        ).fetchall()
        return [dict(row) for row in rows]


def upsert_published(path: str, key: str) -> None:
    """Insert or update a published directory."""
    from datetime import datetime, timezone

    added = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO published (path, key, added)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                key = excluded.key,
                added = excluded.added
            """,
            (path, key, added),
        )
        conn.commit()


def list_published() -> list[dict]:
    """List all published directories."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT path, key, added FROM published ORDER BY key"
        ).fetchall()
        return [dict(row) for row in rows]


def delete_published(path: str) -> bool:
    """Delete a published directory by path. Returns True if deleted."""
    with _get_connection() as conn:
        cursor = conn.execute("DELETE FROM published WHERE path = ?", (path,))
        conn.commit()
        return cursor.rowcount > 0
