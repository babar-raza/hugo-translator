"""
Comprehensive tests for implementation verification script.

Tests cover:
- File existence checking
- Test collection logic
- Import validation
- Syntax checking
- Report generation
- Both success and failure scenarios
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess
import sys

import pytest

# Import the verification script modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from verify_implementation import (
    VerificationResult,
    VerificationSuite,
    Reporter,
)


class TestVerificationResult:
    """Test VerificationResult dataclass."""

    def test_create_verification_result(self):
        """Test creating a verification result."""
        result = VerificationResult(
            check_name="test_check",
            expected="value1",
            actual="value1",
            passed=True,
            details="Test passed"
        )

        assert result.check_name == "test_check"
        assert result.expected == "value1"
        assert result.actual == "value1"
        assert result.passed is True
        assert result.details == "Test passed"

    def test_verification_result_to_dict(self):
        """Test converting verification result to dict."""
        result = VerificationResult(
            check_name="test_check",
            expected="value1",
            actual="value2",
            passed=False,
            details="Values don't match"
        )

        result_dict = result.to_dict()

        assert result_dict["check_name"] == "test_check"
        assert result_dict["expected"] == "value1"
        assert result_dict["actual"] == "value2"
        assert result_dict["passed"] is False
        assert result_dict["details"] == "Values don't match"


class TestVerificationSuite:
    """Test VerificationSuite functionality."""

    @pytest.fixture
    def temp_project(self, tmp_path):
        """Create a temporary project structure for testing."""
        # Create directories
        (tmp_path / "scripts").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()

        # Create some test files
        (tmp_path / "scripts" / "test_script.py").write_text("print('hello')")
        (tmp_path / "src" / "module.py").write_text("def func(): pass")

        return tmp_path

    def test_verify_files_all_exist(self, temp_project):
        """Test file verification when all files exist (happy path)."""
        suite = VerificationSuite(temp_project)
        results = suite.verify_files([
            "scripts/test_script.py",
            "src/module.py"
        ])

        # Should have individual results plus summary
        assert len(results) >= 2

        # All individual checks should pass
        individual_results = [r for r in results if r.check_name.startswith("file_exists:")]
        assert all(r.passed for r in individual_results)

        # Summary should pass
        summary = [r for r in results if r.check_name == "file_existence_summary"][0]
        assert summary.passed is True
        assert summary.actual == 2

    def test_verify_files_some_missing(self, temp_project):
        """Test file verification when some files are missing (failure path)."""
        suite = VerificationSuite(temp_project)
        results = suite.verify_files([
            "scripts/test_script.py",
            "scripts/missing_file.py",
            "src/module.py"
        ])

        # Summary should fail
        summary = [r for r in results if r.check_name == "file_existence_summary"][0]
        assert summary.passed is False
        assert summary.actual == 2  # Only 2 out of 3 exist

        # Check for the missing file result
        missing_file_result = [r for r in results if "missing_file" in r.check_name][0]
        assert missing_file_result.passed is False

    def test_verify_directory_structure(self, temp_project):
        """Test directory structure verification."""
        suite = VerificationSuite(temp_project)
        results = suite.verify_directory_structure([
            "scripts",
            "src",
            "tests"
        ])

        # All directories should exist
        summary = [r for r in results if r.check_name == "directory_structure_summary"][0]
        assert summary.passed is True
        assert summary.actual == 3

    def test_verify_directory_structure_missing(self, temp_project):
        """Test directory structure verification with missing directories."""
        suite = VerificationSuite(temp_project)
        results = suite.verify_directory_structure([
            "scripts",
            "nonexistent_dir",
            "tests"
        ])

        # Should fail because one directory is missing
        summary = [r for r in results if r.check_name == "directory_structure_summary"][0]
        assert summary.passed is False
        assert summary.actual == 2  # Only 2 out of 3 exist

    @patch('subprocess.run')
    def test_verify_tests_collection(self, mock_run, temp_project):
        """Test test collection logic."""
        # Mock pytest output showing 10 tests collected
        mock_run.return_value = Mock(
            stdout="collected 10 tests\n",
            stderr="",
            returncode=0
        )

        suite = VerificationSuite(temp_project)
        results = suite.verify_tests(min_expected_tests=5)

        # Should pass because 10 >= 5
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].actual == 10

        # Verify subprocess was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "-m" in call_args[0][0]
        assert "pytest" in call_args[0][0]
        assert "--collect-only" in call_args[0][0]

    @patch('subprocess.run')
    def test_verify_tests_insufficient(self, mock_run, temp_project):
        """Test test collection when count is insufficient."""
        # Mock pytest output showing only 3 tests
        mock_run.return_value = Mock(
            stdout="3 selected\n",
            stderr="",
            returncode=0
        )

        suite = VerificationSuite(temp_project)
        results = suite.verify_tests(min_expected_tests=10)

        # Should fail because 3 < 10
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].actual == 3

    @patch('subprocess.run')
    def test_verify_tests_timeout(self, mock_run, temp_project):
        """Test test collection handling timeout."""
        # Mock timeout exception
        mock_run.side_effect = subprocess.TimeoutExpired("pytest", 60)

        suite = VerificationSuite(temp_project)
        results = suite.verify_tests(min_expected_tests=5)

        # Should fail with timeout
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].actual == "TIMEOUT"

    @patch('subprocess.run')
    def test_verify_tests_pytest_not_found(self, mock_run, temp_project):
        """Test test collection when pytest is not installed."""
        # Mock pytest not found
        mock_run.side_effect = FileNotFoundError("pytest not found")

        suite = VerificationSuite(temp_project)
        results = suite.verify_tests(min_expected_tests=5)

        # Should fail with pytest not found
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].actual == "PYTEST_NOT_FOUND"

    def test_verify_imports_success(self, temp_project):
        """Test import validation with successful imports."""
        # Create a simple module
        (temp_project / "src" / "__init__.py").write_text("")
        (temp_project / "src" / "test_module.py").write_text("def test_func(): pass")

        suite = VerificationSuite(temp_project)
        results = suite.verify_imports(["sys", "os"])  # Use stdlib modules

        # Should have individual results plus summary
        summary = [r for r in results if r.check_name == "import_validation_summary"][0]
        assert summary.passed is True

    def test_verify_imports_failure(self, temp_project):
        """Test import validation with failed imports."""
        suite = VerificationSuite(temp_project)
        results = suite.verify_imports(["nonexistent_module_xyz"])

        # Should fail
        summary = [r for r in results if r.check_name == "import_validation_summary"][0]
        assert summary.passed is False
        assert summary.actual == 0

    def test_verify_syntax_valid(self, temp_project):
        """Test syntax validation with valid Python files."""
        # Create valid Python file
        valid_file = temp_project / "test_valid.py"
        valid_file.write_text("def hello():\n    print('hello')\n")

        suite = VerificationSuite(temp_project)
        results = suite.verify_syntax(["test_valid.py"])

        # Should pass
        summary = [r for r in results if r.check_name == "syntax_validation_summary"][0]
        assert summary.passed is True
        assert summary.actual == 1

    def test_verify_syntax_invalid(self, temp_project):
        """Test syntax validation with invalid Python files."""
        # Create invalid Python file
        invalid_file = temp_project / "test_invalid.py"
        invalid_file.write_text("def hello(\n    print('missing closing paren')\n")

        suite = VerificationSuite(temp_project)
        results = suite.verify_syntax(["test_invalid.py"])

        # Should fail
        summary = [r for r in results if r.check_name == "syntax_validation_summary"][0]
        assert summary.passed is False
        assert summary.actual == 0

    def test_verify_syntax_file_not_found(self, temp_project):
        """Test syntax validation when file doesn't exist."""
        suite = VerificationSuite(temp_project)
        results = suite.verify_syntax(["nonexistent.py"])

        # Should fail
        individual_result = [r for r in results if r.check_name == "syntax:nonexistent.py"][0]
        assert individual_result.passed is False
        assert individual_result.actual == "FILE_NOT_FOUND"

    def test_get_summary_all_pass(self, temp_project):
        """Test summary generation when all checks pass."""
        suite = VerificationSuite(temp_project)

        # Add some passing results
        suite.results = [
            VerificationResult("check1", True, True, True, ""),
            VerificationResult("check2", True, True, True, ""),
            VerificationResult("check3", True, True, True, ""),
        ]

        summary = suite.get_summary()

        assert summary["total_checks"] == 3
        assert summary["passed_checks"] == 3
        assert summary["failed_checks"] == 0
        assert summary["pass_rate"] == 1.0
        assert summary["all_passed"] is True

    def test_get_summary_some_fail(self, temp_project):
        """Test summary generation when some checks fail."""
        suite = VerificationSuite(temp_project)

        # Add mixed results
        suite.results = [
            VerificationResult("check1", True, True, True, ""),
            VerificationResult("check2", True, False, False, ""),
            VerificationResult("check3", True, True, True, ""),
        ]

        summary = suite.get_summary()

        assert summary["total_checks"] == 3
        assert summary["passed_checks"] == 2
        assert summary["failed_checks"] == 1
        assert summary["pass_rate"] == pytest.approx(0.666, rel=0.01)
        assert summary["all_passed"] is False


class TestReporter:
    """Test Reporter functionality."""

    def test_generate_json_report(self, tmp_path):
        """Test JSON report generation."""
        results = [
            VerificationResult("check1", "expected", "actual", True, "Test passed"),
            VerificationResult("check2", 10, 5, False, "Count mismatch"),
        ]
        summary = {
            "total_checks": 2,
            "passed_checks": 1,
            "failed_checks": 1,
            "pass_rate": 0.5,
            "all_passed": False
        }

        output_file = tmp_path / "report.json"
        Reporter.generate_json_report(results, summary, output_file)

        # Verify file was created and contains valid JSON
        assert output_file.exists()
        with open(output_file) as f:
            report = json.load(f)

        assert report["summary"]["total_checks"] == 2
        assert report["summary"]["passed_checks"] == 1
        assert len(report["results"]) == 2

    def test_generate_markdown_report(self):
        """Test Markdown report generation."""
        results = [
            VerificationResult("file_exists:test.py", True, True, True, "File exists"),
            VerificationResult("test_count", 10, 5, False, "Insufficient tests"),
        ]
        summary = {
            "total_checks": 2,
            "passed_checks": 1,
            "failed_checks": 1,
            "pass_rate": 0.5,
            "all_passed": False
        }

        markdown = Reporter.generate_markdown_report(results, summary)

        # Verify markdown contains key elements
        assert "# Implementation Verification Report" in markdown
        assert "## Summary" in markdown
        assert "Total Checks:** 2" in markdown
        assert "Passed:** 1" in markdown
        assert "Failed:** 1" in markdown
        assert "[FAIL]" in markdown

    def test_print_console_report(self, capsys):
        """Test console report printing."""
        results = [
            VerificationResult("check1", True, True, True, ""),
            VerificationResult("check2", 10, 5, False, "Count too low"),
        ]
        summary = {
            "total_checks": 2,
            "passed_checks": 1,
            "failed_checks": 1,
            "pass_rate": 0.5,
            "all_passed": False
        }

        Reporter.print_console_report(results, summary)

        captured = capsys.readouterr()
        output = captured.out

        assert "IMPLEMENTATION VERIFICATION REPORT" in output
        assert "Total Checks:  2" in output
        assert "Passed:        1" in output
        assert "Failed:        1" in output
        assert "[X] check2" in output


class TestIntegration:
    """Integration tests for the verification script."""

    def test_full_verification_workflow(self, tmp_path):
        """Test complete verification workflow."""
        # Create a minimal project structure
        (tmp_path / "scripts").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "scripts" / "test.py").write_text("print('test')")

        suite = VerificationSuite(tmp_path)

        # Run multiple verifications
        suite.verify_directory_structure(["scripts", "src"])
        suite.verify_files(["scripts/test.py"])
        suite.verify_syntax(["scripts/test.py"])

        # Get summary
        summary = suite.get_summary()

        # All checks should pass
        assert summary["all_passed"] is True
        assert summary["failed_checks"] == 0

    def test_verification_with_failures(self, tmp_path):
        """Test verification workflow with failures."""
        suite = VerificationSuite(tmp_path)

        # These should fail
        suite.verify_directory_structure(["nonexistent"])
        suite.verify_files(["missing.py"])

        # Get summary
        summary = suite.get_summary()

        # Should have failures
        assert summary["all_passed"] is False
        assert summary["failed_checks"] > 0
