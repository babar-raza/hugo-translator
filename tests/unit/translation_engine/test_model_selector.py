"""Tests for TC-AGT-11: Run-history-backed model selection."""

import json
from pathlib import Path

import pytest

from src.translation_engine.model_selector import (
    ModelRecommendation,
    ModelScore,
    compute_model_scores,
    select_model,
)


@pytest.fixture()
def metrics_file(tmp_path):
    return tmp_path / "validation_metrics.jsonl"


def _write_metrics(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestModelScore:
    def test_acceptance_rate(self):
        score = ModelScore(model_id="m2m100", total_files=10, accepted_files=8)
        assert score.acceptance_rate == 0.8

    def test_acceptance_rate_zero(self):
        score = ModelScore(model_id="m2m100")
        assert score.acceptance_rate == 0.0


class TestComputeModelScores:
    def test_single_model(self):
        metrics = [
            {"model_id": "m2m100", "decision": "ACCEPT"},
            {"model_id": "m2m100", "decision": "ACCEPT"},
            {"model_id": "m2m100", "decision": "REJECT"},
        ]
        scores = compute_model_scores(metrics)
        assert "m2m100" in scores
        assert scores["m2m100"].total_files == 3
        assert scores["m2m100"].accepted_files == 2
        assert scores["m2m100"].rejected_files == 1

    def test_multiple_models(self):
        metrics = [
            {"model_id": "m2m100", "decision": "ACCEPT"},
            {"model_id": "m2m100", "decision": "REJECT"},
            {"model_id": "professionalize_llm", "decision": "ACCEPT"},
            {"model_id": "professionalize_llm", "decision": "ACCEPT"},
        ]
        scores = compute_model_scores(metrics)
        assert len(scores) == 2
        assert scores["m2m100"].acceptance_rate == 0.5
        assert scores["professionalize_llm"].acceptance_rate == 1.0

    def test_retry_counted(self):
        metrics = [
            {"model_id": "m2m100", "decision": "RETRY"},
        ]
        scores = compute_model_scores(metrics)
        assert scores["m2m100"].retried_files == 1
        assert scores["m2m100"].total_files == 1

    def test_empty_metrics(self):
        scores = compute_model_scores([])
        assert scores == {}

    def test_unknown_model(self):
        metrics = [{"decision": "ACCEPT"}]
        scores = compute_model_scores(metrics)
        assert "unknown" in scores


class TestSelectModel:
    def test_disabled_returns_default(self):
        result = select_model("site", "de", config={"enabled": False})
        assert result.recommended_model == "m2m100"
        assert result.fallback_used is True

    def test_no_config_returns_default(self):
        result = select_model("site", "de")
        assert result.recommended_model == "m2m100"
        assert result.fallback_used is True

    def test_custom_default_model(self):
        result = select_model("site", "de", config={"enabled": False, "default_model": "opus-mt"})
        assert result.recommended_model == "opus-mt"

    def test_insufficient_history(self, metrics_file):
        _write_metrics(
            metrics_file,
            [
                {
                    "site_id": "site",
                    "target_lang": "de",
                    "model_id": "m2m100",
                    "decision": "ACCEPT",
                },
                {
                    "site_id": "site",
                    "target_lang": "de",
                    "model_id": "m2m100",
                    "decision": "ACCEPT",
                },
            ],
        )
        result = select_model(
            "site",
            "de",
            config={"enabled": True, "min_history_runs": 5},
            metrics_file=metrics_file,
        )
        assert result.fallback_used is True
        assert "Insufficient" in result.reason

    def test_selects_best_model(self, metrics_file):
        entries = []
        # m2m100: 6/10 = 60%
        for _ in range(6):
            entries.append(
                {"site_id": "site", "target_lang": "de", "model_id": "m2m100", "decision": "ACCEPT"}
            )
        for _ in range(4):
            entries.append(
                {"site_id": "site", "target_lang": "de", "model_id": "m2m100", "decision": "REJECT"}
            )
        # professionalize_llm: 9/10 = 90%
        for _ in range(9):
            entries.append(
                {
                    "site_id": "site",
                    "target_lang": "de",
                    "model_id": "professionalize_llm",
                    "decision": "ACCEPT",
                }
            )
        entries.append(
            {
                "site_id": "site",
                "target_lang": "de",
                "model_id": "professionalize_llm",
                "decision": "REJECT",
            }
        )

        _write_metrics(metrics_file, entries)
        result = select_model(
            "site",
            "de",
            config={"enabled": True, "min_history_runs": 5},
            metrics_file=metrics_file,
        )
        assert result.recommended_model == "professionalize_llm"
        assert result.fallback_used is False
        assert len(result.candidates) == 2

    def test_filters_by_site_and_lang(self, metrics_file):
        entries = [
            {"site_id": "site-a", "target_lang": "de", "model_id": "m2m100", "decision": "ACCEPT"},
            {"site_id": "site-b", "target_lang": "de", "model_id": "opus-mt", "decision": "ACCEPT"},
            {"site_id": "site-a", "target_lang": "fr", "model_id": "nllb", "decision": "ACCEPT"},
        ]
        # Add more for site-a/de to meet threshold
        for _ in range(10):
            entries.append(
                {
                    "site_id": "site-a",
                    "target_lang": "de",
                    "model_id": "m2m100",
                    "decision": "ACCEPT",
                }
            )

        _write_metrics(metrics_file, entries)
        result = select_model(
            "site-a",
            "de",
            config={"enabled": True, "min_history_runs": 5},
            metrics_file=metrics_file,
        )
        assert result.recommended_model == "m2m100"
        # Should not see opus-mt or nllb
        model_ids = {c["model_id"] for c in result.candidates}
        assert "opus-mt" not in model_ids
        assert "nllb" not in model_ids

    def test_no_metrics_file(self, tmp_path):
        result = select_model(
            "site",
            "de",
            config={"enabled": True, "min_history_runs": 5},
            metrics_file=tmp_path / "nonexistent.jsonl",
        )
        assert result.fallback_used is True

    def test_confidence_scales_with_data(self, metrics_file):
        entries = []
        for _ in range(20):
            entries.append(
                {"site_id": "site", "target_lang": "de", "model_id": "m2m100", "decision": "ACCEPT"}
            )

        _write_metrics(metrics_file, entries)
        result = select_model(
            "site",
            "de",
            config={"enabled": True, "min_history_runs": 5},
            metrics_file=metrics_file,
        )
        assert result.confidence > 0.5  # 20 files / (5*2) = 2.0, capped at 1.0
        assert result.confidence <= 1.0

    def test_tiebreak_by_data_volume(self, metrics_file):
        entries = []
        # Both models at 100% but m2m100 has more data
        for _ in range(10):
            entries.append(
                {"site_id": "site", "target_lang": "de", "model_id": "m2m100", "decision": "ACCEPT"}
            )
        for _ in range(5):
            entries.append(
                {
                    "site_id": "site",
                    "target_lang": "de",
                    "model_id": "opus-mt",
                    "decision": "ACCEPT",
                }
            )

        _write_metrics(metrics_file, entries)
        result = select_model(
            "site",
            "de",
            config={"enabled": True, "min_history_runs": 5},
            metrics_file=metrics_file,
        )
        # m2m100 has more data at same rate, should be preferred
        assert result.recommended_model == "m2m100"
