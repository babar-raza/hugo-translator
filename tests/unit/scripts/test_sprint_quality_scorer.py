"""Unit tests for scripts/ops/sprint_quality_scorer.py.

Tests quality scoring, reroute detection, and threshold enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.ops.sprint_quality_scorer import (
    ALL_DIMENSIONS,
    DEFAULT_WEIGHTS,
    check_rework,
    compute_weighted_overall,
    create_template,
    evaluate_all,
    evaluate_taskcard,
    load_rubric,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _all_scores(score: float) -> dict[str, float]:
    """Create dimension_scores with all dimensions set to the same score."""
    return dict.fromkeys(ALL_DIMENSIONS, score)


def _scores_with_override(base: float, **overrides: float) -> dict[str, float]:
    """Create dimension_scores with a base score and overrides."""
    scores = _all_scores(base)
    scores.update(overrides)
    return scores


# ---------------------------------------------------------------------------
# Weighted overall tests
# ---------------------------------------------------------------------------


class TestWeightedOverall:
    def test_perfect_scores(self) -> None:
        scores = _all_scores(5.0)
        overall = compute_weighted_overall(scores, DEFAULT_WEIGHTS)
        assert overall == 5.0

    def test_zero_scores(self) -> None:
        scores = _all_scores(0.0)
        overall = compute_weighted_overall(scores, DEFAULT_WEIGHTS)
        assert overall == 0.0

    def test_mixed_scores(self) -> None:
        scores = _all_scores(4.0)
        overall = compute_weighted_overall(scores, DEFAULT_WEIGHTS)
        assert overall == 4.0

    def test_weights_sum_to_one(self) -> None:
        total = sum(DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Rework detection tests
# ---------------------------------------------------------------------------


class TestReworkDetection:
    def test_all_passing(self) -> None:
        scores = _all_scores(5.0)
        rework = check_rework(scores, 5.0)
        assert rework == []

    def test_dimension_below_minimum(self) -> None:
        """NC-4: Score 3/5 in required dimension -> rerouted."""
        scores = _scores_with_override(5.0, evidence_quality=2.5)
        rework = check_rework(scores, 4.5)
        assert len(rework) >= 1
        dims = [r["dimension"] for r in rework]
        assert "evidence_quality" in dims

    def test_critical_dimension_below_threshold(self) -> None:
        scores = _scores_with_override(4.5, correctness=3.5)
        rework = check_rework(scores, 4.3)
        dims = [r["dimension"] for r in rework]
        assert "correctness" in dims

    def test_overall_below_minimum(self) -> None:
        scores = _all_scores(3.5)
        overall = compute_weighted_overall(scores, DEFAULT_WEIGHTS)
        rework = check_rework(scores, overall)
        dims = [r["dimension"] for r in rework]
        assert "overall" in dims

    def test_boundary_score_passes(self) -> None:
        """Score of exactly 3.0 should pass dimension minimum."""
        scores = _all_scores(4.5)
        scores["documentation"] = 3.0
        overall = compute_weighted_overall(scores, DEFAULT_WEIGHTS)
        rework = check_rework(scores, overall)
        # documentation at exactly 3.0 passes the >= 3.0 check
        doc_rework = [r for r in rework if r["dimension"] == "documentation"]
        assert len(doc_rework) == 0


# ---------------------------------------------------------------------------
# Taskcard evaluation tests
# ---------------------------------------------------------------------------


class TestTaskcardEvaluation:
    def test_accepted(self) -> None:
        scores = _all_scores(5.0)
        result = evaluate_taskcard("TC-01", scores, DEFAULT_WEIGHTS)
        assert result["verdict"] == "ACCEPTED"
        assert result["rework_items"] == []

    def test_rerouted(self) -> None:
        """NC-4: Below-4 triggers REROUTED."""
        scores = _scores_with_override(5.0, correctness=2.0)
        result = evaluate_taskcard("TC-01", scores, DEFAULT_WEIGHTS)
        assert result["verdict"] == "REROUTED"
        assert len(result["rework_items"]) >= 1


# ---------------------------------------------------------------------------
# Full evaluation tests
# ---------------------------------------------------------------------------


class TestFullEvaluation:
    def test_all_green(self) -> None:
        data = {
            "run_id": "test",
            "evaluations": [
                {"taskcard_id": "TC-01", "dimension_scores": _all_scores(5.0), "reroute_count": 0},
                {"taskcard_id": "TC-02", "dimension_scores": _all_scores(4.5), "reroute_count": 0},
            ],
        }
        result = evaluate_all(data, DEFAULT_WEIGHTS)
        assert result["final_sprint_summary"]["all_green"] is True
        assert result["final_sprint_summary"]["accepted_count"] == 2
        assert result["final_sprint_summary"]["rerouted_count"] == 0

    def test_mixed_results(self) -> None:
        data = {
            "run_id": "test",
            "evaluations": [
                {"taskcard_id": "TC-01", "dimension_scores": _all_scores(5.0), "reroute_count": 0},
                {
                    "taskcard_id": "TC-02",
                    "dimension_scores": _scores_with_override(5.0, correctness=1.0),
                    "reroute_count": 0,
                },
            ],
        }
        result = evaluate_all(data, DEFAULT_WEIGHTS)
        assert result["final_sprint_summary"]["all_green"] is False
        assert result["final_sprint_summary"]["accepted_count"] == 1
        assert result["final_sprint_summary"]["rerouted_count"] == 1
        assert len(result["reroute_log"]) == 1

    def test_no_taskcard_accepted_without_evidence(self) -> None:
        """NC-9: Taskcard accepted without evidence -> blocked.
        Enforced by evaluate_taskcard: score of 0 in evidence_quality
        triggers reroute."""
        scores = _scores_with_override(5.0, evidence_quality=0.0)
        result = evaluate_taskcard("TC-01", scores, DEFAULT_WEIGHTS)
        assert result["verdict"] == "REROUTED"


# ---------------------------------------------------------------------------
# Rubric loading tests
# ---------------------------------------------------------------------------


class TestRubricLoading:
    def test_missing_rubric_uses_defaults(self, tmp_path: Path) -> None:
        weights = load_rubric(tmp_path / "nonexistent.yaml")
        assert weights == DEFAULT_WEIGHTS

    def test_valid_rubric_loads(self) -> None:
        rubric_path = Path("config/sprint_quality_rubric.yaml")
        if rubric_path.exists():
            weights = load_rubric(rubric_path)
            assert abs(weights["correctness"] - 0.18) < 0.01


# ---------------------------------------------------------------------------
# Template creation tests
# ---------------------------------------------------------------------------


class TestTemplateCreation:
    def test_create_template(self, tmp_path: Path) -> None:
        path = tmp_path / "template.json"
        create_template(path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "evaluations" in data
        assert len(data["evaluations"]) == 1
        assert data["evaluations"][0]["taskcard_id"] == "TC-EXAMPLE-01"
