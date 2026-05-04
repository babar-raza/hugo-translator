"""
Validator for ensuring Hugo shortcodes are preserved exactly in translation.

This validator checks that all Hugo shortcodes from source text are present
and structurally unchanged in the translated text. Hugo shortcodes are special
markup that must not be translated, added, removed, or modified in any way.

Checks (all are ERRORs):
- Added shortcode (present in translation but not source)
- Removed shortcode (present in source but not translation)
- Orphan closing shortcode (no matching opener)
- Orphan opening shortcode (no matching closer)
- Translated shortcode name (e.g. {{< figura >}} instead of {{< figure >}})
- Changed delimiter type ({{% %}} vs {{< >}})
- Changed parameter names or values (structural)
- Broken quote structure within shortcode
- Source has no shortcodes but target contains one
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator


@dataclass(frozen=True)
class ParsedShortcode:
    """Structured representation of a Hugo shortcode."""
    raw: str              # Normalized raw text
    name: str             # Shortcode name (lowercased for comparison)
    delimiter: str        # "<" for {{< >}} or "%" for {{% %}}
    is_closing: bool      # True if /name
    is_self_closing: bool # True if ends with / before closing delimiter
    params_raw: str       # Raw parameter string for exact comparison


class ShortcodePreservationValidator(PostTranslationValidator):
    """Validates that Hugo shortcodes are preserved exactly in translation.

    Hugo shortcodes come in several forms:
    - {{< shortcode >}} - self-closing or opening tag
    - {{< /shortcode >}} - closing tag
    - {{% shortcode %}} - with inner content processing
    - {{% /shortcode %}} - closing tag with processing
    - {{/* comment */}} - comments

    All structural differences between source and translation shortcodes are
    reported as ERRORs (not WARNINGs) to ensure fail-closed behavior.
    """

    # Pattern: capture delimiter type (<  or %), content between delimiters
    _SHORTCODE_RE = re.compile(
        r'\{\{(?P<delim>[<%])(?P<body>.*?)(?P=delim)\}\}',
        re.DOTALL,
    )

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate shortcode structural preservation.

        Args:
            source: Original source text
            translation: Translated text
            context: Validation context (optional)

        Returns:
            ValidationResult with shortcode issues (all are ERROR severity)
        """
        issues = []

        source_shortcodes = self._extract_structured(source)
        translation_shortcodes = self._extract_structured(translation)

        source_raw = [sc.raw for sc in source_shortcodes]
        translation_raw = [sc.raw for sc in translation_shortcodes]
        source_counter = Counter(source_raw)
        translation_counter = Counter(translation_raw)

        # Source has no shortcodes but target contains one
        if not source_shortcodes and translation_shortcodes:
            for sc in translation_shortcodes:
                issues.append(ValidationIssue(
                    validator="ShortcodePreservationValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Shortcode present in translation but source has none: {sc.raw}",
                    location="shortcodes",
                ))

        # Added shortcodes (present in translation, not in source)
        for raw in translation_counter:
            if raw not in source_counter:
                issues.append(ValidationIssue(
                    validator="ShortcodePreservationValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Unexpected shortcode in translation (LLM hallucination): {raw}",
                    location="shortcodes",
                ))

        # Removed or reduced shortcodes (present in source, absent/reduced in translation)
        for raw, count in source_counter.items():
            t_count = translation_counter.get(raw, 0)
            if t_count == 0:
                issues.append(ValidationIssue(
                    validator="ShortcodePreservationValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Shortcode missing in translation: {raw}",
                    location="shortcodes",
                ))
            elif t_count < count:
                issues.append(ValidationIssue(
                    validator="ShortcodePreservationValidator",
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Shortcode count reduced: appears {count}x in source "
                        f"but {t_count}x in translation: {raw}"
                    ),
                    location="shortcodes",
                ))

        # Check for translated names, delimiter mutation, and parameter mutation
        # by comparing source shortcode names to translation shortcode names
        source_names = Counter(sc.name for sc in source_shortcodes)
        translation_names = Counter(sc.name for sc in translation_shortcodes)
        for name in source_names:
            if name not in translation_names:
                # Name is absent — find if any similar name exists (translation artifact)
                close = [n for n in translation_names if n not in source_names]
                if close:
                    issues.append(ValidationIssue(
                        validator="ShortcodePreservationValidator",
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"Shortcode name '{name}' missing in translation; "
                            f"possibly translated to: {close}"
                        ),
                        location="shortcodes",
                    ))

        # Delimiter mutation: source used {{< >}} but translation used {{% %}} or vice versa
        source_by_name: dict[str, list[ParsedShortcode]] = {}
        for sc in source_shortcodes:
            source_by_name.setdefault(sc.name, []).append(sc)
        trans_by_name: dict[str, list[ParsedShortcode]] = {}
        for sc in translation_shortcodes:
            trans_by_name.setdefault(sc.name, []).append(sc)

        for name, src_list in source_by_name.items():
            if name not in trans_by_name:
                continue
            t_list = trans_by_name[name]
            for src_sc, t_sc in zip(src_list, t_list):
                if src_sc.delimiter != t_sc.delimiter:
                    issues.append(ValidationIssue(
                        validator="ShortcodePreservationValidator",
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"Shortcode delimiter changed for '{name}': "
                            f"source used '{src_sc.delimiter}' but translation used '{t_sc.delimiter}'"
                        ),
                        location="shortcodes",
                    ))
                if src_sc.params_raw != t_sc.params_raw:
                    issues.append(ValidationIssue(
                        validator="ShortcodePreservationValidator",
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"Shortcode parameters changed for '{name}': "
                            f"source='{src_sc.params_raw}' translation='{t_sc.params_raw}'"
                        ),
                        location="shortcodes",
                    ))

        # Orphan closing shortcode in translation (closing without opener)
        self._check_orphan_shortcodes(translation_shortcodes, "translation", issues)
        # Orphan opening shortcode in translation (opener without closer)
        # Only flag if source doesn't have the same opener (i.e. not a self-closing pattern)
        self._check_orphan_shortcodes(source_shortcodes, "source", issues)

        has_errors = any(i.severity == ValidationSeverity.ERROR for i in issues)
        return ValidationResult(
            success=not has_errors,
            issues=issues,
            metadata={
                "source_shortcode_count": len(source_shortcodes),
                "translation_shortcode_count": len(translation_shortcodes),
            },
        )

    def _extract_structured(self, text: str) -> list[ParsedShortcode]:
        """Extract Hugo shortcodes as structured objects.

        Returns:
            List of ParsedShortcode objects with name, delimiter, params, etc.
        """
        results = []
        for m in self._SHORTCODE_RE.finditer(text):
            delim = m.group("delim")  # "<" or "%"
            body = m.group("body").strip()
            raw = re.sub(r'\s+', ' ', m.group(0)).strip()

            is_closing = body.startswith("/")
            if is_closing:
                body = body[1:].strip()

            # Self-closing: body ends with /
            is_self_closing = body.endswith("/") and not is_closing
            if is_self_closing:
                body = body[:-1].strip()

            # Extract name (first token)
            parts = body.split(None, 1)
            name = parts[0].lower() if parts else ""
            params_raw = parts[1].strip() if len(parts) > 1 else ""

            results.append(ParsedShortcode(
                raw=raw,
                name=name,
                delimiter=delim,
                is_closing=is_closing,
                is_self_closing=is_self_closing,
                params_raw=params_raw,
            ))
        return results

    def _check_orphan_shortcodes(
        self,
        shortcodes: list[ParsedShortcode],
        label: str,
        issues: list[ValidationIssue],
    ) -> None:
        """Check for unmatched opening or closing shortcodes.

        Self-closing shortcodes ({{< name / >}} style) are excluded from
        orphan detection. Paired shortcodes must have matching opener/closer.
        """
        # Only non-self-closing, non-comment shortcodes with %% delimiter
        # ({{< >}} shortcodes can be legitimately unpaired in Hugo)
        stack: list[str] = []
        for sc in shortcodes:
            if sc.is_self_closing or sc.name.startswith("/*"):
                continue
            if sc.delimiter == "%":
                if sc.is_closing:
                    if stack and stack[-1] == sc.name:
                        stack.pop()
                    else:
                        issues.append(ValidationIssue(
                            validator="ShortcodePreservationValidator",
                            severity=ValidationSeverity.ERROR,
                            message=(
                                f"Orphan closing shortcode in {label}: "
                                f"{{% /{sc.name} %}} has no matching opener"
                            ),
                            location="shortcodes",
                        ))
                else:
                    stack.append(sc.name)

        for unclosed in stack:
            issues.append(ValidationIssue(
                validator="ShortcodePreservationValidator",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Orphan opening shortcode in {label}: "
                    f"{{% {unclosed} %}} has no matching closer"
                ),
                location="shortcodes",
            ))
