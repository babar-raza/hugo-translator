"""
Unit tests for enhanced failure classification logic.

Tests the multi-failure detection capability that addresses the Phase 6 issue
where 70% of failures were classified as FAIL_OTHER due to incomplete classification.
"""
import pytest
from src.translation_engine.quality.failure_classifier import (
    FailureInfo,
    classify_all_failures,
    classify_failure_legacy,
    SEVERITY_RANK,
)


class TestSingleFailureDetection:
    """Test detection of single failure types."""

    def test_untranslated_prose_only(self):
        """Test detection of untranslated prose failure."""
        verify_data = {
            "passed": False,
            "checks": {
                "untranslated": {
                    "ratio": 0.45,
                    "threshold": 0.35,
                    "passed": False,
                },
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        assert category == "FAIL_UNTRANSLATED_PROSE"
        assert "0.45" in reason or "45" in reason
        assert len(failures) == 1
        assert failures[0].category == "FAIL_UNTRANSLATED_PROSE"
        assert failures[0].details["ratio"] == 0.45

    def test_markdown_fidelity_only(self):
        """Test detection of markdown fidelity failure."""
        verify_data = {
            "passed": False,
            "checks": {
                "markdown_fidelity": {
                    "passed": False,
                    "errors": ["Bold span count mismatch: source=10, target=12"],
                    "source_counts": {"bold": 10},
                    "target_counts": {"bold": 12},
                },
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        assert category == "FAIL_MARKDOWN_FIDELITY"
        assert "Bold span count" in reason
        assert len(failures) == 1

    def test_code_preservation_only(self):
        """Test detection of code preservation failure."""
        verify_data = {
            "passed": False,
            "checks": {
                "code_preservation": {
                    "passed": False,
                },
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        assert category == "FAIL_CODE_SPAN_CHANGED"
        assert "code" in reason.lower()
        assert len(failures) == 1

    def test_token_leakage_only(self):
        """Test detection of token leakage failure."""
        verify_data = {
            "passed": False,
            "checks": {
                "token_leakage": {
                    "passed": False,
                    "leaks": ["{{%", "{{<"],
                },
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        assert category == "FAIL_CODE_SPAN_CHANGED"
        assert "Token leakage" in reason
        assert "2 instances" in reason
        assert len(failures) == 1

    def test_line_count_only(self):
        """Test detection of line count failure."""
        verify_data = {
            "passed": False,
            "checks": {
                "line_count": {
                    "source": 100,
                    "target": 80,
                    "threshold": 95.0,
                    "passed": False,
                },
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        assert category == "FAIL_LINE_COUNT"
        assert "Line count too low" in reason
        assert "80" in reason
        assert len(failures) == 1


class TestMultipleFailureDetection:
    """Test detection of multiple concurrent failures."""

    def test_markdown_and_line_count(self):
        """Test detection of both markdown fidelity and line count failures."""
        verify_data = {
            "passed": False,
            "checks": {
                "markdown_fidelity": {
                    "passed": False,
                    "errors": ["Bold span count mismatch: source=13, target=14"],
                    "source_counts": {"bold": 13, "links": 4},
                    "target_counts": {"bold": 14, "links": 5},
                },
                "line_count": {
                    "source": 48,
                    "target": 30,
                    "threshold": 45.6,
                    "passed": False,
                },
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        # Primary should be markdown fidelity (higher severity)
        assert category == "FAIL_MARKDOWN_FIDELITY"

        # Should detect both failures
        assert len(failures) == 2

        categories = [f.category for f in failures]
        assert "FAIL_MARKDOWN_FIDELITY" in categories
        assert "FAIL_LINE_COUNT" in categories

    def test_untranslated_overrides_all(self):
        """Test that untranslated prose is highest priority."""
        verify_data = {
            "passed": False,
            "checks": {
                "untranslated": {
                    "ratio": 0.50,
                    "threshold": 0.35,
                    "passed": False,
                },
                "markdown_fidelity": {
                    "passed": False,
                    "errors": ["Bold mismatch"],
                },
                "line_count": {
                    "source": 100,
                    "target": 80,
                    "threshold": 95.0,
                    "passed": False,
                },
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        # Primary should be untranslated (highest severity)
        assert category == "FAIL_UNTRANSLATED_PROSE"

        # Should detect all 3 failures
        assert len(failures) == 3

        # First failure should be untranslated
        assert failures[0].category == "FAIL_UNTRANSLATED_PROSE"

    def test_all_failures_combined(self):
        """Test detection of all possible failure types."""
        verify_data = {
            "passed": False,
            "checks": {
                "untranslated": {
                    "ratio": 0.40,
                    "threshold": 0.35,
                    "passed": False,
                },
                "markdown_fidelity": {
                    "passed": False,
                    "errors": ["Bold mismatch", "Link mismatch"],
                },
                "code_preservation": {
                    "passed": False,
                },
                "token_leakage": {
                    "passed": False,
                    "leaks": ["{{%"],
                },
                "line_count": {
                    "source": 100,
                    "target": 80,
                    "threshold": 95.0,
                    "passed": False,
                },
                "frontmatter": {
                    "passed": False,
                    "source_keys": ["title"],
                    "target_keys": ["title", "extra"],
                },
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        # Primary should be untranslated (highest severity)
        assert category == "FAIL_UNTRANSLATED_PROSE"

        # Should detect multiple failures
        assert len(failures) >= 5

        categories = [f.category for f in failures]
        assert "FAIL_UNTRANSLATED_PROSE" in categories
        assert "FAIL_MARKDOWN_FIDELITY" in categories
        assert "FAIL_CODE_SPAN_CHANGED" in categories
        assert "FAIL_LINE_COUNT" in categories


class TestSeverityRanking:
    """Test that failures are ranked by severity."""

    def test_severity_ordering(self):
        """Test that severity rank is correct."""
        assert SEVERITY_RANK["FAIL_UNTRANSLATED_PROSE"] < SEVERITY_RANK["FAIL_MARKDOWN_FIDELITY"]
        assert SEVERITY_RANK["FAIL_MARKDOWN_FIDELITY"] < SEVERITY_RANK["FAIL_CODE_SPAN_CHANGED"]
        assert SEVERITY_RANK["FAIL_CODE_SPAN_CHANGED"] < SEVERITY_RANK["FAIL_LINE_COUNT"]
        assert SEVERITY_RANK["FAIL_LINE_COUNT"] < SEVERITY_RANK["FAIL_OTHER"]

    def test_failures_sorted_by_severity(self):
        """Test that returned failures are sorted by severity."""
        verify_data = {
            "passed": False,
            "checks": {
                "line_count": {  # Lower severity
                    "source": 100,
                    "target": 80,
                    "threshold": 95.0,
                    "passed": False,
                },
                "untranslated": {  # Higher severity
                    "ratio": 0.40,
                    "threshold": 0.35,
                    "passed": False,
                },
            },
        }

        _, _, failures = classify_all_failures(verify_data)

        # Should be sorted: untranslated first, line_count second
        assert failures[0].category == "FAIL_UNTRANSLATED_PROSE"
        assert failures[1].category == "FAIL_LINE_COUNT"

        # Verify severity values are in ascending order
        severities = [f.severity for f in failures]
        assert severities == sorted(severities)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_no_verification_data(self):
        """Test handling of missing verification data."""
        category, reason, failures = classify_all_failures(None)

        assert category == "FAIL_OTHER"
        assert "No verification data" in reason
        assert len(failures) == 1

    def test_empty_verification_data(self):
        """Test handling of empty verification data."""
        verify_data = {}

        category, reason, failures = classify_all_failures(verify_data)

        # Should return FAIL_OTHER
        assert category == "FAIL_OTHER"
        assert len(failures) == 1

    def test_verification_failed_no_specific_errors(self):
        """Test handling of generic verification failure."""
        verify_data = {
            "passed": False,
            "checks": {},  # No specific check failures
        }

        category, reason, failures = classify_all_failures(verify_data)

        assert category == "FAIL_OTHER"
        assert len(failures) == 1

    def test_verification_passed(self):
        """Test handling of successful verification (edge case)."""
        verify_data = {
            "passed": True,
            "checks": {
                "markdown_fidelity": {"passed": True},
                "line_count": {"passed": True},
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        # Should still return something (no failures detected)
        assert category == "FAIL_OTHER"
        assert len(failures) == 1


class TestFailureInfo:
    """Test FailureInfo dataclass."""

    def test_failure_info_creation(self):
        """Test creating FailureInfo objects."""
        failure = FailureInfo("FAIL_MARKDOWN_FIDELITY", "Bold mismatch", {"count": 5})

        assert failure.category == "FAIL_MARKDOWN_FIDELITY"
        assert failure.reason == "Bold mismatch"
        assert failure.details["count"] == 5
        assert failure.severity == SEVERITY_RANK["FAIL_MARKDOWN_FIDELITY"]

    def test_failure_info_to_dict(self):
        """Test converting FailureInfo to dictionary."""
        failure = FailureInfo("FAIL_UNTRANSLATED_PROSE", "Too much English", {"ratio": 0.5})

        result = failure.to_dict()

        assert result["category"] == "FAIL_UNTRANSLATED_PROSE"
        assert result["reason"] == "Too much English"
        assert result["details"]["ratio"] == 0.5


class TestBackwardCompatibility:
    """Test backward compatibility with legacy API."""

    def test_legacy_function_returns_primary_only(self):
        """Test that legacy function returns only primary category and reason."""
        verify_data = {
            "passed": False,
            "checks": {
                "markdown_fidelity": {"passed": False, "errors": ["Bold mismatch"]},
                "line_count": {"source": 100, "target": 80, "threshold": 95.0, "passed": False},
            },
        }

        category, reason = classify_failure_legacy(verify_data)

        # Should return tuple of 2 items (not 3)
        assert isinstance(category, str)
        assert isinstance(reason, str)
        assert category == "FAIL_MARKDOWN_FIDELITY"


class TestPhase6RealWorldCases:
    """Test with real Phase 6 verification data."""

    def test_cells_index_multi_failure(self):
        """Test the actual cells/_index.md case from Phase 6."""
        verify_data = {
            "passed": False,
            "checks": {
                "line_count": {
                    "source": 48,
                    "target": 30,
                    "threshold": 45.6,
                    "passed": False,
                },
                "markdown_fidelity": {
                    "passed": False,
                    "errors": [
                        "Bold span count mismatch: source=13, target=14. Bold must not convert to italic or list items.",
                        "Link count mismatch: source=4, target=5",
                    ],
                    "source_counts": {"bold": 13, "links": 4},
                    "target_counts": {"bold": 14, "links": 5},
                },
                "untranslated": {"ratio": 0.0, "threshold": 0.35, "passed": True},
            },
        }

        category, reason, failures = classify_all_failures(verify_data)

        # Should detect BOTH failures
        assert len(failures) == 2

        categories = [f.category for f in failures]
        assert "FAIL_MARKDOWN_FIDELITY" in categories
        assert "FAIL_LINE_COUNT" in categories

        # Primary should be markdown fidelity (higher severity)
        assert category == "FAIL_MARKDOWN_FIDELITY"

        # Verify both errors are captured
        md_failure = [f for f in failures if f.category == "FAIL_MARKDOWN_FIDELITY"][0]
        assert "Bold span count mismatch" in md_failure.reason
        assert md_failure.details["source_counts"]["bold"] == 13
        assert md_failure.details["target_counts"]["bold"] == 14


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
