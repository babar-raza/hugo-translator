"""Character-level fidelity of model output against its source.

TC-APT-073. Measured on words-document-net's seven accepted cells: U+2011
NON-BREAKING HYPHEN appears in 7 of 7 locales -- 147 occurrences (nl 67, he 37,
fr 22, hi 11, el 7, ar 2, fa 1) -- with ZERO in the English source, and U+00AD
SOFT HYPHEN appears word-interior in fr. Both render like ordinary punctuation,
so two independent reviewer batches caught them in only 2 of the 7 locales,
while they break copy, search and diffing everywhere. By RB-005's recurrence
test -- the same defect at the same structural position across multiple locales
is not variance -- this is a producer bug.

This lives in its own leaf module because BOTH translation paths need it and
they must not import each other: `segment_translator` handles the legacy /
non-AST path, and `reconstructor.ast_renderer` is authoritative for body AND
frontmatter on every AST-enabled profile (which is all in-scope sites).
"""

from __future__ import annotations

# Value is the replacement: "" deletes, "-" substitutes the ASCII form.
#
# U+200E/U+200F RTL marks are deliberately absent: they can be functionally
# necessary in ar/fa/he bidi text, and the same measurement found zero of them
# injected. U+00A0 NBSP is also absent -- French typography uses it legitimately
# before ':' and '!', and it too measured zero injected.
_INJECTED_INVISIBLES: dict[str, str] = {
    "­": "",   # SOFT HYPHEN -- invisible; splits a word for search/copy
    "‑": "-",  # NON-BREAKING HYPHEN -- renders as a hyphen, is not one
    "​": "",   # ZERO WIDTH SPACE
    "⁠": "",   # WORD JOINER
}


def normalize_injected_invisibles(source_text: str | None, translated_text: str | None) -> str | None:
    """Strip invisible/lookalike punctuation the model introduced on its own.

    Conditional on the source: a character the source itself uses is left
    alone, so this is a fidelity rule ("do not introduce what the source
    lacks") rather than a character ban, and a page that deliberately typesets
    a non-breaking hyphen keeps it.

    Call this on model output while protected spans are still masked, so code
    spans, links and shortcodes can never be rewritten by it.
    """
    if not translated_text:
        return translated_text
    source = source_text or ""
    result = translated_text
    for character, replacement in _INJECTED_INVISIBLES.items():
        if character in result and character not in source:
            result = result.replace(character, replacement)
    return result
