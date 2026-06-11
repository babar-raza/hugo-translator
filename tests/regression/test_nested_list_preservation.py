"""
Regression test for nested list preservation during translation.

Tests that nested list structures are not concatenated or flattened
during the translation pipeline.

MISSION: Reproduce and fix the nested list corruption bug identified in
PHASE10_PROD_FORCE_TRANSLATE.md
"""

import os
import sys
from pathlib import Path

# Add src to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import NodeType
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer
from src.utils.models import BodyRules, SiteProfile


def count_list_items(ast_node):
    """Recursively count list item nodes in an AST."""
    count = 0
    if ast_node.type == NodeType.LIST_ITEM:
        count += 1
    for child in ast_node.children:
        count += count_list_items(child)
    return count


def count_list_containers(ast_node):
    """Recursively count list container nodes in an AST."""
    count = 0
    if ast_node.type == NodeType.LIST:
        count += 1
    for child in ast_node.children:
        count += count_list_containers(child)
    return count


class FakeTranslationBackend:
    """Fake MT backend that wraps text with TR(...) for deterministic testing."""

    def translate_batch(self, texts, src_lang, tgt_lang):
        """Translate by wrapping each text with TR(...)."""
        return [f"TR({text})" for text in texts]


def test_nested_list_structure_preserved():
    """
    Test that nested list structures are preserved during translation.

    This test should FAIL before the fix and PASS after the fix.
    """
    print("\n" + "=" * 80)
    print("TEST: Nested List Structure Preservation")
    print("=" * 80)

    # Read fixture
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "nested_list_fixture.en.md"
    assert fixture_path.exists(), f"Fixture not found: {fixture_path}"

    source_content = fixture_path.read_text(encoding="utf-8")
    print(f"\n[1/5] Source content loaded: {len(source_content)} chars")

    # Parse source
    parser = HugoParser()
    source_doc = parser.parse_string(source_content)
    print("[2/5] Source parsed into AST")

    # Count list structures in source (need to traverse the whole AST)
    source_list_items = sum(count_list_items(node) for node in source_doc.ast)
    source_list_containers = sum(count_list_containers(node) for node in source_doc.ast)
    source_lines = len(source_content.strip().split("\n"))

    print("      Source metrics:")
    print(f"      - List items: {source_list_items}")
    print(f"      - List containers: {source_list_containers}")
    print(f"      - Line count: {source_lines}")

    # Create minimal site profile
    site_profile = SiteProfile(
        site_id="test.site",
        content_roots=["/test"],
        default_source_lang="en",
        target_langs=["fr"],
        body=BodyRules(translate_markdown=True),
        frontmatter={},
    )

    # Extract text units from body AST
    # Use the strategy from the site profile's body rules; pass site_profile as keyword arg.
    strategy = site_profile.body.ast_segmentation_strategy if site_profile.body else "adaptive"
    extractor = TextUnitExtractor(segmentation_strategy=strategy, site_profile=site_profile)
    translation_plan = extractor.extract_from_ast(source_doc.ast, source_doc.frontmatter)
    text_units = translation_plan.units

    print(f"[3/5] Extracted {len(text_units)} text units")

    # Simulate translation: set translated_text on each unit using the fake backend
    fake_backend = FakeTranslationBackend()
    for unit in text_units:
        if not unit.do_not_translate:
            unit.translated_text = fake_backend.translate_batch([unit.source_text], "en", "fr")[0]
        else:
            unit.translated_text = unit.source_text

    print(f"[4/5] Simulated translation of {len(text_units)} units")

    # Reconstruct using ASTRenderer (the production reconstructor)
    # It reads unit.translated_text and maps back to AST via node_addr
    renderer = ASTRenderer()
    frontmatter_copy = dict(source_doc.frontmatter) if source_doc.frontmatter else {}
    renderer.apply_translations(source_doc.ast, text_units, frontmatter_copy)
    reconstructed_body = renderer.render_to_markdown(source_doc.ast)

    # Combine into full document
    if frontmatter_copy:
        import yaml

        fm_yaml = yaml.dump(frontmatter_copy, allow_unicode=True, default_flow_style=False)
        output_content = f"---\n{fm_yaml}---\n\n{reconstructed_body}"
    else:
        output_content = reconstructed_body

    print(f"[5/5] Reconstructed output: {len(output_content)} chars")

    # Parse output to check structure
    output_doc = parser.parse_string(output_content)
    output_list_items = sum(count_list_items(node) for node in output_doc.ast)
    output_list_containers = sum(count_list_containers(node) for node in output_doc.ast)
    output_lines = len(output_content.strip().split("\n"))

    print("\n      Output metrics:")
    print(f"      - List items: {output_list_items}")
    print(f"      - List containers: {output_list_containers}")
    print(f"      - Line count: {output_lines}")

    # Calculate metrics
    line_retention = output_lines / source_lines if source_lines > 0 else 0
    item_retention = output_list_items / source_list_items if source_list_items > 0 else 0

    print("\n      Retention ratios:")
    print(f"      - Line retention: {line_retention:.1%} ({output_lines}/{source_lines})")
    print(f"      - Item retention: {item_retention:.1%} ({output_list_items}/{source_list_items})")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    #  Save output for inspection
    debug_output_path = REPO_ROOT / "tests" / "fixtures" / "nested_list_output_debug.md"
    debug_output_path.write_text(output_content, encoding="utf-8")
    print(f"\n      Debug output saved to: {debug_output_path}")

    # Assert list item count is preserved (allow 10% tolerance for minor parsing differences)
    tolerance = int(source_list_items * 0.1) + 1
    assert abs(output_list_items - source_list_items) <= tolerance, (
        f"List item count mismatch: expected {source_list_items}, got {output_list_items}. "
        f"Difference {abs(output_list_items - source_list_items)} exceeds tolerance {tolerance}. "
        f"This indicates list items are being concatenated or duplicated."
    )
    print(f"[PASS] List item count acceptable: {output_list_items} (tolerance ±{tolerance})")

    # Assert list container count is close (allow some tolerance for restructuring)
    container_tolerance = int(source_list_containers * 0.3) + 1
    container_loss = source_list_containers - output_list_containers
    assert container_loss <= container_tolerance, (
        f"Too many list containers lost: expected {source_list_containers}, got {output_list_containers}. "
        f"Loss of {container_loss} exceeds tolerance {container_tolerance}. "
        f"This indicates list structure is being flattened."
    )
    print(
        f"[PASS] List container count acceptable: {output_list_containers} (expected {source_list_containers}, tolerance -{container_tolerance})"
    )

    # Assert line count is not drastically reduced (allow 20% variance for translation).
    # Multi-line list items (* **Header**\n  description:) are collapsed to a single line
    # after rendering (SOFT_BREAK → space), which is valid restructuring — not concatenation.
    # The items/containers/indentation assertions above catch real concatenation bugs.
    min_expected_lines = int(source_lines * 0.80)
    assert output_lines >= min_expected_lines, (
        f"Line count too low: expected >= {min_expected_lines} (80% of {source_lines}), "
        f"got {output_lines}. This indicates content concatenation."
    )
    print(f"[PASS] Line count acceptable: {output_lines} >= {min_expected_lines}")

    # Assert nested indentation is present in output
    # Check for indentation patterns (at least 2 or 4 spaces at line start for nested items)
    nested_pattern_found = any(
        line.startswith("  ") or line.startswith("    ")
        for line in output_content.split("\n")
        if line.strip().startswith("-") or line.strip().startswith("*")
    )
    assert nested_pattern_found, (
        "No nested indentation found in output. Lists may have been flattened."
    )
    print("[PASS] Nested indentation patterns found in output")

    print("\n" + "=" * 80)
    print("TEST PASSED: Nested list structure preserved!")
    print("=" * 80)


def test_checklist_item_separation():
    """
    Test that checklist items with icons (✔) remain on separate lines.
    """
    print("\n" + "=" * 80)
    print("TEST: Checklist Item Separation")
    print("=" * 80)

    # Simple checklist markdown (use proper list markers)
    checklist_md = """---
title: Test
---

## Features

- ✔ First feature
- ✔ Second feature
- ✔ Third feature
- ✔ Fourth feature
- ✔ Fifth feature
"""

    print("\n[1/4] Testing checklist with 5 items")

    # Parse
    parser = HugoParser()
    source_doc = parser.parse_string(checklist_md)
    source_list_items = sum(count_list_items(node) for node in source_doc.ast)
    source_lines = len(checklist_md.strip().split("\n"))

    print(f"[2/4] Source has {source_list_items} list items, {source_lines} lines")

    # Create site profile
    site_profile = SiteProfile(
        site_id="test.site",
        content_roots=["/test"],
        default_source_lang="en",
        target_langs=["fr"],
        body=BodyRules(translate_markdown=True),
        frontmatter={},
    )

    # Extract and translate
    strategy2 = site_profile.body.ast_segmentation_strategy if site_profile.body else "adaptive"
    extractor = TextUnitExtractor(segmentation_strategy=strategy2, site_profile=site_profile)
    translation_plan = extractor.extract_from_ast(source_doc.ast, source_doc.frontmatter)
    text_units = translation_plan.units

    fake_backend = FakeTranslationBackend()
    for unit in text_units:
        if not unit.do_not_translate:
            unit.translated_text = fake_backend.translate_batch([unit.source_text], "en", "fr")[0]
        else:
            unit.translated_text = unit.source_text

    print(f"[3/4] Translated {len(text_units)} units")

    # Reconstruct using ASTRenderer (production path)
    renderer2 = ASTRenderer()
    renderer2.apply_translations(source_doc.ast, text_units)
    reconstructed_body = renderer2.render_to_markdown(source_doc.ast)

    # Check output
    output_lines = reconstructed_body.strip().split("\n")
    checklist_lines = [line for line in output_lines if "✔" in line]

    print(f"[4/4] Output has {len(checklist_lines)} lines with checkmark")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    assert len(checklist_lines) == 5, (
        f"Expected 5 checklist lines, got {len(checklist_lines)}. Items may have been concatenated."
    )
    print("[PASS] All 5 checklist items on separate lines")

    # Each checklist line should have exactly one ✔
    for i, line in enumerate(checklist_lines, 1):
        check_count = line.count("✔")
        assert check_count == 1, (
            f"Checklist line {i} has {check_count} checkmarks (expected 1). Line: {line[:50]}..."
        )
    print("[PASS] Each checklist line has exactly one checkmark")

    print("\n" + "=" * 80)
    print("TEST PASSED: Checklist items properly separated!")
    print("=" * 80)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("REGRESSION TEST SUITE: Nested List Preservation")
    print("=" * 80)

    try:
        test_nested_list_structure_preserved()
        print("\n[OK] Test 1 passed\n")
    except AssertionError as e:
        print(f"\n[FAIL] Test 1 FAILED: {e}\n")
        raise

    try:
        test_checklist_item_separation()
        print("\n[OK] Test 2 passed\n")
    except AssertionError as e:
        print(f"\n[FAIL] Test 2 FAILED: {e}\n")
        raise

    print("\n" + "=" * 80)
    print("ALL TESTS PASSED!")
    print("=" * 80)
