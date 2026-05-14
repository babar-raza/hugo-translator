"""
Integration tests for metrics output from translation pipeline.

Tests that metrics are produced correctly and values are monotonic.
"""

import json

# Add src to path for imports
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from observability.progress import (
    ProgressSnapshot,
    ProgressTracker,
    get_progress_tracker,
    init_progress_tracker,
    stop_progress_tracker,
)


class MockTranslationPipeline:
    """Mock translation pipeline for testing metrics integration."""

    def __init__(self, progress: ProgressTracker):
        self.progress = progress

    def translate_files(self, files: list[dict], batch_size: int = 10):
        """
        Simulate translating multiple files.

        Args:
            files: List of dicts with 'name' and 'segments' keys
            batch_size: Number of segments per batch
        """
        total_segments = sum(f["segments"] for f in files)
        self.progress.set_totals(segments=total_segments)

        for file_info in files:
            file_name = file_info["name"]
            segment_count = file_info["segments"]
            success = file_info.get("success", True)
            cache_hit_rate = file_info.get("cache_hit_rate", 0.0)

            self.progress.file_started(file_name, segment_count=segment_count)

            # Calculate cache hits vs misses
            cache_hits = int(segment_count * cache_hit_rate)
            cache_misses = segment_count - cache_hits

            # Record cache hits
            for _ in range(cache_hits):
                self.progress.cache_hit("l2")
                self.progress.segments_completed(1)

            # Simulate model translation in batches
            remaining = cache_misses
            while remaining > 0:
                batch = min(remaining, batch_size)
                self.progress.batch_started(batch)

                # Simulate translation time
                time.sleep(0.01)

                for _ in range(batch):
                    self.progress.cache_miss()

                self.progress.segments_completed(batch, duration_s=0.01 * batch)
                self.progress.batch_completed(batch)
                remaining -= batch

            if not success:
                self.progress.record_error("test_error", f"Simulated failure in {file_name}", file_name)

            self.progress.file_completed(success=success)


class TestMetricsIntegration:
    """Integration tests for metrics pipeline."""

    def test_metrics_monotonic_progress(self):
        """Verify segments_done is monotonically increasing."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            metrics_path = Path(tmpdir) / "metrics"

            tracker = ProgressTracker(
                show_progress=False,
                update_interval=0.1,  # Fast updates
                metrics_file=metrics_path,
            )
            tracker.start(files_total=3)

            pipeline = MockTranslationPipeline(tracker)
            pipeline.translate_files([
                {"name": "file1.md", "segments": 20, "cache_hit_rate": 0.3},
                {"name": "file2.md", "segments": 30, "cache_hit_rate": 0.5},
                {"name": "file3.md", "segments": 10, "cache_hit_rate": 0.0},
            ])

            final = tracker.stop()

            # Read NDJSON and verify monotonicity
            ndjson_path = metrics_path.with_suffix(".ndjson")
            assert ndjson_path.exists()

            lines = ndjson_path.read_text().strip().split("\n")
            segments_done_values = []

            for line in lines:
                data = json.loads(line)
                segments_done_values.append(data["segments"]["done"])

            # Check monotonically increasing (or equal)
            for i in range(1, len(segments_done_values)):
                assert segments_done_values[i] >= segments_done_values[i-1], \
                    f"Segment count decreased at index {i}: {segments_done_values[i-1]} -> {segments_done_values[i]}"

            # Final should have all segments
            assert final.segments_done == 60

    def test_metrics_file_structure(self):
        """Verify metrics file has correct JSON structure."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            metrics_path = Path(tmpdir) / "metrics"

            tracker = ProgressTracker(
                show_progress=False,
                update_interval=0,
                metrics_file=metrics_path,
            )
            tracker.start(files_total=1)
            tracker.set_model("test_model", "cpu")

            tracker.file_started("test.md", segment_count=10)
            tracker.cache_hit("l1")
            tracker.cache_hit("l2")
            tracker.cache_miss()
            tracker.segments_completed(10, duration_s=1.0)
            tracker.add_tokens(tokens_in=100, tokens_out=150)
            tracker.file_completed()

            tracker.stop()

            # Read final snapshot
            json_path = metrics_path.parent / "metrics_current.json"
            with open(json_path) as f:
                data = json.load(f)

            # Verify structure
            assert "timestamp" in data
            assert "timestamp_iso" in data
            assert "elapsed_s" in data
            assert "eta_s" in data
            assert "eta_formatted" in data

            # Overall section
            assert "overall" in data
            assert "percent_complete_files" in data["overall"]
            assert "percent_complete_segments" in data["overall"]

            # Files section
            assert "files" in data
            assert data["files"]["total"] == 1
            assert data["files"]["done"] == 1

            # Segments section
            assert "segments" in data
            assert data["segments"]["total"] == 10
            assert data["segments"]["done"] == 10

            # Performance section
            assert "performance" in data
            assert "segments_per_sec_rolling" in data["performance"]
            assert "segments_per_sec_lifetime" in data["performance"]
            assert "avg_segment_ms" in data["performance"]

            # Cache section
            assert "cache" in data
            assert data["cache"]["hits"] == 2
            assert data["cache"]["misses"] == 1
            assert data["cache"]["l1_hits"] == 1
            assert data["cache"]["l2_hits"] == 1

            # Translation section
            assert "translation" in data
            assert data["translation"]["model"] == "test_model"
            assert data["translation"]["device"] == "cpu"
            assert data["translation"]["tokens_in"] == 100
            assert data["translation"]["tokens_out"] == 150

            # Errors section
            assert "errors" in data
            assert data["errors"]["count"] == 0

    def test_cache_hit_rate_calculation(self):
        """Verify cache hit rate is calculated correctly."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()

        # 75% hit rate: 3 hits, 1 miss
        tracker.cache_hit("l1")
        tracker.cache_hit("l2")
        tracker.cache_hit("l3")
        tracker.cache_miss()

        snapshot = tracker.get_snapshot()

        assert snapshot.cache_hits == 3
        assert snapshot.cache_misses == 1
        assert snapshot.cache_hit_rate == 0.75
        assert snapshot.l1_hits == 1
        assert snapshot.l2_hits == 1
        assert snapshot.l3_hits == 1

        tracker.stop()

    def test_eta_decreases_over_time(self):
        """Verify ETA decreases as work progresses."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()
        tracker.set_totals(segments=100)

        etas = []

        # Process in chunks and record ETA
        for _ in range(5):
            tracker.segments_completed(10, duration_s=0.1)
            snapshot = tracker.get_snapshot()
            if snapshot.eta_s is not None:
                etas.append(snapshot.eta_s)
            time.sleep(0.05)

        tracker.stop()

        # ETA should generally decrease (allow for some variance due to EMA)
        assert len(etas) >= 2
        # First ETA should be higher than last
        assert etas[0] > etas[-1]

    def test_throughput_averaging(self):
        """Verify throughput is calculated as rolling average."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()

        # Variable rates
        tracker.segments_completed(10, duration_s=1.0)  # 10/sec
        tracker.segments_completed(20, duration_s=1.0)  # 20/sec
        tracker.segments_completed(10, duration_s=1.0)  # 10/sec

        snapshot = tracker.get_snapshot()

        # Rolling average should smooth out the variations
        # Not exactly any single rate due to EMA
        assert 10.0 < snapshot.segments_per_sec_rolling < 20.0

        tracker.stop()

    def test_error_accumulation(self):
        """Verify errors accumulate correctly by type."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()

        tracker.record_error("model_error", "Out of memory", "file1.md")
        tracker.record_error("model_error", "Timeout", "file2.md")
        tracker.record_error("validation_error", "Invalid format", "file3.md")

        snapshot = tracker.get_snapshot()

        assert snapshot.error_count == 3
        assert snapshot.errors_by_type["model_error"] == 2
        assert snapshot.errors_by_type["validation_error"] == 1
        assert "file3.md" in snapshot.last_failed_file

        tracker.stop()

    def test_batch_timing_average(self):
        """Verify batch timing is averaged correctly."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()

        # Simulate batches with different durations
        for _ in range(3):
            tracker.batch_started(16)
            time.sleep(0.05)
            tracker.batch_completed(16)

        snapshot = tracker.get_snapshot()

        assert snapshot.batches_done == 3
        assert snapshot.avg_batch_s > 0.04  # At least 40ms per batch

        tracker.stop()

    def test_percent_complete_accuracy(self):
        """Verify percent complete is accurate."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start(files_total=4)
        tracker.set_totals(segments=100)

        # 25% files, 50% segments
        tracker.file_started("f1.md")
        tracker.file_completed()
        tracker.segments_completed(50)

        snapshot = tracker.get_snapshot()

        assert snapshot.percent_complete_files == 25.0
        assert snapshot.percent_complete_segments == 50.0

        tracker.stop()


class TestMetricsOutputFormats:
    """Tests for metrics output formatting."""

    def test_compact_line_format(self):
        """Verify compact line contains all key metrics."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 60,
            elapsed_s=60.0,
            eta_s=120.0,
            files_total=10,
            files_done=5,
            segments_total=1000,
            segments_done=500,
            segments_per_sec_rolling=8.5,
            cache_hit_rate=0.65,
            error_count=2,
            percent_complete_segments=50.0,
        )

        line = snapshot.to_compact_line()

        assert "50.0%" in line
        assert "files=5/10" in line
        assert "segs=500/1000" in line
        assert "rate=8.5/s" in line
        assert "cache=65%" in line
        assert "2m 0s" in line  # ETA
        assert "err=2" in line

    def test_dict_json_serializable(self):
        """Verify snapshot dict is JSON serializable."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 60,
            elapsed_s=60.0,
            errors_by_type={"test": 1},
        )

        data = snapshot.to_dict()

        # Should not raise
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

        # Round-trip
        parsed = json.loads(json_str)
        assert parsed["elapsed_s"] == 60.0


class TestGlobalTrackerIntegration:
    """Tests for global tracker usage in pipeline."""

    def test_global_tracker_in_simulated_engine(self, test_model):
        """Simulate how engine would use global tracker."""
        # Clean up
        stop_progress_tracker()

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            metrics_path = Path(tmpdir) / "metrics"

            # Initialize like CLI would
            tracker = init_progress_tracker(
                update_interval=0,
                show_progress=False,
                metrics_file=metrics_path,
            )
            tracker.start(files_total=2)
            tracker.set_model(test_model, "cuda")

            # Simulate engine calls using get_progress_tracker()
            progress = get_progress_tracker()
            assert progress is not None

            progress.file_started("doc1.md", segment_count=5)
            progress.cache_hit("l1")
            progress.segments_completed(1)
            progress.cache_miss()
            progress.batch_started(4)
            progress.segments_completed(4, duration_s=0.1)
            progress.batch_completed(4)
            progress.file_completed()

            progress.file_started("doc2.md", segment_count=3)
            progress.segments_completed(3, duration_s=0.05)
            progress.file_completed()

            # Stop like CLI would
            final = stop_progress_tracker()

            assert final.files_done == 2
            assert final.segments_done == 8
            assert final.cache_hits == 1
            assert final.cache_misses == 1

            # Verify output files
            json_path = metrics_path.parent / "metrics_current.json"
            assert json_path.exists()

            ndjson_path = metrics_path.with_suffix(".ndjson")
            assert ndjson_path.exists()
