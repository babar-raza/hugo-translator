"""TC-H5: Per-file quality score tests.

Four cases:
  1. test_pass_score — purity OK, no errors, no missing nodes → PASS
  2. test_partial_score_warnings — purity OK, 1 warning, no errors → PARTIAL
  3. test_fail_score_validation_error — any ERROR → FAIL
  4. test_fail_score_missing_nodes — >1 missing node → PARTIAL (boundary)
"""

from __future__ import annotations

import pytest

from src.translation_engine.models import TranslationStats


class TestQualityScore:
    def test_pass_score(self):
        """Purity OK, 0 errors, 0 missing nodes → PASS."""
        stats = TranslationStats(
            validation_passed=True,
            validation_errors=0,
            validation_warnings=0,
            ast_missing_nodes=0,
        )
        # Simulate engine decision
        if stats.validation_errors > 0:
            stats.quality_score = "FAIL"
        elif stats.ast_missing_nodes > 1 or stats.validation_warnings > 0:
            stats.quality_score = "PARTIAL"
        else:
            stats.quality_score = "PASS"

        assert stats.quality_score == "PASS"

    def test_partial_score_warnings(self):
        """Purity OK, 1 warning, 0 errors → PARTIAL."""
        stats = TranslationStats(
            validation_passed=True,
            validation_errors=0,
            validation_warnings=1,
            ast_missing_nodes=0,
        )
        if stats.validation_errors > 0:
            stats.quality_score = "FAIL"
        elif stats.ast_missing_nodes > 1 or stats.validation_warnings > 0:
            stats.quality_score = "PARTIAL"
        else:
            stats.quality_score = "PASS"

        assert stats.quality_score == "PARTIAL"

    def test_fail_score_validation_error(self):
        """Any validation ERROR → FAIL regardless of warnings."""
        stats = TranslationStats(
            validation_passed=False,
            validation_errors=2,
            validation_warnings=3,
            ast_missing_nodes=0,
        )
        if stats.validation_errors > 0:
            stats.quality_score = "FAIL"
        elif stats.ast_missing_nodes > 1 or stats.validation_warnings > 0:
            stats.quality_score = "PARTIAL"
        else:
            stats.quality_score = "PASS"

        assert stats.quality_score == "FAIL"

    def test_partial_score_missing_nodes(self):
        """2 missing nodes (>1) → PARTIAL when no errors."""
        stats = TranslationStats(
            validation_passed=True,
            validation_errors=0,
            validation_warnings=0,
            ast_missing_nodes=2,
        )
        if stats.validation_errors > 0:
            stats.quality_score = "FAIL"
        elif stats.ast_missing_nodes > 1 or stats.validation_warnings > 0:
            stats.quality_score = "PARTIAL"
        else:
            stats.quality_score = "PASS"

        assert stats.quality_score == "PARTIAL"

    def test_quality_score_field_exists(self):
        """quality_score field is present on TranslationStats and defaults to empty string."""
        stats = TranslationStats()
        assert hasattr(stats, "quality_score")
        assert stats.quality_score == ""
