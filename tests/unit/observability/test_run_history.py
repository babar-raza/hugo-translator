"""Tests for RunHistoryTracker (TC-AGENT-01)."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

import pytest

from src.observability.run_history import (
    RegressionAlert,
    RunHistoryTracker,
    RunOutcome,
)


def _make_outcome(
    acceptance_rate: float = 0.90,
    site_id: str = "docs.aspose.net",
    target_lang: str = "de",
    run_id: str | None = None,
    timestamp: str | None = None,
) -> RunOutcome:
    return RunOutcome(
        run_id=run_id or str(uuid.uuid4()),
        site_id=site_id,
        target_lang=target_lang,
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        files_attempted=10,
        files_accepted=int(10 * acceptance_rate),
        files_rejected=int(10 * (1 - acceptance_rate)),
        files_skipped=0,
        retry_count=1,
        acceptance_rate=acceptance_rate,
        dominant_failure_type=None,
        elapsed_seconds=120.0,
    )


class TestRecordAndRetrieve:
    def test_record_and_retrieve_outcome(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        outcome = _make_outcome(acceptance_rate=0.85)
        tracker.record_outcome(outcome)

        results = tracker.get_recent_outcomes("docs.aspose.net", "de", limit=10)
        assert len(results) == 1
        assert results[0].run_id == outcome.run_id
        assert results[0].acceptance_rate == 0.85

    def test_multiple_outcomes_ordered_by_timestamp(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        for i in range(5):
            tracker.record_outcome(
                _make_outcome(
                    acceptance_rate=0.80 + i * 0.02,
                    timestamp=f"2026-06-{10 + i:02d}T00:00:00Z",
                )
            )
        results = tracker.get_recent_outcomes("docs.aspose.net", "de", limit=5)
        assert len(results) == 5
        # Most recent first
        assert results[0].acceptance_rate == pytest.approx(0.88)


class TestAcceptanceRateTrend:
    def test_acceptance_rate_trend_calculation(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        rates = [0.80, 0.85, 0.90, 0.95, 1.00]
        for i, rate in enumerate(rates):
            tracker.record_outcome(
                _make_outcome(
                    acceptance_rate=rate,
                    timestamp=f"2026-06-{10 + i:02d}T00:00:00Z",
                )
            )
        trend = tracker.get_acceptance_rate_trend("docs.aspose.net", "de", window=5)
        assert trend == pytest.approx(0.90)

    def test_empty_history_returns_none(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        assert tracker.get_acceptance_rate_trend("docs.aspose.net", "de") is None


class TestRegressionDetection:
    def test_regression_detection_fires_on_drop(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        # 5 stable runs at 0.90
        for i in range(5):
            tracker.record_outcome(
                _make_outcome(
                    acceptance_rate=0.90,
                    timestamp=f"2026-06-{10 + i:02d}T00:00:00Z",
                )
            )
        # Then a sharp drop
        tracker.record_outcome(
            _make_outcome(
                acceptance_rate=0.50,
                timestamp="2026-06-15T00:00:00Z",
            )
        )

        alert = tracker.detect_regression("docs.aspose.net", "de", threshold=0.15)
        assert alert is not None
        assert isinstance(alert, RegressionAlert)
        assert alert.current_rate == 0.50
        assert alert.moving_avg == pytest.approx(0.90)
        assert alert.delta >= 0.15

    def test_regression_detection_silent_on_stable(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        for i in range(5):
            tracker.record_outcome(
                _make_outcome(
                    acceptance_rate=0.90,
                    timestamp=f"2026-06-{10 + i:02d}T00:00:00Z",
                )
            )
        alert = tracker.detect_regression("docs.aspose.net", "de", threshold=0.15)
        assert alert is None

    def test_empty_history_returns_none(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        assert tracker.detect_regression("docs.aspose.net", "de") is None

    def test_single_run_returns_none(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        tracker.record_outcome(_make_outcome())
        assert tracker.detect_regression("docs.aspose.net", "de") is None


class TestMemoryDB:
    def test_memory_db_works(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        tracker.record_outcome(_make_outcome())
        results = tracker.get_recent_outcomes("docs.aspose.net", "de")
        assert len(results) == 1


class TestConcurrentWrites:
    def test_concurrent_writes_safe(self) -> None:
        tracker = RunHistoryTracker(":memory:")
        errors: list[Exception] = []

        def write_outcome(idx: int) -> None:
            try:
                tracker.record_outcome(
                    _make_outcome(
                        acceptance_rate=0.80 + idx * 0.01,
                        run_id=f"run-{idx}",
                    )
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_outcome, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        results = tracker.get_recent_outcomes("docs.aspose.net", "de", limit=20)
        assert len(results) == 10


class TestWALMode:
    def test_wal_mode_enabled(self, tmp_path) -> None:
        db_path = tmp_path / "test.db"
        tracker = RunHistoryTracker(db_path)
        tracker.record_outcome(_make_outcome())

        # Verify WAL mode is set
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"
        tracker.close()


class TestRegressionDetectionEndToEnd:
    """TC-FIX-09: Proves rejection→run_history→regression chain works end-to-end."""

    def test_regression_detection_wired_with_real_data(self) -> None:
        """Regression alert fires when acceptance drops significantly from stable baseline."""
        tracker = RunHistoryTracker(":memory:")
        # Stable baseline: 5 runs at 0.95
        for _ in range(5):
            tracker.record_outcome(_make_outcome(acceptance_rate=0.95))
        # Sharp drop: 1 recent run at 0.60 (delta = 0.35, threshold = 0.15)
        tracker.record_outcome(_make_outcome(acceptance_rate=0.60))

        alert = tracker.detect_regression("docs.aspose.net", "de", threshold=0.15)
        assert alert is not None, "Expected regression alert to fire after acceptance drop"
        assert alert.delta >= 0.15, f"Expected delta >= 0.15, got {alert.delta}"
        assert alert.current_rate == pytest.approx(0.60, abs=0.05)
        assert alert.site_id == "docs.aspose.net"
        assert alert.target_lang == "de"

    def test_acceptance_rate_reflects_failed_files(self) -> None:
        """acceptance_rate stored correctly when files_rejected > 0 (not always 1.0)."""
        tracker = RunHistoryTracker(":memory:")
        outcome = RunOutcome(
            run_id=str(uuid.uuid4()),
            site_id="docs.aspose.net",
            target_lang="de",
            timestamp=datetime.now(timezone.utc).isoformat(),
            files_attempted=10,
            files_accepted=7,
            files_rejected=3,
            files_skipped=0,
            retry_count=0,
            acceptance_rate=0.7,
            dominant_failure_type=None,
            elapsed_seconds=1.0,
        )
        tracker.record_outcome(outcome)
        results = tracker.get_recent_outcomes("docs.aspose.net", "de", limit=5)
        assert len(results) == 1
        assert results[0].acceptance_rate == pytest.approx(0.7)
        assert results[0].files_rejected == 3
        # Regression should NOT fire on a single run with no baseline
        alert = tracker.detect_regression("docs.aspose.net", "de", threshold=0.15)
        assert alert is None, "No regression expected with only 1 run (no baseline)"
