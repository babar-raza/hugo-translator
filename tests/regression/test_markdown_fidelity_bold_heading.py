"""
Regression test for markdown fidelity: bold/heading preservation.

Tests that bold-only paragraphs remain as bold paragraphs and don't get
converted to list items or italics during translation.

Example failure case:
    Source: **Plateformes soutenues**
    Target (wrong): * Des plateformes soutenues * (italic)
    Target (wrong): - Des plateformes soutenues (list item)
    Target (correct): **Plateformes soutenues** (bold preserved)
"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.translation_engine.parser.ast_nodes import NodeType
from src.translation_engine.parser.hugo_parser import HugoParser


@pytest.fixture
def parser():
    """Provide HugoParser instance."""
    return HugoParser()


@pytest.fixture
def bold_only_fixture():
    """Source fixture with bold-only paragraphs."""
    return """---
title: Test Document
---

# Supported Platforms

**Supported Platforms**

This is a paragraph with **bold text** inside.

**Another bold-only paragraph**

- List item 1
- List item 2

**Final bold paragraph**
"""


@pytest.fixture
def correct_translation():
    """Correct translation preserving bold structure."""
    return """---
title: Document de test
---

# Plateformes prises en charge

**Plateformes prises en charge**

Ceci est un paragraphe avec **texte en gras** à l'intérieur.

**Un autre paragraphe en gras uniquement**

- Élément de liste 1
- Élément de liste 2

**Paragraphe en gras final**
"""


@pytest.fixture
def corrupted_translation_list():
    """Corrupted translation: bold converted to list items."""
    return """---
title: Document de test
---

# Plateformes prises en charge

- Plateformes prises en charge

Ceci est un paragraphe avec **texte en gras** à l'intérieur.

- Un autre paragraphe en gras uniquement

- Élément de liste 1
- Élément de liste 2

- Paragraphe en gras final
"""


@pytest.fixture
def corrupted_translation_italic():
    """Corrupted translation: bold converted to italic."""
    return """---
title: Document de test
---

# Plateformes prises en charge

*Plateformes prises en charge*

Ceci est un paragraphe avec **texte en gras** à l'intérieur.

*Un autre paragraphe en gras uniquement*

- Élément de liste 1
- Élément de liste 2

*Paragraphe en gras final*
"""


def test_bold_count_preserved(parser, bold_only_fixture, correct_translation):
    """Test that bold count is preserved in correct translation."""
    source_doc = parser.parse_string(bold_only_fixture)
    target_doc = parser.parse_string(correct_translation)

    def count_bold(ast):
        count = 0
        def traverse(node):
            nonlocal count
            if node.type == NodeType.STRONG:
                count += 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return count

    source_bold = count_bold(source_doc.ast)
    target_bold = count_bold(target_doc.ast)

    assert source_bold == target_bold, \
        f"Bold count mismatch: source={source_bold}, target={target_bold}"
    assert source_bold >= 3, "Fixture should have at least 3 bold elements"


def test_bold_not_converted_to_list(parser, bold_only_fixture, corrupted_translation_list):
    """Test that bold-to-list corruption is detected."""
    source_doc = parser.parse_string(bold_only_fixture)
    target_doc = parser.parse_string(corrupted_translation_list)

    def count_bold(ast):
        count = 0
        def traverse(node):
            nonlocal count
            if node.type == NodeType.STRONG:
                count += 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return count

    def count_list_items(ast):
        count = 0
        def traverse(node):
            nonlocal count
            if node.type == NodeType.LIST_ITEM:
                count += 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return count

    source_bold = count_bold(source_doc.ast)
    target_bold = count_bold(target_doc.ast)
    source_list_items = count_list_items(source_doc.ast)
    target_list_items = count_list_items(target_doc.ast)

    # In corrupted translation, bold count drops and list items increase
    assert target_bold < source_bold, "Corrupted translation should have fewer bold elements"
    assert target_list_items > source_list_items, \
        "Corrupted translation should have more list items (bold converted)"


def test_bold_not_converted_to_italic(parser, bold_only_fixture, corrupted_translation_italic):
    """Test that bold-to-italic corruption is detected."""
    source_doc = parser.parse_string(bold_only_fixture)
    target_doc = parser.parse_string(corrupted_translation_italic)

    def count_bold(ast):
        count = 0
        def traverse(node):
            nonlocal count
            if node.type == NodeType.STRONG:
                count += 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return count

    def count_italic(ast):
        count = 0
        def traverse(node):
            nonlocal count
            if node.type == NodeType.EMPHASIS:
                count += 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return count

    source_bold = count_bold(source_doc.ast)
    target_bold = count_bold(target_doc.ast)
    source_italic = count_italic(source_doc.ast)
    target_italic = count_italic(target_doc.ast)

    # In corrupted translation, bold count drops and italic count increases
    assert target_bold < source_bold, "Corrupted translation should have fewer bold elements"
    assert target_italic > source_italic, \
        "Corrupted translation should have more italic elements (bold converted)"


def test_heading_levels_preserved(parser):
    """Test that heading levels are preserved."""
    source = """---
title: Test
---

# Level 1

## Level 2

### Level 3

## Another Level 2
"""

    target = """---
title: Test
---

# Niveau 1

## Niveau 2

### Niveau 3

## Un autre niveau 2
"""

    source_doc = parser.parse_string(source)
    target_doc = parser.parse_string(target)

    def count_headings(ast):
        headings = {}
        def traverse(node):
            if node.type == NodeType.HEADING:
                level = node.attrs.get('level', 1)
                headings[level] = headings.get(level, 0) + 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return headings

    source_headings = count_headings(source_doc.ast)
    target_headings = count_headings(target_doc.ast)

    assert source_headings == target_headings, \
        f"Heading level mismatch: source={source_headings}, target={target_headings}"


def test_verifier_integration(bold_only_fixture, correct_translation):
    """Test that the e2e_verify_single_file script detects fidelity issues."""
    from scripts.e2e_verify_single_file import verify_ast_structural_fidelity

    # Test correct translation (should pass)
    result = verify_ast_structural_fidelity(bold_only_fixture, correct_translation)
    assert result['passed'], f"Correct translation should pass. Errors: {result['errors']}"

    # Test corrupted translation with list items
    corrupted_list = bold_only_fixture.replace(
        "**Another bold-only paragraph**",
        "- Another bold-only paragraph"
    )
    result_list = verify_ast_structural_fidelity(bold_only_fixture, corrupted_list)
    assert not result_list['passed'], "Corrupted translation (list) should fail"
    assert any('bold' in str(err).lower() for err in result_list['errors']), \
        "Should report bold count mismatch"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
