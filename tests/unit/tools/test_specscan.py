"""
Unit tests for specscan tool.

Tests the spec verification functionality including:
- YAML parsing
- Evidence verification
- Runtime units validation
- Feature specs validation
- Report generation
- Exit codes
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from scripts.specscan import SpecScanner, SpecScanResult, ScanSummary


class TestSpecScanner:
    """Test suite for SpecScanner class."""

    def test_init(self, tmp_path):
        """Test scanner initialization."""
        specs_dir = tmp_path / "specs"
        report_dir = tmp_path / "reports"
        project_root = tmp_path

        scanner = SpecScanner(specs_dir, report_dir, project_root)

        assert scanner.specs_dir == specs_dir
        assert scanner.report_dir == report_dir
        assert scanner.project_root == project_root
        assert scanner.summary.total_specs == 0
        assert scanner.summary.passed == 0
        assert scanner.summary.failed == 0

    def test_load_evidence_registry_success(self, tmp_path):
        """Test loading valid evidence registry."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        # Create evidence registry
        evidence_data = {
            'evidence': [
                {
                    'evidence_id': 'evidence-001',
                    'type': 'file',
                    'pointer': 'src/cli.py:100',
                    'notes': 'CLI entry point'
                }
            ]
        }

        evidence_file = specs_dir / "_evidence_index.yml"
        with open(evidence_file, 'w') as f:
            yaml.dump(evidence_data, f)

        scanner = SpecScanner(specs_dir, tmp_path / "reports", tmp_path)
        scanner._load_evidence_registry()

        assert len(scanner.evidence_registry) == 1
        assert 'evidence-001' in scanner.evidence_registry
        assert scanner.evidence_registry['evidence-001']['type'] == 'file'

    def test_load_evidence_registry_missing(self, tmp_path):
        """Test handling missing evidence registry."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        scanner = SpecScanner(specs_dir, tmp_path / "reports", tmp_path)
        scanner._load_evidence_registry()

        # Should create a failure result
        assert scanner.summary.failed == 1
        assert len(scanner.summary.results) == 1
        assert scanner.summary.results[0].status == "FAIL"

    def test_validate_start_method_docker(self):
        """Test validation of docker-compose commands."""
        scanner = SpecScanner(Path("specs"), Path("reports"), Path("."))

        # Valid docker commands
        assert scanner._validate_start_method("docker-compose up orchestrator") is True
        assert scanner._validate_start_method("docker-compose up worker-cpu") is True

        # Invalid (but we accept anything starting with docker-compose up)
        assert scanner._validate_start_method("docker-compose") is True  # lenient

    def test_validate_start_method_python(self):
        """Test validation of python module commands."""
        scanner = SpecScanner(Path("specs"), Path("reports"), Path("."))

        # Valid python commands
        assert scanner._validate_start_method("python -m src.cli") is True
        assert scanner._validate_start_method("python -m src.workers.translation_worker") is True

        # Invalid module path
        assert scanner._validate_start_method("python -m 123invalid") is False
        assert scanner._validate_start_method("python -m .invalid") is False

    def test_validate_start_method_cli(self):
        """Test validation of CLI commands."""
        scanner = SpecScanner(Path("specs"), Path("reports"), Path("."))

        # Valid CLI commands
        assert scanner._validate_start_method("translate-hugo --site test") is True

    def test_verify_runtime_unit_valid(self, tmp_path):
        """Test verification of valid runtime unit."""
        unit = {
            'id': 'test-unit',
            'name': 'Test Unit',
            'description': 'A test unit',
            'start_method': 'docker-compose up test',
            'ports': ['8000'],
            'deps': [],
            'config_knobs': [],
            'evidence_ids': []
        }

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_runtime_unit(unit, tmp_path / "test.yml", 0)

        assert result.status == "PASS"
        assert result.spec_id == "test-unit"
        assert "All checks passed" in result.messages

    def test_verify_runtime_unit_missing_fields(self, tmp_path):
        """Test verification of runtime unit with missing fields."""
        unit = {
            'id': 'test-unit',
            # Missing 'name', 'description', 'start_method'
        }

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_runtime_unit(unit, tmp_path / "test.yml", 0)

        assert result.status == "FAIL"
        assert any("Missing required field: name" in m for m in result.messages)
        assert any("Missing required field: description" in m for m in result.messages)
        assert any("Missing required field: start_method" in m for m in result.messages)

    def test_verify_runtime_unit_invalid_start_method(self, tmp_path):
        """Test verification of runtime unit with invalid start method."""
        unit = {
            'id': 'test-unit',
            'name': 'Test Unit',
            'description': 'A test unit',
            'start_method': 'python -m 123invalid',  # Invalid module name
        }

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_runtime_unit(unit, tmp_path / "test.yml", 0)

        assert result.status == "FAIL"
        assert any("Invalid start_method syntax" in m for m in result.messages)

    def test_verify_runtime_unit_missing_evidence(self, tmp_path):
        """Test verification of runtime unit with missing evidence."""
        unit = {
            'id': 'test-unit',
            'name': 'Test Unit',
            'description': 'A test unit',
            'start_method': 'docker-compose up test',
            'evidence_ids': ['evidence-999']  # Non-existent evidence
        }

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        # Don't load evidence registry (empty)
        result = scanner._verify_runtime_unit(unit, tmp_path / "test.yml", 0)

        assert result.status == "FAIL"
        assert any("Evidence ID not found" in m for m in result.messages)

    def test_verify_runtime_unit_invalid_port(self, tmp_path):
        """Test verification of runtime unit with invalid port."""
        unit = {
            'id': 'test-unit',
            'name': 'Test Unit',
            'description': 'A test unit',
            'start_method': 'docker-compose up test',
            'ports': ['99999']  # Out of range
        }

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_runtime_unit(unit, tmp_path / "test.yml", 0)

        assert result.status == "WARNING"
        assert any("Port out of valid range" in m for m in result.messages)

    def test_verify_feature_valid(self, tmp_path):
        """Test verification of valid feature spec."""
        features_dir = tmp_path / "specs" / "features"
        features_dir.mkdir(parents=True)

        feature_file = features_dir / "test-001-feature.md"
        feature_content = """# TEST-001: Test Feature

**Feature:** Test feature
**Status:** EVIDENCE_ONLY

## Summary
Test feature description.

## Evidence
Evidence goes here.

## Related Specs
- [Other Spec](other.md)
"""
        feature_file.write_text(feature_content)

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_feature(feature_file)

        assert result.status == "PASS"
        assert result.spec_id == "test-001-feature"

    def test_verify_feature_empty_file(self, tmp_path):
        """Test verification of empty feature file."""
        features_dir = tmp_path / "specs" / "features"
        features_dir.mkdir(parents=True)

        feature_file = features_dir / "test-001-feature.md"
        feature_file.write_text("")

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_feature(feature_file)

        assert result.status == "FAIL"
        assert any("File is empty" in m for m in result.messages)

    def test_verify_feature_missing_sections(self, tmp_path):
        """Test verification of feature with missing sections."""
        features_dir = tmp_path / "specs" / "features"
        features_dir.mkdir(parents=True)

        feature_file = features_dir / "test-001-feature.md"
        feature_content = """# Test Feature

Some content but no status or evidence sections.
"""
        feature_file.write_text(feature_content)

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_feature(feature_file)

        assert result.status == "WARNING"
        assert any("No status marker found" in m for m in result.messages)
        assert any("No Evidence section found" in m for m in result.messages)

    def test_verify_evidence_valid(self, tmp_path):
        """Test verification of valid evidence entry."""
        # Create a test file
        test_file = tmp_path / "src" / "cli.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# Test file\nprint('hello')\n")

        evidence_data = {
            'evidence_id': 'evidence-001',
            'type': 'file',
            'pointer': 'src/cli.py:2',
            'notes': 'Test evidence'
        }

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_evidence('evidence-001', evidence_data)

        assert result.status == "PASS"
        assert "Pointer file exists" in result.messages

    def test_verify_evidence_missing_file(self, tmp_path):
        """Test verification of evidence with missing file."""
        evidence_data = {
            'evidence_id': 'evidence-001',
            'type': 'file',
            'pointer': 'src/nonexistent.py:100',
            'notes': 'Test evidence'
        }

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_evidence('evidence-001', evidence_data)

        assert result.status == "FAIL"
        assert any("Pointer file not found" in m for m in result.messages)

    def test_verify_evidence_missing_pointer(self, tmp_path):
        """Test verification of evidence with missing pointer field."""
        evidence_data = {
            'evidence_id': 'evidence-001',
            'type': 'file',
            # Missing 'pointer'
            'notes': 'Test evidence'
        }

        scanner = SpecScanner(tmp_path / "specs", tmp_path / "reports", tmp_path)
        result = scanner._verify_evidence('evidence-001', evidence_data)

        assert result.status == "FAIL"
        assert any("Missing 'pointer' field" in m for m in result.messages)

    def test_generate_report(self, tmp_path):
        """Test report generation."""
        specs_dir = tmp_path / "specs"
        report_dir = tmp_path / "reports"
        specs_dir.mkdir()

        scanner = SpecScanner(specs_dir, report_dir, tmp_path)

        # Add some results
        scanner.summary.total_specs = 3
        scanner.summary.passed = 2
        scanner.summary.failed = 1
        scanner.summary.results = [
            SpecScanResult("runtime_unit", "unit-1", "PASS", ["All good"], "file:1"),
            SpecScanResult("runtime_unit", "unit-2", "PASS", ["All good"], "file:2"),
            SpecScanResult("feature", "feature-1", "FAIL", ["Missing field"], "file:3"),
        ]

        report_path = scanner._generate_report()

        assert report_path.exists()
        assert report_path.parent == report_dir
        assert "spec_compliance_" in report_path.name

        # Read and verify report content
        content = report_path.read_text()
        assert "# Spec Compliance Report" in content
        assert "Total Specs Scanned: 3" in content
        assert "Passed: 2/3" in content
        assert "Failed: 1/3" in content
        assert "unit-1" in content
        assert "feature-1" in content

    def test_scan_all_exit_code_pass(self, tmp_path):
        """Test exit code 0 when all checks pass."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        # Create minimal valid evidence registry
        evidence_data = {'evidence': []}
        evidence_file = specs_dir / "_evidence_index.yml"
        with open(evidence_file, 'w') as f:
            yaml.dump(evidence_data, f)

        scanner = SpecScanner(specs_dir, tmp_path / "reports", tmp_path)
        exit_code = scanner.scan_all()

        assert exit_code == 0

    def test_scan_all_exit_code_fail(self, tmp_path):
        """Test exit code 1 when checks fail."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        # Don't create evidence registry (will cause failure)

        scanner = SpecScanner(specs_dir, tmp_path / "reports", tmp_path)
        exit_code = scanner.scan_all()

        assert exit_code == 1
        assert scanner.summary.failed > 0


class TestSpecScanResult:
    """Test SpecScanResult dataclass."""

    def test_creation(self):
        """Test creating a result."""
        result = SpecScanResult(
            spec_type="runtime_unit",
            spec_id="test-unit",
            status="PASS",
            messages=["All good"],
            location="test.yml:5"
        )

        assert result.spec_type == "runtime_unit"
        assert result.spec_id == "test-unit"
        assert result.status == "PASS"
        assert len(result.messages) == 1
        assert result.location == "test.yml:5"

    def test_default_messages(self):
        """Test default empty messages list."""
        result = SpecScanResult(
            spec_type="feature",
            spec_id="test-feature",
            status="WARNING"
        )

        assert result.messages == []
        assert result.location == ""


class TestScanSummary:
    """Test ScanSummary dataclass."""

    def test_initialization(self):
        """Test summary initialization."""
        summary = ScanSummary()

        assert summary.total_specs == 0
        assert summary.passed == 0
        assert summary.failed == 0
        assert summary.warnings == 0
        assert summary.results == []

    def test_adding_results(self):
        """Test adding results to summary."""
        summary = ScanSummary()

        result1 = SpecScanResult("runtime_unit", "unit-1", "PASS")
        result2 = SpecScanResult("feature", "feature-1", "FAIL")

        summary.results.append(result1)
        summary.results.append(result2)
        summary.total_specs = 2
        summary.passed = 1
        summary.failed = 1

        assert len(summary.results) == 2
        assert summary.total_specs == 2
        assert summary.passed == 1
        assert summary.failed == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
