"""
AST Node definitions for Hugo Markdown parsing.

Defines the structure for representing parsed Markdown content.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
    children: List["ASTNode"] = field(default_factory=list)
    attrs: Dict[str, Any] = field(default_factory=dict)
    raw: Optional[str] = None
    location: Optional[SourceLocation] = None
    node_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
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
    def from_dict(cls, data: Dict[str, Any]) -> "ASTNode":
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


# Convenience constructors for common node types

def text_node(content: str, node_id: Optional[str] = None) -> ASTNode:
    """Create a text node."""
    return ASTNode(type=NodeType.TEXT, raw=content, node_id=node_id)


def paragraph_node(children: List[ASTNode], node_id: Optional[str] = None) -> ASTNode:
    """Create a paragraph node."""
    return ASTNode(type=NodeType.PARAGRAPH, children=children, node_id=node_id)


def heading_node(level: int, children: List[ASTNode], node_id: Optional[str] = None) -> ASTNode:
    """Create a heading node."""
    return ASTNode(
        type=NodeType.HEADING,
        children=children,
        attrs={"level": level},
        node_id=node_id
    )


def link_node(url: str, children: List[ASTNode], title: Optional[str] = None, node_id: Optional[str] = None) -> ASTNode:
    """Create a link node."""
    attrs = {"url": url}
    if title:
        attrs["title"] = title
    return ASTNode(type=NodeType.LINK, children=children, attrs=attrs, node_id=node_id)


def code_block_node(code: str, language: Optional[str] = None, node_id: Optional[str] = None) -> ASTNode:
    """Create a code block node."""
    attrs = {}
    if language:
        attrs["lang"] = language
    return ASTNode(type=NodeType.CODE_BLOCK, raw=code, attrs=attrs, node_id=node_id)


def list_node(items: List[ASTNode], ordered: bool = False, node_id: Optional[str] = None) -> ASTNode:
    """Create a list node."""
    return ASTNode(
        type=NodeType.LIST,
        children=items,
        attrs={"ordered": ordered},
        node_id=node_id
    )


def list_item_node(children: List[ASTNode], node_id: Optional[str] = None) -> ASTNode:
    """Create a list item node."""
    return ASTNode(type=NodeType.LIST_ITEM, children=children, node_id=node_id)
