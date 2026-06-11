"""
Regression tests: Shortcode hallucination detection (RC-2).

TC-SH-01: Source has no shortcodes + translation adds {{% /steps %}} → ERROR
TC-SH-02: Source has matched {{% steps %}} pair + translation keeps it → PASS
TC-SH-03: Source has steps pair + translation adds extra {{% /steps %}} → ERROR
TC-SH-04: Source has {{% notice %}} shortcode + translation removes it → ERROR (missing)
TC-SH-05: Simulates Japanese KB RC-2 defect pattern exactly

RC-2 root cause: unexpected-new-shortcode was WARNING, should be ERROR.
"""

from __future__ import annotations

import pytest

try:
    from src.translation_engine.validation.shortcode_preservation_validator import (
        ShortcodePreservationValidator,
    )

    HAS_VALIDATOR = True
except ImportError:
    HAS_VALIDATOR = False

# Also test the scan tool's shortcode balance checker
try:
    from scripts.repair_translated_content import Issue, check_shortcode_balance

    HAS_SCAN = True
except ImportError:
    HAS_SCAN = False


@pytest.mark.skipif(not HAS_VALIDATOR, reason="ShortcodePreservationValidator not available")
class TestShortcodePreservationValidator:
    """Test ShortcodePreservationValidator raises ERROR for hallucinated shortcodes."""

    def test_tc_sh_01_no_shortcodes_source_but_translation_adds_closer(self):
        """Source has no shortcodes but translation adds {{% /steps %}} → ERROR."""
        source = "1. Step one\n2. Step two\n3. Step three"
        translation = "1. Step one\n2. Step two\n3. {{% /steps %}}\n4. Step three"

        validator = ShortcodePreservationValidator()
        result = validator.validate(source, translation)

        assert result is not None
        error_issues = [i for i in result.issues if i.severity.value == "error"]
        assert len(error_issues) > 0, "Expected ERROR for shortcode added by LLM, got: " + str(
            [i.message for i in result.issues]
        )

    def test_tc_sh_02_source_has_pair_translation_keeps_it(self):
        """Source and translation both have matched {{% steps %}} pair → PASS."""
        source = "{{% steps %}}\n### Step 1\nContent.\n{{% /steps %}}"
        translation = "{{% steps %}}\n### Stap 1\nInhoud.\n{{% /steps %}}"

        validator = ShortcodePreservationValidator()
        result = validator.validate(source, translation)

        error_issues = [i for i in result.issues if i.severity.value == "error"]
        assert len(error_issues) == 0, "Expected no errors for matched pair, got: " + str(
            [i.message for i in error_issues]
        )

    def test_tc_sh_04_source_has_shortcode_translation_removes_it(self):
        """Source has {{% notice %}} shortcode, translation removes it → ERROR.

        Note: The validator regex uses (?P=delim) which requires the same
        character on both sides, so it only handles {{% %}} style shortcodes
        (delim = %). The {{< >}} style (delim < vs >) is a known validator
        limitation tracked separately.
        """
        source = "{{% notice info %}}\nImportant information here.\n{{% /notice %}}"
        translation = "Important information here."

        validator = ShortcodePreservationValidator()
        result = validator.validate(source, translation)

        assert result is not None
        error_issues = [i for i in result.issues if i.severity.value == "error"]
        assert len(error_issues) > 0, (
            "Expected ERROR for removed {{% notice %}} shortcode, got: "
            + str([i.message for i in result.issues])
        )

    def test_tc_sh_05_japanese_kb_rc2_pattern(self):
        """Simulates the exact RC-2 defect: numbered list + injected {{% /steps %}}."""
        # English source: plain numbered list, NO shortcodes (KB article body excerpt)
        source = "7. Save the modified Word document to disk.\n\n## Where to host the API\n"
        # Japanese translation: same but with hallucinated {{% /steps %}} at step 7
        translation = "7. {{% /steps %}}.\n\n## API をホストする場所\n"

        validator = ShortcodePreservationValidator()
        result = validator.validate(source, translation)

        assert result is not None
        error_issues = [i for i in result.issues if i.severity.value == "error"]
        assert len(error_issues) > 0, (
            "RC-2: shortcode hallucination must be ERROR, not WARNING. "
            "Got: " + str([(i.severity, i.message) for i in result.issues])
        )


@pytest.mark.skipif(not HAS_SCAN, reason="repair_translated_content not available")
class TestScanShortcodeBalance:
    """Test the scan tool's orphan shortcode detection."""

    def test_scan_detects_orphan_closer(self):
        """Scan tool detects orphan {{% /steps %}} with no opener."""
        body = "Some text\n7. {{% /steps %}}\nMore text\n"
        issues = check_shortcode_balance(body, "test/path.md")
        orphan_close = [i for i in issues if i.kind == "orphan_closing_shortcode"]
        assert len(orphan_close) > 0, "Expected orphan_closing_shortcode issue"

    def test_scan_passes_matched_pair(self):
        """Scan tool accepts matched {{% steps %}} / {{% /steps %}} pair."""
        body = "{{% steps %}}\n### Step 1\nContent\n{{% /steps %}}\n"
        issues = check_shortcode_balance(body, "test/path.md")
        orphan_close = [i for i in issues if i.kind == "orphan_closing_shortcode"]
        orphan_open = [i for i in issues if i.kind == "orphan_opening_shortcode"]
        assert len(orphan_close) == 0
        assert len(orphan_open) == 0

    def test_scan_detects_extra_closer_after_matched_pair(self):
        """Scan tool detects extra {{% /steps %}} after matched pair."""
        body = (
            "{{% steps %}}\n"
            "### Step 1\n"
            "Content\n"
            "{{% /steps %}}\n"
            "Some section\n"
            "### {{% /steps %}}\n"  # extra orphan
        )
        issues = check_shortcode_balance(body, "test/path.md")
        orphan_close = [i for i in issues if i.kind == "orphan_closing_shortcode"]
        assert len(orphan_close) > 0, "Expected orphan closer detection after matched pair"
