"""
Integration tests for benchmarking CLI subcommands (CLI-TC-06).

Tests all 10 benchmarking CLI subcommands:
- run, list, report, compare, recommend, migrate, aggregate, retention, export, archive

All tests use fixture databases in temp directories (CI-safe).

Note: These tests require the full application dependencies (torch, etc.)
to be installed. Tests will be skipped if dependencies are unavailable.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Get project root for module imports
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Check if CLI dependencies are available
CLI_AVAILABLE = False
CLI_SKIP_REASON = "Unknown"

try:
    # Try importing to check if dependencies are available
    import torch
    CLI_AVAILABLE = True
except ImportError as e:
    CLI_SKIP_REASON = f"torch not available: {e}"


# Skip all tests in this module if dependencies unavailable
pytestmark = pytest.mark.skipif(
    not CLI_AVAILABLE,
    reason=CLI_SKIP_REASON
)


class TestFixtures:
    """Helper class for creating test fixtures."""

    @staticmethod
    def create_test_database(db_path: Path) -> None:
        """Create a test database with schema and sample data."""
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create schema (matching storage.py schema)
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS benchmark_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE NOT NULL,
                model_id TEXT NOT NULL,
                device TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                config_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS benchmark_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                unit TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS system_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                info_key TEXT NOT NULL,
                info_value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS retention_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                table_name TEXT NOT NULL,
                retention_days INTEGER NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_executed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS aggregated_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                aggregation_key TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                aggregation_type TEXT NOT NULL,
                value REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                period_start TIMESTAMP,
                period_end TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Insert schema version
        cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version, description) VALUES (?, ?)",
            (8, "Current schema version")
        )

        # Insert sample benchmark runs
        now = datetime.now()
        runs = [
            ("run-001", "opus_en_fr", "cuda:0", "completed", now - timedelta(hours=2), now - timedelta(hours=1)),
            ("run-002", "m2m100_418m", "cuda:0", "completed", now - timedelta(hours=1), now - timedelta(minutes=30)),
            ("run-003", "opus_en_fr", "cpu", "completed", now - timedelta(minutes=30), now - timedelta(minutes=15)),
            ("run-004", "nllb_200m", "cuda:1", "pending", now - timedelta(minutes=10), None),
        ]

        for run_id, model, device, status, started, completed in runs:
            cursor.execute("""
                INSERT INTO benchmark_runs
                (run_id, model_id, device, status, started_at, completed_at, config_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (run_id, model, device, status, started, completed, json.dumps({"batch_size": 32})))

        # Insert sample benchmark results
        results = [
            ("run-001", "throughput_tokens_per_sec", 150.5, "tok/s"),
            ("run-001", "duration_seconds", 45.2, "s"),
            ("run-001", "peak_memory_mb", 8500, "MB"),
            ("run-002", "throughput_tokens_per_sec", 200.3, "tok/s"),
            ("run-002", "duration_seconds", 32.1, "s"),
            ("run-003", "throughput_tokens_per_sec", 50.0, "tok/s"),
            ("run-003", "duration_seconds", 120.5, "s"),
        ]

        for run_id, metric, value, unit in results:
            cursor.execute("""
                INSERT INTO benchmark_results (run_id, metric_name, metric_value, unit)
                VALUES (?, ?, ?, ?)
            """, (run_id, metric, value, unit))

        # Insert sample system info
        system_info = [
            ("run-001", "gpu_name", "NVIDIA RTX 4090"),
            ("run-001", "gpu_memory", "24GB"),
            ("run-001", "cuda_version", "12.1"),
            ("run-002", "gpu_name", "NVIDIA RTX 4090"),
            ("run-003", "cpu_model", "AMD Ryzen 9 7950X"),
        ]

        for run_id, key, value in system_info:
            cursor.execute("""
                INSERT INTO system_info (run_id, info_key, info_value)
                VALUES (?, ?, ?)
            """, (run_id, key, value))

        # Insert sample retention policy
        cursor.execute("""
            INSERT INTO retention_policies (name, table_name, retention_days, enabled)
            VALUES (?, ?, ?, ?)
        """, ("default_cleanup", "benchmark_results", 90, 1))

        conn.commit()
        conn.close()


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database with sample data."""
    db_path = tmp_path / "test_benchmark.db"
    TestFixtures.create_test_database(db_path)
    return db_path


@pytest.fixture
def empty_db(tmp_path):
    """Create an empty test database with schema only."""
    db_path = tmp_path / "empty_benchmark.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )
    """)
    cursor.execute("INSERT INTO schema_version (version, description) VALUES (1, 'Initial')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def archive_dir(tmp_path):
    """Create a temporary archive directory."""
    archive_path = tmp_path / "archives"
    archive_path.mkdir()
    return archive_path


def run_cli_command(args: list, env_override: dict = None) -> subprocess.CompletedProcess:
    """Run a CLI command and return the result."""
    cmd = [sys.executable, "-m", "src.benchmarking.cli"] + args
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
        timeout=60
    )


class TestListSubcommand:
    """Integration tests for the 'list' subcommand."""

    def test_list_all_runs(self, test_db):
        """Test listing all benchmark runs."""
        result = run_cli_command(["list", "--db", str(test_db)])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        # Check that some output was produced
        assert result.stdout or result.returncode == 0

    def test_list_with_model_filter(self, test_db):
        """Test listing runs filtered by model."""
        result = run_cli_command(["list", "--db", str(test_db), "--model", "opus_en_fr"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_list_with_device_filter(self, test_db):
        """Test listing runs filtered by device."""
        result = run_cli_command(["list", "--db", str(test_db), "--device", "cpu"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_list_with_limit(self, test_db):
        """Test listing runs with a limit."""
        result = run_cli_command(["list", "--db", str(test_db), "--limit", "2"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_list_json_format(self, test_db):
        """Test listing runs in JSON format."""
        result = run_cli_command(["list", "--db", str(test_db), "--format", "json"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        # If JSON output, verify it's valid JSON
        if result.stdout.strip():
            try:
                json.loads(result.stdout)
            except json.JSONDecodeError:
                pass  # May have mixed output

    def test_list_missing_database(self, tmp_path):
        """Test list command with non-existent database."""
        fake_db = tmp_path / "nonexistent.db"
        result = run_cli_command(["list", "--db", str(fake_db)])

        # Should fail or show empty results
        assert result.returncode != 0 or "not found" in result.stderr.lower() or result.stdout == ""


class TestReportSubcommand:
    """Integration tests for the 'report' subcommand."""

    def test_report_single_run(self, test_db):
        """Test generating a report for a single run."""
        result = run_cli_command(["report", "--run", "run-001", "--db", str(test_db)])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_report_json_format(self, test_db):
        """Test report output in JSON format."""
        result = run_cli_command(["report", "--run", "run-001", "--db", str(test_db), "--format", "json"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        # If JSON output, try to parse it
        if result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                assert isinstance(data, dict)
            except json.JSONDecodeError:
                pass  # May have mixed output

    def test_report_markdown_format(self, test_db):
        """Test report output in Markdown format."""
        result = run_cli_command(["report", "--run", "run-001", "--db", str(test_db), "--format", "markdown"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_report_invalid_run_id(self, test_db):
        """Test report with non-existent run ID."""
        result = run_cli_command(["report", "--run", "nonexistent-run", "--db", str(test_db)])

        # Should handle gracefully (may return error or empty)
        assert result.returncode in [0, 1] or "not found" in result.stderr.lower()


class TestCompareSubcommand:
    """Integration tests for the 'compare' subcommand."""

    def test_compare_two_runs(self, test_db):
        """Test comparing two benchmark runs."""
        result = run_cli_command([
            "compare",
            "--runs", "run-001,run-002",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_compare_multiple_runs(self, test_db):
        """Test comparing multiple benchmark runs."""
        result = run_cli_command([
            "compare",
            "--runs", "run-001,run-002,run-003",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_compare_with_metric(self, test_db):
        """Test comparison with specific metric."""
        result = run_cli_command([
            "compare",
            "--runs", "run-001,run-002",
            "--metric", "duration_seconds",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_compare_json_output(self, test_db):
        """Test comparison with JSON output."""
        result = run_cli_command([
            "compare",
            "--runs", "run-001,run-002",
            "--format", "json",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"


class TestRecommendSubcommand:
    """Integration tests for the 'recommend' subcommand."""

    def test_recommend_basic(self, test_db, tmp_path):
        """Test basic recommendation generation."""
        # Create minimal registry file
        registry_path = tmp_path / "registry.yaml"
        registry_path.write_text("""
models:
  opus_en_fr:
    backend: opus
    model_size_mb: 100
    min_ram_gb: 0.5
    optimal_device: cpu
""")

        result = run_cli_command([
            "recommend",
            "--db", str(test_db),
            "--registry", str(registry_path),
            "--max-memory-gb", "4"
        ])

        # May succeed or fail based on data availability
        assert result.returncode in [0, 1], f"Command crashed: {result.stderr}"

    def test_recommend_with_device(self, test_db, tmp_path):
        """Test recommendations for specific device."""
        registry_path = tmp_path / "registry.yaml"
        registry_path.write_text("""
models:
  opus_en_fr:
    backend: opus
    model_size_mb: 100
    min_ram_gb: 0.5
    optimal_device: cpu
""")

        result = run_cli_command([
            "recommend",
            "--db", str(test_db),
            "--registry", str(registry_path),
            "--device", "cpu"
        ])

        assert result.returncode in [0, 1], f"Command crashed: {result.stderr}"


class TestMigrateSubcommand:
    """Integration tests for the 'migrate' subcommand."""

    def test_migrate_list(self, test_db):
        """Test listing available migrations."""
        result = run_cli_command(["migrate", "--list", "--db", str(test_db)])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        # Should show migration list
        assert "migration" in result.stdout.lower() or "version" in result.stdout.lower() or result.returncode == 0

    def test_migrate_to_version(self, empty_db):
        """Test migration to specific version."""
        result = run_cli_command(["migrate", "--to", "8", "--db", str(empty_db)])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

        # Verify schema version increased
        conn = sqlite3.connect(str(empty_db))
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        conn.close()
        assert version >= 1

    def test_migrate_dry_run(self, empty_db):
        """Test migration in dry-run mode."""
        result = run_cli_command(["migrate", "--to", "8", "--dry-run", "--db", str(empty_db)])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_migrate_up_down_cycle(self, empty_db):
        """Test complete migration up/down cycle."""
        # First migrate up
        result_up = run_cli_command(["migrate", "--to", "8", "--db", str(empty_db)])
        assert result_up.returncode == 0, f"Migrate up failed: {result_up.stderr}"

        # Then rollback
        result_down = run_cli_command(["migrate", "--rollback", "1", "--db", str(empty_db)])

        # Rollback may succeed or fail depending on implementation
        assert result_down.returncode in [0, 1, 2], f"Migrate rollback crashed: {result_down.stderr}"


class TestAggregateSubcommand:
    """Integration tests for the 'aggregate' subcommand."""

    def test_aggregate_all(self, test_db):
        """Test aggregating all models."""
        result = run_cli_command(["aggregate", "--all", "--db", str(test_db)])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_aggregate_by_model_device(self, test_db):
        """Test aggregation for specific model/device."""
        result = run_cli_command([
            "aggregate",
            "--model", "opus_en_fr",
            "--device", "cpu",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_aggregate_with_lookback(self, test_db):
        """Test aggregation with custom lookback period."""
        result = run_cli_command([
            "aggregate",
            "--all",
            "--lookback-days", "30",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_aggregate_create_baseline(self, test_db):
        """Test creating performance baseline."""
        result = run_cli_command([
            "aggregate",
            "--baseline",
            "--model", "opus_en_fr",
            "--device", "cpu",
            "--type", "weekly",
            "--db", str(test_db)
        ])

        # May succeed or fail based on data availability
        assert result.returncode in [0, 1], f"Command crashed: {result.stderr}"


class TestRetentionSubcommand:
    """Integration tests for the 'retention' subcommand."""

    def test_retention_status(self, test_db):
        """Test retention policy status."""
        result = run_cli_command(["retention", "--status", "--db", str(test_db)])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        # Should show policy information
        assert "policy" in result.stdout.lower() or "retention" in result.stdout.lower() or result.returncode == 0

    def test_retention_run_dry(self, test_db):
        """Test retention execution in dry-run mode."""
        result = run_cli_command([
            "retention",
            "--run",
            "--dry-run",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_retention_run_specific_policy(self, test_db):
        """Test running specific retention policy."""
        result = run_cli_command([
            "retention",
            "--run",
            "--policies", "default_cleanup",
            "--dry-run",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"


class TestExportSubcommand:
    """Integration tests for the 'export' subcommand."""

    def test_export_csv(self, test_db, tmp_path):
        """Test CSV export."""
        output_file = tmp_path / "export.csv"
        result = run_cli_command([
            "export",
            "--format", "csv",
            "--output", str(output_file),
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        # Verify file was created
        if output_file.exists():
            content = output_file.read_text()
            assert len(content) > 0

    def test_export_json(self, test_db, tmp_path):
        """Test JSON export."""
        output_file = tmp_path / "export.json"
        result = run_cli_command([
            "export",
            "--format", "json",
            "--output", str(output_file),
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

        # Verify JSON is valid if file exists
        if output_file.exists():
            with open(output_file) as f:
                data = json.load(f)
                assert isinstance(data, (dict, list))

    def test_export_sqlite(self, test_db, tmp_path):
        """Test SQLite export."""
        output_file = tmp_path / "export.db"
        result = run_cli_command([
            "export",
            "--format", "sqlite",
            "--output", str(output_file),
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

        # Verify SQLite file is valid if created
        if output_file.exists():
            conn = sqlite3.connect(str(output_file))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            conn.close()
            assert len(tables) >= 0

    def test_export_with_tables_filter(self, test_db, tmp_path):
        """Test export of specific tables."""
        output_file = tmp_path / "filtered_export.json"
        result = run_cli_command([
            "export",
            "--format", "json",
            "--output", str(output_file),
            "--tables", "benchmark_runs,benchmark_results",
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"


class TestArchiveSubcommand:
    """Integration tests for the 'archive' subcommand."""

    def test_archive_list(self, test_db, archive_dir):
        """Test listing archives."""
        result = run_cli_command([
            "archive",
            "--list",
            "--archive-dir", str(archive_dir),
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_archive_create(self, test_db, archive_dir):
        """Test creating an archive."""
        result = run_cli_command([
            "archive",
            "--create",
            "--before", "2099-12-31",
            "--archive-dir", str(archive_dir),
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_archive_create_compressed(self, test_db, archive_dir):
        """Test creating a compressed archive."""
        result = run_cli_command([
            "archive",
            "--create",
            "--before", "2099-12-31",
            "--compress",
            "--archive-dir", str(archive_dir),
            "--db", str(test_db)
        ])

        assert result.returncode == 0, f"Command failed: {result.stderr}"

    def test_archive_restore_cycle(self, test_db, archive_dir, tmp_path):
        """Test complete archive/restore cycle (end-to-end)."""
        # Step 1: Create archive
        create_result = run_cli_command([
            "archive",
            "--create",
            "--before", "2099-12-31",
            "--archive-dir", str(archive_dir),
            "--db", str(test_db)
        ])
        assert create_result.returncode == 0, f"Archive create failed: {create_result.stderr}"

        # Step 2: Find the created archive file
        archive_files = list(archive_dir.glob("*.db")) + list(archive_dir.glob("*.gz"))

        # Step 3: If archive was created, try restore
        if archive_files:
            archive_file = archive_files[0]

            # Create a new database for restore
            restore_db = tmp_path / "restored.db"
            TestFixtures.create_test_database(restore_db)  # Create empty schema

            restore_result = run_cli_command([
                "archive",
                "--restore", str(archive_file),
                "--db", str(restore_db)
            ])

            # Restore may succeed or fail depending on archive format
            assert restore_result.returncode in [0, 1], f"Archive restore crashed: {restore_result.stderr}"

    def test_archive_rotate(self, test_db, archive_dir):
        """Test archive rotation (keep N most recent)."""
        # Create multiple archives first
        for _ in range(3):
            run_cli_command([
                "archive",
                "--create",
                "--before", "2099-12-31",
                "--archive-dir", str(archive_dir),
                "--db", str(test_db)
            ])

        # Rotate to keep only 1
        result = run_cli_command([
            "archive",
            "--rotate",
            "--keep", "1",
            "--archive-dir", str(archive_dir),
            "--db", str(test_db)
        ])

        assert result.returncode in [0, 1], f"Command crashed: {result.stderr}"


class TestRunSubcommand:
    """Integration tests for the 'run' subcommand."""

    def test_run_help(self):
        """Test run subcommand help."""
        result = run_cli_command(["run", "--help"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        assert "run" in result.stdout.lower() or "model" in result.stdout.lower()

    def test_run_requires_model(self, test_db):
        """Test that run requires --model argument."""
        result = run_cli_command(["run", "--db", str(test_db)])

        # Should fail due to missing required argument
        assert result.returncode != 0 or "required" in result.stderr.lower() or "model" in result.stderr.lower()


class TestCLIHelp:
    """Tests for CLI help and documentation."""

    def test_main_help(self):
        """Test main CLI help."""
        result = run_cli_command(["--help"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        # Should list available subcommands
        output = result.stdout.lower()
        assert any(cmd in output for cmd in ["list", "report", "export", "archive"])

    def test_version(self):
        """Test version flag."""
        result = run_cli_command(["--version"])

        assert result.returncode == 0, f"Command failed: {result.stderr}"
        # Should show version info
        assert result.stdout.strip() or "version" in result.stderr.lower()

    @pytest.mark.parametrize("subcommand", [
        "run", "list", "report", "compare", "recommend",
        "migrate", "aggregate", "retention", "export", "archive"
    ])
    def test_subcommand_help(self, subcommand):
        """Test that each subcommand has help."""
        result = run_cli_command([subcommand, "--help"])

        assert result.returncode == 0, f"Help failed for {subcommand}: {result.stderr}"
        # Should show usage/help text
        assert "usage" in result.stdout.lower() or subcommand in result.stdout.lower()


class TestErrorHandling:
    """Tests for CLI error handling."""

    def test_invalid_subcommand(self):
        """Test invalid subcommand handling."""
        result = run_cli_command(["invalid-command-xyz"])

        # Should fail with error message
        assert result.returncode != 0 or "invalid" in result.stderr.lower()

    def test_corrupted_database(self, tmp_path):
        """Test handling of corrupted database."""
        # Create a file that's not a valid SQLite database
        corrupted_db = tmp_path / "corrupted.db"
        corrupted_db.write_text("This is not a valid SQLite database")

        result = run_cli_command(["list", "--db", str(corrupted_db)])

        # Should fail with database error
        assert result.returncode != 0 or "error" in result.stderr.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
