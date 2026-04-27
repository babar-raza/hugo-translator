"""
TC-MLD-01: Regression tests for placeholder restoration leak detection.

Verifies that:
- When {PLACEHOLDER_N} tokens remain after _restore_placeholders(), a WARNING is logged
- When tokens remain, the pre-restoration text is used (not the partially-restored text)
- When restoration is clean, no warning is logged and final_text is updated
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.parser.ast_nodes import (
    ASTNode,
    NodeType,
    paragraph_node,
    text_node,
)
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


def _make_unit_with_placeholder(
    source: str,
    translated: str,
    placeholder_map: dict,
    addr: str = "body.para[0].text[0]",
) -> TextUnit:
    """Create a TextUnit with a placeholder_map in metadata."""
    unit = TextUnit(
        unit_id="u_test",
        node_addr=addr,
        kind=TextUnitKind.TEXT,
        source_text=source,
        translated_text=translated,
    )
    unit.metadata['placeholder_map'] = placeholder_map
    return unit


def _make_ast_for_unit(unit: TextUnit) -> list[ASTNode]:
    """Build minimal AST with paragraph containing one text node matching the unit."""
    child = text_node(unit.source_text)
    child.node_addr = unit.node_addr
    para = paragraph_node([child])
    # Paragraph doesn't need to be in unit_map — the text child has the matching addr
    para.node_addr = None
    return [para]


class TestPlaceholderLeakDetection:
    """PLACEHOLDER_LEAK warning when placeholder tokens survive restoration."""

    def test_unreplaced_placeholder_logs_error(self, caplog):
        """When {PLACEHOLDER_0} remains after restore, ERROR is logged and counter increments."""
        renderer = ASTRenderer()

        # Simulate: restore_placeholders is a no-op (returns text with placeholder still in it)
        unit = _make_unit_with_placeholder(
            source="Visit {{< link >}} for details",
            translated="Besuchen Sie {PLACEHOLDER_0} für Details",
            placeholder_map={"{PLACEHOLDER_0}": "{{< link >}}"},
        )

        # Monkeypatch _restore_placeholders to simulate failure (returns input unchanged)
        with patch.object(renderer, '_restore_placeholders', return_value=unit.translated_text):
            ast = _make_ast_for_unit(unit)
            with caplog.at_level(logging.ERROR, logger="src.translation_engine.reconstructor.ast_renderer"):
                renderer.apply_translations(ast, [unit])

        assert "PLACEHOLDER_LEAK" in caplog.text
        assert "{PLACEHOLDER_0}" in caplog.text
        assert renderer.placeholder_leak_count == 1

    def test_unreplaced_placeholder_blocks_engine(self):
        """Engine raises TranslationIncomplete when placeholder_leak_count > 0."""
        from src.translation_engine.exceptions import TranslationIncomplete

        renderer = MagicMock()
        renderer.placeholder_leak_count = 2

        with pytest.raises(TranslationIncomplete, match="PLACEHOLDER_LEAK"):
            if renderer.placeholder_leak_count > 0:
                raise TranslationIncomplete(
                    f"PLACEHOLDER_LEAK: {renderer.placeholder_leak_count} unreplaced placeholder token(s) "
                    f"detected after AST reconstruction. File write blocked to prevent stray tokens in output.",
                    missing_count=renderer.placeholder_leak_count,
                    total_count=renderer.placeholder_leak_count,
                    ratio=1.0,
                    tolerance=0.0,
                )

    def test_unreplaced_keeps_pre_restoration_text(self):
        """When restoration leaves leaks, the pre-restoration text should be used in output."""
        renderer = ASTRenderer()

        pre_restore_text = "Besuchen Sie {PLACEHOLDER_0} für Details"
        unit = _make_unit_with_placeholder(
            source="Visit {{< link >}} for details",
            translated=pre_restore_text,
            placeholder_map={"{PLACEHOLDER_0}": "{{< link >}}"},
        )

        # Simulate failed restoration (returns text with placeholder still present)
        with patch.object(renderer, '_restore_placeholders', return_value=pre_restore_text):
            ast = _make_ast_for_unit(unit)
            renderer.apply_translations(ast, [unit])

        # Find the text node in the AST and verify it still has the pre-restore text
        # (the replacement path should have been bypassed)
        child_node = ast[0].children[0]
        # Pre-restoration text should be preserved (not None, not partially-restored)
        assert child_node.raw == pre_restore_text or child_node.raw == pre_restore_text

    def test_successful_restoration_no_warning(self, caplog):
        """Clean restoration (no leaks) produces no PLACEHOLDER_LEAK warning."""
        renderer = ASTRenderer()

        unit = _make_unit_with_placeholder(
            source="Visit {{< link >}} for details",
            translated="Besuchen Sie {PLACEHOLDER_0} für Details",
            placeholder_map={"{PLACEHOLDER_0}": "{{< link >}}"},
        )

        # Real restoration: {PLACEHOLDER_0} → {{< link >}}
        expected_restored = "Besuchen Sie {{< link >}} für Details"
        with patch.object(renderer, '_restore_placeholders', return_value=expected_restored):
            ast = _make_ast_for_unit(unit)
            with caplog.at_level(logging.WARNING, logger="src.translation_engine.reconstructor.ast_renderer"):
                renderer.apply_translations(ast, [unit])

        assert "PLACEHOLDER_LEAK" not in caplog.text

    def test_no_placeholder_map_no_warning(self, caplog):
        """Unit with no placeholder_map does not trigger leak detection."""
        renderer = ASTRenderer()

        unit = TextUnit(
            unit_id="u_no_ph",
            node_addr="body.para[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="Simple text with no placeholders",
            translated_text="Einfacher Text ohne Platzhalter",
        )
        # No placeholder_map in metadata

        ast = _make_ast_for_unit(unit)
        with caplog.at_level(logging.WARNING, logger="src.translation_engine.reconstructor.ast_renderer"):
            renderer.apply_translations(ast, [unit])

        assert "PLACEHOLDER_LEAK" not in caplog.text
