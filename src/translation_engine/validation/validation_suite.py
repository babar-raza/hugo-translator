"""
Validation suite for coordinating multiple validators.

This module orchestrates all validators (legacy and new post-translation validators)
and provides config-based validator loading from validation.yaml.
"""

from pathlib import Path
from typing import Any

import yaml

from .base import ValidationResult, Validator
from .completeness_validator import CompletenessValidator
from .file_placement_validator import FilePlacementValidator
from .frontmatter_protection_validator import FrontmatterProtectionValidator
from .language_consistency_validator import LanguageConsistencyValidator
from .link_validator import LinkValidator
from .placeholder_validator import PlaceholderValidator
from .repetition_detector_validator import RepetitionDetectorValidator
from .shortcode_preservation_validator import ShortcodePreservationValidator
from .structure_validator import StructureValidator
from .terminology_preservation_validator import TerminologyPreservationValidator
from .yaml_validator import YAMLValidator


class ValidationSuite:
    """
    Orchestrates multiple validators for comprehensive translation validation.

    Supports:
    - Legacy validators: YAML, Placeholder, Structure, Link
    - New post-translation validators: Completeness, LanguageConsistency,
      ShortcodePreservation, FrontmatterProtection, TerminologyPreservation, FilePlacement
    - Config-based validator loading from validation.yaml
    - Short-circuit on critical failures (optional)

    Usage:
        # Create with default validators
        suite = ValidationSuite()

        # Create from config
        suite = ValidationSuite.from_config("config/validation.yaml")

        # Validate translation
        result = suite.validate(source, translation, context)
    """

    def __init__(
        self,
        validators: list[Validator] | None = None,
        fail_fast: bool = False,
        short_circuit_on_critical: bool = False,
    ):
        """
        Initialize validation suite.

        Args:
            validators: List of validators to use. If None, uses default set.
            fail_fast: Whether to stop on first error (legacy behavior)
            short_circuit_on_critical: Whether to stop on critical failures (errors)
        """
        self.validators = validators if validators is not None else self._create_default_validators()
        self.fail_fast = fail_fast
        self.short_circuit_on_critical = short_circuit_on_critical

    @staticmethod
    def _load_lang_consistency_config() -> dict:
        """Load language_consistency config from validation.yaml (best-effort, never raises).

        Returns:
            Dict with 'confidence_threshold' and 'per_language_overrides' keys.
        """
        defaults = {"confidence_threshold": 0.85, "per_language_overrides": {}}
        try:
            cfg_path = Path("config/validation.yaml")
            if not cfg_path.exists():
                return defaults
            with cfg_path.open(encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            lc = cfg.get("validators", {}).get("language_consistency", {})
            defaults["confidence_threshold"] = lc.get("confidence_threshold", 0.85)
            defaults["per_language_overrides"] = lc.get("per_language_overrides", {})
        except Exception:
            pass
        return defaults

    def _create_default_validators(self) -> list[Validator]:
        """
        Create default set of validators (all enabled).

        Per-language thresholds for LanguageConsistencyValidator are loaded lazily
        from config/validation.yaml so that the default constructor picks up
        production settings without requiring an explicit config path.

        Returns:
            List of validator instances
        """
        lc_cfg = self._load_lang_consistency_config()
        return [
            # Legacy validators
            PlaceholderValidator(),
            StructureValidator(),
            LinkValidator(),
            # New post-translation validators (VAL-01 through VAL-06)
            CompletenessValidator(),
            LanguageConsistencyValidator(
                confidence_threshold=lc_cfg["confidence_threshold"],
                per_language_overrides=lc_cfg["per_language_overrides"],
            ),
            ShortcodePreservationValidator(),
            RepetitionDetectorValidator(config={
                "ngram_threshold": 5,          # Require 5+ occurrences (default 3) — reduces false positives on structured docs
                "sentence_dup_threshold": 3,   # Require 3 duplicates (default 2) — tolerates paired FAQ/step patterns
                "word_freq_threshold": 0.35,   # Slightly relaxed (default 0.30) — product names repeat legitimately
            }),
            # Note: FrontmatterProtectionValidator, TerminologyPreservationValidator,
            # and FilePlacementValidator require constructor arguments,
            # so they are only created via from_config() or explicitly passed in
        ]

    @classmethod
    def from_config(
        cls,
        config_path: Path | None = None,
        site_profile=None,
        config_service=None,
        short_circuit_on_critical: bool = False,
    ) -> "ValidationSuite":
        """
        Create ValidationSuite from validation.yaml configuration.

        Args:
            config_path: Path to validation.yaml. If None, uses default location.
            site_profile: Optional SiteProfile for validators that need it
            config_service: Optional ConfigService for validators that need it
            short_circuit_on_critical: Whether to stop on critical failures

        Returns:
            ValidationSuite instance with enabled validators
        """
        # Default to config/validation.yaml if not specified
        if config_path is None:
            # Assume we're in src/translation_engine/validation/
            # Navigate to project root: ../../../config/validation.yaml
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent.parent
            config_path = project_root / "config" / "validation.yaml"

        # Load config
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)

        validators_config = config.get('validators', {})
        validators: list[Validator] = []

        # Load validators based on enabled flag
        # Legacy validators
        if validators_config.get('yaml', {}).get('enabled', True):
            validators.append(YAMLValidator())

        if validators_config.get('placeholder', {}).get('enabled', True):
            validators.append(PlaceholderValidator())

        if validators_config.get('structure', {}).get('enabled', True):
            validators.append(StructureValidator())

        if validators_config.get('link', {}).get('enabled', True):
            validators.append(LinkValidator())

        # New post-translation validators (VAL-01 through VAL-06)
        if validators_config.get('completeness', {}).get('enabled', True):
            validators.append(CompletenessValidator())

        if validators_config.get('language_consistency', {}).get('enabled', True):
            lc_cfg = validators_config.get('language_consistency', {})
            confidence_threshold = lc_cfg.get('confidence_threshold', 0.85)
            per_language_overrides = lc_cfg.get('per_language_overrides', {})
            validators.append(LanguageConsistencyValidator(
                confidence_threshold=confidence_threshold,
                per_language_overrides=per_language_overrides,
            ))

        if validators_config.get('shortcode_preservation', {}).get('enabled', True):
            validators.append(ShortcodePreservationValidator())

        if validators_config.get('frontmatter_protection', {}).get('enabled', True):
            if site_profile:
                validators.append(FrontmatterProtectionValidator(site_profile=site_profile))

        if validators_config.get('terminology_preservation', {}).get('enabled', True):
            validators.append(TerminologyPreservationValidator())

        if validators_config.get('file_placement', {}).get('enabled', True):
            validators.append(FilePlacementValidator(config_service=config_service))

        if validators_config.get('repetition_detector', {}).get('enabled', True):
            rep_cfg = {k: v for k, v in validators_config.get('repetition_detector', {}).items()
                       if k not in ('enabled', 'description')}
            validators.append(RepetitionDetectorValidator(config=rep_cfg))

        return cls(
            validators=validators,
            fail_fast=False,
            short_circuit_on_critical=short_circuit_on_critical,
        )

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> list[ValidationResult]:
        """
        Run all validators on a translation.

        Args:
            source: Source text
            translation: Translated text
            context: Optional context (language pair, file path, etc.)

        Returns:
            List of ValidationResult objects from all validators
        """
        results: list[ValidationResult] = []
        context = context or {}

        for validator in self.validators:
            result = validator.validate(source, translation, context)
            results.append(result)

            # Stop if fail_fast and we hit an error
            if self.fail_fast and not result.success:
                break

            # Stop if short_circuit_on_critical and we hit critical errors
            if self.short_circuit_on_critical and result.has_errors():
                break

        return results

    def validate_aggregated(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Run all validators and return a single aggregated result.

        This is the legacy behavior that merges all results into one.

        Args:
            source: Source text
            translation: Translated text
            context: Optional context (language pair, file path, etc.)

        Returns:
            Single aggregated ValidationResult
        """
        results = self.validate(source, translation, context)

        # Aggregate all results
        aggregate_result = ValidationResult(success=True)
        for result in results:
            aggregate_result.merge(result)

        return aggregate_result

    def validate_with_yaml(
        self,
        source_yaml: str,
        translation_yaml: str,
        source_body: str,
        translation_body: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate a complete Hugo document (frontmatter + body).

        Args:
            source_yaml: Source frontmatter YAML
            translation_yaml: Translation frontmatter YAML
            source_body: Source markdown body
            translation_body: Translation markdown body
            context: Optional context

        Returns:
            Aggregated ValidationResult
        """
        # Validate frontmatter
        yaml_validator = YAMLValidator()
        yaml_result = yaml_validator.validate(source_yaml, translation_yaml, context)

        # Validate body
        body_result = self.validate_aggregated(source_body, translation_body, context)

        # Merge results
        yaml_result.merge(body_result)
        return yaml_result

    def add_validator(self, validator: Validator) -> None:
        """
        Add a validator to the suite.

        Args:
            validator: Validator instance to add
        """
        self.validators.append(validator)

    def remove_validator(self, validator_name: str) -> bool:
        """
        Remove a validator by name.

        Args:
            validator_name: Name of validator to remove

        Returns:
            True if removed, False if not found
        """
        for i, validator in enumerate(self.validators):
            if validator.name == validator_name:
                self.validators.pop(i)
                return True
        return False

    def get_validator(self, validator_name: str) -> Validator | None:
        """
        Get a validator by name.

        Args:
            validator_name: Name of validator

        Returns:
            Validator instance or None if not found
        """
        for validator in self.validators:
            if validator.name == validator_name:
                return validator
        return None
