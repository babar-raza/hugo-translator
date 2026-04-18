import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor


@pytest.fixture
def extractor():
    return TextUnitExtractor(
        segmentation_strategy="sentence_only",
        terminology_file=None
    )


class TestShortcodeProtection:
    """Test Hugo shortcode detection in _is_non_translatable()."""

    @pytest.mark.parametrize("shortcode,expected", [
        # Opening shortcodes with %
        ("{{% steps %}}", True),
        ("{{% alert %}}", True),
        ("{{% note type=\"warning\" %}}", True),

        # Closing shortcodes
        ("{{% /steps %}}", True),
        ("{{% /alert %}}", True),

        # Self-closing shortcodes with <
        ("{{< ref \"path/to/file\" >}}", True),
        ("{{< figure src=\"image.png\" >}}", True),
        ("{{< relref \"guide.md\" >}}", True),

        # Non-shortcodes that should NOT match
        ("regular text", False),
        ("{{variable}}", False),  # Template variable (one brace pair)
        ("{{ .Title }}", False),   # Go template
        ("code {{var}} here", False),
        ("{{% incomplete", False),  # Malformed
        ("steps %}}", False),       # Missing opening

        # Edge cases
        ("", False),  # Empty string
        ("   ", False),  # Whitespace only
        ("{{% %}}", True),  # Empty shortcode (valid Hugo syntax)
        ("{{< >}}", True),  # Empty self-closing
    ])
    def test_hugo_shortcode_detection(self, extractor, shortcode, expected):
        """Verify Hugo shortcodes are correctly identified as non-translatable."""
        result = extractor._is_non_translatable(shortcode)
        assert result == expected, f"Failed for: {shortcode}"

    def test_shortcode_with_unicode(self, extractor):
        """Test shortcodes containing unicode characters."""
        # Hugo shortcodes can have unicode in arguments
        assert extractor._is_non_translatable("{{% note title=\"测试\" %}}") == True

    def test_shortcode_case_sensitivity(self, extractor):
        """Verify shortcode detection is case-sensitive for content."""
        # Hugo shortcodes are case-sensitive
        assert extractor._is_non_translatable("{{% Steps %}}") == True
        assert extractor._is_non_translatable("{{% STEPS %}}") == True

    def test_nested_braces_not_shortcode(self, extractor):
        """Ensure nested braces don't trigger false positives."""
        assert extractor._is_non_translatable("{{foo {{bar}}}}") == False

    def test_shortcode_with_newlines(self, extractor):
        """Test that shortcodes with internal newlines are not matched."""
        # Our regex requires shortcode on single line
        multiline = """{{% steps
        param="value"
        %}}"""
        assert extractor._is_non_translatable(multiline) == False

    def test_integration_with_full_unit_extraction(self, extractor):
        """Integration test: shortcode text must not appear in any translatable unit."""
        from src.translation_engine.parser.hugo_parser import HugoParser
        from src.translation_engine.parser.ast_nodes import NodeType

        markdown = """---
title: Test
---

{{% steps %}}

Content here.

{{% /steps %}}
"""
        parser = HugoParser()
        doc = parser.parse_string(markdown)
        units = []

        # Traverse AST to extract units
        for node in doc.ast:
            extractor._traverse_node(node, units)

        # Shortcode paragraphs are parsed as INLINE_HTML nodes in the AST.
        # They do NOT produce TextUnits (renderer preserves them via node.raw directly).
        # Verify no translatable unit contains raw shortcode syntax.
        for unit in units:
            if not unit.do_not_translate:
                assert "{{% steps" not in unit.source_text, \
                    f"Shortcode leaked into translatable unit: {unit.source_text}"
                assert "{{% /steps" not in unit.source_text, \
                    f"Shortcode leaked into translatable unit: {unit.source_text}"

        # Verify the plain content was extracted
        content_units = [u for u in units if "Content here" in u.source_text]
        assert len(content_units) >= 1, "Plain content should be extracted as a unit"
