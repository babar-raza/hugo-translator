"""Unit tests for min_segments threshold enforcement (TC-BM-06)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from src.benchmarking.production_ingestor import ProductionMetricsIngestor
from src.benchmarking.storage import BenchmarkDatabase


@pytest.fixture
def temp_db(tmp_path):
    """Create temporary database for testing."""
    db_path = tmp_path / "test.db"
    return BenchmarkDatabase(db_path)


def test_below_threshold_not_recorded(temp_db, caplog):
    """Test translations below threshold are not recorded."""
    # Create ingestor with threshold=5
    ingestor = ProductionMetricsIngestor(temp_db, enabled=True, min_segments=5)

    # Record translation with 4 segments (below threshold)
    ingestor.record_translation_run(
        file_path="test.md",
        target_lang="es",
        segments_translated=4,
        segments_from_tm=0,
        segments_translated_new=4,
        translation_model="test_model",
        retry_count=0,
        success=True,
        duration_seconds=1.0,
    )

    # Should NOT be recorded
    runs = temp_db.list_runs(purpose="production")
    assert len(runs) == 0

    # Should log debug message
    assert "Skipping metrics recording" in caplog.text
    assert "segments=4" in caplog.text
    assert "threshold=5" in caplog.text


def test_at_threshold_recorded(temp_db):
    """Test translations at threshold ARE recorded."""
    # Create ingestor with threshold=5
    ingestor = ProductionMetricsIngestor(temp_db, enabled=True, min_segments=5)

    # Record translation with exactly 5 segments
    ingestor.record_translation_run(
        file_path="test.md",
        target_lang="es",
        segments_translated=5,
        segments_from_tm=0,
        segments_translated_new=5,
        translation_model="test_model",
        retry_count=0,
        success=True,
        duration_seconds=1.0,
    )

    # Should be recorded
    runs = temp_db.list_runs(purpose="production")
    assert len(runs) == 1


def test_above_threshold_recorded(temp_db):
    """Test translations above threshold ARE recorded."""
    # Create ingestor with threshold=5
    ingestor = ProductionMetricsIngestor(temp_db, enabled=True, min_segments=5)

    # Record translation with 10 segments (above threshold)
    ingestor.record_translation_run(
        file_path="test.md",
        target_lang="es",
        segments_translated=10,
        segments_from_tm=2,
        segments_translated_new=8,
        translation_model="test_model",
        retry_count=0,
        success=True,
        duration_seconds=2.0,
    )

    # Should be recorded
    runs = temp_db.list_runs(purpose="production")
    assert len(runs) == 1

    # Verify run details
    run_id = runs[0][0]
    run = temp_db.get_run(run_id)
    assert run.iterations == 10


def test_threshold_default_is_one(temp_db):
    """Test that default threshold is 1."""
    # Create ingestor without specifying min_segments
    ingestor = ProductionMetricsIngestor(temp_db, enabled=True)

    # Should have min_segments=1
    assert ingestor.min_segments == 1

    # Record with 1 segment should work
    ingestor.record_translation_run(
        file_path="test.md",
        target_lang="es",
        segments_translated=1,
        segments_from_tm=0,
        segments_translated_new=1,
        translation_model="test_model",
        retry_count=0,
        success=True,
        duration_seconds=0.5,
    )

    # Should be recorded
    runs = temp_db.list_runs(purpose="production")
    assert len(runs) == 1


def test_negative_threshold_becomes_one(temp_db):
    """Test that negative threshold is coerced to 1."""
    # Create ingestor with negative min_segments
    ingestor = ProductionMetricsIngestor(temp_db, enabled=True, min_segments=-5)

    # Should be coerced to 1
    assert ingestor.min_segments == 1


def test_zero_threshold_becomes_one(temp_db):
    """Test that zero threshold is coerced to 1."""
    # Create ingestor with zero min_segments
    ingestor = ProductionMetricsIngestor(temp_db, enabled=True, min_segments=0)

    # Should be coerced to 1
    assert ingestor.min_segments == 1


def test_disabled_ingestor_ignores_threshold(temp_db):
    """Test that disabled ingestor doesn't record regardless of threshold."""
    # Create DISABLED ingestor (threshold irrelevant)
    ingestor = ProductionMetricsIngestor(temp_db, enabled=False, min_segments=1)

    # Try to record
    ingestor.record_translation_run(
        file_path="test.md",
        target_lang="es",
        segments_translated=100,  # Well above threshold
        segments_from_tm=0,
        segments_translated_new=100,
        translation_model="test_model",
        retry_count=0,
        success=True,
        duration_seconds=5.0,
    )

    # Should NOT be recorded (disabled)
    runs = temp_db.list_runs(purpose="production")
    assert len(runs) == 0


def test_multiple_runs_some_filtered(temp_db):
    """Test that multiple runs are correctly filtered by threshold."""
    ingestor = ProductionMetricsIngestor(temp_db, enabled=True, min_segments=5)

    # Record 5 runs with varying segment counts
    segment_counts = [3, 4, 5, 6, 10]
    for i, segments in enumerate(segment_counts):
        ingestor.record_translation_run(
            file_path=f"test{i}.md",
            target_lang="es",
            segments_translated=segments,
            segments_from_tm=0,
            segments_translated_new=segments,
            translation_model="test_model",
            retry_count=0,
            success=True,
            duration_seconds=1.0,
        )

    # Only 3, 4 should be filtered out (< 5)
    # 5, 6, 10 should be recorded
    runs = temp_db.list_runs(purpose="production")
    assert len(runs) == 3
