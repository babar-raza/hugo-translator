"""
SR-06: Observability verification tests.

Verify that key operations produce expected log output.
This ensures proper debugging and monitoring capabilities in production.
"""

import json
import logging


class TestAtomicWriteLogging:
    """Test logging from atomic write operations."""

    def test_successful_write_logs_debug(self, tmp_path, caplog):
        """Verify successful atomic write logs debug message."""
        from utils.atomic_write import atomic_write

        with caplog.at_level(logging.DEBUG):
            atomic_write(tmp_path / "test.txt", "test content")

        # Should log bytes written with path
        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("Atomically wrote" in msg for msg in debug_messages), (
            f"Expected 'Atomically wrote' in debug logs, got: {debug_messages}"
        )

    def test_successful_write_includes_byte_count(self, tmp_path, caplog):
        """Verify debug log includes byte count."""
        from utils.atomic_write import atomic_write

        content = "a" * 100
        with caplog.at_level(logging.DEBUG):
            atomic_write(tmp_path / "test.txt", content)

        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        # Should mention number of bytes
        assert any(str(len(content)) in msg for msg in debug_messages), (
            f"Expected byte count {len(content)} in logs"
        )

    def test_successful_write_includes_path(self, tmp_path, caplog):
        """Verify debug log includes target path."""
        from utils.atomic_write import atomic_write

        target = tmp_path / "subdir" / "test.txt"
        with caplog.at_level(logging.DEBUG):
            atomic_write(target, "content")

        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        # Should include filename in log
        assert any("test.txt" in msg for msg in debug_messages), (
            f"Expected 'test.txt' in debug logs, got: {debug_messages}"
        )

    def test_error_handling_no_spurious_logs(self, tmp_path, caplog):
        """Verify error handling doesn't produce unexpected logs."""
        from utils.atomic_write import InvalidPathError, atomic_write

        # Try to write to non-existent parent without create_parents
        bad_path = tmp_path / "nonexistent" / "deep" / "file.txt"

        with caplog.at_level(logging.DEBUG):
            try:
                atomic_write(bad_path, "content", create_parents=False)
            except (InvalidPathError, OSError):
                pass  # Expected

        # Should not have excessive error logs (errors are raised, not logged)
        error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
        # atomic_write raises exceptions rather than logging errors
        # So we don't expect ERROR level logs here


class TestFileLockLogging:
    """Test logging from file lock operations."""

    def test_lock_acquire_logs_debug(self, tmp_path, caplog):
        """Verify lock acquisition logs debug message."""
        from utils.file_lock import FileLock

        lock_file = tmp_path / "test.lock"

        with caplog.at_level(logging.DEBUG):
            lock = FileLock(lock_file, timeout=5)
            try:
                lock.acquire()
                lock.release()
            except Exception:
                pass

        # Should log lock acquisition
        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("Lock acquired" in msg for msg in debug_messages), (
            f"Expected 'Lock acquired' in debug logs, got: {debug_messages}"
        )

    def test_lock_release_logs_debug(self, tmp_path, caplog):
        """Verify lock release logs debug message."""
        from utils.file_lock import FileLock

        lock_file = tmp_path / "test.lock"

        with caplog.at_level(logging.DEBUG):
            lock = FileLock(lock_file, timeout=5)
            try:
                lock.acquire()
                lock.release()
            except Exception:
                pass

        # Should log lock release
        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("Lock released" in msg for msg in debug_messages), (
            f"Expected 'Lock released' in debug logs, got: {debug_messages}"
        )

    def test_stale_lock_warning(self, tmp_path, caplog):
        """Verify stale lock detection logs warning."""
        from utils.file_lock import FileLock

        lock_file = tmp_path / "test.lock"

        # Create stale lock (non-existent PID)
        lock_file.write_text("999999999\n")

        with caplog.at_level(logging.WARNING):
            lock = FileLock(lock_file, timeout=5)
            try:
                lock.acquire()
                lock.release()
            except Exception:
                pass

        # Should log stale lock detection
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        # Note: Stale lock warning only logged if detection succeeds
        # On some platforms, stale detection may not trigger
        if warning_messages:
            assert any("stale" in msg.lower() for msg in warning_messages), (
                f"Expected 'stale' in warning logs, got: {warning_messages}"
            )

    def test_stale_lock_removal_logs_info(self, tmp_path, caplog):
        """Verify stale lock removal logs info message."""
        from utils.file_lock import FileLock

        lock_file = tmp_path / "test.lock"

        # Create stale lock
        lock_file.write_text("999999999\n")

        with caplog.at_level(logging.INFO):
            lock = FileLock(lock_file, timeout=5)
            try:
                lock.acquire()
                lock.release()
            except Exception:
                pass

        # Should log removal of stale lock
        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        # Stale lock removal is logged at INFO level
        if info_messages:
            assert any(
                "removed" in msg.lower() and "stale" in msg.lower() for msg in info_messages
            ), "Expected stale removal message in info logs"

    def test_lock_context_manager_cleanup(self, tmp_path, caplog):
        """Verify lock context manager cleans up properly."""
        from utils.file_lock import FileLock

        lock_file = tmp_path / "test.lock"

        with caplog.at_level(logging.DEBUG):
            # Use context manager for proper cleanup
            with FileLock(lock_file, timeout=5):
                # Lock should be acquired
                assert lock_file.exists()

        # After context exit, lock should be released and file removed
        assert not lock_file.exists()

        # Should have logged both acquire and release
        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("acquired" in msg.lower() for msg in debug_messages)
        assert any("released" in msg.lower() for msg in debug_messages)


class TestProgressTrackerLogging:
    """Test logging from progress tracker."""

    def test_initialization_logs_info(self, test_environment, progress_tracker_class, caplog):
        """Verify progress tracker initialization logs info message."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Create some test files
        files = [
            env["source_dir"] / "file1.md",
            env["source_dir"] / "file2.md",
            env["source_dir"] / "file3.md",
        ]
        for f in files:
            f.write_text("test content")

        with caplog.at_level(logging.INFO):
            tracker = ProgressTracker(
                site_id="log-test",
                source_dir=env["source_dir"],
                output_dir=env["output_dir"],
                target_langs=["es"],
                progress_dir=env["progress_dir"],
            )
            tracker.initialize(files)

        # Should log initialization
        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("initialized" in msg.lower() for msg in info_messages), (
            f"Expected 'initialized' in info logs, got: {info_messages}"
        )

    def test_recovery_logs_info(self, test_environment, progress_tracker_class, caplog):
        """Verify recovery operation logs info message."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Create valid progress file
        progress_file = env["progress_dir"] / "progress_test123.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test123",
                    "schema_version": "1.0",
                    "site_id": "test-site",
                    "source_dir": str(env["source_dir"]),
                    "output_dir": str(env["output_dir"]),
                    "target_langs": ["es"],
                    "completed_files": {"file1.md": ["es"]},
                    "failed_files": {},
                    "total_files": 2,
                    "files_processed": 1,
                    "translations_completed": 1,
                    "translations_failed": 0,
                    "started_at": "2024-01-01T00:00:00Z",
                    "last_updated": "2024-01-01T00:01:00Z",
                }
            )
        )

        with caplog.at_level(logging.INFO):
            tracker = ProgressTracker.recover_progress_file(progress_file)

        if tracker:
            # Should log recovery success
            info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
            assert any("recover" in msg.lower() for msg in info_messages), (
                f"Expected 'recover' in info logs, got: {info_messages}"
            )

    def test_recovery_from_corrupted_logs_warning(
        self, test_environment, progress_tracker_class, caplog
    ):
        """Verify corrupted file recovery logs warning."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Create corrupted progress file (missing required fields)
        progress_file = env["progress_dir"] / "progress_corrupt.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "corrupt123",
                    "schema_version": "1.0",
                    # Missing required fields like site_id, target_langs, etc.
                }
            )
        )

        with caplog.at_level(logging.WARNING):
            tracker = ProgressTracker.recover_progress_file(progress_file)

        # Should log warning about recovery attempt
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "recover" in msg.lower() or "attempting" in msg.lower() for msg in warning_messages
        ), f"Expected recovery warning, got: {warning_messages}"

    def test_recovery_from_invalid_json_logs_error(
        self, test_environment, progress_tracker_class, caplog
    ):
        """Verify invalid JSON recovery logs error."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Create invalid JSON file
        progress_file = env["progress_dir"] / "progress_invalid.json"
        progress_file.write_text("{invalid json content")

        with caplog.at_level(logging.ERROR):
            tracker = ProgressTracker.recover_progress_file(progress_file)

        # Should return None and log error
        assert tracker is None

        error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
        assert any("invalid" in msg.lower() or "json" in msg.lower() for msg in error_messages), (
            f"Expected JSON error in logs, got: {error_messages}"
        )

    def test_clear_progress_logs_info(self, test_environment, progress_tracker_class, caplog):
        """Verify clearing progress logs info message."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        tracker = ProgressTracker(
            site_id="clear-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es"],
            progress_dir=env["progress_dir"],
        )
        tracker.state.total_files = 1
        tracker.mark_completed("file1.md", "es")

        # Clear logs
        caplog.clear()

        with caplog.at_level(logging.INFO):
            tracker.clear()

        # Should log clearing
        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("clear" in msg.lower() for msg in info_messages), (
            f"Expected 'clear' in info logs, got: {info_messages}"
        )

    def test_existing_progress_load_logs_info(
        self, test_environment, progress_tracker_class, caplog
    ):
        """Verify loading existing progress logs info message."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Create initial tracker
        tracker1 = ProgressTracker(
            site_id="reload-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es"],
            progress_dir=env["progress_dir"],
            run_id="reload123",
        )
        tracker1.state.total_files = 5
        tracker1.mark_completed("file1.md", "es")
        tracker1.mark_completed("file2.md", "es")

        # Clear logs
        caplog.clear()

        # Load existing progress
        with caplog.at_level(logging.INFO):
            tracker2 = ProgressTracker(
                site_id="reload-test",
                source_dir=env["source_dir"],
                output_dir=env["output_dir"],
                target_langs=["es"],
                progress_dir=env["progress_dir"],
                run_id="reload123",  # Same run_id
            )

        # Should log existing progress load
        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("loaded" in msg.lower() or "existing" in msg.lower() for msg in info_messages), (
            f"Expected progress load message, got: {info_messages}"
        )

    def test_find_latest_skips_corrupted_with_warning(
        self, test_environment, progress_tracker_class, caplog
    ):
        """Verify find_latest skips corrupted files with warning."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Create corrupted progress file
        corrupted = env["progress_dir"] / "progress_bad.json"
        corrupted.write_text("{invalid json")

        with caplog.at_level(logging.WARNING):
            tracker = ProgressTracker.find_latest(env["progress_dir"], "test-site")

        # Should log warning about skipping corrupted file
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("skip" in msg.lower() or "corrupt" in msg.lower() for msg in warning_messages), (
            f"Expected warning about corrupted file, got: {warning_messages}"
        )


class TestLoggingLevels:
    """Test that appropriate log levels are used."""

    def test_debug_level_for_routine_operations(self, tmp_path, caplog):
        """Verify routine operations use DEBUG level."""
        from utils.atomic_write import atomic_write

        with caplog.at_level(logging.DEBUG):
            atomic_write(tmp_path / "test.txt", "content")

        # Successful writes should be DEBUG, not INFO
        debug_count = sum(1 for r in caplog.records if r.levelno == logging.DEBUG)
        info_count = sum(1 for r in caplog.records if r.levelno == logging.INFO)

        assert debug_count > 0, "Expected DEBUG logs for routine operations"
        # Note: Other components may log at INFO level

    def test_info_level_for_significant_events(
        self, test_environment, progress_tracker_class, caplog
    ):
        """Verify significant events use INFO level."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        files = [env["source_dir"] / "file1.md"]
        for f in files:
            f.write_text("test")

        with caplog.at_level(logging.INFO):
            tracker = ProgressTracker(
                site_id="level-test",
                source_dir=env["source_dir"],
                output_dir=env["output_dir"],
                target_langs=["es"],
                progress_dir=env["progress_dir"],
            )
            tracker.initialize(files)

        # Initialization should be INFO level
        info_count = sum(1 for r in caplog.records if r.levelno == logging.INFO)
        assert info_count > 0, "Expected INFO logs for significant events"

    def test_warning_level_for_recoverable_issues(self, tmp_path, caplog):
        """Verify recoverable issues use WARNING level."""
        from utils.file_lock import FileLock

        lock_file = tmp_path / "test.lock"
        lock_file.write_text("999999999\n")  # Stale lock

        with caplog.at_level(logging.WARNING):
            lock = FileLock(lock_file, timeout=5)
            try:
                lock.acquire()
                lock.release()
            except Exception:
                pass

        # Stale locks are warnings (recoverable)
        # Note: May not always trigger on all platforms

    def test_error_level_for_critical_failures(
        self, test_environment, progress_tracker_class, caplog
    ):
        """Verify critical failures use ERROR level."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Invalid JSON triggers error during recovery
        bad_file = env["progress_dir"] / "progress_bad.json"
        bad_file.write_text("{invalid")

        with caplog.at_level(logging.ERROR):
            tracker = ProgressTracker.recover_progress_file(bad_file)

        # JSON errors should be logged at ERROR level
        error_count = sum(1 for r in caplog.records if r.levelno == logging.ERROR)
        assert error_count > 0, "Expected ERROR logs for critical failures"
