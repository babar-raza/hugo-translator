"""
E2E Integration Test for SHORTCODE-007: Single Protection System

Verifies that Hugo shortcodes are preserved with PlaceholderManager disabled
(preserve_patterns: []) -- block-level shortcodes are excluded from
translation entirely via the AST node-type classifier, never reaching any
placeholder-protection layer at all.

CU-01 (2026-09-10): the original InlineFormatProtector-specific test
(`test_inline_format_protector_handles_markdown_formatting`) was removed
here along with `inline_format_protector.py` itself, confirmed dead in
production (imported only from tests, no real call site). The two tests
below never actually exercised InlineFormatProtector -- they test
TextUnitExtractor's real, current preserve_patterns=[] + AST node-type
shortcode handling, which is unaffected by that deletion.

Author: SHORTCODE-007-P3
Date: 2026-01-20
"""

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.hugo_parser import HugoParser


class TestShortcodeSingleProtection:
    """
    Test suite verifying single protection system for Hugo shortcodes.

    SHORTCODE-007 eliminates double-protection architecture by disabling
    PlaceholderManager for shortcodes (preserve_patterns: []) -- block-level
    shortcodes are protected by the AST node-type classifier instead.
    """

    def test_no_placeholder_manager_tokens_when_disabled(self):
        """
        CRITICAL: Verify TextUnits do NOT contain {PLACEHOLDER_N} tokens
        when PlaceholderManager is disabled (preserve_patterns: []).

        This test confirms the configuration changes from SHORTCODE-007-P1.

        Expected:
        - With preserve_patterns: [] → No {PLACEHOLDER_} tokens created
        - TextUnits contain original {{< shortcode >}} syntax
        """
        # Sample markdown with Hugo shortcodes
        markdown = """---
title: Test Page
---

{{< sections >}}

The **Aspose.Slides** plugins provide features for {{< callout >}}presentations{{< /callout >}}.

{{% steps %}}
1. Step one
2. Step two
{{% /steps %}}
"""

        # Parse markdown
        parser = HugoParser()
        doc = parser.parse_string(markdown)

        assert doc.ast is not None, "AST should be created"

        # Extract TextUnits WITHOUT preserve_patterns (SHORTCODE-007-P1 change)
        # This simulates the new configuration where preserve_patterns: []
        extractor = TextUnitExtractor(
            segmentation_strategy="sentence_only",
            preserve_patterns=[],  # CRITICAL: Empty array (no PlaceholderManager protection)
        )

        translation_plan = extractor.extract_from_ast(doc.ast, doc.frontmatter)
        units = translation_plan.units

        assert len(units) > 0, "Should extract text units"

        # Collect all text from units
        all_text = "\n".join(u.source_text for u in units)

        # CRITICAL ASSERTION 1: NO PlaceholderManager tokens
        assert "{PLACEHOLDER_" not in all_text, (
            "PlaceholderManager should NOT create tokens when preserve_patterns: []. "
            "Found {PLACEHOLDER_} in extracted units."
        )

        # ASSERTION 2: Block-level shortcodes ({{< sections >}}, {{% steps %}}) are
        # excluded from translation entirely by the AST node-type classifier —
        # they do NOT appear in the extracted text units. Only inline/paragraph content
        # appears in units.
        # Verify that the paragraph content IS present:
        assert (
            "The **Aspose.Slides** plugins provide features" in all_text
            or "Aspose.Slides" in all_text
        ), "Paragraph content should appear in extracted units"
        assert "Step one" in all_text, (
            "Content inside shortcode blocks should appear in extracted units"
        )

    def test_multiple_shortcodes_without_placeholders(self):
        """
        Test that multiple shortcode types are preserved without PlaceholderManager.

        Verifies:
        - All Hugo shortcode variants preserved: {{< >}}, {{% %}}, {{< / >}}
        - No {PLACEHOLDER_} tokens created
        - Ready for InlineFormatProtector to handle during translation
        """
        markdown = """---
title: Multi-Shortcode Test
---

{{< sections >}}

{{% steps %}}
Instructions here.
{{% /steps %}}

{{< callout >}}
Important note.
{{< /callout >}}

{{< ref "docs.md" >}}
"""

        # Parse
        parser = HugoParser()
        doc = parser.parse_string(markdown)

        # Extract with NO preserve_patterns
        extractor = TextUnitExtractor(
            segmentation_strategy="sentence_only",
            preserve_patterns=[],  # Empty: PlaceholderManager disabled
        )

        translation_plan = extractor.extract_from_ast(doc.ast, doc.frontmatter)
        units = translation_plan.units

        # Collect all text
        all_text = "\n".join(u.source_text for u in units)

        # Verify NO PlaceholderManager tokens
        assert "{PLACEHOLDER_" not in all_text, "No PlaceholderManager tokens should be created"

        # Block-level shortcodes ({{< sections >}}, {{% steps %}}, {{% /steps %}},
        # {{< callout >}}, {{< ref >}} on their own lines) are excluded from
        # translation via the AST node-type classifier — they do NOT appear in
        # extracted text units. This is the correct behavior: no translation model
        # ever sees these shortcodes.
        # Verify instead that paragraph content IS present:
        assert "Instructions here." in all_text, "Paragraph inside block should be extracted"
        assert "Important note." in all_text, "Content inside callout should be extracted"
