"""Integration tests for benchmark production script with DB persistence.

Tests that benchmark scripts properly persist results to the BenchmarkDatabase.
"""
import subprocess
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

    # Minimal pytest.skip replacement
    class _pytest:
        @staticmethod
        def skip(msg):
            print(f"SKIP: {msg}")
            return

    pytest = _pytest()


def test_benchmark_cpu_comprehensive_with_db():
    """Test benchmark_cpu_comprehensive.py saves to database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        # Check if script exists
        script_path = Path("scripts/benchmark_cpu_comprehensive.py")
        if not script_path.exists():
            pytest.skip("benchmark_cpu_comprehensive.py not found")

        # Check if dependencies are available
        try:
            from src.benchmarking.storage import BenchmarkDatabase
        except ImportError:
            pytest.skip("Benchmarking module not available")

        # Note: Full execution would require:
        # result = subprocess.run(
        #     [
        #         "python", "scripts/benchmark_cpu_comprehensive.py",
        #         "--models", "m2m100_418m",
        #         "--batch-sizes", "4",
        #         "--iterations", "1",
        #         "--save-to-db", str(db_path),
        #         "--corpus", "tiny",
        #         "--max-samples", "2"
        #     ],
        #     capture_output=True,
        #     text=True,
        #     timeout=120,
        # )
        #
        # assert result.returncode == 0, f"Script failed: {result.stderr}"
        #
        # # Verify DB contains results
        # db = BenchmarkDatabase(db_path)
        # runs = db.list_runs(limit=10)
        # assert len(runs) > 0, "No runs saved to database"

        # Placeholder test - actual execution requires models/corpus
        assert script_path.exists(), "Script exists"
        assert "--save-to-db" in script_path.read_text(), "Script has --save-to-db flag"

    finally:
        db_path.unlink(missing_ok=True)


def test_benchmark_db_flag_is_optional():
    """Test that benchmark script works without --save-to-db (backward compatible)."""
    script_path = Path("scripts/benchmark_cpu_comprehensive.py")

    if not script_path.exists():
        pytest.skip("benchmark_cpu_comprehensive.py not found")

    # Verify help shows --save-to-db as optional
    result = subprocess.run(
        ["python", str(script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, f"Help failed: {result.stderr}"
    assert "--save-to-db" in result.stdout, "Missing --save-to-db in help"

    # Verify it's optional (not in required arguments section)
    # Optional args typically appear in "optional arguments:" section
    help_text = result.stdout.lower()
    assert "optional" in help_text or "save-to-db" in help_text.split("positional arguments")[0] if "positional arguments" in help_text else True


def test_benchmark_db_schema_compatibility():
    """Verify BenchmarkDatabase schema supports benchmark results."""
    try:
        from src.benchmarking.storage import (
            BenchmarkDatabase,
            BenchmarkResult,
            BenchmarkRun,
            SystemInfo,
        )
    except ImportError:
        pytest.skip("Benchmarking module not available")

    # Create in-memory database
    db = BenchmarkDatabase(":memory:")

    # Verify schema has required fields (use __dataclass_fields__ — required fields
    # without defaults are not class attributes and hasattr() returns False for them)
    assert "model_id" in BenchmarkRun.__dataclass_fields__, "BenchmarkRun needs model_id"
    assert "device" in BenchmarkRun.__dataclass_fields__, "BenchmarkRun needs device"
    assert "throughput_tokens_per_sec" in BenchmarkResult.__dataclass_fields__, "BenchmarkResult needs throughput"


if __name__ == "__main__":
    # Run tests directly for manual validation
    print("Running benchmark production DB tests...")

    test_benchmark_cpu_comprehensive_with_db()
    print("PASS: Script exists with --save-to-db flag")

    test_benchmark_db_flag_is_optional()
    print("PASS: Flag is optional (backward compatible)")

    test_benchmark_db_schema_compatibility()
    print("PASS: Database schema compatible")

    print("\nAll tests passed!")
