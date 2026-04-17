"""
Multiline content handler for structure-preserving translation.

Implements the line-by-line translation pattern from legacy/ast2md-converter.py
to preserve bullet point structure, indentation, and newlines during translation.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def normalize_newlines(text: str) -> str:
    """
    Normalize escaped newline sequences to actual newlines.

    Handles:
    - \\\\n (escaped backslash-n in Python string) -> newline
    - \\n (literal backslash-n) -> newline
    - \\r\\n -> \\n (normalize Windows line endings)

    Reference: legacy/ast2md-converter.py lines 233-234

    Args:
        text: Input text potentially containing escaped newlines

    Returns:
        Text with escaped newlines converted to actual newlines
    """
    # Normalize Windows line endings first
    result = text.replace('\r\n', '\n')

    # Handle escaped newlines (\\n literal in source)
    # Pattern: backslash followed by 'n' -> actual newline
    result = re.sub(r'\\n', '\n', result)

    return result


@dataclass
class LineInfo:
    """Information about a single line for translation."""

    original: str
    indent: str
    prefix: str  # Bullet prefix like "- ", "* ", "1. "
    content: str  # Translatable content
    is_empty: bool
    line_index: int


@dataclass
class MultilineResult:
    """Result of multiline translation."""

    translated_text: str
    line_count_source: int
    line_count_translated: int
    structure_preserved: bool
    lines_info: list[LineInfo] = field(default_factory=list)


class MultilineHandler:
    """
    Handler for translating multiline content while preserving structure.

    This handler splits multiline text into individual lines, translates each
    line separately, and reassembles them with the original structure intact.

    Key features:
    - Preserves line count (input lines == output lines)
    - Preserves indentation whitespace exactly
    - Preserves bullet prefixes (-, *, 1., etc.)
    - Handles empty lines without translation
    - Normalizes escaped newlines before processing
    """

    # Pattern to detect bullet list prefixes
    BULLET_PATTERN = re.compile(r'^([-*+]\s+|\d+[.)]\s+)')

    # Pattern to detect block quote prefix
    BLOCKQUOTE_PATTERN = re.compile(r'^(>\s*)+')

    def __init__(self, normalize_escapes: bool = True):
        """
        Initialize the multiline handler.

        Args:
            normalize_escapes: Whether to normalize escaped newlines (default True)
        """
        self.normalize_escapes = normalize_escapes

    def is_multiline(self, text: str) -> bool:
        """
        Check if text contains multiple lines requiring special handling.

        Args:
            text: Text to check

        Returns:
            True if text contains newlines
        """
        return '\n' in text or '\\n' in text

    def parse_lines(self, text: str) -> list[LineInfo]:
        """
        Parse multiline text into structured line information.

        Args:
            text: Multiline text to parse

        Returns:
            List of LineInfo objects describing each line
        """
        # Normalize escaped newlines if enabled
        if self.normalize_escapes:
            text = normalize_newlines(text)

        lines = text.split('\n')
        result = []

        for idx, line in enumerate(lines):
            # Separate indentation from content
            stripped = line.lstrip()
            indent = line[:len(line) - len(stripped)]

            # Check for empty line
            if not stripped:
                result.append(LineInfo(
                    original=line,
                    indent=indent,
                    prefix='',
                    content='',
                    is_empty=True,
                    line_index=idx
                ))
                continue

            # Check for bullet/numbered list prefix
            bullet_match = self.BULLET_PATTERN.match(stripped)
            if bullet_match:
                prefix = bullet_match.group(1)
                content = stripped[len(prefix):]
                result.append(LineInfo(
                    original=line,
                    indent=indent,
                    prefix=prefix,
                    content=content,
                    is_empty=False,
                    line_index=idx
                ))
                continue

            # Check for blockquote prefix
            quote_match = self.BLOCKQUOTE_PATTERN.match(stripped)
            if quote_match:
                prefix = quote_match.group(0)
                content = stripped[len(prefix):]
                result.append(LineInfo(
                    original=line,
                    indent=indent,
                    prefix=prefix,
                    content=content,
                    is_empty=False,
                    line_index=idx
                ))
                continue

            # Regular text line
            result.append(LineInfo(
                original=line,
                indent=indent,
                prefix='',
                content=stripped,
                is_empty=False,
                line_index=idx
            ))

        return result

    def translate(
        self,
        text: str,
        translate_fn: Callable[[str], str],
        skip_empty: bool = True
    ) -> MultilineResult:
        """
        Translate multiline text while preserving structure.

        Args:
            text: Multiline text to translate
            translate_fn: Function to translate a single line of text
            skip_empty: Skip translation of empty lines (default True)

        Returns:
            MultilineResult with translated text and metadata
        """
        # Parse into line info
        lines_info = self.parse_lines(text)
        source_line_count = len(lines_info)

        translated_lines = []

        for line_info in lines_info:
            if line_info.is_empty:
                # Preserve empty lines as-is
                translated_lines.append(line_info.original)
                logger.debug(f"Line {line_info.line_index}: empty, preserved")
                continue

            if not line_info.content.strip():
                # Line has structure but no translatable content
                translated_lines.append(
                    f"{line_info.indent}{line_info.prefix}{line_info.content}"
                )
                logger.debug(f"Line {line_info.line_index}: no content, preserved structure")
                continue

            # Translate the content
            try:
                translated_content = translate_fn(line_info.content)
            except Exception as e:
                logger.warning(
                    f"Translation failed for line {line_info.line_index}: {e}. "
                    f"Keeping original."
                )
                translated_content = line_info.content

            # Reassemble with preserved structure
            translated_line = f"{line_info.indent}{line_info.prefix}{translated_content}"
            translated_lines.append(translated_line)
            logger.debug(
                f"Line {line_info.line_index}: translated "
                f"'{line_info.content[:30]}...' -> '{translated_content[:30]}...'"
            )

        # Rejoin with newlines
        translated_text = '\n'.join(translated_lines)
        translated_line_count = len(translated_lines)

        # Check structure preservation
        structure_preserved = source_line_count == translated_line_count

        if not structure_preserved:
            logger.warning(
                f"Structure drift detected: {source_line_count} source lines "
                f"-> {translated_line_count} translated lines"
            )

        return MultilineResult(
            translated_text=translated_text,
            line_count_source=source_line_count,
            line_count_translated=translated_line_count,
            structure_preserved=structure_preserved,
            lines_info=lines_info
        )

    def translate_simple(
        self,
        text: str,
        translate_fn: Callable[[str], str]
    ) -> str:
        """
        Simple translation interface returning just the translated text.

        This is a convenience method for integration points that don't need
        the full MultilineResult metadata.

        Args:
            text: Multiline text to translate
            translate_fn: Function to translate a single line of text

        Returns:
            Translated text with structure preserved
        """
        result = self.translate(text, translate_fn)
        return result.translated_text


def translate_multiline(
    text: str,
    translate_fn: Callable[[str], str],
    normalize_escapes: bool = True
) -> str:
    """
    Convenience function for multiline translation.

    This is the primary entry point for translating multiline content
    with structure preservation.

    Args:
        text: Multiline text to translate
        translate_fn: Function to translate a single line of text
        normalize_escapes: Whether to normalize escaped newlines

    Returns:
        Translated text with structure preserved

    Example:
        >>> def my_translate(text):
        ...     return text.upper()  # Simple example
        >>> result = translate_multiline("- Item 1\\n- Item 2", my_translate)
        >>> print(result)
        - ITEM 1
        - ITEM 2
    """
    handler = MultilineHandler(normalize_escapes=normalize_escapes)
    return handler.translate_simple(text, translate_fn)
