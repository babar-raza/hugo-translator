"""
Markdown reconstruction from translated segments and original AST.
"""
import logging
from copy import deepcopy
from io import StringIO
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from ...utils.models import FrontmatterMode, SiteProfile
from ..extractor import PlaceholderManager, Segment, SegmentContextType
from ..parser import ASTNode, HugoDocument, NodeType
from ..quality.glossary_corrector import get_glossary_corrector
from .yaml_formatter import YAMLFormatter

logger = logging.getLogger(__name__)

# Module-level ruamel.yaml instance for CommentedMap round-trip copying
_yaml_copier = YAML()
_yaml_copier.preserve_quotes = True
_yaml_copier.allow_duplicate_keys = True  # Hugo files may have duplicate keys


class MarkdownReconstructor:
    """Reconstructs Hugo Markdown from translated segments."""

    def __init__(self, site_profile: SiteProfile):
        """
        Initialize reconstructor.

        Args:
            site_profile: Site-specific reconstruction rules
        """
        self.site_profile = site_profile
        self.placeholder_manager = PlaceholderManager()
        self.yaml_formatter = YAMLFormatter()

    def reconstruct_document(
        self,
        doc: HugoDocument,
        translations: dict[str, str],
        target_lang: str,
        segment_map: dict[str, str] | None = None,
    ) -> str:
        """
        Reconstruct complete Hugo Markdown document.

        Args:
            doc: Original parsed document
            translations: Mapping of segment_id -> translated_text
            target_lang: Target language code
            segment_map: Optional mapping of node_id -> segment_id for body segments

        Returns:
            Complete Markdown document with frontmatter
        """
        # Store segment map for body reconstruction
        self._segment_map = segment_map or {}

        # Reconstruct frontmatter
        frontmatter = self.reconstruct_frontmatter(
            doc.frontmatter, translations, target_lang
        )

        # Reconstruct body
        body = self.reconstruct_body(doc.ast, translations, target_lang)

        # Format frontmatter
        fm_yaml = self.yaml_formatter.format_frontmatter(frontmatter)

        # Combine
        return f"{fm_yaml}\n{body}" if body else fm_yaml

    def _copy_commented_map(self, original: dict[str, Any] | CommentedMap) -> dict[str, Any] | CommentedMap:
        """
        Create a deep copy of frontmatter that preserves CommentedMap structure.

        Standard deepcopy() loses ruamel.yaml comment metadata. This method
        uses YAML round-trip serialization to preserve comments, quote styles,
        and literal block scalars.

        Args:
            original: Original frontmatter (CommentedMap or dict)

        Returns:
            Deep copy preserving CommentedMap structure if applicable
        """
        if isinstance(original, CommentedMap):
            # Use YAML round-trip to preserve comments
            stream = StringIO()
            _yaml_copier.dump(original, stream)
            stream.seek(0)
            return _yaml_copier.load(stream)
        else:
            # Regular dict - use standard deepcopy
            return deepcopy(original)

    def reconstruct_frontmatter(
        self,
        original: dict[str, Any] | CommentedMap,
        translations: dict[str, str],
        target_lang: str,
    ) -> dict[str, Any] | CommentedMap:
        """
        Reconstruct frontmatter with translations.

        Args:
            original: Original frontmatter dictionary (CommentedMap preserves comments)
            translations: Mapping of segment_id -> translated_text
            target_lang: Target language code

        Returns:
            Reconstructed frontmatter dictionary (CommentedMap if input was CommentedMap)
        """
        result = self._copy_commented_map(original)

        for key, rule in self.site_profile.frontmatter.items():
            if rule.mode == FrontmatterMode.TRANSLATE:
                # Check if this key matches array elements in original
                # Example: key="body.block.title_left" should find body.block[0].title_left, body.block[1].title_left, etc.
                indexed_keys = self._find_indexed_keys(key, original, translations)

                if indexed_keys:
                    # Found indexed translations (e.g., body.block[0].title_left)
                    for indexed_key in indexed_keys:
                        translation = self._find_frontmatter_translation(
                            indexed_key, translations, original
                        )
                        if translation:
                            self.yaml_formatter.set_nested_value(result, indexed_key, translation)
                else:
                    # No arrays found, use key as-is
                    translation = self._find_frontmatter_translation(
                        key, translations, original
                    )
                    if translation:
                        self.yaml_formatter.set_nested_value(result, key, translation)

            elif rule.mode == FrontmatterMode.TRANSLATE_LIST:
                # Translate list items
                original_list = self.yaml_formatter.get_nested_value(original, key)
                if isinstance(original_list, list):
                    translated_list = []
                    for idx, item in enumerate(original_list):
                        list_key = f"{key}[{idx}]"
                        translation = self._find_frontmatter_translation(
                            list_key, translations, original
                        )
                        if translation:
                            translated_list.append(translation)
                        else:
                            translated_list.append(item)  # Fallback to original

                    self.yaml_formatter.set_nested_value(result, key, translated_list)

            elif rule.mode == FrontmatterMode.PASSTHROUGH:
                # Already in result (copied from original)
                pass

            elif rule.mode == FrontmatterMode.COMPUTED:
                # Apply computed strategy
                computed_value = self._compute_field(key, result, target_lang)
                if computed_value is not None:
                    self.yaml_formatter.set_nested_value(result, key, computed_value)

            elif rule.mode == FrontmatterMode.IGNORE:
                # Remove from result
                self._remove_nested_key(result, key)

        return result

    def reconstruct_body(
        self,
        original_ast: list[ASTNode],
        translations: dict[str, str],
        target_lang: str,
    ) -> str:
        """
        Reconstruct Markdown body from AST and translations.

        Args:
            original_ast: Original AST nodes
            translations: Mapping of segment_id -> translated_text
            target_lang: Target language code

        Returns:
            Reconstructed Markdown string with glossary corrections applied
        """
        if not original_ast:
            return ""

        parts = []
        for node in original_ast:
            md = self._reconstruct_node(node, translations)
            if md:
                parts.append(md)

        reconstructed = "\n\n".join(parts)

        # FIX-TRANSLATION-QUALITY: Apply glossary corrections
        # Post-process the reconstructed markdown to fix known mistranslations
        src_lang = self.site_profile.default_source_lang
        corrector = get_glossary_corrector(src_lang, target_lang)

        if corrector:
            corrected, corrections_applied = corrector.apply_corrections(
                reconstructed, src_lang, target_lang
            )
            if corrections_applied:
                logger.info(
                    f"Applied {len(corrections_applied)} glossary corrections "
                    f"for {src_lang}->{target_lang}: {corrections_applied}"
                )
            return corrected

        return reconstructed

    def _reconstruct_node(
        self, node: ASTNode, translations: dict[str, str]
    ) -> str:
        """Reconstruct Markdown for a single AST node."""

        if node.type == NodeType.PARAGRAPH:
            # Find translation for this paragraph
            text = self._find_body_translation(node.node_id, translations)
            if text:
                return text
            # Fallback: reconstruct from children
            return self._reconstruct_inline_children(node.children)

        elif node.type == NodeType.HEADING:
            # Find translation for heading
            text = self._find_body_translation(node.node_id, translations)
            if not text:
                text = self._reconstruct_inline_children(node.children)

            level = node.attrs.get("level", 1)
            prefix = "#" * level
            return f"{prefix} {text}"

        elif node.type == NodeType.CODE_BLOCK:
            # Preserve code blocks as-is
            lang = node.attrs.get("lang", "")
            code = node.raw or ""
            if lang:
                return f"```{lang}\n{code}```"
            else:
                return f"```\n{code}```"

        elif node.type == NodeType.THEMATIC_BREAK:
            return "---"

        elif node.type == NodeType.BLOCK_HTML:
            # Preserve HTML blocks as-is
            return node.raw or ""

        elif node.type == NodeType.LIST:
            # Reconstruct list
            return self._reconstruct_list(node, translations)

        elif node.type == NodeType.TABLE:
            # Reconstruct table
            return self._reconstruct_table(node, translations)

        elif node.type == NodeType.LIST_ITEM:
            # Find translation for list item
            text = self._find_body_translation(node.node_id, translations)
            if not text:
                text = self._reconstruct_inline_children(node.children)

            # Determine list marker
            is_ordered = node.attrs.get("ordered", False)
            marker = "1." if is_ordered else "-"
            return f"{marker} {text}"

        # For other node types, try to reconstruct children
        if node.children:
            child_parts = []
            for child in node.children:
                child_md = self._reconstruct_node(child, translations)
                if child_md:
                    child_parts.append(child_md)
            return "\n\n".join(child_parts)

        return ""

    def _reconstruct_list(
        self, list_node: ASTNode, translations: dict[str, str]
    ) -> str:
        """Reconstruct a list from AST node."""
        items = []
        is_ordered = list_node.attrs.get("ordered", False)

        for child in list_node.children:
            if child.type == NodeType.LIST_ITEM:
                # Find translation
                text = self._find_body_translation(child.node_id, translations)
                if not text:
                    text = self._reconstruct_inline_children(child.children)

                marker = "1." if is_ordered else "-"
                items.append(f"{marker} {text}")

        return "\n".join(items)

    def _reconstruct_table(
        self, table_node: ASTNode, translations: dict[str, str]
    ) -> str:
        """Reconstruct a markdown table from AST node."""
        if not table_node.children:
            return ""

        rows = []
        header_row = None
        num_columns = 0

        for row_node in table_node.children:
            if row_node.type != NodeType.TABLE_ROW:
                continue

            is_header = row_node.attrs.get("is_header", False)
            cells = []

            for cell_node in row_node.children:
                if cell_node.type != NodeType.TABLE_CELL:
                    continue

                # Find translation for cell
                text = self._find_body_translation(cell_node.node_id, translations)
                if not text:
                    text = self._reconstruct_inline_children(cell_node.children)

                cells.append(text.strip())

            if is_header:
                header_row = cells
                num_columns = len(cells)
            else:
                rows.append(cells)

        # Build table markdown
        if not header_row:
            return ""

        lines = []

        # Header row
        lines.append("| " + " | ".join(header_row) + " |")

        # Separator row
        lines.append("| " + " | ".join(["---"] * num_columns) + " |")

        # Data rows
        for row in rows:
            # Pad row if needed
            while len(row) < num_columns:
                row.append("")
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def _reconstruct_inline_children(self, children: list[ASTNode]) -> str:
        """Reconstruct inline content from child nodes."""
        parts = []

        for child in children:
            if child.type == NodeType.TEXT:
                parts.append(child.raw or "")
            elif child.type == NodeType.CODE_SPAN:
                parts.append(f"`{child.raw}`" if child.raw else "")
            elif child.type == NodeType.SOFT_BREAK:
                parts.append(" ")
            elif child.type == NodeType.LINE_BREAK:
                parts.append("\n")
            elif child.type == NodeType.INLINE_HTML:
                parts.append(child.raw or "")
            elif child.type == NodeType.LINK:
                # Reconstruct link: [text](url) or [text](url "title")
                url = child.attrs.get("url", "")
                title = child.attrs.get("title")
                text = self._reconstruct_inline_children(child.children)
                if title:
                    # Escape quotes in title
                    escaped_title = title.replace('"', '\\"')
                    parts.append(f'[{text}]({url} "{escaped_title}")')
                else:
                    parts.append(f'[{text}]({url})')
            elif child.type == NodeType.STRONG:
                # Reconstruct bold: **text**
                text = self._reconstruct_inline_children(child.children)
                parts.append(f'**{text}**')
            elif child.type == NodeType.EMPHASIS:
                # Reconstruct italic: *text*
                text = self._reconstruct_inline_children(child.children)
                parts.append(f'*{text}*')
            elif child.type == NodeType.IMAGE:
                # Reconstruct image: ![alt](src) or ![alt](src "title")
                src = child.attrs.get("src", "")
                alt = child.attrs.get("alt", "")
                title = child.attrs.get("title")
                if title:
                    escaped_title = title.replace('"', '\\"')
                    parts.append(f'![{alt}]({src} "{escaped_title}")')
                else:
                    parts.append(f'![{alt}]({src})')
            elif child.children:
                # Recurse for nested inline elements
                parts.append(self._reconstruct_inline_children(child.children))

        return "".join(parts)

    def _find_frontmatter_translation(
        self, key: str, translations: dict[str, str], original: dict[str, Any]
    ) -> str | None:
        """
        Find translation for frontmatter field.

        Args:
            key: Frontmatter key (may include [idx] for list items)
            translations: Translation map (segment_id -> translated_text)
            original: Original frontmatter

        Returns:
            Translated text if found, None otherwise
        """
        # Use yaml_formatter which now supports array indices
        original_text = self.yaml_formatter.get_nested_value(original, key)

        if not isinstance(original_text, str):
            return None

        # Look for translation by segment ID
        # The segment ID is generated from text + context, so we need to
        # recreate it to look up the translation
        from ..extractor import SegmentContext

        context = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key=key,
        )

        segment_id = Segment.create_id(
            original_text, context, self.site_profile.site_id
        )

        # Look up translation
        if segment_id in translations:
            return translations[segment_id]

        return None

    def _find_body_translation(
        self, node_id: str | None, translations: dict[str, str]
    ) -> str | None:
        """
        Find translation for body node.

        Args:
            node_id: AST node ID
            translations: Translation map (segment_id -> translated_text)

        Returns:
            Translated text if found, None otherwise
        """
        if not node_id:
            return None

        # Use segment map if available
        if hasattr(self, "_segment_map") and self._segment_map:
            segment_id = self._segment_map.get(node_id)
            if segment_id and segment_id in translations:
                return translations[segment_id]

        # Fallback: try direct node_id lookup (for tests)
        if node_id in translations:
            return translations[node_id]

        return None

    def _compute_field(
        self, key: str, frontmatter: dict[str, Any], target_lang: str
    ) -> Any | None:
        """
        Compute derived frontmatter field.

        Args:
            key: Field key
            frontmatter: Current frontmatter
            target_lang: Target language

        Returns:
            Computed value
        """
        # Example computed fields:
        # - slug: slugify translated title
        # - url: generate from translated title + lang
        # - lang: set to target_lang

        if key == "lang":
            return target_lang

        # For other computed fields, would need specific logic
        # This is a simplified implementation
        return None

    def _remove_nested_key(self, data: dict[str, Any], key: str) -> None:
        """Remove a nested key from dictionary."""
        parts = key.split(".")
        current = data

        # Navigate to parent
        for part in parts[:-1]:
            if not isinstance(current, dict) or part not in current:
                return
            current = current[part]

        # Remove final key
        if isinstance(current, dict) and parts[-1] in current:
            del current[parts[-1]]

    def _find_indexed_keys(
        self, generic_key: str, original: dict[str, Any], translations: dict[str, str]
    ) -> list[str]:
        """
        Find all indexed versions of a generic key that have translations.

        Args:
            generic_key: Generic key pattern (e.g., "body.block.title_left")
            original: Original frontmatter to check for arrays
            translations: Translation map to check for indexed translations

        Returns:
            List of indexed keys (e.g., ["body.block[0].title_left", "body.block[1].title_left"])
            Empty list if no indexed versions found

        Example:
            Input: "body.block.title_left"
            Output: ["body.block[0].title_left", "body.block[1].title_left"]
        """
        # Check if the translations dict contains any indexed versions of this key
        # by scanning for keys that match the pattern with array indices
        indexed_keys = []

        # Look through translations for keys that match the pattern
        # Example: body.block.title_left should match body.block[0].title_left
        for segment_id in translations.keys():
            # Extract the frontmatter key from the segment_id
            # Segment IDs are generated from text + context, but we can check
            # if there are translations that would match indexed versions
            pass

        # Alternative: scan the original frontmatter structure to find arrays
        # Then generate indexed keys for those arrays
        parts = generic_key.split(".")

        # Navigate through the original frontmatter to find arrays
        result = self._expand_arrays_in_key(parts, original, [])

        return result

    def _expand_arrays_in_key(
        self, parts: list[str], data: Any, current_path: list[str]
    ) -> list[str]:
        """
        Recursively expand a key pattern to find all indexed versions.

        Args:
            parts: Remaining parts of the key to process
            data: Current data structure being traversed
            current_path: Path built so far

        Returns:
            List of fully indexed keys
        """
        if not parts:
            # Reached the end of the key
            return [".".join(current_path)] if current_path else []

        if not isinstance(data, dict):
            return []

        part = parts[0]
        remaining = parts[1:]

        if part not in data:
            return []

        field_value = data[part]

        if isinstance(field_value, list):
            # This field is an array - expand all indices
            results = []
            for idx, item in enumerate(field_value):
                indexed_part = f"{part}[{idx}]"
                expanded = self._expand_arrays_in_key(
                    remaining, item, current_path + [indexed_part]
                )
                results.extend(expanded)
            return results
        else:
            # Regular field - continue traversal
            return self._expand_arrays_in_key(
                remaining, field_value, current_path + [part]
            )
