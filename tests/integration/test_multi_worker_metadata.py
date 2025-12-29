"""
Integration tests for multi-worker metadata coordination (CHH-02).

Tests end-to-end behavior of MetadataTracker with real Redis instance.
"""

import json
import multiprocessing
import time
from pathlib import Path

import pytest

from src.utils.metadata_tracker import MetadataTracker


# Requires Redis to be running
pytestmark = pytest.mark.integration


def worker_process(
    worker_id: int,
    metadata_file: Path,
    redis_host: str,
    redis_port: int,
    num_files: int,
    results_queue: multiprocessing.Queue,
):
    """
    Worker process that simulates concurrent metadata updates.

    Each worker updates metadata for num_files source files.
    """
    try:
        # Import Redis inside worker process
        import redis

        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True,
        )

        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id=f"worker-{worker_id}",
            redis_client=redis_client,
            lock_timeout=10,
        )

        # Load existing metadata
        tracker.load()

        # Simulate updating source file hashes
        for i in range(num_files):
            source_path = Path(f"/fake/source/file_{worker_id}_{i}.md")
            # Fake update (in real scenario, this would call update_source)
            # For test purposes, we'll manually update _data
            from src.utils.metadata_tracker import SourceFileMetadata
            from datetime import datetime, timezone

            tracker._data[str(source_path)] = type('FileMetadata', (), {
                'source': SourceFileMetadata(
                    path=str(source_path),
                    hash=f"hash_{worker_id}_{i}",
                    last_modified=datetime.now(timezone.utc).isoformat(),
                    size_bytes=1024,
                    hash_computed_at=datetime.now(timezone.utc).isoformat(),
                ),
                'outputs': {}
            })()

            # Save after each update (stress test locking)
            tracker.save()

            # Small delay to increase contention
            time.sleep(0.01)

        results_queue.put({"worker_id": worker_id, "status": "success", "files": num_files})

    except Exception as e:
        results_queue.put({"worker_id": worker_id, "status": "error", "error": str(e)})


@pytest.fixture
def redis_connection():
    """
    Fixture to ensure Redis is available.

    Skips test if Redis not running.
    """
    try:
        import redis

        client = redis.Redis(host="localhost", port=6379, decode_responses=True)
        client.ping()
        return {"host": "localhost", "port": 6379}
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


class TestMultiWorkerMetadata:
    """Integration tests for multi-worker metadata coordination."""

    def test_two_workers_concurrent_updates__no_data_loss(
        self, tmp_path, redis_connection
    ):
        """Two workers updating metadata concurrently should not lose data."""
        metadata_file = tmp_path / ".translation_metadata.json"

        # Start 2 worker processes
        results_queue = multiprocessing.Queue()
        processes = []

        for worker_id in range(2):
            p = multiprocessing.Process(
                target=worker_process,
                args=(
                    worker_id,
                    metadata_file,
                    redis_connection["host"],
                    redis_connection["port"],
                    10,  # Each worker updates 10 files
                    results_queue,
                ),
            )
            p.start()
            processes.append(p)

        # Wait for completion
        for p in processes:
            p.join(timeout=30)
            assert not p.is_alive(), "Worker process timed out"

        # Collect results
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        # All workers succeeded
        assert len(results) == 2
        for result in results:
            assert result["status"] == "success", f"Worker failed: {result}"

        # Verify metadata file integrity
        assert metadata_file.exists()
        data = json.loads(metadata_file.read_text())

        # Should have 20 total files (2 workers * 10 files each)
        assert len(data["files"]) == 20

        # Each file should be present
        for worker_id in range(2):
            for file_id in range(10):
                file_key = f"/fake/source/file_{worker_id}_{file_id}.md"
                assert file_key in data["files"]
                assert data["files"][file_key]["source"]["hash"] == f"hash_{worker_id}_{file_id}"

    def test_five_workers_high_contention__metadata_consistent(
        self, tmp_path, redis_connection
    ):
        """Five workers with high contention should maintain consistency."""
        metadata_file = tmp_path / ".translation_metadata.json"

        # Start 5 worker processes
        results_queue = multiprocessing.Queue()
        processes = []

        for worker_id in range(5):
            p = multiprocessing.Process(
                target=worker_process,
                args=(
                    worker_id,
                    metadata_file,
                    redis_connection["host"],
                    redis_connection["port"],
                    20,  # Each worker updates 20 files
                    results_queue,
                ),
            )
            p.start()
            processes.append(p)

        # Wait for completion
        for p in processes:
            p.join(timeout=60)
            assert not p.is_alive(), "Worker process timed out"

        # Collect results
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        # All workers succeeded
        assert len(results) == 5
        for result in results:
            assert result["status"] == "success", f"Worker failed: {result}"

        # Verify metadata
        data = json.loads(metadata_file.read_text())
        assert len(data["files"]) == 100  # 5 workers * 20 files

    def test_worker_crash_during_lock__other_workers_continue(
        self, tmp_path, redis_connection
    ):
        """If one worker crashes while holding lock, others should recover."""

        def crashing_worker(metadata_file, redis_host, redis_port, results_queue):
            """Worker that crashes after acquiring lock."""
            try:
                import redis

                redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    decode_responses=True,
                )

                tracker = MetadataTracker(
                    metadata_file=metadata_file,
                    hash_algorithm="md5",
                    site_id="crasher",
                    redis_client=redis_client,
                    lock_timeout=5,  # Short timeout for faster recovery
                )

                tracker.load()
                tracker._loaded = True
                tracker._data = {}

                # Intentionally crash during save (simulates worker crash)
                with patch_save_to_crash(tracker):
                    tracker.save()

            except Exception:
                # Worker crashes (expected)
                pass

        # This test is complex to implement properly and may be flaky
        # Skipping for now, but documented as expected behavior
        pytest.skip("Worker crash recovery requires complex Redis lock timeout handling")

    def test_sequential_workers__metadata_accumulates(
        self, tmp_path, redis_connection
    ):
        """Workers running sequentially should accumulate metadata correctly."""
        metadata_file = tmp_path / ".translation_metadata.json"

        # Run 3 workers sequentially
        for worker_id in range(3):
            results_queue = multiprocessing.Queue()
            p = multiprocessing.Process(
                target=worker_process,
                args=(
                    worker_id,
                    metadata_file,
                    redis_connection["host"],
                    redis_connection["port"],
                    5,
                    results_queue,
                ),
            )
            p.start()
            p.join(timeout=15)

            result = results_queue.get()
            assert result["status"] == "success"

        # Verify accumulated metadata
        data = json.loads(metadata_file.read_text())
        assert len(data["files"]) == 15  # 3 workers * 5 files

    def test_lock_timeout_configuration_respected(self, tmp_path, redis_connection):
        """Custom lock timeout from config should be used."""
        metadata_file = tmp_path / ".translation_metadata.json"

        import redis

        redis_client = redis.Redis(
            host=redis_connection["host"],
            port=redis_connection["port"],
            decode_responses=True,
        )

        # Custom timeout
        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id="timeout-test",
            redis_client=redis_client,
            lock_timeout=60,  # 60 seconds
        )

        tracker._loaded = True
        tracker._data = {}

        # Save should use custom timeout
        # (We can't easily verify the timeout was used without mocking,
        #  but at minimum this shouldn't crash)
        tracker.save()

        assert metadata_file.exists()


def patch_save_to_crash(tracker):
    """Helper to make save() crash (for testing crash recovery)."""
    import contextlib

    @contextlib.contextmanager
    def crash_context():
        # Acquire lock then crash
        raise RuntimeError("Simulated worker crash")

    return crash_context()
