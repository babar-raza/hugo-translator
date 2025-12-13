#!/usr/bin/env python3
"""
Tests for Production Readiness Validation Runner

Tests the wrapper that executes production_readiness_check.py and validates results.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import after path setup
from scripts.validate_production_readiness import (
    CheckResult,
    EvidenceReporter,
    OutputParser,
    ProductionReadinessValidator,
    ReadinessRunner,
    ResultValidator,
    ValidationReport
)


# ============================================================================
# ReadinessRunner Tests
# ============================================================================


def test_readiness_runner_initialization():
    """Test ReadinessRunner can be initialized."""
    project_root = Path(__file__).parent.parent.parent
    runner = ReadinessRunner(project_root)

    assert runner is not None
    assert runner.project_root == project_root
    assert runner.script_path.name == "production_readiness_check.py"


@patch('subprocess.run')
def test_readiness_runner_execute_success(mock_run):
    """Test successful execution of readiness check."""
    # Mock successful execution
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "✓ Test Check: passed\n"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    project_root = Path(__file__).parent.parent.parent
    runner = ReadinessRunner(project_root)

    exit_code, stdout, stderr, execution_time = runner.execute()

    assert exit_code == 0
    assert "✓ Test Check" in stdout
    assert stderr == ""
    assert execution_time >= 0


@patch('subprocess.run')
def test_readiness_runner_execute_failure(mock_run):
    """Test failed execution of readiness check."""
    # Mock failed execution
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = "✗ Test Check: failed\n"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    project_root = Path(__file__).parent.parent.parent
    runner = ReadinessRunner(project_root)

    exit_code, stdout, stderr, execution_time = runner.execute()

    assert exit_code == 1
    assert "✗ Test Check" in stdout


@patch('subprocess.run')
def test_readiness_runner_timeout(mock_run):
    """Test timeout handling."""
    # Mock timeout
    mock_run.side_effect = subprocess.TimeoutExpired("cmd", 10)

    project_root = Path(__file__).parent.parent.parent
    runner = ReadinessRunner(project_root)

    exit_code, stdout, stderr, execution_time = runner.execute(timeout=10)

    assert exit_code == 1
    assert "timed out" in stderr.lower()


# ============================================================================
# OutputParser Tests
# ============================================================================


def test_output_parser_parse_success():
    """Test parsing successful check output."""
    parser = OutputParser()

    stdout = """
✓ Directories: All required directories exist
✓ Config Files: Model registry valid (5 models)
✓ Dependencies: All required packages installed
"""

    checks = parser.parse(stdout, "")

    assert len(checks) == 3
    assert all(check.passed for check in checks)
    assert checks[0].name == "Directories"
    assert "required directories" in checks[0].message


def test_output_parser_parse_failures():
    """Test parsing failed check output."""
    parser = OutputParser()

    stdout = """
✓ Directories: All required directories exist
✗ Config Files: model_registry.yaml not found
✓ Dependencies: All required packages installed
"""

    checks = parser.parse(stdout, "")

    assert len(checks) == 3
    assert checks[1].passed == False
    assert checks[1].name == "Config Files"


def test_output_parser_extract_summary():
    """Test extracting summary line."""
    parser = OutputParser()

    stdout = """
✓ Check 1: passed
✗ Check 2: failed
RESULTS: 1/2 checks passed
"""

    summary = parser.extract_summary(stdout)

    assert summary is not None
    assert "RESULTS:" in summary
    assert "1/2" in summary


def test_output_parser_extract_warnings():
    """Test extracting warnings."""
    parser = OutputParser()

    stdout = """
✓ Check 1: passed
✓ Check 2: OK (warning: low disk space)
Warning: Memory below recommended threshold
"""

    warnings = parser.extract_warnings(stdout)

    assert len(warnings) >= 1
    assert any("warning" in w.lower() for w in warnings)


# ============================================================================
# ResultValidator Tests
# ============================================================================


def test_result_validator_all_passed():
    """Test validation when all checks pass."""
    validator = ResultValidator(strict=False)

    checks = [
        CheckResult("Check 1", True, "passed"),
        CheckResult("Check 2", True, "passed"),
    ]

    result = validator.validate(checks, exit_code=0, warnings=[])

    assert result is True


def test_result_validator_with_failures():
    """Test validation when checks fail."""
    validator = ResultValidator(strict=False)

    checks = [
        CheckResult("Check 1", True, "passed"),
        CheckResult("Check 2", False, "failed"),
    ]

    result = validator.validate(checks, exit_code=1, warnings=[])

    assert result is False


def test_result_validator_strict_mode_warnings():
    """Test strict mode fails on warnings."""
    validator = ResultValidator(strict=True)

    checks = [
        CheckResult("Check 1", True, "passed"),
        CheckResult("Check 2", True, "passed"),
    ]

    warnings = ["Warning: Low disk space"]

    result = validator.validate(checks, exit_code=0, warnings=warnings)

    assert result is False


def test_result_validator_non_strict_warnings():
    """Test non-strict mode allows warnings."""
    validator = ResultValidator(strict=False)

    checks = [
        CheckResult("Check 1", True, "passed"),
        CheckResult("Check 2", True, "passed"),
    ]

    warnings = ["Warning: Low disk space"]

    result = validator.validate(checks, exit_code=0, warnings=warnings)

    assert result is True


def test_result_validator_get_failed_checks():
    """Test getting list of failed checks."""
    validator = ResultValidator(strict=False)

    checks = [
        CheckResult("Check 1", True, "passed"),
        CheckResult("Check 2", False, "failed"),
        CheckResult("Check 3", True, "passed"),
        CheckResult("Check 4", False, "failed"),
    ]

    failed = validator.get_failed_checks(checks)

    assert len(failed) == 2
    assert failed[0].name == "Check 2"
    assert failed[1].name == "Check 4"


# ============================================================================
# EvidenceReporter Tests
# ============================================================================


def test_evidence_reporter_generate_json_report():
    """Test generating JSON evidence report."""
    reporter = EvidenceReporter()

    validation = ValidationReport(
        timestamp="2024-01-01T12:00:00",
        command="python scripts/production_readiness_check.py",
        exit_code=0,
        execution_time=5.5,
        checks=[
            CheckResult("Check 1", True, "passed"),
            CheckResult("Check 2", True, "passed"),
        ],
        stdout="output",
        stderr="",
        passed=True,
        retry_count=0,
        warnings=[]
    )

    report_json = reporter.generate_report(validation)

    # Parse JSON
    report_data = json.loads(report_json)

    assert report_data['timestamp'] == "2024-01-01T12:00:00"
    assert report_data['exit_code'] == 0
    assert report_data['passed'] is True
    assert len(report_data['checks']) == 2


def test_evidence_reporter_save_to_file():
    """Test saving report to file."""
    reporter = EvidenceReporter()

    validation = ValidationReport(
        timestamp="2024-01-01T12:00:00",
        command="python scripts/production_readiness_check.py",
        exit_code=0,
        execution_time=5.5,
        checks=[CheckResult("Check 1", True, "passed")],
        stdout="output",
        stderr="",
        passed=True,
        retry_count=0,
        warnings=[]
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.json"
        reporter.generate_report(validation, report_path)

        assert report_path.exists()

        # Load and verify
        report_data = json.loads(report_path.read_text())
        assert report_data['passed'] is True


def test_evidence_reporter_markdown_report():
    """Test generating markdown report."""
    reporter = EvidenceReporter()

    validation = ValidationReport(
        timestamp="2024-01-01T12:00:00",
        command="python scripts/production_readiness_check.py",
        exit_code=0,
        execution_time=5.5,
        checks=[
            CheckResult("Check 1", True, "passed"),
            CheckResult("Check 2", False, "failed"),
        ],
        stdout="output",
        stderr="",
        passed=False,
        retry_count=1,
        warnings=["Warning 1"]
    )

    report_md = reporter.generate_markdown_report(validation)

    assert "# Production Readiness Validation Report" in report_md
    assert "**Exit Code:** 0" in report_md
    assert "**Retries:** 1" in report_md
    assert "Check 1" in report_md
    assert "Check 2" in report_md
    assert "Warning 1" in report_md


# ============================================================================
# ProductionReadinessValidator Integration Tests
# ============================================================================


@patch.object(ReadinessRunner, 'execute')
def test_validator_successful_validation(mock_execute):
    """Test complete validation process with success."""
    # Mock successful execution
    mock_execute.return_value = (
        0,  # exit_code
        "✓ Check 1: passed\n✓ Check 2: passed\n",
        "",
        5.0
    )

    project_root = Path(__file__).parent.parent.parent
    validator = ProductionReadinessValidator(
        project_root=project_root,
        strict=False,
        max_retries=0
    )

    report = validator.validate()

    assert report is not None
    assert report.passed is True
    assert report.exit_code == 0
    assert len(report.checks) == 2


@patch.object(ReadinessRunner, 'execute')
def test_validator_failed_validation(mock_execute):
    """Test complete validation process with failure."""
    # Mock failed execution
    mock_execute.return_value = (
        1,  # exit_code
        "✓ Check 1: passed\n✗ Check 2: failed\n",
        "",
        5.0
    )

    project_root = Path(__file__).parent.parent.parent
    validator = ProductionReadinessValidator(
        project_root=project_root,
        strict=False,
        max_retries=0
    )

    report = validator.validate()

    assert report is not None
    assert report.passed is False
    assert report.exit_code == 1


@patch.object(ReadinessRunner, 'execute')
def test_validator_retry_logic(mock_execute):
    """Test retry logic on transient failures."""
    # First call fails with transient error, second succeeds
    mock_execute.side_effect = [
        (1, "", "Connection timeout error", 5.0),
        (0, "✓ Check 1: passed\n", "", 5.0)
    ]

    project_root = Path(__file__).parent.parent.parent
    validator = ProductionReadinessValidator(
        project_root=project_root,
        strict=False,
        max_retries=2,
        retry_delay=0  # No delay for tests
    )

    report = validator.validate()

    assert report is not None
    assert report.passed is True
    assert report.retry_count == 1
    assert mock_execute.call_count == 2


@patch.object(ReadinessRunner, 'execute')
def test_validator_no_retry_on_permanent_failure(mock_execute):
    """Test no retry on permanent failures."""
    # Permanent failure (missing file)
    mock_execute.return_value = (
        1,
        "✗ Config Files: model_registry.yaml not found\n",
        "",
        5.0
    )

    project_root = Path(__file__).parent.parent.parent
    validator = ProductionReadinessValidator(
        project_root=project_root,
        strict=False,
        max_retries=3,
        retry_delay=0
    )

    report = validator.validate()

    assert report is not None
    assert report.passed is False
    assert report.retry_count == 0
    assert mock_execute.call_count == 1


def test_validator_is_transient_failure():
    """Test transient failure detection."""
    project_root = Path(__file__).parent.parent.parent
    validator = ProductionReadinessValidator(
        project_root=project_root,
        strict=False,
        max_retries=0
    )

    # Transient failures
    checks_transient = [
        CheckResult("Check 1", False, "Connection timeout"),
    ]
    assert validator._is_transient_failure(checks_transient, "network error") is True

    # Permanent failures
    checks_permanent = [
        CheckResult("Check 1", False, "File not found"),
    ]
    assert validator._is_transient_failure(checks_permanent, "missing config") is False
