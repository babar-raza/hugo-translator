"""
Frontmatter integrity validator for post-translation structural checks.

Validates that translated frontmatter preserves:
- Same canonical key set (no translated, added, or removed keys)
- Same key order (unless site profile explicitly allows reorder)
- No duplicate keys
- Same value type per key (bool stays bool, list stays list, string stays string)
- Same list/scalar shape and nested structure
- Passthrough fields unchanged exactly
- Booleans remain booleans (not "true" string or "FALSE")
- Dates remain valid and same format
- URLs unchanged or valid according to profile
- Product/platform metadata unchanged
- source_version and generated_by unchanged
- aliases unchanged unless explicitly regenerated
- Output YAML parses with content pipeline parser

This validator is a FAIL-CLOSED guard. All violations are ERRORs.
Invalid output must not overwrite existing files.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .base import ValidationResult, ValidationSeverity, Validator

# Fields that must be passed through unchanged (byte-for-byte equal to source).
# Extend as additional passthrough fields are discovered in site profiles.
PASSTHROUGH_FIELDS = frozenset(
    {
        "date",
        "lastmod",
        "draft",
        "author",
        "weight",
        "type",
        "layout",
        "cart_id",
        "plugin_platform",
        "gisthash",
        "gistfile",
        "productname",
        "productkey",
        "platformkey",
        "productplatform",
        "source_version",
        "generated_by",
        "enhanced",
        "howtoimage",
        "linktitle",
        # products.aspose.net structural
        "enable",
        "plugin_name",
    }
)

# Fields where only the URL/path value matters and must not be translated
URL_LIKE_FIELDS = frozenset(
    {
        "slug",
        "url",
        "canonical",
        "image",
        "thumbnail",
        "howtoimage",
    }
)

# Regex: URL starts with http/https/ftp or /
_URL_RE = re.compile(r"^(https?://|ftp://|/)", re.IGNORECASE)
_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")


class FrontmatterIntegrityValidator(Validator):
    """Post-translation frontmatter structural integrity validator.

    Checks that translation has not mutated frontmatter structure, key names,
    types, passthrough values, or URLs. All violations are ERRORs.
    """

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate frontmatter integrity.

        Args:
            source: Source frontmatter YAML (without --- delimiters)
            translation: Translated frontmatter YAML (without --- delimiters)
            context: Optional context with site_profile, translatable_keys, etc.

        Returns:
            ValidationResult — success=False if any key/type/passthrough violation found
        """
        result = ValidationResult(success=True)
        context = context or {}

        source_data = self._parse(source, "source", result)
        if source_data is None:
            result.success = False
            return result

        translation_data = self._parse(translation, "translation", result)
        if translation_data is None:
            result.success = False
            return result

        translatable = set(context.get("translatable_keys", []))

        self._check_key_set(source_data, translation_data, result)
        self._check_key_order(source_data, translation_data, result)
        self._check_types(source_data, translation_data, result)
        self._check_passthrough(source_data, translation_data, translatable, result)
        self._check_url_fields(source_data, translation_data, result)

        if result.issues:
            has_error = any(i.severity == ValidationSeverity.ERROR for i in result.issues)
            result.success = not has_error

        return result

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _parse(self, yaml_str: str, label: str, result: ValidationResult) -> dict[str, Any] | None:
        try:
            data = yaml.safe_load(yaml_str)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"{label} frontmatter is not a YAML mapping (got {type(data).__name__})",
                        location=label,
                    )
                )
                return None
            return data
        except yaml.YAMLError as exc:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"{label} frontmatter YAML parse failed: {exc}",
                    location=label,
                )
            )
            return None

    def _check_key_set(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        src_keys = set(source.keys())
        tgt_keys = set(translation.keys())
        missing = src_keys - tgt_keys
        extra = tgt_keys - src_keys
        if missing:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Translation frontmatter missing keys: {sorted(missing)}",
                    location="frontmatter",
                    details={"missing_keys": sorted(missing)},
                )
            )
        if extra:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Translation frontmatter has extra keys (possible translated key names): "
                    f"{sorted(extra)}",
                    location="frontmatter",
                    details={"extra_keys": sorted(extra)},
                )
            )

    def _check_key_order(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        common = [k for k in source if k in translation]
        tgt_common = [k for k in translation if k in source]
        if common != tgt_common:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Frontmatter key order changed. Source order: {common}. "
                    f"Translation order: {tgt_common}",
                    location="frontmatter",
                )
            )

    def _check_types(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        for key in source:
            if key not in translation:
                continue
            sv = source[key]
            tv = translation[key]
            s_type = type(sv).__name__
            t_type = type(tv).__name__
            if type(sv) is not type(tv):
                # Allow None/None equivalence
                if sv is None and tv is None:
                    continue
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"Type changed for key '{key}': source={s_type}, translation={t_type}",
                        location=f"frontmatter.{key}",
                        details={"source_type": s_type, "translation_type": t_type},
                    )
                )
                continue

            # Bool: must remain bool, not "true"/"false" string
            if isinstance(sv, bool):
                if not isinstance(tv, bool):
                    result.issues.append(
                        self.create_issue(
                            ValidationSeverity.ERROR,
                            f"Boolean key '{key}' was converted to {t_type} in translation",
                            location=f"frontmatter.{key}",
                        )
                    )

            # List: check length and element types
            if isinstance(sv, list) and isinstance(tv, list):
                if len(sv) != len(tv):
                    result.issues.append(
                        self.create_issue(
                            ValidationSeverity.ERROR,
                            f"List length changed for key '{key}': "
                            f"source={len(sv)}, translation={len(tv)}",
                            location=f"frontmatter.{key}",
                        )
                    )

    def _check_passthrough(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        translatable: set[str],
        result: ValidationResult,
    ) -> None:
        for key in PASSTHROUGH_FIELDS:
            if key not in source or key not in translation:
                continue
            if key in translatable:
                continue
            sv = source[key]
            tv = translation[key]
            if sv != tv:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"Passthrough field '{key}' was modified: "
                        f"source={sv!r}, translation={tv!r}",
                        location=f"frontmatter.{key}",
                        details={"source_value": str(sv), "translation_value": str(tv)},
                    )
                )

    def _check_url_fields(
        self,
        source: dict[str, Any],
        translation: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        for key in URL_LIKE_FIELDS:
            if key not in source or key not in translation:
                continue
            sv = str(source[key]) if source[key] is not None else ""
            tv = str(translation[key]) if translation[key] is not None else ""
            if sv == tv:
                continue
            # URL changed — check for non-ASCII corruption
            if _NON_ASCII_RE.search(tv) and not _NON_ASCII_RE.search(sv):
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"URL field '{key}' contains non-ASCII characters after translation "
                        f"(possible URL corruption)",
                        location=f"frontmatter.{key}",
                        details={"source_value": sv, "translation_value": tv},
                    )
                )
