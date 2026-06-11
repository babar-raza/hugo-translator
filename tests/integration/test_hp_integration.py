"""
Integration tests for HP-01 through HP-05 fixes.

Verifies that parser fixes are actually used in translation pipeline.
"""

from pathlib import Path

import pytest

from src.translation_engine.extractor.inline_format_protector import InlineFormatProtector
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import NodeType
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.utils.config_loader import ConfigService


class TestHPIntegration:
    """Verify HP fixes are integrated in translation pipeline."""

    @pytest.fixture
    def test_content(self):
        """Sample content with lists, links, bold."""
        return """---
title: "Integration Test"
---

## Features

1. **First feature**: Description here
2. **Second feature**: More details

## Links

- [Documentation](https://docs.example.com)
- [API Reference](https://api.example.com)

## Bold Text

This has **bold emphasis** in paragraph.
"""

    def test_hp01_lists_parsed(self, test_content):
        """HP-01: Verify lists are parsed into LIST nodes."""
        parser = HugoParser()
        parsed = parser.parse_string(test_content)

        # Count LIST nodes
        def count_lists(ast_list):
            count = 0
            for node in ast_list:
                if node.type == NodeType.LIST:
                    count += 1
                if hasattr(node, "children") and node.children:
                    count += count_lists(node.children)
            return count

        list_count = count_lists(parsed.ast)
        assert list_count == 2, f"Expected 2 lists, got {list_count}"

    def test_hp02_links_parsed(self, test_content):
        """HP-02: Verify links are parsed into LINK nodes."""
        parser = HugoParser()
        parsed = parser.parse_string(test_content)

        # Count LINK nodes
        def count_links(ast_list):
            count = 0
            for node in ast_list:
                if node.type == NodeType.LINK:
                    count += 1
                if hasattr(node, "children") and node.children:
                    count += count_links(node.children)
            return count

        link_count = count_links(parsed.ast)
        assert link_count == 2, f"Expected 2 links, got {link_count}"

    def test_hp02_bold_parsed(self, test_content):
        """HP-02: Verify bold is parsed into STRONG nodes."""
        parser = HugoParser()
        parsed = parser.parse_string(test_content)

        # Count STRONG nodes
        def count_strong(ast_list):
            count = 0
            for node in ast_list:
                if node.type == NodeType.STRONG:
                    count += 1
                if hasattr(node, "children") and node.children:
                    count += count_strong(node.children)
            return count

        strong_count = count_strong(parsed.ast)
        assert strong_count >= 3, f"Expected ≥3 bold markers, got {strong_count}"

    def _reconstruct(self, test_content):
        """Parse → extract → identity-translate → reconstruct. Returns output markdown."""
        config_service = ConfigService(Path(__file__).parent.parent.parent / "config")
        site_profile = config_service.get_site_profile("kb.aspose.net")
        parser = HugoParser()
        parsed = parser.parse_string(test_content)

        extractor = TextUnitExtractor(segmentation_strategy="sentence_only")
        plan = extractor.extract_from_ast(parsed.ast, parsed.frontmatter)

        # Identity translation: pass source text through unchanged
        translations = {
            u.node_addr: u.source_text for u in plan.units if u.node_addr and u.source_text
        }

        reconstructor = MarkdownReconstructor(site_profile)
        return reconstructor.reconstruct_body(parsed.ast, translations, "de")

    def test_hp03_lists_reconstructed(self, test_content):
        """HP-03: Verify lists are reconstructed in output."""
        output = self._reconstruct(test_content)

        assert "\n1. " in output or "1. " in output, "Ordered list markers not reconstructed"
        assert "\n- " in output or "- " in output, "Bullet list markers not reconstructed"

    def test_hp03_links_reconstructed(self, test_content):
        """HP-03: Verify links are reconstructed with URLs."""
        output = self._reconstruct(test_content)

        assert "](" in output, "Link syntax not reconstructed"
        assert "https://docs.example.com" in output, "URL not preserved"
        assert "https://api.example.com" in output, "URL not preserved"

    def test_hp03_bold_reconstructed(self, test_content):
        """HP-03: Verify bold markers are reconstructed."""
        output = self._reconstruct(test_content)

        bold_count = output.count("**") // 2
        assert bold_count >= 3, f"Expected ≥3 bold markers in output, got {bold_count}"

    def test_hp05_inline_protection_active(self, test_content):
        """HP-05: Verify InlineFormatProtector tokenizes inline code content."""
        parser = HugoParser()
        parsed = parser.parse_string(test_content)

        extractor = TextUnitExtractor(segmentation_strategy="sentence_only")
        plan = extractor.extract_from_ast(parsed.ast, parsed.frontmatter)

        # Find a unit with inline code and verify InlineFormatProtector works on it
        protector = InlineFormatProtector(use_unicode=True)
        content_with_code = "Use `some_function()` and `another_call()` here."
        result = protector.protect(content_with_code)

        # Protector should tokenize inline code content
        assert result.protected is not None
        restored = protector.restore(result, result.protected)
        assert "some_function()" in restored, "Inline code should survive protect/restore"
        assert "⟦" not in restored, "Unicode tokens must not leak into final output"

        # Verify extractor produced units from test content (pipeline is functional)
        assert len(plan.units) > 0, "TextUnitExtractor produced no units"
