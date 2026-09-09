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

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute("SELECT state,COUNT(*) FROM tm_intents GROUP BY state").fetchall()
        result = {"PENDING": 0, "CLAIMED": 0, "APPLIED": 0}
        result.update({state: count for state, count in rows})
        return result


class TMIntentWriter:
    """The only component permitted to mutate L2 and L3 from an intent spool."""

    def __init__(self, spool: TMIntentSpool, l2: Any, l3: Any | None = None) -> None:
        self.spool, self.l2, self.l3 = spool, l2, l3

    def run_once(self, *, limit: int = 50, owner: str | None = None) -> dict[str, int]:
        owner = owner or f"tm-writer-{uuid.uuid4()}"
        applied = failed = 0
        for intent in self.spool.claim(owner, limit=limit):
            try:
                payload = {
                    key: value
                    for key, value in intent.items()
                    if key not in {"intent_id", "schema_version"}
                }
                stored = self.l2.store(**payload)
                if stored and self.l3 is not None:
                    self.l3.add_entry(
                        entry_id=f"{payload['site_id']}:{payload['src_lang']}:{payload['tgt_lang']}:{hashlib.sha256(payload['text'].encode()).hexdigest()}",
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
