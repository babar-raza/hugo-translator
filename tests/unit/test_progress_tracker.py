"""
Unit tests for ProgressTracker and EMA calculations.

Tests ETA calculation, rolling throughput, and metrics snapshots.
"""

import json

# Add src to path for imports
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from observability.progress import (
    EMACalculator,
    ProgressSnapshot,
    ProgressTracker,
    get_progress_tracker,
    init_progress_tracker,
    stop_progress_tracker,
)


class TestEMACalculator:
    """Tests for exponential moving average calculator."""

    def test_initial_value(self):
        """First sample sets the EMA value."""
        ema = EMACalculator(alpha=0.3)
        result = ema.add_sample(10.0)
        assert result == 10.0
        assert ema.get_value() == 10.0

    def test_ema_smoothing(self):
        """EMA smooths values correctly with alpha."""
        ema = EMACalculator(alpha=0.5)
        ema.add_sample(10.0)  # EMA = 10.0
        result = ema.add_sample(20.0)  # EMA = 0.5 * 20 + 0.5 * 10 = 15.0
        assert result == 15.0

    def test_ema_weight_on_recent(self):
        """Higher alpha gives more weight to recent values."""
        ema_high = EMACalculator(alpha=0.9)
        ema_low = EMACalculator(alpha=0.1)

        # Add same samples
        for val in [10.0, 20.0, 30.0]:
            ema_high.add_sample(val)
            ema_low.add_sample(val)

        # High alpha should be closer to 30
        assert ema_high.get_value() > ema_low.get_value()
        assert ema_high.get_value() > 25.0  # Closer to 30

    def test_moving_average(self):
        """Moving average of window is calculated correctly."""
        ema = EMACalculator(alpha=0.3, window_size=3)
        ema.add_sample(10.0)
        ema.add_sample(20.0)
        ema.add_sample(30.0)
        assert ema.get_moving_average() == 20.0  # (10+20+30)/3

    def test_window_overflow(self):
        """Window maintains max size."""
        ema = EMACalculator(alpha=0.3, window_size=3)
        for val in [10.0, 20.0, 30.0, 40.0, 50.0]:
            ema.add_sample(val)
        # Only last 3 samples should be kept
        assert ema.get_moving_average() == 40.0  # (30+40+50)/3

    def test_reset(self):
        """Reset clears all state."""
        ema = EMACalculator(alpha=0.3)
        ema.add_sample(100.0)
        ema.reset()
        assert ema.get_value() == 0.0
        assert ema.get_moving_average() == 0.0


class TestProgressSnapshot:
    """Tests for progress snapshot formatting."""

    def test_eta_formatting_seconds(self):
        """ETA formats correctly for seconds."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 10,
            elapsed_s=10.0,
            eta_s=45.0,
        )
        assert snapshot._format_eta() == "45s"

    def test_eta_formatting_minutes(self):
        """ETA formats correctly for minutes."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 10,
            elapsed_s=10.0,
            eta_s=125.0,  # 2m 5s
        )
        assert snapshot._format_eta() == "2m 5s"

    def test_eta_formatting_hours(self):
        """ETA formats correctly for hours."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 10,
            elapsed_s=10.0,
            eta_s=3725.0,  # 1h 2m 5s
        )
        assert snapshot._format_eta() == "1h 2m 5s"

    def test_eta_formatting_calculating(self):
        """ETA shows calculating for None."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 10,
            elapsed_s=10.0,
            eta_s=None,
        )
        assert snapshot._format_eta() == "calculating..."

    def test_eta_formatting_done(self):
        """ETA shows done for 0."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 10,
            elapsed_s=10.0,
            eta_s=0.0,
        )
        assert snapshot._format_eta() == "done"

    def test_to_compact_line(self):
        """Compact line format includes key metrics."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 10,
            elapsed_s=10.0,
            eta_s=30.0,
            files_total=10,
            files_done=3,
            segments_total=100,
            segments_done=30,
            segments_per_sec_rolling=5.0,
            cache_hit_rate=0.75,
            error_count=1,
            percent_complete_segments=30.0,
        )
        line = snapshot.to_compact_line()
        assert "30.0%" in line
        assert "files=3/10" in line
        assert "segs=30/100" in line
        assert "rate=5.0/s" in line
        assert "cache=75%" in line
        assert "ETA=30s" in line
        assert "err=1" in line

    def test_to_dict_structure(self):
        """Dict format has expected structure."""
        snapshot = ProgressSnapshot(
            timestamp=time.time(),
            start_time=time.time() - 10,
            elapsed_s=10.0,
            files_total=10,
            files_done=5,
            segments_total=100,
            segments_done=50,
        )
        data = snapshot.to_dict()

        # Check structure
        assert "timestamp" in data
        assert "timestamp_iso" in data
        assert "elapsed_s" in data
        assert "overall" in data
        assert "files" in data
        assert "segments" in data
        assert "performance" in data
        assert "cache" in data
        assert "translation" in data
        assert "errors" in data

        # Check nested structure
        assert data["files"]["total"] == 10
        assert data["files"]["done"] == 5
        assert data["segments"]["total"] == 100
        assert data["segments"]["done"] == 50


class TestProgressTracker:
    """Tests for ProgressTracker functionality."""

    def test_start_and_stop(self):
        """Tracker starts and stops cleanly."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start(files_total=5)
        snapshot = tracker.stop()

        assert snapshot.files_total == 5
        assert snapshot.elapsed_s > 0

    def test_file_progress(self):
        """File progress is tracked correctly."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start(files_total=3)

        tracker.file_started("test1.md", segment_count=10)
        tracker.file_completed(success=True)

        tracker.file_started("test2.md", segment_count=20)
        tracker.file_completed(success=False)

        snapshot = tracker.get_snapshot()

        assert snapshot.files_done == 1
        assert snapshot.files_failed == 1
        assert snapshot.files_total == 3
        assert snapshot.segments_total == 30  # 10 + 20

        tracker.stop()

    def test_segment_progress(self):
        """Segment progress is tracked correctly."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()
        tracker.set_totals(segments=100)

        tracker.segments_completed(25, duration_s=1.0)
        tracker.segments_completed(25, duration_s=1.0)

        snapshot = tracker.get_snapshot()

        assert snapshot.segments_done == 50
        assert snapshot.segments_total == 100
        assert snapshot.percent_complete_segments == 50.0

        tracker.stop()

    def test_cache_tracking(self):
        """Cache hits and misses are tracked."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()

        tracker.cache_hit("l1")
        tracker.cache_hit("l1")
        tracker.cache_hit("l2")
        tracker.cache_miss()

        snapshot = tracker.get_snapshot()

        assert snapshot.cache_hits == 3
        assert snapshot.cache_misses == 1
        assert snapshot.l1_hits == 2
        assert snapshot.l2_hits == 1
        assert snapshot.cache_hit_rate == 0.75

        tracker.stop()

    def test_eta_calculation(self):
        """ETA is calculated from throughput."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()
        tracker.set_totals(segments=100)

        # Simulate 10 segments/sec rate
        tracker.segments_completed(10, duration_s=1.0)

        snapshot = tracker.get_snapshot()

        # With 90 remaining at 10/sec, ETA should be ~9 seconds
        assert snapshot.eta_s is not None
        assert 5.0 < snapshot.eta_s < 15.0

        tracker.stop()

    def test_throughput_ema(self):
        """Rolling throughput uses EMA smoothing."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()
        tracker.set_totals(segments=100)

        # Add varying rates
        tracker.segments_completed(10, duration_s=1.0)  # 10/sec
        tracker.segments_completed(20, duration_s=1.0)  # 20/sec

        snapshot = tracker.get_snapshot()

        # Rolling rate should be between 10 and 20 due to EMA
        assert 10.0 < snapshot.segments_per_sec_rolling < 20.0

        tracker.stop()

    def test_error_tracking(self):
        """Errors are tracked with details."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()

        tracker.record_error("translation_error", "Model failed", "test.md")
        tracker.record_error("validation_error", "Invalid format")

        snapshot = tracker.get_snapshot()

        assert snapshot.error_count == 2
        assert "Invalid format" in snapshot.last_error
        assert snapshot.errors_by_type["translation_error"] == 1
        assert snapshot.errors_by_type["validation_error"] == 1

        tracker.stop()

    def test_metrics_file_output(self):
        """Metrics are written to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_path = Path(tmpdir) / "metrics"

            tracker = ProgressTracker(
                show_progress=False,
                update_interval=0,
                metrics_file=metrics_path,
            )
            tracker.start(files_total=1)
            tracker.file_started("test.md", segment_count=5)
            tracker.segments_completed(5, duration_s=1.0)
            tracker.file_completed()
            tracker.stop()

            # Check snapshot file
            json_path = metrics_path.parent / "metrics_current.json"
            assert json_path.exists()

            with open(json_path) as f:
                data = json.load(f)
            assert data["files"]["done"] == 1

            # Check NDJSON stream
            ndjson_path = metrics_path.with_suffix(".ndjson")
            assert ndjson_path.exists()

            lines = ndjson_path.read_text().strip().split("\n")
            assert len(lines) >= 1  # At least final snapshot

            # Verify each line is valid JSON
            for line in lines:
                data = json.loads(line)
                assert "timestamp" in data

    def test_monotonic_segments(self):
        """Segment count is monotonically increasing."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()

        counts = []
        for i in range(5):
            tracker.segments_completed(10)
            counts.append(tracker.get_snapshot().segments_done)

        # Verify monotonically increasing
        for i in range(1, len(counts)):
            assert counts[i] >= counts[i-1]

        assert counts[-1] == 50

        tracker.stop()

    def test_batch_tracking(self):
        """Batch progress is tracked."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start()
        tracker.set_totals(batches=5)

        tracker.batch_started(16)
        tracker.batch_completed(16)
        tracker.batch_started(16)
        tracker.batch_completed(16)

        snapshot = tracker.get_snapshot()

        assert snapshot.batches_done == 2
        assert snapshot.avg_batch_s > 0

        tracker.stop()


class TestGlobalProgressTracker:
    """Tests for global progress tracker singleton."""

    def test_init_and_get(self):
        """Global tracker can be initialized and retrieved."""
        # Clean up any existing tracker
        stop_progress_tracker()

        tracker = init_progress_tracker(
            update_interval=0,
            show_progress=False,
        )
        assert tracker is not None

        retrieved = get_progress_tracker()
        assert retrieved is tracker

        stop_progress_tracker()

    def test_stop_returns_snapshot(self):
        """Stopping returns final snapshot."""
        init_progress_tracker(update_interval=0, show_progress=False)
        tracker = get_progress_tracker()
        tracker.start(files_total=5)
        tracker.file_started("test.md")
        tracker.file_completed()

        snapshot = stop_progress_tracker()

        assert snapshot is not None
        assert snapshot.files_done == 1
        assert get_progress_tracker() is None

    def test_stop_without_init(self):
        """Stopping non-existent tracker returns None."""
        # Ensure no tracker exists
        stop_progress_tracker()

        result = stop_progress_tracker()
        assert result is None


class TestProgressTrackerIntegration:
    """Integration tests simulating real workflow."""

    def test_simulated_translation_run(self, test_model):
        """Simulate a full translation run with multiple files."""
        tracker = ProgressTracker(show_progress=False, update_interval=0)
        tracker.start(files_total=3)
        tracker.set_model(test_model, "cuda")

        # File 1: 10 segments, some cache hits
        tracker.file_started("file1.md", segment_count=10)
        tracker.cache_hit("l1")
        tracker.cache_hit("l1")
        tracker.cache_hit("l2")
        tracker.cache_miss()
        tracker.cache_miss()
        tracker.cache_miss()
        tracker.cache_miss()
        tracker.cache_miss()
        tracker.cache_miss()
        tracker.cache_miss()
        tracker.batch_started(7)
        tracker.segments_completed(7, duration_s=0.5)
        tracker.batch_completed(7)
        tracker.segments_completed(3)  # Cache hits
        tracker.file_completed()

        # File 2: 20 segments
        tracker.file_started("file2.md", segment_count=20)
        tracker.batch_started(16)
        tracker.segments_completed(16, duration_s=1.0)
        tracker.batch_completed(16)
        tracker.batch_started(4)
        tracker.segments_completed(4, duration_s=0.25)
        tracker.batch_completed(4)
        tracker.file_completed()

        # File 3: failed
        tracker.file_started("file3.md", segment_count=5)
        tracker.record_error("model_error", "Out of memory", "file3.md")
        tracker.file_completed(success=False)

        snapshot = tracker.stop()

        # Verify final state
        assert snapshot.files_done == 2
        assert snapshot.files_failed == 1
        assert snapshot.segments_done == 30
        assert snapshot.cache_hits == 3
        assert snapshot.cache_misses == 7
        assert snapshot.batches_done == 3
        assert snapshot.error_count == 1
        assert snapshot.model_name == test_model
        assert snapshot.device == "cuda"
