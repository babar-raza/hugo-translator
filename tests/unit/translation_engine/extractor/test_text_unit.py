"""
Unit tests for TextUnit and BodyTranslationPlan data models (HP-06 TC-01).
"""

import pytest

from src.translation_engine.extractor.text_unit import (
    BodyTranslationPlan,
    TextUnit,
    TextUnitKind,
)


class TestTextUnitKind:
    """Test TextUnitKind enum."""

    def test_all_kinds_exist(self):
        """Test that all expected kinds are defined."""
        assert TextUnitKind.TEXT == "text"
        assert TextUnitKind.HEADING_TEXT == "heading_text"
        assert TextUnitKind.LINK_TEXT == "link_text"
        assert TextUnitKind.IMAGE_ALT == "image_alt"
        assert TextUnitKind.TABLE_CELL_TEXT == "table_cell_text"
        assert TextUnitKind.CODE_SPAN == "code_span"
        assert TextUnitKind.BLOCKQUOTE_TEXT == "blockquote_text"
        assert TextUnitKind.LIST_ITEM_TEXT == "list_item_text"

    def test_kind_values_are_strings(self):
        """Test that enum values are strings (for serialization)."""
        for kind in TextUnitKind:
            assert isinstance(kind.value, str)

    def test_kind_from_string(self):
        """Test creating enum from string value."""
        assert TextUnitKind("text") == TextUnitKind.TEXT
        assert TextUnitKind("heading_text") == TextUnitKind.HEADING_TEXT

    def test_kind_invalid_raises_error(self):
        """Test that invalid kind raises ValueError."""
        with pytest.raises(ValueError):
            TextUnitKind("invalid_kind")


class TestTextUnit:
    """Test TextUnit data model."""

    def test_create_basic_unit(self):
        """Test creating a basic TextUnit."""
        unit = TextUnit(
            unit_id="test_id",
            node_addr="para[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="Hello World",
        )

        assert unit.unit_id == "test_id"
        assert unit.node_addr == "para[0].text[0]"
        assert unit.kind == TextUnitKind.TEXT
        assert unit.source_text == "Hello World"
        assert unit.prefix_ws == ""
        assert unit.suffix_ws == ""
        assert unit.do_not_translate is False
        assert unit.translated_text is None
        assert unit.metadata == {}

    def test_create_unit_with_whitespace(self):
        """Test creating unit with whitespace fields."""
        unit = TextUnit(
            unit_id="test_id",
            node_addr="para[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="Hello",
            prefix_ws="  ",
            suffix_ws=" ",
        )

        assert unit.prefix_ws == "  "
        assert unit.suffix_ws == " "

    def test_create_unit_do_not_translate(self):
        """Test creating unit marked as do_not_translate."""
        unit = TextUnit(
            unit_id="code1",
            node_addr="para[0].code[0]",
            kind=TextUnitKind.CODE_SPAN,
            source_text="SaveFormat.Pptx",
            do_not_translate=True,
        )

        assert unit.do_not_translate is True

    def test_create_unit_with_metadata(self):
        """Test creating unit with metadata."""
        metadata = {"parent_type": "paragraph", "depth": 2}
        unit = TextUnit(
            unit_id="test_id",
            node_addr="para[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="Hello",
            metadata=metadata,
        )

        assert unit.metadata == metadata

    def test_validation_empty_unit_id(self):
        """Test that empty unit_id raises ValueError."""
        with pytest.raises(ValueError, match="unit_id cannot be empty"):
            TextUnit(
                unit_id="",
                node_addr="para[0].text[0]",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
            )

    def test_validation_empty_node_addr(self):
        """Test that empty node_addr raises ValueError."""
        with pytest.raises(ValueError, match="node_addr cannot be empty"):
            TextUnit(
                unit_id="test_id",
                node_addr="",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
            )

    def test_validation_empty_source_text_allowed(self):
        """Test that empty source_text is allowed (whitespace-only nodes)."""
        unit = TextUnit(
            unit_id="test_id",
            node_addr="para[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="",
        )
        assert unit.source_text == ""

    def test_create_id_method(self):
        """Test TextUnit.create_id() class method."""
        unit_id = TextUnit.create_id(
            node_addr="para[0].text[0]",
            source_text="Hello World",
            kind=TextUnitKind.TEXT,
        )

        assert isinstance(unit_id, str)
        assert len(unit_id) == 16  # First 16 chars of SHA-256

    def test_create_id_deterministic(self):
        """Test that create_id produces same ID for same inputs."""
        id1 = TextUnit.create_id("p1.t1", "Hello", TextUnitKind.TEXT)
        id2 = TextUnit.create_id("p1.t1", "Hello", TextUnitKind.TEXT)
        assert id1 == id2

    def test_create_id_different_for_different_inputs(self):
        """Test that create_id produces different IDs for different inputs."""
        id1 = TextUnit.create_id("p1.t1", "Hello", TextUnitKind.TEXT)
        id2 = TextUnit.create_id("p1.t2", "Hello", TextUnitKind.TEXT)  # Different node
        id3 = TextUnit.create_id("p1.t1", "World", TextUnitKind.TEXT)  # Different text
        id4 = TextUnit.create_id("p1.t1", "Hello", TextUnitKind.HEADING_TEXT)  # Different kind

        assert id1 != id2
        assert id1 != id3
        assert id1 != id4

    def test_serialization_to_dict(self):
        """Test TextUnit.to_dict() serialization."""
        unit = TextUnit(
            unit_id="abc123",
            node_addr="para[2].strong[0].text[1]",
            kind=TextUnitKind.TEXT,
            source_text="Hello World",
            prefix_ws="  ",
            suffix_ws=" ",
            do_not_translate=False,
            translated_text="Hola Mundo",
            metadata={"depth": 3},
        )

        data = unit.to_dict()

        assert data["unit_id"] == "abc123"
        assert data["node_addr"] == "para[2].strong[0].text[1]"
        assert data["kind"] == "text"  # Enum serialized to string
        assert data["source_text"] == "Hello World"
        assert data["prefix_ws"] == "  "
        assert data["suffix_ws"] == " "
        assert data["do_not_translate"] is False
        assert data["translated_text"] == "Hola Mundo"
        assert data["metadata"] == {"depth": 3}

    def test_deserialization_from_dict(self):
        """Test TextUnit.from_dict() deserialization."""
        data = {
            "unit_id": "abc123",
            "node_addr": "para[2].text[0]",
            "kind": "text",
            "source_text": "Hello",
            "prefix_ws": "  ",
            "suffix_ws": " ",
            "do_not_translate": False,
            "translated_text": "Hola",
            "metadata": {"depth": 2},
        }

        unit = TextUnit.from_dict(data)

        assert unit.unit_id == "abc123"
        assert unit.node_addr == "para[2].text[0]"
        assert unit.kind == TextUnitKind.TEXT
        assert unit.source_text == "Hello"
        assert unit.prefix_ws == "  "
        assert unit.suffix_ws == " "
        assert unit.do_not_translate is False
        assert unit.translated_text == "Hola"
        assert unit.metadata == {"depth": 2}

    def test_serialization_roundtrip(self):
        """Test that serialization roundtrip preserves all data."""
        original = TextUnit(
            unit_id="test123",
            node_addr="heading[1].text[0]",
            kind=TextUnitKind.HEADING_TEXT,
            source_text="Prerequisites",
            prefix_ws="",
            suffix_ws="",
            do_not_translate=False,
            translated_text="Voraussetzungen",
            metadata={"level": 2},
        )

        data = original.to_dict()
        restored = TextUnit.from_dict(data)

        assert restored.unit_id == original.unit_id
        assert restored.node_addr == original.node_addr
        assert restored.kind == original.kind
        assert restored.source_text == original.source_text
        assert restored.prefix_ws == original.prefix_ws
        assert restored.suffix_ws == original.suffix_ws
        assert restored.do_not_translate == original.do_not_translate
        assert restored.translated_text == original.translated_text
        assert restored.metadata == original.metadata

    def test_deserialization_with_defaults(self):
        """Test deserialization with optional fields missing (use defaults)."""
        data = {
            "unit_id": "abc",
            "node_addr": "p1.t1",
            "kind": "text",
            "source_text": "Hello",
            # Optional fields omitted
        }

        unit = TextUnit.from_dict(data)

        assert unit.prefix_ws == ""
        assert unit.suffix_ws == ""
        assert unit.do_not_translate is False
        assert unit.translated_text is None
        assert unit.metadata == {}

    def test_deserialization_missing_required_field(self):
        """Test that deserialization fails if required field is missing."""
        data = {
            "unit_id": "abc",
            "node_addr": "p1.t1",
            # Missing 'kind' and 'source_text'
        }

        with pytest.raises(KeyError):
            TextUnit.from_dict(data)

    def test_get_final_text_with_translation(self):
        """Test get_final_text() with translated text."""
        unit = TextUnit(
            unit_id="test",
            node_addr="p1.t1",
            kind=TextUnitKind.TEXT,
            source_text="Hello",
            prefix_ws="  ",
            suffix_ws=" ",
            translated_text="Hola",
        )

        assert unit.get_final_text() == "  Hola "

    def test_get_final_text_without_translation(self):
        """Test get_final_text() without translated text (uses source)."""
        unit = TextUnit(
            unit_id="test",
            node_addr="p1.t1",
            kind=TextUnitKind.TEXT,
            source_text="Hello",
            prefix_ws="  ",
            suffix_ws=" ",
            translated_text=None,
        )

        assert unit.get_final_text() == "  Hello "

    def test_get_final_text_no_whitespace(self):
        """Test get_final_text() with no whitespace."""
        unit = TextUnit(
            unit_id="test",
            node_addr="p1.t1",
            kind=TextUnitKind.TEXT,
            source_text="Hello",
            translated_text="Hola",
        )

        assert unit.get_final_text() == "Hola"

    def test_all_text_unit_kinds(self):
        """Test creating TextUnit with all possible kinds."""
        kinds = [
            TextUnitKind.TEXT,
            TextUnitKind.HEADING_TEXT,
            TextUnitKind.LINK_TEXT,
            TextUnitKind.IMAGE_ALT,
            TextUnitKind.TABLE_CELL_TEXT,
            TextUnitKind.CODE_SPAN,
            TextUnitKind.BLOCKQUOTE_TEXT,
            TextUnitKind.LIST_ITEM_TEXT,
        ]

        for kind in kinds:
            unit = TextUnit(
                unit_id=f"test_{kind.value}",
                node_addr=f"node_{kind.value}",
                kind=kind,
                source_text=f"Text for {kind.value}",
            )
            assert unit.kind == kind


class TestBodyTranslationPlan:
    """Test BodyTranslationPlan data model."""

    def test_create_basic_plan(self):
        """Test creating a basic BodyTranslationPlan."""
        ast = ["dummy", "ast", "nodes"]  # Mock AST
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
            )
        ]
        fingerprint = "abc123def456"

        plan = BodyTranslationPlan(
            ast=ast,
            units=units,
            ast_fingerprint=fingerprint,
        )

        assert plan.ast == ast
        assert plan.units == units
        assert plan.ast_fingerprint == fingerprint
        assert plan.metadata == {}

    def test_create_plan_with_metadata(self):
        """Test creating plan with metadata."""
        ast = []
        units = []
        metadata = {"source_lang": "en", "target_lang": "de"}

        plan = BodyTranslationPlan(
            ast=ast,
            units=units,
            ast_fingerprint="abc",
            metadata=metadata,
        )

        assert plan.metadata == metadata

    def test_validation_ast_none(self):
        """Test that None AST raises ValueError."""
        with pytest.raises(ValueError, match="ast cannot be None"):
            BodyTranslationPlan(
                ast=None,
                units=[],
                ast_fingerprint="abc",
            )

    def test_validation_units_not_list(self):
        """Test that non-list units raises ValueError."""
        with pytest.raises(ValueError, match="units must be a list"):
            BodyTranslationPlan(
                ast=[],
                units="not a list",
                ast_fingerprint="abc",
            )

    def test_validation_empty_fingerprint(self):
        """Test that empty fingerprint raises ValueError."""
        with pytest.raises(ValueError, match="ast_fingerprint cannot be empty"):
            BodyTranslationPlan(
                ast=[],
                units=[],
                ast_fingerprint="",
            )

    def test_get_translatable_units(self):
        """Test get_translatable_units() method."""
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
                do_not_translate=False,
            ),
            TextUnit(
                unit_id="u2",
                node_addr="p1.c1",
                kind=TextUnitKind.CODE_SPAN,
                source_text="code",
                do_not_translate=True,
            ),
            TextUnit(
                unit_id="u3",
                node_addr="p1.t2",
                kind=TextUnitKind.TEXT,
                source_text="World",
                do_not_translate=False,
            ),
        ]

        plan = BodyTranslationPlan(ast=[], units=units, ast_fingerprint="abc")
        translatable = plan.get_translatable_units()

        assert len(translatable) == 2
        assert translatable[0].unit_id == "u1"
        assert translatable[1].unit_id == "u3"

    def test_get_non_translatable_units(self):
        """Test get_non_translatable_units() method."""
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
                do_not_translate=False,
            ),
            TextUnit(
                unit_id="u2",
                node_addr="p1.c1",
                kind=TextUnitKind.CODE_SPAN,
                source_text="code1",
                do_not_translate=True,
            ),
            TextUnit(
                unit_id="u3",
                node_addr="p1.c2",
                kind=TextUnitKind.CODE_SPAN,
                source_text="code2",
                do_not_translate=True,
            ),
        ]

        plan = BodyTranslationPlan(ast=[], units=units, ast_fingerprint="abc")
        non_translatable = plan.get_non_translatable_units()

        assert len(non_translatable) == 2
        assert non_translatable[0].unit_id == "u2"
        assert non_translatable[1].unit_id == "u3"

    def test_plan_serialization_to_dict(self):
        """Test BodyTranslationPlan.to_dict() serialization."""
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
            ),
            TextUnit(
                unit_id="u2",
                node_addr="p1.t2",
                kind=TextUnitKind.TEXT,
                source_text="World",
            ),
        ]

        plan = BodyTranslationPlan(
            ast=["dummy"],
            units=units,
            ast_fingerprint="abc123",
            metadata={"lang": "en"},
        )

        data = plan.to_dict()

        assert "units" in data
        assert len(data["units"]) == 2
        assert data["units"][0]["unit_id"] == "u1"
        assert data["ast_fingerprint"] == "abc123"
        assert data["metadata"] == {"lang": "en"}
        assert "ast" not in data  # AST is not serialized

    def test_plan_deserialization_from_dict(self):
        """Test BodyTranslationPlan.from_dict() deserialization."""
        data = {
            "units": [
                {
                    "unit_id": "u1",
                    "node_addr": "p1.t1",
                    "kind": "text",
                    "source_text": "Hello",
                }
            ],
            "ast_fingerprint": "abc123",
            "metadata": {"lang": "en"},
        }

        ast = ["dummy", "ast"]
        plan = BodyTranslationPlan.from_dict(data, ast)

        assert plan.ast == ast
        assert len(plan.units) == 1
        assert plan.units[0].unit_id == "u1"
        assert plan.ast_fingerprint == "abc123"
        assert plan.metadata == {"lang": "en"}

    def test_plan_serialization_roundtrip(self):
        """Test that plan serialization roundtrip preserves data (except AST)."""
        original_ast = ["original", "ast"]
        original_units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
                translated_text="Hola",
            )
        ]

        original = BodyTranslationPlan(
            ast=original_ast,
            units=original_units,
            ast_fingerprint="fingerprint123",
            metadata={"source_lang": "en", "target_lang": "es"},
        )

        # Serialize
        data = original.to_dict()

        # Deserialize (must provide AST separately)
        restored = BodyTranslationPlan.from_dict(data, ast=original_ast)

        # Check that everything matches (except AST reference)
        assert len(restored.units) == len(original.units)
        assert restored.units[0].unit_id == original.units[0].unit_id
        assert restored.units[0].source_text == original.units[0].source_text
        assert restored.units[0].translated_text == original.units[0].translated_text
        assert restored.ast_fingerprint == original.ast_fingerprint
        assert restored.metadata == original.metadata

    def test_empty_units_list(self):
        """Test creating plan with empty units list."""
        plan = BodyTranslationPlan(ast=[], units=[], ast_fingerprint="abc")

        assert plan.units == []
        assert plan.get_translatable_units() == []
        assert plan.get_non_translatable_units() == []


class TestIntegration:
    """Integration tests for TextUnit and BodyTranslationPlan."""

    def test_typical_workflow(self):
        """Test typical translation workflow with TextUnit and BodyTranslationPlan."""
        # 1. Create units (simulating extraction from AST)
        units = [
            TextUnit(
                unit_id=TextUnit.create_id("p1.t1", "Install", TextUnitKind.TEXT),
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Install",
                prefix_ws="",
                suffix_ws=" ",
            ),
            TextUnit(
                unit_id=TextUnit.create_id("p1.s1.t1", "Visual Studio", TextUnitKind.TEXT),
                node_addr="p1.s1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Visual Studio",
                do_not_translate=True,  # Product name
            ),
            TextUnit(
                unit_id=TextUnit.create_id("p1.t2", " 2019", TextUnitKind.TEXT),
                node_addr="p1.t2",
                kind=TextUnitKind.TEXT,
                source_text=" 2019",
            ),
        ]

        # 2. Create translation plan
        ast = ["dummy", "ast"]
        plan = BodyTranslationPlan(
            ast=ast,
            units=units,
            ast_fingerprint="test_fingerprint",
            metadata={"source_lang": "en", "target_lang": "de"},
        )

        # 3. Translate translatable units
        for unit in plan.get_translatable_units():
            # Simulate MT translation
            if unit.source_text == "Install":
                unit.translated_text = "Installieren Sie"
            elif unit.source_text == " 2019":
                unit.translated_text = " 2019"

        # 4. Copy non-translatable units as-is
        for unit in plan.get_non_translatable_units():
            unit.translated_text = unit.source_text

        # 5. Get final text for each unit
        final_texts = [unit.get_final_text() for unit in plan.units]

        assert final_texts[0] == "Installieren Sie "
        assert final_texts[1] == "Visual Studio"  # Preserved
        assert final_texts[2] == " 2019"

    def test_serialization_and_restoration(self):
        """Test full serialization and restoration workflow."""
        # Create plan
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="h1.t1",
                kind=TextUnitKind.HEADING_TEXT,
                source_text="Prerequisites",
            )
        ]
        original_ast = ["dummy"]
        plan = BodyTranslationPlan(
            ast=original_ast,
            units=units,
            ast_fingerprint="fp123",
        )

        # Serialize
        serialized = plan.to_dict()

        # Restore from serialization (simulating cache read)
        # Note: In real workflow, AST comes from re-parsing the original file
        restored_plan = BodyTranslationPlan.from_dict(serialized, ast=original_ast)

        # Verify restoration
        assert len(restored_plan.units) == 1
        assert restored_plan.units[0].node_addr == "h1.t1"
        assert restored_plan.ast_fingerprint == "fp123"
