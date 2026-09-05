"""Cross-field frontmatter consistency detection (TC-APT-042).

Near-duplicate frontmatter fields (typically ``description`` and ``summary``)
often contain the same source phrase, but each field is extracted and
translated as a fully independent unit with no shared context.  Observed
across 6+ languages on two source pages (introducing-words-foss-net,
introducing-pdf-foss-typescript): one field translates the shared phrase
(e.g. "MIT-licensed, zero-dependency") while its near-duplicate sibling
leaves the identical English fragment untranslated.

The sibling's own successful translation is ground truth that the phrase is
translatable, so an *asymmetric* verbatim survival is a defect.  Protected
brand/technical tokens (Aspose.PDF, FOSS, API Reference, ...) survive
verbatim in BOTH fields and are therefore never flagged — the asymmetry
condition filters them structurally, without needing a terminology list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

__all__ = ["CrossFieldResidual", "find_cross_field_residuals"]

# A shared token run qualifies as a "phrase" worth checking when it is long
# enough that its verbatim survival cannot plausibly be a cognate or a brand
# token: 3+ tokens with >=8 alphabetic chars, or 2 tokens with >=12 (catches
# hyphenated compound pairs like "MIT-licensed, zero-dependency").
_MIN_TOKENS_LOOSE = 3
_MIN_ALPHA_LOOSE = 8
_MIN_TOKENS_TIGHT = 2
_MIN_ALPHA_TIGHT = 12


@dataclass
class CrossFieldResidual:
    """One untranslated shared phrase, with the sibling field that proves it translatable."""

    unit: Any
    field_name: str
    phrase: str
    sibling_field: str
    sibling_source: str
    sibling_translation: str


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _alpha_count(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def _qualifies(tokens: list[str]) -> bool:
    phrase = " ".join(tokens)
    if "PLACEHOLDER" in phrase:
        return False
    alpha = _alpha_count(phrase)
    if len(tokens) == 1:
        # A single stranded compound (observed live: "MIT-licensed" surviving
        # in el's summary while the sibling translated it). Require a real
        # lowercase word component so bare acronyms/identifiers ("MIT",
        # "C++20") never qualify on their own — protected terms are filtered
        # by the asymmetry condition anyway, this just avoids noisy retries.
        return alpha >= 8 and bool(re.search(r"[a-z]{4,}", tokens[0]))
    long_enough = (len(tokens) >= _MIN_TOKENS_LOOSE and alpha >= _MIN_ALPHA_LOOSE) or (
        len(tokens) >= _MIN_TOKENS_TIGHT and alpha >= _MIN_ALPHA_TIGHT
    )
    # Require one substantive token so runs of short function words
    # ("for the web") do not qualify on length alone.
    return long_enough and any(len(t.strip(".,;:!?()[]")) >= 4 for t in tokens)


def _shared_token_runs(source_a: str, source_b: str) -> list[list[str]]:
    """Maximal common contiguous token runs of the two source texts."""
    tokens_a = source_a.split()
    tokens_b = source_b.split()
    if not tokens_a or not tokens_b:
        return []
    norm_a = [t.casefold() for t in tokens_a]
    norm_b = [t.casefold() for t in tokens_b]
    matcher = SequenceMatcher(a=norm_a, b=norm_b, autojunk=False)
    return [
        tokens_a[block.a : block.a + block.size]
        for block in matcher.get_matching_blocks()
        if block.size >= _MIN_TOKENS_TIGHT
    ]


def _longest_asymmetric_subrun(
    run_tokens: list[str], translated_b: str, translated_a: str
) -> str | None:
    """Longest qualifying sub-run left verbatim in B's translation but absent from A's.

    The model typically translates most of a shared phrase and strands only a
    fragment (e.g. a hyphenated compound), so the residual is a sub-run of the
    maximal shared run, not necessarily the whole of it.
    """
    total = len(run_tokens)
    for length in range(total, 0, -1):
        for start in range(0, total - length + 1):
            sub = run_tokens[start : start + length]
            if not _qualifies(sub):
                continue
            sub_norm = _normalize(" ".join(sub))
            if sub_norm in translated_b and sub_norm not in translated_a:
                return " ".join(sub)
    return None


def _unit_source(unit: Any) -> str:
    meta = getattr(unit, "metadata", None) or {}
    return meta.get("original_text") or getattr(unit, "source_text", "") or ""


def find_cross_field_residuals(units: list[Any]) -> list[CrossFieldResidual]:
    """Find frontmatter units that left a shared phrase untranslated while a sibling translated it."""
    eligible = []
    for unit in units:
        node_addr = str(getattr(unit, "node_addr", "") or "")
        if not node_addr.startswith("frontmatter."):
            continue
        if getattr(unit, "do_not_translate", False):
            continue
        translated = getattr(unit, "translated_text", None)
        if not translated or not str(translated).strip():
            continue
        meta = getattr(unit, "metadata", None) or {}
        field_name = meta.get("field_name")
        if not field_name:
            continue
        eligible.append((unit, str(field_name)))

    residuals: list[CrossFieldResidual] = []
    flagged: set[tuple[int, str]] = set()
    for unit_b, field_b in eligible:
        source_b = _unit_source(unit_b)
        translated_b = _normalize(str(unit_b.translated_text))
        for unit_a, field_a in eligible:
            if unit_a is unit_b or field_a == field_b:
                continue
            source_a = _unit_source(unit_a)
            translated_a = _normalize(str(unit_a.translated_text))
            for run_tokens in _shared_token_runs(source_b, source_a):
                # Asymmetry: B kept the English fragment verbatim, A translated it away.
                phrase = _longest_asymmetric_subrun(run_tokens, translated_b, translated_a)
                if phrase is None:
                    continue
                key = (id(unit_b), phrase.casefold())
                if key in flagged:
                    continue
                flagged.add(key)
                residuals.append(
                    CrossFieldResidual(
                        unit=unit_b,
                        field_name=field_b,
                        phrase=phrase,
                        sibling_field=field_a,
                        sibling_source=source_a,
                        sibling_translation=str(unit_a.translated_text),
                    )
                )
    return residuals
