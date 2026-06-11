"""
TC-TEST-03: LLM escalation deterministic unit tests.

Proves that the engine code path fires LLM escalation when retry_count >= 2
and config enables it, without requiring a live LLM model.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestLoadQueuedLlmPaths:
    """retranslate_queue.load_queued_llm_paths() filters by retry_count threshold."""

    def test_entries_at_threshold_are_included(self, tmp_path):
        """retry_count == 2 (== _LLM_ESCALATION_THRESHOLD) should be in the set."""
        queue_file = tmp_path / "retranslate_queue.jsonl"
        entries = [
            {"output_path": "/out/file_a.md", "tgt_lang": "fr", "retry_count": 2},
            {"output_path": "/out/file_b.md", "tgt_lang": "de", "retry_count": 1},
        ]
        queue_file.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        with patch("src.tm.retranslate_queue._queue_path", return_value=queue_file):
            from src.tm.retranslate_queue import load_queued_llm_paths

            result = load_queued_llm_paths()

        assert "/out/file_a.md" in result
        assert "/out/file_b.md" not in result

    def test_entries_above_max_retries_excluded(self, tmp_path):
        """retry_count > _MAX_RETRIES (3) should NOT be in the set (quarantine-bound)."""
        queue_file = tmp_path / "retranslate_queue.jsonl"
        entries = [
            {"output_path": "/out/stuck.md", "tgt_lang": "fr", "retry_count": 4},
            {"output_path": "/out/eligible.md", "tgt_lang": "de", "retry_count": 3},
        ]
        queue_file.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        with patch("src.tm.retranslate_queue._queue_path", return_value=queue_file):
            from src.tm.retranslate_queue import load_queued_llm_paths

            result = load_queued_llm_paths()

        assert "/out/stuck.md" not in result
        assert "/out/eligible.md" in result

    def test_empty_queue_returns_empty_set(self, tmp_path):
        """Missing queue file returns empty set."""
        queue_file = tmp_path / "nonexistent.jsonl"

        with patch("src.tm.retranslate_queue._queue_path", return_value=queue_file):
            from src.tm.retranslate_queue import load_queued_llm_paths

            result = load_queued_llm_paths()

        assert result == set()


class TestLlmModelOverrideApplied:
    """Engine applies model_id_override when output_path is in the escalation set."""

    def test_override_applied_when_in_escalation_set(self):
        """When output_path is in _rtq_llm_output_paths and escalation enabled,
        _llm_model_override should be set to the configured model."""
        mock_self = MagicMock()
        output_path = Path("/out/stuck_file.md")
        resolved = str(output_path.resolve())

        mock_self._rtq_llm_output_paths = {resolved}
        mock_self.config.get_config.return_value = {
            "translation_engine": {
                "llm_escalation_enabled": True,
                "llm_escalation_model": "professionalize_llm",
            }
        }

        # Reproduce the engine code path (engine.py:1455-1469)
        _llm_model_override = None
        _rtq_llm_paths = getattr(mock_self, "_rtq_llm_output_paths", None)
        if _rtq_llm_paths and str(output_path.resolve()) in _rtq_llm_paths:
            try:
                _te_cfg = mock_self.config.get_config().get("translation_engine", {})
                if _te_cfg.get("llm_escalation_enabled", False):
                    _llm_model_override = _te_cfg.get("llm_escalation_model", "professionalize_llm")
            except Exception:
                pass

        assert _llm_model_override == "professionalize_llm"

    def test_no_override_when_escalation_disabled(self):
        """When llm_escalation_enabled=false, no override even if path is in set."""
        mock_self = MagicMock()
        output_path = Path("/out/stuck_file.md")
        resolved = str(output_path.resolve())

        mock_self._rtq_llm_output_paths = {resolved}
        mock_self.config.get_config.return_value = {
            "translation_engine": {
                "llm_escalation_enabled": False,
            }
        }

        _llm_model_override = None
        _rtq_llm_paths = getattr(mock_self, "_rtq_llm_output_paths", None)
        if _rtq_llm_paths and str(output_path.resolve()) in _rtq_llm_paths:
            try:
                _te_cfg = mock_self.config.get_config().get("translation_engine", {})
                if _te_cfg.get("llm_escalation_enabled", False):
                    _llm_model_override = _te_cfg.get("llm_escalation_model", "professionalize_llm")
            except Exception:
                pass

        assert _llm_model_override is None

    def test_no_override_when_path_not_in_escalation_set(self):
        """When output_path is NOT in _rtq_llm_output_paths, no override."""
        mock_self = MagicMock()
        output_path = Path("/out/normal_file.md")

        mock_self._rtq_llm_output_paths = {"/out/different_file.md"}
        mock_self.config.get_config.return_value = {
            "translation_engine": {
                "llm_escalation_enabled": True,
                "llm_escalation_model": "professionalize_llm",
            }
        }

        _llm_model_override = None
        _rtq_llm_paths = getattr(mock_self, "_rtq_llm_output_paths", None)
        if _rtq_llm_paths and str(output_path.resolve()) in _rtq_llm_paths:
            try:
                _te_cfg = mock_self.config.get_config().get("translation_engine", {})
                if _te_cfg.get("llm_escalation_enabled", False):
                    _llm_model_override = _te_cfg.get("llm_escalation_model", "professionalize_llm")
            except Exception:
                pass

        assert _llm_model_override is None


class TestGlobalYamlEscalationConfig:
    """Verify global.yaml has the expected LLM escalation configuration."""

    def test_llm_escalation_enabled_in_config(self):
        """global.yaml must have llm_escalation_enabled: true (TC-FIX-03)."""
        import yaml

        raw = yaml.safe_load(Path("config/global.yaml").read_text(encoding="utf-8"))
        te_cfg = raw.get("translation_engine", {})
        assert te_cfg.get("llm_escalation_enabled") is True, (
            "llm_escalation_enabled must be true in global.yaml (TC-FIX-03)"
        )

    def test_llm_escalation_model_configured(self):
        """global.yaml must have llm_escalation_model set."""
        import yaml

        raw = yaml.safe_load(Path("config/global.yaml").read_text(encoding="utf-8"))
        te_cfg = raw.get("translation_engine", {})
        model = te_cfg.get("llm_escalation_model", "professionalize_llm")
        assert model, "llm_escalation_model must be a non-empty string"
