#!/usr/bin/env python3
"""
Tests for Deployment Safety Checker

Tests the deployment safety automation and checklist validation.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import after path setup
from scripts.check_deployment_safety import (
    ApprovalReporter,
    AutomatedChecker,
    CheckItem,
    ChecklistLoader,
    ChecklistReport,
    ChecklistValidator,
)

# ============================================================================
# CheckItem Tests
# ============================================================================


def test_check_item_creation():
    """Test CheckItem can be created."""
    item = CheckItem(category="Test", name="Test Check", automated=True, required=True)

    assert item.category == "Test"
    assert item.name == "Test Check"
    assert item.automated is True
    assert item.required is True
    assert item.status == "pending"


def test_check_item_to_dict():
    """Test CheckItem serialization."""
    item = CheckItem(
        category="Test",
        name="Test Check",
        automated=True,
        required=True,
        status="passed",
        evidence="Test passed",
    )

    item_dict = item.to_dict()

    assert item_dict["category"] == "Test"
    assert item_dict["name"] == "Test Check"
    assert item_dict["status"] == "passed"
    assert item_dict["evidence"] == "Test passed"


# ============================================================================
# ChecklistLoader Tests
# ============================================================================


def test_checklist_loader_initialization():
    """Test ChecklistLoader can be initialized."""
    loader = ChecklistLoader()

    assert loader is not None
    assert hasattr(loader, "checklist_items")


def test_checklist_loader_defines_items():
    """Test ChecklistLoader defines checklist items."""
    loader = ChecklistLoader()
    items = loader.get_checklist()

    assert len(items) > 0
    assert all(isinstance(item, CheckItem) for item in items)


def test_checklist_includes_categories():
    """Test checklist includes expected categories."""
    loader = ChecklistLoader()
    items = loader.get_checklist()

    categories = set(item.category for item in items)

    expected_categories = {"Code Quality", "Security", "Performance", "Infrastructure", "Rollback"}

    for expected in expected_categories:
        assert expected in categories, f"Missing category: {expected}"


def test_checklist_has_automated_and_manual():
    """Test checklist has both automated and manual items."""
    loader = ChecklistLoader()
    items = loader.get_checklist()

    automated = [i for i in items if i.automated]
    manual = [i for i in items if not i.automated]

    assert len(automated) > 0, "Should have automated checks"
    assert len(manual) > 0, "Should have manual checks"


# ============================================================================
# AutomatedChecker Tests
# ============================================================================


def test_automated_checker_initialization():
    """Test AutomatedChecker can be initialized."""
    project_root = Path(__file__).parent.parent.parent
    checker = AutomatedChecker(project_root)

    assert checker is not None
    assert checker.project_root == project_root


@patch("subprocess.run")
def test_automated_checker_tests_pass(mock_run):
    """Test checking if all tests pass."""
    # Mock successful test run
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "All tests passed"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    project_root = Path(__file__).parent.parent.parent
    checker = AutomatedChecker(project_root)

    passed, evidence, error = checker.check_all_tests_pass()

    assert passed is True
    assert "passed" in evidence.lower()


@patch("subprocess.run")
def test_automated_checker_tests_fail(mock_run):
    """Test checking when tests fail."""
    # Mock failed test run
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = "1 failed, 5 passed"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    project_root = Path(__file__).parent.parent.parent
    checker = AutomatedChecker(project_root)

    passed, evidence, error = checker.check_all_tests_pass()

    assert passed is False
    assert "failed" in evidence.lower()


@patch("subprocess.run")
def test_automated_checker_smoke_tests(mock_run):
    """Test smoke test check."""
    # Mock successful smoke tests
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Smoke tests passed"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        scripts_dir = project_root / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run_smoke_tests.py").write_text('print("test")')

        checker = AutomatedChecker(project_root)

        passed, evidence, error = checker.check_smoke_tests()

        assert passed is True


def test_automated_checker_static_analysis():
    """Test static analysis check."""
    project_root = Path(__file__).parent.parent.parent
    checker = AutomatedChecker(project_root)

    passed, evidence, error = checker.check_static_analysis()

    # Should pass if imports work (we're in a real project)
    assert passed is True


def test_automated_checker_dependencies():
    """Test dependency check."""
    project_root = Path(__file__).parent.parent.parent
    checker = AutomatedChecker(project_root)

    passed, evidence, error = checker.check_dependencies_secure()

    # Should pass if requirements file exists
    assert passed is True


def test_automated_checker_resources():
    """Test resource requirements check."""
    project_root = Path(__file__).parent.parent.parent
    checker = AutomatedChecker(project_root)

    passed, evidence, error = checker.check_resource_requirements()

    # Should pass or skip (depending on psutil availability)
    assert passed is True or "skip" in evidence.lower()


@patch("subprocess.run")
def test_automated_checker_production_readiness(mock_run):
    """Test production readiness check."""
    # Mock successful readiness check
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "All checks passed"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        scripts_dir = project_root / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "production_readiness_check.py").write_text('print("test")')

        checker = AutomatedChecker(project_root)

        passed, evidence, error = checker.check_production_readiness()

        assert passed is True


@patch("subprocess.run")
def test_automated_checker_rollback_dry_run(mock_run):
    """Test rollback dry-run check."""
    # Mock successful dry-run
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Dry-run successful"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        scripts_dir = project_root / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "rollback.py").write_text('print("test")')

        checker = AutomatedChecker(project_root)

        passed, evidence, error = checker.check_rollback_tested()

        assert passed is True


def test_automated_checker_run_all_checks():
    """Test running all automated checks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        checker = AutomatedChecker(project_root)

        items = [
            CheckItem("Test", "Static analysis clean", automated=True, required=True),
            CheckItem("Test", "Manual review", automated=False, required=True),
        ]

        updated_items = checker.run_all_checks(items)

        # Static analysis should have been run
        static_item = [i for i in updated_items if i.name == "Static analysis clean"][0]
        assert static_item.status in ["passed", "failed", "skipped"]

        # Manual item should remain manual
        manual_item = [i for i in updated_items if i.name == "Manual review"][0]
        assert manual_item.status == "manual"


# ============================================================================
# ChecklistValidator Tests
# ============================================================================


def test_checklist_validator_initialization():
    """Test ChecklistValidator can be initialized."""
    validator = ChecklistValidator()

    assert validator is not None


def test_checklist_validator_all_passed():
    """Test validation when all checks pass."""
    validator = ChecklistValidator()

    items = [
        CheckItem("Test", "Check 1", automated=True, required=True, status="passed"),
        CheckItem("Test", "Check 2", automated=True, required=True, status="passed"),
    ]

    ready, warnings = validator.validate(items, strict=False)

    assert ready is True
    assert len(warnings) == 0


def test_checklist_validator_with_failures():
    """Test validation when checks fail."""
    validator = ChecklistValidator()

    items = [
        CheckItem("Test", "Check 1", automated=True, required=True, status="passed"),
        CheckItem("Test", "Check 2", automated=True, required=True, status="failed"),
    ]

    ready, warnings = validator.validate(items, strict=False)

    assert ready is False
    assert len(warnings) > 0
    assert any("failed" in w.lower() for w in warnings)


def test_checklist_validator_with_manual():
    """Test validation with manual checks."""
    validator = ChecklistValidator()

    items = [
        CheckItem("Test", "Check 1", automated=True, required=True, status="passed"),
        CheckItem("Test", "Check 2", automated=False, required=True, status="manual"),
    ]

    # Non-strict should allow manual
    ready, warnings = validator.validate(items, strict=False)
    assert ready is True

    # Strict should require manual completion
    ready, warnings = validator.validate(items, strict=True)
    assert ready is False
    assert any("manual" in w.lower() for w in warnings)


def test_checklist_validator_pending_automated():
    """Test validation with pending automated checks."""
    validator = ChecklistValidator()

    items = [
        CheckItem("Test", "Check 1", automated=True, required=True, status="pending"),
        CheckItem("Test", "Check 2", automated=True, required=True, status="passed"),
    ]

    ready, warnings = validator.validate(items, strict=False)

    assert ready is False
    assert any("pending" in w.lower() or "not run" in w.lower() for w in warnings)


# ============================================================================
# ApprovalReporter Tests
# ============================================================================


def test_approval_reporter_initialization():
    """Test ApprovalReporter can be initialized."""
    reporter = ApprovalReporter()

    assert reporter is not None


def test_approval_reporter_generate_json():
    """Test generating JSON approval report."""
    reporter = ApprovalReporter()

    items = [
        CheckItem("Test", "Check 1", automated=True, required=True, status="passed"),
    ]

    report = ChecklistReport(
        timestamp="2024-01-01T12:00:00",
        total_items=1,
        automated_items=1,
        manual_items=0,
        passed=1,
        failed=0,
        pending=0,
        manual_review=0,
        ready_for_deployment=True,
        items=items,
    )

    report_json = reporter.generate_report(report)

    # Should be valid JSON
    report_data = json.loads(report_json)
    assert report_data["ready_for_deployment"] is True
    assert report_data["total_items"] == 1


def test_approval_reporter_save_to_file():
    """Test saving approval report to file."""
    reporter = ApprovalReporter()

    items = [
        CheckItem("Test", "Check 1", automated=True, required=True, status="passed"),
    ]

    report = ChecklistReport(
        timestamp="2024-01-01T12:00:00",
        total_items=1,
        automated_items=1,
        manual_items=0,
        passed=1,
        failed=0,
        pending=0,
        manual_review=0,
        ready_for_deployment=True,
        items=items,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.json"
        reporter.generate_report(report, report_path)

        assert report_path.exists()

        # Verify content
        report_data = json.loads(report_path.read_text())
        assert report_data["ready_for_deployment"] is True


def test_approval_reporter_markdown():
    """Test generating markdown report."""
    reporter = ApprovalReporter()

    items = [
        CheckItem(
            "Code Quality",
            "Check 1",
            automated=True,
            required=True,
            status="passed",
            evidence="Test passed",
        ),
        CheckItem(
            "Security",
            "Check 2",
            automated=True,
            required=True,
            status="failed",
            evidence="Test failed",
            error="Error details",
        ),
    ]

    report = ChecklistReport(
        timestamp="2024-01-01T12:00:00",
        total_items=2,
        automated_items=2,
        manual_items=0,
        passed=1,
        failed=1,
        pending=0,
        manual_review=0,
        ready_for_deployment=False,
        items=items,
        warnings=["1 check failed"],
    )

    md_report = reporter.generate_markdown_report(report)

    # Should contain expected sections
    assert "# Deployment Safety Approval Report" in md_report
    assert "Code Quality" in md_report
    assert "Security" in md_report
    assert "Check 1" in md_report
    assert "Check 2" in md_report
    assert "Warnings" in md_report


def test_checklist_report_to_dict():
    """Test ChecklistReport serialization."""
    items = [
        CheckItem("Test", "Check 1", automated=True, required=True, status="passed"),
    ]

    report = ChecklistReport(
        timestamp="2024-01-01T12:00:00",
        total_items=1,
        automated_items=1,
        manual_items=0,
        passed=1,
        failed=0,
        pending=0,
        manual_review=0,
        ready_for_deployment=True,
        items=items,
    )

    report_dict = report.to_dict()

    assert report_dict["timestamp"] == "2024-01-01T12:00:00"
    assert report_dict["ready_for_deployment"] is True
    assert len(report_dict["items"]) == 1
