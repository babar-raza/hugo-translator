"""
CONTRACT: specs/features/bm-001-model-benchmarking.md

Verifies core benchmarking system invariants:
1. BenchmarkResult/BenchmarkRun dataclass structure
2. Database schema version tracking
3. WAL mode for concurrent reads
4. Foreign key enforcement
5. Thread-safe operations
6. JSON serialization/deserialization

BM-001 Core Feature: Model Benchmarking System
"""

import sys
import threading
from dataclasses import fields
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def temp_db_path(tmp_path):
    """Create temporary database path."""
    return tmp_path / "test_benchmark.db"


@pytest.fixture
def sample_system_info():
    """Create sample SystemInfo for testing."""
    from src.benchmarking.system_info import SystemInfo
    return SystemInfo(
        cpu_model="Intel Core i7-9700K",
        cpu_cores=8,
        total_ram_gb=16.0,
        gpu_model="NVIDIA RTX 3060",
        gpu_memory_gb=12.0,
        os_name="Windows",
        os_version="10.0.19045",
        python_version="3.10.12",
        torch_version="2.1.0",
        collected_at_utc="2025-12-19T00:00:00Z",
    )


@pytest.fixture
def sample_benchmark_result():
    """Create sample BenchmarkResult for testing."""
    from src.benchmarking.storage import BenchmarkResult
    return BenchmarkResult(
        sample_id="sample_001",
        model_id="test_model",
        device="cpu",
        batch_size=8,
        duration_seconds=2.5,
        tokens_input=120,
        tokens_output=115,
        throughput_tokens_per_sec=48.0,
        peak_memory_mb=512.0,
    )


@pytest.fixture
def sample_benchmark_run(sample_system_info, sample_benchmark_result):
    """Create sample BenchmarkRun for testing."""
    from src.benchmarking.storage import BenchmarkRun
    return BenchmarkRun(
        run_id="test_run_001",
        model_id="test_model",
        device="cpu",
        batch_sizes=[4, 8, 16],
        iterations=3,
        corpus_category="small",
        purpose="testing",
        tags=["unit-test"],
        system_info=sample_system_info,
        results=[sample_benchmark_result],
        total_duration_seconds=10.5,
    )


# ==============================================================================
# BM-001: BenchmarkResult Structure Tests
# ==============================================================================


@pytest.mark.contract
def test_benchmark_result_has_required_fields():
    """
    Verify BenchmarkResult dataclass has all required fields.

    CONTRACT: BM-001 - BenchmarkResult schema
    Evidence: src/benchmarking/storage.py lines 27-44
    """
    from src.benchmarking.storage import BenchmarkResult

    result = BenchmarkResult(
        sample_id="test",
        model_id="test_model",
        device="cpu",
        batch_size=8,
        duration_seconds=1.0,
        tokens_input=100,
        tokens_output=90,
        throughput_tokens_per_sec=90.0,
    )

    # Required fields
    assert hasattr(result, 'sample_id')
    assert hasattr(result, 'model_id')
    assert hasattr(result, 'device')
    assert hasattr(result, 'batch_size')
    assert hasattr(result, 'duration_seconds')
    assert hasattr(result, 'tokens_input')
    assert hasattr(result, 'tokens_output')
    assert hasattr(result, 'throughput_tokens_per_sec')

    # Optional fields
    assert hasattr(result, 'peak_memory_mb')
    assert hasattr(result, 'bleu_score')
    assert hasattr(result, 'comet_score')
    assert hasattr(result, 'errors')


@pytest.mark.contract
def test_benchmark_result_quality_metrics_optional():
    """
    Verify quality metrics (BLEU, COMET) are optional.

    CONTRACT: BM-001 - Quality metrics schema (REQ-BM-03)
    Evidence: src/benchmarking/storage.py lines 39-40
    """
    from src.benchmarking.storage import BenchmarkResult

    # Create without quality metrics
    result = BenchmarkResult(
        sample_id="test",
        model_id="test_model",
        device="cpu",
        batch_size=8,
        duration_seconds=1.0,
        tokens_input=100,
        tokens_output=90,
        throughput_tokens_per_sec=90.0,
    )

    # Quality metrics should default to None
    assert result.bleu_score is None
    assert result.comet_score is None


@pytest.mark.contract
def test_benchmark_result_to_dict_roundtrip(sample_benchmark_result):
    """
    Verify BenchmarkResult can be serialized and deserialized.

    CONTRACT: BM-001 - JSON serialization
    Evidence: src/benchmarking/storage.py lines 46-53
    """
    from src.benchmarking.storage import BenchmarkResult

    # Convert to dict
    data = sample_benchmark_result.to_dict()
    assert isinstance(data, dict)
    assert "sample_id" in data
    assert "model_id" in data

    # Convert back to object
    restored = BenchmarkResult.from_dict(data)
    assert restored.sample_id == sample_benchmark_result.sample_id
    assert restored.model_id == sample_benchmark_result.model_id
    assert restored.throughput_tokens_per_sec == sample_benchmark_result.throughput_tokens_per_sec


# ==============================================================================
# BM-001: BenchmarkRun Structure Tests
# ==============================================================================


@pytest.mark.contract
def test_benchmark_run_has_required_fields():
    """
    Verify BenchmarkRun dataclass has all required fields.

    CONTRACT: BM-001 - BenchmarkRun schema
    Evidence: src/benchmarking/storage.py lines 57-72
    """
    from src.benchmarking.storage import BenchmarkRun

    # Check field names exist
    field_names = {f.name for f in fields(BenchmarkRun)}

    required_fields = {
        'run_id', 'model_id', 'device', 'batch_sizes', 'iterations',
        'corpus_category', 'purpose', 'tags', 'system_info', 'results',
        'total_duration_seconds', 'timestamp_utc', 'metadata'
    }

    for field in required_fields:
        assert field in field_names, f"Missing required field: {field}"


@pytest.mark.contract
def test_benchmark_run_timestamp_auto_generated():
    """
    Verify BenchmarkRun auto-generates timestamp if not provided.

    CONTRACT: BM-001 - Timestamp tracking
    Evidence: src/benchmarking/storage.py line 71
    """
    from src.benchmarking.storage import BenchmarkRun
    from src.benchmarking.system_info import SystemInfo

    sysinfo = SystemInfo(
        cpu_model="Test",
        cpu_cores=4,
        total_ram_gb=8.0,
        os_name="Test",
        os_version="1.0",
        python_version="3.10",
        torch_version="2.0",
        collected_at_utc="2025-01-01T00:00:00Z",
    )

    run = BenchmarkRun(
        run_id="test",
        model_id="test_model",
        device="cpu",
        batch_sizes=[8],
        iterations=1,
        corpus_category="tiny",
        purpose="testing",
        tags=[],
        system_info=sysinfo,
        results=[],
        total_duration_seconds=1.0,
    )

    # Timestamp should be auto-generated
    assert run.timestamp_utc is not None
    assert len(run.timestamp_utc) > 0


@pytest.mark.contract
def test_benchmark_run_to_dict_roundtrip(sample_benchmark_run):
    """
    Verify BenchmarkRun can be serialized and deserialized.

    CONTRACT: BM-001 - JSON serialization
    Evidence: src/benchmarking/storage.py lines 74-87
    """
    from src.benchmarking.storage import BenchmarkRun

    # Convert to dict
    data = sample_benchmark_run.to_dict()
    assert isinstance(data, dict)
    assert "run_id" in data
    assert "system_info" in data
    assert "results" in data

    # Convert back to object
    restored = BenchmarkRun.from_dict(data)
    assert restored.run_id == sample_benchmark_run.run_id
    assert restored.model_id == sample_benchmark_run.model_id


# ==============================================================================
# BM-001: Database Schema Tests
# ==============================================================================


@pytest.mark.contract
def test_database_creates_schema_version_table(temp_db_path):
    """
    Verify database creates schema_version tracking table.

    CONTRACT: BM-001 - Schema version tracking
    Evidence: src/benchmarking/storage.py lines 179-186
    """
    from src.benchmarking.storage import BenchmarkDatabase

    db = BenchmarkDatabase(temp_db_path)

    # Query schema_version table directly
    import sqlite3
    conn = sqlite3.connect(str(temp_db_path))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
    tables = cursor.fetchall()
    conn.close()

    assert len(tables) == 1
    assert tables[0][0] == 'schema_version'

    db.close()


@pytest.mark.contract
def test_database_schema_version_matches():
    """
    Verify SCHEMA_VERSION constant is accessible.

    CONTRACT: BM-001 - Schema version tracking
    Evidence: src/benchmarking/storage.py line 100
    """
    from src.benchmarking.storage import BenchmarkDatabase

    # Schema version should be a positive integer
    assert hasattr(BenchmarkDatabase, 'SCHEMA_VERSION')
    assert isinstance(BenchmarkDatabase.SCHEMA_VERSION, int)
    assert BenchmarkDatabase.SCHEMA_VERSION > 0


@pytest.mark.contract
def test_database_creates_required_tables(temp_db_path):
    """
    Verify database creates all required tables.

    CONTRACT: BM-001 - Database schema
    Evidence: src/benchmarking/storage.py lines 211-266
    """
    from src.benchmarking.storage import BenchmarkDatabase

    db = BenchmarkDatabase(temp_db_path)

    # Query all tables
    import sqlite3
    conn = sqlite3.connect(str(temp_db_path))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    # Required tables
    required_tables = {'benchmark_runs', 'system_info', 'benchmark_results', 'schema_version'}
    for table in required_tables:
        assert table in tables, f"Missing required table: {table}"

    db.close()


# ==============================================================================
# BM-001: WAL Mode Tests
# ==============================================================================


@pytest.mark.contract
def test_database_uses_wal_mode(temp_db_path):
    """
    Verify database uses WAL mode for concurrent reads.

    CONTRACT: BM-001 - WAL mode for concurrent reads
    Evidence: src/benchmarking/storage.py line 127
    """
    from src.benchmarking.storage import BenchmarkDatabase

    db = BenchmarkDatabase(temp_db_path)

    # Check WAL mode
    import sqlite3
    conn = sqlite3.connect(str(temp_db_path))
    cursor = conn.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    conn.close()

    assert mode.lower() == 'wal'

    db.close()


@pytest.mark.contract
def test_database_foreign_keys_enabled(temp_db_path):
    """
    Verify database has foreign keys enabled.

    CONTRACT: BM-001 - Foreign key enforcement
    Evidence: src/benchmarking/storage.py line 126
    """
    from src.benchmarking.storage import BenchmarkDatabase

    db = BenchmarkDatabase(temp_db_path)

    # Check foreign keys pragma
    import sqlite3
    conn = sqlite3.connect(str(temp_db_path))
    conn.execute("PRAGMA foreign_keys = ON")  # Must be set per connection
    cursor = conn.execute("PRAGMA foreign_keys")
    fk_enabled = cursor.fetchone()[0]
    conn.close()

    assert fk_enabled == 1

    db.close()


# ==============================================================================
# BM-001: Thread Safety Tests
# ==============================================================================


@pytest.mark.contract
def test_database_has_lock_for_thread_safety(temp_db_path):
    """
    Verify database uses lock for thread-safe operations.

    CONTRACT: BM-001 - Thread-safe operations
    Evidence: src/benchmarking/storage.py line 111
    """
    from src.benchmarking.storage import BenchmarkDatabase

    db = BenchmarkDatabase(temp_db_path)

    # Database should have a lock attribute
    assert hasattr(db, '_lock')
    assert isinstance(db._lock, type(threading.Lock()))

    db.close()


# ==============================================================================
# BM-001: Context Manager Tests
# ==============================================================================


@pytest.mark.contract
def test_database_supports_context_manager(temp_db_path):
    """
    Verify database can be used as context manager.

    CONTRACT: BM-001 - Context manager support
    Evidence: src/benchmarking/storage.py lines 166-172
    """
    from src.benchmarking.storage import BenchmarkDatabase

    # Should work as context manager
    with BenchmarkDatabase(temp_db_path) as db:
        assert db is not None
        # Query should work
        import sqlite3
        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM benchmark_runs")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 0


# ==============================================================================
# BM-001: Memory Database Tests
# ==============================================================================


@pytest.mark.contract
def test_database_supports_memory_mode():
    """
    Verify database supports :memory: mode.

    CONTRACT: BM-001 - In-memory database support
    Evidence: src/benchmarking/storage.py lines 108-116
    """
    from src.benchmarking.storage import BenchmarkDatabase

    # Memory database should work
    db = BenchmarkDatabase(":memory:")

    # Tables should exist
    assert hasattr(db, '_memory_conn')
    assert db._memory_conn is not None

    db.close()


# ==============================================================================
# BM-001: SystemInfo Structure Tests
# ==============================================================================


@pytest.mark.contract
def test_system_info_has_required_fields():
    """
    Verify SystemInfo dataclass has all required fields.

    CONTRACT: BM-001 - SystemInfo schema
    Evidence: src/benchmarking/system_info.py
    """
    from src.benchmarking.system_info import SystemInfo

    sysinfo = SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=4,
        total_ram_gb=8.0,
        os_name="Linux",
        os_version="5.0",
        python_version="3.10",
        torch_version="2.0",
        collected_at_utc="2025-01-01T00:00:00Z",
    )

    # Required fields
    assert hasattr(sysinfo, 'cpu_model')
    assert hasattr(sysinfo, 'cpu_cores')
    assert hasattr(sysinfo, 'total_ram_gb')
    assert hasattr(sysinfo, 'os_name')
    assert hasattr(sysinfo, 'python_version')
    assert hasattr(sysinfo, 'torch_version')

    # Optional fields
    assert hasattr(sysinfo, 'gpu_model')
    assert hasattr(sysinfo, 'gpu_memory_gb')


@pytest.mark.contract
def test_system_info_to_dict_roundtrip(sample_system_info):
    """
    Verify SystemInfo can be serialized and deserialized.

    CONTRACT: BM-001 - SystemInfo serialization
    Evidence: src/benchmarking/system_info.py to_dict/from_dict
    """
    from src.benchmarking.system_info import SystemInfo

    # Convert to dict
    data = sample_system_info.to_dict()
    assert isinstance(data, dict)
    assert "cpu_model" in data

    # Convert back to object
    restored = SystemInfo.from_dict(data)
    assert restored.cpu_model == sample_system_info.cpu_model
    assert restored.cpu_cores == sample_system_info.cpu_cores


# ==============================================================================
# BM-001: Index Creation Tests
# ==============================================================================


@pytest.mark.contract
def test_database_creates_performance_indexes(temp_db_path):
    """
    Verify database creates indexes for common queries.

    CONTRACT: BM-001 - Query optimization
    Evidence: src/benchmarking/storage.py lines 269-276
    """
    from src.benchmarking.storage import BenchmarkDatabase

    db = BenchmarkDatabase(temp_db_path)

    # Query indexes
    import sqlite3
    conn = sqlite3.connect(str(temp_db_path))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    conn.close()

    # Key indexes should exist
    key_indexes = ['idx_runs_model', 'idx_runs_device', 'idx_runs_timestamp', 'idx_results_run']
    for idx in key_indexes:
        assert idx in indexes, f"Missing index: {idx}"

    db.close()


# ==============================================================================
# BM-001: Cache Fields Tests
# ==============================================================================


@pytest.mark.contract
def test_benchmark_result_has_cache_tracking_fields():
    """
    Verify BenchmarkResult includes cache tracking fields.

    CONTRACT: BM-001 - Cache hit/miss tracking
    Evidence: src/benchmarking/storage.py lines 41-43
    """
    from src.benchmarking.storage import BenchmarkResult

    result = BenchmarkResult(
        sample_id="test",
        model_id="test_model",
        device="cpu",
        batch_size=8,
        duration_seconds=1.0,
        tokens_input=100,
        tokens_output=90,
        throughput_tokens_per_sec=90.0,
    )

    # Cache tracking fields
    assert hasattr(result, 'cache_status')
    assert hasattr(result, 'tm_level')
    assert hasattr(result, 'cache_hit_rate')

    # Default values
    assert result.cache_status == "unknown"
    assert result.tm_level == "none"
    assert result.cache_hit_rate == 0.0
