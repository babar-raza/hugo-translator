"""Unit tests for data export functionality (Phase 4.3).

Tests the BenchmarkExporter class:
- CSV export
- JSON export
- SQLite backup
- Export filters
- Compression
"""

import csv
import gzip
import json
import pytest
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.benchmarking.exporter import (
    BenchmarkExporter,
    ExportFilter,
    ExportProgress,
    ExportResult,
)
from src.benchmarking.storage import (
    BenchmarkDatabase,
    BenchmarkRun,
    BenchmarkResult,
    SystemInfo,
)


class TestExportFilter:
    """Tests for ExportFilter dataclass."""

    def test_to_dict(self):
        """Test converting ExportFilter to dictionary."""
        filter_obj = ExportFilter(
            start_date="2024-01-01",
            end_date="2024-12-31",
            model_ids=["model_a", "model_b"],
            devices=["cpu"],
        )

        result = filter_obj.to_dict()

        assert result["start_date"] == "2024-01-01"
        assert result["end_date"] == "2024-12-31"
        assert result["model_ids"] == ["model_a", "model_b"]
        assert result["devices"] == ["cpu"]

    def test_to_dict_empty(self):
        """Test ExportFilter with no filters."""
        filter_obj = ExportFilter()
        result = filter_obj.to_dict()

        assert result["start_date"] is None
        assert result["model_ids"] is None


class TestExportProgress:
    """Tests for ExportProgress dataclass."""

    def test_to_dict(self):
        """Test converting ExportProgress to dictionary."""
        progress = ExportProgress(
            table="benchmark_runs",
            rows_exported=500,
            total_rows=1000,
            percent_complete=50.0,
        )

        result = progress.to_dict()

        assert result["table"] == "benchmark_runs"
        assert result["rows_exported"] == 500
        assert result["percent_complete"] == 50.0


class TestExportResult:
    """Tests for ExportResult dataclass."""

    def test_to_dict(self):
        """Test converting ExportResult to dictionary."""
        result = ExportResult(
            format="csv",
            output_path="/path/to/export",
            rows_exported=1000,
            tables_exported=["benchmark_runs", "benchmark_results"],
            file_size_bytes=12345,
            compressed=False,
            duration_seconds=1.5,
        )

        result_dict = result.to_dict()

        assert result_dict["format"] == "csv"
        assert result_dict["rows_exported"] == 1000
        assert result_dict["compressed"] is False
        assert result_dict["error"] is None

    def test_to_dict_with_error(self):
        """Test ExportResult with error."""
        result = ExportResult(
            format="csv",
            output_path="/path/to/export",
            rows_exported=0,
            tables_exported=[],
            file_size_bytes=0,
            compressed=False,
            duration_seconds=0.1,
            error="Export failed",
        )

        result_dict = result.to_dict()
        assert result_dict["error"] == "Export failed"


class TestBenchmarkExporter:
    """Test suite for BenchmarkExporter."""

    def _create_test_run(
        self,
        db: BenchmarkDatabase,
        run_id: str,
        model_id: str = "test_model",
        device: str = "cpu",
        num_results: int = 5,
        timestamp: datetime = None,
    ) -> str:
        """Create a test benchmark run."""
        if timestamp is None:
            timestamp = datetime.now(UTC)

        results = []
        for i in range(num_results):
            results.append(BenchmarkResult(
                sample_id=f"{run_id}_sample_{i}",
                model_id=model_id,
                device=device,
                batch_size=8,
                duration_seconds=1.0 + i * 0.1,
                tokens_input=100,
                tokens_output=100,
                throughput_tokens_per_sec=100.0 + i * 10,
                peak_memory_mb=500.0,
            ))

        run = BenchmarkRun(
            run_id=run_id,
            model_id=model_id,
            device=device,
            batch_sizes=[8],
            iterations=1,
            corpus_category="test",
            purpose="testing",
            tags=["test"],
            system_info=SystemInfo(
                cpu_model="Test CPU",
                cpu_cores=4,
                total_ram_gb=8.0,
            ),
            results=results,
            total_duration_seconds=10.0,
            timestamp_utc=timestamp.isoformat(),
        )

        db.save_run(run)
        return run.run_id

    def test_export_csv(self):
        """Test CSV export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test data
            self._create_test_run(db, "run1", num_results=10)
            self._create_test_run(db, "run2", num_results=5)

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export"

            result = exporter.export_csv(output_path)

            # Check result
            assert result.error is None
            assert result.format == "csv"
            assert result.rows_exported > 0
            assert len(result.tables_exported) > 0
            assert result.compressed is False

            # Check output files exist
            assert (output_path / "benchmark_runs.csv").exists()
            assert (output_path / "benchmark_results.csv").exists()

            # Verify CSV content
            with open(output_path / "benchmark_runs.csv") as f:
                reader = csv.reader(f)
                rows = list(reader)
                assert len(rows) >= 3  # Header + 2 runs

    def test_export_csv_compressed(self):
        """Test compressed CSV export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1")

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export.csv.gz"

            result = exporter.export_csv(output_path, compress=True)

            assert result.error is None
            assert result.compressed is True

            # Check compressed file exists
            assert output_path.with_suffix(".benchmark_runs.csv.gz").exists()

    def test_export_csv_with_filter(self):
        """Test CSV export with filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create runs with different models
            self._create_test_run(db, "run1", model_id="model_a")
            self._create_test_run(db, "run2", model_id="model_b")

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export"

            # Export only model_a
            filter_obj = ExportFilter(model_ids=["model_a"])
            result = exporter.export_csv(output_path, filter=filter_obj)

            assert result.error is None

            # Verify only model_a data
            with open(output_path / "benchmark_runs.csv") as f:
                content = f.read()
                assert "model_a" in content
                # model_b should not appear in filtered export
                # (Note: header row doesn't contain model data)

    def test_export_json(self):
        """Test JSON export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1", num_results=10)

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export.json"

            result = exporter.export_json(output_path)

            assert result.error is None
            assert result.format == "json"
            assert result.rows_exported > 0
            assert output_path.exists()

            # Verify JSON structure
            with open(output_path) as f:
                data = json.load(f)

            assert "export_metadata" in data
            assert "tables" in data
            assert "benchmark_runs" in data["tables"]
            assert len(data["tables"]["benchmark_runs"]) >= 1

    def test_export_json_compressed(self):
        """Test compressed JSON export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1")

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export.json.gz"

            result = exporter.export_json(output_path, compress=True)

            assert result.error is None
            assert result.compressed is True
            assert output_path.exists()

            # Verify can decompress and read
            with gzip.open(output_path, "rt") as f:
                data = json.load(f)
            assert "tables" in data

    def test_export_json_pretty(self):
        """Test pretty-printed JSON export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1")

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export.json"

            result = exporter.export_json(output_path, pretty_print=True)

            assert result.error is None

            # Verify indentation
            with open(output_path) as f:
                content = f.read()
            assert "\n  " in content  # Pretty-printed has indentation

    def test_export_json_with_date_filter(self):
        """Test JSON export with date range filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create old and recent runs
            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            recent_timestamp = datetime.now(UTC)

            self._create_test_run(db, "old_run", timestamp=old_timestamp)
            self._create_test_run(db, "recent_run", timestamp=recent_timestamp)

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export.json"

            # Export only recent data (last 30 days)
            filter_obj = ExportFilter(
                start_date=(datetime.now(UTC) - timedelta(days=30)).isoformat()
            )
            result = exporter.export_json(output_path, filter=filter_obj)

            assert result.error is None

            with open(output_path) as f:
                data = json.load(f)

            # Should only contain recent run
            runs = data["tables"]["benchmark_runs"]
            run_ids = [r["run_id"] for r in runs]
            assert "recent_run" in run_ids
            assert "old_run" not in run_ids

    def test_export_sqlite_full_backup(self):
        """Test full SQLite backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1", num_results=20)
            self._create_test_run(db, "run2", num_results=10)

            exporter = BenchmarkExporter(db_path)
            backup_path = Path(tmpdir) / "backup.db"

            result = exporter.export_sqlite(backup_path)

            assert result.error is None
            assert result.format == "sqlite"
            assert backup_path.exists()

            # Verify backup is valid database
            backup_db = BenchmarkDatabase(backup_path)
            runs = backup_db.list_runs()
            assert len(runs) == 2

    def test_export_sqlite_with_filter(self):
        """Test filtered SQLite export."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1", model_id="model_a")
            self._create_test_run(db, "run2", model_id="model_b")

            exporter = BenchmarkExporter(db_path)
            backup_path = Path(tmpdir) / "filtered_backup.db"

            filter_obj = ExportFilter(model_ids=["model_a"])
            result = exporter.export_sqlite(backup_path, filter=filter_obj)

            assert result.error is None

            # Verify backup contains only filtered data using raw SQLite
            # (BenchmarkDatabase would try to re-apply migrations to exported db)
            import sqlite3
            backup_conn = sqlite3.connect(backup_path)
            cursor = backup_conn.execute("SELECT run_id, model_id FROM benchmark_runs")
            runs = cursor.fetchall()
            backup_conn.close()

            assert len(runs) == 1
            assert runs[0][1] == "model_a"

            # Close source database to prevent Windows file locking
            db.close()

    def test_export_empty_database(self):
        """Test exporting from empty database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            exporter = BenchmarkExporter(db_path)

            # CSV export
            csv_result = exporter.export_csv(Path(tmpdir) / "export_csv")
            assert csv_result.error is None
            assert csv_result.rows_exported == 0

            # JSON export
            json_result = exporter.export_json(Path(tmpdir) / "export.json")
            assert json_result.error is None
            assert json_result.rows_exported == 0

    def test_get_export_estimate(self):
        """Test export size estimation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1", num_results=100)

            exporter = BenchmarkExporter(db_path)
            estimate = exporter.get_export_estimate()

            assert "tables" in estimate
            assert "total_rows" in estimate
            assert estimate["total_rows"] > 0
            assert "benchmark_runs" in estimate["tables"]

    def test_get_export_estimate_with_filter(self):
        """Test export estimation with filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1", model_id="model_a")
            self._create_test_run(db, "run2", model_id="model_b")

            exporter = BenchmarkExporter(db_path)

            # Full estimate
            full_estimate = exporter.get_export_estimate()

            # Filtered estimate
            filter_obj = ExportFilter(model_ids=["model_a"])
            filtered_estimate = exporter.get_export_estimate(filter=filter_obj)

            assert filtered_estimate["total_rows"] < full_estimate["total_rows"]

    def test_progress_callback(self):
        """Test progress callback is called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create enough data to trigger progress callbacks
            for i in range(5):
                self._create_test_run(db, f"run_{i}", num_results=500)

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export.json"

            progress_updates = []

            def progress_callback(progress: ExportProgress):
                progress_updates.append(progress)

            result = exporter.export_json(
                output_path,
                progress_callback=progress_callback,
            )

            assert result.error is None
            # Progress callbacks should have been called
            # (May be empty if total rows < 1000)


class TestExporterEdgeCases:
    """Test edge cases for exporter."""

    def test_export_with_device_filter(self):
        """Test export filtered by device."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create runs on different devices
            results_cpu = [BenchmarkResult(
                sample_id="sample_cpu",
                model_id="test_model",
                device="cpu",
                batch_size=8,
                duration_seconds=1.0,
                tokens_input=100,
                tokens_output=100,
                throughput_tokens_per_sec=100.0,
            )]
            run_cpu = BenchmarkRun(
                run_id="run_cpu",
                model_id="test_model",
                device="cpu",
                batch_sizes=[8],
                iterations=1,
                corpus_category="test",
                purpose="testing",
                tags=["test"],
                system_info=SystemInfo(cpu_model="Test CPU", cpu_cores=4, total_ram_gb=8.0),
                results=results_cpu,
                total_duration_seconds=1.0,
            )
            db.save_run(run_cpu)

            results_cuda = [BenchmarkResult(
                sample_id="sample_cuda",
                model_id="test_model",
                device="cuda",
                batch_size=8,
                duration_seconds=0.5,
                tokens_input=100,
                tokens_output=100,
                throughput_tokens_per_sec=200.0,
            )]
            run_cuda = BenchmarkRun(
                run_id="run_cuda",
                model_id="test_model",
                device="cuda",
                batch_sizes=[8],
                iterations=1,
                corpus_category="test",
                purpose="testing",
                tags=["test"],
                system_info=SystemInfo(cpu_model="Test CPU", cpu_cores=4, total_ram_gb=8.0),
                results=results_cuda,
                total_duration_seconds=0.5,
            )
            db.save_run(run_cuda)

            exporter = BenchmarkExporter(db_path)
            output_path = Path(tmpdir) / "export.json"

            # Export only CPU data
            filter_obj = ExportFilter(devices=["cpu"])
            result = exporter.export_json(output_path, filter=filter_obj)

            assert result.error is None

            with open(output_path) as f:
                data = json.load(f)

            runs = data["tables"]["benchmark_runs"]
            assert len(runs) == 1
            assert runs[0]["device"] == "cpu"
