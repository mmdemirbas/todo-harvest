"""SQLite-backed sync mapping and conflict resolution.

Tracks local_id ↔ (source, source_id) relationships, timestamps for
conflict resolution, and a sync log for auditability.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("mapping.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SyncMapping:
    """SQLite-backed ID mapping and conflict resolution."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._create_tables()
        return self._conn

    def _create_tables(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_map (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                local_id            TEXT NOT NULL,
                source              TEXT NOT NULL,
                source_id           TEXT NOT NULL,
                last_synced_at      TEXT,
                local_updated_at    TEXT,
                source_updated_at   TEXT,
                UNIQUE(source, source_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                source      TEXT NOT NULL,
                action      TEXT NOT NULL,
                item_count  INTEGER NOT NULL,
                details     TEXT
            )
        """)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SyncMapping:
        self._connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- ID mapping ----------------------------------------------------------

    def get_local_id(self, source: str, source_id: str) -> str | None:
        """Look up local_id for a (source, source_id) pair. Returns None if not found."""
        conn = self._connect()
        row = conn.execute(
            "SELECT local_id FROM sync_map WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        return row["local_id"] if row else None

    def get_source_id(self, local_id: str, source: str) -> str | None:
        """Look up source_id for a (local_id, source) pair."""
        conn = self._connect()
        row = conn.execute(
            "SELECT source_id FROM sync_map WHERE local_id = ? AND source = ?",
            (local_id, source),
        ).fetchone()
        return row["source_id"] if row else None

    def generate_local_id(self) -> str:
        """Generate a new stable local UUID."""
        return str(uuid.uuid4())

    def upsert(
        self,
        local_id: str,
        source: str,
        source_id: str,
        source_updated_at: str | None = None,
        local_updated_at: str | None = None,
    ) -> None:
        """Insert or update a mapping entry."""
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO sync_map (local_id, source, source_id, source_updated_at, local_updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source, source_id) DO UPDATE SET
                local_id = excluded.local_id,
                source_updated_at = excluded.source_updated_at,
                local_updated_at = excluded.local_updated_at
            """,
            (local_id, source, source_id, source_updated_at, local_updated_at),
        )
        conn.commit()

    def mark_synced(self, local_id: str, source: str) -> None:
        """Update last_synced_at to now for a (local_id, source) pair."""
        conn = self._connect()
        now = _now_iso()
        conn.execute(
            "UPDATE sync_map SET last_synced_at = ? WHERE local_id = ? AND source = ?",
            (now, local_id, source),
        )
        conn.commit()

    def get_last_synced_at(self, local_id: str, source: str) -> str | None:
        """Get last_synced_at for a (local_id, source) pair."""
        conn = self._connect()
        row = conn.execute(
            "SELECT last_synced_at FROM sync_map WHERE local_id = ? AND source = ?",
            (local_id, source),
        ).fetchone()
        return row["last_synced_at"] if row else None

    # -- Conflict resolution -------------------------------------------------

    @staticmethod
    def resolve_conflict(
        field: str,
        local_value: Any,
        local_updated_at: str | None,
        source_value: Any,
        source_updated_at: str | None,
        last_synced_at: str | None,
    ) -> tuple[Any, str]:
        """Resolve a conflict between local and source values.

        Returns (winning_value, winner_label) where winner_label is "local" or "source".

        Strategy:
        - If values are equal: no conflict, return local (arbitrary).
        - If one side updated after last sync and the other didn't: that side wins.
        - If both updated after last sync (true conflict): source wins (latest external data).
        - If no timestamps available: source wins (prefer fresh data on pull).
        """
        if local_value == source_value:
            return local_value, "local"

        # If we have timestamps, use them
        if last_synced_at and local_updated_at and source_updated_at:
            local_changed = local_updated_at > last_synced_at
            source_changed = source_updated_at > last_synced_at
            if local_changed and not source_changed:
                return local_value, "local"
            if source_changed and not local_changed:
                return source_value, "source"
            # Both changed — source wins (prefer external data on pull)
            return source_value, "source"

        # No timestamps — source wins
        return source_value, "source"

    # -- Sync log ------------------------------------------------------------

    def log_sync(self, source: str, action: str, item_count: int, details: str | None = None) -> None:
        """Append an entry to the sync log."""
        conn = self._connect()
        conn.execute(
            "INSERT INTO sync_log (timestamp, source, action, item_count, details) VALUES (?, ?, ?, ?, ?)",
            (_now_iso(), source, action, item_count, details),
        )
        conn.commit()

    def get_sync_log(self, limit: int = 50) -> list[dict]:
        """Return recent sync log entries."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT timestamp, source, action, item_count, details FROM sync_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
