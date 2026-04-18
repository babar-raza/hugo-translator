"""
AST renderer for AST-based translation: Applies translations and renders to Markdown.

This module takes translated TextUnits and applies them back to the AST,
then renders the complete AST to valid Markdown with all formatting preserved.
"""

import logging
import re
from typing import Any

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
        self.unit_map: dict[str, TextUnit] = {}
        self.applied_units: set = set()
        # Lazy-initialize PlaceholderManager for placeholder restoration
        self._placeholder_manager = None
        # Counter for AST nodes that had no matching TextUnit (potential source-lang leakage)
        self._missing_node_count: int = 0

    def _restore_placeholders(self, text: str, placeholder_map: dict[str, str]) -> str:
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

    def _preserve_punctuation(self, source_text: str, translated_text: str, prefix_ws: str, suffix_ws: str) -> str:
        """
        Preserve leading/trailing punctuation that MT models sometimes drop (FIX-C).

        MT models occasionally drop leading punctuation (period, comma, semicolon)
        which creates malformed markdown like `**bold**Word` instead of `**bold**. Word`.
        This breaks markdown parsing and loses bold formatting.

        Args:
            source_text: Original source text (stripped, no whitespace)
            translated_text: Translated text from MT model (stripped, no whitespace)
            prefix_ws: Leading whitespace
            suffix_ws: Trailing whitespace

        Returns:
            Final text with punctuation preserved and whitespace reattached
        """
        # Define punctuation characters to preserve
        LEADING_PUNCT = '.!?;:,‚„…'
        TRAILING_PUNCT = '.!?;:,‚„…'

        # Check if source had leading punctuation but translation doesn't
        if source_text and translated_text:
            # Extract leading punctuation from source
            source_leading_punct = ""
            for char in source_text:
                if char in LEADING_PUNCT:
                    source_leading_punct += char
                else:
                    break

            # Check if translation is missing this punctuation
            if source_leading_punct and not translated_text.startswith(source_leading_punct):
                logger.debug(
                    f"[FIX-C] Restoring leading punctuation '{source_leading_punct}' "
                    f"dropped by MT model. Source: {source_text[:30]}, "
                    f"Translation: {translated_text[:30]}"
                )
                translated_text = source_leading_punct + translated_text

            # Extract trailing punctuation from source
            source_trailing_punct = ""
            for char in reversed(source_text):
                if char in TRAILING_PUNCT:
                    source_trailing_punct = char + source_trailing_punct
                else:
                    break

            # Check if translation is missing trailing punctuation
            if source_trailing_punct and not translated_text.endswith(source_trailing_punct):
                logger.debug(
                    f"[FIX-C] Restoring trailing punctuation '{source_trailing_punct}' "
                    f"dropped by MT model. Source: {source_text[-30:]}, "
                    f"Translation: {translated_text[-30:]}"
                )
                translated_text = translated_text + source_trailing_punct

        # Reattach whitespace
        return f"{prefix_ws}{translated_text}{suffix_ws}"

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

    def _normalize_bold_markers(self, text: str) -> str:
        """
        Fix M2M100 bold marker corruption in translated text (FIX-BOLD-01).

        M2M100 and similar MT models sometimes produce asymmetric asterisk sequences
        for bold markers, e.g. "* Texto*" instead of "**Texto**". This method
        normalizes the five common corruption patterns.

        Patterns (applied in order):
        P4a: ***text*  → **text**  (triple opening, single closing)
        P4b: *text***  → **text**  (single opening, triple closing)
        P2:  * text**  → **text**  (single + space opening, double closing)
        P3:  **text *  → **text**  (double opening, single + space closing)
        P1:  * Uppercase text* → **Uppercase text** (heading-style corruption)

        Args:
            text: Translated text potentially containing corrupted bold markers

        Returns:
            Text with bold marker corruption fixed, or None/empty unchanged.
        """
        if not text:
            return text

        # P4a: Triple opening, single closing: ***text* → **text**
        # Does NOT match ***text*** (valid bold-italic — (?!\*) prevents it)
        text = re.sub(r'\*\*\*([^*\n]+)\*(?!\*)', r'**\1**', text)

        # P4b: Single opening, triple closing: *text*** → **text**
        # Does NOT match ***text*** ((?<!\*) at pos 1/2 fails)
        text = re.sub(r'(?<!\*)\*([^*\n]+)\*\*\*', r'**\1**', text)

        # P2: Asymmetric opening (single * + space, double closing): * text** → **text**
        text = re.sub(r'(?<!\*)\*\s+([^*\n]+?)\s*\*\*(?!\*)', r'**\1**', text)

        # P3: Asymmetric closing (double opening, single * + optional space): **text * → **text**
        # (?<!\S) ensures ** is at start-of-string or after whitespace (opening position,
        # not a closing ** from a prior valid bold). [^\n*] prevents cross-line matching.
        text = re.sub(r'(?<!\S)\*\*\s*([^\n*]+?)\s*(?<!\*)\*(?!\*)', r'**\1**', text)

        # P1: Heading-style corruption — single * with uppercase content: * Texto* → **Texto**
        # Requires uppercase first character (Latin or Unicode) to avoid matching
        # legitimate lowercase italic *word*. [^\n*] prevents cross-line matching.
        text = re.sub(
            r'(?<!\*)\*\s*([A-Z\u00C0-\u017F][^\n*]*?)\s*\*(?!\*)',
            r'**\1**',
            text
        )

        return text

    def _reparse_inline_markdown(self, text: str, parent_node_addr: str) -> list[ASTNode]:
        """
        Re-parse translated text containing markdown syntax back into AST nodes.

        FIX-MARKDOWN-PRESERVATION: When text contains markdown formatting like **bold**
        or *italic*, parse it back into proper AST structure (STRONG/EMPHASIS nodes).

        This fixes the core issue where translated text like "Ceci est **texte gras** ici"
        was being treated as plain text instead of being parsed into STRONG nodes.

        Args:
            text: Translated text potentially containing markdown syntax
            parent_node_addr: Node address of parent for child addressing

        Returns:
            List of AST nodes representing the parsed inline content

        Example:
            Input: "This is **bold** and *italic* text"
            Output: [TEXT("This is "), STRONG([TEXT("bold")]), TEXT(" and "),
                     EMPHASIS([TEXT("italic")]), TEXT(" text")]
        """
        from markdown_it import MarkdownIt

        # Use markdown_it to parse inline content
        md = MarkdownIt("commonmark")

        # Parse as inline content (wrap in dummy paragraph for parsing)
        tokens = md.parse(text)

        # Extract inline tokens from paragraph
        inline_tokens = None
        for i, token in enumerate(tokens):
            if token.type == "inline":
                inline_tokens = token.children
                break

        if not inline_tokens:
            # No inline tokens found, return as plain text
            from ..parser.ast_nodes import ASTNode
            return [ASTNode(
                type=NodeType.TEXT,
                raw=text,
                children=[],
                attrs={},
                node_addr=f"{parent_node_addr}.0"
            )]

        # Parse inline tokens into AST nodes
        return self._parse_inline_tokens_to_ast(inline_tokens, parent_node_addr)

    def _parse_inline_tokens_to_ast(self, tokens: list, parent_node_addr: str) -> list[ASTNode]:
        """
        Convert markdown_it inline tokens to AST nodes.

        Args:
            tokens: List of inline tokens from markdown_it
            parent_node_addr: Parent node address for child addressing

        Returns:
            List of AST nodes
        """
        from ..parser.ast_nodes import ASTNode

        nodes = []
        i = 0
        child_idx = 0

        while i < len(tokens):
            token = tokens[i]
            node_addr = f"{parent_node_addr}.{child_idx}"

            if token.type == "text":
                nodes.append(ASTNode(
                    type=NodeType.TEXT,
                    raw=token.content,
                    children=[],
                    attrs={},
                    node_addr=node_addr
                ))
                child_idx += 1
                i += 1

            elif token.type == "strong_open":
                # Find matching strong_close
                children_tokens = []
                i += 1
                depth = 1
                while i < len(tokens) and depth > 0:
                    if tokens[i].type == "strong_open":
                        depth += 1
                    elif tokens[i].type == "strong_close":
                        depth -= 1
                        if depth == 0:
                            break
                    children_tokens.append(tokens[i])
                    i += 1

                # Recursively parse children
                children = self._parse_inline_tokens_to_ast(children_tokens, node_addr)

                nodes.append(ASTNode(
                    type=NodeType.STRONG,
                    children=children,
                    attrs={},
                    node_addr=node_addr
                ))
                child_idx += 1
                i += 1  # Skip strong_close

            elif token.type == "em_open":
                # Find matching em_close
                children_tokens = []
                i += 1
                depth = 1
                while i < len(tokens) and depth > 0:
                    if tokens[i].type == "em_open":
                        depth += 1
                    elif tokens[i].type == "em_close":
                        depth -= 1
                        if depth == 0:
                            break
                    children_tokens.append(tokens[i])
                    i += 1

                # Recursively parse children
                children = self._parse_inline_tokens_to_ast(children_tokens, node_addr)

                nodes.append(ASTNode(
                    type=NodeType.EMPHASIS,
                    children=children,
                    attrs={},
                    node_addr=node_addr
                ))
                child_idx += 1
                i += 1  # Skip em_close

            elif token.type == "code_inline":
                nodes.append(ASTNode(
                    type=NodeType.CODE_SPAN,
                    raw=token.content,
                    children=[],
                    attrs={},
                    node_addr=node_addr
                ))
                child_idx += 1
                i += 1

            elif token.type == "link_open":
                # Extract link URL
                url = ""
                for attr in token.attrs or []:
                    if attr[0] == "href":
                        url = attr[1]
                        break

                # Find matching link_close
                children_tokens = []
                i += 1
                depth = 1
                while i < len(tokens) and depth > 0:
                    if tokens[i].type == "link_open":
                        depth += 1
                    elif tokens[i].type == "link_close":
                        depth -= 1
                        if depth == 0:
                            break
                    children_tokens.append(tokens[i])
                    i += 1

                # Recursively parse children
                children = self._parse_inline_tokens_to_ast(children_tokens, node_addr)

                nodes.append(ASTNode(
                    type=NodeType.LINK,
                    children=children,
                    attrs={"url": url},
                    node_addr=node_addr
                ))
                child_idx += 1
                i += 1  # Skip link_close

            elif token.type == "softbreak":
                nodes.append(ASTNode(
                    type=NodeType.SOFT_BREAK,
                    children=[],
                    attrs={},
                    node_addr=node_addr
                ))
                child_idx += 1
                i += 1

            elif token.type == "hardbreak":
                nodes.append(ASTNode(
                    type=NodeType.LINE_BREAK,
                    children=[],
                    attrs={},
                    node_addr=node_addr
                ))
                child_idx += 1
                i += 1

            else:
                # Skip unknown token types
                logger.debug(f"Skipping unknown inline token type: {token.type}")
                i += 1

        return nodes

    def _apply_frontmatter_translations(self, frontmatter_dict: dict[str, Any], text_units: list[TextUnit]) -> None:
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

    def apply_translations(self, ast: list[ASTNode], units: list[TextUnit], frontmatter: dict[str, Any] | None = None) -> None:
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
        self._missing_node_count = 0  # Reset per call

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

        # Report missing nodes (AST nodes that had no matching TextUnit — source text rendered)
        if self._missing_node_count > 0:
            logger.error(
                f"AST reconstruction: {self._missing_node_count} nodes had no translation unit. "
                f"Output may contain source-language text (AST_FALLBACK path was taken)."
            )

    def _apply_to_node(self, node: ASTNode, ancestor_in_unit_map: bool = False) -> None:
        """
        Recursively apply translations to node and children.

        Args:
            ancestor_in_unit_map: True when any ancestor of this node is already in
                unit_map (Path A full-sentence extraction).  Inline formatting nodes
                (STRONG, EM, CODE…) inside a translated PARAGRAPH must not be counted
                as missing-node gaps even though they themselves have no TextUnit —
                their content was already covered by the ancestor's translation.
                Set by the parent call; do not pass this argument directly.
            node: ASTNode to update
        """
        import os
        debug_mode = os.environ.get('TRANSLATION_DEBUG', '0') == '1'

        # INSTRUMENTATION: Log PARAGRAPH processing with children info
        if debug_mode and node.type == NodeType.PARAGRAPH:
            children_summary = [f"{child.type.name}" for child in node.children]
            logger.info(f"[HARDENING-INSTRUMENT] BEFORE: PARAGRAPH node_addr={node.node_addr}")
            logger.info(f"[HARDENING-INSTRUMENT]   Children count: {len(node.children)}")
            logger.info(f"[HARDENING-INSTRUMENT]   Children types: {children_summary}")
            logger.info(f"[HARDENING-INSTRUMENT]   Has translation unit: {node.node_addr in self.unit_map if node.node_addr else False}")

            # Log inline formatting presence
            has_strong = any(c.type == NodeType.STRONG for c in node.children)
            has_emphasis = any(c.type == NodeType.EMPHASIS for c in node.children)
            logger.info(f"[HARDENING-INSTRUMENT]   Has STRONG nodes: {has_strong}")
            logger.info(f"[HARDENING-INSTRUMENT]   Has EMPHASIS nodes: {has_emphasis}")

        # Check if this node has a corresponding TextUnit
        if node.node_addr and node.node_addr in self.unit_map:
            unit = self.unit_map[node.node_addr]

            # FIX-C: Preserve leading/trailing punctuation that MT models sometimes drop
            # This prevents malformed markdown like `**bold**Word` instead of `**bold**. Word`
            if unit.translated_text and unit.source_text:
                final_text = self._preserve_punctuation(unit.source_text, unit.translated_text, unit.prefix_ws, unit.suffix_ws)
            else:
                # No translation or no source - use standard whitespace reattachment
                final_text = unit.get_final_text()

            # Restore placeholders (if any were applied during extraction)
            placeholder_map = unit.metadata.get('placeholder_map', {})
            if placeholder_map:
                restored = self._restore_placeholders(final_text, placeholder_map)
                # Detect unreplaced placeholder tokens — indicates partial restoration failure
                remaining_placeholders = re.findall(r'\{PLACEHOLDER_\d+\}', restored)
                if remaining_placeholders:
                    logger.warning(
                        f"PLACEHOLDER_LEAK: {len(remaining_placeholders)} token(s) not restored "
                        f"for node_addr={node.node_addr!r}. "
                        f"Tokens: {remaining_placeholders[:3]}. Using pre-restoration text."
                    )
                    # Keep final_text pre-restoration; purity gate will catch any stray tokens
                else:
                    final_text = restored

            # INSTRUMENTATION: Log translation application
            if debug_mode and node.type == NodeType.PARAGRAPH:
                logger.info(f"[HARDENING-INSTRUMENT]   Translated text preview: {final_text[:100]}")
                logger.info(f"[HARDENING-INSTRUMENT]   Unit extraction_mode: {unit.metadata.get('extraction_mode', 'UNKNOWN')}")

            # Update node content based on type
            if node.type in (NodeType.TEXT, NodeType.CODE_SPAN, NodeType.CODE_BLOCK):
                # Text nodes: update raw content
                node.raw = final_text
                self.applied_units.add(node.node_addr)
            elif node.type == NodeType.IMAGE:
                # Image: update alt text (src preserved in attrs)
                if 'alt' in node.attrs:
                    node.attrs['alt'] = final_text
                self.applied_units.add(node.node_addr)
            elif node.type == NodeType.LINK:
                # Link: text is in children (url preserved in attrs)
                pass  # Text children will be updated recursively
                self.applied_units.add(node.node_addr)
            elif node.type == NodeType.STRONG:
                # FIX-B: STRONG nodes must never be flattened
                # Apply translation to TEXT children only, preserve STRONG wrapper
                if debug_mode:
                    logger.info("[HARDENING-FIX-B] Preserving STRONG node, processing children")
                # Don't mark as applied - let children be processed
                pass
            elif node.type == NodeType.EMPHASIS:
                # FIX-B: EMPHASIS nodes must never be flattened
                # Apply translation to TEXT children only, preserve EMPHASIS wrapper
                if debug_mode:
                    logger.info("[HARDENING-FIX-B] Preserving EMPHASIS node, processing children")
                # Don't mark as applied - let children be processed
                pass
            elif node.type == NodeType.HEADING:
                # FIX-B: HEADING nodes must NEVER be flattened
                # Preserve heading level attribute and process children recursively
                heading_level = node.attrs.get('level', 1)

                # Check for inline formatting in heading
                has_inline_formatting = any(
                    child.type in (NodeType.STRONG, NodeType.EMPHASIS, NodeType.LINK,
                                   NodeType.CODE_SPAN, NodeType.IMAGE)
                    for child in node.children
                )

                if has_inline_formatting:
                    # FIX-MARKDOWN-PRESERVATION: Re-parse heading with inline formatting
                    if debug_mode:
                        logger.info(f"[FIX-MARKDOWN-PRESERVATION] Re-parsing HEADING level={heading_level} with inline formatting")

                    # Re-parse the translated text back into AST nodes
                    new_children = self._reparse_inline_markdown(final_text, node.node_addr)
                    node.children = new_children

                    # CRITICAL: Preserve heading level
                    node.attrs['level'] = heading_level

                    # Mark as applied
                    self.applied_units.add(node.node_addr)
                else:
                    # HEADING with plain text - safe to flatten but MUST preserve level
                    from ..parser.ast_nodes import ASTNode

                    if debug_mode:
                        logger.info(f"[HARDENING-FIX-B] Flattening HEADING level={heading_level} (no inline formatting)")

                    text_node = ASTNode(
                        type=NodeType.TEXT,
                        raw=final_text,
                        children=[],
                        attrs={},
                        node_addr=f"{node.node_addr}.0"
                    )
                    node.children = [text_node]

                    # CRITICAL: Preserve heading level
                    node.attrs['level'] = heading_level

                    # Mark as applied
                    self.applied_units.add(node.node_addr)
            elif node.type in (NodeType.PARAGRAPH, NodeType.LIST_ITEM,
                              NodeType.BLOCKQUOTE, NodeType.TABLE_CELL):
                # Container nodes with full-sentence extraction (sentence_only strategy):
                # FIX-A: Only flatten if NO inline formatting is present

                # Check for inline formatting nodes
                # FIX-F: Include LINE_BREAK to preserve multi-line list items
                has_inline_formatting = any(
                    child.type in (NodeType.STRONG, NodeType.EMPHASIS, NodeType.LINK,
                                   NodeType.CODE_SPAN, NodeType.IMAGE, NodeType.LINE_BREAK)
                    for child in node.children
                )

                if has_inline_formatting:
                    # FIX-MARKDOWN-PRESERVATION: Re-parse translated text with markdown
                    # Instead of skipping, re-parse the translation to reconstruct inline formatting
                    if debug_mode and node.type == NodeType.PARAGRAPH:
                        logger.info("[FIX-MARKDOWN-PRESERVATION] Re-parsing translated text with inline formatting")
                        logger.info(f"[FIX-MARKDOWN-PRESERVATION]   Original children: {len(node.children)}")
                        logger.info(f"[FIX-MARKDOWN-PRESERVATION]   Text preview: {final_text[:100]}")

                    # Re-parse the translated text (which contains markdown like **bold**)
                    # back into AST nodes with proper STRONG/EMPHASIS structure
                    new_children = self._reparse_inline_markdown(final_text, node.node_addr)

                    if debug_mode and node.type == NodeType.PARAGRAPH:
                        logger.info(f"[FIX-MARKDOWN-PRESERVATION]   Re-parsed children: {len(new_children)}")
                        strong_count = sum(1 for c in new_children if c.type == NodeType.STRONG)
                        logger.info(f"[FIX-MARKDOWN-PRESERVATION]   STRONG nodes: {strong_count}")

                    # Preserve block-level children (nested LIST, CODE_BLOCK) that
                    # coexist with inline formatting — same fix as the flatten path below.
                    block_children = [
                        child for child in node.children
                        if child.type in (NodeType.CODE_BLOCK, NodeType.LIST)
                    ]

                    # Replace children with re-parsed inline nodes + preserved block children
                    node.children = new_children + block_children

                    # Mark as applied
                    self.applied_units.add(node.node_addr)
                else:
                    # Safe to flatten - no inline formatting to destroy
                    from ..parser.ast_nodes import ASTNode

                    # INSTRUMENTATION: Log before flattening
                    if debug_mode and node.type == NodeType.PARAGRAPH:
                        logger.info("[HARDENING-FIX-A] FLATTENING (no inline formatting)")

                    # Bug 4: Preserve block-level children — flattening must not destroy them.
                    # A container can have a full-sentence TextUnit for its inline text
                    # AND also contain CODE_BLOCK or nested LIST children (which are either
                    # extracted as do_not_translate units or have their own units). Keep
                    # block-level children alongside the translated text node.
                    block_children = [
                        child for child in node.children
                        if child.type in (NodeType.CODE_BLOCK, NodeType.LIST)
                    ]

                    text_node = ASTNode(
                        type=NodeType.TEXT,
                        raw=final_text,
                        children=[],
                        attrs={},
                        node_addr=f"{node.node_addr}.0"
                    )
                    node.children = [text_node] + block_children

                    # Mark as applied
                    self.applied_units.add(node.node_addr)
            else:
                # Other containers: content is in children
                pass  # Children will be updated recursively
                # Mark as applied for these other containers
                self.applied_units.add(node.node_addr)

            # Note: For PARAGRAPH with inline formatting (FIX-A), we don't mark as applied
            # so children can be processed recursively

        # TC-MLD-01/TC-MLD-06/TC-AST-03: Detect nodes with an address but no matching
        # TextUnit.  These nodes will render their original source-language children
        # as-is — the primary AST_FALLBACK path for mixed-language output.
        #
        # TC-MLD-06 refinement: the extractor has two paths for formatted containers:
        #   Path A (full-sentence): creates one TextUnit for the whole container.
        #   Path B (leaf extraction): creates TextUnits only for leaf TEXT children.
        # In Path B the container address is never in unit_map — the content IS still
        # translated at the child level.  Before firing a warning, check whether any
        # descendant is already in unit_map; if so this is a leaf-extraction container,
        # not a true gap.
        #
        # TC-AST-03 refinement: Path A full-sentence extraction translates the PARAGRAPH
        # as a whole.  Its inline formatting children (STRONG, EM, CODE…) have addresses
        # but are NOT in unit_map — their content IS covered by the ancestor PARAGRAPH.
        # The ancestor_in_unit_map flag (propagated from the parent call) suppresses
        # false-positive counting for these nodes.
        this_in_unit_map = bool(node.node_addr and node.node_addr in self.unit_map)

        # TC-AST-03: log when ancestor coverage suppresses what would otherwise be a gap.
        if (node.node_addr and not this_in_unit_map and ancestor_in_unit_map
                and node.node_addr not in self.applied_units
                and not node.node_addr.startswith(('frontmatter.', '__'))):
            logger.debug(
                "AST_ANCESTOR_SUPPRESSED: %s (type=%s) — covered by ancestor in unit_map",
                node.node_addr, node.type.name,
            )

        if (node.node_addr
                and not this_in_unit_map
                and not ancestor_in_unit_map                         # TC-AST-03 guard
                and node.node_addr not in self.applied_units
                and not node.node_addr.startswith(('frontmatter.', '__'))):
            has_prose = any(
                c.type == NodeType.TEXT and c.raw and len(c.raw.strip()) > 5
                for c in node.children
            )
            if has_prose and node.type not in (
                NodeType.CODE_BLOCK, NodeType.CODE_SPAN, NodeType.INLINE_HTML
            ):
                def _has_descendant_in_unit_map(n) -> bool:
                    if n.node_addr and n.node_addr in self.unit_map:
                        return True
                    return any(_has_descendant_in_unit_map(c) for c in n.children)

                if not _has_descendant_in_unit_map(node):
                    # True gap: prose container has no translated descendants AND no
                    # ancestor in unit_map — source-language text WILL appear in output.
                    self._missing_node_count += 1
                    logger.warning(
                        f"AST_FALLBACK: node_addr={node.node_addr!r} not in unit_map "
                        f"(type={node.type.name}) and no descendants translated. "
                        f"Source text will render as-is."
                    )
                # else: leaf-extraction case — content translated at child level, no warning needed

        # Recursively apply to children.
        # Propagate ancestor coverage: if THIS node is in unit_map (Path A), all
        # descendants are covered — pass ancestor_in_unit_map=True downward.
        child_ancestor_flag = ancestor_in_unit_map or this_in_unit_map
        for child in node.children:
            self._apply_to_node(child, ancestor_in_unit_map=child_ancestor_flag)

    def render_to_markdown(self, ast: list[ASTNode]) -> str:
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

        # FIX-D: Preserve spacing between bold-only paragraphs and lists
        # Remove extra blank line when bold-only paragraph is followed by a list
        # Pattern: **text**\n\n- list  →  **text**\n- list
        import re
        rendered = re.sub(r'(\*\*[^*\n]+\*\*)\n\n(-\s)', r'\1\n\2', rendered)
        rendered = re.sub(r'(\*\*[^*\n]+\*\*)\n\n(\d+\.\s)', r'\1\n\2', rendered)  # ordered lists too

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
        """
        Render all children of a node, adding newlines before block elements.

        FIX-NESTED-LIST: Block elements (LIST, BLOCKQUOTE, CODE_BLOCK, TABLE)
        need newlines before them when nested inside list items or other containers.
        Without this, nested lists get concatenated on the same line as their parent content.
        """
        # Block elements that should start on a new line
        BLOCK_TYPES = {NodeType.LIST, NodeType.BLOCKQUOTE, NodeType.CODE_BLOCK, NodeType.TABLE}

        result = []
        for child in node.children:
            rendered = self._render_node(child)

            # Add newline before block elements (unless it's the first child)
            if result and child.type in BLOCK_TYPES:
                result.append('\n')

            result.append(rendered)

        return "".join(result)

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

                output.append(first_line + '\n')
                for sub_line in subsequent_lines:
                    output.append(sub_line + '\n')

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
