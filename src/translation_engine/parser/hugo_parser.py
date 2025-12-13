"""
Hugo Markdown Parser - converts Hugo MD files to internal AST representation.

Uses ruamel.yaml for YAML parsing to preserve comments, quote styles, and formatting.
"""
import re
import uuid
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import frontmatter as fm
from markdown_it import MarkdownIt
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .ast_nodes import (
    ASTNode, NodeType, SourceLocation,
    code_block_node, heading_node, link_node,
    list_item_node, list_node, paragraph_node, text_node,
)

# Module-level ruamel.yaml instance for comment/quote preservation
_yaml_parser = YAML()
_yaml_parser.preserve_quotes = True
_yaml_parser.width = 4096  # Prevent line wrapping
_yaml_parser.allow_duplicate_keys = True  # Hugo files may have duplicate keys across sections


class HugoDocument:
    """Internal representation of a parsed Hugo Markdown file."""

    def __init__(
        self,
        frontmatter: Dict[str, Any],
        ast: List[ASTNode],
        source_path: Optional[Path] = None,
        encoding: str = "utf-8",
    ):
        self.frontmatter = frontmatter
        self.ast = ast
        self.source_path = source_path
        self.encoding = encoding

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "frontmatter": self.frontmatter,
            "ast": [node.to_dict() for node in self.ast],
            "source_path": str(self.source_path) if self.source_path else None,
            "encoding": self.encoding,
        }


class HugoParser:
    """Parser for Hugo Markdown files with frontmatter."""

    def __init__(self, enable_tables: bool = True):
        """Initialize the Hugo parser."""
        self.md = MarkdownIt("commonmark")

        if enable_tables:
            self.md.enable("table")

        self._node_counter = 0

    def _generate_node_id(self) -> str:
        """Generate unique node ID."""
        self._node_counter += 1
        return f"node_{self._node_counter}_{uuid.uuid4().hex[:8]}"

    def parse_file(self, path: Path) -> HugoDocument:
        """Parse a Hugo Markdown file."""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            encoding = "utf-8"
        except UnicodeDecodeError:
            with open(path, "r", encoding="latin-1") as f:
                content = f.read()
            encoding = "latin-1"

        doc = self.parse_string(content)
        doc.source_path = path
        doc.encoding = encoding

        return doc

    def parse_string(self, content: str) -> HugoDocument:
        """Parse a Markdown string with frontmatter.

        Uses ruamel.yaml to preserve comments, quote styles, and formatting.
        The frontmatter is returned as a CommentedMap which retains YAML structure.
        """
        # Pre-process: normalize non-breaking spaces to regular spaces for YAML parsing
        # Some Hugo files use NBSP (\xa0) for indentation which YAML parsers don't recognize
        content = content.replace('\xa0', ' ')

        # Use python-frontmatter to split frontmatter from body
        try:
            post = fm.loads(content)
            body_content = post.content

            # Re-parse the YAML using ruamel.yaml to preserve comments/quotes
            # Extract raw YAML from the original content
            frontmatter_dict = self._parse_yaml_with_comments(content)
            if frontmatter_dict is None:
                frontmatter_dict = dict(post.metadata)
        except Exception:
            frontmatter_dict = {}
            body_content = content

        # Parse body to AST
        ast = self._parse_markdown_to_ast(body_content)

        return HugoDocument(frontmatter=frontmatter_dict, ast=ast)

    def _parse_yaml_with_comments(self, content: str) -> Optional[Union[CommentedMap, Dict[str, Any]]]:
        """Extract and parse YAML frontmatter using ruamel.yaml for comment preservation.

        Args:
            content: Full Hugo markdown content with frontmatter

        Returns:
            CommentedMap with preserved comments/quotes, or None if parsing fails
        """
        # Match YAML frontmatter between --- delimiters
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not match:
            return None

        yaml_content = match.group(1)

        try:
            # Use ruamel.yaml to parse - returns CommentedMap preserving structure
            result = _yaml_parser.load(StringIO(yaml_content))
            return result if result is not None else CommentedMap()
        except Exception:
            return None

    def _parse_markdown_to_ast(self, markdown: str) -> List[ASTNode]:
        """Parse Markdown content to AST."""
        tokens = self.md.parse(markdown)
        ast = []

        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Skip closing tokens
            if token.type.endswith("_close"):
                i += 1
                continue

            # Parse based on type
            if token.type == "paragraph_open":
                if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                    children = self._parse_inline_content(tokens[i + 1])
                    ast.append(paragraph_node(children, self._generate_node_id()))
                i += 3  # Skip open, inline, close

            elif token.type == "heading_open":
                level = int(token.tag[1])
                if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                    children = self._parse_inline_content(tokens[i + 1])
                    ast.append(heading_node(level, children, self._generate_node_id()))
                i += 3

            elif token.type == "fence" or token.type == "code_block":
                lang = token.info if hasattr(token, "info") else None
                ast.append(code_block_node(token.content, lang, self._generate_node_id()))
                i += 1

            elif token.type == "hr":
                ast.append(ASTNode(type=NodeType.THEMATIC_BREAK, node_id=self._generate_node_id()))
                i += 1

            elif token.type == "html_block":
                ast.append(ASTNode(type=NodeType.BLOCK_HTML, raw=token.content, node_id=self._generate_node_id()))
                i += 1

            else:
                i += 1

        return ast

    def _parse_inline_content(self, inline_token) -> List[ASTNode]:
        """Parse inline token children to AST nodes."""
        if not inline_token.children:
            return [text_node(inline_token.content, self._generate_node_id())]

        nodes = []
        for child in inline_token.children:
            if child.type == "text":
                nodes.append(text_node(child.content, self._generate_node_id()))
            elif child.type == "code_inline":
                nodes.append(ASTNode(type=NodeType.CODE_SPAN, raw=child.content, node_id=self._generate_node_id()))
            elif child.type == "softbreak":
                nodes.append(ASTNode(type=NodeType.SOFT_BREAK, node_id=self._generate_node_id()))
            elif child.type == "hardbreak":
                nodes.append(ASTNode(type=NodeType.LINE_BREAK, node_id=self._generate_node_id()))
            elif child.type == "html_inline":
                nodes.append(ASTNode(type=NodeType.INLINE_HTML, raw=child.content, node_id=self._generate_node_id()))

        return nodes
