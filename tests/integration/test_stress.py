"""
Stress tests for resilience components.

Higher concurrency and longer durations than standard tests.

SR-04: High-concurrency stress testing to expose race conditions and deadlocks.
"""
import threading
import time


class TestAtomicWriteStress:
    """Stress tests for atomic write operations."""

    def test_20_concurrent_writers_same_directory(self, tmp_path, atomic_write_module):
        """Test 20 concurrent writers to same directory."""
        atomic_write = atomic_write_module['atomic_write']

        errors = []
        successes = []

        def writer(writer_id):
            for iteration in range(10):
                try:
                    file_path = tmp_path / f"file_{writer_id}_{iteration}.txt"
                    content = f"Content from writer {writer_id}, iteration {iteration}"
                    atomic_write(file_path, content)
                    successes.append((writer_id, iteration))
                except Exception as e:
                    errors.append((writer_id, iteration, str(e)))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # All writes should succeed
        assert len(errors) == 0, f"Errors occurred: {errors[:5]}"
        assert len(successes) == 200

        # Verify all files exist and have correct content
        files = list(tmp_path.glob("*.txt"))
        assert len(files) == 200

        for f in files:
            content = f.read_text()
            assert content.startswith("Content from writer")

    def test_concurrent_writes_same_file(self, tmp_path, atomic_write_module):
        """Test multiple writers to same file handle contention gracefully.

        On Windows, concurrent atomic writes to the same file may fail with
        PermissionError due to file locking. This test verifies that:
        1. At least some writes succeed
        2. The final file has valid content
        3. Failures are handled cleanly (no crashes)
        """
        atomic_write = atomic_write_module['atomic_write']

        target_file = tmp_path / "shared.txt"
        write_count = [0]
        error_count = [0]
        lock = threading.Lock()

        def writer(writer_id):
            for i in range(5):
                try:
                    content = f"Writer {writer_id} iteration {i}"
                    atomic_write(target_file, content)
                    with lock:
                        write_count[0] += 1
                except PermissionError:
                    # Expected on Windows with concurrent writes to same file
                    with lock:
                        error_count[0] += 1
                time.sleep(0.001)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # File should exist with valid content from at least one write
        assert target_file.exists()
        content = target_file.read_text()
        assert content.startswith("Writer")

        # At least some writes should succeed (not all fail)
        assert write_count[0] > 0, "All writes failed - unexpected"

        # Total attempts should equal write + error counts
        assert write_count[0] + error_count[0] == 50


class TestFileLockStress:
    """Stress tests for file locking."""

    def test_lock_contention_20_threads(self, tmp_path, file_lock_class):
        """Test 20 threads competing for same lock."""
        FileLock = file_lock_class['FileLock']

        lock_file = tmp_path / "stress.lock"
        acquire_count = [0]
        release_count = [0]
        errors = []
        count_lock = threading.Lock()

        def worker(worker_id):
            lock = FileLock(lock_file, timeout=30)
            try:
                if lock.acquire(blocking=True):
                    with count_lock:
                        acquire_count[0] += 1

                    # Hold lock briefly
                    time.sleep(0.02)

                    lock.release()
                    with count_lock:
                        release_count[0] += 1
            except Exception as e:
                errors.append((worker_id, str(e)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]

        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        elapsed = time.time() - start

        # All should eventually acquire and release
        assert len(errors) == 0, f"Errors: {errors}"
        assert acquire_count[0] == 20
        assert release_count[0] == 20

        # Should complete in reasonable time
        assert elapsed < 60

        # Lock file cleaned up
        assert not lock_file.exists()


class TestProgressTrackerStress:
    """Stress tests for progress tracking."""

    def test_rapid_completion_marking(self, test_environment, progress_tracker_class):
        """Test rapid mark_completed calls."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        tracker = ProgressTracker(
            site_id="stress-test",
            source_dir=env['source_dir'],
            output_dir=env['output_dir'],
            target_langs=["es"],
            progress_dir=env['progress_dir'],
        )
        tracker.state.total_files = 100

        # Rapidly mark 100 files complete
        start = time.time()
        for i in range(100):
            tracker.mark_completed(f"file_{i}.md", "es")
        elapsed = time.time() - start

        # Should complete quickly (< 5 seconds for 100 files)
        assert elapsed < 5.0

        # All tracked correctly
        assert tracker.state.translations_completed == 100

        # File persisted correctly
        assert tracker.progress_file.exists()
        import json
        data = json.loads(tracker.progress_file.read_text())
        assert len(data["completed_files"]) == 100

    def test_concurrent_progress_updates(self, test_environment, progress_tracker_class):
        """Test concurrent mark_completed calls from multiple threads.

        Note: This test creates separate ProgressTracker instances per thread
        to avoid Windows file locking issues during concurrent writes.
        """
        ProgressTracker = progress_tracker_class
        env = test_environment

        errors = []
        successes = [0]
        lock = threading.Lock()

        def worker(worker_id):
            """Each worker creates its own tracker and marks 5 files complete in 2 languages."""
            try:
                # Create separate tracker per thread to avoid concurrent write conflicts
                tracker = ProgressTracker(
                    site_id=f"concurrent-stress-{worker_id}",
                    source_dir=env['source_dir'],
                    output_dir=env['output_dir'],
                    target_langs=["es", "fr"],
                    progress_dir=env['progress_dir'],
                )
                tracker.state.total_files = 5

                for i in range(5):
                    file_name = f"file_{worker_id}_{i}.md"
                    tracker.mark_completed(file_name, "es")
                    tracker.mark_completed(file_name, "fr")
                    with lock:
                        successes[0] += 2
            except Exception as e:
                errors.append((worker_id, str(e)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]

        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()  # Wait indefinitely for completion
        elapsed = time.time() - start

        # All updates should succeed
        assert len(errors) == 0, f"Errors: {errors}"
        assert successes[0] == 100

        # Should complete in reasonable time
        assert elapsed < 15.0

        # All progress files should exist (one per worker)
        progress_files = list(env['progress_dir'].glob("*.json"))
        assert len(progress_files) == 10
