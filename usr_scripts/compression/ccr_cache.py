"""
ccr_cache.py – Compress-Cache-Retrieve layer using SQLite.

Stores originals alongside their compressed representations so an agent
can later expand a short ``ref_key`` back to the full context.  Entries
expire after a configurable TTL and the cache exposes a
``get_frequently_retrieved`` query for the TOIN feedback loop.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS compression_cache (
    ref_key      TEXT PRIMARY KEY,
    original     BLOB,
    compressed   TEXT,
    drop_pct     REAL,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at   DATETIME,
    access_count INTEGER DEFAULT 0,
    task_type    TEXT
);
"""


# ---------------------------------------------------------------------------
# CCRCache
# ---------------------------------------------------------------------------


class CCRCache:
    """SQLite-backed Compress-Cache-Retrieve store."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # store
    # ------------------------------------------------------------------

    def store(
        self,
        original: str,
        compressed: str,
        drop_pct: float,
        task_type: str,
        ttl_hours: int = 24,
    ) -> str:
        """Persist an original/compressed pair and return its *ref_key*.

        The *ref_key* is the first 12 hex characters of the SHA-256
        digest of *original*.
        """
        ref_key = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

        self._conn.execute(
            """
            INSERT OR REPLACE INTO compression_cache
                (ref_key, original, compressed, drop_pct, expires_at, access_count, task_type)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                ref_key,
                original.encode("utf-8"),
                compressed,
                drop_pct,
                expires_at.isoformat(),
                task_type,
            ),
        )
        self._conn.commit()
        return ref_key

    # ------------------------------------------------------------------
    # retrieve
    # ------------------------------------------------------------------

    def retrieve(self, ref_key: str) -> str | None:
        """Return the *original* text for *ref_key*, or ``None`` if
        missing / expired."""
        row = self._conn.execute(
            "SELECT original, expires_at FROM compression_cache WHERE ref_key = ?",
            (ref_key,),
        ).fetchone()

        if row is None:
            return None

        original_blob, expires_at_str = row
        expires_at = datetime.fromisoformat(expires_at_str)

        # Normalise to offset-aware UTC for comparison.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > expires_at:
            return None

        self._conn.execute(
            "UPDATE compression_cache SET access_count = access_count + 1 WHERE ref_key = ?",
            (ref_key,),
        )
        self._conn.commit()

        if isinstance(original_blob, bytes):
            return original_blob.decode("utf-8")
        return original_blob  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    def cleanup_expired(self) -> None:
        """Delete all rows whose TTL has elapsed."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "DELETE FROM compression_cache WHERE expires_at < ?",
            (now,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # frequently retrieved
    # ------------------------------------------------------------------

    def get_frequently_retrieved(self, threshold: float = 0.3) -> list[str]:
        """Return *ref_keys* whose ``access_count`` is in the top
        *threshold* fraction (default 30 %) of all entries.

        Used by the TOIN feedback loop to identify contexts that are
        repeatedly expanded and should therefore be kept lossless.
        """
        rows = self._conn.execute(
            "SELECT ref_key, access_count FROM compression_cache ORDER BY access_count DESC"
        ).fetchall()

        if not rows:
            return []

        cutoff_index = max(1, int(len(rows) * threshold))
        return [r[0] for r in rows[:cutoff_index]]

    # ------------------------------------------------------------------
    # close
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def expand_context(ref_key: str, db_path: str) -> str | None:
    """Open a :class:`CCRCache`, retrieve the original for *ref_key*,
    close, and return it (or ``None``)."""
    cache = CCRCache(db_path)
    try:
        return cache.retrieve(ref_key)
    finally:
        cache.close()
