"""
Integration test for nested list reconstruction (Issue #5).

Tests the full translation pipeline with nested lists to verify:
1. Nested list items are extracted correctly
2. All items are translated
3. Nested structure is preserved in output
4. No "orphaned TextUnits" warning appears
"""

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer

# Sample nested list markdown for testing
SIMPLE_NESTED_LIST = """
# Test Document

* Extract text from:
    * Slide bodies
    * Master slides
    * Layout slides
    * Note pages
    * Comments
* Option to preserve text order
* Another top-level item
"""

MULTIPLE_NESTING_LEVELS = """
# Multiple Levels

* Level 1
    * Level 2
        * Level 3
            * Level 4
* Back to Level 1
    * Level 2 again
"""

MIXED_CONTENT_NESTED_LIST = """
# Mixed Content

* Item with **bold** text and [link](https://example.com):
    * Nested item 1
    * Nested item 2 with *emphasis*
* Regular item with code: `inline_code()`
    * Another nested item
"""

ORDERED_NESTED_LIST = """
# Ordered Lists

1. First ordered item
    1. Nested ordered item
    2. Another nested ordered
2. Second ordered item
    * Mixed: unordered nested under ordered
"""


class MockTranslator:
    """Mock translator that adds French prefix to simulate translation."""

    def __init__(self):
        self.translation_map = {
            # Simple nested list
            "Extract text from:": "Extrait du texte de:",
            "Slide bodies": "Corps de diapositives",
            "Master slides": "Master slides",
            "Layout slides": "Layout slides",
            "Note pages": "Pages de notes",
            "Comments": "Commentaires",
            "Option to preserve text order": "Option de conservation de l'ordre du texte",
            "Another top-level item": "Un autre élément de niveau supérieur",
            "Test Document": "Document de test",
            # Multiple nesting levels
            "Multiple Levels": "Niveaux multiples",
            "Level 1": "Niveau 1",
            "Level 2": "Niveau 2",
            "Level 3": "Niveau 3",
            "Level 4": "Niveau 4",
            "Back to Level 1": "Retour au niveau 1",
            "Level 2 again": "Niveau 2 encore",
            # Mixed content
            "Mixed Content": "Contenu mixte",
            "Item with **bold** text and [link](https://example.com):": "Élément avec texte **gras** et [lien](https://example.com):",
            "Nested item 1": "Élément imbriqué 1",
            "Nested item 2 with *emphasis*": "Élément imbriqué 2 avec *emphase*",
            "Regular item with code: `inline_code()`": "Élément régulier avec code: `inline_code()`",
            "Another nested item": "Un autre élément imbriqué",
            # Ordered lists
            "Ordered Lists": "Listes ordonnées",
            "First ordered item": "Premier élément ordonné",
            "Nested ordered item": "Élément ordonné imbriqué",
            "Another nested ordered": "Un autre ordonné imbriqué",
            "Second ordered item": "Deuxième élément ordonné",
            "Mixed: unordered nested under ordered": "Mixte: non ordonné imbriqué sous ordonné",
        }

    def translate(self, text: str) -> str:
        """Return translation from map or original text."""
        return self.translation_map.get(text, text)


def translate_markdown(markdown_content: str) -> tuple[str, list, int, int]:
    """
    Full translation pipeline.

    Returns:
        tuple: (output_markdown, warnings, extracted_count, applied_count)
    """
    # Parse
    parser = HugoParser()
    doc = parser.parse_string(markdown_content)
    ast, frontmatter = doc.ast, doc.frontmatter

    # Extract
    extractor = TextUnitExtractor()
    plan = extractor.extract_from_ast(ast, frontmatter)
    text_units = plan.units
    extracted_count = len(text_units)

    # Mock translation
    translator = MockTranslator()
    for unit in text_units:
        if unit.source_text:
            unit.translated_text = translator.translate(unit.source_text)

    # Apply translations and render
    renderer = ASTRenderer()

    # Capture warnings by checking for orphaned units
    renderer.apply_translations(ast, text_units, frontmatter)

    # Check for unapplied units
    unapplied_units = set(renderer.unit_map.keys()) - renderer.applied_units
    # Filter out frontmatter units
    unapplied_non_frontmatter = [
        addr for addr in unapplied_units if not addr.startswith("frontmatter.")
    ]

    applied_count = len(renderer.applied_units)

    # Render
    output_markdown = renderer.render_to_markdown(ast)

    return output_markdown, unapplied_non_frontmatter, extracted_count, applied_count


def test_simple_nested_list():
    """Test basic nested list with 5 nested items."""
    output, unapplied, extracted, applied = translate_markdown(SIMPLE_NESTED_LIST)

    # Verify no orphaned units
    assert len(unapplied) == 0, f"Found {len(unapplied)} orphaned TextUnits: {unapplied[:5]}"

    # Verify all units were applied
    assert applied == extracted, f"Only {applied}/{extracted} units applied"

    # Verify output structure - should have nested items
    assert "Extrait du texte de:" in output
    assert "Corps de diapositives" in output
    assert "Master slides" in output
    assert "Layout slides" in output
    assert "Pages de notes" in output
    assert "Commentaires" in output
    assert "Option de conservation de l'ordre du texte" in output

    # Verify indentation exists (nested items should have leading spaces)
    # ASTRenderer uses 2-space indent per nesting level
    lines = output.split("\n")
    nested_lines = [line for line in lines if line.startswith("  -")]
    assert len(nested_lines) >= 5, f"Expected at least 5 nested items, found {len(nested_lines)}"

    print("\nPASS: Simple nested list test passed")
    print(f"   Extracted: {extracted} units")
    print(f"   Applied: {applied} units")
    print(f"   Orphaned: {len(unapplied)} units")
    print(f"   Nested lines: {len(nested_lines)}")


def test_multiple_nesting_levels():
    """Test multiple nesting levels (4 levels deep)."""
    output, unapplied, extracted, applied = translate_markdown(MULTIPLE_NESTING_LEVELS)

    # Verify no orphaned units
    assert len(unapplied) == 0, f"Found {len(unapplied)} orphaned TextUnits: {unapplied[:5]}"

    # Verify all units were applied
    assert applied == extracted, f"Only {applied}/{extracted} units applied"

    # Verify content
    assert "Niveau 1" in output
    assert "Niveau 2" in output
    assert "Niveau 3" in output
    assert "Niveau 4" in output

    # Verify different indentation levels exist
    # ASTRenderer uses 2-space indent per nesting level
    lines = output.split("\n")
    level2_lines = [line for line in lines if line.startswith("  -") or line.startswith("  *")]
    level3_lines = [line for line in lines if line.startswith("    -") or line.startswith("    *")]
    level4_lines = [
        line for line in lines if line.startswith("      -") or line.startswith("      *")
    ]

    assert len(level2_lines) >= 2, f"Expected at least 2 level-2 items, found {len(level2_lines)}"
    assert len(level3_lines) >= 1, f"Expected at least 1 level-3 item, found {len(level3_lines)}"
    assert len(level4_lines) >= 1, f"Expected at least 1 level-4 item, found {len(level4_lines)}"

    print("\nPASS: Multiple nesting levels test passed")
    print(f"   Level 2 items: {len(level2_lines)}")
    print(f"   Level 3 items: {len(level3_lines)}")
    print(f"   Level 4 items: {len(level4_lines)}")


def test_mixed_content_nested_list():
    """Test nested lists with inline formatting (bold, emphasis, links, code)."""
    output, unapplied, extracted, applied = translate_markdown(MIXED_CONTENT_NESTED_LIST)

    # Verify no orphaned units
    assert len(unapplied) == 0, f"Found {len(unapplied)} orphaned TextUnits: {unapplied[:5]}"

    # Verify all units were applied
    assert applied == extracted, f"Only {applied}/{extracted} units applied"

    # Verify content with inline formatting preserved
    assert "**gras**" in output or "**bold**" in output  # Bold preserved
    assert "[lien]" in output or "[link]" in output  # Link preserved
    assert "`inline_code()`" in output  # Code preserved
    assert "*emphase*" in output or "*emphasis*" in output  # Emphasis preserved

    # Verify nested structure (2-space indent per level)
    lines = output.split("\n")
    nested_lines = [line for line in lines if line.startswith("  -")]
    assert len(nested_lines) >= 3, f"Expected at least 3 nested items, found {len(nested_lines)}"

    print("\nPASS: Mixed content nested list test passed")
    print(f"   Nested items: {len(nested_lines)}")


def test_ordered_nested_list():
    """Test ordered lists with nested lists (ordered and unordered mix)."""
    output, unapplied, extracted, applied = translate_markdown(ORDERED_NESTED_LIST)

    # Verify no orphaned units
    assert len(unapplied) == 0, f"Found {len(unapplied)} orphaned TextUnits: {unapplied[:5]}"

    # Verify all units were applied
    assert applied == extracted, f"Only {applied}/{extracted} units applied"

    # Verify content
    assert "Premier élément ordonné" in output
    assert "Élément ordonné imbriqué" in output
    assert "Deuxième élément ordonné" in output

    # Verify ordered list structure (should have numbered items)
    lines = output.split("\n")
    ordered_top_level = [
        line for line in lines if line.strip().startswith("1.") or line.strip().startswith("2.")
    ]
    assert len(ordered_top_level) >= 2, (
        f"Expected at least 2 top-level ordered items, found {len(ordered_top_level)}"
    )

    # Verify nested structure (2-space indent per level)
    nested_lines = [line for line in lines if line.startswith("  ")]
    assert len(nested_lines) >= 2, f"Expected at least 2 nested items, found {len(nested_lines)}"

    print("\nPASS: Ordered nested list test passed")
    print(f"   Top-level ordered items: {len(ordered_top_level)}")
    print(f"   Nested items: {len(nested_lines)}")


def test_no_regression_simple_list():
    """Ensure simple (non-nested) lists still work correctly."""
    simple_list = """
# Simple List

* Item 1
* Item 2
* Item 3
"""

    output, unapplied, extracted, applied = translate_markdown(simple_list)

    # Verify no orphaned units
    assert len(unapplied) == 0, f"Found {len(unapplied)} orphaned TextUnits: {unapplied[:5]}"

    # Verify all units were applied
    assert applied == extracted, f"Only {applied}/{extracted} units applied"

    # Verify structure (should NOT have indented items)
    lines = output.split("\n")
    nested_lines = [line for line in lines if line.startswith("  -")]
    assert len(nested_lines) == 0, (
        f"Simple list should not have nested items, found {len(nested_lines)}"
    )

    print("\nPASS: Simple list (no regression) test passed")


if __name__ == "__main__":
    """Run all tests with detailed output."""
    print("=" * 70)
    print("INTEGRATION TEST: Nested List Reconstruction (Issue #5)")
    print("=" * 70)

    try:
        test_simple_nested_list()
        test_multiple_nesting_levels()
        test_mixed_content_nested_list()
        test_ordered_nested_list()
        test_no_regression_simple_list()

        print("\n" + "=" * 70)
        print("PASS: ALL TESTS PASSED")
        print("=" * 70)
        print("\nVerification Summary:")
        print("- Nested list items are extracted correctly")
        print("- All items are translated")
        print("- Nested structure is preserved in output")
        print("- No 'orphaned TextUnits' warnings")
        print("- Inline formatting preserved")
        print("- Multiple nesting levels supported")
        print("- No regression on simple lists")

    except AssertionError as e:
        print("\n" + "=" * 70)
        print("FAIL: TEST FAILED")
        print("=" * 70)
        print(f"\nError: {e}")
        raise
