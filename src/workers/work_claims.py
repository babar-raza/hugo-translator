"""TC-APT-056: fleet work-claims helper.

This mission runs as a multi-session fleet against one shared working tree
(plan §0.6/TC-APT-056). Before opening a Track-A page or starting a Track-B
taskcard, a session leases it here first -- `work_key` is `page:<source_path>`
or `taskcard:TC-APT-###`. Until this module existed, every session
approximated the lease with an ad hoc atomic-append-and-verify against
`data/campaigns/claims.jsonl` with no real cross-process exclusion; this
gives that interim protocol a genuine OS-level `FileLock` (src/utils/
file_lock.py, already used the same way by CampaignRunner.run()) around the
read-check-write sequence, so two processes racing to claim the same key at
the same instant cannot both win.

Tolerant of the claims.jsonl schema drift already on disk from the interim
protocol: earlier rows use either `claimed_at` or `acquired_at` for the same
field, and not every row carries `ttl_minutes`. Reads accept both; writes
always use `claimed_at` + `expires_at` for consistency going forward.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.utils.file_lock import FileLock

_CLAIMS_FILE = Path("data/campaigns/claims.jsonl")
DEFAULT_TTL_MINUTES = 45


def _claims_path(override: Path | None) -> Path:
    return override or _CLAIMS_FILE


def _lock_path(claims_path: Path) -> Path:
    return claims_path.with_suffix(claims_path.suffix + ".lock")


def _load_rows(claims_path: Path) -> list[dict[str, Any]]:
    if not claims_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in claims_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _row_claimed_at(row: dict[str, Any]) -> str:
    return row.get("claimed_at") or row.get("acquired_at") or ""


def _parse(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def active_claim(
    work_key: str, *, claims_path: Path | None = None, now: datetime | None = None
) -> dict[str, Any] | None:
    """The live claim for `work_key`, or None if unclaimed / expired / released.

    Live means: the most recent CLAIM row for this key has not expired, and
    no RELEASE row from the SAME session for the SAME claim has landed after it.
    """
    path = _claims_path(claims_path)
    now = now or datetime.now(timezone.utc)
    rows = [r for r in _load_rows(path) if r.get("work_key") == work_key]
    rows.sort(key=_row_claimed_at)

    latest_claim: dict[str, Any] | None = None
    for row in rows:
        action = row.get("action", "CLAIM")
        if action == "CLAIM":
            latest_claim = row
        elif action == "RELEASE" and latest_claim is not None:
            if row.get("session_id") == latest_claim.get("session_id"):
                latest_claim = None

    if latest_claim is None:
        return None
    expires_at = _parse(latest_claim.get("expires_at", ""))
    if expires_at is not None and expires_at <= now:
        return None
    return latest_claim


def acquire_claim(
    work_key: str,
    session_id: str,
    *,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    purpose: str | None = None,
    claims_path: Path | None = None,
    lock_timeout: float = 10.0,
) -> bool:
    """Try to claim `work_key` for `session_id`.

    Returns True if the claim was acquired or renewed (no other session holds
    a live claim on this key, or this same session already does). Returns
    False if a DIFFERENT session holds a live claim -- the caller must skip
    this work, never proceed anyway.
    """
    path = _claims_path(claims_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(_lock_path(path), timeout=lock_timeout):
        now = datetime.now(timezone.utc)
        existing = active_claim(work_key, claims_path=path, now=now)
        if existing is not None and existing.get("session_id") != session_id:
            return False
        row: dict[str, Any] = {
            "work_key": work_key,
            "session_id": session_id,
            "claimed_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(),
            "ttl_minutes": ttl_minutes,
            "action": "CLAIM",
        }
        if purpose:
            row["purpose"] = purpose
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True


def release_claim(
    work_key: str, session_id: str, *, claims_path: Path | None = None
) -> None:
    """Explicitly release a claim early (e.g. work finished well before its TTL)."""
    path = _claims_path(claims_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(_lock_path(path), timeout=10):
        row = {
            "work_key": work_key,
            "session_id": session_id,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "action": "RELEASE",
        }
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
