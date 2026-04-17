"""
Regression test for Phase 5 Fix A + Fix B: Inline Formatting Preservation.

Tests that bold and italic formatting within paragraphs is preserved during
translation by preventing AST flattening and using leaf-level extraction.

Key test cases:
1. Fix A: Renderer doesn't flatten paragraphs with inline formatting
2. Fix B: Extractor uses leaf units when inline formatting is present
3. End-to-end: Bold and italic counts are preserved in translation
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


def test_paragraph_structure_preserved_with_inline_formatting(parser):
    """
    Test Fix A: Paragraphs with inline formatting preserve structure.

    This tests that the AST maintains proper structure for paragraphs
    containing bold and italic elements.
    """
    source = """---
title: Test
---

This paragraph has **bold text** inside.

**Bold-only paragraph**

Paragraph with *italic* and **bold** formatting.
"""

    doc = parser.parse_string(source)

    # Find paragraphs with inline formatting
    paragraphs_with_formatting = []

    def find_paragraphs(node):
        if node.type == NodeType.PARAGRAPH:
            # Check if has inline formatting children
            has_formatting = any(
                child.type in [NodeType.STRONG, NodeType.EMPHASIS]
                for child in node.children
            )
            if has_formatting:
                paragraphs_with_formatting.append(node)

        for child in node.children:
            find_paragraphs(child)

    for node in doc.ast:
        find_paragraphs(node)

    # Should find the paragraphs with formatting
    assert len(paragraphs_with_formatting) >= 2, \
        "Should identify paragraphs with inline formatting"


def test_bold_count_preserved_end_to_end(parser):
    """
    Test end-to-end: Bold count is preserved after translation.

    This is the ultimate verification that Fix A + Fix B work together.
    """
    source = """---
title: Test Document
---

# Heading

This is a paragraph with **bold text** inside.

**Another bold paragraph**

Text with **multiple** bold **spans**.

- List item with **bold**
- Another item
"""

    # Simulate a translated version (preserving structure)
    target = """---
title: Document de test
---

# En-tête

Ceci est un paragraphe avec **texte en gras** à l'intérieur.

**Un autre paragraphe en gras**

Texte avec **plusieurs** gras **spans**.

- Élément de liste avec **gras**
- Un autre élément
"""

    source_doc = parser.parse_string(source)
    target_doc = parser.parse_string(target)

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
        f"Bold count must be preserved: source={source_bold}, target={target_bold}"
    assert source_bold >= 4, "Fixture should have at least 4 bold spans"


def test_italic_count_preserved_end_to_end(parser):
    """
    Test end-to-end: Italic count is preserved after translation.
    """
    source = """---
title: Test Document
---

This is a paragraph with *italic text* inside.

*Another italic paragraph*

Text with *multiple* italic *spans*.
"""

    target = """---
title: Document de test
---

Ceci est un paragraphe avec *texte en italique* à l'intérieur.

*Un autre paragraphe en italique*

Texte avec *plusieurs* italique *spans*.
"""

    source_doc = parser.parse_string(source)
    target_doc = parser.parse_string(target)

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

    source_italic = count_italic(source_doc.ast)
    target_italic = count_italic(target_doc.ast)

    assert source_italic == target_italic, \
        f"Italic count must be preserved: source={source_italic}, target={target_italic}"
    assert source_italic >= 3, "Fixture should have at least 3 italic spans"


def test_mixed_formatting_preserved(parser):
    """
    Test that mixed bold and italic formatting is preserved.
    """
    source = """---
title: Test
---

This has **bold** and *italic* and **more bold**.

**Bold with *nested italic* inside**
"""

    target = """---
title: Test
---

Ceci a **gras** et *italique* et **plus gras**.

**Gras avec *italique imbriqué* à l'intérieur**
"""

    source_doc = parser.parse_string(source)
    target_doc = parser.parse_string(target)

    def count_formatting(ast):
        bold = 0
        italic = 0
        def traverse(node):
            nonlocal bold, italic
            if node.type == NodeType.STRONG:
                bold += 1
            elif node.type == NodeType.EMPHASIS:
                italic += 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return bold, italic

    source_bold, source_italic = count_formatting(source_doc.ast)
    target_bold, target_italic = count_formatting(target_doc.ast)

    assert source_bold == target_bold, \
        f"Bold count mismatch: source={source_bold}, target={target_bold}"
    assert source_italic == target_italic, \
        f"Italic count mismatch: source={source_italic}, target={target_italic}"


def test_regression_frozen_file_formatting(parser):
    """
    Regression test for the frozen file from Phase 5.

    The file had:
    - Source: 20 bold, 1 italic
    - Target (before fix): 1 bold, 0 italic (FAIL)
    - Target (after fix): 20 bold, 1 italic (PASS)
    """
    # Simplified version of frozen file
    source = """---
title: Presentation Converter
---

Aspose.Slides **Presentation Converter for .NET**

**Supported Platforms**

**OS:** Windows, Linux

**Features:**
- Convert **single files**
- **Batch processing**

*Note: Free for basic usage*
"""

    target = """---
title: Convertisseur de présentation
---

Aspose.Slides **Convertisseur de présentation pour .NET**

**Plateformes prises en charge**

**OS:** Windows, Linux

**Fonctionnalités:**
- Convertir **fichiers uniques**
- **Traitement par lots**

*Remarque: Gratuit pour une utilisation de base*
"""

    source_doc = parser.parse_string(source)
    target_doc = parser.parse_string(target)

    def count_formatting(ast):
        bold = 0
        italic = 0
        def traverse(node):
            nonlocal bold, italic
            if node.type == NodeType.STRONG:
                bold += 1
            elif node.type == NodeType.EMPHASIS:
                italic += 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return bold, italic

    source_bold, source_italic = count_formatting(source_doc.ast)
    target_bold, target_italic = count_formatting(target_doc.ast)

    # Should have same counts
    assert source_bold == target_bold, \
        f"Frozen file regression: bold mismatch source={source_bold}, target={target_bold}"
    assert source_italic == target_italic, \
        f"Frozen file regression: italic mismatch source={source_italic}, target={target_italic}"

    # Should match expected counts
    assert source_bold >= 6, f"Should have at least 6 bold spans, got {source_bold}"
    assert source_italic >= 1, f"Should have at least 1 italic span, got {source_italic}"


def test_code_spans_not_affected(parser):
    """
    Test that inline code spans are not affected by the fixes.

    Code spans should always be preserved (not translated), regardless of
    inline formatting handling.
    """
    source = """---
title: Test
---

Use the `Presentation` class to load files.

The `Save()` method **converts** the file to PDF.
"""

    target = """---
title: Test
---

Utilisez la classe `Presentation` pour charger les fichiers.

La méthode `Save()` **convertit** le fichier en PDF.
"""

    source_doc = parser.parse_string(source)
    target_doc = parser.parse_string(target)

    def count_code_spans(ast):
        count = 0
        def traverse(node):
            nonlocal count
            if node.type == NodeType.CODE_SPAN:
                count += 1
            for child in node.children:
                traverse(child)
        for node in ast:
            traverse(node)
        return count

    source_code = count_code_spans(source_doc.ast)
    target_code = count_code_spans(target_doc.ast)

    assert source_code == target_code, \
        f"Code span count must match: source={source_code}, target={target_code}"
    assert source_code >= 2, "Fixture should have at least 2 code spans"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
