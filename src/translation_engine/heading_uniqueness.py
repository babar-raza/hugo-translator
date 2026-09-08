"""Intra-document heading-translation uniqueness (recurrence, 2026-09-08).

Two textually DIFFERENT English headings in the same document (e.g.
"Introduction" and "Getting Started") are each extracted and translated as
independent units with no knowledge of each other. For CJK targets in
particular, both idiomatically converge on the same canonical native phrase
(observed: ja and zh both render "Introduction" AND "Getting Started" as the
identical string), producing two H2 sections with the same visible title.

Confirmed on 2 different source pages (pdf-document-management-go: zh, ja;
pdf-document-management-python: ja) -- a RECURRENCE-ESCALATION-grade
producer bug, not model sampling variance: the i18n heading table has no
approved entry for either heading (both fall through to ordinary MT/LLM
translation), so this is a translation-choice collision, not a lookup bug.

The fix is structurally identical to frontmatter_consistency.py's cross-field
residual repair: detect the collision post-translation, then retry all but
one of the colliding headings with feedback naming the sibling's already-used
rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ["HeadingCollision", "find_duplicate_heading_translations"]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


@dataclass
class HeadingCollision:
    """A group of 2+ headings with different English source text that
    translated to the identical rendering; ``losers`` are retried, keeping
    ``winner``'s translation as the reference the retry feedback cites."""

    winner: Any
    losers: list[Any]
    shared_translation: str


def find_duplicate_heading_translations(units: list[Any]) -> list[HeadingCollision]:
    """Find groups of body headings whose DIFFERENT English source text
    translated to the identical rendering within one document."""
    eligible = []
    for unit in units:
        kind = str(getattr(unit, "kind", "") or "")
        if kind not in ("heading_text", "HEADING_TEXT"):
            continue
        if getattr(unit, "do_not_translate", False):
            continue
        translated = getattr(unit, "translated_text", None)
        if not translated or not str(translated).strip():
            continue
        source = getattr(unit, "source_text", "") or ""
        if not source.strip():
            continue
        eligible.append(unit)

    by_translation: dict[str, list[Any]] = {}
    for unit in eligible:
        key = _normalize(str(unit.translated_text))
        by_translation.setdefault(key, []).append(unit)

    collisions: list[HeadingCollision] = []
    for norm_translation, group in by_translation.items():
        if len(group) < 2:
            continue
        # Distinct-source subgroups: units in this translation group whose
        # ENGLISH source text differs (same source repeated twice is not a
        # collision -- it is the same heading, correctly rendered twice).
        distinct_sources: dict[str, list[Any]] = {}
        for unit in group:
            distinct_sources.setdefault(_normalize(unit.source_text), []).append(unit)
        if len(distinct_sources) < 2:
            continue
        # One winner (first unit of the first-seen source), every other
        # DIFFERENT-source unit in the group is a loser to retry.
        winner = group[0]
        losers = [u for u in group[1:] if _normalize(u.source_text) != _normalize(winner.source_text)]
        if not losers:
            continue
        collisions.append(
            HeadingCollision(
                winner=winner,
                losers=losers,
                shared_translation=str(winner.translated_text),
            )
        )
    return collisions
