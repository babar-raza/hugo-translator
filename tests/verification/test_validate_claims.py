"""
Tests for Evidence-Based Claim Validator

Tests cover:
- Claim loading from YAML
- Evidence collection from various sources
- Claim validation with different tolerance types
- Report generation
- Error handling
"""

import json

# Import the modules we're testing
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'scripts'))
from validate_claims import (
    Claim,
    ClaimLoader,
    ClaimValidationReport,
    ClaimValidator,
    EvidenceCollector,
    Reporter,
    ValidationResult,
)


class TestClaimLoader:
    """Test ClaimLoader class."""

    def test_load_claims_from_yaml(self, tmp_path):
        """Test loading claims from YAML file."""
        config_file = tmp_path / 'claims.yaml'
        config_file.write_text("""
version: "1.0"
claims:
  - id: "test_claim"
    description: "Test claim description"
    expected_value: 100
    tolerance: "greater_than_or_equal"
    evidence_source: "test_source"
    evidence_key: "test.key"
    category: "test"

evidence_sources:
  test_source:
    type: "json_file"
    path: "test.json"
""")

        claims, evidence_sources = ClaimLoader.load_claims(str(config_file))

        assert len(claims) == 1
        assert claims[0].id == "test_claim"
        assert claims[0].description == "Test claim description"
        assert claims[0].expected_value == 100
        assert claims[0].tolerance == "greater_than_or_equal"
        assert claims[0].evidence_source == "test_source"
        assert claims[0].evidence_key == "test.key"
        assert claims[0].category == "test"

        assert "test_source" in evidence_sources
        assert evidence_sources["test_source"]["type"] == "json_file"

    def test_load_claims_file_not_found(self):
        """Test loading claims from non-existent file."""
        with pytest.raises(FileNotFoundError):
            ClaimLoader.load_claims("nonexistent.yaml")

    def test_find_claim_by_description(self):
        """Test finding claim by description."""
        claims = [
            Claim(
                id="claim1",
                description="Test claim about files",
                expected_value=100,
                tolerance="equals",
                evidence_source="source1",
                evidence_key="key1",
                category="test"
            ),
            Claim(
                id="claim2",
                description="Test claim about tests",
                expected_value=50,
                tolerance="equals",
                evidence_source="source2",
                evidence_key="key2",
                category="test"
            )
        ]

        result = ClaimLoader.find_claim_by_description(claims, "files")
        assert result is not None
        assert result.id == "claim1"

        result = ClaimLoader.find_claim_by_description(claims, "tests")
        assert result is not None
        assert result.id == "claim2"

        result = ClaimLoader.find_claim_by_description(claims, "nonexistent")
        assert result is None


class TestEvidenceCollector:
    """Test EvidenceCollector class."""

    def test_collect_from_json_file(self, tmp_path):
        """Test collecting evidence from JSON file."""
        # Create test JSON file
        json_file = tmp_path / 'evidence.json'
        json_file.write_text(json.dumps({
            'total_files': 100,
            'total_tests': 50
        }))

        collector = EvidenceCollector(tmp_path)
        evidence = collector._collect_from_json_file({
            'path': 'evidence.json'
        })

        assert evidence is not None
        assert evidence['total_files'] == 100
        assert evidence['total_tests'] == 50

    def test_collect_from_json_file_not_found(self, tmp_path):
        """Test collecting from non-existent JSON file."""
        collector = EvidenceCollector(tmp_path)
        evidence = collector._collect_from_json_file({
            'path': 'nonexistent.json'
        })

        assert evidence is None

    @patch('subprocess.run')
    def test_collect_from_pytest(self, mock_run, tmp_path):
        """Test collecting evidence from pytest."""
        # Mock pytest output
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """
<Module test_file.py>
  <Function test_one>
  <Function test_two>
  <Function test_three>
collected 3 tests
"""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        collector = EvidenceCollector(tmp_path)
        evidence = collector._collect_from_pytest({
            'command': 'pytest --collect-only -q'
        })

        assert evidence is not None
        assert evidence['total_tests'] >= 3

    @patch('subprocess.run')
    def test_collect_from_pytest_timeout(self, mock_run, tmp_path):
        """Test pytest collection timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired('pytest', 30)

        collector = EvidenceCollector(tmp_path)
        evidence = collector._collect_from_pytest({
            'command': 'pytest --collect-only -q'
        })

        assert evidence is None


class TestClaimValidator:
    """Test ClaimValidator class."""

    def test_extract_value_simple(self):
        """Test extracting value with simple key path."""
        data = {
            'total_files': 100,
            'stats': {
                'total_lines': 1000
            }
        }

        assert ClaimValidator.extract_value(data, 'total_files') == 100
        assert ClaimValidator.extract_value(data, 'stats.total_lines') == 1000

    def test_extract_value_array_index(self):
        """Test extracting value with array indexing."""
        data = {
            'files': [
                {'name': 'file1.py'},
                {'name': 'file2.py'}
            ]
        }

        assert ClaimValidator.extract_value(data, 'files[0].name') == 'file1.py'
        assert ClaimValidator.extract_value(data, 'files[1].name') == 'file2.py'

    def test_extract_value_length(self):
        """Test extracting length of array."""
        data = {
            'files': [1, 2, 3, 4, 5]
        }

        assert ClaimValidator.extract_value(data, 'files.length') == 5

    def test_extract_value_division(self):
        """Test extracting value with division."""
        data = {
            'code_lines': 1000,
            'comment_lines': 200
        }

        result = ClaimValidator.extract_value(data, 'code_lines / comment_lines')
        assert result == 5.0

    def test_extract_value_not_found(self):
        """Test extracting non-existent value."""
        data = {'key': 'value'}

        assert ClaimValidator.extract_value(data, 'nonexistent') is None
        assert ClaimValidator.extract_value(data, 'key.nested') is None

    def test_validate_claim_equals_pass(self):
        """Test claim validation with equals tolerance - pass."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="equals",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 100}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'
        assert result.actual_value == 100

    def test_validate_claim_equals_fail(self):
        """Test claim validation with equals tolerance - fail."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="equals",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 50}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'FAIL'
        assert result.actual_value == 50

    def test_validate_claim_greater_than_pass(self):
        """Test claim validation with greater_than tolerance - pass."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="greater_than",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 150}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'
        assert result.actual_value == 150

    def test_validate_claim_greater_than_fail(self):
        """Test claim validation with greater_than tolerance - fail."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="greater_than",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 50}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'FAIL'
        assert result.actual_value == 50

    def test_validate_claim_greater_than_or_equal_pass(self):
        """Test claim validation with greater_than_or_equal tolerance - pass."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="greater_than_or_equal",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 100}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'

        evidence = {'value': 150}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'

    def test_validate_claim_less_than_pass(self):
        """Test claim validation with less_than tolerance - pass."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="less_than",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 50}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'

    def test_validate_claim_less_than_or_equal_pass(self):
        """Test claim validation with less_than_or_equal tolerance - pass."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="less_than_or_equal",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 100}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'

        evidence = {'value': 50}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'

    def test_validate_claim_range_pass(self):
        """Test claim validation with range tolerance - pass."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=[50, 150],
            tolerance="range",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 100}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'

    def test_validate_claim_range_fail(self):
        """Test claim validation with range tolerance - fail."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=[50, 150],
            tolerance="range",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 200}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'FAIL'

    def test_validate_claim_missing_evidence(self):
        """Test claim validation with missing evidence."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="equals",
            evidence_source="test",
            evidence_key="nonexistent",
            category="test"
        )

        evidence = {'value': 100}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'UNKNOWN'
        assert result.error is not None

    def test_validate_claim_boolean(self):
        """Test claim validation with boolean values."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=True,
            tolerance="equals",
            evidence_source="test",
            evidence_key="enabled",
            category="test"
        )

        evidence = {'enabled': True}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'


class TestReporter:
    """Test Reporter class."""

    def test_save_report(self, tmp_path):
        """Test saving report to JSON."""
        report = ClaimValidationReport(
            validation_time='2024-01-01T12:00:00',
            total_claims=5,
            passed_claims=4,
            failed_claims=1,
            unknown_claims=0,
            results=[],
            errors=[],
            warnings=[]
        )

        output_file = tmp_path / 'report.json'
        Reporter.save_report(report, str(output_file))

        assert output_file.exists()

        with open(output_file) as f:
            data = json.load(f)

        assert data['total_claims'] == 5
        assert data['passed_claims'] == 4
        assert data['failed_claims'] == 1

    def test_print_summary(self, capsys):
        """Test printing summary report."""
        report = ClaimValidationReport(
            validation_time='2024-01-01T12:00:00',
            total_claims=3,
            passed_claims=2,
            failed_claims=1,
            unknown_claims=0,
            results=[
                ValidationResult(
                    claim_id='claim1',
                    claim_description='Test claim 1',
                    expected_value=100,
                    actual_value=100,
                    status='PASS',
                    tolerance='equals',
                    evidence_source='test'
                ),
                ValidationResult(
                    claim_id='claim2',
                    claim_description='Test claim 2',
                    expected_value=50,
                    actual_value=30,
                    status='FAIL',
                    tolerance='greater_than',
                    evidence_source='test',
                    details='Expected > 50, got 30'
                ),
                ValidationResult(
                    claim_id='claim3',
                    claim_description='Test claim 3',
                    expected_value=200,
                    actual_value=200,
                    status='PASS',
                    tolerance='equals',
                    evidence_source='test'
                )
            ],
            errors=['Test error'],
            warnings=['Test warning']
        )

        Reporter.print_summary(report)

        captured = capsys.readouterr()
        assert 'Claim Validation Report' in captured.out
        assert 'Total claims: 3' in captured.out
        assert 'Passed: 2' in captured.out
        assert 'Failed: 1' in captured.out
        assert 'Test claim 1' in captured.out
        assert 'Test claim 2' in captured.out
        assert 'Test error' in captured.out
        assert 'Test warning' in captured.out


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_extract_value_with_none_data(self):
        """Test extracting value from None data."""
        assert ClaimValidator.extract_value(None, 'key') is None

    def test_extract_value_with_empty_dict(self):
        """Test extracting value from empty dict."""
        assert ClaimValidator.extract_value({}, 'key') is None

    def test_validate_claim_with_string_values(self):
        """Test claim validation with string values."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value="expected",
            tolerance="equals",
            evidence_source="test",
            evidence_key="value",
            category="test"
        )

        evidence = {'value': 'expected'}
        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'

    def test_validate_claim_with_nested_evidence(self):
        """Test claim validation with deeply nested evidence."""
        claim = Claim(
            id="test",
            description="Test",
            expected_value=100,
            tolerance="equals",
            evidence_source="test",
            evidence_key="level1.level2.level3.value",
            category="test"
        )

        evidence = {
            'level1': {
                'level2': {
                    'level3': {
                        'value': 100
                    }
                }
            }
        }

        result = ClaimValidator.validate_claim(claim, evidence)

        assert result.status == 'PASS'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
