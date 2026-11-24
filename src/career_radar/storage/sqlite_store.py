"""SQLite incremental job store supporting NEW, UPDATED, UNCHANGED, and CLOSED diffs."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional, Sequence

from career_radar.models import (
    ATSProvider,
    JobChangeType,
    JobDiff,
    JobPosting,
    ScanResult,
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    new_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    unchanged_count INTEGER NOT NULL DEFAULT 0,
    closed_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    department TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    raw_json TEXT NOT NULL,
    UNIQUE(company_name, external_id)
);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id INTEGER NOT NULL,
    company_name TEXT NOT NULL,
    external_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    old_hash TEXT,
    new_hash TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(scan_run_id) REFERENCES scan_runs(id)
);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_posting(row: sqlite3.Row) -> JobPosting:
    raw_payload: dict[str, Any] = json.loads(row["raw_json"]) if row["raw_json"] else {}
    return JobPosting(
        company=row["company_name"],
        provider=ATSProvider(row["provider"]),
        external_id=row["external_id"],
        title=row["title"],
        location=row["location"],
        department=row["department"],
        url=row["url"],
        description=row["description"],
        raw_payload=raw_payload,
        content_hash=row["content_hash"],
    )


class SQLiteJobStore:
    """Persistent SQLite repository for incremental ATS scan tracking."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

    def _connect(self) -> closing[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return closing(conn)

    def record_scan(
        self,
        company_name: str,
        provider: ATSProvider,
        postings: Sequence[JobPosting],
        *,
        mark_missing_closed: bool = True,
    ) -> ScanResult:
        """Persist a company scan and compute NEW/UPDATED/UNCHANGED/CLOSED diffs."""
        if not company_name.strip():
            raise ValueError("company_name must not be empty.")
        seen_ids: set[str] = set()
        for posting in postings:
            if posting.company != company_name:
                raise ValueError(
                    f"Posting '{posting.external_id}' belongs to '{posting.company}', "
                    f"expected '{company_name}'."
                )
            if posting.external_id in seen_ids:
                raise ValueError(
                    f"Duplicate external_id '{posting.external_id}' in scan for '{company_name}'."
                )
            seen_ids.add(posting.external_id)

        now = _utc_now_iso()
        diffs: list[JobDiff] = []
        new_count = 0
        updated_count = 0
        unchanged_count = 0
        closed_count = 0

        with self._connect() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO scan_runs (company_name, provider, started_at, status)
                    VALUES (?, ?, ?, 'running')
                    """,
                    (company_name, provider.value, now),
                )
                scan_run_id = int(cursor.lastrowid)

                existing_rows = {
                    row["external_id"]: row
                    for row in conn.execute(
                        "SELECT * FROM jobs WHERE company_name = ?",
                        (company_name,),
                    ).fetchall()
                }

                for posting in postings:
                    raw_json = json.dumps(dict(posting.raw_payload), ensure_ascii=False)
                    existing = existing_rows.get(posting.external_id)

                    if existing is None:
                        conn.execute(
                            """
                            INSERT INTO jobs (
                                company_name, provider, external_id, title, location,
                                department, url, description, content_hash,
                                first_seen_at, last_seen_at, is_active, raw_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                            """,
                            (
                                company_name,
                                posting.provider.value,
                                posting.external_id,
                                posting.title,
                                posting.location,
                                posting.department,
                                posting.url,
                                posting.description,
                                posting.content_hash,
                                now,
                                now,
                                raw_json,
                            ),
                        )
                        conn.execute(
                            """
                            INSERT INTO job_events (
                                scan_run_id, company_name, external_id, event_type,
                                old_hash, new_hash, created_at
                            ) VALUES (?, ?, ?, ?, NULL, ?, ?)
                            """,
                            (
                                scan_run_id,
                                company_name,
                                posting.external_id,
                                JobChangeType.NEW.value,
                                posting.content_hash,
                                now,
                            ),
                        )
                        diffs.append(JobDiff(posting=posting, change_type=JobChangeType.NEW))
                        new_count += 1
                    elif int(existing["is_active"]) == 0 or existing["content_hash"] != posting.content_hash:
                        old_hash = str(existing["content_hash"])
                        conn.execute(
                            """
                            UPDATE jobs
                            SET provider = ?, title = ?, location = ?, department = ?,
                                url = ?, description = ?, content_hash = ?,
                                last_seen_at = ?, is_active = 1, raw_json = ?
                            WHERE company_name = ? AND external_id = ?
                            """,
                            (
                                posting.provider.value,
                                posting.title,
                                posting.location,
                                posting.department,
                                posting.url,
                                posting.description,
                                posting.content_hash,
                                now,
                                raw_json,
                                company_name,
                                posting.external_id,
                            ),
                        )
                        conn.execute(
                            """
                            INSERT INTO job_events (
                                scan_run_id, company_name, external_id, event_type,
                                old_hash, new_hash, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                scan_run_id,
                                company_name,
                                posting.external_id,
                                JobChangeType.UPDATED.value,
                                old_hash,
                                posting.content_hash,
                                now,
                            ),
                        )
                        diffs.append(
                            JobDiff(
                                posting=posting,
                                change_type=JobChangeType.UPDATED,
                                previous_hash=old_hash,
                            )
                        )
                        updated_count += 1
                    else:
                        conn.execute(
                            """
                            UPDATE jobs SET last_seen_at = ?
                            WHERE company_name = ? AND external_id = ?
                            """,
                            (now, company_name, posting.external_id),
                        )
                        diffs.append(
                            JobDiff(
                                posting=posting,
                                change_type=JobChangeType.UNCHANGED,
                                previous_hash=posting.content_hash,
                            )
                        )
                        unchanged_count += 1

                if mark_missing_closed:
                    for external_id, existing in existing_rows.items():
                        if external_id not in seen_ids and int(existing["is_active"]) == 1:
                            conn.execute(
                                """
                                UPDATE jobs SET is_active = 0
                                WHERE company_name = ? AND external_id = ?
                                """,
                                (company_name, external_id),
                            )
                            old_hash = str(existing["content_hash"])
                            conn.execute(
                                """
                                INSERT INTO job_events (
                                    scan_run_id, company_name, external_id, event_type,
                                    old_hash, new_hash, created_at
                                ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                                """,
                                (
                                    scan_run_id,
                                    company_name,
                                    external_id,
                                    JobChangeType.CLOSED.value,
                                    old_hash,
                                    now,
                                ),
                            )
                            diffs.append(
                                JobDiff(
                                    posting=_row_to_posting(existing),
                                    change_type=JobChangeType.CLOSED,
                                    previous_hash=old_hash,
                                )
                            )
                            closed_count += 1

                finished_at = _utc_now_iso()
                conn.execute(
                    """
                    UPDATE scan_runs
                    SET finished_at = ?, status = 'completed',
                        new_count = ?, updated_count = ?, unchanged_count = ?, closed_count = ?
                    WHERE id = ?
                    """,
                    (
                        finished_at,
                        new_count,
                        updated_count,
                        unchanged_count,
                        closed_count,
                        scan_run_id,
                    ),
                )

        return ScanResult(
            company_name=company_name,
            provider=provider,
            scan_run_id=scan_run_id,
            diffs=tuple(diffs),
            new_count=new_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            closed_count=closed_count,
        )

    def list_active_jobs(self, company_name: Optional[str] = None) -> list[JobPosting]:
        """Return currently active postings stored in SQLite."""
        with self._connect() as conn:
            if company_name is not None:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE is_active = 1 AND company_name = ? ORDER BY id",
                    (company_name,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs WHERE is_active = 1 ORDER BY id").fetchall()
        return [_row_to_posting(row) for row in rows]

    def list_events(self, company_name: Optional[str] = None) -> list[dict[str, Any]]:
        """Return recorded state-change events ordered chronologically."""
        with self._connect() as conn:
            if company_name is not None:
                rows = conn.execute(
                    "SELECT * FROM job_events WHERE company_name = ? ORDER BY id",
                    (company_name,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM job_events ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def update_job_description(
        self,
        company_name: str,
        external_id: str,
        description: str,
    ) -> None:
        """Persist enriched full JD text without mutating list-level content_hash."""
        with self._connect() as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE jobs SET description = ?
                    WHERE company_name = ? AND external_id = ?
                    """,
                    (description, company_name, external_id),
                )

    def record_scan_error(
        self,
        company_name: str,
        provider: ATSProvider,
        error_message: str,
    ) -> int:
        """Persist an isolated scan failure without mutating existing active jobs."""
        if not company_name.strip():
            raise ValueError("company_name must not be empty.")
        now = _utc_now_iso()
        with self._connect() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO scan_runs (
                        company_name, provider, started_at, finished_at, status, error_message
                    ) VALUES (?, ?, ?, ?, 'error', ?)
                    """,
                    (company_name, provider.value, now, now, error_message),
                )
                return int(cursor.lastrowid)

    def list_scan_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent scan_runs ordered from newest to oldest."""
        safe_limit = max(1, int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]
