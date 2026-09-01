"""
YAML frontmatter formatting for Hugo documents.

Uses ruamel.yaml to preserve comments, quote styles, and literal block scalars.
"""
import hashlib
import re
from io import StringIO
from typing import Any

# RC-D auto-correction: same fields as MetadataMarkdownContaminationValidator.
# Applied before serialization so the validator never needs to retry.
_RCD_CHECKED_FIELDS: frozenset[str] = frozenset(
    ["title", "description", "linktitle", "head_title", "head_description",
     "seoTitle", "summary"]
    + [f"step{i}" for i in range(1, 11)]
)
# Leading heading marker: value starts with one or more '#' followed by space
_RCD_LEADING_HASH_RE = re.compile(r"^#{1,6}\s+")
# Trailing orphaned '#' or '#.': NOT preceded by C or c (preserves C#)
_RCD_TRAILING_HASH_RE = re.compile(r"(?<![Cc])#\.?\s*$")

# HT-QUALITY-GATES-001 Part 25: CP1252 C1 control-range bytes (0x80-0x9F)
# that, when correctly interpreted, represent common punctuation (smart
# quotes, dashes, ellipsis) rather than genuine control characters. Confirmed
# real via direct reproduction: a `uk` retranslation produced literal U+0092
# in MT output, crashing YAML serialization ("unacceptable character #x0092:
# special characters are not allowed") -- the same known, pre-existing
# transient-failure class documented elsewhere in this session (the fr/ca
# retry failures during the original full retranslation). Mapping each byte
# to its actual intended character is correct here, not a guess: this is the
# standard, well-documented CP1252-vs-Latin1/control-range mismatch.
_CP1252_C1_MAP = {
    0x80: "€", 0x82: "‚", 0x83: "ƒ", 0x84: "„",
    0x85: "…", 0x86: "†", 0x87: "‡", 0x88: "ˆ",
    0x89: "‰", 0x8a: "Š", 0x8b: "‹", 0x8c: "Œ",
    0x8e: "Ž", 0x91: "‘", 0x92: "’", 0x93: "“",
    0x94: "”", 0x95: "•", 0x96: "–", 0x97: "—",
    0x98: "˜", 0x99: "™", 0x9a: "š", 0x9b: "›",
    0x9c: "œ", 0x9e: "ž", 0x9f: "Ÿ",
}
_CP1252_C1_RE = re.compile("[" + "".join(chr(c) for c in _CP1252_C1_MAP) + "]")

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
# Use documented indent() API (ruamel >= 0.16) to set 4-space indentation.
# This preserves Hugo convention and prevents block scalar indentation failures.
_yaml_dumper.indent(mapping=4, sequence=4, offset=2)


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
    def format_frontmatter(data: dict[str, Any] | CommentedMap) -> str:
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

        # RC-D: Strip orphaned Markdown heading markers from scalar fields
        # before serialization so MetadataMarkdownContaminationValidator never
        # needs to trigger a costly LLM retry for this systematic MT artifact.
        YAMLFormatter._strip_rcd_contamination(data)

        # HT-QUALITY-GATES-001 Part 25: fix CP1252-remnant C1 control chars
        # before they can crash YAML serialization (see _CP1252_C1_MAP above).
        YAMLFormatter._sanitize_cp1252_c1_chars(data)

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
                indent=4,
            )

        # RC-5: Post-serialization validation — fail before write if YAML is invalid.
        YAMLFormatter._validate_yaml_output(yaml_content)

        # Wrap in Hugo frontmatter delimiters
        return f"---\n{yaml_content}---\n"

    @staticmethod
    def _validate_yaml_output(yaml_content: str) -> None:
        """Raise ValueError if serialized YAML is not parseable by yaml.safe_load.

        Called by format_frontmatter() before returning. Prevents invalid YAML
        from reaching the file write step (RC-5 fix).
        """
        try:
            result = yaml.safe_load(yaml_content)
            if result is not None and not isinstance(result, dict):
                raise ValueError(
                    f"Serialized frontmatter YAML is not a mapping (got {type(result).__name__})"
                )
        except yaml.YAMLError as exc:
            raise ValueError(f"Serialized frontmatter YAML is invalid: {exc}") from exc

    @staticmethod
    def _strip_rcd_contamination(data: dict[str, Any] | CommentedMap) -> None:
        """RC-D auto-correction: strip orphaned Markdown '#' markers in-place.

        MT models systematically produce trailing '#' when the English source
        title ends with 'C#'. This strips the artefact before serialization so
        the MetadataMarkdownContaminationValidator never needs to retry.

        Only top-level scalar fields in _RCD_CHECKED_FIELDS are touched.
        The C# programming language marker is preserved: the regex requires
        that the '#' is NOT immediately preceded by 'C' or 'c'.
        """
        for field in _RCD_CHECKED_FIELDS:
            value = data.get(field)
            if not isinstance(value, str) or not value:
                continue
            original = value
            # Strip leading heading marker (e.g. "# Title" → "Title")
            value = _RCD_LEADING_HASH_RE.sub("", value)
            # Strip trailing orphaned # or #. (e.g. "...語を削除#" → "...語を削除")
            value = _RCD_TRAILING_HASH_RE.sub("", value).rstrip()
            if value != original:
                data[field] = value
                logger.info(
                    "rcd_autocorrect",
                    field=field,
                    before_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
                    after_sha256=hashlib.sha256(value.encode("utf-8")).hexdigest(),
                    before_length=len(original),
                    after_length=len(value),
                )

    @staticmethod
    def _sanitize_cp1252_c1_chars(data: dict[str, Any] | CommentedMap) -> None:
        """Recursively replace CP1252-remnant C1 control chars in-place with
        their actual intended punctuation (see _CP1252_C1_MAP), so a real
        MT-output artifact never crashes YAML serialization with
        "unacceptable character #xNNNN". Walks dicts, lists, and scalar
        strings (including LiteralScalarString, preserving its block style).
        """

        def fix(value: str) -> str:
            return _CP1252_C1_RE.sub(lambda m: _CP1252_C1_MAP[ord(m.group(0))], value)

        def walk(obj: Any) -> Any:
            if isinstance(obj, dict):
                for key in list(obj.keys()):
                    obj[key] = walk(obj[key])
                return obj
            if isinstance(obj, list):
                for i in range(len(obj)):
                    obj[i] = walk(obj[i])
                return obj
            if isinstance(obj, str):
                fixed = fix(obj)
                if fixed != obj:
                    if isinstance(obj, LiteralScalarString):
                        return LiteralScalarString(fixed)
                    return fixed
                return obj
            return obj

        walk(data)

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
    def set_nested_value(data: dict[str, Any], key: str, value: Any) -> None:
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
    def get_nested_value(data: dict[str, Any], key: str, default: Any = None) -> Any:
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
