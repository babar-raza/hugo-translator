"""
YAML syntax validator for frontmatter validation.
"""

import re
from typing import Any

import yaml

from .base import ValidationResult, ValidationSeverity, Validator


class YAMLValidator(Validator):
    """
    Validates YAML frontmatter syntax and structure.

    Checks:
    - Valid YAML syntax
    - Proper escaping of special characters
    - Consistent key structure between source and translation
    - No unintended type changes
    """

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate YAML frontmatter.

        Args:
            source: Source frontmatter YAML
            translation: Translated frontmatter YAML
            context: Optional context with file_path, language pair

        Returns:
            ValidationResult with any YAML issues
        """
        result = ValidationResult(success=True)
        context = context or {}

        # Parse source YAML
        source_data = self._parse_yaml(source, "source", result)
        if source_data is None:
            result.success = False
            return result

        # Parse translation YAML
        translation_data = self._parse_yaml(translation, "translation", result)
        if translation_data is None:
            result.success = False
            return result

        # Check structure consistency
        self._check_structure(source_data, translation_data, result)

        # Check for type changes
        self._check_type_consistency(source_data, translation_data, result)

        # Check for dangerous characters
        self._check_dangerous_chars(translation, result)

        return result

    def _parse_yaml(
        self, yaml_str: str, label: str, result: ValidationResult
    ) -> dict[str, Any] | None:
        """
        Parse YAML string and report errors.

        Args:
            yaml_str: YAML string to parse
            label: Label for error messages ("source" or "translation")
            result: ValidationResult to add issues to

        Returns:
            Parsed YAML dict, or None if parsing failed
        """
        try:
            data = yaml.safe_load(yaml_str)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"{label} YAML must be a dictionary, got {type(data).__name__}",
                        location=label,
                    )
                )
                return None
            return data
        except yaml.YAMLError as e:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Invalid {label} YAML syntax: {str(e)}",
                    location=label,
                    details={"error": str(e)},
                )
            )
            return None

    def _check_structure(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        """
        Check that translation has same keys as source.

        Args:
            source: Source YAML data
            translation: Translation YAML data
            result: ValidationResult to add issues to
        """
        source_keys = set(source.keys())
        translation_keys = set(translation.keys())

        # Missing keys
        missing_keys = source_keys - translation_keys
        if missing_keys:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Translation missing keys: {', '.join(sorted(missing_keys))}",
                    location="frontmatter",
                    details={"missing_keys": list(missing_keys)},
                )
            )

        # Extra keys — ERROR: extra keys in translation likely means YAML keys were
        # translated (RC-3 defect class) or hallucinated by LLM.
        extra_keys = translation_keys - source_keys
        if extra_keys:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Translation has extra/translated keys (possible key translation): "
                    f"{', '.join(sorted(extra_keys))}",
                    location="frontmatter",
                    details={"extra_keys": list(extra_keys)},
                )
            )

    def _check_type_consistency(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        """
        Check that values maintain same types.

        Args:
            source: Source YAML data
            translation: Translation YAML data
            result: ValidationResult to add issues to
        """
        for key in source.keys():
            if key not in translation:
                continue  # Already reported as missing

            source_value = source[key]
            translation_value = translation[key]

            source_type = type(source_value).__name__
            translation_type = type(translation_value).__name__

            if source_type != translation_type:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"Type mismatch for '{key}': source is {source_type}, translation is {translation_type}",
                        location=f"frontmatter.{key}",
                        details={
                            "source_type": source_type,
                            "translation_type": translation_type,
                        },
                    )
                )

            # For lists, check length consistency
            if isinstance(source_value, list) and isinstance(translation_value, list):
                if len(source_value) != len(translation_value):
                    result.issues.append(
                        self.create_issue(
                            ValidationSeverity.WARNING,
                            f"List length mismatch for '{key}': source has {len(source_value)}, translation has {len(translation_value)}",
                            location=f"frontmatter.{key}",
                            details={
                                "source_length": len(source_value),
                                "translation_length": len(translation_value),
                            },
                        )
                    )

    def _check_dangerous_chars(
        self, yaml_str: str, result: ValidationResult
    ) -> None:
        """
        Check for characters that might break YAML parsing.

        Args:
            yaml_str: YAML string to check
            result: ValidationResult to add issues to
        """
        # Check for unquoted colons in values
        # Pattern: word characters followed by : followed by word characters (not at line start)
        unquoted_colon_pattern = r"^([^:\n]+):\s*([^'\"\n]*:[^'\"\n]*)\s*$"
        for line_num, line in enumerate(yaml_str.split("\n"), 1):
            if re.match(unquoted_colon_pattern, line):
                # Check if the value part has colons without quotes
                parts = line.split(":", 1)
                if len(parts) == 2:
                    value = parts[1].strip()
                    if ":" in value and not (
                        value.startswith(("'", '"')) or "|" in parts[1]
                    ):
                        result.issues.append(
                            self.create_issue(
                                ValidationSeverity.WARNING,
                                "Unquoted colon in value may cause parsing issues",
                                location=f"line {line_num}",
                                details={"line": line.strip()},
                            )
                        )

        # Check for unescaped quotes
        if yaml_str.count('"') % 2 != 0:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    "Odd number of double quotes detected - may indicate unescaped quote",
                    location="yaml",
                )
            )
