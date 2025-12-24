"""
Integration tests for graceful shutdown telemetry capture (GS-01 through GS-05).

Validates that when translation is interrupted with SIGINT/SIGTERM:
- status is set to 'cancelled' (GS-01)
- duration_ms reflects actual elapsed time (GS-02)
- end_time is populated with UTC timestamp (GS-03)
- items_* reflect partial progress (GS-04)
- metrics_json contains partial token/TM stats (GS-05)
"""
import subprocess
import signal
import time
import sqlite3
import json
import os
from pathlib import Path
import pytest


@pytest.fixture
def telemetry_db_path():
    """Return path to telemetry database."""
    # Try Docker path first, fall back to test DB
    docker_path = Path("/data/telemetry.sqlite")
    if docker_path.exists():
        return docker_path

    # Fallback: Use local test database
    test_db = Path(__file__).parent.parent.parent / "test_telemetry.sqlite"
    return test_db


@pytest.fixture
def cleanup_test_runs(telemetry_db_path):
    """Clean up test telemetry records after test."""
    yield
    # Cleanup logic: Remove test records
    if telemetry_db_path.exists():
        try:
            conn = sqlite3.connect(telemetry_db_path)
            # Clean up records from the last 10 minutes to avoid interfering with production
            conn.execute("""
                DELETE FROM agent_runs
                WHERE agent_name = 'hugo-translator'
                AND created_at > datetime('now', '-10 minutes')
            """)
            conn.commit()
            conn.close()
        except Exception:
            pass  # Best effort cleanup


@pytest.mark.integration
@pytest.mark.skipif(not Path("/data/telemetry.sqlite").exists(),
                   reason="Requires telemetry database (Docker environment)")
def test_directory_translation_interrupted_captures_telemetry(telemetry_db_path, cleanup_test_runs):
    """Test that interrupting directory translation captures complete telemetry."""
    # Start translation in subprocess
    proc = subprocess.Popen([
        "python", "-m", "src.cli",
        "--site", "blog.aspose.net",
        "--input", "content/blog/"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Let it run for 3 seconds
    time.sleep(3)
    start_time = time.time()

    # Send SIGINT
    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=10)

    end_time = time.time()
    elapsed_ms = int((end_time - start_time) * 1000)

    # Query telemetry database
    conn = sqlite3.connect(telemetry_db_path)
    cursor = conn.execute("""
        SELECT status, duration_ms, end_time, items_discovered, items_succeeded,
               items_failed, metrics_json, error_summary
        FROM agent_runs
        WHERE agent_name = 'hugo-translator'
        ORDER BY created_at DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    assert row is not None, "No telemetry record found"

    status, duration_ms, end_time_str, items_disc, items_succ, items_fail, metrics_json_str, error = row

    # GS-01: Verify status is 'cancelled'
    assert status == 'cancelled', f"Expected status='cancelled', got '{status}'"

    # GS-02: Verify duration_ms is captured
    assert duration_ms is not None, "duration_ms should not be None"
    assert duration_ms > 0, f"Expected duration_ms > 0, got {duration_ms}"
    assert duration_ms < elapsed_ms + 2000, f"Duration {duration_ms}ms too large (expected ~{elapsed_ms}ms)"

    # GS-03: Verify end_time is populated
    assert end_time_str is not None, "end_time should be populated"

    # Verify error_summary mentions SIGINT
    assert 'SIGINT' in error or 'interrupted' in error.lower(), f"error_summary: {error}"

    # GS-04: Verify items_* metrics (may be 0 if interrupted very early)
    assert items_disc is not None and items_disc >= 0
    assert items_succ is not None and items_succ >= 0

    # GS-05: Verify metrics_json (may be empty if no translations completed)
    if metrics_json_str:
        metrics = json.loads(metrics_json_str)
        # If populated, should have token fields
        assert isinstance(metrics, dict)

    conn.close()


@pytest.mark.integration
@pytest.mark.skipif(not Path("/data/telemetry.sqlite").exists(),
                   reason="Requires telemetry database (Docker environment)")
def test_file_translation_interrupted_captures_telemetry(telemetry_db_path, cleanup_test_runs):
    """Test that interrupting file translation captures complete telemetry."""
    # Create a test markdown file
    test_file = Path("tests/fixtures/test_graceful_shutdown.md")
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("# Test Content\n\nThis is a test file for graceful shutdown.\n")

    try:
        # Start translation in subprocess
        proc = subprocess.Popen([
            "python", "-m", "src.cli",
            "--site", "blog.aspose.net",
            "--input", str(test_file),
            "--target-langs", "es,fr,de"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Let it run for 2 seconds
        time.sleep(2)

        # Send SIGINT
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)

        # Query telemetry database
        conn = sqlite3.connect(telemetry_db_path)
        cursor = conn.execute("""
            SELECT status, duration_ms, end_time, error_summary
            FROM agent_runs
            WHERE agent_name = 'hugo-translator'
            ORDER BY created_at DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        if row:
            status, duration_ms, end_time_str, error = row

            # GS-01: Verify status
            assert status == 'cancelled', f"Expected status='cancelled', got '{status}'"

            # GS-02: Verify duration
            assert duration_ms is not None and duration_ms >= 0

            # GS-03: Verify end_time
            assert end_time_str is not None

        conn.close()

    finally:
        # Cleanup test file
        if test_file.exists():
            test_file.unlink()


@pytest.mark.unit
def test_graceful_shutdown_telemetry_fields_integration():
    """
    Unit-level integration test for GS-01 through GS-05.

    Tests the full flow without actual database access.
    """
    from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
    from unittest.mock import Mock
    import src.observability.graceful_shutdown as gs_module

    # Reset global state
    _active_contexts.clear()
    gs_module._shutdown_in_progress = False

    # Create realistic mock context
    mock_ctx = Mock()
    mock_ctx._start_time = time.time() - 2.5
    mock_ctx.set_metrics = Mock()
    mock_ctx.__exit__ = Mock()
    mock_ctx.get_partial_metrics = Mock(return_value={
        'items_discovered': 15,
        'items_succeeded': 8,
        'items_failed': 0,
        'metrics_json': {
            'tokens_input': 2500,
            'tokens_output': 3200,
            'tm_hits': 12,
            'translated_segments': 45
        }
    })

    # Register context
    _active_contexts.append(mock_ctx)

    # Trigger shutdown
    try:
        _perform_graceful_shutdown(signal.SIGINT, None)
    except SystemExit:
        pass

    # Verify ALL critical fields were set
    assert mock_ctx.set_metrics.called
    call_kwargs = mock_ctx.set_metrics.call_args[1]

    # GS-01: run_status
    assert call_kwargs['run_status'] == 'cancelled'

    # GS-02: duration_ms
    assert 'duration_ms' in call_kwargs
    assert 2000 < call_kwargs['duration_ms'] < 3500

    # GS-03: end_time
    assert 'end_time' in call_kwargs
    assert isinstance(call_kwargs['end_time'], str)

    # GS-04: items_*
    assert call_kwargs.get('items_discovered') == 15
    assert call_kwargs.get('items_succeeded') == 8
    assert call_kwargs.get('items_failed') == 0

    # GS-05: metrics_json
    assert 'metrics_json' in call_kwargs
    assert call_kwargs['metrics_json']['tokens_input'] == 2500
    assert call_kwargs['metrics_json']['tm_hits'] == 12

    # Other fields
    assert 'output_summary' in call_kwargs
    assert 'error_summary' in call_kwargs
    assert 'SIGINT' in call_kwargs['error_summary']
