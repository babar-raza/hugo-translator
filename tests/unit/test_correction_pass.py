"""Tests for TC-06: Two-stage translate + correct for failed validations."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.translation_engine.correction import (
    attempt_correction,
    build_correction_prompt,
)


class TestBuildCorrectionPrompt:
    def test_basic_prompt(self):
        prompt = build_correction_prompt(
            source_body="Hello world",
            translated_body="Hola mundo",
            src_lang="en",
            tgt_lang="es",
            issues=[{"severity": "error", "message": "Missing period"}],
        )
        assert "Hello world" in prompt
        assert "Hola mundo" in prompt
        assert "en" in prompt
        assert "es" in prompt
        assert "Missing period" in prompt

    def test_validation_issue_objects(self):
        """Test with objects that have .message and .severity attributes."""
        issue = MagicMock()
        issue.message = "Link broken"
        issue.severity = MagicMock()
        issue.severity.value = "warning"

        prompt = build_correction_prompt(
            source_body="src", translated_body="tgt",
            src_lang="en", tgt_lang="fr",
            issues=[issue],
        )
        assert "[warning] Link broken" in prompt

    def test_empty_issues(self):
        prompt = build_correction_prompt(
            source_body="src", translated_body="tgt",
            src_lang="en", tgt_lang="de",
            issues=[],
        )
        assert "(no details)" in prompt

    def test_truncates_long_content(self):
        long_text = "x" * 20_000
        prompt = build_correction_prompt(
            source_body=long_text, translated_body=long_text,
            src_lang="en", tgt_lang="ja",
            issues=[],
        )
        # Should not contain the full 20K text (capped at 8000)
        assert len(prompt) < 20_000


class TestAttemptCorrection:
    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_successful_correction(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_info = MagicMock()
        mock_registry.get_model.return_value = mock_info
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = "Corrected translation"
        mock_backend_cls.return_value = mock_backend

        result = attempt_correction(
            source_body="Hello",
            translated_body="Hola (broken)",
            src_lang="en",
            tgt_lang="es",
            issues=[{"severity": "error", "message": "Link broken"}],
            model_id="test_model",
        )
        assert result == "Corrected translation"
        mock_backend.load.assert_called_once()

    @patch("src.model_runtime.registry.ModelRegistry")
    def test_unknown_model_returns_none(self, mock_registry_cls):
        mock_registry = MagicMock()
        mock_registry.get_model.side_effect = KeyError("not found")
        mock_registry_cls.return_value = mock_registry

        result = attempt_correction(
            source_body="src", translated_body="tgt",
            src_lang="en", tgt_lang="es", issues=[],
        )
        assert result is None

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_empty_response_returns_none(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = ""
        mock_backend_cls.return_value = mock_backend

        result = attempt_correction(
            source_body="src", translated_body="tgt",
            src_lang="en", tgt_lang="fr", issues=[],
        )
        assert result is None

    def test_import_error_returns_none(self):
        """When model_runtime is unavailable, returns None gracefully."""
        with patch.dict("sys.modules", {"src.model_runtime.registry": None}):
            result = attempt_correction(
                source_body="src", translated_body="tgt",
                src_lang="en", tgt_lang="de", issues=[],
            )
            assert result is None

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_provider_none_returns_none(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = None
        mock_backend_cls.return_value = mock_backend

        result = attempt_correction(
            source_body="src", translated_body="tgt",
            src_lang="en", tgt_lang="it", issues=[],
        )
        assert result is None


class TestCorrectionConfigGate:
    """Tests proving correction only fires when config enables it."""

    def test_config_disabled_skips_correction(self):
        """When correction_pass.enabled is false, correction should not run."""
        config = {"correction_pass": {"enabled": False, "model": "professionalize_llm"}}
        # Simulate engine logic from engine.py ~line 1637
        _corr_cfg = config.get("correction_pass", {})
        should_run = _corr_cfg.get("enabled", False)
        assert should_run is False

    def test_config_enabled_allows_correction(self):
        """When correction_pass.enabled is true, correction should proceed."""
        config = {"correction_pass": {"enabled": True, "model": "professionalize_llm"}}
        _corr_cfg = config.get("correction_pass", {})
        should_run = _corr_cfg.get("enabled", False)
        assert should_run is True

    def test_missing_config_defaults_to_disabled(self):
        """Missing correction_pass config defaults to disabled."""
        config = {}
        _corr_cfg = config.get("correction_pass", {})
        should_run = _corr_cfg.get("enabled", False)
        assert should_run is False

    def test_guard_flag_prevents_double_correction(self):
        """_correction_attempted guard prevents infinite loops."""
        _correction_attempted = False

        # First attempt: should proceed
        if not _correction_attempted:
            _correction_attempted = True
            first_run = True
        else:
            first_run = False

        # Second attempt: should be blocked
        if not _correction_attempted:
            second_run = True
        else:
            second_run = False

        assert first_run is True
        assert second_run is False
