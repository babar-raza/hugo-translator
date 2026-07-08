"""
Segment extraction from HugoDocument based on Site Profile rules.
"""
import hashlib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ...utils.models import FrontmatterMode, SiteProfile
from ..parser import ASTNode, HugoDocument, NodeType
from .placeholder_manager import PlaceholderManager


class SegmentContextType(str, Enum):
    """Type of segment context."""

    FRONTMATTER = "frontmatter"
    BODY_TEXT = "body_text"
    HEADING = "heading"
    LIST_ITEM = "list_item"


@dataclass
class SegmentContext:
    """Context information for a translatable segment."""

    context_type: SegmentContextType
    node_id: str | None = None
    frontmatter_key: str | None = None
    parent_node_type: NodeType | None = None
    depth: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Segment:
    """A translatable unit with context."""

    id: str
    source_text: str
    context: SegmentContext
    site_id: str
    source_lang: str
    placeholder_map: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Terminology protection fields (TRM-05)
    protected_terms: list[Any] = field(default_factory=list)  # List[ProtectedSegment]
    protection_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create_id(cls, text: str, context: SegmentContext, site_id: str) -> str:
        """Generate a unique segment ID."""
        # Create a stable hash based on text and context
        content = f"{site_id}:{context.context_type}:{text}"
        if context.frontmatter_key:
            content += f":{context.frontmatter_key}"
        if context.node_id:
            content += f":{context.node_id}"

        return hashlib.sha256(content.encode()).hexdigest()[:16]


class SegmentExtractor:
    """Extracts translatable segments from HugoDocument."""

    def __init__(self, site_profile: SiteProfile, terminology_manager: Any | None = None):
        """
        Initialize segment extractor.

        Args:
            site_profile: Site-specific extraction rules
            terminology_manager: Optional TerminologyManager for protecting terms
        """
        self.site_profile = site_profile
        self.placeholder_manager = PlaceholderManager()
        self.terminology_manager = terminology_manager

        # Compile preserve patterns from site profile
        self.preserve_patterns = site_profile.body.preserve_patterns or []
        self.preserve_blocks = site_profile.body.preserve_blocks or []

        # Hugo shortcode patterns
        self.shortcode_patterns = site_profile.body.placeholder_syntax or [
            r"\{\{<.*?>\}\}",  # {{< shortcode >}}
            r"\{\{%.*?%\}\}",  # {{% shortcode %}}
        ]

    def extract_all(
        self, doc: HugoDocument, source_lang: str | None = None
    ) -> list[Segment]:
        """
        Extract all translatable segments from document.

        Args:
            doc: Parsed Hugo document
            source_lang: Source language code (defaults to site profile default)

        Returns:
            List of translatable segments
        """
        source_lang = source_lang or self.site_profile.default_source_lang
        segments = []

        # Extract from frontmatter
        segments.extend(
            self.extract_from_frontmatter(doc.frontmatter, source_lang)
        )

        # Extract from body AST
        if self.site_profile.body.translate_markdown:
            segments.extend(self.extract_from_body(doc.ast, source_lang))

        return segments

    def extract_from_frontmatter(
        self, frontmatter: dict[str, Any], source_lang: str
    ) -> list[Segment]:
        """
        Extract segments from frontmatter based on rules.

        Handles both simple paths (e.g., "title") and paths that traverse
        arrays (e.g., "body.block.title_left" where block is an array).

        Args:
            frontmatter: Frontmatter dictionary
            source_lang: Source language code

        Returns:
            List of frontmatter segments
        """
        segments = []

        for key, rule in self.site_profile.frontmatter.items():
            if rule.mode == FrontmatterMode.IGNORE:
                continue

            if rule.mode == FrontmatterMode.TRANSLATE:
                # Use array-aware extraction to handle paths like body.block.title_left
                matches = self._get_all_nested_values(frontmatter, key)

                if not matches:
                    # Fallback: try simple path (backward compatibility)
                    value = self._get_nested_value(frontmatter, key)
                    if value is not None and isinstance(value, str) and value.strip():
                        # Skip pure identifiers — m2m translates placeholder tokens literally
                        if not self._is_pure_identifier(value):
                            seg = self._create_frontmatter_segment(
                                key, value, source_lang
                            )
                            segments.append(seg)
                else:
                    # Process all matches from array-aware extraction
                    for indexed_key, value in matches:
                        if isinstance(value, str) and value.strip():
                            if not self._is_pure_identifier(value):
                                seg = self._create_frontmatter_segment(
                                    indexed_key, value, source_lang
                                )
                                segments.append(seg)

            elif rule.mode == FrontmatterMode.TRANSLATE_LIST:
                # For TRANSLATE_LIST, the final value is expected to be a list of strings
                # Use array-aware extraction to find all such lists
                matches = self._get_all_nested_values(frontmatter, key)

                if not matches:
                    # Fallback: try simple path
                    value = self._get_nested_value(frontmatter, key)
                    if isinstance(value, list):
                        for idx, item in enumerate(value):
                            if isinstance(item, str) and item.strip():
                                list_key = f"{key}[{idx}]"
                                seg = self._create_frontmatter_segment(
                                    list_key, item, source_lang
                                )
                                segments.append(seg)
                else:
                    # Process all matches - each match's value should be a list
                    for indexed_key, value in matches:
                        if isinstance(value, list):
                            for idx, item in enumerate(value):
                                if isinstance(item, str) and item.strip():
                                    list_key = f"{indexed_key}[{idx}]"
                                    seg = self._create_frontmatter_segment(
                                        list_key, item, source_lang
                                    )
                                    segments.append(seg)
                        elif isinstance(value, str) and value.strip():
                            # Single string match (array item was the string itself)
                            seg = self._create_frontmatter_segment(
                                indexed_key, value, source_lang
                            )
                            segments.append(seg)

            # PASSTHROUGH and COMPUTED don't generate segments

        return segments

    def extract_from_body(
        self, ast: list[ASTNode], source_lang: str
    ) -> list[Segment]:
        """
        Extract text nodes from AST per body rules.

        Args:
            ast: List of AST nodes
            source_lang: Source language code

        Returns:
            List of body segments
        """
        segments = []
        self._extract_from_nodes(ast, segments, source_lang, depth=0)
        return segments

    def _extract_from_nodes(
        self,
        nodes: list[ASTNode],
        segments: list[Segment],
        source_lang: str,
        depth: int,
        parent_type: NodeType | None = None,
    ):
        """Recursively extract segments from AST nodes."""
        for node in nodes:
            # Check if this node type should be preserved
            if node.type in self.preserve_blocks:
                continue

            # Extract based on node type
            if node.type == NodeType.PARAGRAPH:
                # Extract text from paragraph children
                text = self._extract_text_from_children(node.children)
                if text and text.strip():
                    seg = self._create_body_segment(
                        text,
                        node,
                        SegmentContextType.BODY_TEXT,
                        source_lang,
                        depth,
                        parent_type,
                    )
                    segments.append(seg)

            elif node.type == NodeType.HEADING:
                # Extract heading text
                text = self._extract_text_from_children(node.children)
                if text and text.strip():
                    seg = self._create_body_segment(
                        text,
                        node,
                        SegmentContextType.HEADING,
                        source_lang,
                        depth,
                        parent_type,
                    )
                    segments.append(seg)

            elif node.type == NodeType.LIST_ITEM:
                # Extract list item text
                text = self._extract_text_from_children(node.children)
                if text and text.strip():
                    seg = self._create_body_segment(
                        text,
                        node,
                        SegmentContextType.LIST_ITEM,
                        source_lang,
                        depth,
                        parent_type,
                    )
                    segments.append(seg)

            # Recurse into children for other node types
            if node.children:
                self._extract_from_nodes(
                    node.children,
                    segments,
                    source_lang,
                    depth + 1,
                    node.type,
                )

    def _extract_text_from_children(self, children: list[ASTNode]) -> str:
        """Extract concatenated text from child nodes."""
        text_parts = []

        for child in children:
            if child.type == NodeType.TEXT:
                text_parts.append(child.raw or "")
            elif child.type == NodeType.CODE_SPAN:
                # Preserve inline code
                text_parts.append(f"`{child.raw}`" if child.raw else "")
            elif child.type == NodeType.SOFT_BREAK:
                text_parts.append(" ")
            elif child.type == NodeType.LINE_BREAK:
                text_parts.append("\n")
            elif child.type == NodeType.INLINE_HTML:
                # Keep inline HTML as-is
                text_parts.append(child.raw or "")
            elif child.children:
                # Recurse for nested structures
                text_parts.append(self._extract_text_from_children(child.children))

        return "".join(text_parts)

    def _create_frontmatter_segment(
        self, key: str, value: str, source_lang: str
    ) -> Segment:
        """Create a segment from frontmatter field."""
        # Protect shortcodes and patterns
        protected_text, placeholder_map = self._protect_content(value)

        context = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key=key,
        )

        segment_id = Segment.create_id(
            value, context, self.site_profile.site_id
        )

        segment = Segment(
            id=segment_id,
            source_text=protected_text,
            context=context,
            site_id=self.site_profile.site_id,
            source_lang=source_lang,
            placeholder_map=placeholder_map,
        )

        # Protect terminology (TRM-05)
        self._protect_terminology(segment)

        return segment

    def _create_body_segment(
        self,
        text: str,
        node: ASTNode,
        context_type: SegmentContextType,
        source_lang: str,
        depth: int,
        parent_type: NodeType | None,
    ) -> Segment:
        """Create a segment from body text."""
        # Protect shortcodes and patterns
        protected_text, placeholder_map = self._protect_content(text)

        context = SegmentContext(
            context_type=context_type,
            node_id=node.node_id,
            parent_node_type=parent_type,
            depth=depth,
            metadata={
                "attrs": node.attrs,
            },
        )

        segment_id = Segment.create_id(
            text, context, self.site_profile.site_id
        )

        segment = Segment(
            id=segment_id,
            source_text=protected_text,
            context=context,
            site_id=self.site_profile.site_id,
            source_lang=source_lang,
            placeholder_map=placeholder_map,
        )

        # Protect terminology (TRM-05)
        self._protect_terminology(segment)

        return segment

    def _is_pure_identifier(self, text: str) -> bool:
        """Return True if the entire text is a non-translatable technical identifier.

        Used to skip frontmatter fields whose value is purely an API identifier
        (e.g. linkTitle/title = "VertexDeclaration") so they are never sent to
        the MT model — placeholders for pure identifiers confuse m2m100 which
        translates the token literally instead of preserving it.
        """
        t = text.strip()
        if not t:
            return False
        # Multi-hump PascalCase: VertexDeclaration, AnimationNode, FbxFormat
        if re.match(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+$", t):
            return True
        # PascalCase.With.Dots: Aspose.Slides, VertexDeclaration.Clear
        if re.match(r"^[A-Z][a-zA-Z0-9_]*(?:\.[A-Z][a-zA-Z0-9_]+)+$", t):
            return True
        # ALL_CAPS identifiers: API, SDK, ARGB
        if re.match(r"^[A-Z]{2,}(?:_[A-Z0-9]+)*$", t):
            return True
        # snake_case
        if "_" in t and t.replace("_", "").islower():
            return True
        # Matches any preserve_pattern in full
        all_patterns = self.shortcode_patterns + self.preserve_patterns
        for pat in all_patterns:
            try:
                if re.fullmatch(pat, t):
                    return True
            except re.error:
                pass
        return False

    def _protect_content(self, text: str) -> tuple[str, dict[str, str]]:
        """Protect non-translatable content with placeholders."""
        # m2m100 translates {PLACEHOLDER_N} tokens as prose (e.g. "Τον Χάρη 0") with no
        # recovery path — bypass placeholder substitution entirely for that model.
        if os.environ.get("BYPASS_PLACEHOLDER_PROTECTION"):
            return text, {}
        # Combine shortcode patterns with preserve patterns
        all_patterns = self.shortcode_patterns + self.preserve_patterns
        return self.placeholder_manager.protect(text, all_patterns)

    def _protect_terminology(self, segment: Segment) -> None:
        """
        Protect terminology in segment using TerminologyManager.

        This modifies the segment in-place, updating:
        - source_text: with terminology placeholders
        - protected_terms: list of ProtectedSegment objects
        - protection_metadata: debugging information

        Args:
            segment: Segment to protect (modified in-place)
        """
        if self.terminology_manager is None:
            # No terminology manager - skip protection
            return

        # Protect terminology in the segment's text
        protected_segment = self.terminology_manager.protect(
            segment.source_text,
            site=segment.site_id
        )

        # Only update if terms were actually protected
        if protected_segment.term_mapping:
            # Store the protected segment for later restoration
            segment.protected_terms.append(protected_segment)

            # Update the segment's source text with protected version
            segment.source_text = protected_segment.protected_text

            # Store metadata for debugging
            segment.protection_metadata = {
                'original_text': protected_segment.original_text,
                'terms_protected': len(protected_segment.term_mapping),
                'term_categories': list(set(
                    term.rule.category
                    for term in protected_segment.term_mapping.values()
                ))
            }

    def restore_terminology(self, translated_text: str, segment: Segment) -> str:
        """
        Restore protected terminology in translated text.

        This should be called on the translated segment text BEFORE reconstruction
        to restore any terminology that was protected during extraction.

        Args:
            translated_text: Translated text with terminology placeholders
            segment: Original segment with protected_terms

        Returns:
            Text with terminology placeholders replaced by original terms
        """
        if self.terminology_manager is None or not segment.protected_terms:
            # No protection was applied - return as-is
            return translated_text

        # Restore from each protected segment
        # (typically there should only be one, but we support multiple)
        restored_text = translated_text
        for protected_segment in segment.protected_terms:
            # Create a new ProtectedSegment with the translated text
            # but the same term mapping
            translated_protected = type(protected_segment)(
                original_text=protected_segment.original_text,
                protected_text=restored_text,
                term_mapping=protected_segment.term_mapping
            )
            restored_text = self.terminology_manager.restore(translated_protected)

        return restored_text

    def _get_nested_value(
        self, data: dict[str, Any], key: str
    ) -> Any | None:
        """
        Get value from nested dictionary using dot notation.

        For simple (non-array) paths only. For paths that may contain
        arrays, use _get_all_nested_values() instead.

        Args:
            data: Dictionary to search
            key: Dot-separated key path (e.g., "banner.title")

        Returns:
            Value if found, None otherwise
        """
        parts = key.split(".")
        current = data

        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None

        return current

    def _get_all_nested_values(
        self, data: dict[str, Any], key_pattern: str
    ) -> list[tuple[str, Any]]:
        """
        Get all values matching a key pattern, handling arrays in the path.

        When the path traverses through an array (list), this method iterates
        over all array items and continues the path resolution for each.

        Example:
            key_pattern: "body.block.title_left"
            data: {"body": {"block": [{"title_left": "A"}, {"title_left": "B"}]}}
            returns: [("body.block[0].title_left", "A"), ("body.block[1].title_left", "B")]

        Args:
            data: Dictionary to search
            key_pattern: Dot-separated key path (e.g., "body.block.title_left")

        Returns:
            List of (indexed_key, value) tuples for all matching values
        """
        parts = key_pattern.split(".")
        results: list[tuple[str, Any]] = []

        def traverse(current: Any, remaining_parts: list[str], current_path: str):
            """Recursively traverse the structure, handling arrays."""
            if not remaining_parts:
                # Reached the end of the path
                if current is not None:
                    results.append((current_path, current))
                return

            part = remaining_parts[0]
            rest = remaining_parts[1:]

            if isinstance(current, dict):
                # Normal dict traversal
                next_val = current.get(part)
                if next_val is not None:
                    next_path = f"{current_path}.{part}" if current_path else part
                    traverse(next_val, rest, next_path)

            elif isinstance(current, list):
                # Array detected - iterate over all items
                for idx, item in enumerate(current):
                    # Continue with the current part (not consumed yet)
                    # because the array is an intermediate step
                    indexed_path = f"{current_path}[{idx}]"
                    if isinstance(item, dict):
                        next_val = item.get(part)
                        if next_val is not None:
                            traverse(next_val, rest, f"{indexed_path}.{part}")
                    # If item is not a dict, we can't get 'part' from it

        # Start traversal
        traverse(data, parts, "")
        return results
