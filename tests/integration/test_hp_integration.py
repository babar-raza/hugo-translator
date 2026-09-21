"""
Integration tests for HP-01 through HP-05 fixes.

Verifies that parser fixes are actually used in translation pipeline.
"""

from pathlib import Path
from collections import Counter
import re

import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import NodeType
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.translation_engine.validation import StructureValidator
from src.translation_engine.validation.repetition_detector_validator import (
    RepetitionDetectorValidator,
)
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

class TestCampaignHealingFixtureTopology:
    """Pin the real-shaped docs failures to immutable, offline fixtures."""

    _TOPOLOGY_KINDS = frozenset(
        {
            NodeType.HEADING,
            NodeType.LIST,
            NodeType.LIST_ITEM,
            NodeType.LINK,
            NodeType.CODE_BLOCK,
            NodeType.TABLE,
            NodeType.TABLE_ROW,
            NodeType.TABLE_CELL,
        }
    )

    @staticmethod
    def _topology(ast):
        counts = Counter()

        def walk(nodes):
            for node in nodes:
                if node.type in TestCampaignHealingFixtureTopology._TOPOLOGY_KINDS:
                    counts[node.type.value] += 1
                walk(getattr(node, "children", []) or [])

        walk(ast)
        return counts

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "format-support.md",
            "materials-shading.md",
            "deformers.md",
            "gltf.md",
            "profiles.md",
            "render.md",
            "scene-management.md",
        ],
    )
    def test_identity_ast_roundtrip_preserves_campaign_fixture_topology(self, fixture_name):
        """Real parser/extractor/reconstructor keeps structural nodes intact.

        This deliberately uses identity translations.  It proves the topology
        boundary itself and leaves model-generated bad candidates to the
        structural validators rather than weakening them.
        """
        repo = Path(__file__).resolve().parents[2]
        parser = HugoParser()
        profile = ConfigService(repo / "config").get_site_profile("docs.aspose.org")
        source_path = repo / "tests" / "fixtures" / "campaign_healing" / fixture_name
        source = parser.parse_file(source_path)
        plan = TextUnitExtractor(
            segmentation_strategy="sentence_only", site_profile=profile, target_lang="de"
        ).extract_from_ast(source.ast, source.frontmatter)
        translations = {
            unit.node_addr: unit.source_text
            for unit in plan.units
            if unit.node_addr and unit.source_text
        }

        reconstructor = MarkdownReconstructor(profile)
        source_body = reconstructor.reconstruct_body(source.ast, {}, "en")
        rendered = reconstructor.reconstruct_body(source.ast, translations, "de")
        target = parser.parse_string(rendered)

        assert self._topology(target.ast) == self._topology(source.ast)
        assert len(re.findall(r"\{\{[<%].*?[>%]\}\}", rendered)) == len(
            re.findall(r"\{\{[<%].*?[>%]\}\}", source_path.read_text(encoding="utf-8"))
        )

        # The AST snapshot is the authoritative topology proof.  Keep the
        # text-level structural validator in the same offline path as a
        # second, independently implemented guard against renderer drift.
        structure_result = StructureValidator().validate(
            source_body, rendered
        )
        assert structure_result.success
        assert structure_result.issues == []

    def test_structural_and_repetition_regressions_remain_detectable(self):
        """Broken candidates remain blocking inputs to a zero-defect run.

        These are deliberately representative Markdown rather than a mock
        parser result: a duplicate link, three dropped list nodes, a dropped
        heading, and a removed code span all flow through the production
        structure validator.  Repetition is tested separately because it is
        an independent page-level gate that must not be hidden by topology
        preservation.
        """
        source = """## Overview

- First item
- Second item
- Third item
- Fourth item

See [the reference](https://example.invalid/reference) and use `method()`.
"""
        malformed = """See [the reference](https://example.invalid/reference)
and [the reference](https://example.invalid/reference).
"""

        structure_result = StructureValidator().validate(source, malformed)
        messages = "\n".join(issue.message for issue in structure_result.issues).lower()
        assert not structure_result.success  # dropped inline code is an ERROR
        assert "heading count mismatch" in messages
        assert "list item count mismatch" in messages
        assert "link/image count mismatch" in messages
        assert "code block count mismatch" in messages

        repetition_result = RepetitionDetectorValidator().validate(
            source,
            "boucle de traduction boucle de traduction boucle de traduction "
            "boucle de traduction boucle de traduction boucle de traduction",
            context={"target_lang": "fr"},
        )
        assert not repetition_result.success
        assert any("gram" in issue.message for issue in repetition_result.issues)
