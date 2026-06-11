"""
Unit tests for engine multi-mode support (T304: federated-splashing-panda).

Tests TranslationEngine with serial, parallel, and round-robin modes.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.translation_engine.engine import TranslationEngine
from src.translation_engine.models import (
    LanguageProgress,
    MultiLanguageProgress,
    TranslationResult,
)


class TestTranslationEngineMultiModeInitialization:
    """Test TranslationEngine initialization with multi-language parameters."""

    def test_engine_serial_mode(self):
        """Test engine initialization in serial mode (default)."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
            parallel_languages=0,
            global_lang_rounds=0,
        )

        assert engine.parallel_languages == 0
        assert engine.global_lang_rounds == 0
        assert engine.global_lang_sort == "desc"

    def test_engine_parallel_mode(self):
        """Test engine initialization in parallel mode."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
            parallel_languages=2,
        )

        assert engine.parallel_languages == 2
        assert engine.global_lang_rounds == 0

    def test_engine_roundrobin_mode(self):
        """Test engine initialization in round-robin mode."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
            global_lang_rounds=50,
            global_lang_sort="asc",
        )

        assert engine.parallel_languages == 0
        assert engine.global_lang_rounds == 50
        assert engine.global_lang_sort == "asc"

    def test_mutual_exclusion_raises_error(self):
        """Test that using both parallel and round-robin raises ValueError."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        with pytest.raises(ValueError, match="Cannot use both"):
            TranslationEngine(
                config_service=mock_config,
                tm=mock_tm,
                model_loader=mock_loader,
                parallel_languages=2,
                global_lang_rounds=50,
            )

    def test_engine_with_kwargs(self):
        """Test engine initialization with multi-language kwargs."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
            **{
                "parallel_languages": 3,
                "global_lang_sort": "desc",
            },
        )

        assert engine.parallel_languages == 3
        assert engine.global_lang_sort == "desc"


class TestTranslationEngineClearCache:
    """Test TranslationEngine._clear_language_cache()."""

    def test_clear_language_cache_clears_l1(self):
        """Test _clear_language_cache clears L1 cache."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        # Mock L1 cache with clear method
        mock_l1 = Mock()
        mock_l1.cache = {"key1": "value1", "key2": "value2"}
        mock_tm.l1 = mock_l1

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
        )

        # Call clear
        engine._clear_language_cache()

        # Verify clear was called
        mock_l1.clear.assert_called_once()

    def test_clear_language_cache_handles_missing_l1(self):
        """Test _clear_language_cache handles missing L1 gracefully."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        # No L1 cache
        del mock_tm.l1

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
        )

        # Should not raise exception
        engine._clear_language_cache()

    def test_clear_language_cache_handles_missing_clear_method(self):
        """Test _clear_language_cache handles missing clear method."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        # L1 without clear method
        mock_l1 = Mock()
        del mock_l1.clear
        mock_tm.l1 = mock_l1

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
        )

        # Should not raise exception
        engine._clear_language_cache()


class TestTranslationEngineSingleLanguage:
    """Test TranslationEngine._translate_single_language()."""

    @patch.object(TranslationEngine, "translate_file")
    def test_translate_single_language_calls_translate_file(self, mock_translate_file):
        """Test _translate_single_language calls translate_file with single language."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        # Mock translate_file return value
        mock_result = Mock(spec=TranslationResult)
        mock_translate_file.return_value = mock_result

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
        )

        # Call _translate_single_language
        result = engine._translate_single_language(
            site_id="example",
            file_path=Path("content/post.md"),
            target_lang="de",
            force=False,
        )

        # Verify translate_file called with single language
        mock_translate_file.assert_called_once_with(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["de"],
            force=False,
        )

        assert result is mock_result

    @patch.object(TranslationEngine, "translate_file")
    def test_translate_single_language_with_force(self, mock_translate_file):
        """Test _translate_single_language passes force parameter."""
        mock_config = Mock()
        mock_tm = Mock()
        mock_loader = Mock()

        mock_result = Mock(spec=TranslationResult)
        mock_translate_file.return_value = mock_result

        engine = TranslationEngine(
            config_service=mock_config,
            tm=mock_tm,
            model_loader=mock_loader,
        )

        result = engine._translate_single_language(
            site_id="example",
            file_path=Path("content/post.md"),
            target_lang="fr",
            force=True,
        )

        # Verify force=True passed
        mock_translate_file.assert_called_once_with(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["fr"],
            force=True,
        )


class TestLanguageProgressModel:
    """Test LanguageProgress dataclass."""

    def test_language_progress_initialization(self):
        """Test LanguageProgress initialization."""
        progress = LanguageProgress(
            language_code="de",
            total_texts=100,
            completed_texts=50,
            success=True,
        )

        assert progress.language_code == "de"
        assert progress.total_texts == 100
        assert progress.completed_texts == 50
        assert progress.success is True
        assert progress.error is None

    def test_language_progress_percentage(self):
        """Test progress_percentage property."""
        progress = LanguageProgress(
            language_code="fr",
            total_texts=100,
            completed_texts=25,
        )

        assert progress.progress_percentage == 25.0

    def test_language_progress_percentage_zero_total(self):
        """Test progress_percentage when total is zero."""
        progress = LanguageProgress(
            language_code="es",
            total_texts=0,
            completed_texts=0,
        )

        assert progress.progress_percentage == 100.0

    def test_language_progress_with_error(self):
        """Test LanguageProgress with error."""
        progress = LanguageProgress(
            language_code="it",
            total_texts=100,
            completed_texts=0,
            success=False,
            error="Translation failed",
        )

        assert progress.success is False
        assert progress.error == "Translation failed"


class TestMultiLanguageProgressModel:
    """Test MultiLanguageProgress dataclass."""

    def test_multilanguage_progress_initialization(self):
        """Test MultiLanguageProgress initialization."""
        progress = MultiLanguageProgress(
            mode="parallel",
            current_round=0,
        )

        assert progress.mode == "parallel"
        assert progress.current_round == 0
        assert len(progress.languages) == 0

    def test_multilanguage_progress_total_languages(self):
        """Test total_languages property."""
        progress = MultiLanguageProgress()
        progress.languages = {
            "de": LanguageProgress("de", 100, 50),
            "fr": LanguageProgress("fr", 100, 75),
        }

        assert progress.total_languages == 2

    def test_multilanguage_progress_completed_languages(self):
        """Test completed_languages property."""
        progress = MultiLanguageProgress()
        progress.languages = {
            "de": LanguageProgress("de", 100, 100),  # Complete
            "fr": LanguageProgress("fr", 100, 75),  # Incomplete
            "es": LanguageProgress("es", 50, 50),  # Complete
        }

        assert progress.completed_languages == 2

    def test_multilanguage_progress_overall_percentage(self):
        """Test overall_progress_percentage property."""
        progress = MultiLanguageProgress()
        progress.languages = {
            "de": LanguageProgress("de", 100, 50),  # 50%
            "fr": LanguageProgress("fr", 100, 100),  # 100%
        }

        # Overall: 150/200 = 75%
        assert progress.overall_progress_percentage == 75.0

    def test_multilanguage_progress_overall_percentage_empty(self):
        """Test overall_progress_percentage when no languages."""
        progress = MultiLanguageProgress()

        assert progress.overall_progress_percentage == 100.0

    def test_multilanguage_progress_overall_percentage_zero_total(self):
        """Test overall_progress_percentage when total is zero."""
        progress = MultiLanguageProgress()
        progress.languages = {
            "de": LanguageProgress("de", 0, 0),
            "fr": LanguageProgress("fr", 0, 0),
        }

        assert progress.overall_progress_percentage == 100.0

    def test_multilanguage_progress_roundrobin_mode(self):
        """Test MultiLanguageProgress with round-robin mode."""
        progress = MultiLanguageProgress(
            mode="roundrobin",
            current_round=5,
        )
        progress.languages = {
            "de": LanguageProgress("de", 100, 60),
            "fr": LanguageProgress("fr", 100, 50),
            "es": LanguageProgress("es", 100, 40),
        }

        assert progress.mode == "roundrobin"
        assert progress.current_round == 5
        assert progress.total_languages == 3
        assert progress.overall_progress_percentage == 50.0  # 150/300
