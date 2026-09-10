"""TD-02 (TC-APT-105 audit): leaf_inventory.classify_sole_leaf, the shared
reference implementation of RC-01's fixed AST-reuse safety check.

Covers all three LeafClassification outcomes plus the edge cases the
taskcard calls out explicitly: zero leaves, deeply nested single leaf, and
multiple do_not_translate leaves.
"""

from __future__ import annotations

from src.translation_engine.extractor.leaf_inventory import (
    LeafClassification,
    classify_sole_leaf,
)
from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind


def _unit(node_addr: str, *, source_text: str = "text", do_not_translate: bool = False) -> TextUnit:
    return TextUnit(
        unit_id=f"unit-{node_addr}",
        node_addr=node_addr,
        kind=TextUnitKind.TEXT,
        source_text=source_text,
        prefix_ws="",
        suffix_ws="",
        do_not_translate=do_not_translate,
    )


class TestOrdinarySoleLeaf:
    def test_container_addr_itself_is_the_sole_leaf(self):
        units = [_unit("para[0]")]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.ORDINARY_SOLE_LEAF
        assert result.sole_unit is units[0]

    def test_single_descendant_leaf(self):
        units = [_unit("para[0].link[0].text[0]")]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.ORDINARY_SOLE_LEAF
        assert result.sole_unit is units[0]

    def test_deeply_nested_single_leaf(self):
        units = [_unit("para[0].strong[0].link[0].text[0]")]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.ORDINARY_SOLE_LEAF
        assert result.sole_unit is units[0]

    def test_units_outside_the_subtree_are_ignored(self):
        units = [_unit("para[0].text[0]"), _unit("para[1].text[0]")]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.ORDINARY_SOLE_LEAF
        assert result.sole_unit is units[0]

    def test_sibling_addr_sharing_a_string_prefix_is_not_a_false_match(self):
        """"para[10]" must not be treated as a descendant of "para[1]" just
        because the string "para[1]" is a prefix of "para[10]" -- only an
        exact match or a "." child-path boundary counts."""
        units = [_unit("para[10].text[0]")]

        result = classify_sole_leaf("para[1]", units)

        assert result.classification == LeafClassification.NOT_SOLE_LEAF


class TestProtectedSoleLeaf:
    def test_single_protected_leaf(self):
        units = [_unit("para[0].link[0].text[0]", do_not_translate=True)]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.PROTECTED_SOLE_LEAF
        assert result.sole_unit is units[0]


class TestNotSoleLeaf:
    def test_zero_leaves(self):
        units: list[TextUnit] = []

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.NOT_SOLE_LEAF
        assert result.sole_unit is None

    def test_zero_leaves_because_only_empty_source_text_units_exist(self):
        units = [_unit("para[0].text[0]", source_text="")]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.NOT_SOLE_LEAF

    def test_two_ordinary_leaves(self):
        units = [_unit("para[0].text[0]"), _unit("para[0].text[1]")]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.NOT_SOLE_LEAF
        assert result.sole_unit is None

    def test_multiple_do_not_translate_leaves(self):
        """The exact live TC-APT-105 shape: one protected leaf plus one
        ordinary leaf must NOT look like "exactly one leaf" just because
        only one of them is do_not_translate."""
        units = [
            _unit("para[0].link[0].text[0]", do_not_translate=True),
            _unit("para[0].text[1]", do_not_translate=False),
        ]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.NOT_SOLE_LEAF
        assert result.sole_unit is None

    def test_two_protected_leaves(self):
        units = [
            _unit("para[0].text[0]", do_not_translate=True),
            _unit("para[0].text[1]", do_not_translate=True),
        ]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.NOT_SOLE_LEAF
        assert result.sole_unit is None

    def test_container_addr_itself_plus_a_separate_descendant_is_two_leaves(self):
        units = [_unit("para[0]"), _unit("para[0].text[0]")]

        result = classify_sole_leaf("para[0]", units)

        assert result.classification == LeafClassification.NOT_SOLE_LEAF
