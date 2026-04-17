"""
AST Node definitions for Hugo Markdown parsing.

Defines the structure for representing parsed Markdown content.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class NodeType(str, Enum):
    """Types of AST nodes."""
    # Document structure
    DOCUMENT = "document"
    PARAGRAPH = "paragraph"

    # Block elements
    HEADING = "heading"
    LIST = "list"
    LIST_ITEM = "list_item"
    BLOCKQUOTE = "blockquote"
    CODE_BLOCK = "block_code"
    TABLE = "table"
    TABLE_ROW = "table_row"
    TABLE_CELL = "table_cell"
    THEMATIC_BREAK = "thematic_break"
    BLOCK_HTML = "block_html"

    # Inline elements
    TEXT = "text"
    STRONG = "strong"
    EMPHASIS = "emphasis"
    CODE_SPAN = "codespan"
    LINK = "link"
    IMAGE = "image"
    INLINE_HTML = "inline_html"
    LINE_BREAK = "linebreak"
    SOFT_BREAK = "softbreak"


@dataclass
class SourceLocation:
    """Track source location for reconstruction."""
    line: int
    column: int
    offset: int = 0


@dataclass
class ASTNode:
    """Base class for all AST nodes."""
    type: NodeType
    children: list["ASTNode"] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)
    raw: str | None = None
    location: SourceLocation | None = None
    node_id: str | None = None
    node_addr: str | None = None  # AST Translation: Stable node address for deterministic translation

    def to_dict(self) -> dict[str, Any]:
        """Convert node to dictionary representation."""
        result = {"type": self.type.value}

        if self.children:
            result["children"] = [child.to_dict() for child in self.children]

        if self.attrs:
            result["attrs"] = self.attrs

        if self.raw is not None:
            result["raw"] = self.raw

        if self.node_id:
            result["id"] = self.node_id

        if self.location:
            result["location"] = {
                "line": self.location.line,
                "column": self.location.column,
            }

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ASTNode":
        """Create node from dictionary."""
        node = cls(
            type=NodeType(data["type"]),
            attrs=data.get("attrs", {}),
            raw=data.get("raw"),
            node_id=data.get("id"),
        )

        if "children" in data:
            node.children = [cls.from_dict(child) for child in data["children"]]

        if "location" in data:
            node.location = SourceLocation(
                line=data["location"]["line"],
                column=data["location"]["column"],
            )

        return node

    def assign_addresses(self, prefix: str = "body") -> None:
        """
        Recursively assign stable node addresses to this node and all descendants.

        Address format: hierarchical dot notation with type and index.
        Example: "body.para[2].strong[0].text[1]"

        This method is idempotent - calling it multiple times produces the same addresses.

        Args:
            prefix: Address prefix for this node (default: "body" for top-level)

        Example:
            >>> para = paragraph_node([text_node("Hello")])
            >>> para.assign_addresses()
            >>> assert para.node_addr == "body.para[0]"
            >>> assert para.children[0].node_addr == "body.para[0].text[0]"
        """
        # Assign address to this node
        self.node_addr = prefix

        # Group children by type to assign indices
        type_counters: dict[str, int] = {}

        for child in self.children:
            # Get type name (lowercase, remove underscores)
            type_name = child.type.value.replace('_', '')

            # Get index for this type
            idx = type_counters.get(type_name, 0)
            type_counters[type_name] = idx + 1

            # Build child address
            child_addr = f"{prefix}.{type_name}[{idx}]"

            # Recursively assign to child
            child.assign_addresses(child_addr)

    def get_node_by_addr(self, addr: str) -> Optional["ASTNode"]:
        """
        Get descendant node by address.

        Args:
            addr: Node address in dot notation (e.g., "body.para[2].text[0]")

        Returns:
            ASTNode if found, None if address is invalid or not found

        Example:
            >>> doc = paragraph_node([text_node("Hello")])
            >>> doc.assign_addresses()
            >>> text = doc.get_node_by_addr("body.para[0].text[0]")
            >>> assert text is not None
            >>> assert text.type == NodeType.TEXT
        """
        if not addr:
            return None

        # If this is the target address, return self
        if self.node_addr == addr:
            return self

        # If addr doesn't start with this node's address, it's not a descendant
        if not self.node_addr or not addr.startswith(self.node_addr + "."):
            return None

        # Parse the next component after this node's address
        # Example: if self.node_addr = "body.para[0]" and addr = "body.para[0].text[1]"
        # then we need to find child with addr starting with "body.para[0].text[1]"

        # Search children recursively
        for child in self.children:
            result = child.get_node_by_addr(addr)
            if result is not None:
                return result

        # Not found in any child
        return None


# Convenience constructors for common node types

def text_node(content: str, node_id: str | None = None) -> ASTNode:
    """Create a text node."""
    return ASTNode(type=NodeType.TEXT, raw=content, node_id=node_id)


def paragraph_node(children: list[ASTNode], node_id: str | None = None) -> ASTNode:
    """Create a paragraph node."""
    return ASTNode(type=NodeType.PARAGRAPH, children=children, node_id=node_id)


def heading_node(level: int, children: list[ASTNode], node_id: str | None = None) -> ASTNode:
    """Create a heading node."""
    return ASTNode(
        type=NodeType.HEADING,
        children=children,
        attrs={"level": level},
        node_id=node_id
    )


def link_node(url: str, children: list[ASTNode], title: str | None = None, node_id: str | None = None) -> ASTNode:
    """Create a link node."""
    attrs = {"url": url}
    if title:
        attrs["title"] = title
    return ASTNode(type=NodeType.LINK, children=children, attrs=attrs, node_id=node_id)


def code_block_node(code: str, language: str | None = None, node_id: str | None = None) -> ASTNode:
    """Create a code block node."""
    attrs = {}
    if language:
        attrs["lang"] = language
    return ASTNode(type=NodeType.CODE_BLOCK, raw=code, attrs=attrs, node_id=node_id)


def list_node(items: list[ASTNode], ordered: bool = False, node_id: str | None = None) -> ASTNode:
    """Create a list node."""
    return ASTNode(
        type=NodeType.LIST,
        children=items,
        attrs={"ordered": ordered},
        node_id=node_id
    )


def list_item_node(children: list[ASTNode], node_id: str | None = None) -> ASTNode:
    """Create a list item node."""
    return ASTNode(type=NodeType.LIST_ITEM, children=children, node_id=node_id)


def code_span_node(code: str, node_id: str | None = None) -> ASTNode:
    """Create an inline code span node."""
    return ASTNode(type=NodeType.CODE_SPAN, raw=code, node_id=node_id)
