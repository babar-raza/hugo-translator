"""
YAML frontmatter formatting for Hugo documents.

Uses ruamel.yaml to preserve comments, quote styles, and literal block scalars.
"""
import re
from io import StringIO
from typing import Any, Dict, List, Union

import structlog
import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

logger = structlog.get_logger(__name__)

# Module-level ruamel.yaml instance for round-trip formatting
_yaml_dumper = YAML()
_yaml_dumper.preserve_quotes = True
_yaml_dumper.width = 4096  # Prevent line wrapping
_yaml_dumper.default_flow_style = False
_yaml_dumper.allow_duplicate_keys = True  # Hugo files may have duplicate keys


class YAMLFormatter:
    """Formats frontmatter as Hugo-compatible YAML.

    Uses ruamel.yaml for round-trip formatting that preserves:
    - YAML comments (# Static, # Head, etc.)
    - Quote styles (double, single, unquoted)
    - Literal block scalars (|)
    - Blank lines between sections
    """

    # Regex pattern to parse array indices from keys like "block[0]"
    INDEX_PATTERN = re.compile(r'^([^\[]+)(?:\[(\d+)\])?$')

    @staticmethod
    def format_frontmatter(data: Union[Dict[str, Any], CommentedMap]) -> str:
        """
        Format frontmatter dictionary as YAML with Hugo conventions.

        Uses ruamel.yaml for round-trip formatting that preserves comments,
        quote styles, and literal block scalars.

        Args:
            data: Frontmatter dictionary (CommentedMap for comment preservation)

        Returns:
            Formatted YAML string with --- delimiters
        """
        if not data:
            return ""

        try:
            # Use ruamel.yaml for round-trip formatting
            stream = StringIO()
            _yaml_dumper.dump(data, stream)
            yaml_content = stream.getvalue()
            logger.debug("yaml_format_success", preserved_comments=isinstance(data, CommentedMap))
        except Exception as e:
            # Fallback to PyYAML if ruamel.yaml fails
            logger.warning("yaml_ruamel_fallback", error=str(e))
            yaml_content = yaml.dump(
                dict(data) if isinstance(data, CommentedMap) else data,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=float("inf"),
            )

        # Wrap in Hugo frontmatter delimiters
        return f"---\n{yaml_content}---\n"

    @staticmethod
    def apply_literal_style(value: str) -> LiteralScalarString:
        """Convert a string to literal block scalar style (|).

        Use this for multi-line content that should preserve newlines and formatting.

        Args:
            value: String value to convert

        Returns:
            LiteralScalarString that will be dumped with | style
        """
        return LiteralScalarString(value)

    @staticmethod
    def should_use_literal_style(value: str) -> bool:
        """Determine if a string value should use literal block style (|).

        Literal style is preferred when content has:
        - Multiple lines AND list markers (- bullets)
        - Multiple paragraphs (double newlines)
        - Multi-line content that would be hard to read inline

        Args:
            value: String value to check

        Returns:
            True if literal style should be used
        """
        if not isinstance(value, str):
            return False

        # Must have newlines to warrant literal style
        if "\n" not in value:
            return False

        # Use literal style if:
        # 1. Has list markers (markdown bullets)
        has_list_markers = bool(re.search(r"^\s*[-*+]\s+", value, re.MULTILINE))

        # 2. Has multiple paragraphs (double newline)
        has_multiple_paragraphs = "\n\n" in value

        # 3. Has numbered list items
        has_numbered_list = bool(re.search(r"^\s*\d+\.\s+", value, re.MULTILINE))

        return has_list_markers or has_multiple_paragraphs or has_numbered_list

    @staticmethod
    def maybe_apply_literal_style(value: Any) -> Any:
        """Apply literal style to a value if appropriate.

        Automatically converts multi-line strings with bullets or paragraphs
        to LiteralScalarString for proper YAML formatting.

        Args:
            value: Value to potentially convert

        Returns:
            LiteralScalarString if literal style is needed, original value otherwise
        """
        if isinstance(value, str) and YAMLFormatter.should_use_literal_style(value):
            return LiteralScalarString(value)
        return value

    @staticmethod
    def set_nested_value(data: Dict[str, Any], key: str, value: Any) -> None:
        """
        Set value in nested dictionary using dot notation with array index support.

        Preserves CommentedMap structure when the parent is a CommentedMap.

        Args:
            data: Dictionary to modify (CommentedMap or dict)
            key: Dot-separated key path with optional array indices
                 (e.g., "banner.title" or "body.block[0].title_left")
            value: Value to set

        Example:
            data = {}
            set_nested_value(data, "banner.title", "Hello")
            # data = {"banner": {"title": "Hello"}}

            set_nested_value(data, "body.block[0].title", "First")
            # data = {"body": {"block": [{"title": "First"}]}}
        """
        parts = key.split(".")
        current = data

        # Helper to create the right dict type based on parent
        def create_dict(parent):
            if isinstance(parent, CommentedMap):
                return CommentedMap()
            return {}

        # Navigate to parent structure
        for i, part in enumerate(parts[:-1]):
            match = YAMLFormatter.INDEX_PATTERN.match(part)
            if not match:
                raise ValueError(f"Invalid key part: {part}")

            field = match.group(1)
            index = int(match.group(2)) if match.group(2) else None

            # Handle array index
            if index is not None:
                # This part has an index, so field must be a list
                if field not in current:
                    current[field] = []
                elif not isinstance(current[field], list):
                    current[field] = []

                # Extend array if needed
                while len(current[field]) <= index:
                    current[field].append(create_dict(current))

                current = current[field][index]
            else:
                # No index on this part, field should be a dict
                if field not in current:
                    current[field] = create_dict(current)
                elif not isinstance(current[field], dict):
                    # If it's not a dict, make it one (overwrite)
                    current[field] = create_dict(current)

                current = current[field]

        # Set final value
        final_part = parts[-1]
        match = YAMLFormatter.INDEX_PATTERN.match(final_part)
        if not match:
            raise ValueError(f"Invalid key part: {final_part}")

        field = match.group(1)
        index = int(match.group(2)) if match.group(2) else None

        # Auto-apply literal style for multi-line content with bullets/paragraphs
        final_value = YAMLFormatter.maybe_apply_literal_style(value)

        if index is not None:
            if field not in current:
                current[field] = []
            elif not isinstance(current[field], list):
                current[field] = []

            # Extend array if needed
            while len(current[field]) <= index:
                current[field].append(None)

            current[field][index] = final_value
        else:
            current[field] = final_value

    @staticmethod
    def get_nested_value(data: Dict[str, Any], key: str, default: Any = None) -> Any:
        """
        Get value from nested dictionary using dot notation with array index support.

        Args:
            data: Dictionary to search
            key: Dot-separated key path with optional array indices
                 (e.g., "banner.title" or "body.block[0].title_left")
            default: Default value if key not found

        Returns:
            Value if found, default otherwise
        """
        parts = key.split(".")
        current = data

        for part in parts:
            match = YAMLFormatter.INDEX_PATTERN.match(part)
            if not match:
                return default

            field = match.group(1)
            index = int(match.group(2)) if match.group(2) else None

            # Get field value
            if isinstance(current, dict):
                current = current.get(field)
            else:
                return default

            if current is None:
                return default

            # Handle array index
            if index is not None:
                if isinstance(current, list) and 0 <= index < len(current):
                    current = current[index]
                else:
                    return default

        return current
