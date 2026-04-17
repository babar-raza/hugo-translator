"""
E2E Integration Test for SHORTCODE-007: Single Protection System

Verifies that Hugo shortcodes are preserved using only InlineFormatProtector
(PlaceholderManager disabled for shortcodes).

Author: SHORTCODE-007-P3
Date: 2026-01-20
"""


from src.translation_engine.extractor.inline_format_protector import InlineFormatProtector
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.hugo_parser import HugoParser


class TestShortcodeSingleProtection:
    """
    Test suite verifying single protection system for Hugo shortcodes.

    SHORTCODE-007 eliminates double-protection architecture by:
    1. Disabling PlaceholderManager for shortcodes (preserve_patterns: [])
    2. Using only InlineFormatProtector throughout pipeline
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
            preserve_patterns=[]  # CRITICAL: Empty array (no PlaceholderManager protection)
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

        # CRITICAL ASSERTION 2: Original shortcodes preserved
        assert "{{< sections >}}" in all_text, (
            "Original {{< sections >}} should be preserved when PlaceholderManager disabled"
        )
        assert "{{< callout >}}" in all_text, (
            "Original {{< callout >}} should be preserved when PlaceholderManager disabled"
        )
        assert "{{% steps %}}" in all_text, (
            "Original {{% steps %}} should be preserved when PlaceholderManager disabled"
        )

    def test_inline_format_protector_handles_shortcodes(self):
        """
        Verify InlineFormatProtector protects original shortcode syntax.

        This test confirms the single protection system works correctly.

        Expected:
        - InlineFormatProtector.protect() recognizes {{< shortcodes >}}
        - Protection creates tokens like ⟦SHORTCODE0001⟧
        - Restoration correctly recovers original shortcodes
        """
        # Sample text with shortcodes and formatting
        text = "{{< sections >}}\n\nThe **Aspose.Slides** plugins for {{< callout >}}presentations{{< /callout >}}."

        # Create protector
        protector = InlineFormatProtector(use_unicode=True)

        # STEP 1: Protect
        result = protector.protect(text)

        # ASSERTION 1: Original shortcodes NOT in protected text
        assert "{{< sections >}}" not in result.protected, (
            "Shortcode should be replaced with token in protected text. "
            f"Protected: {result.protected}"
        )

        assert "{{< callout >}}" not in result.protected, (
            "Shortcode should be replaced with token in protected text. "
            f"Protected: {result.protected}"
        )

        # ASSERTION 2: Token format present (either SHORTCODE or Unicode ⟦)
        has_token = "SHORTCODE" in result.protected or "⟦" in result.protected
        assert has_token, (
            "Expected shortcode protection tokens in protected text. "
            f"Protected: {result.protected}"
        )

        # ASSERTION 3: Bold also protected
        assert "**Aspose.Slides**" not in result.protected, (
            "Bold should also be protected. "
            f"Protected: {result.protected}"
        )

        # STEP 2: Simulate translation (preserve tokens)
        translated = result.protected.replace("The", "Os").replace(
            "plugins for", "plugins para"
        )

        # STEP 3: Restore
        restored = protector.restore(result, translated)

        # ASSERTION 4: Original shortcodes restored
        assert "{{< sections >}}" in restored, (
            f"Shortcode should be restored. Restored text: {restored}"
        )

        assert "{{< callout >}}" in restored, (
            f"Shortcode should be restored. Restored text: {restored}"
        )

        assert "{{< /callout >}}" in restored, (
            f"Closing shortcode should be restored. Restored text: {restored}"
        )

        # ASSERTION 5: Translation preserved
        assert "Os" in restored, (
            f"Translation should be preserved. Restored text: {restored}"
        )

        # ASSERTION 6: Bold content restored
        assert "Aspose.Slides" in restored, (
            f"Bold content should be restored. Restored text: {restored}"
        )

        # ASSERTION 7: No token leakage
        assert "⟦" not in restored, (
            f"Unicode tokens should not leak into output. Restored text: {restored}"
        )

        assert "SHORTCODE" not in restored, (
            f"SHORTCODE tokens should not leak into output. Restored text: {restored}"
        )

        assert "BOLD" not in restored, (
            f"BOLD tokens should not leak into output. Restored text: {restored}"
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
            preserve_patterns=[]  # Empty: PlaceholderManager disabled
        )

        translation_plan = extractor.extract_from_ast(doc.ast, doc.frontmatter)
        units = translation_plan.units

        # Collect all text
        all_text = "\n".join(u.source_text for u in units)

        # Verify NO PlaceholderManager tokens
        assert "{PLACEHOLDER_" not in all_text, (
            "No PlaceholderManager tokens should be created"
        )

        # Verify all shortcodes preserved
        assert "{{< sections >}}" in all_text, "{{< sections >}} preserved"
        assert "{{% steps %}}" in all_text, "{{% steps %}} preserved"
        assert "{{< callout >}}" in all_text, "{{< callout >}} preserved"
        assert "{{< ref" in all_text, "{{< ref >}} preserved"
