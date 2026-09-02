"""Portfolio-wide work ledger: SQLite index over per-site MetadataTracker records (TC-APT-003).

Mission ``aspose-org-full-portfolio-translation-20260901``, plan sections 7.1 and 14.1.

This is an **aggregation/query index**, not a second hash-tracking system: source/target
hashes come from each site's extended ``MetadataTracker`` JSON (``src/utils/metadata_tracker.py``),
fingerprints from ``src/workers/fingerprints.py``, provenance from receipts /
``src/workers/git_provenance.py``.  The ledger never recomputes hashes itself.

Content-free by construction: every column is a hash, path, enum, count or timestamp.
``upsert()`` rejects any ``validation_results`` JSON carrying a ``content`` /
``translated_content`` key at any nesting level (recursive form of
``CampaignLedger.append_receipt()``'s top-level guard).

Two files:

* ``data/campaigns/work_ledger.sqlite3``      -- current state (this module's table)
* ``data/campaigns/work_ledger_events.jsonl``  -- append-only audit trail; the table is
  rebuildable from it (:meth:`WorkLedger.replay_events`).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_LEDGER_PATH = Path("data/campaigns/work_ledger.sqlite3")
DEFAULT_EVENTS_PATH = Path("data/campaigns/work_ledger_events.jsonl")
#: Canonical location of the mission's per-site extended MetadataTracker files.
DEFAULT_METADATA_DIR = Path("data/campaigns/metadata")

ELIGIBILITY_STATES: tuple[str, ...] = (
    "UNSUPPORTED_LANGUAGE",
    "EXCLUDED_BY_PROFILE",
    "SOURCE_INVALID",
    "BLOCKED",
    "MANUAL_REVIEW_REJECTED",
    "FAILED_PRIOR_VALIDATION",
    "MISSING_TRANSLATION",
    "SOURCE_CHANGED",
    "PROFILE_CHANGED",
    "PROTECTION_RULE_CHANGED",
    "MODEL_OR_PROMPT_INVALIDATED",
    "UP_TO_DATE",
    "UNKNOWN_PROVENANCE",  # 13th, additive, backfill-only (plan 7.4)
)
PROVENANCE_KINDS: tuple[str, ...] = (
    "RECEIPT_BACKED",
    "GIT_COMMIT_BACKED",
    "AUDITED_BASELINE",
    "FRONTMATTER_TAGGED",
    "UNKNOWN",
)
REVIEW_RESULTS: tuple[str, ...] = ("PENDING", "APPROVED", "REJECTED", "NOT_REQUIRED")
FORBIDDEN_CONTENT_KEYS = frozenset({"content", "translated_content"})

DDL = """
CREATE TABLE IF NOT EXISTS page_language_work (
  work_id                   TEXT PRIMARY KEY,
  site_id                   TEXT NOT NULL,
  family                    TEXT NOT NULL DEFAULT '',
  platform                  TEXT NOT NULL DEFAULT '',
  source_path               TEXT NOT NULL,
  target_lang               TEXT NOT NULL,
  expected_output_path      TEXT NOT NULL,
  source_sha256             TEXT NOT NULL,
  profile_fingerprint       TEXT NOT NULL,
  protection_fingerprint    TEXT NOT NULL,
  target_exists             INTEGER NOT NULL,
  target_sha256             TEXT,
  provenance_kind           TEXT NOT NULL DEFAULT 'UNKNOWN',
  provenance_ref            TEXT,
  provenance_source_sha256  TEXT,
  provenance_profile_fp     TEXT,
  provenance_protection_fp  TEXT,
  tm_lineage_config_fp      TEXT,
  tm_lineage_model_id       TEXT,
  provider_model            TEXT,
  prompt_config_version     TEXT,
  eligibility_state         TEXT NOT NULL,
  eligibility_reason_code   TEXT NOT NULL,
  attempts                  INTEGER NOT NULL DEFAULT 0,
  last_attempt_at           TEXT,
  last_validated_checkpoint TEXT,
  validation_results        TEXT,
  claude_review_result      TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
  claude_review_at          TEXT,
  claude_review_note        TEXT CHECK(length(claude_review_note) <= 500),
  defect_reference          TEXT,
  output_commit_ref         TEXT,
  wave                      INTEGER NOT NULL DEFAULT 0,
  schema_version            INTEGER NOT NULL DEFAULT 1,
  created_at                TEXT NOT NULL,
  updated_at                TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_plw_cell ON page_language_work(site_id, source_path, target_lang);
CREATE INDEX IF NOT EXISTS ix_plw_state ON page_language_work(eligibility_state);
CREATE INDEX IF NOT EXISTS ix_plw_site_lang ON page_language_work(site_id, target_lang);
"""

COLUMNS: tuple[str, ...] = (
    "work_id",
    "site_id",
    "family",
    "platform",
    "source_path",
    "target_lang",
    "expected_output_path",
    "source_sha256",
    "profile_fingerprint",
    "protection_fingerprint",
    "target_exists",
    "target_sha256",
    "provenance_kind",
    "provenance_ref",
    "provenance_source_sha256",
    "provenance_profile_fp",
    "provenance_protection_fp",
    "tm_lineage_config_fp",
    "tm_lineage_model_id",
    "provider_model",
    "prompt_config_version",
    "eligibility_state",
    "eligibility_reason_code",
    "attempts",
    "last_attempt_at",
    "last_validated_checkpoint",
    "validation_results",
    "claude_review_result",
    "claude_review_at",
    "claude_review_note",
    "defect_reference",
    "output_commit_ref",
    "wave",
    "schema_version",
    "created_at",
    "updated_at",
)
REQUIRED: tuple[str, ...] = (
    "site_id",
    "source_path",
    "target_lang",
    "expected_output_path",
    "source_sha256",
    "profile_fingerprint",
    "protection_fingerprint",
    "target_exists",
    "eligibility_state",
    "eligibility_reason_code",
)
_UPDATE_COLUMNS = tuple(c for c in COLUMNS if c not in ("work_id", "created_at"))
_UPSERT_SQL = (
    f"INSERT INTO page_language_work ({', '.join(COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in COLUMNS)}) "
    "ON CONFLICT(work_id) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in _UPDATE_COLUMNS)
)


class WorkLedgerError(RuntimeError):
    """Invalid row or invariant violation."""


def work_id_for(site_id: str, source_path: str, target_lang: str) -> str:
    return hashlib.sha256(f"{site_id}\0{source_path}\0{target_lang}".encode()).hexdigest()


def metadata_path_for_site(site_id: str, metadata_dir: Path = DEFAULT_METADATA_DIR) -> Path:
    """Canonical per-site extended MetadataTracker file for this mission."""
    return metadata_dir / site_id / ".translation_metadata.json"


def _contains_forbidden_key(obj: Any) -> bool:
    if isinstance(obj, dict):
        return any(
            str(k) in FORBIDDEN_CONTENT_KEYS or _contains_forbidden_key(v) for k, v in obj.items()
        )
    if isinstance(obj, (list, tuple)):
        return any(_contains_forbidden_key(v) for v in obj)
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize + validate one row; raise :class:`WorkLedgerError` on any violation."""
    missing = [k for k in REQUIRED if row.get(k) in (None, "")]
    # target_exists may legitimately be 0/False; only None/'' count as missing.
    if "target_exists" in missing and row.get("target_exists") in (0, False):
        missing.remove("target_exists")
    if missing:
        raise WorkLedgerError(f"row missing required fields: {missing}")
    unknown = set(row) - set(COLUMNS)
    if unknown:
        raise WorkLedgerError(f"row has unknown columns: {sorted(unknown)}")
    if row["eligibility_state"] not in ELIGIBILITY_STATES:
        raise WorkLedgerError(f"invalid eligibility_state {row['eligibility_state']!r}")
    kind = row.get("provenance_kind") or "UNKNOWN"
    if kind not in PROVENANCE_KINDS:
        raise WorkLedgerError(f"invalid provenance_kind {kind!r}")
    review = row.get("claude_review_result") or "NOT_REQUIRED"
    if review not in REVIEW_RESULTS:
        raise WorkLedgerError(f"invalid claude_review_result {review!r}")
    note = row.get("claude_review_note")
    if note is not None and len(str(note)) > 500:
        raise WorkLedgerError("claude_review_note exceeds 500 chars")
    vr = row.get("validation_results")
    if vr is not None:
        parsed = json.loads(vr) if isinstance(vr, str) else vr
        if _contains_forbidden_key(parsed):
            raise WorkLedgerError(
                "validation_results carries translated content (content-free invariant)"
            )
        row["validation_results"] = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    for hash_field in ("source_sha256", "target_sha256", "provenance_source_sha256"):
        value = row.get(hash_field)
        if value not in (None, "") and (
            len(str(value)) != 64 or not all(c in "0123456789abcdef" for c in str(value))
        ):
            raise WorkLedgerError(f"{hash_field} is not a sha256 hex digest")
    out = dict(row)
    out["work_id"] = work_id_for(out["site_id"], out["source_path"], out["target_lang"])
    out["target_exists"] = 1 if out["target_exists"] else 0
    out["provenance_kind"] = kind
    out["claude_review_result"] = review
    out.setdefault("family", "")
    out.setdefault("platform", "")
    out.setdefault("attempts", 0)
    out.setdefault("wave", 0)
    out["schema_version"] = SCHEMA_VERSION
    return out


class WorkLedger:
    """SQLite-backed ``page_language_work`` table with an append-only JSONL event trail."""

    def __init__(self, path: Path = DEFAULT_LEDGER_PATH, events_path: Path | None = None) -> None:
        self.path = Path(path)
        self.events_path = (
            Path(events_path) if events_path else self.path.with_name("work_ledger_events.jsonl")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(DDL)

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> WorkLedger:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ events
    @staticmethod
    def _event_payload(event: str, row: dict[str, Any], reason: str | None) -> dict[str, Any]:
        payload = {
            "event": event,
            "at": row.get("updated_at") or _now(),
            "work_id": row["work_id"],
            "site_id": row["site_id"],
            "source_path": row["source_path"],
            "target_lang": row["target_lang"],
            "eligibility_state": row.get("eligibility_state"),
            "eligibility_reason_code": row.get("eligibility_reason_code"),
            "provenance_kind": row.get("provenance_kind"),
            "target_exists": row.get("target_exists"),
            "reason": reason,
            "row": row,
        }
        if _contains_forbidden_key(payload):
            raise WorkLedgerError("event carries translated content (content-free invariant)")
        return payload

    def _append_events(self, payloads: list[dict[str, Any]]) -> None:
        if not payloads:
            return
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    # ------------------------------------------------------------------ writes
    def _existing_created(self, work_ids: list[str]) -> dict[str, str]:
        """``work_id -> created_at`` for the ids already present (chunked IN queries)."""
        found: dict[str, str] = {}
        for start in range(0, len(work_ids), 900):
            chunk = work_ids[start : start + 900]
            marks = ", ".join("?" for _ in chunk)
            for r in self._conn.execute(
                f"SELECT work_id, created_at FROM page_language_work WHERE work_id IN ({marks})",
                chunk,
            ):
                found[r["work_id"]] = r["created_at"]
        return found

    def _write_rows(
        self, rows: list[dict[str, Any]], *, reason: str | None, record_event: bool
    ) -> list[dict[str, Any]]:
        """Validate, upsert all rows in ONE transaction, append events with ONE file open."""
        clean = [validate_row(dict(r)) for r in rows]
        now = _now()
        existing = self._existing_created([c["work_id"] for c in clean])
        payloads: list[dict[str, Any]] = []
        for c in clean:
            c["created_at"] = existing.get(c["work_id"]) or c.get("created_at") or now
            c["updated_at"] = now
            if record_event:
                payloads.append(
                    self._event_payload(
                        "update" if c["work_id"] in existing else "insert", c, reason
                    )
                )
        with self._conn:
            self._conn.executemany(
                _UPSERT_SQL, [tuple(c.get(col) for col in COLUMNS) for c in clean]
            )
        self._append_events(payloads)
        return clean

    def upsert(
        self, row: dict[str, Any], *, reason: str | None = None, record_event: bool = True
    ) -> dict[str, Any]:
        """Insert or replace one cell row (validated, content-free), logging an event."""
        return self._write_rows([row], reason=reason, record_event=record_event)[0]

    def bulk_upsert(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        reason: str | None = None,
        batch_size: int = 5000,
    ) -> int:
        """Upsert many rows in batched transactions (one event-log open per batch)."""
        count = 0
        batch: list[dict[str, Any]] = []
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                count += len(self._write_rows(batch, reason=reason, record_event=True))
                batch = []
        if batch:
            count += len(self._write_rows(batch, reason=reason, record_event=True))
        return count

    def commit(self) -> None:
        self._conn.commit()

    def set_state(
        self,
        work_id: str,
        eligibility_state: str,
        reason_code: str,
        *,
        reason: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Transition one row's eligibility (and optional other columns), logging the event."""
        row = self.get(work_id)
        if row is None:
            raise WorkLedgerError(f"unknown work_id {work_id}")
        row.update(fields)
        row["eligibility_state"] = eligibility_state
        row["eligibility_reason_code"] = reason_code
        return self.upsert(row, reason=reason)

    # ------------------------------------------------------------------ reads
    def get(self, work_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM page_language_work WHERE work_id = ?", (work_id,))
        found = cur.fetchone()
        return dict(found) if found else None

    def get_cell(self, site_id: str, source_path: str, target_lang: str) -> dict[str, Any] | None:
        return self.get(work_id_for(site_id, source_path, target_lang))

    def query(
        self,
        *,
        site_id: str | None = None,
        target_lang: str | None = None,
        eligibility_state: str | Iterable[str] | None = None,
        family: str | None = None,
        platform: str | None = None,
        limit: int | None = None,
        order_by: str = "wave, site_id, source_path, target_lang",
    ) -> Iterator[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if site_id is not None:
            clauses.append("site_id = ?")
            params.append(site_id)
        if target_lang is not None:
            clauses.append("target_lang = ?")
            params.append(target_lang)
        if family is not None:
            clauses.append("family = ?")
            params.append(family)
        if platform is not None:
            clauses.append("platform = ?")
            params.append(platform)
        if eligibility_state is not None:
            states = (
                [eligibility_state]
                if isinstance(eligibility_state, str)
                else list(eligibility_state)
            )
            clauses.append(f"eligibility_state IN ({', '.join('?' for _ in states)})")
            params.extend(states)
        sql = "SELECT * FROM page_language_work"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        for found in self._conn.execute(sql, params):
            yield dict(found)

    def count(self, **filters: Any) -> int:
        return sum(1 for _ in self.query(**filters))

    def counts_by_state(self, *, site_id: str | None = None) -> dict[str, int]:
        sql = "SELECT eligibility_state, COUNT(*) AS n FROM page_language_work"
        params: tuple[Any, ...] = ()
        if site_id is not None:
            sql += " WHERE site_id = ?"
            params = (site_id,)
        sql += " GROUP BY eligibility_state ORDER BY eligibility_state"
        return {r["eligibility_state"]: r["n"] for r in self._conn.execute(sql, params)}

    def counts_by_site_state(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self._conn.execute(
            "SELECT site_id, eligibility_state, COUNT(*) AS n FROM page_language_work "
            "GROUP BY site_id, eligibility_state ORDER BY site_id, eligibility_state"
        ):
            out.setdefault(r["site_id"], {})[r["eligibility_state"]] = r["n"]
        return out

    def total(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM page_language_work").fetchone()[0])

    def duplicate_cells(self) -> int:
        """Rows violating the one-row-per-cell contract (always 0; the unique index enforces it)."""
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM (SELECT site_id, source_path, target_lang, COUNT(*) c "
                "FROM page_language_work GROUP BY 1,2,3 HAVING c > 1)"
            ).fetchone()[0]
        )

    # ------------------------------------------------------------------ rebuild
    @classmethod
    def replay_events(cls, events_path: Path, target: Path) -> WorkLedger:
        """Rebuild a ledger table from the append-only event log (last write wins)."""
        ledger = cls(target, events_path=target.with_name("replayed_events.jsonl"))
        rows: list[dict[str, Any]] = []
        for line in Path(events_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            row = dict(payload["row"])
            row.pop("created_at", None)
            row.pop("updated_at", None)
            rows.append(row)
        for start in range(0, len(rows), 5000):
            ledger._write_rows(rows[start : start + 5000], reason=None, record_event=False)
        return ledger
