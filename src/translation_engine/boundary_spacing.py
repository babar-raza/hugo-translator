"""TC-APT-110/111 (2026-09-11): shared answer to "does restoring a protected
value here need a synthetic boundary space?" -- the LLM/MT model can drop the
whitespace immediately before/after a placeholder token during generation
while leaving the placeholder itself intact (braces or {TERM_N} form), gluing
the restored value directly onto adjacent prose (e.g. "com{PLACEHOLDER_0}" ->
"comWorkbook.save"). Two independent restore() implementations need this
exact check -- PlaceholderManager (extractor, AST/M2M100 path) and
TerminologyProtector (terminology, LLM-backend path) -- so it lives here
rather than being duplicated (and drifting) in both.
"""

from __future__ import annotations

# Scripts that conventionally write with NO space between adjacent
# words/foreign terms -- inserting a synthetic space for these would itself
# be wrong, so the glued-word fix never fires when either boundary character
# falls in one of these ranges. Confirmed by the real defect's own
# distribution: it only ever appeared in space-delimited scripts (ar cs es fa
# hu nl pt uk); ja/ko/zh/th candidates on the same page, same run, kept
# correct spacing around the identical Latin identifiers.
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


def is_no_space_script_char(ch: str) -> bool:
    codepoint = ord(ch)
    return any(lo <= codepoint <= hi for lo, hi in _NO_SPACE_SCRIPT_RANGES)


def needs_space_boundary(context_char: str, value_char: str) -> bool:
    """True if a placeholder's restored value would butt directly against
    `context_char` with zero separator, in a script where that is never a
    legitimate construction (see `_NO_SPACE_SCRIPT_RANGES`).

    Deliberately restricted to letter/digit-against-letter/digit: a
    placeholder boundary against punctuation (parens, colons, quotes) is
    common and legitimate (e.g. the documented Finnish case-suffix
    "PLACEHOLDER_0:n" -- the colon is not alnum, so this returns False and
    that behavior is unchanged).
    """
    if not context_char or not value_char:
        return False
    if not (context_char.isalnum() and value_char.isalnum()):
        return False
    if is_no_space_script_char(context_char) or is_no_space_script_char(value_char):
        return False
    return True
