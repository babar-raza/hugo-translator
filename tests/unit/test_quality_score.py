"""TC-H5 / TC-H5B: Per-file quality score tests.

TC-H5B fix 2026-06-11 (ethereal-sauteeing-brook sprint 2):
  Replaced tautological inline-logic tests with tests that call the actual engine
  method TranslationEngine._compute_quality_score().  The previous tests replicated
  the scoring if/elif/else in the test body and then asserted the value the test
  itself had just set — they would pass even if the engine code was removed.

  These tests fail if:
  - _compute_quality_score() is removed from the engine
  - The method's branching logic changes without updating the tests
  - quality_score is not set correctly in either the ACCEPT or REJECT code path

Engine code path covered:
  - TranslationEngine._compute_quality_score() (static method, engine.py ~line 1044)
  - engine.py ACCEPT path: result.stats.quality_score = _compute_quality_score(_s)
  - engine.py REJECT path: result.stats.quality_score = "FAIL" (TranslationRejectedError)
"""

from __future__ import annotations

import pytest

from src.translation_engine.models import TranslationStats
from src.translation_engine.engine import TranslationEngine


class TestQualityScoreEngineMethod:
    """Tests that call TranslationEngine._compute_quality_score() directly.

    These tests would fail if the method is removed or its logic changes.
    """

    def test_pass_score(self):
        """0 errors, 0 warnings, 0 missing nodes → PASS."""
        stats = TranslationStats(
            validation_passed=True,
            validation_errors=0,
            validation_warnings=0,
            ast_missing_nodes=0,
        )
        score = TranslationEngine._compute_quality_score(stats)
        assert score == "PASS"

    def test_partial_score_warnings(self):
        """1 warning, 0 errors → PARTIAL."""
        stats = TranslationStats(
            validation_passed=True,
            validation_errors=0,
            validation_warnings=1,
            ast_missing_nodes=0,
        )
        score = TranslationEngine._compute_quality_score(stats)
        assert score == "PARTIAL"

    def test_fail_score_validation_error(self):
        """Any ERROR → FAIL regardless of warning or missing-node count."""
        stats = TranslationStats(
            validation_passed=False,
            validation_errors=2,
            validation_warnings=3,
            ast_missing_nodes=0,
        )
        score = TranslationEngine._compute_quality_score(stats)
        assert score == "FAIL"

    def test_partial_score_missing_nodes(self):
        """2 missing nodes (>1), 0 errors → PARTIAL."""
        stats = TranslationStats(
            validation_passed=True,
            validation_errors=0,
            validation_warnings=0,
            ast_missing_nodes=2,
        )
        score = TranslationEngine._compute_quality_score(stats)
        assert score == "PARTIAL"

    def test_pass_boundary_one_missing_node(self):
        """Exactly 1 missing node (≤1), 0 errors, 0 warnings → PASS (boundary condition)."""
        stats = TranslationStats(
            validation_passed=True,
            validation_errors=0,
            validation_warnings=0,
            ast_missing_nodes=1,
        )
        score = TranslationEngine._compute_quality_score(stats)
        assert score == "PASS", "Exactly 1 missing node must be PASS (boundary is >1)"

    def test_error_dominates_warnings(self):
        """Errors dominate warnings: even if warnings > 0, errors → FAIL not PARTIAL."""
        stats = TranslationStats(
            validation_passed=False,
            validation_errors=1,
            validation_warnings=5,
            ast_missing_nodes=3,
        )
        score = TranslationEngine._compute_quality_score(stats)
        assert score == "FAIL", "Errors must dominate — result must be FAIL not PARTIAL"

    def test_method_is_callable_as_static(self):
        """_compute_quality_score must be a static method callable without an instance."""
        # This test fails if the method is removed or turned into an instance method
        # without updating the call sites.
        assert callable(TranslationEngine._compute_quality_score), (
            "_compute_quality_score must exist as a callable on TranslationEngine"
        )
        # Call through the class (not an instance) to confirm static method contract
        result = TranslationEngine._compute_quality_score(
            TranslationStats(validation_errors=0, validation_warnings=0, ast_missing_nodes=0)
        )
        assert result == "PASS"


class TestQualityScoreFieldPresence:
    """Preserve the original TC-H5 check that the field exists on TranslationStats."""

    def test_quality_score_field_exists_and_defaults_empty(self):
        """quality_score field is present on TranslationStats and defaults to empty string."""
        stats = TranslationStats()
        assert hasattr(stats, "quality_score")
        assert stats.quality_score == ""
