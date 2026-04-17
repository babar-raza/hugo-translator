"""
RES-10: Integration tests for translation resilience system.

These tests verify the complete resilience system at the component level,
testing that all resilience features work together correctly without
requiring full model loading.
"""

import json
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

# Add src directory to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


class TestAtomicWriteIntegration:
    """Test atomic write integration with error handling."""

    def test_atomic_write_creates_file_safely(self, tmp_path):
        """Test atomic write creates file with full error handling."""
        from utils.atomic_write import atomic_write

        file_path = tmp_path / "test.txt"
        content = "Test content for atomic write"

        atomic_write(file_path, content)

        assert file_path.exists()
        assert file_path.read_text() == content

    def test_atomic_write_creates_parent_directories(self, tmp_path):
        """Test atomic write creates nested parent directories."""
        from utils.atomic_write import atomic_write

        file_path = tmp_path / "nested" / "deep" / "test.txt"
        content = "Nested content"

        atomic_write(file_path, content, create_parents=True)

        assert file_path.exists()
        assert file_path.read_text() == content

    def test_atomic_write_overwrites_safely(self, tmp_path):
        """Test atomic write overwrites existing file safely."""
        from utils.atomic_write import atomic_write

        file_path = tmp_path / "test.txt"

        # Write initial content
        atomic_write(file_path, "Initial content")

        # Overwrite
        atomic_write(file_path, "Updated content")

        assert file_path.read_text() == "Updated content"


class TestFileLockIntegration:
    """Test file lock integration with concurrent access."""

    def test_lock_prevents_concurrent_access(self, tmp_path):
        """Test lock prevents concurrent access from multiple instances."""
        from utils.file_lock import FileLock, LockError

        lock_file = tmp_path / "test.lock"

        lock1 = FileLock(lock_file, timeout=1.0)
        lock2 = FileLock(lock_file, timeout=1.0)

        # First lock should succeed
        assert lock1.acquire() is True

        # Second lock should fail
        with pytest.raises(LockError):
            lock2.acquire()

        lock1.release()

    def test_lock_context_manager(self, tmp_path):
        """Test lock works as context manager."""
        from utils.file_lock import FileLock

        lock_file = tmp_path / "test.lock"

        with FileLock(lock_file) as lock:
            assert lock._locked
            assert lock_file.exists()

        assert not lock._locked

    def test_lock_acquired_after_release(self, tmp_path):
        """Test lock can be acquired after release."""
        from utils.file_lock import FileLock

        lock_file = tmp_path / "test.lock"

        lock1 = FileLock(lock_file)
        lock1.acquire()
        lock1.release()

        # Should be able to acquire again
        lock2 = FileLock(lock_file)
        assert lock2.acquire() is True
        lock2.release()


class TestProgressTrackerIntegration:
    """Test progress tracker with validation and recovery."""

    def test_progress_tracker_save_and_load(self, tmp_path):
        """Test progress tracker saves and loads correctly."""
        # Import directly to avoid package issues
        import importlib.util
        progress_path = src_path / "translation_engine" / "progress.py"
        spec = importlib.util.spec_from_file_location("progress_module", progress_path)
        progress_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(progress_module)
        ProgressTracker = progress_module.ProgressTracker

        progress_dir = tmp_path / "progress"
        progress_dir.mkdir(parents=True, exist_ok=True)
        source_dir = tmp_path / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        # Create tracker and mark some files complete
        tracker = ProgressTracker(
            site_id="test-site",
            source_dir=source_dir,
            output_dir=tmp_path / "output",
            target_langs=["es", "fr"],
            progress_dir=progress_dir,
        )
        tracker.state.total_files = 5
        tracker.mark_completed("file1.md", "es")
        tracker.mark_completed("file1.md", "fr")
        # Note: mark_completed auto-saves via _save_state()

        # Verify file exists and has correct content
        progress_file = tracker.progress_file
        assert progress_file.exists()
        data = json.loads(progress_file.read_text())
        assert data["site_id"] == "test-site"
        assert "file1.md" in data["completed_files"]

    def test_progress_validation_detects_invalid(self, tmp_path):
        """Test validation detects invalid progress files."""
        import importlib.util
        progress_path = src_path / "translation_engine" / "progress.py"
        spec = importlib.util.spec_from_file_location("progress_module", progress_path)
        progress_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(progress_module)
        ProgressTracker = progress_module.ProgressTracker

        # Create invalid progress file
        progress_file = tmp_path / "invalid_progress.json"
        progress_file.write_text("{invalid json")

        is_valid, msg, recoverable = ProgressTracker.validate_progress_file(progress_file)

        assert is_valid is False
        assert "Invalid JSON" in msg

    def test_progress_recovery_works(self, tmp_path):
        """Test progress recovery from partial data."""
        import importlib.util
        progress_path = src_path / "translation_engine" / "progress.py"
        spec = importlib.util.spec_from_file_location("progress_module", progress_path)
        progress_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(progress_module)
        ProgressTracker = progress_module.ProgressTracker

        # Create recoverable progress file (missing some fields)
        progress_file = tmp_path / "partial_progress.json"
        progress_file.write_text(json.dumps({
            "run_id": "test-run",
            "site_id": "mysite",
            "completed_files": {"file1.md": ["es"]},
            "total_files": 2,
        }))

        tracker = ProgressTracker.recover_progress_file(progress_file)

        assert tracker is not None
        assert tracker.state.site_id == "mysite"
        assert "file1.md" in tracker.state.completed_files


class TestErrorHandlingIntegration:
    """Test error handling across components."""

    def test_disk_full_error_propagates(self, tmp_path):
        """Test disk full error propagates correctly."""
        import errno

        from utils.atomic_write import DiskFullError, atomic_write

        file_path = tmp_path / "test.txt"

        # Mock tempfile.mkstemp to simulate disk full
        with mock.patch('tempfile.mkstemp') as mock_mkstemp:
            mock_mkstemp.side_effect = OSError(errno.ENOSPC, "No space")

            with pytest.raises(DiskFullError):
                atomic_write(file_path, "content")

    def test_invalid_path_error_propagates(self, tmp_path):
        """Test invalid path error propagates correctly."""
        import errno

        from utils.atomic_write import InvalidPathError, atomic_write

        file_path = tmp_path / "test.txt"

        with mock.patch('tempfile.mkstemp') as mock_mkstemp:
            mock_mkstemp.side_effect = OSError(errno.ENAMETOOLONG, "Name too long")

            with pytest.raises(InvalidPathError):
                atomic_write(file_path, "content")


class TestComponentIntegration:
    """Test multiple components working together."""

    def test_atomic_write_with_lock(self, tmp_path):
        """Test atomic write protected by file lock."""
        from utils.atomic_write import atomic_write
        from utils.file_lock import FileLock

        lock_file = tmp_path / "write.lock"
        output_file = tmp_path / "output.txt"

        with FileLock(lock_file):
            atomic_write(output_file, "Protected content")

        assert output_file.exists()
        assert output_file.read_text() == "Protected content"

    def test_progress_with_lock(self, tmp_path):
        """Test progress tracking with file lock."""
        import importlib.util
        progress_path = src_path / "translation_engine" / "progress.py"
        spec = importlib.util.spec_from_file_location("progress_module", progress_path)
        progress_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(progress_module)
        ProgressTracker = progress_module.ProgressTracker

        from utils.file_lock import FileLock

        lock_file = tmp_path / "progress.lock"
        progress_dir = tmp_path / "progress"
        progress_dir.mkdir(parents=True, exist_ok=True)
        source_dir = tmp_path / "src"
        source_dir.mkdir(parents=True, exist_ok=True)

        with FileLock(lock_file):
            tracker = ProgressTracker(
                site_id="test",
                source_dir=source_dir,
                output_dir=tmp_path / "out",
                target_langs=["es"],
                progress_dir=progress_dir,
            )
            tracker.state.total_files = 1
            tracker.mark_completed("file.md", "es")
            # Note: mark_completed auto-saves via _save_state()

        # Verify after lock released
        assert tracker.progress_file.exists()


class TestThreadSafetyIntegration:
    """Test thread safety of resilience components."""

    def test_concurrent_atomic_writes(self, tmp_path):
        """Test multiple concurrent atomic writes don't corrupt."""
        from utils.atomic_write import atomic_write

        results = []
        errors = []

        def writer(idx):
            try:
                file_path = tmp_path / f"file_{idx}.txt"
                content = f"Content from writer {idx}"
                atomic_write(file_path, content)
                results.append((idx, True))
            except Exception as e:
                errors.append((idx, str(e)))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # All writes should succeed
        assert len(results) == 5
        assert len(errors) == 0

        # Verify files
        for i in range(5):
            file_path = tmp_path / f"file_{i}.txt"
            assert file_path.exists()
            assert file_path.read_text() == f"Content from writer {i}"


class TestModulesExist:
    """Verify all resilience modules exist and have required components."""

    def test_atomic_write_module(self):
        """Verify atomic_write module exists with required classes."""
        atomic_path = src_path / "utils" / "atomic_write.py"
        assert atomic_path.exists()

        content = atomic_path.read_text()
        assert "def atomic_write" in content
        assert "class AtomicWriteError" in content
        assert "class DiskFullError" in content
        assert "class InvalidPathError" in content
        assert "class ReadOnlyFilesystemError" in content
        assert "RES-09" in content

    def test_file_lock_module(self):
        """Verify file_lock module exists with required classes."""
        lock_path = src_path / "utils" / "file_lock.py"
        assert lock_path.exists()

        content = lock_path.read_text()
        assert "class FileLock" in content
        assert "class LockError" in content
        assert "def acquire" in content
        assert "def release" in content
        assert "RES-08" in content

    def test_progress_module(self):
        """Verify progress module has validation and recovery."""
        progress_path = src_path / "translation_engine" / "progress.py"
        assert progress_path.exists()

        content = progress_path.read_text()
        assert "class ProgressTracker" in content
        assert "def validate_progress_file" in content
        assert "def recover_progress_file" in content
        assert "RES-07" in content

    def test_engine_integration(self):
        """Verify engine.py integrates with resilience features."""
        engine_path = src_path / "translation_engine" / "engine.py"
        assert engine_path.exists()

        content = engine_path.read_text()

        # Check imports
        assert "from ..utils.atomic_write import" in content
        assert "from ..utils.file_lock import" in content

        # Check RES feature markers
        assert "RES-06" in content  # Graceful shutdown
        assert "RES-08" in content  # File locking
        assert "RES-09" in content  # Error handling

    def test_cli_integration(self):
        """Verify cli.py integrates with resilience features."""
        cli_path = src_path / "cli.py"
        assert cli_path.exists()

        content = cli_path.read_text()

        # Check RES feature markers
        assert "RES-06" in content  # Signal handlers
        assert "RES-07" in content  # Progress validation


class TestResilienceSystemComplete:
    """Verify the complete resilience system is in place."""

    def test_all_res_features_implemented(self):
        """Verify all RES features have been implemented."""
        # Check for RES markers in appropriate files
        checks = [
            (src_path / "utils" / "atomic_write.py", ["RES-03", "RES-09"]),
            (src_path / "utils" / "file_lock.py", ["RES-08"]),
            (src_path / "translation_engine" / "progress.py", ["RES-07"]),
            (src_path / "translation_engine" / "engine.py", ["RES-05", "RES-06", "RES-08", "RES-09"]),
            (src_path / "cli.py", ["RES-02", "RES-06", "RES-07"]),
        ]

        missing = []

        for file_path, markers in checks:
            if not file_path.exists():
                missing.append(f"{file_path} does not exist")
                continue

            content = file_path.read_text()
            for marker in markers:
                if marker not in content:
                    missing.append(f"{marker} not found in {file_path.name}")

        if missing:
            pytest.fail("Missing implementations:\n" + "\n".join(missing))
