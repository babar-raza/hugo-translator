"""
Unit tests for nested list reconstruction (TASK-PROD-001).

Tests verify that nested list structures are preserved during translation
and that all nested list items receive their translations correctly.

Bug Fix: Previously, when a LIST_ITEM had a translation applied, the
`node.children = [text_node]` line would delete all nested LIST children,
causing nested list items to be orphaned and their translations never applied.

Fix: Preserve nested LIST children when replacing LIST_ITEM content by
extracting them first and appending after the text node.
"""

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


class TestNestedListReconstruction:
    """Test nested list reconstruction after translation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.renderer = ASTRenderer()

    def test_basic_two_level_nested_list(self):
        """
        Test Case 1: Basic 2-level nested list.

        Structure:
        - Parent item (translated)
            - Child item 1 (translated)
            - Child item 2 (translated)
        - Another parent (translated)

        Verifies:
        - All 4 translations applied
        - Nested LIST structure preserved
        - No orphaned TextUnits
        """
        # Create AST structure
        # Parent LIST_ITEM
        child_item_1 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Child 1", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[0]",
        )
        child_item_2 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Child 2", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[1]",
        )
        nested_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[child_item_1, child_item_2],
            attrs={"ordered": False},
            node_addr="body.list[0].listitem[0].list[0]",
        )
        parent_item_1 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[
                ASTNode(type=NodeType.TEXT, raw="Parent item", children=[], attrs={}),
                nested_list,
            ],
            attrs={},
            node_addr="body.list[0].listitem[0]",
        )
        parent_item_2 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Another parent", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[1]",
        )
        root_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[parent_item_1, parent_item_2],
            attrs={"ordered": False},
            node_addr="body.list[0]",
        )

        ast = [root_list]

        # Create translated TextUnits
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="body.list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Parent item",
                translated_text="Élément parent",
            ),
            TextUnit(
                unit_id="u2",
                node_addr="body.list[0].listitem[0].list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Child 1",
                translated_text="Enfant 1",
            ),
            TextUnit(
                unit_id="u3",
                node_addr="body.list[0].listitem[0].list[0].listitem[1]",
                kind=TextUnitKind.TEXT,
                source_text="Child 2",
                translated_text="Enfant 2",
            ),
            TextUnit(
                unit_id="u4",
                node_addr="body.list[0].listitem[1]",
                kind=TextUnitKind.TEXT,
                source_text="Another parent",
                translated_text="Un autre parent",
            ),
        ]

        # Apply translations
        self.renderer.apply_translations(ast, units)

        # Verify all units were applied
        assert len(self.renderer.applied_units) == 4, "All 4 TextUnits should be applied"
        assert len(self.renderer.unit_map) - len(self.renderer.applied_units) == 0, (
            "No orphaned units"
        )

        # Verify AST structure preserved
        parent_item = ast[0].children[0]  # First list item
        assert len(parent_item.children) == 2, "Parent item should have text + nested list"
        assert parent_item.children[0].type == NodeType.TEXT, "First child should be TEXT"
        assert parent_item.children[0].raw == "Élément parent", "Parent text should be translated"
        assert parent_item.children[1].type == NodeType.LIST, "Second child should be nested LIST"

        # Verify nested list structure
        nested = parent_item.children[1]
        assert len(nested.children) == 2, "Nested list should have 2 items"
        assert nested.children[0].children[0].raw == "Enfant 1", "First nested item translated"
        assert nested.children[1].children[0].raw == "Enfant 2", "Second nested item translated"

        # Verify markdown output
        markdown = self.renderer.render_to_markdown(ast)
        assert "Élément parent" in markdown
        assert "Enfant 1" in markdown
        assert "Enfant 2" in markdown
        assert "Un autre parent" in markdown

    def test_three_level_nested_list(self):
        """
        Test Case 2: 3-level nested list.

        Structure:
        - Level 1
            - Level 2
                - Level 3

        Verifies:
        - All 3 levels translated
        - Deep nesting preserved
        - Correct indentation in output
        """
        # Create AST: Level 3 item
        level_3_item = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Level 3", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[0].list[0].listitem[0]",
        )
        level_3_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[level_3_item],
            attrs={"ordered": False},
            node_addr="body.list[0].listitem[0].list[0].listitem[0].list[0]",
        )

        # Level 2 item (contains level 3 list)
        level_2_item = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[
                ASTNode(type=NodeType.TEXT, raw="Level 2", children=[], attrs={}),
                level_3_list,
            ],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[0]",
        )
        level_2_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[level_2_item],
            attrs={"ordered": False},
            node_addr="body.list[0].listitem[0].list[0]",
        )

        # Level 1 item (contains level 2 list)
        level_1_item = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[
                ASTNode(type=NodeType.TEXT, raw="Level 1", children=[], attrs={}),
                level_2_list,
            ],
            attrs={},
            node_addr="body.list[0].listitem[0]",
        )
        root_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[level_1_item],
            attrs={"ordered": False},
            node_addr="body.list[0]",
        )

        ast = [root_list]

        # Create translated TextUnits
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="body.list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Level 1",
                translated_text="Niveau 1",
            ),
            TextUnit(
                unit_id="u2",
                node_addr="body.list[0].listitem[0].list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Level 2",
                translated_text="Niveau 2",
            ),
            TextUnit(
                unit_id="u3",
                node_addr="body.list[0].listitem[0].list[0].listitem[0].list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Level 3",
                translated_text="Niveau 3",
            ),
        ]

        # Apply translations
        self.renderer.apply_translations(ast, units)

        # Verify all units applied
        assert len(self.renderer.applied_units) == 3, "All 3 TextUnits should be applied"

        # Verify deep nesting preserved
        level_1 = ast[0].children[0]
        assert len(level_1.children) == 2, "Level 1 should have text + nested list"
        assert level_1.children[1].type == NodeType.LIST, "Level 1 should have nested LIST"

        level_2 = level_1.children[1].children[0]
        assert len(level_2.children) == 2, "Level 2 should have text + nested list"
        assert level_2.children[1].type == NodeType.LIST, "Level 2 should have nested LIST"

        level_3 = level_2.children[1].children[0]
        assert len(level_3.children) == 1, "Level 3 should have only text"
        assert level_3.children[0].raw == "Niveau 3", "Level 3 translated"

        # Verify markdown output
        markdown = self.renderer.render_to_markdown(ast)
        assert "Niveau 1" in markdown
        assert "Niveau 2" in markdown
        assert "Niveau 3" in markdown

    def test_mixed_content_with_nested_lists(self):
        """
        Test Case 3: Mixed content (inline formatting + nested lists).

        Structure:
        - Item with **bold** and *italic*:
            - Nested item 1
            - Nested item 2

        Verifies:
        - Parent item translation includes inline formatting
        - Nested lists still preserved
        - No interference between inline and block elements
        """
        # Create nested items
        nested_item_1 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Nested 1", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[0]",
        )
        nested_item_2 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Nested 2", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[1]",
        )
        nested_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[nested_item_1, nested_item_2],
            attrs={"ordered": False},
            node_addr="body.list[0].listitem[0].list[0]",
        )

        # Parent item with mixed inline content
        parent_item = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[
                ASTNode(type=NodeType.TEXT, raw="Item with ", children=[], attrs={}),
                ASTNode(
                    type=NodeType.STRONG,
                    raw="",
                    children=[ASTNode(type=NodeType.TEXT, raw="bold", children=[], attrs={})],
                    attrs={},
                ),
                ASTNode(type=NodeType.TEXT, raw=" and ", children=[], attrs={}),
                ASTNode(
                    type=NodeType.EMPHASIS,
                    raw="",
                    children=[ASTNode(type=NodeType.TEXT, raw="italic", children=[], attrs={})],
                    attrs={},
                ),
                nested_list,
            ],
            attrs={},
            node_addr="body.list[0].listitem[0]",
        )
        root_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[parent_item],
            attrs={"ordered": False},
            node_addr="body.list[0]",
        )

        ast = [root_list]

        # Create translated TextUnits
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="body.list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Item with bold and italic",
                translated_text="Élément avec **gras** et *italique*",
            ),
            TextUnit(
                unit_id="u2",
                node_addr="body.list[0].listitem[0].list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Nested 1",
                translated_text="Imbriqué 1",
            ),
            TextUnit(
                unit_id="u3",
                node_addr="body.list[0].listitem[0].list[0].listitem[1]",
                kind=TextUnitKind.TEXT,
                source_text="Nested 2",
                translated_text="Imbriqué 2",
            ),
        ]

        # Apply translations
        self.renderer.apply_translations(ast, units)

        # Verify all units applied
        assert len(self.renderer.applied_units) == 3, "All 3 TextUnits should be applied"

        # Verify parent item structure
        # After re-parse of inline markdown + nested list preservation,
        # parent.children = [inline nodes..., LIST] where inline nodes include
        # TEXT, STRONG, TEXT, EMPHASIS parsed from "Élément avec **gras** et *italique*".
        parent = ast[0].children[0]
        assert len(parent.children) >= 2, "Parent should have inline nodes + nested list"
        assert parent.children[-1].type == NodeType.LIST, "Last child is nested list"

        # Verify nested items
        assert len(parent.children[-1].children) == 2, "Nested list has 2 items"

        # Verify markdown output
        markdown = self.renderer.render_to_markdown(ast)
        assert "gras" in markdown
        assert "italique" in markdown
        assert "Imbriqué 1" in markdown
        assert "Imbriqué 2" in markdown

    def test_empty_nested_list(self):
        """
        Test Case 4: Empty nested list.

        Structure:
        - Parent item
            (empty nested list)

        Verifies:
        - Empty nested LIST preserved in AST
        - No crashes or errors
        - Parent translation still applied
        """
        # Create empty nested list
        empty_nested_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[],
            attrs={"ordered": False},
            node_addr="body.list[0].listitem[0].list[0]",
        )

        # Parent item with empty nested list
        parent_item = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[
                ASTNode(type=NodeType.TEXT, raw="Parent", children=[], attrs={}),
                empty_nested_list,
            ],
            attrs={},
            node_addr="body.list[0].listitem[0]",
        )
        root_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[parent_item],
            attrs={"ordered": False},
            node_addr="body.list[0]",
        )

        ast = [root_list]

        # Create translated TextUnit
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="body.list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Parent",
                translated_text="Parent traduit",
            )
        ]

        # Apply translations
        self.renderer.apply_translations(ast, units)

        # Verify unit applied
        assert len(self.renderer.applied_units) == 1, "1 TextUnit should be applied"

        # Verify structure
        parent = ast[0].children[0]
        assert len(parent.children) == 2, "Parent should have text + empty nested list"
        assert parent.children[0].raw == "Parent traduit", "Parent translated"
        assert parent.children[1].type == NodeType.LIST, "Empty nested list preserved"
        assert len(parent.children[1].children) == 0, "Nested list is empty"

        # Verify markdown renders without crash
        markdown = self.renderer.render_to_markdown(ast)
        assert "Parent traduit" in markdown

    def test_multiple_nested_lists_in_same_parent(self):
        """
        Test Case 5: Multiple nested lists in same parent.

        Structure:
        - Parent item with text
            - First nested list
                - Item A
            - Second nested list
                - Item B

        Verifies:
        - All nested LIST children preserved
        - Order maintained (text, then lists)
        - All translations applied
        """
        # First nested list
        first_nested_item = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Item A", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[0]",
        )
        first_nested_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[first_nested_item],
            attrs={"ordered": False},
            node_addr="body.list[0].listitem[0].list[0]",
        )

        # Second nested list
        second_nested_item = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Item B", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[1].listitem[0]",
        )
        second_nested_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[second_nested_item],
            attrs={"ordered": False},
            node_addr="body.list[0].listitem[0].list[1]",
        )

        # Parent item with both nested lists
        parent_item = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[
                ASTNode(type=NodeType.TEXT, raw="Parent", children=[], attrs={}),
                first_nested_list,
                second_nested_list,
            ],
            attrs={},
            node_addr="body.list[0].listitem[0]",
        )
        root_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[parent_item],
            attrs={"ordered": False},
            node_addr="body.list[0]",
        )

        ast = [root_list]

        # Create translated TextUnits
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="body.list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Parent",
                translated_text="Parent traduit",
            ),
            TextUnit(
                unit_id="u2",
                node_addr="body.list[0].listitem[0].list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Item A",
                translated_text="Élément A",
            ),
            TextUnit(
                unit_id="u3",
                node_addr="body.list[0].listitem[0].list[1].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Item B",
                translated_text="Élément B",
            ),
        ]

        # Apply translations
        self.renderer.apply_translations(ast, units)

        # Verify all units applied
        assert len(self.renderer.applied_units) == 3, "All 3 TextUnits should be applied"

        # Verify structure: text + 2 nested lists
        parent = ast[0].children[0]
        assert len(parent.children) == 3, "Parent should have text + 2 nested lists"
        assert parent.children[0].type == NodeType.TEXT, "First child is text"
        assert parent.children[0].raw == "Parent traduit", "Parent translated"
        assert parent.children[1].type == NodeType.LIST, "Second child is first nested list"
        assert parent.children[2].type == NodeType.LIST, "Third child is second nested list"

        # Verify nested items
        assert parent.children[1].children[0].children[0].raw == "Élément A"
        assert parent.children[2].children[0].children[0].raw == "Élément B"

        # Verify markdown output
        markdown = self.renderer.render_to_markdown(ast)
        assert "Parent traduit" in markdown
        assert "Élément A" in markdown
        assert "Élément B" in markdown

    def test_ordered_nested_lists(self):
        """
        Test Case 6: Ordered nested lists.

        Structure:
        1. First item
            1. Nested ordered item 1
            2. Nested ordered item 2
        2. Second item

        Verifies:
        - Ordered lists work correctly with nesting
        - Numbering preserved
        - All translations applied
        """
        # Nested ordered items
        nested_item_1 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Nested 1", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[0]",
        )
        nested_item_2 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Nested 2", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[0].list[0].listitem[1]",
        )
        nested_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[nested_item_1, nested_item_2],
            attrs={"ordered": True},  # Ordered nested list
            node_addr="body.list[0].listitem[0].list[0]",
        )

        # Parent ordered items
        parent_item_1 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[
                ASTNode(type=NodeType.TEXT, raw="First item", children=[], attrs={}),
                nested_list,
            ],
            attrs={},
            node_addr="body.list[0].listitem[0]",
        )
        parent_item_2 = ASTNode(
            type=NodeType.LIST_ITEM,
            raw="",
            children=[ASTNode(type=NodeType.TEXT, raw="Second item", children=[], attrs={})],
            attrs={},
            node_addr="body.list[0].listitem[1]",
        )
        root_list = ASTNode(
            type=NodeType.LIST,
            raw="",
            children=[parent_item_1, parent_item_2],
            attrs={"ordered": True},  # Ordered parent list
            node_addr="body.list[0]",
        )

        ast = [root_list]

        # Create translated TextUnits
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="body.list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="First item",
                translated_text="Premier élément",
            ),
            TextUnit(
                unit_id="u2",
                node_addr="body.list[0].listitem[0].list[0].listitem[0]",
                kind=TextUnitKind.TEXT,
                source_text="Nested 1",
                translated_text="Imbriqué 1",
            ),
            TextUnit(
                unit_id="u3",
                node_addr="body.list[0].listitem[0].list[0].listitem[1]",
                kind=TextUnitKind.TEXT,
                source_text="Nested 2",
                translated_text="Imbriqué 2",
            ),
            TextUnit(
                unit_id="u4",
                node_addr="body.list[0].listitem[1]",
                kind=TextUnitKind.TEXT,
                source_text="Second item",
                translated_text="Deuxième élément",
            ),
        ]

        # Apply translations
        self.renderer.apply_translations(ast, units)

        # Verify all units applied
        assert len(self.renderer.applied_units) == 4, "All 4 TextUnits should be applied"

        # Verify structure
        parent = ast[0].children[0]
        assert len(parent.children) == 2, "Parent should have text + nested list"
        assert parent.children[1].attrs["ordered"] is True, "Nested list is ordered"

        # Verify markdown output has numbering
        markdown = self.renderer.render_to_markdown(ast)
        assert "1. " in markdown, "Ordered list numbering present"
        assert "Premier élément" in markdown
        assert "Imbriqué 1" in markdown
        assert "Imbriqué 2" in markdown
        assert "Deuxième élément" in markdown
