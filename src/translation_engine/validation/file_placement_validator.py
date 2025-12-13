"""
File placement validator for directory structure verification.

Validates that translated files are placed in the correct directory structure
according to subdomain-specific rules and language folder conventions.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.config_loader import ConfigService
from src.utils.models import SiteProfile
from .base import Validator, ValidationResult, ValidationSeverity


class FilePlacementValidator(Validator):
    """
    Validates file placement according to subdomain conventions.

    Checks:
    - Language folder substitution (/en/ → /de/, /en/ → /fr/, etc.)
    - Subdomain-specific path rules (products, blog, reference, docs)
    - Content root alignment verification
    - Path structure consistency
    """

    def __init__(
        self,
        config_service: Optional[ConfigService] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize the file placement validator.

        Args:
            config_service: Optional ConfigService instance for loading site profiles
            name: Optional custom name for this validator instance
        """
        super().__init__(name)
        self.config_service = config_service

    def validate(
        self,
        source: str,
        translation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate file placement for a translation.

        Args:
            source: Source file path (absolute or relative)
            translation: Translation file path (absolute or relative)
            context: Optional context containing:
                - source_lang: Source language code (e.g., "en")
                - target_lang: Target language code (e.g., "de")
                - site_id: Site identifier for loading profile (e.g., "products.aspose.net")
                - site_profile: Pre-loaded SiteProfile object (alternative to site_id)

        Returns:
            ValidationResult with any placement issues found
        """
        result = ValidationResult(success=True)
        context = context or {}

        # Extract paths
        source_path = Path(source)
        translation_path = Path(translation)

        # Extract language info from context
        source_lang = context.get("source_lang", "en")
        target_lang = context.get("target_lang")

        if not target_lang:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    "No target language specified in context",
                    details={"context": context},
                )
            )
            result.success = False
            return result

        # Load site profile if available
        site_profile = context.get("site_profile")
        if not site_profile and self.config_service and context.get("site_id"):
            try:
                site_profile = self.config_service.get_site_profile(context["site_id"])
            except Exception as e:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.WARNING,
                        f"Could not load site profile: {str(e)}",
                        details={"site_id": context.get("site_id"), "error": str(e)},
                    )
                )

        # Validate language substitution
        self._validate_language_substitution(
            source_path, translation_path, source_lang, target_lang, result
        )

        # Validate content root alignment if site profile available
        if site_profile:
            self._validate_content_root(
                source_path, translation_path, site_profile, result
            )

        # Validate subdomain-specific rules if site profile available
        if site_profile and context.get("site_id"):
            self._validate_subdomain_rules(
                translation_path, site_profile, context["site_id"], result
            )

        return result

    def _validate_language_substitution(
        self,
        source_path: Path,
        translation_path: Path,
        source_lang: str,
        target_lang: str,
        result: ValidationResult,
    ) -> None:
        """
        Validate that language folder substitution is correct.

        Checks that the translation path has the source language folder
        replaced with the target language folder.

        Args:
            source_path: Source file path
            translation_path: Translation file path
            source_lang: Source language code
            target_lang: Target language code
            result: ValidationResult to add issues to
        """
        source_parts = source_path.parts
        translation_parts = translation_path.parts

        # Find source language in source path
        source_lang_indices = [
            i for i, part in enumerate(source_parts) if part == source_lang
        ]

        # Find target language in translation path
        target_lang_indices = [
            i for i, part in enumerate(translation_parts) if part == target_lang
        ]

        # Check if source language exists in source path
        if not source_lang_indices:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"Source language '{source_lang}' not found in source path",
                    location="source_path",
                    details={
                        "source_path": str(source_path),
                        "source_lang": source_lang,
                    },
                )
            )
            return

        # Check if target language exists in translation path
        if not target_lang_indices:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Target language '{target_lang}' not found in translation path",
                    location="translation_path",
                    details={
                        "translation_path": str(translation_path),
                        "target_lang": target_lang,
                    },
                )
            )
            result.success = False
            return

        # Check if source language appears in translation path (it shouldn't)
        if any(part == source_lang for part in translation_parts):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Source language '{source_lang}' found in translation path - language substitution failed",
                    location="translation_path",
                    details={
                        "source_path": str(source_path),
                        "translation_path": str(translation_path),
                        "source_lang": source_lang,
                        "target_lang": target_lang,
                    },
                )
            )
            result.success = False

        # Verify that the paths match except for language folders
        # Build expected translation path by replacing language folders
        for source_idx in source_lang_indices:
            if source_idx < len(translation_parts):
                if translation_parts[source_idx] != target_lang:
                    # The corresponding position should have target language
                    result.issues.append(
                        self.create_issue(
                            ValidationSeverity.WARNING,
                            f"Path structure mismatch at position {source_idx}: expected '{target_lang}', got '{translation_parts[source_idx]}'",
                            location="translation_path",
                            details={
                                "expected": target_lang,
                                "actual": translation_parts[source_idx],
                                "position": source_idx,
                            },
                        )
                    )

    def _validate_content_root(
        self,
        source_path: Path,
        translation_path: Path,
        site_profile: SiteProfile,
        result: ValidationResult,
    ) -> None:
        """
        Validate that paths align with content roots defined in site profile.

        Args:
            source_path: Source file path
            translation_path: Translation file path
            site_profile: Site profile with content root definitions
            result: ValidationResult to add issues to
        """
        if not site_profile.content_roots:
            return

        # Check if source path contains any content root
        source_str = str(source_path.as_posix())
        source_has_root = any(
            root in source_str for root in site_profile.content_roots
        )

        # Check if translation path contains any content root
        translation_str = str(translation_path.as_posix())
        translation_has_root = any(
            root in translation_str for root in site_profile.content_roots
        )

        if not source_has_root:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"Source path does not contain any defined content root: {site_profile.content_roots}",
                    location="source_path",
                    details={
                        "source_path": source_str,
                        "content_roots": site_profile.content_roots,
                    },
                )
            )

        if not translation_has_root:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Translation path does not contain any defined content root: {site_profile.content_roots}",
                    location="translation_path",
                    details={
                        "translation_path": translation_str,
                        "content_roots": site_profile.content_roots,
                    },
                )
            )
            result.success = False

    def _validate_subdomain_rules(
        self,
        translation_path: Path,
        site_profile: SiteProfile,
        site_id: str,
        result: ValidationResult,
    ) -> None:
        """
        Validate subdomain-specific path rules.

        Different subdomains may have different directory structure requirements:
        - products.aspose.net: /content/products/{lang}/...
        - blog.aspose.net: /content/blog/{lang}/...
        - reference.aspose.net: /content/reference/{lang}/...
        - docs.aspose.net: /content/docs/{lang}/...

        Args:
            translation_path: Translation file path
            site_profile: Site profile with subdomain-specific rules
            site_id: Site identifier (subdomain)
            result: ValidationResult to add issues to
        """
        translation_str = str(translation_path.as_posix())

        # Extract subdomain from site_id (e.g., "products" from "products.aspose.net")
        subdomain = site_id.split(".")[0] if "." in site_id else site_id

        # Validate that the path follows the output layout pattern
        if site_profile.output_layout and site_profile.output_layout.per_language_folders:
            # Expected pattern is defined in site profile
            pattern = site_profile.output_layout.pattern

            # Check if pattern is followed - basic validation
            # More sophisticated pattern matching could be added here
            if "{lang}" in pattern:
                # At least one language folder should exist in path
                has_lang_folder = any(
                    part in site_profile.target_langs
                    for part in translation_path.parts
                )
                if not has_lang_folder:
                    result.issues.append(
                        self.create_issue(
                            ValidationSeverity.ERROR,
                            f"Translation path does not contain a valid language folder from: {site_profile.target_langs}",
                            location="translation_path",
                            details={
                                "translation_path": translation_str,
                                "expected_languages": site_profile.target_langs,
                                "pattern": pattern,
                            },
                        )
                    )
                    result.success = False

        # Validate content root matches subdomain expectations
        if site_profile.content_roots:
            # For most subdomains, content root should contain the subdomain name
            expected_in_root = subdomain.lower()
            has_expected_root = any(
                expected_in_root in root.lower() for root in site_profile.content_roots
            )

            if not has_expected_root:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.WARNING,
                        f"Content root does not match subdomain '{subdomain}': {site_profile.content_roots}",
                        location="content_roots",
                        details={
                            "subdomain": subdomain,
                            "content_roots": site_profile.content_roots,
                        },
                    )
                )

    def validate_written_file(
        self,
        file_path: Path,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate a file that has been written to disk (post-write validation).

        Performs filesystem-level checks:
        - File exists at expected path
        - File is readable
        - File has content (not empty)
        - File is in correct language folder structure

        Args:
            file_path: Path to the written file
            context: Optional context containing:
                - source_path: Original source file path
                - source_lang: Source language code (e.g., "en")
                - target_lang: Target language code (e.g., "de")
                - site_id: Site identifier for loading profile
                - site_profile: Pre-loaded SiteProfile object

        Returns:
            ValidationResult with any issues found
        """
        result = ValidationResult(success=True)
        context = context or {}

        # Check if file exists
        if not file_path.exists():
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"File does not exist at expected path: {file_path}",
                    location="file_path",
                    details={"file_path": str(file_path)},
                )
            )
            result.success = False
            return result

        # Check if file is readable
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"File is not readable: {str(e)}",
                    location="file_path",
                    details={"file_path": str(file_path), "error": str(e)},
                )
            )
            result.success = False
            return result

        # Check if file has content
        if not content or len(content.strip()) == 0:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    "File is empty or contains only whitespace",
                    location="file_path",
                    details={"file_path": str(file_path), "size_bytes": len(content)},
                )
            )
            result.success = False
            return result

        # Check language folder structure if source path and languages provided
        source_path = context.get("source_path")
        target_lang = context.get("target_lang")

        if source_path and target_lang:
            # Run standard file placement validation
            source_lang = context.get("source_lang", "en")
            placement_result = self.validate(
                source=str(source_path),
                translation=str(file_path),
                context={
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "site_id": context.get("site_id"),
                    "site_profile": context.get("site_profile"),
                },
            )
            result.merge(placement_result)
        else:
            # At minimum, verify target language folder is in path
            if target_lang:
                file_parts = file_path.parts
                if target_lang not in file_parts:
                    result.issues.append(
                        self.create_issue(
                            ValidationSeverity.WARNING,
                            f"Target language '{target_lang}' not found in file path",
                            location="file_path",
                            details={
                                "file_path": str(file_path),
                                "target_lang": target_lang,
                            },
                        )
                    )

        return result
