"""
Unit tests for verification reporting module.

Tests JSON and Markdown report generation.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.verification.checks.base import VerificationIssue, VerificationResult
from src.verification.report import (
    VerificationReporter,
    write_report,
)


@pytest.fixture
def sample_issues():
    """Create sample verification issues for testing."""
    return [
        VerificationIssue(
            severity="error",
            check_name="language_detection",
            location="frontmatter.body.block[0].title_left",
            message="Expected de, detected en",
            source_text="Merge PowerPoint Presentations",
            translated_text="Merge PowerPoint Presentations",
            metadata={"detected_lang": "en", "expected_lang": "de"},
        ),
        VerificationIssue(
            severity="warning",
            check_name="language_detection",
            location="frontmatter.body.block[1].description",
            message="Low confidence detection",
            translated_text="Einige gemischte Inhalte here",
            metadata={"confidence": 0.65},
        ),
        VerificationIssue(
            severity="info",
            check_name="completeness_check",
            location="frontmatter.title",
            message="Field translated successfully",
        ),
    ]


@pytest.fixture
def sample_verification_result(sample_issues):
    """Create a sample verification result."""
    result = VerificationResult(
        issues=sample_issues,
        metadata={"target_lang": "de", "checks_run": ["language_detection", "completeness_check"]},
    )
    result.check_results = {
        "language_detection": {
            "passed": False,
            "issue_count": 2,
            "error_count": 1,
            "warning_count": 1,
        },
        "completeness_check": {
            "passed": True,
            "issue_count": 1,
            "error_count": 0,
            "warning_count": 0,
        },
    }
    return result


@pytest.fixture
def sample_results(sample_verification_result):
    """Create sample results list."""
    return [
        (Path("content/de/presentation-merger/_index.md"), sample_verification_result),
    ]


class TestVerificationReporter:
    """Test VerificationReporter class."""

    def test_json_report_structure(self, sample_results):
        """Test JSON report has correct structure."""
        reporter = VerificationReporter()
        json_output = reporter.to_json(sample_results)

        # Parse JSON to verify structure
        report = json.loads(json_output)

        # Check top-level keys
        assert "timestamp" in report
        assert "summary" in report
        assert "files" in report

        # Check summary
        summary = report["summary"]
        assert summary["total_files"] == 1
        assert summary["passed"] == 0
        assert summary["failed"] == 1
        assert summary["total_errors"] == 1
        assert summary["total_warnings"] == 1
        assert summary["total_info"] == 1

        # Check files
        assert len(report["files"]) == 1
        file_data = report["files"][0]
        assert file_data["path"] == "content/de/presentation-merger/_index.md"
        assert file_data["passed"] is False
        assert file_data["error_count"] == 1
        assert file_data["warning_count"] == 1
        assert file_data["info_count"] == 1

    def test_json_report_includes_issues(self, sample_results):
        """Test JSON report includes detailed issue information."""
        reporter = VerificationReporter()
        json_output = reporter.to_json(sample_results, include_issues=True)

        report = json.loads(json_output)
        file_data = report["files"][0]

        assert "issues" in file_data
        issues = file_data["issues"]
        assert len(issues) == 3

        # Check first issue
        issue = issues[0]
        assert issue["severity"] == "error"
        assert issue["check_name"] == "language_detection"
        assert issue["location"] == "frontmatter.body.block[0].title_left"
        assert "Expected de, detected en" in issue["message"]
        assert "source_text" in issue
        assert "translated_text" in issue

    def test_json_report_excludes_issues(self, sample_results):
        """Test JSON report can exclude detailed issues."""
        reporter = VerificationReporter()
        json_output = reporter.to_json(sample_results, include_issues=False)

        report = json.loads(json_output)
        file_data = report["files"][0]

        assert "issues" not in file_data

    def test_json_report_no_timestamp(self, sample_results):
        """Test JSON report without timestamp."""
        reporter = VerificationReporter(include_timestamps=False)
        json_output = reporter.to_json(sample_results)

        report = json.loads(json_output)
        assert "timestamp" not in report

    def test_markdown_report_structure(self, sample_results):
        """Test Markdown report has correct structure."""
        reporter = VerificationReporter()
        md_output = reporter.to_markdown(sample_results)

        # Check key sections are present
        assert "# Verification Report" in md_output
        assert "## Summary" in md_output
        assert "## Files" in md_output
        assert "### content/de/presentation-merger/_index.md" in md_output

        # Check summary stats
        assert "**Total Files**: 1" in md_output
        assert "**Passed**: 0 (0.0%)" in md_output
        assert "**Failed**: 1 (100.0%)" in md_output
        assert "**Total Errors**: 1" in md_output
        assert "**Total Warnings**: 1" in md_output

    def test_markdown_report_includes_issues(self, sample_results):
        """Test Markdown report includes issue details."""
        reporter = VerificationReporter()
        md_output = reporter.to_markdown(sample_results, include_issues=True)

        # Check issue section exists
        assert "#### Issues" in md_output

        # Check specific issues
        assert "ERROR" in md_output
        assert "language_detection" in md_output
        assert "Expected de, detected en" in md_output
        assert "WARNING" in md_output
        assert "Low confidence detection" in md_output

    def test_markdown_report_excludes_issues(self, sample_results):
        """Test Markdown report can exclude issues."""
        reporter = VerificationReporter()
        md_output = reporter.to_markdown(sample_results, include_issues=False)

        # Issues section should not exist
        assert "#### Issues" not in md_output

    def test_markdown_report_status_indicators(self, sample_results):
        """Test Markdown report shows status indicators correctly."""
        reporter = VerificationReporter()
        md_output = reporter.to_markdown(sample_results)

        # Check for status emoji/text
        assert "✗" in md_output  # Failed marker
        assert "FAILED" in md_output

    def test_console_summary(self, sample_results):
        """Test console summary format."""
        reporter = VerificationReporter()
        summary = reporter.to_console_summary(sample_results)

        assert "Verification Summary:" in summary
        assert "Files: 1 (0 passed, 1 failed)" in summary
        assert "Issues: 1 errors, 1 warnings, 1 info" in summary

    def test_multiple_files(self, sample_verification_result):
        """Test report generation with multiple files."""
        results = [
            (Path("file1.md"), sample_verification_result),
            (Path("file2.md"), VerificationResult()),  # Passed
            (Path("file3.md"), sample_verification_result),
        ]

        reporter = VerificationReporter()
        json_output = reporter.to_json(results)
        report = json.loads(json_output)

        assert report["summary"]["total_files"] == 3
        assert report["summary"]["passed"] == 1
        assert report["summary"]["failed"] == 2
        assert len(report["files"]) == 3

    def test_empty_results(self):
        """Test report generation with no results."""
        reporter = VerificationReporter()
        json_output = reporter.to_json([])
        report = json.loads(json_output)

        assert report["summary"]["total_files"] == 0
        assert report["summary"]["passed"] == 0
        assert report["summary"]["failed"] == 0
        assert len(report["files"]) == 0


class TestWriteReport:
    """Test write_report function."""

    def test_write_json_auto_detect(self, sample_results):
        """Test writing JSON report with auto-detect format."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "verification.json"

            write_report(report_path, sample_results, format_type="auto")

            assert report_path.exists()

            # Verify it's valid JSON
            with open(report_path, encoding="utf-8") as f:
                report = json.load(f)
                assert "summary" in report
                assert "files" in report

    def test_write_markdown_auto_detect(self, sample_results):
        """Test writing Markdown report with auto-detect format."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "verification.md"

            write_report(report_path, sample_results, format_type="auto")

            assert report_path.exists()

            # Verify it's Markdown
            content = report_path.read_text(encoding="utf-8")
            assert "# Verification Report" in content
            assert "## Summary" in content

    def test_write_json_explicit(self, sample_results):
        """Test writing JSON report with explicit format."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.txt"

            write_report(report_path, sample_results, format_type="json")

            assert report_path.exists()

            # Verify it's valid JSON
            with open(report_path, encoding="utf-8") as f:
                report = json.load(f)
                assert "summary" in report

    def test_write_markdown_explicit(self, sample_results):
        """Test writing Markdown report with explicit format."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.txt"

            write_report(report_path, sample_results, format_type="markdown")

            assert report_path.exists()

            content = report_path.read_text(encoding="utf-8")
            assert "# Verification Report" in content

    def test_write_creates_parent_directories(self, sample_results):
        """Test that write_report creates parent directories."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "reports" / "subdir" / "verification.json"

            write_report(report_path, sample_results)

            assert report_path.exists()
            assert report_path.parent.exists()

    def test_write_invalid_extension_auto_detect(self, sample_results):
        """Test that invalid extension raises error with auto-detect."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.txt"

            with pytest.raises(ValueError, match="Cannot auto-detect format"):
                write_report(report_path, sample_results, format_type="auto")

    def test_write_invalid_format_type(self, sample_results):
        """Test that invalid format_type raises error."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.json"

            with pytest.raises(ValueError, match="Invalid format_type"):
                write_report(report_path, sample_results, format_type="xml")

    def test_write_utf8_encoding(self, sample_results):
        """Test that report is written with UTF-8 encoding."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "verification.md"

            write_report(report_path, sample_results)

            # Read and verify UTF-8 characters are preserved
            content = report_path.read_text(encoding="utf-8")
            assert "✗" in content or "✓" in content  # Emoji should be preserved


class TestIssueTextTruncation:
    """Test that long text is properly truncated in reports."""

    def test_json_truncates_long_text(self):
        """Test JSON report truncates long text fields."""
        long_text = "A" * 300  # Longer than 200 char limit

        issue = VerificationIssue(
            severity="error",
            check_name="test",
            location="test.field",
            message="Test message",
            source_text=long_text,
            translated_text=long_text,
        )

        result = VerificationResult(issues=[issue])
        results = [(Path("test.md"), result)]

        reporter = VerificationReporter()
        json_output = reporter.to_json(results)
        report = json.loads(json_output)

        issue_data = report["files"][0]["issues"][0]
        # to_dict truncates to 200 chars
        assert len(issue_data["source_text"]) == 200
        assert len(issue_data["translated_text"]) == 200

    def test_markdown_truncates_long_text(self):
        """Test Markdown report truncates long text fields."""
        long_text = "B" * 150  # Longer than 100 char limit for markdown

        issue = VerificationIssue(
            severity="warning",
            check_name="test",
            location="test.field",
            message="Test message",
            translated_text=long_text,
        )

        result = VerificationResult(issues=[issue])
        results = [(Path("test.md"), result)]

        reporter = VerificationReporter()
        md_output = reporter.to_markdown(results)

        # Should contain truncated text with ellipsis
        assert "..." in md_output
        # Full text should not be present
        assert long_text not in md_output


class TestCheckResultsInReport:
    """Test that check results are included in reports."""

    def test_json_includes_check_results(self, sample_verification_result):
        """Test JSON report includes check results."""
        results = [(Path("test.md"), sample_verification_result)]

        reporter = VerificationReporter()
        json_output = reporter.to_json(results)
        report = json.loads(json_output)

        file_data = report["files"][0]
        assert "check_results" in file_data

        check_results = file_data["check_results"]
        assert "language_detection" in check_results
        assert check_results["language_detection"]["passed"] is False
        assert check_results["language_detection"]["error_count"] == 1

        assert "completeness_check" in check_results
        assert check_results["completeness_check"]["passed"] is True

    def test_markdown_includes_check_results(self, sample_verification_result):
        """Test Markdown report includes check results."""
        results = [(Path("test.md"), sample_verification_result)]

        reporter = VerificationReporter()
        md_output = reporter.to_markdown(results)

        assert "Checks Run" in md_output
        assert "language_detection" in md_output
        assert "completeness_check" in md_output
        assert "✗" in md_output  # Failed check
        assert "✓" in md_output  # Passed check
