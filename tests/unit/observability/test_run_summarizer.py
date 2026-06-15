"""Tests for TC-AGT-04: Professionalize run summarizer."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.observability.run_summarizer import (
    build_summary_prompt,
    summarize_run,
)


SAMPLE_METRICS = {
    "site_id": "docs.aspose.net.words",
    "files_processed": 20,
    "translated": 18,
    "rejected": 1,
    "retried": 1,
    "validators_run": 100,
    "validators_passed": 95,
    "validators_failed": 5,
    "llm_calls": 3,
    "llm_tokens": 2000,
}


class TestBuildSummaryPrompt:
    """Test prompt construction."""

    def test_prompt_contains_metrics(self):
        """Prompt includes the metrics JSON."""
        prompt = build_summary_prompt(SAMPLE_METRICS)
        assert "docs.aspose.net.words" in prompt
        assert "files_processed" in prompt
        assert "20" in prompt

    def test_prompt_has_instructions(self):
        """Prompt includes summarization instructions."""
        prompt = build_summary_prompt(SAMPLE_METRICS)
        assert "3-5 sentences" in prompt
        assert "factual" in prompt


class TestSummarizeRun:
    """Test the summarize_run function."""

    def test_disabled_returns_empty(self):
        """Disabled summarizer returns empty result."""
        result = summarize_run(SAMPLE_METRICS, config={"enabled": False})
        assert result["summary"] == ""
        assert result["llm_called"] is False

    def test_dry_run_writes_file(self):
        """Dry-run mode writes summary file without LLM call."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            result = summarize_run(
                SAMPLE_METRICS,
                config={"enabled": True, "dry_run": True},
                output_dir=Path(tmpdir),
            )
            assert result["dry_run"] is True
            assert result["llm_called"] is False
            assert "(dry-run mode" in result["summary"]
            assert result["output_path"]

            # Verify file was written
            out_path = Path(result["output_path"])
            assert out_path.exists()
            data = json.loads(out_path.read_text(encoding="utf-8"))
            assert data["site_id"] == "docs.aspose.net.words"
            assert data["dry_run"] is True
            assert data["metrics"]["files_processed"] == 20

    def test_dry_run_prompt_populated(self):
        """Dry-run mode still builds the prompt."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            result = summarize_run(
                SAMPLE_METRICS,
                config={"enabled": True, "dry_run": True},
                output_dir=Path(tmpdir),
            )
            assert "files_processed" in result["prompt"]

    @patch("src.observability.run_summarizer._call_llm")
    def test_live_mode_calls_llm(self, mock_call_llm):
        """Live mode calls LLM and uses response."""
        mock_call_llm.return_value = "Translation run processed 20 files with 90% acceptance rate."
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            result = summarize_run(
                SAMPLE_METRICS,
                config={"enabled": True, "dry_run": False},
                output_dir=Path(tmpdir),
            )
            assert result["llm_called"] is True
            assert "20 files" in result["summary"]
            mock_call_llm.assert_called_once()

    @patch("src.observability.run_summarizer._call_llm")
    def test_live_mode_llm_failure(self, mock_call_llm):
        """Live mode handles LLM failure gracefully."""
        mock_call_llm.return_value = None
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            result = summarize_run(
                SAMPLE_METRICS,
                config={"enabled": True, "dry_run": False},
                output_dir=Path(tmpdir),
            )
            assert result["llm_called"] is False
            assert "failed" in result["summary"]

    def test_default_config_disabled(self):
        """Default config (no config passed) disables summarizer."""
        result = summarize_run(SAMPLE_METRICS)
        assert result["summary"] == ""
        assert result["llm_called"] is False
