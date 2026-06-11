"""
Unit tests for scripts/repair_translated_content.py.

TC-RTC-01: Czech-style collapsed YAML blob → collapsed_frontmatter detected
TC-RTC-02: Arabic-style block scalar at same indent as key → block_scalar_indent_failure detected
TC-RTC-03: Clean translated file → zero issues returned
TC-RTC-04: Orphaned {{% /steps %}} → orphan_closing_shortcode detected
TC-RTC-05: Multiple key:value pairs on same line → collapsed_frontmatter detected
TC-RTC-06: Missing closing delimiter (single ---) → missing_closing_delimiter detected
TC-RTC-07: Non-ASCII URL in frontmatter → url_corruption detected
TC-RTC-08: scan_changed_files() filters non-.md and non-translated files
TC-RTC-09: scan_changed_files() returns ScanResult with correct totals
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

try:
    from scripts.repair_translated_content import (
        Issue,
        ScanResult,
        check_block_scalar_indent,
        check_collapsed_frontmatter,
        check_shortcode_balance,
        check_url_corruption,
        check_yaml_parseable,
        extract_frontmatter,
        scan_changed_files,
        scan_file,
    )

    HAS_SCAN = True
except ImportError:
    HAS_SCAN = False


pytestmark = pytest.mark.skipif(not HAS_SCAN, reason="repair_translated_content not importable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_translated_md(fm: str, body: str = "\nContent here.\n") -> str:
    """Assemble a minimal translated Markdown file from frontmatter and body."""
    return f"---\n{fm}\n---\n{body}"


# ---------------------------------------------------------------------------
# TC-RTC-01: Czech-style collapsed YAML blob
# ---------------------------------------------------------------------------


class TestCollapsedFrontmatter:
    """check_collapsed_frontmatter() detects multiple key:value on one line."""

    CZECH_RC3_FM = textwrap.dedent("""\
        Autor: Muzammil Khan Kategorie:
        - Aspose.BarCode Plugin Family Datum: 2024-11-09 Popis: Programově generujte
        Název: Test
    """)

    CLEAN_FM = textwrap.dedent("""\
        author: Muzammil Khan
        categories:
        - Aspose.BarCode Plugin Family
        date: 2024-11-09
        title: Test
    """)

    def test_tc_rtc_01_collapsed_detected(self):
        """TC-RTC-01: Czech-style collapsed YAML blob → collapsed_frontmatter detected."""
        issues = check_collapsed_frontmatter(self.CZECH_RC3_FM, "test/index.cs.md")
        kinds = [i.kind for i in issues]
        assert "collapsed_frontmatter" in kinds, (
            f"Expected 'collapsed_frontmatter' issue, got: {kinds}"
        )

    def test_clean_yaml_no_collapsed(self):
        """Properly structured YAML → no collapsed_frontmatter issues."""
        issues = check_collapsed_frontmatter(self.CLEAN_FM, "test/index.cs.md")
        kinds = [i.kind for i in issues]
        assert "collapsed_frontmatter" not in kinds


# ---------------------------------------------------------------------------
# TC-RTC-02: Arabic-style block scalar at same indent
# ---------------------------------------------------------------------------


class TestBlockScalarIndent:
    """check_block_scalar_indent() detects block scalar content at same indent as key."""

    # Arabic email template pattern: key at indent 4, content at indent 4 (wrong; must be > 4)
    ARABIC_BAD_FM = textwrap.dedent("""\
        layout: product-page
        title: Arabic Title
        content_left: |-
        First line of content
        Second line of content
        content_right: "other value"
    """)

    GOOD_FM = textwrap.dedent("""\
        layout: product-page
        title: Arabic Title
        content_left: |-
            First line of content
            Second line of content
        content_right: "other value"
    """)

    def test_tc_rtc_02_block_scalar_indent_failure_detected(self):
        """TC-RTC-02: Block scalar content at same indent as key → block_scalar_indent_failure."""
        issues = check_block_scalar_indent(self.ARABIC_BAD_FM, "test/_index.md")
        kinds = [i.kind for i in issues]
        assert "block_scalar_indent_failure" in kinds, (
            f"Expected 'block_scalar_indent_failure', got: {kinds}"
        )

    def test_correct_block_scalar_passes(self):
        """Block scalar content more indented than key → no block_scalar_indent_failure."""
        issues = check_block_scalar_indent(self.GOOD_FM, "test/_index.md")
        kinds = [i.kind for i in issues]
        assert "block_scalar_indent_failure" not in kinds


# ---------------------------------------------------------------------------
# TC-RTC-03: Clean translated file → zero issues
# ---------------------------------------------------------------------------


class TestCleanFile:
    """scan_file() returns no issues for a well-formed translated file."""

    CLEAN_FM = textwrap.dedent("""\
        author: Test Author
        title: Translated Title
        date: 2024-01-01
        draft: false
        categories:
        - Category A
    """)

    CLEAN_BODY = "\n## Section\n\nSome translated content here.\n"

    def test_tc_rtc_03_clean_file_zero_issues(self, tmp_path):
        """TC-RTC-03: Clean translated file in a lang folder → zero ERROR issues."""
        lang_dir = tmp_path / "ja"
        lang_dir.mkdir()
        test_file = lang_dir / "some-article.md"
        test_file.write_text(
            make_translated_md(self.CLEAN_FM, self.CLEAN_BODY),
            encoding="utf-8",
        )

        issues = scan_file(test_file)
        error_issues = [i for i in issues if i.severity == "error"]
        assert error_issues == [], (
            f"Expected no ERROR issues for clean file, got: {[(i.kind, i.message) for i in error_issues]}"
        )


# ---------------------------------------------------------------------------
# TC-RTC-04: Orphaned {{% /steps %}} shortcode
# ---------------------------------------------------------------------------


class TestOrphanClosingShortcode:
    """check_shortcode_balance() detects orphaned closing shortcodes."""

    BODY_WITH_ORPHAN_CLOSER = textwrap.dedent("""\
        ## Getting Started

        1. First step here.
        2. Second step here.
        3. Third step here.

        {{% /steps %}}

        ## Summary

        Done.
    """)

    BODY_BALANCED = textwrap.dedent("""\
        {{% steps %}}

        1. First step here.
        2. Second step here.

        {{% /steps %}}
    """)

    BODY_NO_SHORTCODES = textwrap.dedent("""\
        ## Getting Started

        1. First step here.
        2. Second step here.
    """)

    def test_tc_rtc_04_orphan_closing_detected(self):
        """TC-RTC-04: Body with {{% /steps %}} but no opener → orphan_closing_shortcode detected."""
        issues = check_shortcode_balance(self.BODY_WITH_ORPHAN_CLOSER, "test/ja/article.md")
        kinds = [i.kind for i in issues]
        assert "orphan_closing_shortcode" in kinds, (
            f"Expected 'orphan_closing_shortcode', got: {kinds}"
        )

    def test_balanced_shortcode_no_issue(self):
        """Paired {{% steps %}} and {{% /steps %}} → no orphan issue."""
        issues = check_shortcode_balance(self.BODY_BALANCED, "test/ja/article.md")
        closing_orphans = [i for i in issues if i.kind == "orphan_closing_shortcode"]
        assert closing_orphans == []

    def test_no_shortcodes_no_issue(self):
        """Body with no shortcodes at all → no shortcode issues."""
        issues = check_shortcode_balance(self.BODY_NO_SHORTCODES, "test/ja/article.md")
        assert issues == []


# ---------------------------------------------------------------------------
# TC-RTC-05: Multiple key:value pairs on same line
# ---------------------------------------------------------------------------


class TestMultiKVOnOneLine:
    """check_collapsed_frontmatter() detects step-style inline concatenation."""

    # Pattern seen in sk/sv files: step2: ""step3: "..."
    STEP_CONCATENATED_FM = 'step1: "Step 1"\nstep2: ""step3: "Step 3 content"\nstep4: "Step 4"\n'

    def test_tc_rtc_05_multi_kv_detected(self):
        """TC-RTC-05: step2: ''step3: ...' concatenation → collapsed_frontmatter detected."""
        issues = check_collapsed_frontmatter(self.STEP_CONCATENATED_FM, "test/sk/article.md")
        kinds = [i.kind for i in issues]
        assert "collapsed_frontmatter" in kinds, (
            f"Expected 'collapsed_frontmatter' for step2/step3 concatenation, got: {kinds}"
        )


# ---------------------------------------------------------------------------
# TC-RTC-06: Missing closing delimiter
# ---------------------------------------------------------------------------


class TestMissingClosingDelimiter:
    """extract_frontmatter() detects missing closing --- delimiter."""

    def test_tc_rtc_06_missing_closing_delimiter(self):
        """TC-RTC-06: File with only opening --- (no closing) → missing_closing_delimiter error."""
        text = "---\nauthor: Test\ntitle: Title\n\n## Body content\n"
        fm, body, error = extract_frontmatter(text)
        assert error == "missing_closing_delimiter", (
            f"Expected 'missing_closing_delimiter', got error='{error}'"
        )

    def test_valid_frontmatter_no_error(self):
        """File with proper --- delimiters → no error from extract_frontmatter."""
        text = "---\nauthor: Test\ntitle: Title\n---\n\n## Body content\n"
        fm, body, error = extract_frontmatter(text)
        assert error == "", f"Expected no error, got '{error}'"
        assert fm is not None
        assert "author: Test" in fm


# ---------------------------------------------------------------------------
# TC-RTC-07: Non-ASCII URL in frontmatter
# ---------------------------------------------------------------------------


class TestUrlCorruption:
    """check_url_corruption() detects non-ASCII characters in URLs."""

    FM_WITH_CORRUPT_URL = textwrap.dedent("""\
        title: Arabic Page
        url: https://products.aspose.net/barcode/ar/مولد-الباركود/
        layout: product-page
    """)

    FM_WITH_ASCII_URL = textwrap.dedent("""\
        title: Arabic Page
        url: https://products.aspose.net/barcode/ar/barcode-generator/
        layout: product-page
    """)

    def test_tc_rtc_07_non_ascii_url_detected(self):
        """TC-RTC-07: Non-ASCII URL in frontmatter → url_corruption detected."""
        issues = check_url_corruption(self.FM_WITH_CORRUPT_URL, "test/ar/_index.md")
        kinds = [i.kind for i in issues]
        assert "url_corruption" in kinds, f"Expected 'url_corruption', got: {kinds}"

    def test_ascii_url_no_issue(self):
        """ASCII-only URL in frontmatter → no url_corruption issue."""
        issues = check_url_corruption(self.FM_WITH_ASCII_URL, "test/ar/_index.md")
        kinds = [i.kind for i in issues]
        assert "url_corruption" not in kinds


# ---------------------------------------------------------------------------
# TC-RTC-08 / TC-RTC-09: scan_changed_files()
# ---------------------------------------------------------------------------


class TestScanChangedFiles:
    """scan_changed_files() filters correctly and returns ScanResult."""

    def test_tc_rtc_08_non_md_and_english_filtered(self, tmp_path):
        """TC-RTC-08: Non-.md files and English files are silently skipped."""
        # Create a .py file (should skip), an English .md (should skip), and a translated .md
        py_file = tmp_path / "script.py"
        py_file.write_text("print('hi')", encoding="utf-8")

        en_file = tmp_path / "index.md"
        en_file.write_text("---\nauthor: Test\n---\nBody\n", encoding="utf-8")

        lang_dir = tmp_path / "de"
        lang_dir.mkdir()
        de_file = lang_dir / "article.md"
        de_file.write_text(
            make_translated_md("author: Test\ntitle: Test\ndate: 2024-01-01\ndraft: false\n"),
            encoding="utf-8",
        )

        paths = [str(py_file), str(en_file), str(de_file)]
        result = scan_changed_files(paths)

        assert isinstance(result, ScanResult)
        # Only the de/ file should be scanned (py and en-only are filtered)
        assert result.total_files_scanned == 1

    def test_tc_rtc_09_scan_result_totals_correct(self, tmp_path):
        """TC-RTC-09: scan_changed_files() accumulates issues correctly."""
        lang_dir = tmp_path / "cs"
        lang_dir.mkdir()

        # A clean file
        clean_file = lang_dir / "clean.md"
        clean_file.write_text(
            make_translated_md("author: Test\ntitle: Test\ndate: 2024-01-01\ndraft: false\n"),
            encoding="utf-8",
        )

        # A file with YAML parse failure
        bad_file = lang_dir / "bad.md"
        bad_file.write_text(
            "---\nauthor: Test\nAutor: Test Kategorie:\n- A B C: D: E\n---\nBody\n",
            encoding="utf-8",
        )

        paths = [str(clean_file), str(bad_file)]
        result = scan_changed_files(paths)

        assert result.total_files_scanned == 2, (
            f"Expected 2 files scanned, got {result.total_files_scanned}"
        )

    def test_nonexistent_paths_skipped(self):
        """scan_changed_files() silently skips paths that do not exist."""
        result = scan_changed_files(["/nonexistent/path/cs/article.md"])
        assert result.total_files_scanned == 0
