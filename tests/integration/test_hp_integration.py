"""
Integration tests for HP-01 through HP-05 fixes.

Verifies that parser fixes are actually used in translation pipeline.
"""

import pytest
from pathlib import Path

from src.translation_engine.engine import TranslationEngine
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.parser.ast_nodes import NodeType
from src.utils.config_loader import ConfigService
from pathlib import Path


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
                if hasattr(node, 'children') and node.children:
                    count += count_lists(node.children)
            return count

        list_count = count_lists(parsed.body_ast)
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
                if hasattr(node, 'children') and node.children:
                    count += count_links(node.children)
            return count

        link_count = count_links(parsed.body_ast)
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
                if hasattr(node, 'children') and node.children:
                    count += count_strong(node.children)
            return count

        strong_count = count_strong(parsed.body_ast)
        assert strong_count >= 3, f"Expected ≥3 bold markers, got {strong_count}"

    def test_hp03_lists_reconstructed(self, test_content, tmp_path):
        """HP-03: Verify lists are reconstructed in output."""
        config_service = ConfigService(Path(__file__).parent.parent.parent / "config")
        config = config_service.get_site_profile('kb.aspose.net')
        engine = TranslationEngine(config)
        parser = HugoParser()

        parsed = parser.parse_string(test_content)
        translated = engine.translate_document(
            parsed=parsed,
            source_lang='en',
            target_lang='de'
        )

        # Check for list markers in output
        assert '\n1. ' in translated or '\n2. ' in translated, \
            "Ordered list markers not reconstructed"
        assert '\n- ' in translated, \
            "Bullet list markers not reconstructed"

    def test_hp03_links_reconstructed(self, test_content):
        """HP-03: Verify links are reconstructed with URLs."""
        config_service = ConfigService(Path(__file__).parent.parent.parent / "config")
        config = config_service.get_site_profile('kb.aspose.net')
        engine = TranslationEngine(config)
        parser = HugoParser()

        parsed = parser.parse_string(test_content)
        translated = engine.translate_document(
            parsed=parsed,
            source_lang='en',
            target_lang='de'
        )

        # Check for link syntax in output
        assert '](' in translated, "Link syntax not reconstructed"
        assert 'https://docs.example.com' in translated, "URL not preserved"
        assert 'https://api.example.com' in translated, "URL not preserved"

    def test_hp03_bold_reconstructed(self, test_content):
        """HP-03: Verify bold markers are reconstructed."""
        config_service = ConfigService(Path(__file__).parent.parent.parent / "config")
        config = config_service.get_site_profile('kb.aspose.net')
        engine = TranslationEngine(config)
        parser = HugoParser()

        parsed = parser.parse_string(test_content)
        translated = engine.translate_document(
            parsed=parsed,
            source_lang='en',
            target_lang='de'
        )

        # Check for bold markers in output
        bold_count = translated.count('**') // 2
        assert bold_count >= 3, \
            f"Expected ≥3 bold markers in output, got {bold_count}"

    def test_hp05_inline_protection_active(self, test_content):
        """HP-05: Verify inline format protection is applied."""
        config_service = ConfigService(Path(__file__).parent.parent.parent / "config")
        config = config_service.get_site_profile('kb.aspose.net')
        parser = HugoParser()
        parsed = parser.parse_string(test_content)

        from src.translation_engine.extractor.segment_extractor import SegmentExtractor
        extractor = SegmentExtractor(config)
        segments = extractor.extract_all(parsed)

        # Check if inline protection was applied
        protected_segments = [
            seg for seg in segments
            if hasattr(seg, 'inline_format_data') and seg.inline_format_data
        ]

        assert len(protected_segments) > 0, \
            "Inline format protection not applied to any segments"
