"""
Completeness validator for translation quality assurance.

This module validates that all source segments have been translated with 100% coverage.
"""

import re
from typing import Any

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator


class CompletenessValidator(PostTranslationValidator):
    """Validates that all source segments have been translated.

    Checks:
    - All extracted segments have corresponding translations
    - No missing translations in the translation map
    - No untranslated placeholder text remains
    - Translation coverage is 100%

    Example:
        validator = CompletenessValidator()
        result = validator.validate(
            source=source_text,
            translation=translated_text,
            context=validation_context
        )
        if result.has_errors():
            print(f"Missing segments: {result.error_count}")
    """

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate translation completeness.

        Args:
            source: Original source text
            translation: Translated text
            context: Contains segments, translation map, placeholders

        Returns:
            ValidationResult with completeness issues
        """
        if context is None:
            context = {}

        issues = []

        # Check 1: All segments have translations
        translation_map = context.get("translation_map", {})
        source_segments = context.get("source_segments", [])

        for segment_id, segment_text in enumerate(source_segments):
            if segment_id not in translation_map:
                issues.append(
                    ValidationIssue(
                        validator="CompletenessValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Segment {segment_id} not translated",
                        location=f"segment_{segment_id}",
                        details={"suggestion": "Ensure all segments passed to translation model"},
                    )
                )

        # Check 2: No empty translations
        for segment_id, translated_text in translation_map.items():
            if not translated_text or translated_text.strip() == "":
                issues.append(
                    ValidationIssue(
                        validator="CompletenessValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Segment {segment_id} has empty translation",
                        location=f"segment_{segment_id}",
                        details={"suggestion": "Translation must not be empty"},
                    )
                )

        # Check 3: No untranslated placeholders
        placeholder_pattern = r"\{PLACEHOLDER_\d+\}|\{TERM_\d+\}|\{SHORTCODE_\d+\}"
        untranslated_placeholders = re.findall(placeholder_pattern, translation)

        if untranslated_placeholders:
            # Show first 5 placeholders in the suggestion
            placeholder_sample = untranslated_placeholders[:5]
            issues.append(
                ValidationIssue(
                    validator="CompletenessValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {len(untranslated_placeholders)} untranslated placeholders",
                    location="translation_output",
                    details={
                        "suggestion": f"Placeholders must be restored: {placeholder_sample}",
                        "untranslated_count": len(untranslated_placeholders),
                    },
                )
            )

        # Calculate coverage
        total_segments = len(source_segments)
        translated_segments = len(
            [t for t in translation_map.values() if t and t.strip()]
        )
        coverage = (
            (translated_segments / total_segments * 100) if total_segments > 0 else 0.0
        )

        # Check 4: Document-level length ratio (detects severe truncation)
        # Strip frontmatter (---...---) and code blocks (```...```) before comparing.
        # Conservative floor: 0.30 (translation must be at least 30% of source length).
        # CJK scripts are naturally compact; the 0.30 floor is intentionally loose.
        self._check_length_ratio(source, translation, issues)

        # Check 5: Trailing-section content loss (HT-QUALITY-GATES-001 Part 22,
        # plan 5.2 item 3). The 30% floor above is tuned for catching a body-
        # content disaster; it is structurally incapable of catching the
        # single most prevalent defect confirmed this session -- losing just
        # the last section (typically 1-3% of a page). This runs earlier in
        # the pipeline than write_gate.py's Gates 34/35 (same detection
        # signal, language-agnostic URL matching), which matters because a
        # CompletenessValidator failure can trigger a retry-with-feedback
        # BEFORE the file is ever considered for writing, not just warn at
        # the final gate.
        self._check_trailing_section_loss(source, translation, issues)

        return ValidationResult(
            success=len(issues) == 0,
            issues=issues,
            metadata={"coverage_percent": coverage},
        )

    def _check_length_ratio(
        self,
        source: str,
        translation: str,
        issues: list,
    ) -> None:
        """Detect severe truncation by comparing document character lengths.

        Strips frontmatter and fenced code blocks before comparing so that
        code-heavy articles don't produce false positives. The min ratio (0.30)
        is conservative enough to allow compact CJK output without flagging it.

        Args:
            source: Source document text
            translation: Translated document text
            issues: List to append ValidationIssue objects to
        """
        MIN_RATIO = 0.30
        MAX_RATIO = 4.0
        MIN_SOURCE_LEN = 100  # Skip very short documents

        def _strip_boilerplate(text: str) -> str:
            # Remove YAML frontmatter
            text = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, flags=re.DOTALL)
            # Remove fenced code blocks
            text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
            return text.strip()

        src_clean = _strip_boilerplate(source)
        trn_clean = _strip_boilerplate(translation)

        src_len = len(src_clean)
        trn_len = len(trn_clean)

        if src_len < MIN_SOURCE_LEN:
            return  # Too short to be meaningful

        ratio = trn_len / src_len if src_len > 0 else 1.0

        if ratio < MIN_RATIO:
            issues.append(
                ValidationIssue(
                    validator="CompletenessValidator",
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Translation severely truncated: {trn_len} chars vs "
                        f"{src_len} source chars (ratio {ratio:.2f}, min {MIN_RATIO})"
                    ),
                    location="document",
                    details={
                        "ratio": ratio,
                        "src_len": src_len,
                        "trn_len": trn_len,
                        "suggestion": "Translation appears truncated — check for LLM cutoff",
                    },
                )
            )
        elif ratio > MAX_RATIO:
            issues.append(
                ValidationIssue(
                    validator="CompletenessValidator",
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Translation unusually long: {trn_len} chars vs "
                        f"{src_len} source chars (ratio {ratio:.2f})"
                    ),
                    location="document",
                    details={"ratio": ratio, "src_len": src_len, "trn_len": trn_len},
                )
            )

    # Matches write_gate.py's Gates 34/35 detection signal exactly (same
    # regexes, same reasoning) -- kept as a small, independent copy rather
    # than a cross-module import, matching this codebase's existing style
    # for gate-adjacent constants (e.g. multiple independent
    # _NON_LATIN_SCRIPT_LOCALES-shaped sets already exist across modules).
    _TOP_HEADING_RE = re.compile(r"^##\s+.+$", re.MULTILINE)
    _FENCED_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
    _MARKDOWN_LINK_CAPTURE_RE = re.compile(r"\]\((https?://[^)\s]+)\)")

    def _check_trailing_section_loss(
        self,
        source: str,
        translation: str,
        issues: list,
    ) -> None:
        """Detect the single most prevalent defect confirmed this session:
        a dropped trailing section, almost always "See Also"/"Related
        Resources"/an Enterprise-link block. `_check_length_ratio`'s 30%
        floor cannot see this (a lost final section is typically 1-3% of a
        page); heading TEXT can't be compared across languages (a correctly
        translated heading has different text by definition). URLs are the
        one language-invariant signal: if EN's last top-level section links
        somewhere and none of those URLs survive anywhere in the
        translation, that section was very likely dropped, retitled-and-
        stripped, or had its link markup silently destroyed (confirmed real
        case: reference.aspose.org fr/slides/cpp/ShapeFrame.md kept the "##
        Voir aussi" heading but the `[text](url)` markup collapsed to plain
        unlinked text -- caught here even though the heading count matched).
        """

        def _strip_frontmatter(text: str) -> str:
            return re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.DOTALL)

        src_body = _strip_frontmatter(source)
        headings = list(
            self._TOP_HEADING_RE.finditer(self._FENCED_CODE_BLOCK_RE.sub("", src_body))
        )
        if not headings:
            return

        last_section = src_body[headings[-1].start():]
        section_urls = self._MARKDOWN_LINK_CAPTURE_RE.findall(last_section)
        if not section_urls:
            return  # last section isn't link-shaped -- outside this check's scope

        tgt_body = _strip_frontmatter(translation)
        if any(url in tgt_body for url in section_urls):
            return

        issues.append(
            ValidationIssue(
                validator="CompletenessValidator",
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Trailing section likely dropped: source's last section "
                    f"links to {section_urls[:2]}, none of which appear "
                    f"anywhere in the translation"
                ),
                location="document",
                details={
                    "missing_urls": section_urls[:2],
                    "suggestion": (
                        "Check whether the final section (commonly See Also/"
                        "Related Resources) was omitted or had its link "
                        "markup stripped during translation"
                    ),
                },
            )
        )
