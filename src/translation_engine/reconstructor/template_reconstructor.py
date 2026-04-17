"""
Template-based reconstruction that preserves exact source file formatting.

Uses the source (EN) file as a template, replacing only translatable values
while preserving all comments, whitespace, quotes, and structure.
"""
import re
from io import StringIO
from typing import Any

import structlog
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)

from ..extractor import Segment, SegmentContextType

logger = structlog.get_logger(__name__)


class TemplateReconstructor:
    """Reconstructs translated files using source file as template.

    This approach preserves the exact structure of the source file:
    - YAML comments (# Static, # Head, etc.)
    - Quote styles (double, single, unquoted)
    - Literal block scalars (|)
    - Blank lines between sections
    - Indentation and formatting
    """

    def __init__(self):
        """Initialize the template reconstructor."""
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.width = 4096
        self.yaml.allow_duplicate_keys = True

    def reconstruct_from_template(
        self,
        source_content: str,
        translations: dict[str, str],
        segment_map: dict[str, Segment],
    ) -> str:
        """
        Reconstruct translated file using source as template.

        Args:
            source_content: Original source file content (EN)
            translations: Map of segment_id -> translated_text
            segment_map: Map of segment_id -> Segment for context

        Returns:
            Reconstructed file content with translations applied
        """
        # Split frontmatter from body
        parts = source_content.split("---", 2)
        if len(parts) < 3:
            raise ValueError("Invalid Hugo frontmatter format")

        yaml_content = parts[1]
        body_content = parts[2]

        # Parse YAML while preserving structure
        frontmatter = self.yaml.load(StringIO(yaml_content))

        if frontmatter is None:
            frontmatter = CommentedMap()

        # Apply translations to frontmatter
        self._apply_frontmatter_translations(frontmatter, translations, segment_map)

        # Apply translations to body
        translated_body = self._apply_body_translations(
            body_content, translations, segment_map
        )

        # Dump frontmatter preserving formatting
        output_stream = StringIO()
        self.yaml.dump(frontmatter, output_stream)
        new_yaml = output_stream.getvalue()

        logger.debug(
            "template_reconstruction_complete",
            frontmatter_translations=len(
                [
                    s
                    for s in segment_map.values()
                    if s.context.context_type == SegmentContextType.FRONTMATTER
                ]
            ),
            body_translations=len(
                [
                    s
                    for s in segment_map.values()
                    if s.context.context_type != SegmentContextType.FRONTMATTER
                ]
            ),
        )

        return f"---\n{new_yaml}---{translated_body}"

    def _apply_frontmatter_translations(
        self,
        data: CommentedMap,
        translations: dict[str, str],
        segment_map: dict[str, Segment],
    ) -> None:
        """Apply translations to frontmatter, preserving structure."""
        for segment_id, translated_text in translations.items():
            segment = segment_map.get(segment_id)
            if not segment:
                continue

            if segment.context.context_type != SegmentContextType.FRONTMATTER:
                continue

            key = segment.context.frontmatter_key
            if not key:
                continue

            try:
                self._set_value_preserving_style(data, key, translated_text)
                logger.debug(
                    "frontmatter_value_set",
                    key=key,
                    translated_length=len(translated_text),
                )
            except Exception as e:
                logger.warning(
                    "frontmatter_set_failed",
                    key=key,
                    error=str(e),
                )

    def _apply_body_translations(
        self,
        body_content: str,
        translations: dict[str, str],
        segment_map: dict[str, Segment],
    ) -> str:
        """Apply translations to body content.

        For template-based reconstruction, we replace source text with
        translated text in the body while preserving formatting around it.
        """
        translated_body = body_content

        # Get body segments and their translations
        body_segments = [
            (segment_id, segment_map[segment_id])
            for segment_id in translations
            if segment_id in segment_map
            and segment_map[segment_id].context.context_type
            != SegmentContextType.FRONTMATTER
        ]

        # Sort by length (longest first) to avoid substring replacement issues
        body_segments.sort(key=lambda x: len(x[1].source_text), reverse=True)

        for segment_id, segment in body_segments:
            translated_text = translations.get(segment_id)
            if translated_text and segment.source_text in translated_body:
                translated_body = translated_body.replace(
                    segment.source_text, translated_text, 1
                )

        return translated_body

    def _set_value_preserving_style(
        self,
        data: CommentedMap,
        key: str,
        value: str,
    ) -> None:
        """Set value while preserving original scalar style."""
        # Parse key path
        parts = self._parse_key_path(key)
        current = data

        # Navigate to parent
        for part in parts[:-1]:
            if part["index"] is not None:
                current = current[part["field"]][part["index"]]
            else:
                current = current[part["field"]]

        # Get final location
        final = parts[-1]
        if final["index"] is not None:
            target = current[final["field"]]
            old_value = target[final["index"]]
        else:
            old_value = current.get(final["field"])

        # Preserve scalar style from original or auto-detect
        new_value = self._create_styled_value(old_value, value)

        # Set value
        if final["index"] is not None:
            current[final["field"]][final["index"]] = new_value
        else:
            current[final["field"]] = new_value

    def _create_styled_value(self, old_value: Any, new_value: str) -> Any:
        """Create a new value with the same style as the old value.

        If the old value has a specific style (literal, double-quoted, etc.),
        apply that style to the new value. Otherwise, auto-detect based on content.
        """
        if isinstance(old_value, LiteralScalarString):
            return LiteralScalarString(new_value)
        elif isinstance(old_value, DoubleQuotedScalarString):
            return DoubleQuotedScalarString(new_value)
        elif isinstance(old_value, SingleQuotedScalarString):
            return SingleQuotedScalarString(new_value)
        elif self._should_use_literal_style(new_value):
            # Auto-apply literal style for multi-line content with bullets/paragraphs
            return LiteralScalarString(new_value)
        else:
            return new_value

    def _should_use_literal_style(self, value: str) -> bool:
        """Determine if a string value should use literal block style."""
        if not isinstance(value, str) or "\n" not in value:
            return False

        has_list_markers = bool(re.search(r"^\s*[-*+]\s+", value, re.MULTILINE))
        has_multiple_paragraphs = "\n\n" in value
        has_numbered_list = bool(re.search(r"^\s*\d+\.\s+", value, re.MULTILINE))

        return has_list_markers or has_multiple_paragraphs or has_numbered_list

    def _parse_key_path(self, key: str) -> list[dict[str, Any]]:
        """Parse key path like 'body.block[0].title' into components."""
        pattern = re.compile(r"^([^\[]+)(?:\[(\d+)\])?$")

        result = []
        for part in key.split("."):
            match = pattern.match(part)
            if match:
                result.append(
                    {
                        "field": match.group(1),
                        "index": int(match.group(2)) if match.group(2) else None,
                    }
                )
            else:
                # Handle parts without index
                result.append({"field": part, "index": None})
        return result
