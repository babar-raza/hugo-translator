"""
Glued-identifier validator (TC-APT-110, 2026-09-11).

Catches a reader-facing defect class the rest of the battery is blind to:
a technical identifier from the source glued directly onto surrounding
prose with no separator -- e.g. cs "pomocíWorkbook.save", pt
"comWorkbook.save", hu "aWorkbook.save" (all shipped through 44 accepting
gates in wave-cellsrust-quickstart-glueretrigger-20260911r2 and were only
caught by human-tier rubric review, rule RB-004).

The glue has TWO producer paths, so no extractor-side fix can close the
class alone (see data/summaries/
fp-wave-cellsrust-quickstart-glueretrigger-20260911r2-desc-glue.json):

1. Restore-time: the model drops the space around an intact
   {PLACEHOLDER_N} token; PlaceholderManager.restore() re-inserts it since
   5c642cc1.
2. Generation-time: the identifier was never placeholder-protected in that
   unit (confirmed by instrumented trace: the description field's map held
   only 'Aspose.Cells' -- 'Workbook.save' was literal text) and the model
   emits it directly glued to a preposition/article. Only a gate can catch
   this: whether a given generation glues is stochastic.

Scope: DOTTED/UNDERSCORED identifiers from the source only (Workbook.save,
load_xlsx, Aspose.Cells, Cargo.toml). These are non-inflectable, so a
letter glued directly against them is never legitimate in a
space-delimited script. Plain capitalized terms (Rust, Excel) are
deliberately NOT checked: Slavic languages inflect them by direct
suffixation (cs "v Rustu") and Arabic/Persian attach particles/suffixes
("وWOFF2", "URLها"), which a 13,202-file sweep of committed content showed
to be overwhelmingly legitimate morphology, not defects.

Exemptions, each validated against that same sweep (final in-scope
false-positive count: zero; every surviving hit was a real committed
defect):

- Adjacent character in a no-space script (CJK, Thai, ...) -- always
  legal ("使用Workbook.save保存" is correct zh).
- Punctuation, hyphen, digit boundaries -- always legal
  (hu "Workbook.save-el", "(Aspose.Cells)", fi "tsconfig.json:issa").
- The occurrence sits inside a larger dot/word token that itself appears
  in the source (term "input.doc" matching inside "input.docx") --
  compared after normalizing markdown-escaped underscores (\\_ -> _).
- The occurrence sits inside a larger token whose surrounding parts carry
  '.'/'_' structure of their own (term "email_str" inside a translation's
  "MapiMessage.to_email_string"): a code-ish composite, not prose glue.
  Prose glue's surrounding run is pure letters ("comWorkbook.save").
- A SINGLE Arabic-script letter attached before the identifier: the
  one-letter conjunctions/prepositions و/ب/ل/ف/ك attach to the following
  word by orthographic rule ("وAspose.Cells" = "and Aspose.Cells").
  A multi-letter Arabic word glued ("باستخدامWorkbook.save") still fails.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ValidationResult, ValidationSeverity, Validator

# Scripts that conventionally write foreign terms with no separating space.
# Mirrors _NO_SPACE_SCRIPT_RANGES in
# src/translation_engine/extractor/placeholder_manager.py (kept local: the
# validation package must not import extractor internals).
_NO_SPACE_SCRIPT_RANGES = (
    (0x3040, 0x30FF),  # Hiragana, Katakana
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x1100, 0x11FF),  # Hangul Jamo
    (0xAC00, 0xD7A3),  # Hangul Syllables
    (0x0E00, 0x0E7F),  # Thai
    (0x0E80, 0x0EFF),  # Lao
    (0x1000, 0x109F),  # Myanmar
    (0x1780, 0x17FF),  # Khmer
)

_ARABIC_SCRIPT_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)

# Identifier with at least one internal dot/underscore segment:
# Workbook.save, Workbook.load_xlsx, Aspose.Cells, Cargo.toml
_DOTTED_IDENTIFIER_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*(?:[._][A-Za-z0-9]+)+\b"
)

# A word character extends an identifier-ish token around a match; a dot
# extends it ONLY when flanked by word characters on both sides, so a
# sentence-final period ("pomocíWorkbook.load_xlsx.") is never absorbed
# into the token (it would smuggle a '.' into the code-composite
# exemption's "outside" parts and hide real prose glue).
_WORD_CHAR_RE = re.compile(r"\w", re.UNICODE)


def _in_ranges(ch: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    codepoint = ord(ch)
    return any(lo <= codepoint <= hi for lo, hi in ranges)


def _maximal_token_span(text: str, start: int, end: int) -> tuple[int, int]:
    a, b = start, end
    while a > 0:
        ch = text[a - 1]
        if _WORD_CHAR_RE.match(ch):
            a -= 1
        elif ch == "." and a - 1 > 0 and _WORD_CHAR_RE.match(text[a - 2]):
            a -= 1
        else:
            break
    while b < len(text):
        ch = text[b]
        if _WORD_CHAR_RE.match(ch):
            b += 1
        elif ch == "." and b + 1 < len(text) and _WORD_CHAR_RE.match(text[b + 1]):
            b += 1
        else:
            break
    return a, b


class GluedIdentifierValidator(Validator):
    """Reject translations where a dotted/underscored source identifier is
    glued directly against prose letters (see module docstring)."""

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        result = ValidationResult(success=True)

        terms = set(_DOTTED_IDENTIFIER_RE.findall(source))
        if not terms:
            return result
        # Markdown sources escape underscores in prose ("to\_email\_string");
        # normalize so the containing-token exemption can match either form.
        source_normalized = source.replace("\\_", "_")

        for term in sorted(terms):
            self._check_occurrences(term, translation, source_normalized, result)

        if result.has_errors():
            result.success = False
        return result

    def _check_occurrences(
        self,
        term: str,
        translation: str,
        source_normalized: str,
        result: ValidationResult,
    ) -> None:
        for match in re.finditer(re.escape(term), translation):
            start, end = match.span()
            tok_start, tok_end = _maximal_token_span(translation, start, end)
            token = translation[tok_start:tok_end]
            if token != term:
                if token in source_normalized:
                    continue
                outside = translation[tok_start:start] + translation[end:tok_end]
                if "." in outside or "_" in outside:
                    continue
            before = translation[start - 1] if start > 0 else ""
            after = translation[end] if end < len(translation) else ""
            for side, ch in (("before", before), ("after", after)):
                if not ch or not ch.isalpha():
                    continue
                if _in_ranges(ch, _NO_SPACE_SCRIPT_RANGES):
                    continue
                if side == "before" and _in_ranges(ch, _ARABIC_SCRIPT_RANGES):
                    prev = translation[start - 2] if start > 1 else ""
                    if not prev.isalpha():
                        continue
                snippet_lo = max(0, start - 20)
                snippet_hi = min(len(translation), end + 20)
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"Identifier '{term}' glued against letter "
                        f"'{ch}' ({side}) with no separator: "
                        f"...{translation[snippet_lo:snippet_hi]}...",
                        location="glued_identifier",
                        details={
                            "term": term,
                            "side": side,
                            "adjacent_char": ch,
                            "context_snippet": translation[snippet_lo:snippet_hi],
                        },
                    )
                )
                break  # one issue per occurrence is enough
