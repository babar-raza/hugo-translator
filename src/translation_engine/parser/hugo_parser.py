"""
Hugo Markdown Parser - converts Hugo MD files to internal AST representation.

Uses ruamel.yaml for YAML parsing to preserve comments, quote styles, and formatting.
"""
import logging
import re
import uuid
from io import StringIO
from pathlib import Path
from typing import Any

import frontmatter as fm
from markdown_it import MarkdownIt
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

logger = logging.getLogger(__name__)

from .ast_nodes import (
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

# Module-level ruamel.yaml instance for comment/quote preservation
_yaml_parser = YAML()

# Pattern to detect and split Hugo shortcodes from surrounding text.
# Matches {{< ... >}} (regular) and {{% ... %}} (markdown) shortcode forms.
_SHORTCODE_RE = re.compile(r'({{[<%].*?[>%]}})', re.DOTALL)
_yaml_parser.preserve_quotes = True
_yaml_parser.width = 4096  # Prevent line wrapping
_yaml_parser.allow_duplicate_keys = True  # Hugo files may have duplicate keys across sections


def normalize_table_cells(text: str) -> str:
    """Merge multi-line table cell openers into single-line rows.

    Some Hugo source files (API reference) use multi-line cells where a row
    opener starts with | but doesn't end with |, and continuation lines follow::

        | `normalTexture` | `TextureBase` | Read | Gets the texture
         @return the texture
         / |

    markdown-it treats each physical line as a separate TABLE_ROW.  This
    pre-processor merges continuation lines into the preceding opener row so
    the resulting text has only complete single-line ``|…|`` rows.

    INVARIANT: Complete single-line rows (starting AND ending with ``|``) are unchanged.
    INVARIANT: Lines outside table blocks are unchanged.
    INVARIANT: Content inside fenced code blocks (`````) is passed through untouched.

    This function is called by ``HugoParser._normalize_table_cells()`` and may also
    be imported by write_gate.py and surgical_retranslate.py for consistent counting.
    """
    lines = text.splitlines(keepends=True)
    result = []
    in_code_block = False
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.rstrip("\n\r")

        if stripped.lstrip().startswith("```"):
            in_code_block = not in_code_block
            result.append(raw)
            i += 1
            continue

        if in_code_block:
            result.append(raw)
            i += 1
            continue

        if (
            stripped.startswith("|")
            and stripped.count("|") >= 2
            and not stripped.endswith("|")
        ):
            merged = stripped
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].rstrip("\n\r").strip()
                if not next_stripped or next_stripped.startswith("|") or next_stripped.startswith("#"):
                    break
                merged += " " + next_stripped
                j += 1
            if not merged.endswith("|"):
                merged += " |"
            result.append(merged + "\n")
            i = j
        else:
            result.append(raw)
            i += 1

    return "".join(result)


class HugoDocument:
    """Internal representation of a parsed Hugo Markdown file."""

    def __init__(
        self,
        frontmatter: dict[str, Any],
        ast: list[ASTNode],
        source_path: Path | None = None,
        encoding: str = "utf-8",
    ):
        self.frontmatter = frontmatter
        self.ast = ast
        self.source_path = source_path
        self.encoding = encoding

    def to_dict(self) -> dict[str, Any]:
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
            with open(path, encoding="utf-8") as f:
                content = f.read()
            encoding = "utf-8"
        except UnicodeDecodeError:
            with open(path, encoding="latin-1") as f:
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

        # Split frontmatter ourselves before using python-frontmatter. Some Hugo pages
        # have a top-level YAML key named "content", which collides with
        # python-frontmatter's Post(content, **metadata) constructor path.
        frontmatter_split = self._split_frontmatter(content)
        if frontmatter_split is not None:
            yaml_content, body_content = frontmatter_split
            frontmatter_dict = self._parse_yaml_content(yaml_content)
            if frontmatter_dict is None:
                logger.warning(
                    "YAML_FORMAT_FALLBACK: ruamel.yaml failed to parse frontmatter; "
                    "using empty frontmatter to avoid treating YAML as Markdown body."
                )
                frontmatter_dict = CommentedMap()
        else:
            # Backward-compatible fallback for documents without standard Hugo delimiters.
            try:
                post = fm.loads(content)
                body_content = post.content
                frontmatter_dict = dict(post.metadata)
            except Exception:
                frontmatter_dict = {}
                body_content = content

        # Parse body to AST
        ast = self._parse_markdown_to_ast(body_content)

        # AST Translation: Assign stable node addresses to AST for deterministic translation
        # Use per-type counters for addresses like "body.heading[0]", "body.paragraph[0]", etc.
        type_counters: dict[str, int] = {}
        for node in ast:
            type_name = node.type.value.replace('_', '')
            idx = type_counters.get(type_name, 0)
            type_counters[type_name] = idx + 1
            node.assign_addresses(f"body.{type_name}[{idx}]")

        return HugoDocument(frontmatter=frontmatter_dict, ast=ast)

    def _split_frontmatter(self, content: str) -> tuple[str, str] | None:
        """Split standard Hugo YAML frontmatter from body content."""
        match = re.match(
            r'^\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)',
            content,
            re.DOTALL,
        )
        if not match:
            return None
        return match.group(1), content[match.end():]

    def _parse_yaml_content(self, yaml_content: str) -> CommentedMap | dict[str, Any] | None:
        """Parse a YAML frontmatter payload using ruamel.yaml."""
        try:
            result = _yaml_parser.load(StringIO(yaml_content))
            return result if result is not None else CommentedMap()
        except Exception:
            return None

    def _parse_yaml_with_comments(self, content: str) -> CommentedMap | dict[str, Any] | None:
        """Extract and parse YAML frontmatter using ruamel.yaml for comment preservation.

        Args:
            content: Full Hugo markdown content with frontmatter

        Returns:
            CommentedMap with preserved comments/quotes, or None if parsing fails
        """
        frontmatter_split = self._split_frontmatter(content)
        if frontmatter_split is None:
            return None

        yaml_content, _body_content = frontmatter_split
        return self._parse_yaml_content(yaml_content)

    def _normalize_table_cells(self, text: str) -> str:
        """Delegate to module-level normalize_table_cells()."""
        return normalize_table_cells(text)

    def _parse_markdown_to_ast(self, markdown: str) -> list[ASTNode]:
        """Parse Markdown content to AST."""
        markdown = self._normalize_table_cells(markdown)
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

            elif token.type == "blockquote_open":
                node, i = self._parse_blockquote(tokens, i)
                ast.append(node)

            elif token.type == "bullet_list_open":
                node, i = self._parse_list(tokens, i, ordered=False)
                ast.append(node)

            elif token.type == "ordered_list_open":
                node, i = self._parse_list(tokens, i, ordered=True)
                ast.append(node)

            elif token.type == "table_open":
                node, i = self._parse_table(tokens, i)
                ast.append(node)

            else:
                i += 1

        return ast

    def _parse_inline_content(self, inline_token) -> list[ASTNode]:
        """Parse inline token children to AST nodes with proper nesting."""
        if not inline_token.children:
            return [text_node(inline_token.content, self._generate_node_id())]

        return self._parse_inline_tokens(inline_token.children, 0, None)[0]

    def _parse_inline_tokens(
        self, tokens: list, start: int, close_type: str | None
    ) -> tuple[list[ASTNode], int]:
        """
        Parse inline tokens with support for nested elements.

        Args:
            tokens: List of inline tokens
            start: Starting index
            close_type: Token type that closes current element (None for top-level)

        Returns:
            Tuple of (nodes, end_index)
        """
        nodes = []
        i = start

        while i < len(tokens):
            token = tokens[i]

            # Check for closing token
            if close_type and token.type == close_type:
                return nodes, i

            if token.type == "text":
                # Split shortcodes out of plain text tokens into INLINE_HTML nodes
                nodes.extend(self._split_shortcodes(token.content))
                i += 1

            elif token.type == "link_open":
                href = self._get_attr(token, "href", "")
                title = self._get_attr(token, "title")
                children, i = self._parse_inline_tokens(tokens, i + 1, "link_close")
                nodes.append(link_node(href, children, title, self._generate_node_id()))
                i += 1  # Skip link_close

            elif token.type == "strong_open":
                children, i = self._parse_inline_tokens(tokens, i + 1, "strong_close")
                nodes.append(ASTNode(
                    type=NodeType.STRONG,
                    children=children,
                    node_id=self._generate_node_id()
                ))
                i += 1  # Skip strong_close

            elif token.type == "em_open":
                children, i = self._parse_inline_tokens(tokens, i + 1, "em_close")
                nodes.append(ASTNode(
                    type=NodeType.EMPHASIS,
                    children=children,
                    node_id=self._generate_node_id()
                ))
                i += 1  # Skip em_close

            elif token.type == "image":
                src = self._get_attr(token, "src", "")
                alt = token.content or ""
                title = self._get_attr(token, "title")
                attrs = {"src": src, "alt": alt}
                if title:
                    attrs["title"] = title
                nodes.append(ASTNode(
                    type=NodeType.IMAGE,
                    attrs=attrs,
                    node_id=self._generate_node_id()
                ))
                i += 1

            elif token.type == "code_inline":
                nodes.append(ASTNode(
                    type=NodeType.CODE_SPAN,
                    raw=token.content,
                    node_id=self._generate_node_id()
                ))
                i += 1

            elif token.type == "softbreak":
                nodes.append(ASTNode(type=NodeType.SOFT_BREAK, node_id=self._generate_node_id()))
                i += 1

            elif token.type == "hardbreak":
                nodes.append(ASTNode(type=NodeType.LINE_BREAK, node_id=self._generate_node_id()))
                i += 1

            elif token.type == "html_inline":
                nodes.append(ASTNode(
                    type=NodeType.INLINE_HTML,
                    raw=token.content,
                    node_id=self._generate_node_id()
                ))
                i += 1

            else:
                # Unknown token - skip
                i += 1

        return nodes, i

    def _split_shortcodes(self, text: str) -> list[ASTNode]:
        """Split a text string into TEXT and INLINE_HTML nodes at Hugo shortcode boundaries."""
        if "{{" not in text:
            return [text_node(text, self._generate_node_id())]
        nodes = []
        for part in _SHORTCODE_RE.split(text):
            if not part:
                continue
            if _SHORTCODE_RE.fullmatch(part):
                nodes.append(ASTNode(
                    type=NodeType.INLINE_HTML,
                    raw=part,
                    node_id=self._generate_node_id()
                ))
            else:
                nodes.append(text_node(part, self._generate_node_id()))
        return nodes

    def _get_attr(self, token, name: str, default=None):
        """Get attribute from token safely."""
        if hasattr(token, 'attrs') and token.attrs:
            if isinstance(token.attrs, dict):
                return token.attrs.get(name, default)
            # markdown_it uses list of tuples
            for key, val in token.attrs:
                if key == name:
                    return val
        return default

    def _parse_list(self, tokens: list, start_idx: int, ordered: bool) -> tuple[ASTNode, int]:
        """Parse a list from tokens.

        Args:
            tokens: Full token list
            start_idx: Index of *_list_open token
            ordered: Whether this is an ordered list

        Returns:
            Tuple of (list_node, end_index)
        """
        items = []
        i = start_idx + 1  # Skip the open token
        close_type = "ordered_list_close" if ordered else "bullet_list_close"

        # Get start number for ordered lists
        start_num = 1
        if ordered and hasattr(tokens[start_idx], 'attrs'):
            attrs = tokens[start_idx].attrs or {}
            if isinstance(attrs, dict):
                start_num = attrs.get('start', 1)
            elif isinstance(attrs, list):
                # markdown_it uses list of tuples for attrs
                for key, val in attrs:
                    if key == 'start':
                        start_num = int(val)
                        break

        while i < len(tokens):
            token = tokens[i]

            if token.type == close_type:
                break

            if token.type == "list_item_open":
                item_node, i = self._parse_list_item(tokens, i)
                if item_node:
                    items.append(item_node)
            else:
                i += 1

        list_attrs = {"ordered": ordered}
        if ordered and start_num != 1:
            list_attrs["start"] = start_num

        return list_node(items, ordered=ordered, node_id=self._generate_node_id()), i + 1

    def _parse_blockquote(self, tokens: list, start_idx: int) -> tuple[ASTNode, int]:
        """Parse a blockquote from tokens.

        markdown-it emits blockquote_open / [inner content]* / blockquote_close sequences.
        Inner content can be paragraphs, nested blockquotes, code blocks, or lists.

        Args:
            tokens: Full token list
            start_idx: Index of blockquote_open token

        Returns:
            Tuple of (blockquote ASTNode, end_index after blockquote_close)
        """
        children = []
        i = start_idx + 1  # Skip blockquote_open

        while i < len(tokens):
            token = tokens[i]

            if token.type == "blockquote_close":
                i += 1
                break

            # Paragraph inside blockquote
            if token.type == "paragraph_open":
                if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                    inline_children = self._parse_inline_content(tokens[i + 1])
                    children.append(paragraph_node(inline_children, self._generate_node_id()))
                i += 3  # Skip open, inline, close

            # Nested blockquote (recursive)
            elif token.type == "blockquote_open":
                nested, i = self._parse_blockquote(tokens, i)
                children.append(nested)

            # Code block inside blockquote
            elif token.type in ("fence", "code_block"):
                lang = token.info if hasattr(token, "info") else None
                children.append(code_block_node(token.content, lang, self._generate_node_id()))
                i += 1

            # List inside blockquote
            elif token.type == "bullet_list_open":
                nested_list, i = self._parse_list(tokens, i, ordered=False)
                children.append(nested_list)

            elif token.type == "ordered_list_open":
                nested_list, i = self._parse_list(tokens, i, ordered=True)
                children.append(nested_list)

            else:
                i += 1

        return ASTNode(
            type=NodeType.BLOCKQUOTE,
            children=children,
            node_id=self._generate_node_id(),
        ), i

    def _parse_list_item(self, tokens: list, start_idx: int) -> tuple[ASTNode | None, int]:
        """Parse a list item from tokens.

        Args:
            tokens: Full token list
            start_idx: Index of list_item_open token

        Returns:
            Tuple of (list_item_node, end_index)
        """
        children = []
        i = start_idx + 1  # Skip list_item_open

        while i < len(tokens):
            token = tokens[i]

            if token.type == "list_item_close":
                break

            # Handle nested paragraph
            if token.type == "paragraph_open":
                if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                    inline_children = self._parse_inline_content(tokens[i + 1])
                    children.extend(inline_children)
                i += 3  # Skip open, inline, close

            # Handle nested list
            elif token.type in ("bullet_list_open", "ordered_list_open"):
                is_ordered = token.type == "ordered_list_open"
                nested_list, i = self._parse_list(tokens, i, ordered=is_ordered)
                children.append(nested_list)

            # Handle fenced/indented code block inside list item (Bug 1)
            elif token.type in ("fence", "code_block"):
                lang = token.info if hasattr(token, "info") else None
                children.append(code_block_node(token.content, lang, self._generate_node_id()))
                i += 1

            else:
                i += 1

        return list_item_node(children, node_id=self._generate_node_id()), i + 1

    def _parse_table(self, tokens: list, start_idx: int) -> tuple[ASTNode, int]:
        """Parse a table from tokens.

        Args:
            tokens: Full token list
            start_idx: Index of table_open token

        Returns:
            Tuple of (table_node, end_index)
        """
        rows = []
        i = start_idx + 1  # Skip table_open

        while i < len(tokens):
            token = tokens[i]

            if token.type == "table_close":
                break

            # Parse thead section
            if token.type == "thead_open":
                i += 1  # Skip thead_open
                while i < len(tokens) and tokens[i].type != "thead_close":
                    if tokens[i].type == "tr_open":
                        row_node, i = self._parse_table_row(tokens, i, is_header=True)
                        if row_node:
                            rows.append(row_node)
                    else:
                        i += 1
                i += 1  # Skip thead_close

            # Parse tbody section
            elif token.type == "tbody_open":
                i += 1  # Skip tbody_open
                while i < len(tokens) and tokens[i].type != "tbody_close":
                    if tokens[i].type == "tr_open":
                        row_node, i = self._parse_table_row(tokens, i, is_header=False)
                        if row_node:
                            rows.append(row_node)
                    else:
                        i += 1
                i += 1  # Skip tbody_close

            else:
                i += 1

        return ASTNode(type=NodeType.TABLE, children=rows, node_id=self._generate_node_id()), i + 1

    def _parse_table_row(self, tokens: list, start_idx: int, is_header: bool) -> tuple[ASTNode | None, int]:
        """Parse a table row from tokens.

        Args:
            tokens: Full token list
            start_idx: Index of tr_open token
            is_header: Whether this is a header row

        Returns:
            Tuple of (table_row_node, end_index)
        """
        cells = []
        i = start_idx + 1  # Skip tr_open

        while i < len(tokens):
            token = tokens[i]

            if token.type == "tr_close":
                break

            # Parse header cells (th)
            if token.type == "th_open":
                cell_node, i = self._parse_table_cell(tokens, i, is_header=True)
                if cell_node:
                    cells.append(cell_node)

            # Parse data cells (td)
            elif token.type == "td_open":
                cell_node, i = self._parse_table_cell(tokens, i, is_header=False)
                if cell_node:
                    cells.append(cell_node)

            else:
                i += 1

        attrs = {"is_header": is_header}
        return ASTNode(type=NodeType.TABLE_ROW, children=cells, attrs=attrs, node_id=self._generate_node_id()), i + 1

    def _parse_table_cell(self, tokens: list, start_idx: int, is_header: bool) -> tuple[ASTNode | None, int]:
        """Parse a table cell from tokens.

        Args:
            tokens: Full token list
            start_idx: Index of th_open or td_open token
            is_header: Whether this is a header cell

        Returns:
            Tuple of (table_cell_node, end_index)
        """
        children = []
        i = start_idx + 1  # Skip th_open/td_open
        close_type = "th_close" if is_header else "td_close"

        # Get alignment if present
        align = None
        start_token = tokens[start_idx]
        if hasattr(start_token, 'attrs') and start_token.attrs:
            if isinstance(start_token.attrs, dict):
                align = start_token.attrs.get('style')
            elif isinstance(start_token.attrs, list):
                for key, val in start_token.attrs:
                    if key == 'style' and 'text-align' in val:
                        # Extract alignment from style="text-align:center"
                        if 'left' in val:
                            align = 'left'
                        elif 'center' in val:
                            align = 'center'
                        elif 'right' in val:
                            align = 'right'

        while i < len(tokens):
            token = tokens[i]

            if token.type == close_type:
                break

            # Handle inline content
            if token.type == "inline":
                inline_children = self._parse_inline_content(token)
                children.extend(inline_children)
                i += 1
            else:
                i += 1

        attrs = {"is_header": is_header}
        if align:
            attrs["align"] = align

        return ASTNode(type=NodeType.TABLE_CELL, children=children, attrs=attrs, node_id=self._generate_node_id()), i + 1
