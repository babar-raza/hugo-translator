"""TC-APT-039: production-review qualification ledger.

Plan revision 8/§6.1: "qualification is satisfied by production review --
every committed cell's review verdict is the per-cell evidence TC-APT-034's
ledger consumes." This module is that ledger's read/write surface, backed by
`data/campaigns/qualification/cells.jsonl` (one content-free JSON row per
review verdict -- no candidate text, matching every other ledger in this
mission).

A cell is identified by (site_id, target_lang, content_class); a verdict row
additionally names the exact source_path and the model that produced the
reviewed candidate, so:

- cross_model_retry_target() answers "has the OTHER model been tried on this
  EXACT (source_path, target_lang), or is a retry still owed before
  quarantine" (plan §6.1: "a cell is quarantined only after both models have
  been tried and reviewed").
- rolling_reject_rate() / should_auto_flip_primary() operate at the (site_id,
  target_lang, content_class, model) granularity -- "if a cell's review-reject
  rate exceeds 20% over its last 20 cells on its primary, the routing table
  flips that cell's primary to the other model."
- consecutive_clean_count() / qualifies_for_stratified_sampling() at the same
  granularity, using the CURRENT operational threshold from
  project/loop-prompt.md §4.2 (15 consecutive clean cells), which supersedes
  the original plan text's "50" per this mission's own precedence rule (the
  runbook wins on what to do; the plan wins on why/how it is designed).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.file_lock import FileLock

_LEDGER_FILE = Path("data/campaigns/qualification/cells.jsonl")
AUTO_FLIP_WINDOW = 20
AUTO_FLIP_THRESHOLD = 0.20
STRATIFIED_SAMPLING_THRESHOLD = 15
_VALID_VERDICTS = frozenset({"APPROVE", "REJECT"})

# TC-APT-092: in-memory index cache, keyed by resolved ledger path, holding
# (mtime, rows) so repeated queries in one process don't re-read and re-parse
# the whole file every call -- quadratic once cells.jsonl is backfilled from
# every campaign dir's receipts (hundreds of thousands of rows). Invalidated
# by mtime, not a TTL: correct the instant another process's append lands,
# never stale by a fixed window, and only one stat() call on a cache hit.
_index_cache: dict[Path, tuple[float, list[dict[str, Any]]]] = {}


def _ledger_path(override: Path | None) -> Path:
    return override or _LEDGER_FILE


def _lock_path(ledger_path: Path) -> Path:
    return ledger_path.with_suffix(ledger_path.suffix + ".lock")


def _parse_rows(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _load_rows(ledger_path: Path) -> list[dict[str, Any]]:
    """Cached read: reparses only when the file's mtime has moved since the
    last load in THIS process. A cache miss (first call, or another process
    appended since) costs one full parse; every other call costs one stat()."""
    try:
        mtime = ledger_path.stat().st_mtime
    except FileNotFoundError:
        _index_cache.pop(ledger_path, None)
        return []
    cached = _index_cache.get(ledger_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    rows = _parse_rows(ledger_path)
    _index_cache[ledger_path] = (mtime, rows)
    return rows


def record_verdict(
    *,
    site_id: str,
    source_path: str,
    target_lang: str,
    content_class: str,
    model: str,
    verdict: str,
    rubric_rules: tuple[str, ...] = (),
    heal_retrigger: bool = False,
    ledger_path: Path | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Append one review verdict row. Never pass candidate/translated text here.

    heal_retrigger (TC-APT-092): True when this verdict comes from retrying a
    cell already sitting in the heal queue (a Tier-2 fix-verify pass), not
    from first-look production review. Cohort ladder math (rolling_reject_rate,
    consecutive_clean_count, qualifies_for_stratified_sampling) must exclude
    these -- a heal retrigger measures "did the targeted fix work," not "is
    this cohort's ordinary throughput reliable," and mixing the two would let
    a burst of heal retries either manufacture a false PROVEN streak or sink
    a cohort's rate on cells that were never part of its normal flow.
    """
    if verdict not in _VALID_VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(_VALID_VERDICTS)}, got {verdict!r}")
    path = _ledger_path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "site_id": site_id,
        "source_path": source_path,
        "target_lang": target_lang,
        "content_class": content_class,
        "model": model,
        "verdict": verdict,
        "rubric_rules": list(rubric_rules),
        "heal_retrigger": bool(heal_retrigger),
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
    }
    with FileLock(_lock_path(path), timeout=10):
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _index_cache.pop(path, None)
    return row


def models_tried(
    site_id: str, source_path: str, target_lang: str, *, ledger_path: Path | None = None
) -> set[str]:
    """Every model with a recorded verdict for this exact (source_path, target_lang)."""
    path = _ledger_path(ledger_path)
    return {
        row["model"]
        for row in _load_rows(path)
        if row.get("site_id") == site_id
        and row.get("source_path") == source_path
        and row.get("target_lang") == target_lang
        and row.get("model")
    }


def cross_model_retry_target(
    site_id: str,
    source_path: str,
    target_lang: str,
    *,
    rejected_model: str,
    other_model: str,
    ledger_path: Path | None = None,
) -> str | None:
    """The model to retry on next, or None if both models are already tried (quarantine).

    Plan §6.1: "a cell is quarantined only after both models have been tried
    and reviewed" -- this only ever recommends a retry for a model that has
    genuinely never been attempted on this exact cell; it never re-suggests
    a model already tried (avoiding an infinite retry loop between the two).
    """
    tried = models_tried(site_id, source_path, target_lang, ledger_path=ledger_path)
    if other_model in tried:
        return None
    return other_model


def _rolling_verdicts(
    site_id: str,
    target_lang: str,
    content_class: str,
    model: str,
    *,
    window: int,
    ledger_path: Path | None,
) -> list[str]:
    path = _ledger_path(ledger_path)
    matches = [
        row["verdict"]
        for row in _load_rows(path)
        if row.get("site_id") == site_id
        and row.get("target_lang") == target_lang
        and row.get("content_class") == content_class
        and row.get("model") == model
        and row.get("verdict") in _VALID_VERDICTS
        and not row.get("heal_retrigger")
    ]
    return matches[-window:] if window else matches


def rolling_reject_rate(
    site_id: str,
    target_lang: str,
    content_class: str,
    model: str,
    *,
    window: int = AUTO_FLIP_WINDOW,
    ledger_path: Path | None = None,
) -> float | None:
    """Fraction of REJECT verdicts in the most recent `window` cells, or None if none recorded."""
    verdicts = _rolling_verdicts(
        site_id, target_lang, content_class, model, window=window, ledger_path=ledger_path
    )
    if not verdicts:
        return None
    return sum(1 for v in verdicts if v == "REJECT") / len(verdicts)


def should_auto_flip_primary(
    site_id: str,
    target_lang: str,
    content_class: str,
    model: str,
    *,
    window: int = AUTO_FLIP_WINDOW,
    threshold: float = AUTO_FLIP_THRESHOLD,
    ledger_path: Path | None = None,
) -> bool:
    """True once a full window of `window` verdicts exists and its reject rate exceeds threshold.

    Requiring a full window (not just "some" samples) matches the plan's own
    wording -- "over its last 20 cells" -- and avoids flipping a cell's
    primary model off one or two unlucky early reviews.
    """
    verdicts = _rolling_verdicts(
        site_id, target_lang, content_class, model, window=window, ledger_path=ledger_path
    )
    if len(verdicts) < window:
        return False
    reject_rate = sum(1 for v in verdicts if v == "REJECT") / len(verdicts)
    return reject_rate > threshold


def consecutive_clean_count(
    site_id: str,
    target_lang: str,
    content_class: str,
    model: str,
    *,
    ledger_path: Path | None = None,
) -> int:
    """Count of the most recent consecutive APPROVE verdicts, reset by any REJECT."""
    verdicts = _rolling_verdicts(
        site_id, target_lang, content_class, model, window=0, ledger_path=ledger_path
    )
    count = 0
    for verdict in reversed(verdicts):
        if verdict != "APPROVE":
            break
        count += 1
    return count


def qualifies_for_stratified_sampling(
    site_id: str,
    target_lang: str,
    content_class: str,
    model: str,
    *,
    threshold: int = STRATIFIED_SAMPLING_THRESHOLD,
    ledger_path: Path | None = None,
) -> bool:
    """True once a (site, language, class) cell on `model` has enough consecutive clean reviews
    to drop from full review to stratified (1-in-5) sampling (project/loop-prompt.md §4.2)."""
    return (
        consecutive_clean_count(
            site_id, target_lang, content_class, model, ledger_path=ledger_path
        )
        >= threshold
    )
