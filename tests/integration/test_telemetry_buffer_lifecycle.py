"""
Integration tests for telemetry buffer file lifecycle.

Tests buffer file creation, rotation, and cleanup without network calls.
Verifies the .active → .ready → .synced state machine works correctly.

These tests replace the removed direct-DB tests (test_telemetry_pragma_settings.py,
test_telemetry_concurrent_access.py) with tests focused on the new HTTP API + buffer architecture.
"""

import json
import tempfile
import time
from pathlib import Path

import pytest

# Skip all tests if telemetry module not available
pytest.importorskip("telemetry", reason="telemetry module not installed")

from telemetry.buffer import BufferFile


class TestBufferFileCreation:
    """Tests for buffer file creation and initialization."""

    def test_creates_buffer_directory_if_not_exists(self):
        """Buffer directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer_dir = Path(tmpdir) / "nonexistent" / "buffer"
            assert not buffer_dir.exists()

            buffer = BufferFile(str(buffer_dir))

            assert buffer_dir.exists()
            assert buffer_dir.is_dir()

    def test_creates_active_file_on_init(self):
        """Creates .jsonl.active file on initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            active_files = list(Path(tmpdir).glob("*.jsonl.active"))
            assert len(active_files) == 1
            assert active_files[0].name.startswith("telemetry_")
            assert active_files[0].suffix == ".active"

    def test_reuses_existing_active_file(self):
        """Reuses existing .active file instead of creating new one."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create first buffer
            buffer1 = BufferFile(tmpdir)
            first_file = buffer1.current_file

            # Create second buffer (should reuse file)
            buffer2 = BufferFile(tmpdir)
            second_file = buffer2.current_file

            assert first_file == second_file
            # Should still only be one active file
            active_files = list(Path(tmpdir).glob("*.jsonl.active"))
            assert len(active_files) == 1

    def test_uses_most_recent_active_file_if_multiple(self):
        """Uses most recent .active file if multiple exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple active files manually
            old_file = Path(tmpdir) / "telemetry_old.jsonl.active"
            new_file = Path(tmpdir) / "telemetry_new.jsonl.active"

            old_file.touch()
            time.sleep(0.01)  # Ensure different mtimes
            new_file.touch()

            buffer = BufferFile(tmpdir)

            assert buffer.current_file == new_file


class TestBufferFileAppend:
    """Tests for appending events to buffer files."""

    def test_appends_event_as_json_line(self):
        """Events are appended as JSON lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            event = {"event_id": "test-123", "agent_name": "test", "status": "success"}
            buffer.append(event)

            # Read file contents
            with open(buffer.current_file) as f:
                line = f.readline()

            parsed = json.loads(line)
            assert parsed == event

    def test_appends_multiple_events(self):
        """Multiple events can be appended."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            events = [
                {"event_id": f"test-{i}", "agent_name": "test", "status": "success"}
                for i in range(5)
            ]

            for event in events:
                buffer.append(event)

            # Read all lines
            with open(buffer.current_file) as f:
                lines = f.readlines()

            assert len(lines) == 5
            for i, line in enumerate(lines):
                parsed = json.loads(line)
                assert parsed["event_id"] == f"test-{i}"

    def test_append_is_atomic(self):
        """Append operation is atomic (flush after write)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            event = {"event_id": "test-123", "data": "x" * 1000}
            buffer.append(event)

            # File should be readable immediately (flushed)
            with open(buffer.current_file) as f:
                line = f.readline()
                parsed = json.loads(line)
                assert parsed["event_id"] == "test-123"


class TestBufferFileRotation:
    """Tests for buffer file rotation (size and age thresholds)."""

    def test_rotates_when_size_exceeds_max(self):
        """File rotates when size exceeds max_size_mb."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use very small max size (1KB = 0.001MB)
            buffer = BufferFile(tmpdir, max_size_mb=0.001)

            first_file = buffer.current_file

            # Write enough data to exceed threshold
            large_event = {"event_id": "test-123", "data": "x" * 2000}  # ~2KB
            buffer.append(large_event)

            # Next append should trigger rotation
            buffer.append({"event_id": "test-124", "data": "small"})

            # Should have new active file
            assert buffer.current_file != first_file
            assert buffer.current_file.exists()
            assert buffer.current_file.suffix == ".active"

            # Old file should be .ready
            ready_files = list(Path(tmpdir).glob("*.jsonl.ready"))
            assert len(ready_files) == 1

    def test_rotates_when_age_exceeds_max(self):
        """File rotates when age exceeds max_age_hours."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use very short max age (1 second = 0.0002777 hours)
            buffer = BufferFile(tmpdir, max_age_hours=0.0002777)

            first_file = buffer.current_file
            buffer.append({"event_id": "test-123"})

            # Wait for age threshold
            time.sleep(1.5)

            # Next append should trigger rotation
            buffer.append({"event_id": "test-124"})

            # Should have new active file
            assert buffer.current_file != first_file

            # Old file should be .ready
            ready_files = list(Path(tmpdir).glob("*.jsonl.ready"))
            assert len(ready_files) == 1

    def test_rotation_is_atomic(self):
        """Rotation renames file atomically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir, max_size_mb=0.001)

            # Write to exceed threshold
            buffer.append({"event_id": "test-123", "data": "x" * 2000})
            buffer.append({"event_id": "test-124"})  # Triggers rotation

            # Old file should be complete and readable
            ready_files = list(Path(tmpdir).glob("*.jsonl.ready"))
            assert len(ready_files) == 1

            with open(ready_files[0]) as f:
                lines = f.readlines()

            assert len(lines) == 1  # First event
            parsed = json.loads(lines[0])
            assert parsed["event_id"] == "test-123"


class TestBufferFileStates:
    """Tests for buffer file state transitions (.active → .ready → .synced)."""

    def test_active_state_allows_append(self):
        """.active files can be appended to."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            assert buffer.current_file.suffix == ".active"

            buffer.append({"event_id": "test-1"})
            buffer.append({"event_id": "test-2"})

            with open(buffer.current_file) as f:
                lines = f.readlines()

            assert len(lines) == 2

    def test_ready_state_is_closed(self):
        """.ready files are closed (not actively written to)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir, max_size_mb=0.001)

            # Trigger rotation
            buffer.append({"event_id": "test-1", "data": "x" * 2000})
            buffer.append({"event_id": "test-2"})  # Rotates to .ready

            ready_files = list(Path(tmpdir).glob("*.jsonl.ready"))
            assert len(ready_files) == 1

            # Subsequent appends go to new .active file
            buffer.append({"event_id": "test-3"})

            with open(buffer.current_file) as f:
                lines = f.readlines()

            assert len(lines) == 2  # test-2 and test-3
            for line in lines:
                parsed = json.loads(line)
                assert parsed["event_id"] in ["test-2", "test-3"]

    def test_manual_synced_marking(self):
        """Files can be manually marked as .synced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a .ready file manually
            ready_file = Path(tmpdir) / "test.jsonl.ready"
            ready_file.write_text('{"event_id":"test-1"}\n')

            # Mark as synced
            synced_file = ready_file.with_suffix(".synced")
            ready_file.rename(synced_file)

            assert not ready_file.exists()
            assert synced_file.exists()
            assert synced_file.suffix == ".synced"


class TestBufferFileFailureModes:
    """Tests for buffer file error handling."""

    def test_handles_readonly_directory_gracefully(self):
        """Raises informative error when buffer directory is read-only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer_dir = Path(tmpdir) / "readonly"
            buffer_dir.mkdir()
            buffer = BufferFile(str(buffer_dir))

            # Make directory read-only
            buffer_dir.chmod(0o444)

            try:
                # Append should raise IOError
                with pytest.raises((IOError, OSError, PermissionError)):
                    buffer.append({"event_id": "test"})
            finally:
                # Restore permissions for cleanup
                buffer_dir.chmod(0o755)

    def test_creates_new_file_if_current_deleted(self):
        """Creates new .active file if current file is deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            first_file = buffer.current_file
            buffer.append({"event_id": "test-1"})

            # Delete current file
            first_file.unlink()

            # Next append should create new file
            buffer.append({"event_id": "test-2"})

            assert buffer.current_file != first_file
            assert buffer.current_file.exists()

    def test_handles_corrupted_json_gracefully(self):
        """Appending valid JSON after corruption doesn't affect new writes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            # Write corrupted JSON manually
            with open(buffer.current_file, "a") as f:
                f.write('{"invalid json\n')

            # Subsequent appends should still work
            buffer.append({"event_id": "test-1"})

            with open(buffer.current_file) as f:
                lines = f.readlines()

            # Should have both lines (corrupted + valid)
            assert len(lines) == 2
            # Second line should be valid
            parsed = json.loads(lines[1])
            assert parsed["event_id"] == "test-1"


class TestBufferFileFormat:
    """Tests for buffer file format (valid NDJSON)."""

    def test_output_is_valid_ndjson(self):
        """Output format is valid newline-delimited JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            events = [{"event_id": f"test-{i}", "value": i} for i in range(10)]

            for event in events:
                buffer.append(event)

            # Verify NDJSON format
            with open(buffer.current_file) as f:
                for i, line in enumerate(f):
                    parsed = json.loads(line)  # Should not raise
                    assert parsed["event_id"] == f"test-{i}"
                    assert parsed["value"] == i

    def test_each_line_is_complete_json_object(self):
        """Each line is a complete, parseable JSON object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            # Complex nested event
            event = {
                "event_id": "test-123",
                "metadata": {"nested": {"value": [1, 2, 3], "flag": True}},
                "text": 'Line with\nnewlines and "quotes"',
            }

            buffer.append(event)

            with open(buffer.current_file) as f:
                line = f.readline()

            # Line should not contain literal newlines (JSON-escaped)
            assert "\n" not in line.rstrip("\n")

            # Should parse correctly
            parsed = json.loads(line)
            assert parsed == event

    def test_no_trailing_commas_in_file(self):
        """File format has no trailing commas (valid NDJSON)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = BufferFile(tmpdir)

            for i in range(5):
                buffer.append({"event_id": f"test-{i}"})

            # Read entire file
            with open(buffer.current_file) as f:
                content = f.read()

            # Should not have trailing comma
            assert not content.rstrip().endswith(",")

            # Each line should be parseable independently
            for line in content.splitlines():
                if line.strip():
                    json.loads(line)  # Should not raise
