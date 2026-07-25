"""Frontmatter placeholder restoration is part of the pre-write AST gate."""

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


def _frontmatter_unit(translation: str, placeholder_map: dict[str, str]) -> TextUnit:
    return TextUnit(
        unit_id="frontmatter-title",
        node_addr="frontmatter.title",
        kind=TextUnitKind.TEXT,
        source_text="Spreadsheet Management with {PLACEHOLDER_0}",
        translated_text=translation,
        metadata={
            "field_name": "title",
            "field_type": "string",
            "placeholder_map": placeholder_map,
        },
    )


def test_frontmatter_placeholders_are_restored_before_assignment():
    renderer = ASTRenderer()
    frontmatter = {"title": "Spreadsheet Management with Aspose.Cells"}
    unit = _frontmatter_unit(
        "إدارة جداول البيانات باستخدام {PLACEHOLDER_0}",
        {"{PLACEHOLDER_0}": "Aspose.Cells"},
    )

    renderer.apply_translations([], [unit], frontmatter=frontmatter)

    assert frontmatter["title"] == "إدارة جداول البيانات باستخدام Aspose.Cells"
    assert renderer.placeholder_leak_count == 0


def test_unknown_frontmatter_placeholder_is_counted_as_blocking_leak():
    renderer = ASTRenderer()
    frontmatter = {"title": "Source title"}
    unit = _frontmatter_unit("ترجمة {PLACEHOLDER_9}", {})

    renderer.apply_translations([], [unit], frontmatter=frontmatter)

    assert renderer.placeholder_leak_count == 1
