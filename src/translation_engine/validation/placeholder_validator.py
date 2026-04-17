"""
Placeholder integrity validator.

Ensures that placeholders (for code, links, shortcodes, etc.) are preserved
correctly in translations.
"""

import re
from typing import Any

from .base import ValidationResult, ValidationSeverity, Validator


class PlaceholderValidator(Validator):
    """
    Validates placeholder integrity in translations.

    Checks:
    - All source placeholders appear in translation
    - No extra placeholders in translation
    - Placeholders appear in correct order (if strict_order=True)
    - Placeholder syntax is valid
    """

    def __init__(
        self,
        placeholder_pattern: str = r"\{\{([A-Z_]+)_(\d+)\}\}",
        strict_order: bool = False,
        name: str | None = None,
    ):
        """
        Initialize placeholder validator.

        Args:
            placeholder_pattern: Regex pattern for placeholders
            strict_order: Whether to enforce placeholder order
            name: Optional custom name
        """
        super().__init__(name)
        self.placeholder_pattern = placeholder_pattern
        self.strict_order = strict_order

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate placeholder integrity.

        Args:
            source: Source text with placeholders
            translation: Translated text with placeholders
            context: Optional context

        Returns:
            ValidationResult with any placeholder issues
        """
        result = ValidationResult(success=True)

        # Extract placeholders
        source_placeholders = self._extract_placeholders(source)
        translation_placeholders = self._extract_placeholders(translation)

        # Check for missing placeholders
        missing = source_placeholders - translation_placeholders
        if missing:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Missing placeholders in translation: {', '.join(sorted(missing))}",
                    location="placeholders",
                    details={"missing": list(missing)},
                )
            )
            result.success = False

        # Check for extra placeholders
        extra = translation_placeholders - source_placeholders
        if extra:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Extra placeholders in translation: {', '.join(sorted(extra))}",
                    location="placeholders",
                    details={"extra": list(extra)},
                )
            )
            result.success = False

        # Check order if strict
        if self.strict_order and not missing and not extra:
            self._check_order(source, translation, result)

        # Check for frequency mismatches
        self._check_frequency(source, translation, result)

        return result

    def _extract_placeholders(self, text: str) -> set[str]:
        """
        Extract all placeholders from text.

        Args:
            text: Text to extract from

        Returns:
            Set of placeholder strings
        """
        matches = re.findall(self.placeholder_pattern, text)
        return {f"{{{{{prefix}_{num}}}}}" for prefix, num in matches}

    def _check_order(
        self, source: str, translation: str, result: ValidationResult
    ) -> None:
        """
        Check that placeholders appear in same order.

        Args:
            source: Source text
            translation: Translation text
            result: ValidationResult to add issues to
        """
        source_order = [
            match.group(0) for match in re.finditer(self.placeholder_pattern, source)
        ]
        translation_order = [
            match.group(0)
            for match in re.finditer(self.placeholder_pattern, translation)
        ]

        if source_order != translation_order:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    "Placeholder order differs between source and translation",
                    location="placeholders",
                    details={
                        "source_order": source_order,
                        "translation_order": translation_order,
                    },
                )
            )

    def _check_frequency(
        self, source: str, translation: str, result: ValidationResult
    ) -> None:
        """
        Check that each placeholder appears same number of times.

        Args:
            source: Source text
            translation: Translation text
            result: ValidationResult to add issues to
        """
        source_counts: dict[str, int] = {}
        translation_counts: dict[str, int] = {}

        # Count occurrences
        for match in re.finditer(self.placeholder_pattern, source):
            placeholder = match.group(0)
            source_counts[placeholder] = source_counts.get(placeholder, 0) + 1

        for match in re.finditer(self.placeholder_pattern, translation):
            placeholder = match.group(0)
            translation_counts[placeholder] = translation_counts.get(placeholder, 0) + 1

        # Check for frequency mismatches
        all_placeholders = set(source_counts.keys()) | set(translation_counts.keys())
        for placeholder in all_placeholders:
            source_count = source_counts.get(placeholder, 0)
            translation_count = translation_counts.get(placeholder, 0)

            if source_count != translation_count:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.WARNING,
                        f"Placeholder frequency mismatch for {placeholder}: source has {source_count}, translation has {translation_count}",
                        location="placeholders",
                        details={
                            "placeholder": placeholder,
                            "source_count": source_count,
                            "translation_count": translation_count,
                        },
                    )
                )
