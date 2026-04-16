"""
File placement validator for directory structure verification.

Validates that translated files are placed in the correct directory structure
according to subdomain-specific rules and language folder conventions.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.utils.config_loader import ConfigService
from src.utils.models import SiteProfile
from .base import Validator, ValidationResult, ValidationSeverity

logger = structlog.get_logger(__name__)


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

        # Validate language substitution based on localization strategy
        self._validate_language_substitution(
            source_path, translation_path, source_lang, target_lang, result, site_profile
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
        site_profile: Optional[SiteProfile] = None,
    ) -> None:
        """
        Validate that language substitution is correct based on localization strategy.

        For folder-based localization (per_language_folders=True):
            Checks that /en/ folder is replaced with /de/, /fr/, etc.

        For file-based localization (per_language_folders=False):
            Checks that index.md becomes index.de.md, index.fr.md, etc.
            Source files won't have language in path - this is expected.

        Args:
            source_path: Source file path
            translation_path: Translation file path
            source_lang: Source language code
            target_lang: Target language code
            result: ValidationResult to add issues to
            site_profile: Optional site profile for localization settings

        Examples:
            Folder-based (products.aspose.net, per_language_folders=True):
                Source: /content/en/products/cells.md
                Target: /content/de/products/cells.md
                Validates: /en/ → /de/ substitution in path

            File-based (blog.aspose.net, per_language_folders=False):
                Source: /content/blog/post/index.md
                Target: /content/blog/post/index.es.md
                Validates: filename pattern (*.{lang}.md), NOT folder structure
        """
        # Determine localization strategy
        per_language_folders = True  # Default to folder-based for sites without explicit config (safer/stricter)

        if site_profile and site_profile.output_layout:
            # output_layout is a Pydantic OutputLayout model (defined in utils/models.py:97-108)
            # The per_language_folders field is a required bool, so it's always True or False (never None)
            per_language_folders = site_profile.output_layout.per_language_folders
            # Note: If output_layout is None, we keep the safe default (folder-based validation)

        # Log validation routing decision for observability
        logger.debug(
            "file_placement_validation_routing",
            strategy="file-based" if not per_language_folders else "folder-based",
            per_language_folders=per_language_folders,
            site_id=getattr(site_profile, 'site_id', 'unknown'),
            source_file=source_path.name
        )

        if per_language_folders:
            # Folder-based localization: /content/en/post.md → /content/es/post.md
            # Validates that /en/ folder is replaced with target language folder (/es/, /de/, etc.)
            self._validate_folder_based_substitution(
                source_path, translation_path, source_lang, target_lang, result
            )
        else:
            # File-based localization: /content/post/index.md → /content/post/index.es.md
            # Validates that filename includes target language code (index.es.md, index.de.md, etc.)
            # Source files have NO language in path or filename (index.md, _index.md)
            self._validate_file_based_substitution(
                source_path, translation_path, source_lang, target_lang, result
            )

    def _validate_folder_based_substitution(
        self,
        source_path: Path,
        translation_path: Path,
        source_lang: str,
        target_lang: str,
        result: ValidationResult,
    ) -> None:
        """Validate folder-based localization (/en/ → /de/)."""
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
        for source_idx in source_lang_indices:
            if source_idx < len(translation_parts):
                if translation_parts[source_idx] != target_lang:
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

    def _validate_file_based_substitution(
        self,
        source_path: Path,
        translation_path: Path,
        source_lang: str,
        target_lang: str,
        result: ValidationResult,
    ) -> None:
        """
        Validate file-based localization (index.md → index.de.md).

        For file-based sites:
        - Source files are named: index.md, _index.md, post.md (no language code)
        - Translation files are named: index.de.md, _index.fr.md, post.es.md
        """
        translation_name = translation_path.name

        # Check if target language is in the filename
        # Expected pattern: {name}.{lang}.md
        pattern = rf'\.{re.escape(target_lang)}\.md$'
        if not re.search(pattern, translation_name, re.IGNORECASE):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Target language '{target_lang}' not found in translation filename",
                    location="translation_path",
                    details={
                        "translation_path": str(translation_path),
                        "translation_name": translation_name,
                        "target_lang": target_lang,
                        "expected_pattern": f"*.{target_lang}.md",
                    },
                )
            )
            result.success = False
            return

        # Verify source and translation are in same directory (file-based keeps same folder)
        if source_path.parent != translation_path.parent:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    "Source and translation files are in different directories",
                    location="translation_path",
                    details={
                        "source_dir": str(source_path.parent),
                        "translation_dir": str(translation_path.parent),
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
        # Normalize to POSIX (forward slashes) before comparison to handle Windows paths
        # Expand env vars in content roots (e.g. ${ASPOSE_NET_CONTENT}/blog.aspose.net)
        source_str = str(source_path.as_posix())
        expanded_roots = [os.path.expandvars(root) for root in site_profile.content_roots]
        source_has_root = any(
            Path(root).as_posix() in source_str for root in expanded_roots
        )

        # Check if translation path contains any content root
        translation_str = str(translation_path.as_posix())
        translation_has_root = any(
            Path(root).as_posix() in translation_str for root in expanded_roots
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
        # For test profiles without "." (e.g., "blog-test"), use the first dash-separated segment
        if "." in site_id:
            subdomain = site_id.split(".")[0]
        else:
            # Test profile - skip subdomain validation (no reliable domain to match)
            subdomain = None

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

        # Validate content root matches subdomain expectations (only for real domain site_ids)
        if site_profile.content_roots and subdomain is not None:
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
            # At minimum, verify target language is present
            # For folder-based sites: check if target_lang folder is in path
            # For file-based sites: language is in filename, not path (skip check)
            if target_lang:
                # Determine localization strategy (same logic as _validate_language_substitution)
                per_language_folders = True  # Default to folder-based
                site_profile = context.get("site_profile")
                if site_profile and site_profile.output_layout:
                    per_language_folders = site_profile.output_layout.per_language_folders

                # Only check for language folder if using folder-based localization
                if per_language_folders:
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
                # For file-based localization, language is in filename (index.es.md), not folder path

        return result
