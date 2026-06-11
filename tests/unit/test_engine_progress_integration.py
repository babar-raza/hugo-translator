"""Tests for progress tracker integration in translation engine."""

from pathlib import Path
from unittest.mock import Mock, patch


def test_engine_marks_completed_on_success():
    """Verify engine marks progress on successful translation."""
    from src.translation_engine import TranslationEngine
    from src.translation_engine.models import DirectoryResult, TranslationResult

    # Setup mocks
    mock_tracker = Mock()
    mock_config = Mock()
    mock_tm = Mock()
    mock_loader = Mock()

    engine = TranslationEngine(
        config_service=mock_config,
        tm=mock_tm,
        model_loader=mock_loader,
        progress_tracker=mock_tracker,
    )

    # Mock successful translation
    with patch.object(engine, "translate_file") as mock_translate:
        mock_translate.return_value = TranslationResult(
            success=True,
            source_file=Path("test.md"),
            outputs=[Path("output/es/test.md")],
        )

        # Create result object
        result = DirectoryResult(success=False, directory=Path("."))

        # Run sequential translation
        engine._translate_directory_sequential(
            site_id="test",
            md_files=[Path("test.md")],
            target_langs=["es", "fr"],
            result=result,
        )

    # Verify mark_completed called for each language
    assert mock_tracker.mark_completed.call_count == 2
    mock_tracker.mark_completed.assert_any_call(Path("test.md"), "es")
    mock_tracker.mark_completed.assert_any_call(Path("test.md"), "fr")


def test_engine_marks_failed_on_error():
    """Verify engine marks failures with error message."""
    from src.translation_engine import TranslationEngine
    from src.translation_engine.models import DirectoryResult, TranslationResult

    # Setup mocks
    mock_tracker = Mock()
    mock_config = Mock()
    mock_tm = Mock()
    mock_loader = Mock()

    engine = TranslationEngine(
        config_service=mock_config,
        tm=mock_tm,
        model_loader=mock_loader,
        progress_tracker=mock_tracker,
    )

    # Mock failed translation
    with patch.object(engine, "translate_file") as mock_translate:
        mock_translate.return_value = TranslationResult(
            success=False,
            source_file=Path("test.md"),
            errors=["Translation failed", "Model error"],
        )

        # Create result object
        result = DirectoryResult(success=False, directory=Path("."))

        # Run sequential translation
        engine._translate_directory_sequential(
            site_id="test",
            md_files=[Path("test.md")],
            target_langs=["es"],
            result=result,
        )

    # Verify mark_failed called with error message
    assert mock_tracker.mark_failed.call_count == 1
    mock_tracker.mark_failed.assert_called_once_with(
        Path("test.md"), "es", "Translation failed; Model error"
    )


def test_engine_marks_failed_on_exception():
    """Verify engine marks failures when exception is raised."""
    from src.translation_engine import TranslationEngine
    from src.translation_engine.models import DirectoryResult

    # Setup mocks
    mock_tracker = Mock()
    mock_config = Mock()
    mock_tm = Mock()
    mock_loader = Mock()

    engine = TranslationEngine(
        config_service=mock_config,
        tm=mock_tm,
        model_loader=mock_loader,
        progress_tracker=mock_tracker,
    )

    # Mock exception during translation
    with patch.object(engine, "translate_file") as mock_translate:
        mock_translate.side_effect = RuntimeError("Unexpected error")

        # Create result object
        result = DirectoryResult(success=False, directory=Path("."))

        # Run sequential translation
        engine._translate_directory_sequential(
            site_id="test",
            md_files=[Path("test.md")],
            target_langs=["es", "fr"],
            result=result,
        )

    # Verify mark_failed called for each language with exception message
    assert mock_tracker.mark_failed.call_count == 2
    mock_tracker.mark_failed.assert_any_call(Path("test.md"), "es", "Unexpected error")
    mock_tracker.mark_failed.assert_any_call(Path("test.md"), "fr", "Unexpected error")


def test_engine_handles_none_progress_tracker():
    """Verify engine works without progress tracker (backward compat)."""
    from src.translation_engine import TranslationEngine
    from src.translation_engine.models import DirectoryResult, TranslationResult

    # Setup mocks
    mock_config = Mock()
    mock_tm = Mock()
    mock_loader = Mock()

    # Create engine without progress_tracker (default None)
    engine = TranslationEngine(
        config_service=mock_config,
        tm=mock_tm,
        model_loader=mock_loader,
        # progress_tracker not specified - should default to None
    )

    # Verify it defaults to None
    assert engine.progress_tracker is None

    # Mock successful translation
    with patch.object(engine, "translate_file") as mock_translate:
        mock_translate.return_value = TranslationResult(
            success=True,
            source_file=Path("test.md"),
            outputs=[Path("output/es/test.md")],
        )

        # Create result object
        result = DirectoryResult(success=False, directory=Path("."))

        # Run sequential translation - should not raise exception
        engine._translate_directory_sequential(
            site_id="test",
            md_files=[Path("test.md")],
            target_langs=["es"],
            result=result,
        )

    # Verify successful_files incremented despite no progress tracker
    assert result.successful_files == 1


def test_engine_handles_mark_exception():
    """Verify engine continues if mark_completed throws exception."""
    from src.translation_engine import TranslationEngine
    from src.translation_engine.models import DirectoryResult, TranslationResult

    # Setup mocks
    mock_tracker = Mock()
    mock_tracker.mark_completed.side_effect = Exception("Progress save failed")
    mock_config = Mock()
    mock_tm = Mock()
    mock_loader = Mock()

    engine = TranslationEngine(
        config_service=mock_config,
        tm=mock_tm,
        model_loader=mock_loader,
        progress_tracker=mock_tracker,
    )

    # Mock successful translation
    with patch.object(engine, "translate_file") as mock_translate:
        mock_translate.return_value = TranslationResult(
            success=True,
            source_file=Path("test.md"),
            outputs=[Path("output/es/test.md")],
        )

        # Create result object
        result = DirectoryResult(success=False, directory=Path("."))

        # Run sequential translation - should not raise exception
        engine._translate_directory_sequential(
            site_id="test",
            md_files=[Path("test.md")],
            target_langs=["es"],
            result=result,
        )

    # Verify translation continued despite progress save failure
    assert result.successful_files == 1
    # Verify mark_completed was attempted
    assert mock_tracker.mark_completed.call_count >= 1


def test_engine_backward_compatible_no_param():
    """Verify engine can be created without progress_tracker parameter."""
    from src.translation_engine import TranslationEngine

    mock_config = Mock()
    mock_tm = Mock()
    mock_loader = Mock()

    # Create engine using old signature (no progress_tracker)
    engine = TranslationEngine(
        config_service=mock_config,
        tm=mock_tm,
        model_loader=mock_loader,
    )

    # Verify progress_tracker is None
    assert engine.progress_tracker is None
    assert hasattr(engine, "progress_tracker")
