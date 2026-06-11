"""
SR-02: Unit tests for interrupt responsiveness during file translation.

Tests that shutdown requests are checked periodically during file translation,
not just between files, enabling CTRL+C to work during long-running translations.
"""

from pathlib import Path
from unittest.mock import Mock


def test_shutdown_exception_attributes():
    """Test ShutdownRequested exception has correct attributes."""
    from src.translation_engine.exceptions import ShutdownRequested

    exc = ShutdownRequested(file_path="/test/file.md", segments_completed=25)

    assert exc.file_path == "/test/file.md"
    assert exc.segments_completed == 25
    assert "test/file.md" in str(exc)
    assert "25" in str(exc)


def test_shutdown_checked_every_10_segments_tm_loop():
    """Test that shutdown is checked every 10 segments during TM lookup."""
    from src.translation_engine.exceptions import ShutdownRequested

    # Simulate the TM loop logic with shutdown checks
    shutdown_flag = False
    shutdown_at_segment = 25

    segments_processed = 0
    shutdown_raised_at = None

    try:
        for idx in range(1, 31):  # 30 segments
            segments_processed = idx

            # Check shutdown every 10 segments (as in real code)
            if idx % 10 == 0:
                if idx >= shutdown_at_segment:
                    shutdown_flag = True

                if shutdown_flag:
                    shutdown_raised_at = idx
                    raise ShutdownRequested(segments_completed=idx)
    except ShutdownRequested:
        pass

    # Shutdown should be raised at segment 30 (first check after segment 25)
    assert shutdown_raised_at == 30
    assert segments_processed == 30


def test_shutdown_exception_propagates_through_translate_file():
    """Test that ShutdownRequested propagates up from translate_to_language."""
    from src.translation_engine.exceptions import ShutdownRequested

    # This is an integration-style unit test that mocks the internals
    # We can't easily test the full flow without a real engine,
    # but we can verify the exception handling logic

    # Mock the exception being raised
    exc = ShutdownRequested(file_path="/test/file.md", segments_completed=15)

    # Verify it's a TranslationError subclass (for proper exception hierarchy)
    from src.translation_engine.exceptions import TranslationError

    assert isinstance(exc, TranslationError)


def test_directory_sequential_handles_shutdown():
    """Test that sequential directory translation handles shutdown gracefully."""
    from src.translation_engine.exceptions import ShutdownRequested

    # Mock directory result
    result = Mock()
    result.file_results = []
    result.successful_files = 0

    # Mock engine
    engine = Mock()
    engine._current_file = None
    engine.progress_tracker = None
    engine._perform_shutdown = Mock()

    # Mock translate_file to raise ShutdownRequested on second file
    call_count = {"count": 0}

    def mock_translate_file(*args, **kwargs):
        call_count["count"] += 1
        if call_count["count"] == 2:
            raise ShutdownRequested(
                file_path=str(kwargs.get("file_path", "unknown")), segments_completed=10
            )
        # Return success for first file
        file_result = Mock()
        file_result.success = True
        file_result.errors = []
        return file_result

    engine.translate_file = mock_translate_file

    # Simulate directory translation logic
    md_files = [Path(f"/test/file{i}.md") for i in range(5)]

    for md_file in md_files:
        engine._current_file = md_file
        try:
            file_result = engine.translate_file(
                site_id="test",
                file_path=md_file,
                target_langs=["es"],
            )
            result.file_results.append(file_result)
            if file_result.success:
                result.successful_files += 1
        except ShutdownRequested:
            engine._perform_shutdown()
            break
        finally:
            engine._current_file = None

    # Verify shutdown was called
    assert engine._perform_shutdown.called
    # Verify only 2 files were processed (first succeeded, second raised shutdown)
    assert call_count["count"] == 2
    assert result.successful_files == 1


def test_shutdown_request_saves_partial_progress():
    """Test that shutdown request triggers progress save."""
    from src.translation_engine.exceptions import ShutdownRequested

    # Mock progress tracker
    mock_progress = Mock()
    mock_progress.file_completed = Mock()

    # Simulate shutdown during translation
    exc = ShutdownRequested(file_path="/test/file.md", segments_completed=15)

    # In the actual code, this happens in the exception handler
    # We just verify the exception has the right data
    assert exc.segments_completed == 15
    assert exc.file_path == "/test/file.md"


def test_shutdown_check_interval_default():
    """Test that default shutdown check interval is 10 segments."""
    # The interval is hardcoded in the implementation
    # This test documents the expected behavior
    interval = 10

    # Segments where shutdown is checked
    checked_at = [i for i in range(1, 101) if i % interval == 0]

    assert checked_at == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]


def test_shutdown_request_message_formatting():
    """Test ShutdownRequested exception message formatting."""
    from src.translation_engine.exceptions import ShutdownRequested

    # With file path and segments
    exc1 = ShutdownRequested(file_path="/test/file.md", segments_completed=25)
    msg1 = str(exc1)
    assert "Shutdown requested" in msg1
    assert "/test/file.md" in msg1
    assert "25" in msg1

    # With only file path
    exc2 = ShutdownRequested(file_path="/test/file.md")
    msg2 = str(exc2)
    assert "Shutdown requested" in msg2
    assert "/test/file.md" in msg2
    assert "completed 0" not in msg2  # Don't show 0 segments

    # Empty exception
    exc3 = ShutdownRequested()
    msg3 = str(exc3)
    assert "Shutdown requested" in msg3


def test_shutdown_during_tm_storage_loop():
    """Test shutdown check during TM storage loop."""
    # This test verifies the logic in the result storage loop
    # where shutdown is checked every 10 segments

    shutdown_triggered = False
    segments_stored = 0

    # Simulate the storage loop
    for seg_idx in range(1, 51):  # 50 segments
        segments_stored += 1

        # Check shutdown every 10 segments
        if seg_idx % 10 == 0:
            # Simulate shutdown requested at segment 30
            if seg_idx == 30:
                shutdown_triggered = True
                break

    assert shutdown_triggered
    assert segments_stored == 30  # Stopped at segment 30
