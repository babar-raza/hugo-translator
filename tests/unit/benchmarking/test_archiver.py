"""Unit tests for archive system (Phase 4.3).

Tests the BenchmarkArchiver class:
- Archive creation
- Archive restoration
- Archive rotation
- Compression support
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.benchmarking.archiver import (
    ArchiveMetadata,
    ArchiveResult,
    BenchmarkArchiver,
    RestoreResult,
)
from src.benchmarking.storage import (
    BenchmarkDatabase,
    BenchmarkResult,
    BenchmarkRun,
    SystemInfo,
)


class TestArchiveMetadata:
    """Tests for ArchiveMetadata dataclass."""

    def test_to_dict(self):
        """Test converting ArchiveMetadata to dictionary."""
        metadata = ArchiveMetadata(
            archive_id="archive_20240115",
            archive_path="/path/to/archive.db",
            created_at="2024-01-15T12:00:00",
            source_database="/path/to/source.db",
            data_start_date="2023-01-01T00:00:00",
            data_end_date="2023-12-31T23:59:59",
            total_runs=100,
            total_results=5000,
            file_size_bytes=1024000,
            compressed=False,
            schema_version=8,
        )

        result = metadata.to_dict()

        assert result["archive_id"] == "archive_20240115"
        assert result["total_runs"] == 100
        assert result["compressed"] is False

    def test_from_dict(self):
        """Test creating ArchiveMetadata from dictionary."""
        data = {
            "archive_id": "archive_20240115",
            "archive_path": "/path/to/archive.db",
            "created_at": "2024-01-15T12:00:00",
            "source_database": "/path/to/source.db",
            "data_start_date": "2023-01-01T00:00:00",
            "data_end_date": "2023-12-31T23:59:59",
            "total_runs": 100,
            "total_results": 5000,
            "file_size_bytes": 1024000,
            "compressed": False,
            "schema_version": 8,
        }

        metadata = ArchiveMetadata.from_dict(data)

        assert metadata.archive_id == "archive_20240115"
        assert metadata.total_runs == 100


class TestArchiveResult:
    """Tests for ArchiveResult dataclass."""

    def test_to_dict_success(self):
        """Test ArchiveResult to dictionary for success case."""
        metadata = ArchiveMetadata(
            archive_id="test",
            archive_path="/path",
            created_at="2024-01-15T12:00:00",
            source_database="/db",
            data_start_date=None,
            data_end_date=None,
            total_runs=10,
            total_results=100,
            file_size_bytes=1000,
            compressed=False,
            schema_version=8,
        )

        result = ArchiveResult(
            success=True,
            archive_path="/path/to/archive.db",
            metadata=metadata,
            rows_archived=100,
            rows_deleted=0,
            duration_seconds=1.5,
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is True
        assert result_dict["rows_archived"] == 100
        assert result_dict["error"] is None
        assert result_dict["metadata"]["total_runs"] == 10

    def test_to_dict_failure(self):
        """Test ArchiveResult to dictionary for failure case."""
        result = ArchiveResult(
            success=False,
            archive_path=None,
            metadata=None,
            rows_archived=0,
            rows_deleted=0,
            duration_seconds=0.1,
            error="Archive failed",
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is False
        assert result_dict["error"] == "Archive failed"


class TestRestoreResult:
    """Tests for RestoreResult dataclass."""

    def test_to_dict(self):
        """Test RestoreResult to dictionary."""
        result = RestoreResult(
            success=True,
            archive_path="/path/to/archive.db",
            rows_restored=500,
            tables_restored=["benchmark_runs", "benchmark_results"],
            duration_seconds=2.5,
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is True
        assert result_dict["rows_restored"] == 500
        assert "benchmark_runs" in result_dict["tables_restored"]


class TestBenchmarkArchiver:
    """Test suite for BenchmarkArchiver."""

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

    def test_create_archive(self):
        """Test creating an archive."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            # Create old run (60 days ago)
            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            self._create_test_run(db, "old_run", num_results=10, timestamp=old_timestamp)

            # Create recent run
            self._create_test_run(db, "recent_run", num_results=5)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            # Archive data before 30 days ago
            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            result = archiver.create_archive(before_date=before_date)

            assert result.success is True
            assert result.archive_path is not None
            assert result.metadata is not None
            assert result.metadata.total_runs == 1
            assert result.metadata.total_results == 10
            assert result.rows_archived == 10

            # Verify archive file exists
            assert Path(result.archive_path).exists()

    def test_create_archive_no_data(self):
        """Test creating archive with no matching data."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            # Create only recent run
            self._create_test_run(db, "recent_run")

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            # Archive data before a year ago (nothing matches)
            before_date = (datetime.now(UTC) - timedelta(days=365)).isoformat()
            result = archiver.create_archive(before_date=before_date)

            assert result.success is True
            assert result.archive_path is None
            assert result.rows_archived == 0

    def test_create_archive_compressed(self):
        """Test creating compressed archive."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            self._create_test_run(db, "old_run", timestamp=old_timestamp)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            result = archiver.create_archive(before_date=before_date, compress=True)

            assert result.success is True
            assert result.metadata.compressed is True
            assert Path(result.archive_path).suffix == ".gz"

    def test_create_archive_delete_after(self):
        """Test archiving with delete after."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            self._create_test_run(db, "old_run", timestamp=old_timestamp)
            self._create_test_run(db, "recent_run")

            # Verify 2 runs exist
            runs_before = db.list_runs()
            assert len(runs_before) == 2

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            result = archiver.create_archive(
                before_date=before_date,
                delete_after_archive=True,
            )

            assert result.success is True
            assert result.rows_deleted > 0

            # Verify old run deleted
            runs_after = db.list_runs()
            assert len(runs_after) == 1
            assert runs_after[0][0] == "recent_run"

    def test_list_archives(self):
        """Test listing archives."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            # Create old data
            old_timestamp = datetime.now(UTC) - timedelta(days=100)
            self._create_test_run(db, "old_run", timestamp=old_timestamp)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            # Create multiple archives
            for i in range(3):
                before_date = (datetime.now(UTC) - timedelta(days=50 - i * 10)).isoformat()
                archiver.create_archive(
                    before_date=before_date,
                    archive_name=f"archive_{i}",
                )

            archives = archiver.list_archives()

            # Should have archives
            assert len(archives) >= 1

    def test_get_archive(self):
        """Test getting specific archive metadata."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            self._create_test_run(db, "old_run", timestamp=old_timestamp)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            create_result = archiver.create_archive(
                before_date=before_date,
                archive_name="test_archive",
            )

            # Get archive by the name we created it with
            archive = archiver.get_archive("test_archive")

            # Verify archive metadata
            assert archive is not None
            assert "test_archive" in archive.archive_id  # May have suffix
            assert archive.total_runs == 1

    def test_get_archive_not_found(self):
        """Test getting non-existent archive."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            BenchmarkDatabase(db_path)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            archive = archiver.get_archive("nonexistent")

            assert archive is None

    def test_restore_archive(self):
        """Test restoring from archive."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            # Create and archive old run
            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            self._create_test_run(db, "old_run", num_results=10, timestamp=old_timestamp)
            self._create_test_run(db, "recent_run", num_results=5)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            # Archive and delete
            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            archiver.create_archive(
                before_date=before_date,
                archive_name="test_restore",
                delete_after_archive=True,
            )

            # Verify old run deleted
            runs_before_restore = db.list_runs()
            assert len(runs_before_restore) == 1

            # Restore archive
            result = archiver.restore_archive("test_restore")

            assert result.success is True
            assert result.rows_restored > 0
            assert "benchmark_runs" in result.tables_restored

            # Verify data restored
            runs_after_restore = db.list_runs()
            assert len(runs_after_restore) == 2

    def test_restore_archive_not_found(self):
        """Test restoring non-existent archive."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            BenchmarkDatabase(db_path)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            result = archiver.restore_archive("nonexistent")

            assert result.success is False
            assert "not found" in result.error.lower()

    def test_restore_compressed_archive(self):
        """Test restoring from compressed archive."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            self._create_test_run(db, "old_run", num_results=10, timestamp=old_timestamp)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            # Archive with compression
            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            create_result = archiver.create_archive(
                before_date=before_date,
                archive_name="compressed_archive",
                compress=True,
                delete_after_archive=True,
            )

            # Restore
            result = archiver.restore_archive("compressed_archive")

            assert result.success is True
            assert result.rows_restored > 0

    def test_rotate_archives(self):
        """Test archive rotation."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            # Create multiple runs at different times
            for i in range(5):
                timestamp = datetime.now(UTC) - timedelta(days=100 + i * 10)
                self._create_test_run(db, f"old_run_{i}", timestamp=timestamp)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            # Create multiple archives
            for i in range(5):
                timestamp = datetime.now(UTC) - timedelta(days=50 + i * 5)
                archiver.create_archive(
                    before_date=timestamp.isoformat(),
                    archive_name=f"archive_{i}",
                )

            # Verify archives created
            archives_before = archiver.list_archives()
            assert len(archives_before) >= 3

            # Rotate to keep only 2
            deleted = archiver.rotate_archives(keep_count=2)

            archives_after = archiver.list_archives()
            assert len(archives_after) <= 2
            assert deleted >= len(archives_before) - 2

    def test_delete_archive(self):
        """Test deleting a specific archive."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            self._create_test_run(db, "old_run", timestamp=old_timestamp)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            archiver.create_archive(
                before_date=before_date,
                archive_name="to_delete",
            )

            # Verify archive exists
            assert archiver.get_archive("to_delete") is not None

            # Delete archive
            deleted = archiver.delete_archive("to_delete")

            assert deleted is True
            assert archiver.get_archive("to_delete") is None

    def test_delete_archive_not_found(self):
        """Test deleting non-existent archive."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            BenchmarkDatabase(db_path)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            deleted = archiver.delete_archive("nonexistent")

            assert deleted is False

    def test_get_archive_summary(self):
        """Test getting archive summary."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            # Create and archive runs
            for i in range(3):
                timestamp = datetime.now(UTC) - timedelta(days=100 + i * 10)
                self._create_test_run(db, f"old_run_{i}", num_results=10, timestamp=timestamp)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            # Create archive
            before_date = (datetime.now(UTC) - timedelta(days=50)).isoformat()
            archiver.create_archive(before_date=before_date)

            summary = archiver.get_archive_summary()

            assert "archive_count" in summary
            assert "total_size_bytes" in summary
            assert "archive_directory" in summary
            assert summary["archive_count"] >= 1

    def test_custom_archive_name(self):
        """Test creating archive with custom name."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            old_timestamp = datetime.now(UTC) - timedelta(days=60)
            self._create_test_run(db, "old_run", timestamp=old_timestamp)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            result = archiver.create_archive(
                before_date=before_date,
                archive_name="custom_archive_name",
            )

            assert result.success is True
            assert "custom_archive_name" in result.archive_path


class TestArchiverEdgeCases:
    """Test edge cases for archiver."""

    def test_archive_with_system_info(self):
        """Test that system_info is properly archived."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            archive_dir = Path(tmpdir) / "archives"
            db = BenchmarkDatabase(db_path)

            # Create run with detailed system info
            old_timestamp = datetime.now(UTC) - timedelta(days=60)

            results = [BenchmarkResult(
                sample_id="sample",
                model_id="test_model",
                device="cpu",
                batch_size=8,
                duration_seconds=1.0,
                tokens_input=100,
                tokens_output=100,
                throughput_tokens_per_sec=100.0,
            )]

            run = BenchmarkRun(
                run_id="detailed_run",
                model_id="test_model",
                device="cpu",
                batch_sizes=[8],
                iterations=1,
                corpus_category="test",
                purpose="testing",
                tags=["test"],
                system_info=SystemInfo(
                    cpu_model="Intel i7-9700K",
                    cpu_cores=8,
                    total_ram_gb=32.0,
                    gpu_model="NVIDIA RTX 3080",
                    gpu_memory_gb=10.0,
                    os_name="Linux",
                    os_version="5.4.0",
                    python_version="3.10.0",
                    torch_version="2.0.0",
                ),
                results=results,
                total_duration_seconds=1.0,
                timestamp_utc=old_timestamp.isoformat(),
            )
            db.save_run(run)

            archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

            before_date = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            result = archiver.create_archive(
                before_date=before_date,
                archive_name="sys_info_test",
                delete_after_archive=True,
            )

            # Restore and verify system info
            restore_result = archiver.restore_archive("sys_info_test")
            assert restore_result.success is True
            assert "system_info" in restore_result.tables_restored

            restored_run = db.get_run("detailed_run")
            assert restored_run is not None
            assert restored_run.system_info.cpu_model == "Intel i7-9700K"
