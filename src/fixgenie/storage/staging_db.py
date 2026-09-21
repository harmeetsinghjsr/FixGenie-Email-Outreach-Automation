"""
SQLite staging layer.

Why a local DB at all when the "real" store is Google Sheets?
  - Sheets API has rate limits and latency; hammering it during a scrape is slow
    and fragile. We stage everything locally first, then push clean rows in a
    batch. This is the pattern recommended in Section 8 of the requirements.
  - It gives us a durable place to hold raw discovery output so enrichment /
    validation can re-run without re-scraping (Section 12: "cache so you can
    re-parse without re-hitting the source").
  - It's free and built into Python. No server.

Flow of a lead through the DB:
    stage(raw) -> status 'new'
    enrich     -> status 'enriched'
    validate   -> status 'validated'
    push       -> status 'pushed' (now lives in Sheets too)
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import Lead

log = get_logger(__name__)


class StagingDB:
    """Thin wrapper over a SQLite table of leads keyed by deterministic lead_id."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id      TEXT PRIMARY KEY,
                    stage        TEXT NOT NULL DEFAULT 'new',
                    data         TEXT NOT NULL,          -- full Lead as JSON
                    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stage ON leads(stage)")

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def upsert(self, lead: Lead, stage: str = "new") -> bool:
        """
        Insert a lead or update it if the lead_id already exists.

        Returns True if this was a NEW row, False if it updated an existing one.
        This exact-id check is the cheap first-pass dedup (fuzzy dedup lives in
        the dedup module and runs against the Sheet before pushing).
        """
        payload = json.dumps(lead.to_dict(), ensure_ascii=False)
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT 1 FROM leads WHERE lead_id = ?", (lead.lead_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE leads SET data = ?, stage = ?, updated_at = datetime('now') "
                    "WHERE lead_id = ?",
                    (payload, stage, lead.lead_id),
                )
                return False
            conn.execute(
                "INSERT INTO leads (lead_id, stage, data) VALUES (?, ?, ?)",
                (lead.lead_id, stage, payload),
            )
            return True

    def set_stage(self, lead_id: str, stage: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE leads SET stage = ?, updated_at = datetime('now') WHERE lead_id = ?",
                (stage, lead_id),
            )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_by_stage(self, stage: str) -> list[Lead]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT data FROM leads WHERE stage = ? ORDER BY created_at", (stage,)
            ).fetchall()
        return [Lead.from_dict(json.loads(r["data"])) for r in rows]

    def all_leads(self) -> list[Lead]:
        with self._conn() as conn:
            rows = conn.execute("SELECT data FROM leads ORDER BY created_at").fetchall()
        return [Lead.from_dict(json.loads(r["data"])) for r in rows]

    def counts_by_stage(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT stage, COUNT(*) AS n FROM leads GROUP BY stage"
            ).fetchall()
        return {r["stage"]: r["n"] for r in rows}

    def exists(self, lead_id: str) -> bool:
        with self._conn() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM leads WHERE lead_id = ?", (lead_id,)
                ).fetchone()
                is not None
            )
