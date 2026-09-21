"""Throughput-priority wave ordering for the work ledger (TC-APT-024, plan section 17.1).

Mission ``aspose-org-full-portfolio-translation-20260901``.

Score (lower = earlier wave), all four levers from the plan, equal weights pending calibration::

    priority_score = w1*normalize(source_char_count)      # smaller pages first
                   + w2*language_cost_tier/3              # lighter languages first
                   + w3*normalize(missing_lang_count)     # finish nearly-complete pages first
                   - w4*tm_fuzzy_hit_ratio                # templated, TM-friendly pages first

Every component is recorded per cell so the resulting order is inspectable and justifiable
against the formula (the taskcard's acceptance criterion), never an opaque sort.

``tm_fuzzy_hit_ratio`` is a *measured* proxy for TM leverage, not a guess: sources are shingled
into normalised paragraph hashes and the ratio is the fraction of a source's paragraphs that
also occur in at least one other in-scope source.  Aspose's per-product-family pages are heavily
templated, so this ranks genuine near-duplicate boilerplate first.

Language tiers are the plan's starting heuristic and are explicitly marked as such -- to be
revised once TC-APT-006 produces real per-language defect/latency data.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

#: Plan 17.1 starting heuristic (NOT validated -- revise with TC-APT-006 data).
LANGUAGE_COST_TIER: dict[str, int] = {
    **dict.fromkeys(("cs", "de", "es", "fr", "hu", "id", "it", "nl", "pl", "pt", "ro", "sv", "tr", "uk", "vi"), 0),
    **dict.fromkeys(("el", "ru"), 1),
    **dict.fromkeys(("ar", "fa", "he"), 2),
    **dict.fromkeys(("ja", "ko", "zh", "th"), 3),
}
MAX_TIER = 3
DEFAULT_WEIGHTS = (1.0, 1.0, 1.0, 1.0)
#: States that represent work still to do (a cell in a terminal state is not waved).
ACTIONABLE_STATES = frozenset(
    {
        "MISSING_TRANSLATION",
        "SOURCE_CHANGED",
        "PROFILE_CHANGED",
        "PROTECTION_RULE_CHANGED",
        "MODEL_OR_PROMPT_INVALIDATED",
        "UNKNOWN_PROVENANCE",
    }
)
WAVE_COUNT = 10

_FM_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Components:
    """Per-cell score components -- exactly the terms of the documented formula."""

    source_chars: int
    size_norm: float
    language_cost_tier: int
    tier_norm: float
    missing_lang_count: int
    missing_norm: float
    tm_fuzzy_hit_ratio: float
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_chars": self.source_chars,
            "size_norm": round(self.size_norm, 4),
            "language_cost_tier": self.language_cost_tier,
            "tier_norm": round(self.tier_norm, 4),
            "missing_lang_count": self.missing_lang_count,
            "missing_norm": round(self.missing_norm, 4),
            "tm_fuzzy_hit_ratio": round(self.tm_fuzzy_hit_ratio, 4),
            "score": round(self.score, 6),
        }


def paragraph_hashes(text: str) -> list[str]:
    """Normalised paragraph shingles (frontmatter dropped, whitespace collapsed)."""
    body = _FM_RE.sub("", text)
    out: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        norm = _WS_RE.sub(" ", para).strip().lower()
        if len(norm) >= 40:  # ignore trivially short fragments
            out.append(hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16])
    return out


def tm_fuzzy_hit_ratios(sources: dict[str, str]) -> dict[str, float]:
    """source_path -> fraction of its paragraphs shared with at least one OTHER source."""
    per_source: dict[str, list[str]] = {
        path: paragraph_hashes(text) for path, text in sources.items()
    }
    counts: Counter[str] = Counter()
    for hashes in per_source.values():
        counts.update(set(hashes))
    ratios: dict[str, float] = {}
    for path, hashes in per_source.items():
        unique = set(hashes)
        if not unique:
            ratios[path] = 0.0
            continue
        shared = sum(1 for h in unique if counts[h] > 1)
        ratios[path] = shared / len(unique)
    return ratios


def normalize(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def score_cell(
    *,
    source_chars: int,
    target_lang: str,
    missing_lang_count: int,
    tm_fuzzy_hit_ratio: float,
    char_bounds: tuple[int, int],
    max_missing: int,
    weights: tuple[float, float, float, float] = DEFAULT_WEIGHTS,
) -> Components:
    w1, w2, w3, w4 = weights
    tier = LANGUAGE_COST_TIER.get(target_lang, MAX_TIER)
    size_norm = normalize(source_chars, *char_bounds)
    tier_norm = tier / MAX_TIER
    missing_norm = normalize(missing_lang_count, 1, max(max_missing, 1))
    score = w1 * size_norm + w2 * tier_norm + w3 * missing_norm - w4 * tm_fuzzy_hit_ratio
    return Components(
        source_chars=source_chars,
        size_norm=size_norm,
        language_cost_tier=tier,
        tier_norm=tier_norm,
        missing_lang_count=missing_lang_count,
        missing_norm=missing_norm,
        tm_fuzzy_hit_ratio=tm_fuzzy_hit_ratio,
        score=score,
    )


def assign_waves(scores: list[float], wave_count: int = WAVE_COUNT) -> list[int]:
    """Equal-population quantile buckets: wave 0 = lowest scores = earliest."""
    if not scores:
        return []
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    waves = [0] * len(scores)
    per = max(1, len(scores) / wave_count)
    for rank, idx in enumerate(order):
        waves[idx] = min(wave_count - 1, int(rank // per))
    return waves


def compute_waves(
    ledger: Any,
    content_repo: Path,
    *,
    weights: tuple[float, float, float, float] = DEFAULT_WEIGHTS,
    wave_count: int = WAVE_COUNT,
    site_ids: Iterable[str] | None = None,
    dry_run: bool = False,
    sample_size: int = 20,
) -> dict[str, Any]:
    """Score every actionable cell, assign waves, write them back (unless dry_run)."""
    rows = [r for r in ledger.query() if r["eligibility_state"] in ACTIONABLE_STATES]
    if site_ids:
        wanted = set(site_ids)
        rows = [r for r in rows if r["site_id"] in wanted]
    if not rows:
        return {"cells": 0, "waves": {}, "dry_run": dry_run}

    source_paths = sorted({r["source_path"] for r in rows})
    texts: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for rel in source_paths:
        try:
            text = (content_repo / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        texts[rel] = text
        sizes[rel] = len(text)
    ratios = tm_fuzzy_hit_ratios(texts)

    missing_per_source: Counter[str] = Counter()
    for r in rows:
        missing_per_source[r["source_path"]] += 1
    char_values = [v for v in sizes.values() if v]
    bounds = (min(char_values), max(char_values)) if char_values else (0, 1)
    max_missing = max(missing_per_source.values())

    components: list[Components] = []
    for r in rows:
        components.append(
            score_cell(
                source_chars=sizes[r["source_path"]],
                target_lang=r["target_lang"],
                missing_lang_count=missing_per_source[r["source_path"]],
                tm_fuzzy_hit_ratio=ratios.get(r["source_path"], 0.0),
                char_bounds=bounds,
                max_missing=max_missing,
                weights=weights,
            )
        )
    waves = assign_waves([c.score for c in components], wave_count)

    updates = []
    wave_counts: Counter[int] = Counter()
    by_wave_lang: dict[int, Counter[str]] = defaultdict(Counter)
    for r, comp, wave in zip(rows, components, waves):
        wave_counts[wave] += 1
        by_wave_lang[wave][r["target_lang"]] += 1
        if r["wave"] != wave and not dry_run:
            row = dict(r)
            row.pop("created_at", None)
            row.pop("updated_at", None)
            row["wave"] = wave
            updates.append(row)
    if updates:
        ledger.bulk_upsert(updates, reason="TC-APT-024 wave ordering")

    ranked = sorted(zip(rows, components, waves), key=lambda item: item[1].score)
    sample = [
        {
            "wave": w,
            "site_id": r["site_id"],
            "target_lang": r["target_lang"],
            "source_path": r["source_path"],
            "state": r["eligibility_state"],
            **c.as_dict(),
        }
        for r, c, w in ranked[: sample_size // 2] + ranked[-(sample_size // 2) :]
    ]
    return {
        "cells": len(rows),
        "updated": len(updates),
        "dry_run": dry_run,
        "weights": {
            "size": weights[0],
            "language_tier": weights[1],
            "missing_fanout": weights[2],
            "tm_leverage": weights[3],
        },
        "formula": "score = w1*normalize(source_chars) + w2*(tier/3) + w3*normalize(missing_langs) - w4*tm_fuzzy_hit_ratio",
        "char_bounds": bounds,
        "max_missing_langs_for_a_page": max_missing,
        "waves": {str(k): v for k, v in sorted(wave_counts.items())},
        "wave0_languages": dict(by_wave_lang[0].most_common(10)),
        "last_wave_languages": dict(by_wave_lang[max(wave_counts)].most_common(10)),
        "sample_extremes": sample,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from datetime import datetime, timezone

    from src.utils.atomic_write import atomic_write
    from src.workers.work_ledger import DEFAULT_LEDGER_PATH, WorkLedger

    parser = argparse.ArgumentParser(description="TC-APT-024 wave ordering")
    parser.add_argument(
        "--content-repo", type=Path, default=Path("D:/onedrive/Documents/GitHub/aspose.org")
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--site", action="append", dest="sites")
    parser.add_argument("--waves", type=int, default=WAVE_COUNT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report", type=Path, default=Path("data/campaigns/wave_ordering_report.json")
    )
    args = parser.parse_args(argv)

    with WorkLedger(args.ledger) as ledger:
        report = compute_waves(
            ledger,
            args.content_repo.resolve(),
            wave_count=args.waves,
            site_ids=args.sites,
            dry_run=args.dry_run,
        )
    report["at"] = datetime.now(timezone.utc).isoformat()
    atomic_write(path=args.report, content=json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "sample_extremes"}, indent=2))
    for row in report.get("sample_extremes", [])[:6]:
        print(
            f"  wave {row['wave']} {row['target_lang']:>3} score={row['score']:.4f} chars={row['source_chars']:>6} missing={row['missing_lang_count']:>2} tm={row['tm_fuzzy_hit_ratio']:.2f} {row['source_path']}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
