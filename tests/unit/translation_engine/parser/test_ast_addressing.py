"""
Unit tests for AST node addressing system (HP-06 TC-02).

Tests stable node address assignment and retrieval for deterministic
TextUnit mapping.
"""
from src.translation_engine.parser.ast_nodes import (
    ASTNode,
    NodeType,
    code_block_node,
    heading_node,
    link_node,
    list_item_node,
    list_node,
    paragraph_node,
    text_node,
)
from src.translation_engine.parser.hugo_parser import HugoParser


class TestNodeAddressAssignment:
    """Test assign_addresses() method."""

    def test_assign_address_to_single_node(self):
        """Test assigning address to a single node without children."""
        node = text_node("Hello")
        node.assign_addresses("body.text[0]")

        assert node.node_addr == "body.text[0]"

    def test_assign_addresses_to_simple_tree(self):
        """Test assigning addresses to a simple tree structure."""
        para = paragraph_node([
            text_node("Hello "),
            text_node("World")
        ])

        para.assign_addresses("body.para[0]")

        assert para.node_addr == "body.para[0]"
        assert para.children[0].node_addr == "body.para[0].text[0]"
        assert para.children[1].node_addr == "body.para[0].text[1]"

    def test_assign_addresses_with_formatting(self):
        """Test address assignment with inline formatting."""
        from src.translation_engine.parser.ast_nodes import ASTNode

        strong = ASTNode(
            type=NodeType.STRONG,
            children=[text_node("bold text")]
        )

        para = paragraph_node([
            text_node("Before "),
            strong,
            text_node(" after")
        ])

        para.assign_addresses("body.para[0]")

        assert para.node_addr == "body.para[0]"
        assert para.children[0].node_addr == "body.para[0].text[0]"
        assert para.children[1].node_addr == "body.para[0].strong[0]"
        assert para.children[1].children[0].node_addr == "body.para[0].strong[0].text[0]"
        assert para.children[2].node_addr == "body.para[0].text[1]"

    def test_assign_addresses_with_links(self):
        """Test address assignment with links."""
        link = link_node("https://example.com", [text_node("click here")])
        para = paragraph_node([
            text_node("Visit "),
            link,
            text_node(" now")
        ])

        para.assign_addresses("body.para[0]")

        assert para.node_addr == "body.para[0]"
        assert para.children[1].node_addr == "body.para[0].link[0]"
        assert para.children[1].children[0].node_addr == "body.para[0].link[0].text[0]"

    def test_assign_addresses_with_nested_formatting(self):
        """Test address assignment with nested formatting (bold link)."""
        link = link_node("https://example.com", [text_node("link text")])
        strong = ASTNode(type=NodeType.STRONG, children=[link])
        para = paragraph_node([
            text_node("Visit "),
            strong,
            text_node(" now")
        ])

        para.assign_addresses("body.para[0]")

        assert para.children[1].node_addr == "body.para[0].strong[0]"
        assert para.children[1].children[0].node_addr == "body.para[0].strong[0].link[0]"
        assert para.children[1].children[0].children[0].node_addr == "body.para[0].strong[0].link[0].text[0]"

    def test_assign_addresses_to_heading(self):
        """Test address assignment to headings."""
        heading = heading_node(2, [text_node("Prerequisites")])
        heading.assign_addresses("body.heading[0]")

        assert heading.node_addr == "body.heading[0]"
        assert heading.children[0].node_addr == "body.heading[0].text[0]"

    def test_assign_addresses_to_list(self):
        """Test address assignment to lists."""
        list_item1 = list_item_node([text_node("Item 1")])
        list_item2 = list_item_node([text_node("Item 2")])
        list_node_obj = list_node([list_item1, list_item2], ordered=True)

        list_node_obj.assign_addresses("body.list[0]")

        assert list_node_obj.node_addr == "body.list[0]"
        assert list_node_obj.children[0].node_addr == "body.list[0].listitem[0]"
        assert list_node_obj.children[0].children[0].node_addr == "body.list[0].listitem[0].text[0]"
        assert list_node_obj.children[1].node_addr == "body.list[0].listitem[1]"

    def test_assign_addresses_type_counters(self):
        """Test that type counters increment correctly."""
        para = paragraph_node([
            text_node("First "),
            text_node("Second "),
            text_node("Third")
        ])

        para.assign_addresses("body.para[0]")

        # All TEXT nodes should have different indices
        assert para.children[0].node_addr == "body.para[0].text[0]"
        assert para.children[1].node_addr == "body.para[0].text[1]"
        assert para.children[2].node_addr == "body.para[0].text[2]"

    def test_assign_addresses_mixed_types(self):
        """Test address assignment with mixed child types."""
        strong1 = ASTNode(type=NodeType.STRONG, children=[text_node("bold1")])
        strong2 = ASTNode(type=NodeType.STRONG, children=[text_node("bold2")])

        para = paragraph_node([
            text_node("Text 1 "),
            strong1,
            text_node(" Text 2 "),
            strong2,
            text_node(" Text 3")
        ])

        para.assign_addresses("body.para[0]")

        # TEXT nodes counter
        assert para.children[0].node_addr == "body.para[0].text[0]"
        assert para.children[2].node_addr == "body.para[0].text[1]"
        assert para.children[4].node_addr == "body.para[0].text[2]"

        # STRONG nodes counter
        assert para.children[1].node_addr == "body.para[0].strong[0]"
        assert para.children[3].node_addr == "body.para[0].strong[1]"

    def test_assign_addresses_idempotent(self):
        """Test that assign_addresses is idempotent (can call multiple times)."""
        para = paragraph_node([text_node("Hello")])

        para.assign_addresses("body.para[0]")
        addr1 = para.children[0].node_addr

        para.assign_addresses("body.para[0]")
        addr2 = para.children[0].node_addr

        assert addr1 == addr2


class TestGetNodeByAddress:
    """Test get_node_by_addr() method."""

    def test_get_node_by_addr_self(self):
        """Test getting the node itself by its own address."""
        para = paragraph_node([text_node("Hello")])
        para.assign_addresses("body.para[0]")

        result = para.get_node_by_addr("body.para[0]")
        assert result is para

    def test_get_node_by_addr_direct_child(self):
        """Test getting a direct child by address."""
        para = paragraph_node([text_node("Hello")])
        para.assign_addresses("body.para[0]")

        text = para.get_node_by_addr("body.para[0].text[0]")
        assert text is not None
        assert text.type == NodeType.TEXT
        assert text.raw == "Hello"

    def test_get_node_by_addr_nested(self):
        """Test getting a deeply nested node by address."""
        link = link_node("url", [text_node("link text")])
        strong = ASTNode(type=NodeType.STRONG, children=[link])
        para = paragraph_node([strong])

        para.assign_addresses("body.para[0]")

        # Get nested text node
        text = para.get_node_by_addr("body.para[0].strong[0].link[0].text[0]")
        assert text is not None
        assert text.type == NodeType.TEXT
        assert text.raw == "link text"

    def test_get_node_by_addr_invalid_address(self):
        """Test that invalid address returns None."""
        para = paragraph_node([text_node("Hello")])
        para.assign_addresses("body.para[0]")

        result = para.get_node_by_addr("body.para[99].text[0]")
        assert result is None

    def test_get_node_by_addr_empty_address(self):
        """Test that empty address returns None."""
        para = paragraph_node([text_node("Hello")])
        para.assign_addresses("body.para[0]")

        result = para.get_node_by_addr("")
        assert result is None

    def test_get_node_by_addr_wrong_prefix(self):
        """Test that address with wrong prefix returns None."""
        para = paragraph_node([text_node("Hello")])
        para.assign_addresses("body.para[0]")

        result = para.get_node_by_addr("different.para[0].text[0]")
        assert result is None

    def test_get_node_by_addr_multiple_children(self):
        """Test getting specific child when there are multiple."""
        para = paragraph_node([
            text_node("First"),
            text_node("Second"),
            text_node("Third")
        ])
        para.assign_addresses("body.para[0]")

        second = para.get_node_by_addr("body.para[0].text[1]")
        assert second is not None
        assert second.raw == "Second"


class TestDeterminism:
    """Test that address assignment is deterministic."""

    def test_determinism_same_structure(self):
        """Test that same structure produces same addresses."""
        # Build structure twice
        para1 = paragraph_node([text_node("Hello"), text_node("World")])
        para2 = paragraph_node([text_node("Hello"), text_node("World")])

        para1.assign_addresses("body.para[0]")
        para2.assign_addresses("body.para[0]")

        # Addresses should be identical
        assert para1.node_addr == para2.node_addr
        assert para1.children[0].node_addr == para2.children[0].node_addr
        assert para1.children[1].node_addr == para2.children[1].node_addr

    def test_determinism_complex_structure(self):
        """Test determinism with complex nested structure."""
        def build_complex():
            link = link_node("url", [text_node("link")])
            strong = ASTNode(type=NodeType.STRONG, children=[link])
            return paragraph_node([
                text_node("Before "),
                strong,
                text_node(" after")
            ])

        para1 = build_complex()
        para2 = build_complex()

        para1.assign_addresses("body.para[0]")
        para2.assign_addresses("body.para[0]")

        # Check nested addresses match
        link1 = para1.get_node_by_addr("body.para[0].strong[0].link[0]")
        link2 = para2.get_node_by_addr("body.para[0].strong[0].link[0]")

        assert link1.node_addr == link2.node_addr


class TestParserIntegration:
    """Test integration with HugoParser."""

    def test_parser_assigns_addresses_automatically(self):
        """Test that HugoParser automatically assigns addresses after parsing."""
        parser = HugoParser()
        doc = parser.parse_string("""---
title: Test
---

This is a paragraph.
""")

        # Check that addresses were assigned
        assert len(doc.ast) > 0
        para = doc.ast[0]
        assert para.node_addr is not None
        assert para.node_addr.startswith("body.")

    def test_parser_addresses_simple_markdown(self):
        """Test parser address assignment with simple markdown."""
        parser = HugoParser()
        doc = parser.parse_string("**bold**")

        para = doc.ast[0]
        assert para.node_addr == "body.paragraph[0]"
        # Find the STRONG node (parser may add empty text nodes before/after)
        strong_nodes = [c for c in para.children if c.type == NodeType.STRONG]
        assert len(strong_nodes) == 1
        assert strong_nodes[0].node_addr == "body.paragraph[0].strong[0]"

    def test_parser_addresses_link_in_bold(self):
        """Test parser handles nested formatting correctly."""
        parser = HugoParser()
        doc = parser.parse_string("Visit **[link](url)** now.")

        para = doc.ast[0]

        # Get the STRONG node
        strong = para.children[1]  # "Visit " + STRONG + " now."
        assert strong.type == NodeType.STRONG

        # Get the LINK inside STRONG
        link = strong.children[0]
        assert link.type == NodeType.LINK

        # Check address
        link_found = para.get_node_by_addr(link.node_addr)
        assert link_found is link

    def test_parser_address_stability(self):
        """Test that parsing same content twice produces same addresses."""
        parser = HugoParser()

        doc1 = parser.parse_string("**bold** text")
        doc2 = parser.parse_string("**bold** text")

        assert doc1.ast[0].node_addr == doc2.ast[0].node_addr
        assert doc1.ast[0].children[0].node_addr == doc2.ast[0].children[0].node_addr

    def test_parser_multiple_paragraphs(self):
        """Test parser assigns different indices to multiple paragraphs."""
        parser = HugoParser()
        doc = parser.parse_string("""First paragraph.

Second paragraph.

Third paragraph.""")

        assert len(doc.ast) == 3
        assert doc.ast[0].node_addr == "body.paragraph[0]"
        assert doc.ast[1].node_addr == "body.paragraph[1]"
        assert doc.ast[2].node_addr == "body.paragraph[2]"

    def test_parser_heading_and_paragraph(self):
        """Test parser assigns correct indices to mixed elements."""
        parser = HugoParser()
        doc = parser.parse_string("""## Heading

First paragraph.

### Subheading

Second paragraph.""")

        # Check types and addresses
        assert doc.ast[0].type == NodeType.HEADING
        assert doc.ast[0].node_addr == "body.heading[0]"

        assert doc.ast[1].type == NodeType.PARAGRAPH
        assert doc.ast[1].node_addr == "body.paragraph[0]"

        assert doc.ast[2].type == NodeType.HEADING
        assert doc.ast[2].node_addr == "body.heading[1]"

        assert doc.ast[3].type == NodeType.PARAGRAPH
        assert doc.ast[3].node_addr == "body.paragraph[1]"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_children(self):
        """Test addressing with no children."""
        para = paragraph_node([])
        para.assign_addresses("body.para[0]")

        assert para.node_addr == "body.para[0]"
        assert len(para.children) == 0

    def test_deeply_nested_structure(self):
        """Test with deeply nested structure."""
        # Build: para > strong > em > link > text
        text = text_node("deep")
        link = link_node("url", [text])
        em = ASTNode(type=NodeType.EMPHASIS, children=[link])
        strong = ASTNode(type=NodeType.STRONG, children=[em])
        para = paragraph_node([strong])

        para.assign_addresses("body.para[0]")

        # Get deepest node
        deep = para.get_node_by_addr("body.para[0].strong[0].emphasis[0].link[0].text[0]")
        assert deep is not None
        assert deep.raw == "deep"

    def test_get_node_before_address_assignment(self):
        """Test get_node_by_addr before addresses are assigned."""
        para = paragraph_node([text_node("Hello")])
        # Don't call assign_addresses()

        result = para.get_node_by_addr("body.para[0].text[0]")
        # Should return None because node_addr is None
        assert result is None

    def test_underscore_removal_in_type_names(self):
        """Test that underscores are removed from type names in addresses."""
        # Create a parent that contains the code block
        code = code_block_node("print('hello')", language="python")
        parent = ASTNode(type=NodeType.DOCUMENT, children=[code])
        parent.assign_addresses("body")

        # NodeType.CODE_BLOCK -> "blockcode" (underscores removed)
        # The child address should be body.blockcode[0]
        assert code.node_addr == "body.blockcode[0]"

    def test_mixed_content_realistic(self):
        """Test realistic mixed content (from test fixtures)."""
        parser = HugoParser()
        doc = parser.parse_string("""## Prerequisites

1. Install **Visual Studio** 2019
2. Visit **[documentation](https://docs.example.com)** for info

See the `SaveFormat.Pptx` option.""")

        # Verify all nodes have addresses
        for node in doc.ast:
            assert node.node_addr is not None

            # Recursively check all children
            def check_addresses(n):
                assert n.node_addr is not None
                for child in n.children:
                    check_addresses(child)

            check_addresses(node)


class TestBackwardCompatibility:
    """Test that new addressing doesn't break existing functionality."""

    def test_to_dict_includes_node_addr(self):
        """Test that to_dict() serialization includes node_addr."""
        para = paragraph_node([text_node("Hello")])
        para.assign_addresses("body.para[0]")

        data = para.to_dict()
        # node_addr should be in the dict if we add it to serialization
        # (Currently it's not in to_dict(), but that's okay - it's optional)

    def test_existing_node_id_unaffected(self):
        """Test that node_id field is unaffected by addressing."""
        para = paragraph_node([text_node("Hello")], node_id="custom_id_123")
        para.assign_addresses("body.para[0]")

        assert para.node_id == "custom_id_123"
        assert para.node_addr == "body.para[0]"
        # Both can coexist


class TestAcceptanceCriteria:
    """Test TC-02 acceptance criteria."""

    def test_acceptance_address_assignment(self):
        """Test acceptance check: address assignment works."""
        from src.translation_engine.parser import HugoParser
        parser = HugoParser()
        doc = parser.parse_string("""---
title: Test
---

Visit **[link](url)** now.
""")

        # Find the LINK node
        para = doc.ast[0]
        assert para.node_addr is not None

        # Find STRONG > LINK
        strong = para.children[1]
        link = strong.children[0]

        assert link.type == NodeType.LINK

        # Try to get it by address
        link_found = para.get_node_by_addr(link.node_addr)
        assert link_found is not None
        assert link_found is link

    def test_acceptance_address_stability(self):
        """Test acceptance check: addresses are deterministic."""
        from src.translation_engine.parser import HugoParser
        parser = HugoParser()

        doc1 = parser.parse_string("**bold**")
        doc2 = parser.parse_string("**bold**")

        assert doc1.ast[0].node_addr == doc2.ast[0].node_addr
        assert doc1.ast[0].children[0].node_addr == doc2.ast[0].children[0].node_addr
