"""Durable, claim-safe write intents for the canonical TM writer.

SQLite is deliberately used for the coordination record, not as a second TM:
LMDB remains canonical storage and FAISS remains the semantic index.  The spool
only bridges independently running translation/retry processes to one writer.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class TMIntentSpool:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS tm_intents (
                    intent_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    state TEXT NOT NULL, claim_owner TEXT, claim_until REAL,
                    attempts INTEGER NOT NULL DEFAULT 0, applied_at REAL,
                    error TEXT, created_at REAL NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS tm_intents_claim ON tm_intents(state, claim_until)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _intent_id(payload: dict[str, Any]) -> str:
        stable = {
            key: payload.get(key)
            for key in (
                "site_id",
                "src_lang",
                "tgt_lang",
                "text",
                "translation",
                "context",
                "field_name",
            )
        }
        return hashlib.sha256(
            json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def enqueue(self, payload: dict[str, Any]) -> str:
        required = {"site_id", "src_lang", "tgt_lang", "text", "translation"}
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"TM intent missing required fields: {missing}")
        intent_id = self._intent_id(payload)
        encoded = json.dumps(
            {"schema_version": self.SCHEMA_VERSION, **payload}, sort_keys=True, ensure_ascii=False
        )
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO tm_intents(intent_id,payload,state,created_at) VALUES(?,?,?,?)",
                (intent_id, encoded, "PENDING", time.time()),
            )
        return intent_id

    def claim(
        self, owner: str, *, limit: int = 50, lease_seconds: float = 300
    ) -> list[dict[str, Any]]:
        if not owner or limit < 1 or lease_seconds <= 0:
            raise ValueError("owner, positive limit, and positive lease_seconds are required")
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT intent_id,payload FROM tm_intents
                   WHERE state='PENDING' OR (state='CLAIMED' AND claim_until < ?)
                   ORDER BY created_at,intent_id LIMIT ?""",
                (now, limit),
            ).fetchall()
            ids = [row[0] for row in rows]
            if ids:
                db.executemany(
                    "UPDATE tm_intents SET state='CLAIMED',claim_owner=?,claim_until=?,attempts=attempts+1,error=NULL WHERE intent_id=?",
                    [(owner, now + lease_seconds, intent_id) for intent_id in ids],
                )
            db.execute("COMMIT")
        return [{"intent_id": intent_id, **json.loads(payload)} for intent_id, payload in rows]

    def complete(self, intent_id: str, owner: str) -> None:
        with self._connect() as db:
            changed = db.execute(
                "UPDATE tm_intents SET state='APPLIED',applied_at=?,claim_owner=NULL,claim_until=NULL WHERE intent_id=? AND state='CLAIMED' AND claim_owner=?",
                (time.time(), intent_id, owner),
            ).rowcount
        if changed != 1:
            raise RuntimeError("TM intent is not owned by this writer")

    def fail(self, intent_id: str, owner: str, error: Exception) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE tm_intents SET state='PENDING',claim_owner=NULL,claim_until=NULL,error=? WHERE intent_id=? AND claim_owner=?",
                (type(error).__name__, intent_id, owner),
            )

    def requeue_expired_claims(self, *, now: float | None = None) -> int:
        """Return abandoned writer claims to PENDING without touching APPLIED work."""
        now = time.time() if now is None else now
        with self._connect() as db:
            return db.execute(
                "UPDATE tm_intents SET state='PENDING',claim_owner=NULL,claim_until=NULL "
                "WHERE state='CLAIMED' AND claim_until < ?",
                (now,),
            ).rowcount

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute("SELECT state,COUNT(*) FROM tm_intents GROUP BY state").fetchall()
        result = {"PENDING": 0, "CLAIMED": 0, "APPLIED": 0}
        result.update({state: count for state, count in rows})
        return result

    def applied_intents(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Return APPLIED intents (with their original payload) for reconciliation.

        Unlike claim(), this is a read-only view that never changes state --
        it exists so a reconciler can detect and repair an L3 update that a
        writer crash left durably marked APPLIED in the spool but never
        actually persisted to the L3 index (see TMIntentWriter.reconcile_l3).
        """
        query = "SELECT intent_id,payload FROM tm_intents WHERE state='APPLIED' ORDER BY created_at,intent_id"
        params: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [{"intent_id": intent_id, **json.loads(payload)} for intent_id, payload in rows]


class TMIntentWriter:
    """The only component permitted to mutate L2 and L3 from an intent spool."""

    def __init__(self, spool: TMIntentSpool, l2: Any, l3: Any | None = None) -> None:
        self.spool, self.l2, self.l3 = spool, l2, l3

    @staticmethod
    def _l3_entry_id(payload: dict[str, Any]) -> str:
        return (
            f"{payload['site_id']}:{payload['src_lang']}:{payload['tgt_lang']}:"
            f"{hashlib.sha256(payload['text'].encode()).hexdigest()}"
        )

    def run_once(
        self, *, limit: int = 50, owner: str | None = None, lease_seconds: float = 300
    ) -> dict[str, int]:
        owner = owner or f"tm-writer-{uuid.uuid4()}"
        applied = failed = 0
        for intent in self.spool.claim(owner, limit=limit, lease_seconds=lease_seconds):
            try:
                payload = {
                    key: value
                    for key, value in intent.items()
                    if key not in {"intent_id", "schema_version"}
                }
                stored = self.l2.store(**payload)
                if stored and self.l3 is not None:
                    self.l3.add_entry(
                        entry_id=self._l3_entry_id(payload),
                        site_id=payload["site_id"],
                        src_lang=payload["src_lang"],
                        tgt_lang=payload["tgt_lang"],
                        source_text=payload["text"],
                        translation=payload["translation"],
                        context=payload.get("context"),
                        metadata=payload.get("metadata"),
                    )
                self.spool.complete(intent["intent_id"], owner)
                applied += 1
            except Exception as exc:
                self.spool.fail(intent["intent_id"], owner, exc)
                failed += 1
        if applied and self.l3 is not None and hasattr(self.l3, "save_index"):
            self.l3.save_index()
        return {"applied": applied, "failed": failed, **self.spool.stats()}

    def reconcile_l3(self, *, limit: int | None = None) -> dict[str, int]:
        """Repair L3 entries for intents the spool already marked APPLIED.

        run_once() saves the L3 index once per batch, after its loop of
        store()+add_entry()+complete() calls.  A writer crash after an
        intent's spool.complete() but before that trailing save_index() call
        leaves the spool durably believing an L3 update landed when the
        crashed process's in-memory FAISS addition was actually lost --
        never a duplicate (nothing else re-applies an APPLIED intent), but a
        silent, permanent gap between L2/spool state and L3 with no
        automatic repair. This scans already-APPLIED intents (their payload
        survives completion) and, for each one, calls update_entry() first
        so an entry that *was* durably saved is only refreshed -- never
        given a second vector -- and falls back to add_entry() only for an
        entry_id genuinely missing from L3. Safe to run at any time,
        including when nothing is missing (a no-op pass).
        """
        if self.l3 is None:
            return {"checked": 0, "repaired": 0}
        checked = repaired = 0
        for intent in self.spool.applied_intents(limit=limit):
            checked += 1
            payload = {
                key: value
                for key, value in intent.items()
                if key not in {"intent_id", "schema_version"}
            }
            if not self.l3.update_entry(
                entry_id=self._l3_entry_id(payload),
                new_translation=payload["translation"],
                new_metadata=payload.get("metadata"),
            ):
                self.l3.add_entry(
                    entry_id=self._l3_entry_id(payload),
                    site_id=payload["site_id"],
                    src_lang=payload["src_lang"],
                    tgt_lang=payload["tgt_lang"],
                    source_text=payload["text"],
                    translation=payload["translation"],
                    context=payload.get("context"),
                    metadata=payload.get("metadata"),
                )
                repaired += 1
        if repaired and hasattr(self.l3, "save_index"):
            self.l3.save_index()
        return {"checked": checked, "repaired": repaired}
