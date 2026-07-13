"""
Tests for FileReconstructor — surgical per-unit file reconstruction.

These tests exercise the reconstruction logic using mocks to avoid
requiring a full engine, GPU model, or content repo on disk.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.translation_engine.file_reconstructor import FileReconstructor
from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_unit(
    source_text: str,
    kind: TextUnitKind = TextUnitKind.TEXT,
    do_not_translate: bool = False,
    node_addr: str = "body.para[0].text[0]",
    translated_text: str | None = None,
) -> TextUnit:
    return TextUnit(
        unit_id=TextUnit.create_id(node_addr, source_text, kind),
        node_addr=node_addr,
        kind=kind,
        source_text=source_text,
        translated_text=translated_text,
        do_not_translate=do_not_translate,
    )


# ---------------------------------------------------------------------------
# _apply_passthrough_from_en
# ---------------------------------------------------------------------------

class TestApplyPassthroughFromEn:
    """Tests for the passthrough helper — no file I/O needed."""

    def test_passthrough_unit_gets_en_value(self):
        rec = FileReconstructor()
        unit = _make_unit(
            source_text="Вирівнювання",  # current TR value (Ukrainian)
            kind=TextUnitKind.TEXT,
            do_not_translate=True,
            node_addr="frontmatter.title",
        )
        en_frontmatter = {"title": "Alignment"}
        rec._apply_passthrough_from_en([unit], en_frontmatter)
        assert unit.translated_text == "Alignment"

    def test_non_passthrough_unit_unchanged(self):
        rec = FileReconstructor()
        unit = _make_unit(
            source_text="Some translated text",
            kind=TextUnitKind.TEXT,
            do_not_translate=False,  # not a passthrough unit
            node_addr="frontmatter.description",
        )
        original_translated = unit.translated_text
        en_frontmatter = {"description": "English description"}
        rec._apply_passthrough_from_en([unit], en_frontmatter)
        # Should NOT be overwritten (do_not_translate is False)
        assert unit.translated_text == original_translated

    def test_body_unit_not_affected(self):
        rec = FileReconstructor()
        unit = _make_unit(
            source_text="Body text",
            node_addr="body.para[0].text[0]",  # not frontmatter
            do_not_translate=True,
        )
        en_frontmatter = {"title": "Something"}
        rec._apply_passthrough_from_en([unit], en_frontmatter)
        # node_addr doesn't start with "frontmatter." — should be untouched
        assert unit.translated_text is None

    def test_field_name_extracted_from_array_addr(self):
        """frontmatter.keywords[0] → field_name = keywords"""
        rec = FileReconstructor()
        unit = _make_unit(
            source_text="продукт",
            do_not_translate=True,
            node_addr="frontmatter.keywords[0]",
        )
        # keywords is a list in EN frontmatter
        en_frontmatter = {"keywords": ["product"]}
        # List value — should not overwrite (only str values are handled)
        rec._apply_passthrough_from_en([unit], en_frontmatter)
        assert unit.translated_text is None  # list, not str


# ---------------------------------------------------------------------------
# reconstruct (integration with mocked parser/extractor/renderer)
# ---------------------------------------------------------------------------

class TestReconstruct:
    """Full reconstruct() tests using mocks for heavy dependencies."""

    def _make_mock_doc(self, frontmatter=None):
        doc = MagicMock()
        doc.ast = []
        doc.frontmatter = frontmatter or {"title": "Test"}
        return doc

    def _make_mock_plan(self, units):
        plan = MagicMock()
        plan.units = units
        return plan

    def test_identity_reconstruction_keeps_existing_text(self):
        """Without replacements, all units keep their source_text."""
        units = [
            _make_unit("Текст параграфа один.", node_addr="body.p[0]"),
            _make_unit("Текст параграфа два.", node_addr="body.p[1]"),
            _make_unit("Текст параграфа три.", node_addr="body.p[2]"),
        ]
        mock_plan = self._make_mock_plan(units)
        mock_doc = self._make_mock_doc()

        renderer_mock = MagicMock()
        renderer_mock.render_to_markdown.return_value = "reconstructed body"
        formatter_mock = MagicMock()
        formatter_mock.format_frontmatter.return_value = "---\ntitle: Test\n---"

        with (
            patch("src.translation_engine.file_reconstructor.HugoParser") as MockParser,
            patch("src.translation_engine.file_reconstructor.ASTRenderer", return_value=renderer_mock),
            patch("src.translation_engine.file_reconstructor.YAMLFormatter", return_value=formatter_mock),
            patch("src.translation_engine.file_reconstructor.TextUnitExtractor") as MockExtractor,
        ):
            MockParser.return_value.parse_string.return_value = mock_doc
            MockExtractor.return_value.extract_from_ast.return_value = mock_plan

            rec = FileReconstructor()
            result = rec.reconstruct(
                original_tr_content="---\ntitle: Test\n---\noriginal body",
                en_content="---\ntitle: Test\n---\nen body",
                unit_replacements={},
                site_id="reference.aspose.org",
                locale="uk",
            )

        # Verify each unit has identity translation
        for unit in units:
            assert unit.translated_text == unit.source_text

        assert "reconstructed body" in result

    def test_replacement_overrides_specific_unit(self):
        """Only the replaced unit has new translated_text; others keep source_text."""
        units = [
            _make_unit("Текст 1.", node_addr="body.p[0]"),
            _make_unit("Текст 2.", node_addr="body.p[1]"),
            _make_unit("Текст 3.", node_addr="body.p[2]"),
        ]
        mock_plan = self._make_mock_plan(units)
        mock_doc = self._make_mock_doc()

        renderer_mock = MagicMock()
        renderer_mock.render_to_markdown.return_value = "body"
        formatter_mock = MagicMock()
        formatter_mock.format_frontmatter.return_value = "---\ntitle: T\n---"

        with (
            patch("src.translation_engine.file_reconstructor.HugoParser") as MockParser,
            patch("src.translation_engine.file_reconstructor.ASTRenderer", return_value=renderer_mock),
            patch("src.translation_engine.file_reconstructor.YAMLFormatter", return_value=formatter_mock),
            patch("src.translation_engine.file_reconstructor.TextUnitExtractor") as MockExtractor,
        ):
            MockParser.return_value.parse_string.return_value = mock_doc
            MockExtractor.return_value.extract_from_ast.return_value = mock_plan

            rec = FileReconstructor()
            rec.reconstruct(
                original_tr_content="---\ntitle: T\n---\n",
                en_content="---\ntitle: T\n---\n",
                unit_replacements={1: "Виправлений текст 2."},
                site_id="reference.aspose.org",
                locale="uk",
            )

        assert units[0].translated_text == "Текст 1."
        assert units[1].translated_text == "Виправлений текст 2."
        assert units[2].translated_text == "Текст 3."

    def test_out_of_range_replacement_logged_not_raised(self):
        """unit_idx beyond list length should not raise, just warn."""
        units = [_make_unit("Текст.", node_addr="body.p[0]")]
        mock_plan = self._make_mock_plan(units)
        mock_doc = self._make_mock_doc()

        renderer_mock = MagicMock()
        renderer_mock.render_to_markdown.return_value = "body"
        formatter_mock = MagicMock()
        formatter_mock.format_frontmatter.return_value = "---\ntitle: T\n---"

        with (
            patch("src.translation_engine.file_reconstructor.HugoParser") as MockParser,
            patch("src.translation_engine.file_reconstructor.ASTRenderer", return_value=renderer_mock),
            patch("src.translation_engine.file_reconstructor.YAMLFormatter", return_value=formatter_mock),
            patch("src.translation_engine.file_reconstructor.TextUnitExtractor") as MockExtractor,
        ):
            MockParser.return_value.parse_string.return_value = mock_doc
            MockExtractor.return_value.extract_from_ast.return_value = mock_plan

            rec = FileReconstructor()
            # Should not raise even with out-of-range index
            rec.reconstruct(
                original_tr_content="---\ntitle: T\n---\n",
                en_content="---\ntitle: T\n---\n",
                unit_replacements={99: "Some text"},
                site_id="reference.aspose.org",
                locale="uk",
            )

        # Unit 0 keeps its identity
        assert units[0].translated_text == "Текст."

    def test_output_format_has_frontmatter_and_body(self):
        """Result should be 'frontmatter_yaml\\nbody'."""
        units = []
        mock_plan = self._make_mock_plan(units)
        mock_doc = self._make_mock_doc(frontmatter={"title": "My Doc"})

        renderer_mock = MagicMock()
        renderer_mock.render_to_markdown.return_value = "My body content."
        formatter_mock = MagicMock()
        formatter_mock.format_frontmatter.return_value = "---\ntitle: My Doc\n---"

        with (
            patch("src.translation_engine.file_reconstructor.HugoParser") as MockParser,
            patch("src.translation_engine.file_reconstructor.ASTRenderer", return_value=renderer_mock),
            patch("src.translation_engine.file_reconstructor.YAMLFormatter", return_value=formatter_mock),
            patch("src.translation_engine.file_reconstructor.TextUnitExtractor") as MockExtractor,
        ):
            MockParser.return_value.parse_string.return_value = mock_doc
            MockExtractor.return_value.extract_from_ast.return_value = mock_plan

            rec = FileReconstructor()
            result = rec.reconstruct(
                original_tr_content="---\ntitle: My Doc\n---\nMy body content.",
                en_content="---\ntitle: My Doc\n---\nMy body content.",
                unit_replacements={},
                site_id="docs.aspose.org",
                locale="de",
            )

        assert result == "---\ntitle: My Doc\n---\nMy body content."
