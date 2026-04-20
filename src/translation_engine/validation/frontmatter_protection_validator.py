"""
Frontmatter protection validator for enforcing site profile rules.

This validator ensures that frontmatter fields follow site profile rules:
- PASSTHROUGH fields remain unchanged
- IGNORE fields are not present in output
- COMPUTED fields have valid values
"""

import re
from datetime import date, datetime
from typing import Any

import yaml

from ...utils.models import FrontmatterMode, SiteProfile
from .base import ValidationResult, ValidationSeverity, Validator


class FrontmatterProtectionValidator(Validator):
    """
    Validates frontmatter fields against site profile rules.

    Checks:
    - PASSTHROUGH fields are unchanged (url, date, etc.)
    - IGNORE fields are not present in translation output
    - COMPUTED fields have valid computed values
    - Disallowed translations (draft, url, date) are preserved
    """

    def __init__(self, site_profile: SiteProfile, name: str | None = None):
        """
        Initialize frontmatter protection validator.

        Args:
            site_profile: Site profile containing frontmatter rules
            name: Optional custom name for this validator instance
        """
        super().__init__(name)
        self.site_profile = site_profile
        self.frontmatter_rules = site_profile.frontmatter

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate frontmatter fields against site profile rules.

        Args:
            source: Source document with frontmatter
            translation: Translated document with frontmatter
            context: Optional context with file_path, language pair

        Returns:
            ValidationResult with any rule violation issues
        """
        result = ValidationResult(success=True)
        context = context or {}

        # Extract frontmatter from both source and translation
        source_frontmatter = self._extract_frontmatter(source, "source", result)
        if source_frontmatter is None:
            result.success = False
            return result

        translation_frontmatter = self._extract_frontmatter(
            translation, "translation", result
        )
        if translation_frontmatter is None:
            result.success = False
            return result

        # Check PASSTHROUGH fields
        self._check_passthrough_fields(
            source_frontmatter, translation_frontmatter, result
        )

        # Check IGNORE fields
        self._check_ignore_fields(translation_frontmatter, result)

        # Check COMPUTED fields
        self._check_computed_fields(
            source_frontmatter, translation_frontmatter, result, context
        )

        # Check that TRANSLATE fields are actually in the target language
        self._check_translatable_field_language(
            translation_frontmatter, result, context
        )

        return result

    def _check_translatable_field_language(
        self,
        translation: dict[str, Any],
        result: ValidationResult,
        context: dict[str, Any],
    ) -> None:
        """Check that TRANSLATE frontmatter fields are in the target language.

        Detects mixed-language corruption in description, title, seoTitle, summary
        fields (e.g., Greek text appearing in an ES translation).

        Args:
            translation: Translated frontmatter data
            result: ValidationResult to add issues to
            context: Validation context (must contain target_lang)
        """
        target_lang = context.get("target_lang") if context else None
        if not target_lang:
            return

        # Only check these high-value display fields
        CHECKED_FIELDS = {"title", "description", "seoTitle", "summary"}

        try:
            import langdetect
            from langdetect import DetectorFactory
            DetectorFactory.seed = 0
        except ImportError:
            return

        for field, rule in self.frontmatter_rules.items():
            if rule.mode not in (FrontmatterMode.TRANSLATE, FrontmatterMode.TRANSLATE_LIST):
                continue
            if field not in CHECKED_FIELDS:
                continue
            value = translation.get(field)
            if not value or not isinstance(value, str) or len(value.strip()) < 20:
                continue
            try:
                detected_langs = langdetect.detect_langs(value.strip())
                if detected_langs:
                    top = detected_langs[0]
                    if top.lang != target_lang and top.prob > 0.65:
                        result.issues.append(
                            self.create_issue(
                                ValidationSeverity.ERROR,
                                f"Frontmatter field '{field}' detected as '{top.lang}' "
                                f"(confidence {top.prob:.0%}) but expected '{target_lang}'. "
                                f"Preview: '{value[:80]}'",
                                location=f"frontmatter.{field}",
                                details={
                                    "field": field,
                                    "detected_lang": top.lang,
                                    "confidence": top.prob,
                                    "expected_lang": target_lang,
                                },
                            )
                        )
            except Exception:
                pass  # langdetect is probabilistic; silently skip on any error

    def _extract_frontmatter(
        self, content: str, label: str, result: ValidationResult
    ) -> dict[str, Any] | None:
        """
        Extract and parse frontmatter from document.

        Args:
            content: Full document content with frontmatter
            label: Label for error messages ("source" or "translation")
            result: ValidationResult to add issues to

        Returns:
            Parsed frontmatter dict, or None if extraction/parsing failed
        """
        # Match YAML frontmatter delimited by ---
        # Allow empty frontmatter (---\n---\n) by making content optional
        frontmatter_pattern = r"^---\s*\n(.*?)\n?---\s*\n"
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if not match:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"No frontmatter found in {label} document",
                    location=label,
                )
            )
            return None

        yaml_content = match.group(1).strip()
        # Handle empty frontmatter
        if not yaml_content:
            return {}

        # Parse YAML frontmatter
        try:
            data = yaml.safe_load(yaml_content)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"{label} frontmatter must be a dictionary, got {type(data).__name__}",
                        location=f"{label}.frontmatter",
                    )
                )
                return None
            return data
        except yaml.YAMLError as e:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Invalid {label} frontmatter YAML: {str(e)}",
                    location=f"{label}.frontmatter",
                    details={"error": str(e)},
                )
            )
            return None

    def _check_passthrough_fields(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        """
        Check that PASSTHROUGH fields remain unchanged.

        Args:
            source: Source frontmatter data
            translation: Translation frontmatter data
            result: ValidationResult to add issues to
        """
        for field, rule in self.frontmatter_rules.items():
            if rule.mode != FrontmatterMode.PASSTHROUGH:
                continue

            # Check if field exists in source
            if field not in source:
                continue

            # Check if field exists in translation
            if field not in translation:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"PASSTHROUGH field '{field}' missing in translation",
                        location=f"frontmatter.{field}",
                        details={"field": field, "mode": "passthrough"},
                    )
                )
                continue

            # Check if values match exactly
            source_value = source[field]
            translation_value = translation[field]

            if source_value != translation_value:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"PASSTHROUGH field '{field}' was modified (expected: {source_value}, got: {translation_value})",
                        location=f"frontmatter.{field}",
                        details={
                            "field": field,
                            "mode": "passthrough",
                            "expected": source_value,
                            "actual": translation_value,
                        },
                    )
                )

    def _check_ignore_fields(
        self, translation: dict[str, Any], result: ValidationResult
    ) -> None:
        """
        Check that IGNORE fields are not present in translation.

        Args:
            translation: Translation frontmatter data
            result: ValidationResult to add issues to
        """
        for field, rule in self.frontmatter_rules.items():
            if rule.mode != FrontmatterMode.IGNORE:
                continue

            if field in translation:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.WARNING,
                        f"IGNORE field '{field}' should not be present in translation output",
                        location=f"frontmatter.{field}",
                        details={"field": field, "mode": "ignore"},
                    )
                )

    def _check_computed_fields(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        result: ValidationResult,
        context: dict[str, Any],
    ) -> None:
        """
        Check that COMPUTED fields have valid computed values.

        Args:
            source: Source frontmatter data
            translation: Translation frontmatter data
            result: ValidationResult to add issues to
            context: Validation context
        """
        for field, rule in self.frontmatter_rules.items():
            if rule.mode != FrontmatterMode.COMPUTED:
                continue

            if field not in translation:
                # COMPUTED fields may be optional
                continue

            translation_value = translation[field]

            # Validate common computed fields
            if field == "lastmod":
                self._validate_lastmod_field(
                    field, translation_value, result, context
                )
            elif field == "slug":
                self._validate_slug_field(
                    field, source, translation, translation_value, result
                )
            elif field == "permalink":
                self._validate_permalink_field(
                    field, translation_value, result, context
                )
            # Add more computed field validations as needed

    def _validate_lastmod_field(
        self,
        field: str,
        value: Any,
        result: ValidationResult,
        context: dict[str, Any],
    ) -> None:
        """
        Validate lastmod (last modified) field.

        Args:
            field: Field name
            value: Field value
            result: ValidationResult to add issues to
            context: Validation context
        """
        # Check if it's a valid datetime string or datetime/date object
        if isinstance(value, (datetime, date)):
            return  # Valid datetime or date object

        if not isinstance(value, str):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"COMPUTED field '{field}' must be a datetime string or object, got {type(value).__name__}",
                    location=f"frontmatter.{field}",
                    details={"field": field, "type": type(value).__name__},
                )
            )
            return

        # Try to parse common datetime formats
        datetime_formats = [
            "%Y-%m-%dT%H:%M:%S%z",  # ISO 8601 with timezone
            "%Y-%m-%dT%H:%M:%S",  # ISO 8601 without timezone
            "%Y-%m-%d %H:%M:%S",  # Common format
            "%Y-%m-%d",  # Date only
        ]

        parsed = False
        for fmt in datetime_formats:
            try:
                datetime.strptime(value.replace("Z", "+0000"), fmt)
                parsed = True
                break
            except (ValueError, AttributeError):
                continue

        if not parsed:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"COMPUTED field '{field}' has unrecognized datetime format: {value}",
                    location=f"frontmatter.{field}",
                    details={"field": field, "value": value},
                )
            )

    def _validate_slug_field(
        self,
        field: str,
        source: dict[str, Any],
        translation: dict[str, Any],
        value: Any,
        result: ValidationResult,
    ) -> None:
        """
        Validate slug field.

        Args:
            field: Field name
            source: Source frontmatter data
            translation: Translation frontmatter data
            value: Field value
            result: ValidationResult to add issues to
        """
        if not isinstance(value, str):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"COMPUTED field '{field}' must be a string, got {type(value).__name__}",
                    location=f"frontmatter.{field}",
                    details={"field": field, "type": type(value).__name__},
                )
            )
            return

        # Validate slug format (lowercase, hyphens, alphanumeric)
        if not re.match(r"^[a-z0-9-]+$", value):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"COMPUTED field '{field}' has invalid slug format: {value} (expected lowercase, hyphens, alphanumeric)",
                    location=f"frontmatter.{field}",
                    details={"field": field, "value": value},
                )
            )

    def _validate_permalink_field(
        self,
        field: str,
        value: Any,
        result: ValidationResult,
        context: dict[str, Any],
    ) -> None:
        """
        Validate permalink field.

        Args:
            field: Field name
            value: Field value
            result: ValidationResult to add issues to
            context: Validation context
        """
        if not isinstance(value, str):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"COMPUTED field '{field}' must be a string, got {type(value).__name__}",
                    location=f"frontmatter.{field}",
                    details={"field": field, "type": type(value).__name__},
                )
            )
            return

        # Basic URL validation
        if not value.startswith(("/", "http://", "https://")):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"COMPUTED field '{field}' should be a valid URL or path: {value}",
                    location=f"frontmatter.{field}",
                    details={"field": field, "value": value},
                )
            )
