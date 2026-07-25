"""
UnitQualityScorer — per-unit quality detection for translated files.

Compares EN source TextUnits against translated TextUnits and flags
bad units by issue type. Used by unit_heal.py to identify exactly which
units need re-translation, avoiding full-file re-translation overhead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from .extractor.text_unit import TextUnit, TextUnitKind
from .quality.inline_code_repair import has_translated_inline_code as _has_translated_inline_code_shared

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_MOJIBAKE_RE = re.compile(
    r"â€[\"'‘’“”—–]"
    r"|Ã[©è¼½¾\xbf\xa0]"
    r"|â€\x9c|â€\x9d|â€™|â€œ"
)

_SHORTCODE_RE = re.compile(r"\{\{[<%].*?[>%]\}\}", re.DOTALL)

_INLINE_CODE_RE = re.compile(r"`([^`]+)`")

_LINK_URL_RE = re.compile(r"\[(?:[^\[\]]*)\]\(([^)]+)\)")

# Non-Latin locales where ASCII prose headings / cells are suspicious
_NON_LATIN_LOCALES = frozenset(
    "ar bg el fa he hi ja ko ru th uk zh".split()
)

_SHORT_API_DESC_RE = re.compile(
    r"^(?:Gets?|Sets?|Indicates?|Enables?|Disables?|Represents?)\s", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class UnitIssue:
    """A quality issue found in a single TextUnit."""

    unit_idx: int
    unit: TextUnit
    issue_type: str
    confidence: float  # 0.0 = definitely bad, 1.0 = definitely good
    en_unit: TextUnit | None = None


@dataclass
class UnitQualityScorer:
    """
    Scores each translated TextUnit against its EN source counterpart.

    Returns a list of UnitIssue objects for units that failed quality checks.
    Empty list means the file is clean for the requested detectors.

    Usage::

        scorer = UnitQualityScorer(config={}, locale="uk")
        issues = scorer.score(en_units, tr_units)
        bad_indices = [i.unit_idx for i in issues]
    """

    config: dict[str, Any] = field(default_factory=dict)
    locale: str = "en"

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def score(
        self,
        en_units: list[TextUnit],
        tr_units: list[TextUnit],
    ) -> list[UnitIssue]:
        """
        Score translated units against EN source units.

        Units are paired by position. When counts differ, LCS alignment is
        used as a fallback so col/row insertions don't cascade all pairings.

        Returns list of UnitIssue for every bad unit found.
        """
        pairs = self._pair_units(en_units, tr_units)
        issues: list[UnitIssue] = []
        for tr_idx, (en_unit, tr_unit) in pairs:
            issues.extend(self._check_unit(tr_idx, en_unit, tr_unit))
        return issues

    # -----------------------------------------------------------------------
    # Pairing
    # -----------------------------------------------------------------------

    def _pair_units(
        self, en_units: list[TextUnit], tr_units: list[TextUnit]
    ) -> list[tuple[int, tuple[TextUnit | None, TextUnit]]]:
        """
        Pair tr_units with en_units. Returns [(tr_idx, (en_unit|None, tr_unit))].

        Uses index-based pairing when counts match; LCS alignment otherwise.
        """
        if len(en_units) == len(tr_units):
            return [(i, (en_units[i], tr_units[i])) for i in range(len(tr_units))]

        # LCS on (kind, source_text[:30]) tuples
        en_keys = [(u.kind, u.source_text[:30]) for u in en_units]
        tr_keys = [(u.kind, u.source_text[:30]) for u in tr_units]
        matcher = SequenceMatcher(None, en_keys, tr_keys, autojunk=False)

        en_matched: dict[int, int] = {}  # tr_idx → en_idx
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                en_matched[block.b + offset] = block.a + offset

        result = []
        for tr_idx, tr_unit in enumerate(tr_units):
            en_idx = en_matched.get(tr_idx)
            en_unit = en_units[en_idx] if en_idx is not None else None
            result.append((tr_idx, (en_unit, tr_unit)))
        return result

    # -----------------------------------------------------------------------
    # Per-unit checks
    # -----------------------------------------------------------------------

    def _check_unit(
        self,
        tr_idx: int,
        en_unit: TextUnit | None,
        tr_unit: TextUnit,
    ) -> list[UnitIssue]:
        issues: list[UnitIssue] = []
        tr_text = tr_unit.translated_text or tr_unit.source_text or ""
        en_text = en_unit.source_text if en_unit else ""

        if not tr_text.strip():
            return issues

        # mojibake_detector
        if _MOJIBAKE_RE.search(tr_text):
            issues.append(UnitIssue(tr_idx, tr_unit, "mojibake_detector", 0.0, en_unit))

        # shortcode_leak_detector
        if _SHORTCODE_RE.search(tr_text) and not _SHORTCODE_RE.search(en_text):
            issues.append(UnitIssue(tr_idx, tr_unit, "shortcode_leak_detector", 0.0, en_unit))

        # inline_code_integrity_detector
        if en_unit and self._has_translated_inline_code(en_text, tr_text):
            issues.append(
                UnitIssue(tr_idx, tr_unit, "inline_code_integrity_detector", 0.0, en_unit)
            )

        # empty_unit_detector
        if en_unit:
            en_len = len(en_text.strip())
            tr_len = len(tr_text.strip())
            if en_len > 20 and tr_len < 0.10 * en_len:
                issues.append(UnitIssue(tr_idx, tr_unit, "empty_unit_detector", 0.0, en_unit))

        # hallucination_length_detector (TABLE_CELL_TEXT)
        if en_unit and tr_unit.kind is TextUnitKind.TABLE_CELL_TEXT:
            en_len = len(en_text.strip())
            tr_len = len(tr_text.strip())
            if en_len > 0 and tr_len > 3.0 * en_len:
                issues.append(
                    UnitIssue(tr_idx, tr_unit, "hallucination_length_detector", 0.2, en_unit)
                )

        # short_api_desc_detector — short descriptions that MT hallucinates
        if (
            self.locale in _NON_LATIN_LOCALES
            and tr_unit.kind is TextUnitKind.TABLE_CELL_TEXT
            and en_unit
            and len(en_text.strip()) <= 60
            and _SHORT_API_DESC_RE.match(en_text.strip())
        ):
            # Check if translation looks like a hallucination (non-target-script content)
            if self._appears_hallucinated(tr_text, en_text):
                issues.append(
                    UnitIssue(tr_idx, tr_unit, "short_api_desc_detector", 0.3, en_unit)
                )

        # language_purity_detector (HEADING_TEXT, TEXT in non-Latin locales)
        # Fires when:
        # (a) TR is ASCII prose in a non-Latin locale AND EN was NOT ASCII-only, OR
        # (b) TR is identical to EN for a HEADING (un-translated heading in non-Latin doc)
        _purity_heading_identical = (
            tr_unit.kind is TextUnitKind.HEADING_TEXT
            and en_unit is not None
            and tr_text.strip()
            and tr_text.strip() == en_text.strip()
            and self._is_ascii_prose(tr_text)
        )
        _purity_wrong_script = (
            tr_unit.kind in (TextUnitKind.HEADING_TEXT, TextUnitKind.TEXT)
            and tr_text.strip()
            and self._is_ascii_prose(tr_text)
            and not self._is_ascii_prose(en_text)
        )
        if self.locale in _NON_LATIN_LOCALES and (_purity_heading_identical or _purity_wrong_script):
            issues.append(
                UnitIssue(tr_idx, tr_unit, "language_purity_detector", 0.1, en_unit)
            )

        # duplicate_run_detector (TEXT units)
        if tr_unit.kind is TextUnitKind.TEXT and self._has_duplicate_run(tr_text):
            issues.append(UnitIssue(tr_idx, tr_unit, "duplicate_run_detector", 0.0, en_unit))

        # link_path_detector
        if en_unit and self._has_corrupted_link_path(en_text, tr_text):
            issues.append(UnitIssue(tr_idx, tr_unit, "link_path_detector", 0.2, en_unit))

        # newline_ratio_detector
        if en_unit:
            en_nl = en_text.count("\n")
            tr_nl = tr_text.count("\n")
            if en_nl >= 3 and tr_nl > 2.5 * en_nl:
                issues.append(
                    UnitIssue(tr_idx, tr_unit, "newline_ratio_detector", 0.2, en_unit)
                )

        return issues

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _has_translated_inline_code(en_text: str, tr_text: str) -> bool:
        """Return True if any backtick span was ASCII in EN but non-ASCII in TR.

        HT-INLINE-CODE-001 TC-ICR-004: delegated to the shared
        src/translation_engine/quality/inline_code_repair.py primitive
        instead of this class's own index-based pairing (which had no
        fenced-code-block exclusion, no newline exclusion, and used
        `en_spans.index(en_span)` -- silently wrong on a repeated span
        value -- to look up the "matching" TR span by position). The
        shared primitive also declines to fire on an EN/TR span-count
        mismatch rather than guessing a positional pairing.
        """
        return _has_translated_inline_code_shared(en_text, tr_text)

    @staticmethod
    def _is_ascii_prose(text: str) -> bool:
        """True if the text is mostly ASCII alphabetic (looks like untranslated English)."""
        stripped = text.strip()
        if not stripped:
            return False
        ascii_alpha = sum(1 for c in stripped if c.isascii() and c.isalpha())
        total_alpha = sum(1 for c in stripped if c.isalpha())
        if total_alpha == 0:
            return False
        return ascii_alpha / total_alpha > 0.85

    @staticmethod
    def _appears_hallucinated(tr_text: str, en_text: str) -> bool:
        """Heuristic: TR length is >3x EN or TR contains obviously wrong content."""
        en_stripped = en_text.strip()
        tr_stripped = tr_text.strip()
        if not en_stripped:
            return False
        # Length explosion suggests hallucination
        if len(tr_stripped) > 3 * len(en_stripped):
            return True
        return False

    @staticmethod
    def _has_duplicate_run(text: str) -> bool:
        """True if any paragraph is repeated 3+ consecutive times."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) < 3:
            return False
        for i in range(len(paragraphs) - 2):
            if paragraphs[i] == paragraphs[i + 1] == paragraphs[i + 2]:
                return True
        return False

    @staticmethod
    def _has_corrupted_link_path(en_text: str, tr_text: str) -> bool:
        """True if any relative link URL in TR differs from EN."""
        en_urls = _LINK_URL_RE.findall(en_text)
        tr_urls = _LINK_URL_RE.findall(tr_text)
        relative = [u for u in en_urls if u.startswith("..") or u.startswith("/")]
        if not relative:
            return False
        for i, en_url in enumerate(en_urls):
            if en_url.startswith("..") or en_url.startswith("/"):
                if i < len(tr_urls) and tr_urls[i] != en_url:
                    return True
        return False
