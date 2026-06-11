"""
Integration tests for verification report generation.

Tests that reports are generated correctly when verification is enabled.
"""

import json
import sys
import tempfile
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.verification.checks.base import VerificationIssue, VerificationResult
from src.verification.report import VerificationReporter, write_report


def test_end_to_end_json_report():
    """Test complete JSON report generation workflow."""
    # Create sample verification result
    issues = [
        VerificationIssue(
            severity="error",
            check_name="language_detection",
            location="frontmatter.title",
            message="Expected de, detected en",
            translated_text="Hello World",
        ),
    ]

    result = VerificationResult(
        issues=issues,
        metadata={"target_lang": "de"},
    )
    result.check_results = {
        "language_detection": {
            "passed": False,
            "error_count": 1,
        }
    }

    # Create report
    results = [(Path("test/file.md"), result)]

    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "verification.json"
        write_report(report_path, results)

        # Verify report exists and is valid JSON
        assert report_path.exists()

        with open(report_path, encoding="utf-8") as f:
            report_data = json.load(f)

        # Validate structure
        assert report_data["summary"]["total_files"] == 1
        assert report_data["summary"]["failed"] == 1
        assert report_data["summary"]["total_errors"] == 1
        assert len(report_data["files"]) == 1
        assert report_data["files"][0]["passed"] is False


def test_end_to_end_markdown_report():
    """Test complete Markdown report generation workflow."""
    # Create sample verification result
    issues = [
        VerificationIssue(
            severity="warning",
            check_name="completeness_check",
            location="frontmatter.description",
            message="Field may be incomplete",
        ),
    ]

    result = VerificationResult(
        issues=issues,
        metadata={"target_lang": "fr"},
    )
    result.check_results = {
        "completeness_check": {
            "passed": True,  # Warnings don't fail
            "warning_count": 1,
        }
    }

    # Create report
    results = [(Path("test/another_file.md"), result)]

    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "verification.md"
        write_report(report_path, results)

        # Verify report exists
        assert report_path.exists()

        content = report_path.read_text(encoding="utf-8")

        # Validate content
        assert "# Verification Report" in content
        assert "## Summary" in content
        assert "another_file.md" in content  # Just check filename, not full path
        assert "WARNING" in content
        assert "completeness_check" in content
        assert "Field may be incomplete" in content


def test_batch_report_multiple_files():
    """Test report generation for multiple files."""
    # Create multiple results
    result1 = VerificationResult(
        issues=[
            VerificationIssue(
                severity="error",
                check_name="language_detection",
                location="field1",
                message="Error 1",
            )
        ]
    )

    result2 = VerificationResult()  # No issues (passed)

    result3 = VerificationResult(
        issues=[
            VerificationIssue(
                severity="warning",
                check_name="completeness_check",
                location="field2",
                message="Warning 1",
            )
        ]
    )

    results = [
        (Path("file1.md"), result1),
        (Path("file2.md"), result2),
        (Path("file3.md"), result3),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "batch_report.json"
        write_report(report_path, results)

        with open(report_path, encoding="utf-8") as f:
            report_data = json.load(f)

        # Validate summary
        assert report_data["summary"]["total_files"] == 3
        assert report_data["summary"]["passed"] == 2  # file2 and file3 (warning doesn't fail)
        assert report_data["summary"]["failed"] == 1  # file1
        assert report_data["summary"]["total_errors"] == 1
        assert report_data["summary"]["total_warnings"] == 1


def test_reporter_console_summary():
    """Test console summary generation."""
    result = VerificationResult(
        issues=[
            VerificationIssue(
                severity="error",
                check_name="test",
                location="loc",
                message="msg",
            )
        ]
    )

    results = [(Path("test.md"), result)]

    reporter = VerificationReporter()
    summary = reporter.to_console_summary(results)

    assert "Verification Summary:" in summary
    assert "1 errors" in summary


if __name__ == "__main__":
    # Allow running tests directly
    test_end_to_end_json_report()
    test_end_to_end_markdown_report()
    test_batch_report_multiple_files()
    test_reporter_console_summary()
    print("All integration tests passed!")
