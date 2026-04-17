"""
Quality Validator for Translated Hugo Files

Provides comprehensive validation for translated Hugo markdown files including:
- Frontmatter YAML validation
- Placeholder integrity
- Link validity (relative paths exist)
- Code block balance
- Heading structure preservation
- List structure preservation
"""

import re
from pathlib import Path
from typing import Any

import yaml

from ..translation_engine.validation import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)


class QualityValidator:
    """
    Comprehensive quality validator for translated Hugo files.

    Validates:
    - YAML frontmatter syntax
    - Placeholder balance
    - Code block balance
    - Link validity
    - Heading structure
    - List structure
    """

    def __init__(self, base_dir: Path | None = None):
        """
        Initialize quality validator.

        Args:
            base_dir: Base directory for resolving relative links (optional)
        """
        self.base_dir = base_dir

    def validate_file(
        self,
        source_path: Path,
        translation_path: Path,
        target_lang: str,
    ) -> ValidationResult:
        """
        Validate a translated file against its source.

        Args:
            source_path: Path to source file
            translation_path: Path to translated file
            target_lang: Target language code

        Returns:
            ValidationResult with all detected issues
        """
        result = ValidationResult(success=True, file_path=translation_path)

        # Read files
        try:
            with open(source_path, encoding='utf-8') as f:
                source_content = f.read()
        except Exception as e:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="QualityValidator",
                    message=f"Failed to read source file: {e}",
                    location=str(source_path),
                )
            )
            result.success = False
            return result

        try:
            with open(translation_path, encoding='utf-8') as f:
                translation_content = f.read()
        except Exception as e:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="QualityValidator",
                    message=f"Failed to read translation file: {e}",
                    location=str(translation_path),
                )
            )
            result.success = False
            return result

        # Validate content
        return self.validate_content(
            source_content,
            translation_content,
            context={
                "source_path": str(source_path),
                "translation_path": str(translation_path),
                "target_lang": target_lang,
            },
        )

    def validate_content(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate translated content against source.

        Args:
            source: Source markdown content
            translation: Translated markdown content
            context: Optional context information

        Returns:
            ValidationResult with all detected issues
        """
        result = ValidationResult(success=True)
        context = context or {}

        # Split into frontmatter and body
        source_fm, source_body = self._split_frontmatter(source)
        trans_fm, trans_body = self._split_frontmatter(translation)

        # Validate frontmatter YAML
        fm_result = self._validate_frontmatter(source_fm, trans_fm, context)
        result.merge(fm_result)

        # Validate placeholders
        placeholder_result = self._validate_placeholders(source_body, trans_body, context)
        result.merge(placeholder_result)

        # Validate code blocks
        code_result = self._validate_code_blocks(source_body, trans_body, context)
        result.merge(code_result)

        # Validate heading structure
        heading_result = self._validate_headings(source_body, trans_body, context)
        result.merge(heading_result)

        # Validate list structure
        list_result = self._validate_lists(source_body, trans_body, context)
        result.merge(list_result)

        # Validate links
        link_result = self._validate_links(trans_body, context)
        result.merge(link_result)

        # Set overall success based on errors
        result.success = not result.has_errors()

        return result

    def _split_frontmatter(self, content: str) -> tuple[str, str]:
        """
        Split content into frontmatter and body.

        Args:
            content: Full markdown content

        Returns:
            Tuple of (frontmatter_text, body_text)
        """
        # Match YAML frontmatter
        fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
        if fm_match:
            return fm_match.group(1), fm_match.group(2)
        return "", content

    def _validate_frontmatter(
        self,
        source_fm: str,
        trans_fm: str,
        context: dict[str, Any],
    ) -> ValidationResult:
        """Validate frontmatter YAML syntax and structure."""
        result = ValidationResult(success=True)

        # Validate source YAML parses
        if source_fm:
            try:
                source_data = yaml.safe_load(source_fm)
            except yaml.YAMLError as e:
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        validator="QualityValidator",
                        message=f"Source frontmatter YAML error: {e}",
                        location="frontmatter",
                    )
                )
                return result

        # Validate translation YAML parses
        if trans_fm:
            try:
                trans_data = yaml.safe_load(trans_fm)
            except yaml.YAMLError as e:
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        validator="QualityValidator",
                        message=f"Translation frontmatter YAML error: {e}",
                        location="frontmatter",
                        details={"error": str(e)},
                    )
                )
                return result

            # Check for required keys
            if source_fm:
                source_keys = set(source_data.keys()) if source_data else set()
                trans_keys = set(trans_data.keys()) if trans_data else set()

                # Missing keys
                missing_keys = source_keys - trans_keys
                if missing_keys:
                    result.issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            validator="QualityValidator",
                            message=f"Missing frontmatter keys in translation: {', '.join(missing_keys)}",
                            location="frontmatter",
                            details={"missing_keys": list(missing_keys)},
                        )
                    )

                # Extra keys
                extra_keys = trans_keys - source_keys
                if extra_keys:
                    result.issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.INFO,
                            validator="QualityValidator",
                            message=f"Extra frontmatter keys in translation: {', '.join(extra_keys)}",
                            location="frontmatter",
                            details={"extra_keys": list(extra_keys)},
                        )
                    )

        return result

    def _validate_placeholders(
        self,
        source: str,
        translation: str,
        context: dict[str, Any],
    ) -> ValidationResult:
        """Validate placeholder balance."""
        result = ValidationResult(success=True)

        # Extract placeholders from both
        placeholder_patterns = [
            r'\{\{[^}]+\}\}',  # Hugo variables
            r'\{%[^%]+%\}',    # Hugo tags
            r'\{\{<[^>]+>\}\}',  # Hugo shortcodes
        ]

        for pattern in placeholder_patterns:
            source_placeholders = set(re.findall(pattern, source))
            trans_placeholders = set(re.findall(pattern, translation))

            # Check missing placeholders
            missing = source_placeholders - trans_placeholders
            if missing:
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        validator="QualityValidator",
                        message=f"Missing placeholders in translation: {', '.join(list(missing)[:5])}",
                        location="body",
                        details={"missing_count": len(missing), "missing": list(missing)},
                    )
                )

            # Check extra placeholders
            extra = trans_placeholders - source_placeholders
            if extra:
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        validator="QualityValidator",
                        message=f"Extra placeholders in translation: {', '.join(list(extra)[:5])}",
                        location="body",
                        details={"extra_count": len(extra), "extra": list(extra)},
                    )
                )

        return result

    def _validate_code_blocks(
        self,
        source: str,
        translation: str,
        context: dict[str, Any],
    ) -> ValidationResult:
        """Validate code block balance."""
        result = ValidationResult(success=True)

        # Count code block fences
        source_fences = source.count('```')
        trans_fences = translation.count('```')

        if source_fences % 2 != 0:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="QualityValidator",
                    message=f"Unbalanced code blocks in source (odd number of ```): {source_fences}",
                    location="body",
                )
            )

        if trans_fences % 2 != 0:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="QualityValidator",
                    message=f"Unbalanced code blocks in translation (odd number of ```): {trans_fences}",
                    location="body",
                    details={"fence_count": trans_fences},
                )
            )

        # Check if count matches (they should have same number of code blocks)
        if source_fences != trans_fences and source_fences % 2 == 0 and trans_fences % 2 == 0:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="QualityValidator",
                    message=f"Different number of code blocks: source={source_fences//2}, translation={trans_fences//2}",
                    location="body",
                )
            )

        return result

    def _validate_headings(
        self,
        source: str,
        translation: str,
        context: dict[str, Any],
    ) -> ValidationResult:
        """Validate heading structure is preserved."""
        result = ValidationResult(success=True)

        # Extract heading levels
        def get_heading_levels(text: str) -> list[int]:
            levels = []
            for line in text.split('\n'):
                match = re.match(r'^(#{1,6})\s+', line)
                if match:
                    levels.append(len(match.group(1)))
            return levels

        source_levels = get_heading_levels(source)
        trans_levels = get_heading_levels(translation)

        if source_levels != trans_levels:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="QualityValidator",
                    message=f"Heading structure mismatch: source has {len(source_levels)} headings, translation has {len(trans_levels)}",
                    location="body",
                    details={
                        "source_levels": source_levels,
                        "translation_levels": trans_levels,
                    },
                )
            )

        return result

    def _validate_lists(
        self,
        source: str,
        translation: str,
        context: dict[str, Any],
    ) -> ValidationResult:
        """Validate list structure is preserved."""
        result = ValidationResult(success=True)

        # Count list items (rough estimate)
        def count_list_items(text: str) -> int:
            count = 0
            for line in text.split('\n'):
                if re.match(r'^\s*[-*+]\s+', line) or re.match(r'^\s*\d+\.\s+', line):
                    count += 1
            return count

        source_items = count_list_items(source)
        trans_items = count_list_items(translation)

        # Allow some flexibility (within 20%)
        if trans_items < source_items * 0.8 or trans_items > source_items * 1.2:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="QualityValidator",
                    message=f"List item count mismatch: source has ~{source_items} items, translation has ~{trans_items}",
                    location="body",
                    details={
                        "source_count": source_items,
                        "translation_count": trans_items,
                    },
                )
            )

        return result

    def _validate_links(
        self,
        translation: str,
        context: dict[str, Any],
    ) -> ValidationResult:
        """Validate link structure and relative paths."""
        result = ValidationResult(success=True)

        # Extract all markdown links
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        links = re.findall(link_pattern, translation)

        for link_text, link_url in links:
            # Check for broken link structure
            if not link_url.strip():
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        validator="QualityValidator",
                        message=f"Empty link URL for text: [{link_text}]",
                        location="body",
                    )
                )

            # Check relative links if base_dir is set
            if self.base_dir and not link_url.startswith(('http://', 'https://', 'mailto:', '#')):
                # Relative link - check if file exists
                link_path = self.base_dir / link_url.lstrip('/')
                if not link_path.exists():
                    result.issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            validator="QualityValidator",
                            message=f"Relative link not found: {link_url}",
                            location="body",
                            details={"link_text": link_text, "link_url": link_url},
                        )
                    )

        return result

    def validate_directory(
        self,
        source_dir: Path,
        translation_dir: Path,
        target_lang: str,
        recursive: bool = True,
    ) -> dict[str, ValidationResult]:
        """
        Validate all translated files in a directory.

        Args:
            source_dir: Source directory
            translation_dir: Translation directory
            target_lang: Target language code
            recursive: Whether to recurse into subdirectories

        Returns:
            Dictionary mapping file paths to ValidationResult
        """
        results = {}

        # Find all markdown files in translation directory
        pattern = "**/*.md" if recursive else "*.md"
        for trans_file in translation_dir.glob(pattern):
            # Determine corresponding source file
            rel_path = trans_file.relative_to(translation_dir)
            source_file = source_dir / rel_path

            if source_file.exists():
                result = self.validate_file(source_file, trans_file, target_lang)
                results[str(trans_file)] = result
            else:
                # No source file found
                result = ValidationResult(success=False, file_path=trans_file)
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        validator="QualityValidator",
                        message=f"No corresponding source file found at {source_file}",
                        location=str(trans_file),
                    )
                )
                results[str(trans_file)] = result

        return results
