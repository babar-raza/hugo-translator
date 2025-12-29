"""
AST renderer for AST-based translation: Applies translations and renders to Markdown.

This module takes translated TextUnits and applies them back to the AST,
then renders the complete AST to valid Markdown with all formatting preserved.
"""

import logging
import re
from typing import List, Dict, Any, Optional

from ..extractor.text_unit import TextUnit
from ..parser.ast_nodes import ASTNode, NodeType

logger = logging.getLogger(__name__)


class ASTRenderer:
    """
    Renders AST to Markdown with translated content.

    Features:
    - Applies translated TextUnits back to AST using node addresses
    - Renders all node types to valid Markdown
    - Preserves formatting, URLs, code content
    - Deterministic output (same AST → same Markdown)
    - Enhanced table rendering with column alignment
    """

    def __init__(self):
        """Initialize AST renderer."""
        self.unit_map: Dict[str, TextUnit] = {}
        self.applied_units: set = set()
        # Lazy-initialize PlaceholderManager for placeholder restoration
        self._placeholder_manager = None

    def _restore_placeholders(self, text: str, placeholder_map: Dict[str, str]) -> str:
        """
        Restore placeholders in translated text back to original content.

        Args:
            text: Translated text potentially containing placeholders
            placeholder_map: Mapping of placeholders to original content

        Returns:
            Text with placeholders restored to original content
        """
        if not placeholder_map:
            return text

        # Lazy-initialize PlaceholderManager
        if self._placeholder_manager is None:
            from ..extractor.placeholder_manager import PlaceholderManager
            self._placeholder_manager = PlaceholderManager()

        return self._placeholder_manager.restore(text, placeholder_map)

    def _sanitize_language_markers(self, text: str) -> str:
        """
        Remove language markers from text (FIX-BT-02).

        Removes patterns like __de__, __en__, __fr__, etc.
        These markers are internal tags that should never appear in final output.

        Args:
            text: Text potentially containing language markers

        Returns:
            Cleaned text with all markers removed
        """
        if not text:
            return text

        # Pattern: __[a-z]{2}__ (two-letter language code)
        # \s* captures optional trailing whitespace
        pattern = r'__[a-z]{2}__\s*'
        cleaned = re.sub(pattern, '', text)

        # Log if markers were found (indicates pipeline bug)
        if cleaned != text:
            logger.warning(
                f"Language markers detected and removed from output (FIX-BT-02). "
                f"This indicates a pipeline bug. "
                f"Original length: {len(text)}, Cleaned length: {len(cleaned)}"
            )
            logger.debug(f"Original text preview: {text[:200]}")
            logger.debug(f"Cleaned text preview: {cleaned[:200]}")

        return cleaned

    def _apply_frontmatter_translations(self, frontmatter_dict: Dict[str, Any], text_units: List[TextUnit]) -> None:
        """
        Apply translations to frontmatter fields (FIX-BT-03).

        Args:
            frontmatter_dict: Dictionary frontmatter data
            text_units: List of translated TextUnit objects
        """
        if not frontmatter_dict:
            return

        applied_count = 0
        for unit in text_units:
            if not unit.translated_text:
                logger.warning(f"Frontmatter unit has no translation: {unit.metadata}")
                continue

            # Sanitize language markers from frontmatter translations (FIX-BT-02)
            sanitized_translation = self._sanitize_language_markers(unit.translated_text)

            field_name = unit.metadata.get('field_name')
            field_type = unit.metadata.get('field_type')

            if field_type == 'string':
                # Simple string field
                frontmatter_dict[field_name] = sanitized_translation
                logger.debug(f"Applied translation to frontmatter field '{field_name}'")
                applied_count += 1
                # Mark as applied
                self.applied_units.add(unit.node_addr)

            elif field_type == 'array':
                # Array item
                index = unit.metadata.get('index')
                if field_name in frontmatter_dict:
                    if isinstance(frontmatter_dict[field_name], list):
                        if index < len(frontmatter_dict[field_name]):
                            frontmatter_dict[field_name][index] = sanitized_translation
                            logger.debug(f"Applied translation to frontmatter array '{field_name}[{index}]'")
                            applied_count += 1
                            # Mark as applied
                            self.applied_units.add(unit.node_addr)

        logger.info(f"Applied {applied_count} frontmatter translations")

    def apply_translations(self, ast: List[ASTNode], units: List[TextUnit], frontmatter: Optional[Dict[str, Any]] = None) -> None:
        """
        Apply translated TextUnits back to AST nodes and frontmatter.

        Args:
            ast: The AST to update (modified in-place)
            units: Translated TextUnits with node addresses
            frontmatter: Optional frontmatter dictionary to update (FIX-BT-03)

        Raises:
            ValueError: If units cannot be applied (missing nodes, orphaned units)
        """
        # Build unit map by node_addr for fast lookup
        self.unit_map = {unit.node_addr: unit for unit in units}
        self.applied_units = set()

        # Separate frontmatter and body units (FIX-BT-03)
        frontmatter_units = [u for u in units if u.node_addr and u.node_addr.startswith('frontmatter.')]
        body_units = [u for u in units if not (u.node_addr and u.node_addr.startswith('frontmatter.'))]

        # Apply frontmatter translations (FIX-BT-03)
        if frontmatter and frontmatter_units:
            self._apply_frontmatter_translations(frontmatter, frontmatter_units)

        # Apply to each root node
        for node in ast:
            self._apply_to_node(node)

        # Validate all units were applied
        unapplied_units = set(self.unit_map.keys()) - self.applied_units
        if unapplied_units:
            # Filter out frontmatter units from warning (they're applied separately)
            unapplied_non_frontmatter = [addr for addr in unapplied_units if not addr.startswith('frontmatter.')]
            if unapplied_non_frontmatter:
                logger.warning(
                    f"{len(unapplied_non_frontmatter)} TextUnits were not applied to AST. "
                    f"Sample orphaned addresses: {unapplied_non_frontmatter[:5]}"
                )

    def _apply_to_node(self, node: ASTNode) -> None:
        """
        Recursively apply translations to node and children.

        Args:
            node: ASTNode to update
        """
        # Check if this node has a corresponding TextUnit
        if node.node_addr and node.node_addr in self.unit_map:
            unit = self.unit_map[node.node_addr]

            # Get final text (with whitespace reattached)
            final_text = unit.get_final_text()

            # Restore placeholders (if any were applied during extraction)
            placeholder_map = unit.metadata.get('placeholder_map', {})
            if placeholder_map:
                final_text = self._restore_placeholders(final_text, placeholder_map)

            # Update node content based on type
            if node.type in (NodeType.TEXT, NodeType.CODE_SPAN, NodeType.CODE_BLOCK):
                # Text nodes: update raw content
                node.raw = final_text
            elif node.type == NodeType.IMAGE:
                # Image: update alt text (src preserved in attrs)
                if 'alt' in node.attrs:
                    node.attrs['alt'] = final_text
            elif node.type == NodeType.LINK:
                # Link: text is in children (url preserved in attrs)
                pass  # Text children will be updated recursively
            elif node.type in (NodeType.PARAGRAPH, NodeType.HEADING, NodeType.LIST_ITEM,
                              NodeType.BLOCKQUOTE, NodeType.TABLE_CELL):
                # Container nodes with full-sentence extraction (sentence_only strategy):
                # Replace all children with a single TEXT node containing the translation
                from ..parser.ast_nodes import ASTNode
                text_node = ASTNode(
                    type=NodeType.TEXT,
                    raw=final_text,
                    children=[],
                    attrs={},
                    node_addr=f"{node.node_addr}.0"  # Give it a child address
                )
                node.children = [text_node]
            else:
                # Other containers: content is in children
                pass  # Children will be updated recursively

            # Mark as applied
            self.applied_units.add(node.node_addr)

        # Recursively apply to children
        for child in node.children:
            self._apply_to_node(child)

    def render_to_markdown(self, ast: List[ASTNode]) -> str:
        """
        Render AST to Markdown string.

        Args:
            ast: The AST to render

        Returns:
            Valid Markdown with all formatting preserved
        """
        output = []

        for node in ast:
            rendered = self._render_node(node)
            if rendered:
                output.append(rendered)

        # Join with appropriate spacing
        rendered = "".join(output)

        # Final sanitization pass (FIX-BT-02)
        rendered = self._sanitize_language_markers(rendered)

        return rendered

    def _render_node(self, node: ASTNode) -> str:
        """
        Render a single AST node to Markdown.

        Args:
            node: ASTNode to render

        Returns:
            Markdown string
        """
        if node.type == NodeType.TEXT:
            text = node.raw or ""
            # Sanitize markers before output (FIX-BT-02)
            text = self._sanitize_language_markers(text)
            return text

        elif node.type == NodeType.PARAGRAPH:
            content = self._render_children(node)
            return content + "\n\n"

        elif node.type == NodeType.HEADING:
            level = node.attrs.get('level', 1)
            content = self._render_children(node)
            return "#" * level + " " + content + "\n\n"

        elif node.type == NodeType.STRONG:
            content = self._render_children(node)
            return "**" + content + "**"

        elif node.type == NodeType.EMPHASIS:
            content = self._render_children(node)
            return "*" + content + "*"

        elif node.type == NodeType.CODE_SPAN:
            return "`" + (node.raw or "") + "`"

        elif node.type == NodeType.CODE_BLOCK:
            lang = node.attrs.get('lang', '')
            code = node.raw or ""
            return f"```{lang}\n{code}\n```\n\n"

        elif node.type == NodeType.LINK:
            url = node.attrs.get('url', '')
            text = self._render_children(node)
            return f"[{text}]({url})"

        elif node.type == NodeType.IMAGE:
            src = node.attrs.get('src', '')
            alt = node.attrs.get('alt', '')
            return f"![{alt}]({src})"

        elif node.type == NodeType.LIST:
            return self._render_list(node)

        elif node.type == NodeType.LIST_ITEM:
            content = self._render_children(node)
            # List marker is added by parent list renderer
            return content

        elif node.type == NodeType.BLOCKQUOTE:
            content = self._render_children(node)
            # Add > prefix to each line
            lines = content.strip().split('\n')
            quoted = '\n'.join(['> ' + line for line in lines])
            return quoted + "\n\n"

        elif node.type == NodeType.TABLE:
            return self._render_table(node)

        elif node.type == NodeType.THEMATIC_BREAK:
            return "---\n\n"

        elif node.type == NodeType.LINE_BREAK:
            return "\n"

        elif node.type == NodeType.SOFT_BREAK:
            return " "

        elif node.type == NodeType.BLOCK_HTML:
            return (node.raw or "") + "\n\n"

        elif node.type == NodeType.INLINE_HTML:
            return node.raw or ""

        else:
            # Unknown node type: render children
            logger.warning(f"Unknown node type: {node.type}, rendering children")
            return self._render_children(node)

    def _render_children(self, node: ASTNode) -> str:
        """Render all children of a node."""
        return "".join([self._render_node(child) for child in node.children])

    def _render_list(self, list_node: ASTNode) -> str:
        """
        Render list (ordered or unordered).

        Args:
            list_node: LIST node

        Returns:
            Markdown list
        """
        output = []
        is_ordered = list_node.attrs.get('ordered', False)

        for idx, item in enumerate(list_node.children):
            if item.type == NodeType.LIST_ITEM:
                content = self._render_children(item)

                # Add list marker
                if is_ordered:
                    marker = f"{idx + 1}. "
                else:
                    marker = "- "

                # Handle multi-line list items
                lines = content.strip().split('\n')
                first_line = marker + lines[0]
                subsequent_lines = ['  ' + line for line in lines[1:]]  # Indent continuation

                output.append(first_line)
                output.extend(subsequent_lines)
                output.append('\n')

        output.append('\n')  # Extra newline after list
        return "".join(output)

    def _render_table(self, table_node: ASTNode) -> str:
        """
        Render table with aligned columns.

        Enhancement from section 3.11.4:
        - Calculates maximum width per column
        - Pads cells with spaces for alignment
        - Produces clean, readable table markdown

        Args:
            table_node: TABLE node

        Returns:
            Markdown table with aligned columns
        """
        output = []

        # Extract rows from table structure
        rows = []
        header_row = None
        alignments = []

        for child in table_node.children:
            if child.type == NodeType.TABLE_ROW:
                is_header = child.attrs.get('is_header', False)
                row_cells = []

                for cell in child.children:
                    if cell.type == NodeType.TABLE_CELL:
                        cell_content = self._render_children(cell)
                        row_cells.append(cell_content)

                        # Extract alignment if this is header
                        if is_header:
                            align = cell.attrs.get('align', 'left')
                            alignments.append(align)

                if is_header:
                    header_row = row_cells
                else:
                    rows.append(row_cells)

        # If no header row found, treat first row as header
        if header_row is None and rows:
            header_row = rows[0]
            rows = rows[1:]
            alignments = ['left'] * len(header_row)

        # If still no rows, return empty table
        if not header_row:
            return ""

        num_cols = len(header_row)

        # Ensure alignments list matches column count
        while len(alignments) < num_cols:
            alignments.append('left')

        # Calculate max width per column
        all_rows = [header_row] + rows
        col_widths = []
        for col_idx in range(num_cols):
            max_width = 3  # Minimum width for separator (---)
            for row in all_rows:
                if col_idx < len(row):
                    max_width = max(max_width, len(row[col_idx]))
            col_widths.append(max_width)

        # Render header
        header_cells = [
            (header_row[i] if i < len(header_row) else "").ljust(col_widths[i])
            for i in range(num_cols)
        ]
        output.append("| " + " | ".join(header_cells) + " |")

        # Render separator with alignment markers
        separators = []
        for i in range(num_cols):
            width = col_widths[i]
            align = alignments[i]

            if align == 'center':
                sep = ":" + "-" * (width - 2) + ":"
            elif align == 'right':
                sep = "-" * (width - 1) + ":"
            else:  # left or default
                sep = "-" * width

            separators.append(sep.ljust(width))

        output.append("| " + " | ".join(separators) + " |")

        # Render body rows
        for row in rows:
            row_cells = [
                (row[i] if i < len(row) else "").ljust(col_widths[i])
                for i in range(num_cols)
            ]
            output.append("| " + " | ".join(row_cells) + " |")

        return "\n".join(output) + "\n\n"
