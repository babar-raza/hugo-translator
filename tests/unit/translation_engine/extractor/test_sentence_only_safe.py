"""
SHORTCODE-007: Tests for safe sentence_only behavior.

Verifies that sentence_only strategy now checks for formatting/technical content
and falls back to leaf-level extraction when needed, preventing token leakage.
"""

import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import NodeType
from src.translation_engine.parser.hugo_parser import HugoParser


class TestSentenceOnlySafeBehavior:
    """
    Test that sentence_only behaves safely (sentence_only_when_safe).

    After SHORTCODE-007 fix:
    - Plain paragraphs → extracted as full sentence
    - Paragraphs with shortcodes → leaf-level extraction
    - Paragraphs with bold/links/code → leaf-level extraction
    """

    @pytest.fixture
    def parser(self):
        """Create HugoParser instance."""
        return HugoParser(enable_tables=True)

    @pytest.fixture
    def extractor_sentence_only(self):
        """Create extractor with sentence_only strategy."""
        return TextUnitExtractor(segmentation_strategy="sentence_only", preserve_patterns=[])

    def test_plain_paragraph_extracted_as_sentence(self, parser, extractor_sentence_only):
        """
        Plain paragraph (no formatting) should be extracted as full sentence.
        """
        markdown = """---
title: Test
---

This is a plain paragraph with no formatting at all.
"""

        doc = parser.parse_string(markdown)
        plan = extractor_sentence_only.extract_from_ast(doc.ast, doc.frontmatter)

        # Should extract as single unit (full sentence) - filter to body units only
        body_units = [
            u for u in plan.units if not u.do_not_translate and u.node_addr.startswith("body.")
        ]
        assert len(body_units) == 1, f"Expected 1 body unit, got {len(body_units)}"
        assert "plain paragraph" in body_units[0].source_text

    def test_paragraph_with_shortcode_extracts_as_full_sentence(
        self, parser, extractor_sentence_only
    ):
        """
        Paragraph with embedded shortcode is extracted as a full sentence unit.

        Design: INLINE_HTML (shortcodes) is intentionally excluded from
        _has_inline_formatting so that sentence_only extracts the full sentence.
        The shortcode is preserved in-place and protected downstream by
        placeholder_manager before translation occurs.
        """
        markdown = """---
title: Test
---

Intro text {{< sections >}} outro text.
"""

        doc = parser.parse_string(markdown)

        # Verify parser created INLINE_HTML node
        para = doc.ast[0]
        inline_html_nodes = [c for c in para.children if c.type == NodeType.INLINE_HTML]
        assert len(inline_html_nodes) == 1, "Parser should create INLINE_HTML for shortcode"

        # Extract units
        plan = extractor_sentence_only.extract_from_ast(doc.ast, doc.frontmatter)

        # Should extract as a single full-sentence unit containing the shortcode.
        # The shortcode is protected downstream by placeholder_manager.
        body_units = [
            u for u in plan.units if not u.do_not_translate and u.node_addr.startswith("body.")
        ]
        assert len(body_units) == 1, (
            f"Expected 1 full-sentence body unit, got {len(body_units)}: {[u.source_text for u in body_units]}"
        )
        assert "{{<" in body_units[0].source_text, (
            "Shortcode should be present in the unit for downstream placeholder protection"
        )
        assert "Intro text" in body_units[0].source_text
        assert "outro text" in body_units[0].source_text

    def test_paragraph_with_bold_uses_leaf_extraction(self, parser, extractor_sentence_only):
        """
        Paragraph with bold text should use leaf-level extraction.
        """
        markdown = """---
title: Test
---

This has **bold text** inside.
"""

        doc = parser.parse_string(markdown)
        plan = extractor_sentence_only.extract_from_ast(doc.ast, doc.frontmatter)

        # Should extract at leaf level (not full sentence)
        translatable_units = [u for u in plan.units if not u.do_not_translate]
        assert len(translatable_units) >= 2, "Bold formatting should trigger leaf-level extraction"

    def test_paragraph_with_link_uses_leaf_extraction(self, parser, extractor_sentence_only):
        """
        Paragraph with link should use leaf-level extraction.
        """
        markdown = """---
title: Test
---

See [documentation](https://example.com) for details.
"""

        doc = parser.parse_string(markdown)
        plan = extractor_sentence_only.extract_from_ast(doc.ast, doc.frontmatter)

        translatable_units = [u for u in plan.units if not u.do_not_translate]
        assert len(translatable_units) >= 2, "Link should trigger leaf-level extraction"

    def test_paragraph_with_code_uses_leaf_extraction(self, parser, extractor_sentence_only):
        """
        Paragraph with inline code should use leaf-level extraction.
        """
        markdown = """---
title: Test
---

Use `SaveFormat.Pdf` for output.
"""

        doc = parser.parse_string(markdown)
        plan = extractor_sentence_only.extract_from_ast(doc.ast, doc.frontmatter)

        translatable_units = [u for u in plan.units if not u.do_not_translate]
        assert len(translatable_units) >= 2, "Inline code should trigger leaf-level extraction"

    def test_multiple_shortcodes_extracted_as_full_sentence(self, parser, extractor_sentence_only):
        """
        Paragraph with multiple shortcodes is extracted as a full sentence unit.

        Design: INLINE_HTML (shortcodes) is intentionally excluded from
        _has_inline_formatting so sentence_only extracts the full sentence.
        All shortcodes are preserved in the unit for downstream placeholder protection.
        """
        markdown = """---
title: Test
---

Start {{< callout >}} middle {{< ref >}} end.
"""

        doc = parser.parse_string(markdown)
        plan = extractor_sentence_only.extract_from_ast(doc.ast, doc.frontmatter)

        body_units = [
            u for u in plan.units if not u.do_not_translate and u.node_addr.startswith("body.")
        ]

        # Should extract as a single full-sentence unit containing both shortcodes.
        assert len(body_units) == 1, (
            f"Expected 1 full-sentence body unit, got {len(body_units)}: {[u.source_text for u in body_units]}"
        )
        assert "{{<" in body_units[0].source_text, (
            "Shortcodes should be present in the unit for downstream placeholder protection"
        )
        assert "Start" in body_units[0].source_text
        assert "end" in body_units[0].source_text

    def test_complex_paragraph_uses_leaf_extraction(self, parser, extractor_sentence_only):
        """
        Complex paragraph with multiple formatting types.
        """
        markdown = """---
title: Test
---

This has **bold**, `code`, [link](url), and {{< shortcode >}} all mixed.
"""

        doc = parser.parse_string(markdown)
        plan = extractor_sentence_only.extract_from_ast(doc.ast, doc.frontmatter)

        translatable_units = [u for u in plan.units if not u.do_not_translate]

        # Should extract at leaf level (multiple units)
        assert len(translatable_units) >= 3, (
            "Complex formatting should trigger leaf-level extraction"
        )

        # Verify no synthetic tokens in translatable units
        for unit in translatable_units:
            # Should not contain raw markdown syntax
            assert "{{<" not in unit.source_text, f"Shortcode leaked: {unit.source_text}"


class TestAdaptiveStrategyUnchanged:
    """
    Verify adaptive strategy behavior is unchanged.

    Adaptive already had safe behavior - this confirms it still works.
    """

    @pytest.fixture
    def parser(self):
        return HugoParser(enable_tables=True)

    @pytest.fixture
    def extractor_adaptive(self):
        return TextUnitExtractor(segmentation_strategy="adaptive", preserve_patterns=[])

    def test_adaptive_plain_paragraph_extracted_as_sentence(self, parser, extractor_adaptive):
        """Adaptive: plain paragraph extracted as full sentence."""
        markdown = "---\ntitle: T\n---\nPlain text paragraph."
        doc = parser.parse_string(markdown)
        plan = extractor_adaptive.extract_from_ast(doc.ast, doc.frontmatter)

        # Filter to body units only (exclude frontmatter)
        body_units = [
            u for u in plan.units if not u.do_not_translate and u.node_addr.startswith("body.")
        ]
        assert len(body_units) == 1, f"Expected 1 body unit, got {len(body_units)}"

    def test_adaptive_formatted_paragraph_uses_leaf(self, parser, extractor_adaptive):
        """Adaptive: formatted paragraph uses leaf-level extraction."""
        markdown = "---\ntitle: T\n---\nText with **bold** inside."
        doc = parser.parse_string(markdown)
        plan = extractor_adaptive.extract_from_ast(doc.ast, doc.frontmatter)

        translatable_units = [u for u in plan.units if not u.do_not_translate]
        assert len(translatable_units) >= 2


class TestLeafOnlyStrategyUnchanged:
    """
    Verify leaf_only strategy behavior is unchanged.

    leaf_only should always extract at leaf level.
    """

    @pytest.fixture
    def parser(self):
        return HugoParser(enable_tables=True)

    @pytest.fixture
    def extractor_leaf_only(self):
        return TextUnitExtractor(segmentation_strategy="leaf_only", preserve_patterns=[])

    def test_leaf_only_always_extracts_leaves(self, parser, extractor_leaf_only):
        """leaf_only always extracts at leaf level (even plain text)."""
        markdown = "---\ntitle: T\n---\nPlain text paragraph."
        doc = parser.parse_string(markdown)
        plan = extractor_leaf_only.extract_from_ast(doc.ast, doc.frontmatter)

        translatable_units = [u for u in plan.units if not u.do_not_translate]
        # leaf_only extracts individual text nodes
        assert len(translatable_units) >= 1
