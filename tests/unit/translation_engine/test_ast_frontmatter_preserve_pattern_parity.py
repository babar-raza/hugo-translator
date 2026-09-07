"""TC-APT-103 follow-up regression (found live 2026-09-07 on pdf-annotations-in-cpp).

`SegmentExtractor` merges `config/global.yaml`'s `body.preserve_patterns` baseline
into its own pattern list (segment_extractor.py:125-127) so every site profile
gets the shared backtick-code and bare-PascalCase-compound protections without
having to opt in. `_translate_body_ast()`'s `TextUnitExtractor` construction did
not do the same merge, so a frontmatter field containing an identifier like
"AnnotationCollection" got placeholder-protected in the legacy `segments` list
but stayed raw in the AST `TextUnitExtractor`'s units. The reuse-match step
(segment_translator.py ~1846-1878) then compared two differently-normalized
strings for the same source text, treated the unit as "not matched", and sent
it through an independent re-translation whose result disagreed with the
already-computed `translations[]` entry for the same field -- surfacing as a
spurious `ValueError: frontmatter_segment_not_applied` under zero-defect policy
for description/summary on every m2m100-primary run of that page (3/3 of
hu/ja/ro failed identically before the fix).
"""

from src.translation_engine.extractor.placeholder_manager import PlaceholderManager
from src.translation_engine.extractor.segment_extractor import (
    _get_global_body_preserve_patterns,
)
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor

_LIVE_TEXT = "Learn how to work with Annotation and AnnotationCollection in C++."


def test_global_preserve_patterns_include_pascalcase_compound_rule():
    patterns = _get_global_body_preserve_patterns()
    assert any("A-Z" in p for p in patterns), (
        "TC-APT-103's bare-PascalCase-compound pattern is expected in the "
        "global body.preserve_patterns baseline"
    )


def test_text_unit_extractor_accepts_merged_global_patterns():
    """The construction shape `_translate_body_ast` now uses: global baseline
    unioned with the site profile's own list, same as SegmentExtractor."""
    site_only_patterns = ["some-site-only-pattern"]
    merged = _get_global_body_preserve_patterns() + site_only_patterns

    extractor = TextUnitExtractor(segmentation_strategy="leaf_only", preserve_patterns=merged)

    for pattern in _get_global_body_preserve_patterns():
        assert pattern in extractor.preserve_patterns
    assert "some-site-only-pattern" in extractor.preserve_patterns


def test_pascalcase_identifier_protection_requires_global_merge():
    """Proves the actual bug condition: with only a site-local pattern list
    (empty, as on blog.aspose.org), a bare PascalCase compound identifier is
    left raw; with the global baseline merged in (segment_extractor.py's own
    behavior, and now segment_translator.py's too), it is placeholder-protected.
    Two extraction paths disagreeing on this is exactly what produced the live
    `frontmatter_segment_not_applied` failure.
    """
    global_patterns = _get_global_body_preserve_patterns()
    site_only_patterns: list[str] = []

    pm = PlaceholderManager()
    merged_protected, _ = pm.protect(_LIVE_TEXT, global_patterns + site_only_patterns)
    site_only_protected, _ = pm.protect(_LIVE_TEXT, site_only_patterns)

    assert merged_protected != site_only_protected
    assert "AnnotationCollection" not in merged_protected
    assert "AnnotationCollection" in site_only_protected
