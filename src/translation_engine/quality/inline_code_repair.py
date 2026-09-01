"""Shared inline-code-span corruption detector and repairer.

HT-INLINE-CODE-001 TC-ICR-001: single source of truth for "was this
single-backtick code span (an identifier, method name, etc.) translated
instead of preserved verbatim." Three independent, differently-buggy
reimplementations of this check existed before this module
(scripts/quality/audit_all_content.py, UnitQualityScorer, write_gate.py
Gate 22) -- none of them stripped fenced code blocks *and* excluded
newlines *and* required EN/TR span-count parity before trusting a
positional pairing. Confirmed directly against real production audit data
that skipping any one of those three guards produces false positives: a
stray/unpaired backtick lets a naive `` `([^`]+)` `` regex swallow entire
paragraphs, and positional (list-index) pairing silently mispairs spans
once EN and TR span counts diverge anywhere earlier in the same text.

Every consumer of this check should import from here instead of
maintaining its own copy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# An inline code span never legitimately crosses a line in markdown --
# without the [^`\n] exclusion, a single stray/unpaired backtick anywhere
# in the text lets the span swallow everything up to the next backtick,
# including whole paragraphs or table rows.
_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")

# Fenced code blocks must be excluded before extracting inline spans --
# otherwise the fence's own triple backticks get mispaired as inline-code
# delimiters, corrupting the span count and content for everything after.
_FENCED_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


@dataclass(frozen=True)
class InlineCodeMismatch:
    """One EN-ASCII-but-TR-non-ASCII backtick span pair, at its exact
    position in the (fence-containing) translated text."""

    index: int
    en_span: str
    tr_span: str
    tr_start: int
    tr_end: int  # exclusive; matches the FULL `...` token including backticks


def _iter_non_fenced_spans(text: str) -> list[re.Match[str]]:
    """Return backtick-span matches in `text`, excluding any that fall
    inside a fenced code block, preserving original string positions."""
    fenced_ranges = [m.span() for m in _FENCED_CODE_BLOCK_RE.finditer(text)]

    def _in_fence(pos: int) -> bool:
        return any(start <= pos < end for start, end in fenced_ranges)

    return [m for m in _BACKTICK_SPAN_RE.finditer(text) if not _in_fence(m.start())]


def find_inline_code_mismatches(
    en_text: str, tr_text: str
) -> list[InlineCodeMismatch] | None:
    """Return the list of corrupted inline-code spans in `tr_text`, or
    None if span counts don't match between en_text and tr_text (pairing
    would be unreliable -- caller should treat this as "needs manual/LLM
    review", not attempt a positional guess). Returns an empty list if
    counts match and nothing is corrupted.

    Only fires when EN has >=3 backtick spans (matches the established
    convention in write_gate.py Gate 22 / UnitQualityScorer -- avoids noise
    on trivial files with 1-2 incidental backtick uses).

    A mismatch is: the EN span is pure ASCII (i.e. looks like code/an
    identifier) but the corresponding TR span is not (i.e. it was
    translated instead of preserved).
    """
    en_spans = _iter_non_fenced_spans(en_text)
    if len(en_spans) < 3:
        return []

    tr_spans = _iter_non_fenced_spans(tr_text)
    if len(en_spans) != len(tr_spans):
        return None

    mismatches: list[InlineCodeMismatch] = []
    for idx, (en_m, tr_m) in enumerate(zip(en_spans, tr_spans)):
        en_span = en_m.group(1)
        tr_span = tr_m.group(1)
        if en_span.isascii() and not tr_span.isascii():
            mismatches.append(
                InlineCodeMismatch(
                    index=idx,
                    en_span=en_span,
                    tr_span=tr_span,
                    tr_start=tr_m.start(),
                    tr_end=tr_m.end(),
                )
            )
    return mismatches


def has_translated_inline_code(en_text: str, tr_text: str) -> bool:
    """Boolean convenience wrapper for detector call sites (write_gate.py,
    audit scripts, UnitQualityScorer). Returns False on count-mismatch
    (ambiguous pairing) rather than guessing -- callers that need to
    distinguish "clean" from "ambiguous, needs review" should call
    find_inline_code_mismatches directly."""
    mismatches = find_inline_code_mismatches(en_text, tr_text)
    return bool(mismatches)


def restore_inline_code_spans(en_text: str, tr_text: str) -> str | None:
    """Return `tr_text` with every corrupted inline-code span restored to
    its verbatim EN original, or None if there is nothing safe to fix
    (span-count mismatch, or no mismatches found).

    Safety design: replacements are applied by exact byte-offset splicing
    of the matched `` `...` `` token (never a blind str.replace, which
    could hit the wrong occurrence of duplicated text elsewhere in the
    document). A hard invariant is asserted before returning: the text
    *outside* every replaced span must be byte-identical between the
    original and the patched text -- proven by construction below, and
    verified at runtime rather than merely assumed. If that verification
    fails, this function returns None instead of a partially-trusted patch.
    """
    mismatches = find_inline_code_mismatches(en_text, tr_text)
    if not mismatches:
        return None

    unchanged_pieces: list[str] = []
    patched_pieces: list[str] = []
    patched_replacement_spans: list[tuple[int, int]] = []
    cursor = 0
    patched_cursor = 0
    for mm in mismatches:
        unchanged = tr_text[cursor : mm.tr_start]
        unchanged_pieces.append(unchanged)
        patched_pieces.append(unchanged)
        patched_cursor += len(unchanged)

        replacement = f"`{mm.en_span}`"
        patched_pieces.append(replacement)
        patched_replacement_spans.append(
            (patched_cursor, patched_cursor + len(replacement))
        )
        patched_cursor += len(replacement)

        cursor = mm.tr_end

    tail = tr_text[cursor:]
    unchanged_pieces.append(tail)
    patched_pieces.append(tail)

    patched = "".join(patched_pieces)

    if not _verify_only_replacements_differ(
        patched, patched_replacement_spans, unchanged_pieces
    ):
        return None

    return patched


def _verify_only_replacements_differ(
    patched: str,
    patched_replacement_spans: list[tuple[int, int]],
    expected_unchanged_pieces: list[str],
) -> bool:
    """Remove the known replacement spans from `patched` (using
    patched-string-space offsets, tracked while `patched` was built -- no
    offset arithmetic across the two different string lengths) and confirm
    what remains matches the unchanged pieces copied verbatim from the
    original text. This is the hard safety invariant: proof, not
    assumption, that nothing outside the flagged span(s) changed."""
    reconstructed_unchanged: list[str] = []
    cursor = 0
    for start, end in patched_replacement_spans:
        reconstructed_unchanged.append(patched[cursor:start])
        cursor = end
    reconstructed_unchanged.append(patched[cursor:])

    return reconstructed_unchanged == expected_unchanged_pieces
