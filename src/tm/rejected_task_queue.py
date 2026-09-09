"""Durable, claim-safe queue for source-based rejected-translation retries.

The queue stores only task identity and lifecycle metadata.  Source and accepted
candidate bytes remain in the Hugo content tree; terminal receipts intentionally
contain hashes and counts rather than translated text.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .retry_records import RejectedTranslationTask


class RejectedTaskQueue:
    """SQLite WAL queue with atomic claims and idempotent task identity."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS rejected_tasks (
                    task_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    claim_owner TEXT, claim_until REAL, error_code TEXT,
                    receipt TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS rejected_tasks_claim "
                "ON rejected_tasks(state, claim_until, created_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def task_id(task: RejectedTranslationTask) -> str:
        stable = "\x1f".join(
            (task.campaign_id, task.site_id, task.source_path, task.output_path,
             task.source_sha256, task.target_lang, task.failure_fingerprint)
        )
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    @staticmethod
    def _payload(task: RejectedTranslationTask) -> dict[str, Any]:
        return {
            "schema_version": task.schema_version,
            "campaign_id": task.campaign_id,
            "site_id": task.site_id,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "source_sha256": task.source_sha256,
            "target_lang": task.target_lang,
            "failure_category": task.failure_category,
            "failure_fingerprint": task.failure_fingerprint,
            "retry_budget": task.retry_budget,
            "model_target": task.model_target,
            "state": task.state,
            "terminal_receipt_id": task.terminal_receipt_id,
            "terminal_ticket_id": task.terminal_ticket_id,
            **task.extensions,
        }

    def enqueue(self, task: RejectedTranslationTask) -> str:
        if task.state != "QUEUED":
            raise ValueError("only QUEUED retry tasks may be enqueued")
        task_id = self.task_id(task)
        now = time.time()
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO rejected_tasks"
                "(task_id,payload,state,created_at,updated_at) VALUES(?,?,?,?,?)",
                (task_id, json.dumps(self._payload(task), sort_keys=True), "QUEUED", now, now),
            )
        return task_id

    def claim(self, owner: str, *, limit: int = 1, lease_seconds: float = 300) -> list[tuple[str, RejectedTranslationTask, int]]:
        if not owner or limit < 1 or lease_seconds <= 0:
            raise ValueError("owner, positive limit, and positive lease_seconds are required")
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT task_id,payload,attempts FROM rejected_tasks
                   WHERE state='QUEUED' OR (state='CLAIMED' AND claim_until < ?)
                   ORDER BY created_at,task_id LIMIT ?""",
                (now, limit),
            ).fetchall()
            db.executemany(
                "UPDATE rejected_tasks SET state='CLAIMED',attempts=attempts+1,"
                "claim_owner=?,claim_until=?,updated_at=?,error_code=NULL WHERE task_id=?",
                [(owner, now + lease_seconds, now, row[0]) for row in rows],
            )
            db.execute("COMMIT")
        return [(row[0], RejectedTranslationTask.from_mapping(json.loads(row[1])), row[2] + 1) for row in rows]

    def accepted(self, task_id: str, owner: str, receipt: dict[str, Any]) -> None:
        self._terminal(task_id, owner, "ACCEPTED", receipt=receipt)

    def dead_letter(self, task_id: str, owner: str, code: str) -> None:
        self._terminal(task_id, owner, "DEAD_LETTER", error_code=code)

    def operator_dead_letter(self, task_id: str, code: str) -> None:
        """Safely terminate queued/claimed work during operator recovery.

        This deliberately refuses accepted and already terminal work, preserving
        its receipt as immutable evidence.  No task payload is returned.
        """
        code = str(code).strip()
        if not code or len(code) > 120:
            raise ValueError("dead-letter reason must be 1..120 characters")
        with self._connect() as db:
            changed = db.execute(
                "UPDATE rejected_tasks SET state='DEAD_LETTER',claim_owner=NULL,claim_until=NULL,"
                "error_code=?,updated_at=? WHERE task_id=? AND state IN ('QUEUED','CLAIMED')",
                (code, time.time(), task_id),
            ).rowcount
        if changed != 1:
            raise RuntimeError("task is absent or already terminal")

    def attach_intent(self, task_id: str, intent_id: str) -> None:
        """Attach the post-receipt TM intent correlation without candidate bytes."""
        with self._connect() as db:
            row = db.execute(
                "SELECT receipt FROM rejected_tasks WHERE task_id=? AND state='ACCEPTED'", (task_id,)
            ).fetchone()
            if row is None or not row[0]:
                raise RuntimeError("accepted retry task has no receipt")
            receipt = json.loads(row[0])
            receipt["tm_intent_id"] = intent_id
            db.execute(
                "UPDATE rejected_tasks SET receipt=?,updated_at=? WHERE task_id=? AND state='ACCEPTED'",
                (json.dumps(receipt, sort_keys=True), time.time(), task_id),
            )

    def retry(self, task_id: str, owner: str, code: str) -> None:
        now = time.time()
        with self._connect() as db:
            changed = db.execute(
                "UPDATE rejected_tasks SET state='QUEUED',claim_owner=NULL,claim_until=NULL,"
                "error_code=?,updated_at=? WHERE task_id=? AND state='CLAIMED' AND claim_owner=?",
                (code, now, task_id, owner),
            ).rowcount
        if changed != 1:
            raise RuntimeError("retry task is not owned by this consumer")

    def requeue_expired_claims(self, *, now: float | None = None) -> int:
        """Return abandoned consumer claims to QUEUED without changing attempts."""
        now = time.time() if now is None else now
        with self._connect() as db:
            return db.execute(
                "UPDATE rejected_tasks SET state='QUEUED',claim_owner=NULL,claim_until=NULL,updated_at=? "
                "WHERE state='CLAIMED' AND claim_until < ?",
                (now, now),
            ).rowcount

    def _terminal(self, task_id: str, owner: str, state: str, *, receipt: dict[str, Any] | None = None, error_code: str | None = None) -> None:
        now = time.time()
        with self._connect() as db:
            changed = db.execute(
                "UPDATE rejected_tasks SET state=?,claim_owner=NULL,claim_until=NULL,receipt=?,"
                "error_code=?,updated_at=? WHERE task_id=? AND state='CLAIMED' AND claim_owner=?",
                (state, json.dumps(receipt, sort_keys=True) if receipt else None, error_code, now, task_id, owner),
            ).rowcount
        if changed != 1:
            raise RuntimeError("retry task is not owned by this consumer")

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT state,attempts,error_code,receipt FROM rejected_tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            return None
        return {"state": row[0], "attempts": row[1], "error_code": row[2], "receipt": json.loads(row[3]) if row[3] else None}

    def campaign_outcomes(self, campaign_id: str) -> list[dict[str, Any]]:
        """Return payload-free terminal/active outcome metadata for one campaign.

        This is deliberately an aggregation boundary, not an inspection API:
        source paths, failure detail, and accepted candidate bytes stay out of
        campaign summaries.  It lets the originating campaign account for a
        deferred Professionalize result from its durable terminal receipt.
        """
        with self._connect() as db:
            rows = db.execute(
                "SELECT task_id,payload,state,attempts,error_code,receipt FROM rejected_tasks"
            ).fetchall()
        outcomes: list[dict[str, Any]] = []
        for task_id, payload_raw, state, attempts, error_code, receipt_raw in rows:
            payload = json.loads(payload_raw)
            if payload.get("campaign_id") != campaign_id:
                continue
            receipt = json.loads(receipt_raw) if receipt_raw else {}
            outcomes.append(
                {
                    "task_id": task_id,
                    "state": state,
                    "attempts": attempts,
                    "error_code": error_code,
                    "model_target": str(payload.get("model_target") or "unknown"),
                    "receipt_id": receipt.get("receipt_id"),
                }
            )
        return sorted(outcomes, key=lambda row: str(row["task_id"]))

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute("SELECT state,COUNT(*) FROM rejected_tasks GROUP BY state").fetchall()
        stats = {"QUEUED": 0, "CLAIMED": 0, "ACCEPTED": 0, "DEAD_LETTER": 0}
        stats.update(dict(rows))
        return stats

    def health(self, *, now: float | None = None) -> dict[str, int | float | None]:
        """Return payload-free operational state without scanning task content."""
        now = time.time() if now is None else now
        with self._connect() as db:
            oldest = db.execute(
                "SELECT MIN(created_at) FROM rejected_tasks WHERE state IN ('QUEUED','CLAIMED')"
            ).fetchone()[0]
            expired = db.execute(
                "SELECT COUNT(*) FROM rejected_tasks WHERE state='CLAIMED' AND claim_until < ?", (now,)
            ).fetchone()[0]
        return {
            **self.stats(),
            "oldest_active_age_seconds": round(max(0.0, now - oldest), 3) if oldest else None,
            "expired_claims": int(expired),
        }
