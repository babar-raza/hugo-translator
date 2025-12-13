"""
Tests for documentation validation tool

Tests claim detection, evidence checking, and language validation.
"""

import pytest
import sys
from pathlib import Path

# Add scripts directory to path
scripts_dir = Path(__file__).parent.parent.parent / 'scripts'
sys.path.insert(0, str(scripts_dir))

from validate_documentation import (
    ClaimDetector,
    EvidenceChecker,
    LanguageValidator,
    DocumentationValidator,
    ClaimType,
    Severity,
    Claim,
    ValidationIssue,
    ValidationReport,
)


class TestClaimDetector:
    """Test claim detection functionality"""

    def setup_method(self):
        self.detector = ClaimDetector()

    def test_detect_verified_claim_with_marker(self):
        """Test detection of verified claim with ✅ marker"""
        content = "✅ GPU detection works correctly"
        claims, markers = self.detector.detect_claims(content)

        assert len(claims) == 1
        assert claims[0].claim_type == ClaimType.VERIFIED
        assert markers['✅'] == 1

    def test_detect_reported_claim(self):
        """Test detection of reported claim"""
        content = "Agent reports 305 tests created"
        claims, _ = self.detector.detect_claims(content)

        assert len(claims) == 1
        assert claims[0].claim_type == ClaimType.REPORTED
        assert "Agent reports" in claims[0].text

    def test_detect_projected_claim(self):
        """Test detection of projected claim"""
        content = "Expected to handle 1000 requests per second"
        claims, _ = self.detector.detect_claims(content)

        assert len(claims) == 1
        assert claims[0].claim_type == ClaimType.PROJECTED

    def test_detect_unqualified_absolute_claim(self):
        """Test detection of unqualified absolute claim"""
        content = "All tests pass successfully"
        claims, _ = self.detector.detect_claims(content)

        assert len(claims) == 1
        assert claims[0].claim_type == ClaimType.UNQUALIFIED
        assert "all" in claims[0].text.lower()

    def test_detect_100_percent_claim(self):
        """Test detection of 100% claim"""
        content = "100% production ready"
        claims, _ = self.detector.detect_claims(content)

        assert len(claims) == 1
        assert claims[0].claim_type == ClaimType.UNQUALIFIED
        assert "100%" in claims[0].text

    def test_detect_numeric_claim(self):
        """Test detection of numeric claim without qualification"""
        content = "305 tests pass"
        claims, _ = self.detector.detect_claims(content)

        assert len(claims) == 1
        assert claims[0].claim_type == ClaimType.UNQUALIFIED

    def test_detect_production_ready_claim(self):
        """Test detection of production ready claim"""
        content = "System is production ready"
        claims, _ = self.detector.detect_claims(content)

        assert len(claims) == 1
        assert claims[0].claim_type == ClaimType.UNQUALIFIED

    def test_detect_multiple_claims(self):
        """Test detection of multiple claims in text"""
        content = """
        ✅ GPU detection works
        Agent reports 305 tests
        Expected to handle 1000 rps
        All features complete
        """
        claims, _ = self.detector.detect_claims(content)

        assert len(claims) == 4
        types = [c.claim_type for c in claims]
        assert ClaimType.VERIFIED in types
        assert ClaimType.REPORTED in types
        assert ClaimType.PROJECTED in types
        assert ClaimType.UNQUALIFIED in types

    def test_status_marker_counting(self):
        """Test counting of status markers"""
        content = """
        ✅ Verified claim
        📋 Reported claim
        🎯 Projected claim
        ⏳ Pending verification
        """
        _, markers = self.detector.detect_claims(content)

        assert markers['✅'] == 1
        assert markers['📋'] == 1
        assert markers['🎯'] == 1
        assert markers['⏳'] == 1

    def test_context_extraction(self):
        """Test that context is extracted for claims"""
        content = """
        Line before
        ✅ Verified claim
        Line after
        """
        claims, _ = self.detector.detect_claims(content)

        assert len(claims) == 1
        assert "Line before" in claims[0].context
        assert "Line after" in claims[0].context

    def test_qualified_language_patterns(self):
        """Test various qualified language patterns"""
        test_cases = [
            ("Tool output shows success", ClaimType.REPORTED),
            ("Logs indicate completion", ClaimType.REPORTED),
            ("According to agent logs", ClaimType.REPORTED),
            ("Designed for high throughput", ClaimType.PROJECTED),
            ("Should handle 1000 rps", ClaimType.PROJECTED),
            ("May improve performance", ClaimType.PROJECTED),
            ("Intended to support GPU", ClaimType.PROJECTED),
        ]

        for text, expected_type in test_cases:
            claims, _ = self.detector.detect_claims(text)
            assert len(claims) == 1, f"Failed for: {text}"
            assert claims[0].claim_type == expected_type, f"Failed for: {text}"


class TestEvidenceChecker:
    """Test evidence checking functionality"""

    def setup_method(self):
        self.checker = EvidenceChecker()

    def test_detect_evidence_link(self):
        """Test detection of evidence link"""
        content = "Evidence: tests/test_gpu.py passes"
        evidence = self.checker.check_evidence(content, [])

        assert len(evidence) == 1
        assert "tests/test_gpu.py" in evidence[0][1]

    def test_detect_verification_command(self):
        """Test detection of verification command"""
        content = "Verification: `pytest tests/ -v`"
        evidence = self.checker.check_evidence(content, [])

        assert len(evidence) == 1
        assert "pytest" in evidence[0][1]

    def test_detect_file_reference(self):
        """Test detection of file reference"""
        content = "See `src/gpu/detector.py` for implementation"
        evidence = self.checker.check_evidence(content, [])

        assert len(evidence) == 1
        assert "detector.py" in evidence[0][1]

    def test_detect_multiple_evidence_types(self):
        """Test detection of multiple evidence types"""
        content = """
        Evidence: test output
        See: `src/module.py`
        Verification: `pytest -v`
        Command: `python script.py`
        """
        evidence = self.checker.check_evidence(content, [])

        assert len(evidence) >= 4

    def test_validate_verified_claim_with_evidence(self):
        """Test validation passes when verified claim has nearby evidence"""
        claim = Claim(
            text="✅ GPU detection works",
            line_number=5,
            claim_type=ClaimType.VERIFIED,
            pattern="marker"
        )
        evidence = [(6, "Evidence: test output")]

        issues = self.checker.validate_evidence_for_claims([claim], evidence)

        assert len(issues) == 0

    def test_validate_verified_claim_without_evidence(self):
        """Test validation fails when verified claim lacks evidence"""
        claim = Claim(
            text="✅ GPU detection works",
            line_number=5,
            claim_type=ClaimType.VERIFIED,
            pattern="marker"
        )
        evidence = []

        issues = self.checker.validate_evidence_for_claims([claim], evidence)

        assert len(issues) == 1
        assert issues[0].severity == Severity.ERROR
        assert "lacks evidence" in issues[0].message

    def test_validate_evidence_proximity(self):
        """Test evidence must be within 5 lines of claim"""
        claim = Claim(
            text="✅ GPU detection works",
            line_number=5,
            claim_type=ClaimType.VERIFIED,
            pattern="marker"
        )

        # Evidence exactly 5 lines away should be OK
        evidence_ok = [(10, "Evidence: test")]
        issues_ok = self.checker.validate_evidence_for_claims([claim], evidence_ok)
        assert len(issues_ok) == 0

        # Evidence 6 lines away should fail
        evidence_far = [(11, "Evidence: test")]
        issues_far = self.checker.validate_evidence_for_claims([claim], evidence_far)
        assert len(issues_far) == 1


class TestLanguageValidator:
    """Test language validation functionality"""

    def setup_method(self):
        self.validator = LanguageValidator()

    def test_flag_unqualified_claim(self):
        """Test flagging of unqualified claim"""
        claim = Claim(
            text="All tests pass",
            line_number=10,
            claim_type=ClaimType.UNQUALIFIED,
            pattern="Absolute 'all X' claim"
        )

        issues = self.validator.validate_language([claim])

        assert len(issues) == 1
        assert issues[0].severity == Severity.ERROR
        assert "Unqualified absolute claim" in issues[0].message

    def test_suggestion_for_production_ready(self):
        """Test suggestion for production ready claim"""
        claim = Claim(
            text="System is production ready",
            line_number=10,
            claim_type=ClaimType.UNQUALIFIED,
            pattern="Production ready claim"
        )

        issues = self.validator.validate_language([claim])

        assert len(issues) == 1
        assert "verification pending" in issues[0].suggestion.lower()

    def test_suggestion_for_test_claim(self):
        """Test suggestion for test claim"""
        claim = Claim(
            text="All tests pass",
            line_number=10,
            claim_type=ClaimType.UNQUALIFIED,
            pattern="Test claim"
        )

        issues = self.validator.validate_language([claim])

        assert len(issues) == 1
        assert "pytest" in issues[0].suggestion.lower()

    def test_no_issues_for_qualified_claims(self):
        """Test no issues for properly qualified claims"""
        claims = [
            Claim("✅ Verified", 1, ClaimType.VERIFIED, "marker"),
            Claim("Agent reports", 2, ClaimType.REPORTED, "qualified"),
            Claim("Expected to", 3, ClaimType.PROJECTED, "qualified"),
        ]

        issues = self.validator.validate_language(claims)

        assert len(issues) == 0


class TestDocumentationValidator:
    """Test complete validation workflow"""

    def setup_method(self):
        self.validator = DocumentationValidator()

    def test_validate_good_documentation(self):
        """Test validation of well-formatted documentation"""
        content = """
        # Good Documentation

        ✅ GPU detection implemented and tested
        Evidence: tests/test_gpu.py passes
        Verification: `pytest tests/test_gpu.py -v`

        📋 Agent reports 305 tests created
        To verify: `find tests/ -name "test_*.py" | wc -l`

        🎯 Expected to handle 1000 requests per second
        Basis: Design target
        """

        # Create temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            report = self.validator.validate_file(temp_path)

            # Should have claims
            assert len(report.claims_found) > 0

            # Should have evidence
            assert len(report.evidence_links) > 0

            # Should have no errors (all claims properly qualified)
            assert report.error_count == 0

        finally:
            Path(temp_path).unlink()

    def test_validate_bad_documentation(self):
        """Test validation of poorly formatted documentation"""
        content = """
        # Bad Documentation

        All tests pass successfully.
        100% production ready.
        305 tests created.
        GPU detection works perfectly.
        """

        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            report = self.validator.validate_file(temp_path)

            # Should detect unqualified claims
            assert len(report.unqualified_claims) > 0

            # Should have errors
            assert report.error_count > 0

        finally:
            Path(temp_path).unlink()

    def test_report_to_dict(self):
        """Test report conversion to dictionary"""
        report = ValidationReport(file_path="test.md")
        report.claims_found = [
            Claim("Test", 1, ClaimType.VERIFIED, "pattern")
        ]
        report.issues = [
            ValidationIssue(Severity.ERROR, "Test error", 1)
        ]

        result = report.to_dict()

        assert result['file_path'] == "test.md"
        assert result['summary']['total_claims'] == 1
        assert result['summary']['errors'] == 1
        assert len(result['claims']) == 1
        assert len(result['issues']) == 1


class TestIntegration:
    """Integration tests for complete validation scenarios"""

    def test_comprehensive_validation(self):
        """Test comprehensive validation scenario"""
        content = """
        # Implementation Summary

        ## Verified Features

        ✅ GPU detection module implemented
        Evidence: tests/test_gpu_detector.py - 12 tests passing
        Verification: `pytest tests/test_gpu_detector.py -v`
        See: `src/gpu/detector.py` lines 45-120

        ## Reported Features

        📋 Agent reports translation pipeline complete
        Source: Implementation agent logs
        Files: `src/translation/pipeline.py` (420 lines)
        To verify: `pytest tests/test_translation.py`

        ## Projected Capabilities

        🎯 Expected to process 100 pages per minute
        Basis: Design target based on similar systems
        Confidence: Medium (not yet benchmarked)

        ## Issues (Bad Examples)

        All integration tests pass.
        100% production ready.
        System handles 1000 concurrent requests.
        """

        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            validator = DocumentationValidator()
            report = validator.validate_file(temp_path)

            # Should detect verified claims
            assert len(report.verified_claims) > 0

            # Should detect reported claims
            assert len(report.reported_claims) > 0

            # Should detect projected claims
            assert len(report.projected_claims) > 0

            # Should detect unqualified claims in "Issues" section
            assert len(report.unqualified_claims) > 0

            # Should have evidence links
            assert len(report.evidence_links) > 0

            # Should have errors for unqualified claims
            assert report.error_count > 0

        finally:
            Path(temp_path).unlink()

    def test_status_markers_comprehensive(self):
        """Test comprehensive status marker detection"""
        content = """
        ✅ Verified claim
        📋 Reported claim
        🎯 Projected claim
        ⏳ Pending verification
        ⚠️ Partial verification
        ❌ Not verified
        """

        detector = ClaimDetector()
        _, markers = detector.detect_claims(content)

        assert markers['✅'] == 1
        assert markers['📋'] == 1
        assert markers['🎯'] == 1
        assert markers['⏳'] == 1
        assert markers['⚠️'] == 1
        assert markers['❌'] == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
