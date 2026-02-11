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
                ipns_key TEXT NOT NULL,
                name TEXT,
                PRIMARY KEY (node_id, ipns_key)
            )
        """)
        conn.commit()


def upsert_discovered(
    node_id: str, ipns_key: str, name: str | None = None
) -> None:
    """Insert or update a discovered IPNS key or peer index."""
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO discovered (node_id, ipns_key, name)
            VALUES (?, ?, ?)
            ON CONFLICT(node_id, ipns_key) DO UPDATE SET
                name = excluded.name
            """,
            (node_id, ipns_key, name),
        )
        conn.commit()


def list_discovered() -> list[dict]:
    """List all discovered IPNS keys."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT node_id, ipns_key, name FROM discovered ORDER BY node_id, name"
        ).fetchall()
        return [dict(row) for row in rows]
