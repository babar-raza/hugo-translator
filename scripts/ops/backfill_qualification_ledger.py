"""TC-APT-092 (plan SS0.10, BLITZ critical path 1 of 3): backfill
data/campaigns/qualification/cells.jsonl -- the qualification_ledger.py
verdict history TC-APT-093's cohort ladders and TC-APT-099's blitz both read
-- from every campaign dir's acceptance_receipts.jsonl, timestamp-sorted
across dirs (file order lies: gate5-words-doc/-r2/-r3/-r4 are separate files
for the SAME retried cells).

Gate-failures are EXCLUDED, not converted to REJECT (measured 2026-09-06:
100% of the 478 rows across every failure_metadata.jsonl name a structural
gate/validator -- FrontmatterLanguageCheck, TC-SAS-01, RepetitionDetector
Validator, StructureValidator, LanguageConsistencyValidator, verification:
language_detection, GATE36/44, or a generic "pipeline" error -- never a
review verdict; the pipeline records a review's outcome nowhere in
campaign-dir receipts at all). Counting these as REJECTs would be exactly
the "gate-only failures... bias acceptance rates" defect the taskcard warns
against, since a cell that never reached review is not evidence about
review-time quality.

Genuine review verdicts instead come from data/campaigns/heal_queue.jsonl's
`tier: "review_reject"` tickets (the only place a real Claude/human-rubric
verdict is recorded today) -- see e.g. the words-document-net ar/el/fa/fr/hi
tickets citing rubric rules RB-004/RB-005. Each is paired, in timestamp
order, against the acceptance_receipts row for the SAME (source_path,
target_lang) it followed, flipping that specific accepted attempt to
REJECT -- multiple retry cycles on one cell (accept, reject, retry, accept,
reject...) are common (words-document-net/fa was rejected twice) and are
paired by chronological order, not "any" match, so a later successful
retry does not silently absorb an earlier reject or vice versa.

`tier: "review_hold"` tickets (content HELD, never shipped -- e.g. the
cells-go/ar paragraph-link case TC-APT-087 later fixed) have no
corresponding acceptance row and no recorded model, so they are NOT
backfilled here; this is a known, small gap (1 ticket at time of writing),
noted rather than guessed at.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.translation_engine.extractor.text_unit_extractor import is_family_platform_index
from src.workers.qualification_ledger import record_verdict

_RUBRIC_RULE_RE = re.compile(r"\bRB-\d+\b")
_REVIEW_TIERS = frozenset({"review_reject"})


def _site_id_from_source_path(source_path: str) -> str:
    parts = source_path.split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "content" else "unknown"


def classify_content(source_path: str, site_id: str) -> str:
    """Coarse, defensible first pass -- NOT the final TC-APT-093 taxonomy.

    The plan's own measurement ("91% one shape") makes reference.aspose.org's
    templated API pages the single most cohort-relevant distinction to
    preserve; family/platform index pages are a second, already-tested
    structural category (is_family_platform_index, shared with the
    title-identity gate). Everything else is one bucket. TC-APT-093 owns
    refining this if the ladder needs finer content-class granularity.
    """
    if site_id == "reference.aspose.org":
        return "reference_api_page"
    if is_family_platform_index(Path(source_path), include_family_root=True):
        return "family_platform_index"
    return "content_page"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _load_acceptances(campaigns_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for receipts_file in sorted(campaigns_dir.glob("*/acceptance_receipts.jsonl")):
        campaign_id = receipts_file.parent.name
        for row in _load_jsonl(receipts_file):
            row["_campaign_id"] = campaign_id
            row["_heal_retrigger"] = campaign_id.startswith("heal-")
            rows.append(row)
    rows.sort(key=lambda r: r.get("accepted_at") or "")
    return rows


def _load_review_reject_tickets(heal_queue_path: Path) -> dict[tuple[str, str], list[str]]:
    """(source_path, target_lang) -> sorted list of opened_at timestamps."""
    by_cell: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in _load_jsonl(heal_queue_path):
        if row.get("tier") not in _REVIEW_TIERS:
            continue
        key = (row.get("source_path"), row.get("target_lang"))
        by_cell[key].append(row.get("opened_at") or "")
    for key in by_cell:
        by_cell[key].sort()
    return by_cell


def _rubric_rules_for(heal_queue_path: Path, source_path: str, target_lang: str, opened_at: str) -> tuple[str, ...]:
    for row in _load_jsonl(heal_queue_path):
        if (
            row.get("source_path") == source_path
            and row.get("target_lang") == target_lang
            and row.get("opened_at") == opened_at
        ):
            note = row.get("note", "") or ""
            return tuple(sorted(set(_RUBRIC_RULE_RE.findall(note))))
    return ()


def build_verdict_rows(campaigns_dir: Path, heal_queue_path: Path) -> list[dict[str, Any]]:
    acceptances = _load_acceptances(campaigns_dir)
    reject_tickets = _load_review_reject_tickets(heal_queue_path)
    consumed: dict[tuple[str, str], int] = defaultdict(int)

    # Group acceptance indices by cell so pairing is chronological per cell,
    # not global (two different cells' rows must never cross-pair).
    by_cell_indices: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, row in enumerate(acceptances):
        key = (row.get("source_path"), row.get("target_lang"))
        by_cell_indices[key].append(i)

    verdict_rows: list[dict[str, Any]] = []
    for key, indices in by_cell_indices.items():
        source_path, target_lang = key
        tickets = reject_tickets.get(key, [])
        ticket_cursor = 0
        # indices are already in accepted_at order (acceptances list is globally sorted)
        for pos, idx in enumerate(indices):
            row = acceptances[idx]
            accepted_at = row.get("accepted_at") or ""
            next_accepted_at = (
                acceptances[indices[pos + 1]].get("accepted_at") or ""
                if pos + 1 < len(indices)
                else None
            )
            verdict = "APPROVE"
            rubric_rules: tuple[str, ...] = ()
            matched_opened_at = None
            while ticket_cursor < len(tickets):
                opened_at = tickets[ticket_cursor]
                if opened_at < accepted_at:
                    # A stale ticket from before this row's own acceptance
                    # (already paired to an earlier acceptance, or predates
                    # tracking) -- skip it, never pair backwards in time.
                    ticket_cursor += 1
                    continue
                if next_accepted_at is not None and opened_at >= next_accepted_at:
                    # Belongs to a LATER acceptance attempt; leave it for that one.
                    break
                verdict = "REJECT"
                matched_opened_at = opened_at
                ticket_cursor += 1
                break

            if matched_opened_at:
                rubric_rules = _rubric_rules_for(heal_queue_path, source_path, target_lang, matched_opened_at)

            site_id = row.get("site_id") or _site_id_from_source_path(source_path)
            verdict_rows.append(
                {
                    "site_id": site_id,
                    "source_path": source_path,
                    "target_lang": target_lang,
                    "content_class": classify_content(source_path, site_id),
                    "model": row.get("model_fingerprint") or "unknown",
                    "verdict": verdict,
                    "rubric_rules": rubric_rules,
                    "heal_retrigger": bool(row.get("_heal_retrigger")),
                    "recorded_at": accepted_at,
                }
            )

    verdict_rows.sort(key=lambda r: r["recorded_at"])
    return verdict_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaigns-dir", type=Path, default=Path("data/campaigns"))
    parser.add_argument(
        "--heal-queue", type=Path, default=Path("data/campaigns/heal_queue.jsonl")
    )
    parser.add_argument("--ledger-path", type=Path, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="report counts only, write nothing"
    )
    args = parser.parse_args(argv)

    rows = build_verdict_rows(args.campaigns_dir, args.heal_queue)
    approved = sum(1 for r in rows if r["verdict"] == "APPROVE")
    rejected = sum(1 for r in rows if r["verdict"] == "REJECT")
    print(f"backfill rows: {len(rows)} ({approved} APPROVE / {rejected} REJECT)")

    if args.dry_run:
        return 0

    for row in rows:
        record_verdict(
            site_id=row["site_id"],
            source_path=row["source_path"],
            target_lang=row["target_lang"],
            content_class=row["content_class"],
            model=row["model"],
            verdict=row["verdict"],
            rubric_rules=row["rubric_rules"],
            heal_retrigger=row["heal_retrigger"],
            ledger_path=args.ledger_path,
            recorded_at=row["recorded_at"],
        )
    print(f"wrote {len(rows)} rows to qualification ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
