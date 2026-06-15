"""Tests for TC-AGT-08: Professionalize-powered contradiction detector."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.observability.contradiction_detector import (
    _parse_contradictions,
    build_contradiction_prompt,
    collect_config_snippets,
    collect_observed_behavior,
    detect_contradictions,
)


SAMPLE_CONFIG = {
    "adaptive_thresholds": {"enabled": True, "min_history_runs": 10},
    "agent_metrics": {"enabled": False, "dry_run": True},
}

SAMPLE_BEHAVIOR = {
    "latest_signal": {"status": "completed", "verdict": "CLEAN_RUN"},
    "continuation_state": {"phase": "idle", "total_runs": 5},
}


class TestBuildPrompt:
    def test_prompt_contains_config(self):
        prompt = build_contradiction_prompt(SAMPLE_CONFIG, SAMPLE_BEHAVIOR)
        assert "adaptive_thresholds" in prompt
        assert "enabled" in prompt
        assert "true" in prompt.lower()

    def test_prompt_contains_behavior(self):
        prompt = build_contradiction_prompt(SAMPLE_CONFIG, SAMPLE_BEHAVIOR)
        assert "CLEAN_RUN" in prompt
        assert "completed" in prompt

    def test_prompt_has_instructions(self):
        prompt = build_contradiction_prompt(SAMPLE_CONFIG, SAMPLE_BEHAVIOR)
        assert "contradiction" in prompt.lower()
        assert "severity" in prompt.lower()


class TestParseContradictions:
    def test_parse_json_array(self):
        response = '[{"id": "C-01", "severity": "HIGH", "config_key": "x"}]'
        result = _parse_contradictions(response)
        assert len(result) == 1
        assert result[0]["id"] == "C-01"

    def test_parse_empty_array(self):
        result = _parse_contradictions("[]")
        assert result == []

    def test_parse_embedded_array(self):
        response = 'Here are the contradictions:\n[{"id": "C-01"}]\nDone.'
        result = _parse_contradictions(response)
        assert len(result) == 1

    def test_parse_invalid_returns_raw(self):
        response = "No contradictions found."
        result = _parse_contradictions(response)
        assert len(result) == 1
        assert result[0]["id"] == "RAW"

    def test_parse_empty_string(self):
        result = _parse_contradictions("")
        assert result == []


class TestCollectConfigSnippets:
    def test_extracts_known_sections(self):
        config = {
            "adaptive_thresholds": {"enabled": True},
            "agent_metrics": {"enabled": False, "dry_run": True, "secret": "hidden"},
            "correction_pass": {"enabled": True, "model": "professionalize_llm"},
            "unrelated_section": {"foo": "bar"},
        }
        snippets = collect_config_snippets(config)
        assert "adaptive_thresholds" in snippets
        assert "agent_metrics" in snippets
        assert "correction_pass" in snippets
        assert "unrelated_section" not in snippets
        # Verify agent_metrics only has safe keys
        assert "secret" not in snippets["agent_metrics"]

    def test_empty_config(self):
        snippets = collect_config_snippets({})
        assert snippets == {}


class TestCollectObservedBehavior:
    def test_reads_signal_files(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        signal = {
            "status": "completed",
            "verdict": "CLEAN_RUN",
            "files": {"processed": 10},
            "llm_usage": {"calls": 2},
        }
        (signals_dir / "run-signal-001.json").write_text(json.dumps(signal), encoding="utf-8")
        behavior = collect_observed_behavior(run_signals_dir=signals_dir)
        assert behavior["latest_signal"]["status"] == "completed"
        assert behavior["latest_signal"]["verdict"] == "CLEAN_RUN"

    def test_reads_continuation_state(self, tmp_path):
        state_file = tmp_path / "continuation_state.json"
        state = {
            "phase": "completed",
            "stats": {"total_runs": 3, "consecutive_failures": 0},
            "blockers": [],
        }
        state_file.write_text(json.dumps(state), encoding="utf-8")
        behavior = collect_observed_behavior(continuation_state_file=state_file)
        assert behavior["continuation_state"]["phase"] == "completed"
        assert behavior["continuation_state"]["total_runs"] == 3

    def test_missing_dirs_return_empty(self, tmp_path):
        behavior = collect_observed_behavior(
            run_signals_dir=tmp_path / "nonexistent",
            continuation_state_file=tmp_path / "nonexistent.json",
        )
        assert "latest_signal" not in behavior
        assert "continuation_state" not in behavior


class TestDetectContradictions:
    def test_disabled_returns_empty(self):
        result = detect_contradictions(
            SAMPLE_CONFIG,
            SAMPLE_BEHAVIOR,
            detector_config={"enabled": False},
        )
        assert result["contradictions"] == []
        assert result["llm_called"] is False

    def test_dry_run_writes_file(self, tmp_path):
        result = detect_contradictions(
            SAMPLE_CONFIG,
            SAMPLE_BEHAVIOR,
            detector_config={"enabled": True, "dry_run": True},
            output_dir=tmp_path,
        )
        assert result["dry_run"] is True
        assert result["llm_called"] is False
        assert result["contradictions"][0]["id"] == "DRY_RUN"
        assert result["output_path"]

        out_path = Path(result["output_path"])
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["dry_run"] is True
        assert data["contradictions_count"] >= 1

    def test_dry_run_prompt_populated(self, tmp_path):
        result = detect_contradictions(
            SAMPLE_CONFIG,
            SAMPLE_BEHAVIOR,
            detector_config={"enabled": True, "dry_run": True},
            output_dir=tmp_path,
        )
        assert "adaptive_thresholds" in result["prompt"]

    @patch("src.observability.contradiction_detector._call_llm")
    def test_live_mode_calls_llm(self, mock_call_llm, tmp_path):
        mock_call_llm.return_value = '[{"id": "C-01", "severity": "HIGH", "config_key": "adaptive_thresholds.enabled", "expected": "active", "observed": "never invoked"}]'
        result = detect_contradictions(
            SAMPLE_CONFIG,
            SAMPLE_BEHAVIOR,
            detector_config={"enabled": True, "dry_run": False},
            output_dir=tmp_path,
        )
        assert result["llm_called"] is True
        assert len(result["contradictions"]) == 1
        assert result["contradictions"][0]["id"] == "C-01"
        mock_call_llm.assert_called_once()

    @patch("src.observability.contradiction_detector._call_llm")
    def test_live_mode_llm_failure(self, mock_call_llm, tmp_path):
        mock_call_llm.return_value = None
        result = detect_contradictions(
            SAMPLE_CONFIG,
            SAMPLE_BEHAVIOR,
            detector_config={"enabled": True, "dry_run": False},
            output_dir=tmp_path,
        )
        assert result["llm_called"] is False
        assert any(c["id"] == "LLM_UNAVAILABLE" for c in result["contradictions"])

    def test_default_config_disabled(self):
        result = detect_contradictions(SAMPLE_CONFIG, SAMPLE_BEHAVIOR)
        assert result["contradictions"] == []
        assert result["llm_called"] is False
