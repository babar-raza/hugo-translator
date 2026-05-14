"""Unit tests for ProductionMetricsIngestor."""
import tempfile
from pathlib import Path

from src.benchmarking.production_ingestor import ProductionMetricsIngestor
from src.benchmarking.storage import BenchmarkDatabase


def test_ingestor_disabled_is_noop():
    """When enabled=False, record_translation_run should be no-op."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        ingestor = ProductionMetricsIngestor(db, enabled=False)

        # Should not raise or create runs
        ingestor.record_translation_run(
            file_path="test.md",
            target_lang="es",
            segments_translated=10,
            segments_from_tm=5,
            segments_translated_new=5,
            translation_model="test_model",
            retry_count=0,
            success=True,
        )

        # Verify no runs created
        runs = db.list_runs(limit=10)
        assert len(runs) == 0


def test_ingestor_enabled_records_run():
    """When enabled=True, record_translation_run should create benchmark run."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        ingestor = ProductionMetricsIngestor(db, enabled=True)

        ingestor.record_translation_run(
            file_path="test.md",
            target_lang="es",
            segments_translated=10,
            segments_from_tm=5,
            segments_translated_new=5,
            translation_model="test_model",
            retry_count=0,
            success=True,
            duration_seconds=5.5,
        )

        # Verify run created
        runs = db.list_runs(limit=10)
        assert len(runs) == 1

        run_id = runs[0][0]
        run = db.get_run(run_id)
        assert run.purpose == "production"
        assert "production" in run.tags
        assert run.model_id == "test_model"
        assert run.total_duration_seconds == 5.5


def test_ingestor_thread_safe():
    """ProductionMetricsIngestor should be thread-safe."""
    import threading

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        ingestor = ProductionMetricsIngestor(db, enabled=True)

        def record():
            ingestor.record_translation_run(
                file_path="test.md",
                target_lang="es",
                segments_translated=10,
                segments_from_tm=5,
                segments_translated_new=5,
                translation_model="test_model",
                retry_count=0,
                success=True,
            )

        # Run 10 concurrent recordings
        threads = [threading.Thread(target=record) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify 10 runs created
        runs = db.list_runs(limit=20)
        assert len(runs) == 10


def test_ingestor_error_doesnt_crash():
    """ProductionMetricsIngestor should not crash on error."""
    # Create ingestor with enabled=True but None collector (will cause error)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        ingestor = ProductionMetricsIngestor(db, enabled=True)
        # Force error by setting collector to None
        ingestor._collector = None

        # Should not raise, just log error
        ingestor.record_translation_run(
            file_path="test.md",
            target_lang="es",
            segments_translated=10,
            segments_from_tm=5,
            segments_translated_new=5,
            translation_model="test_model",
            retry_count=0,
            success=True,
        )

        # No runs should be created due to error, but no crash
        runs = db.list_runs(limit=10)
        assert len(runs) == 0
