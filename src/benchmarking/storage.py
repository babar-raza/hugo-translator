"""SQLite storage layer for benchmark persistence.

This module provides the BenchmarkDatabase class for storing and retrieving
benchmark runs with WAL mode for concurrent read safety.

Schema:
- benchmark_runs: Core run metadata
- system_info: Hardware/software configuration per run
- benchmark_results: Per-sample performance metrics
"""

import json
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.benchmarking.system_info import SystemInfo

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Single benchmark sample result."""

    sample_id: str
    model_id: str
    device: str
    batch_size: int
    duration_seconds: float
    tokens_input: int
    tokens_output: int
    throughput_tokens_per_sec: float
    src_lang: str = "en"  # Source language (ISO 639-1 code)
    tgt_lang: str = "ru"  # Target language (ISO 639-1 code)
    peak_memory_mb: Optional[float] = None
    bleu_score: Optional[float] = None
    comet_score: Optional[float] = None
    cache_status: str = "unknown"  # hit, miss, cold, disabled, unknown
    tm_level: str = "none"  # l1, l2, l3, none
    cache_hit_rate: float = 0.0  # 0.0 to 1.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkResult":
        """Create BenchmarkResult from dictionary."""
        return cls(**data)


@dataclass
class BenchmarkRun:
    """Complete benchmark run record."""

    run_id: str
    model_id: str
    device: str
    batch_sizes: List[int]
    iterations: int
    corpus_category: Optional[str]
    purpose: str
    tags: List[str]
    system_info: SystemInfo
    results: List[BenchmarkResult]
    total_duration_seconds: float
    src_lang: str = "en"  # Source language for this run
    tgt_lang: str = "ru"  # Target language for this run
    timestamp_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["system_info"] = self.system_info.to_dict()
        data["results"] = [r.to_dict() for r in self.results]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkRun":
        """Create BenchmarkRun from dictionary."""
        data = data.copy()
        data["system_info"] = SystemInfo.from_dict(data["system_info"])
        data["results"] = [BenchmarkResult.from_dict(r) for r in data["results"]]
        return cls(**data)


class BenchmarkDatabase:
    """SQLite database for benchmark persistence.

    Features:
    - WAL mode for concurrent reads
    - Foreign key enforcement
    - Thread-safe operations
    - JSON export/import
    """

    SCHEMA_VERSION = 9

    def __init__(self, db_path: Path | str):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Keep persistent connection for :memory: databases
        self._memory_conn = None
        if self.db_path == ":memory:":
            self._memory_conn = self._create_connection()
        self._init_db()
        logger.info(f"Initialized BenchmarkDatabase at {self.db_path}")

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with proper settings.

        Returns:
            Configured SQLite connection
        """
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection (reuses :memory: connection).

        Returns:
            Configured SQLite connection
        """
        if self._memory_conn is not None:
            return self._memory_conn
        return self._create_connection()

    def _close_connection(self, conn: sqlite3.Connection) -> None:
        """Close a database connection (skips :memory: connection).

        Args:
            conn: Connection to close
        """
        if conn is not self._memory_conn:
            # Checkpoint WAL to prevent file locking issues on Windows
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

    def close(self) -> None:
        """Close all database connections and checkpoint WAL.

        Call this before deleting database files to ensure WAL is flushed.
        """
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
        elif self.db_path != ":memory:":
            # For file-based databases, checkpoint WAL before final close
            conn = self._create_connection()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

    def __enter__(self) -> "BenchmarkDatabase":
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager, closing connections."""
        self.close()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._lock:
            conn = self._get_connection()
            try:
                # Schema version tracking
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                """
                )

                # Check current version
                cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
                row = cursor.fetchone()
                current_version = row[0] if row else 0

                if current_version < self.SCHEMA_VERSION:
                    self._apply_migrations(conn, current_version)

                conn.commit()
                logger.info(f"Database schema at version {self.SCHEMA_VERSION}")
            finally:
                self._close_connection(conn)

    def _apply_migrations(self, conn: sqlite3.Connection, from_version: int) -> None:
        """Apply database migrations.

        Args:
            conn: Database connection
            from_version: Current schema version
        """
        if from_version < 1:
            # Initial schema
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    run_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    device TEXT NOT NULL,
                    batch_sizes TEXT NOT NULL,
                    iterations INTEGER NOT NULL,
                    corpus_category TEXT,
                    purpose TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    total_duration_seconds REAL NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
            """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_info (
                    run_id TEXT PRIMARY KEY,
                    cpu_model TEXT NOT NULL,
                    cpu_cores INTEGER NOT NULL,
                    total_ram_gb REAL NOT NULL,
                    gpu_model TEXT,
                    gpu_vram_gb REAL,
                    os_name TEXT NOT NULL,
                    os_version TEXT NOT NULL,
                    python_version TEXT NOT NULL,
                    torch_version TEXT NOT NULL,
                    transformers_version TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
                )
            """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sample_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    device TEXT NOT NULL,
                    batch_size INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    tokens_input INTEGER NOT NULL,
                    tokens_output INTEGER NOT NULL,
                    throughput_tokens_per_sec REAL NOT NULL,
                    peak_memory_mb REAL,
                    errors TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
                )
            """
            )

            # Indexes for common queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_model ON benchmark_runs(model_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_device ON benchmark_runs(device)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON benchmark_runs(timestamp_utc)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_results_run ON benchmark_results(run_id)")

            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (1, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 1")

        if from_version < 2:
            # v2: Add composite indices for query optimization (BM-01)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_model_device ON benchmark_runs(model_id, device)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_model_device_timestamp ON benchmark_runs(model_id, device, timestamp_utc)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sysinfo_cpu_ram ON system_info(cpu_cores, total_ram_gb)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_results_throughput ON benchmark_results(throughput_tokens_per_sec)"
            )
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (2, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 2")

        if from_version < 3:
            # v3: Add recommendation_feedback table (BM-03)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recommendation_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    recommendation_id TEXT NOT NULL,
                    model_id_recommended TEXT NOT NULL,
                    model_id_used TEXT NOT NULL,
                    device_recommended TEXT NOT NULL,
                    device_used TEXT NOT NULL,
                    predicted_throughput REAL NOT NULL,
                    actual_throughput REAL NOT NULL,
                    predicted_memory_mb REAL NOT NULL,
                    actual_memory_mb REAL NOT NULL,
                    success INTEGER NOT NULL,
                    quality_score REAL,
                    failure_reason TEXT,
                    timestamp_utc TEXT NOT NULL,
                    system_info_json TEXT NOT NULL,
                    FOREIGN KEY (recommendation_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
                )
                """
            )
            # Create indices for efficient queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_recommendation "
                "ON recommendation_feedback(recommendation_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_model "
                "ON recommendation_feedback(model_id_recommended)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_timestamp "
                "ON recommendation_feedback(timestamp_utc)"
            )
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (3, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 3")

        if from_version < 4:
            # v4: Add recommendation_weights table (BM-03)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recommendation_weights (
                    weight_id TEXT PRIMARY KEY,
                    timestamp_utc TEXT NOT NULL,
                    weights_json TEXT NOT NULL
                )
                """
            )
            # Create index for timestamp lookup
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_weights_timestamp "
                "ON recommendation_weights(timestamp_utc)"
            )
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (4, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 4")

        if from_version < 5:
            # v5: Extend system_info with comprehensive SystemInfo fields (SR-02)
            # Add extended hardware context fields from src.benchmarking.system_info.SystemInfo

            # GPU extended fields
            conn.execute("ALTER TABLE system_info ADD COLUMN gpu_compute_capability TEXT")
            conn.execute("ALTER TABLE system_info ADD COLUMN has_cuda INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE system_info ADD COLUMN cuda_version TEXT")
            conn.execute("ALTER TABLE system_info ADD COLUMN gpu_driver_version TEXT")

            # Platform extended fields
            conn.execute("ALTER TABLE system_info ADD COLUMN platform_system TEXT")
            conn.execute("ALTER TABLE system_info ADD COLUMN platform_release TEXT")

            # Python extended fields
            conn.execute("ALTER TABLE system_info ADD COLUMN python_implementation TEXT")

            # PyTorch extended fields
            conn.execute("ALTER TABLE system_info ADD COLUMN torch_cuda_available INTEGER DEFAULT 0")

            # CPU extended fields (BM-09)
            conn.execute("ALTER TABLE system_info ADD COLUMN cpu_frequency_mhz REAL")
            conn.execute("ALTER TABLE system_info ADD COLUMN cpu_frequency_max_mhz REAL")
            conn.execute("ALTER TABLE system_info ADD COLUMN cpu_tdp_watts REAL")
            conn.execute("ALTER TABLE system_info ADD COLUMN memory_bandwidth_gbps REAL")
            conn.execute("ALTER TABLE system_info ADD COLUMN numa_nodes INTEGER DEFAULT 1")

            # Power management
            conn.execute("ALTER TABLE system_info ADD COLUMN power_management_state TEXT")

            # Metadata
            conn.execute("ALTER TABLE system_info ADD COLUMN collected_at_utc TEXT")
            conn.execute("ALTER TABLE system_info ADD COLUMN collector_version TEXT")

            # Note: gpu_vram_gb remains for backward compatibility
            # Mapping: gpu_vram_gb <-> gpu_memory_gb happens in save_run/get_run

            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (5, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 5 - extended SystemInfo fields")

        if from_version < 6:
            # v6: Add quality metrics (BLEU, COMET) to benchmark_results (BM-04)
            conn.execute("ALTER TABLE benchmark_results ADD COLUMN bleu_score REAL")
            conn.execute("ALTER TABLE benchmark_results ADD COLUMN comet_score REAL")

            # Create indices for quality metric queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_results_bleu ON benchmark_results(bleu_score)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_results_comet ON benchmark_results(comet_score)"
            )

            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (6, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 6 - quality metrics (BLEU, COMET)")

        if from_version < 7:
            # v7: Add cache tracking columns to benchmark_results (BM-CACHE-01)
            conn.execute("ALTER TABLE benchmark_results ADD COLUMN cache_status TEXT DEFAULT 'unknown'")
            conn.execute("ALTER TABLE benchmark_results ADD COLUMN tm_level TEXT DEFAULT 'none'")
            conn.execute("ALTER TABLE benchmark_results ADD COLUMN cache_hit_rate REAL DEFAULT 0.0")

            # Create indices for cache analysis queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_results_cache_status ON benchmark_results(cache_status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_results_tm_level ON benchmark_results(tm_level)"
            )

            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (7, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 7 - cache tracking (BM-CACHE-01)")

        if from_version < 8:
            # v8: Add analytics and time-series tables (Phase 4.1)
            # benchmark_trends: Pre-aggregated time-series data
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_trends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    device TEXT NOT NULL,
                    time_window TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    avg_throughput REAL NOT NULL,
                    p50_throughput REAL NOT NULL,
                    p95_throughput REAL NOT NULL,
                    p99_throughput REAL NOT NULL,
                    avg_duration REAL NOT NULL,
                    avg_memory_mb REAL,
                    created_at TEXT NOT NULL,
                    UNIQUE(model_id, device, time_window, window_start)
                )
                """
            )

            # Indices for efficient trend queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trends_model_device ON benchmark_trends(model_id, device)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trends_window ON benchmark_trends(time_window, window_start)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trends_model_device_window "
                "ON benchmark_trends(model_id, device, time_window, window_start)"
            )

            # performance_baselines: Historical performance baselines
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS performance_baselines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    device TEXT NOT NULL,
                    baseline_type TEXT NOT NULL,
                    baseline_date TEXT NOT NULL,
                    avg_throughput REAL NOT NULL,
                    p50_throughput REAL NOT NULL,
                    p95_throughput REAL NOT NULL,
                    sample_count INTEGER NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(model_id, device, baseline_type, baseline_date)
                )
                """
            )

            # Indices for baseline lookups
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_baselines_model_device "
                "ON performance_baselines(model_id, device)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_baselines_type_date "
                "ON performance_baselines(baseline_type, baseline_date)"
            )

            # retention_policies: Configurable data retention
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retention_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy_name TEXT NOT NULL UNIQUE,
                    target_table TEXT NOT NULL,
                    retention_days INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_cleanup TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # Insert default retention policies
            conn.execute(
                """
                INSERT INTO retention_policies
                (policy_name, target_table, retention_days, enabled, created_at, updated_at)
                VALUES
                ('benchmark_results_90d', 'benchmark_results', 90, 1, datetime('now'), datetime('now')),
                ('benchmark_trends_365d', 'benchmark_trends', 365, 1, datetime('now'), datetime('now')),
                ('performance_baselines_730d', 'performance_baselines', 730, 1, datetime('now'), datetime('now'))
                """
            )

            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (8, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 8 - analytics & time-series (Phase 4.1)")

        if from_version < 9:
            # v9: Add query optimization indices (Phase 4.2)
            # Additional composite indices for common query patterns

            # Optimize trend queries with window_start filter
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trends_model_device_start "
                "ON benchmark_trends(model_id, device, window_start)"
            )

            # Optimize baseline queries with baseline_type filter
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_baselines_model_device_type "
                "ON performance_baselines(model_id, device, baseline_type)"
            )

            # Optimize result aggregation queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_results_throughput_perf "
                "ON benchmark_results(run_id, throughput_tokens_per_sec)"
            )

            # Optimize timestamp-based result queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_created_at "
                "ON benchmark_runs(model_id, device, timestamp_utc)"
            )

            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (9, datetime.now(UTC).isoformat()),
            )
            logger.info("Applied schema migration to version 9 - query optimization indices (Phase 4.2)")

    def create_tables(self) -> None:
        """Create database tables (idempotent).

        This is a no-op if tables already exist, maintained for API compatibility.
        """
        # Tables are created in _init_db, this method is for explicit initialization
        logger.debug("Tables already initialized in __init__")

    def save_run(self, run: BenchmarkRun) -> None:
        """Save a benchmark run to the database.

        Args:
            run: BenchmarkRun to persist

        Raises:
            sqlite3.Error: If database operation fails
        """
        with self._lock:
            conn = self._get_connection()
            try:
                # Insert benchmark run
                conn.execute(
                    """
                    INSERT INTO benchmark_runs
                    (run_id, model_id, device, batch_sizes, iterations, corpus_category,
                     purpose, tags, total_duration_seconds, src_lang, tgt_lang, timestamp_utc, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        run.run_id,
                        run.model_id,
                        run.device,
                        json.dumps(run.batch_sizes),
                        run.iterations,
                        run.corpus_category,
                        run.purpose,
                        json.dumps(run.tags),
                        run.total_duration_seconds,
                        run.src_lang,
                        run.tgt_lang,
                        run.timestamp_utc,
                        json.dumps(run.metadata),
                    ),
                )

                # Insert system info
                si = run.system_info
                conn.execute(
                    """
                    INSERT INTO system_info
                    (run_id, cpu_model, cpu_cores, total_ram_gb, gpu_model, gpu_vram_gb,
                     os_name, os_version, python_version, torch_version, transformers_version,
                     timestamp_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        run.run_id,
                        si.cpu_model,
                        si.cpu_cores,
                        si.total_ram_gb,
                        si.gpu_model,
                        si.gpu_memory_gb,  # Comprehensive SystemInfo uses gpu_memory_gb
                        si.os_name,
                        si.os_version,
                        si.python_version,
                        si.torch_version or "",  # Handle None
                        "",  # transformers_version not in comprehensive SystemInfo
                        si.collected_at_utc if hasattr(si, 'collected_at_utc') else si.timestamp_utc,
                    ),
                )

                # Insert results
                for result in run.results:
                    conn.execute(
                        """
                        INSERT INTO benchmark_results
                        (run_id, sample_id, model_id, device, batch_size, duration_seconds,
                         tokens_input, tokens_output, throughput_tokens_per_sec, src_lang, tgt_lang,
                         peak_memory_mb, bleu_score, comet_score, cache_status, tm_level,
                         cache_hit_rate, errors)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            run.run_id,
                            result.sample_id,
                            result.model_id,
                            result.device,
                            result.batch_size,
                            result.duration_seconds,
                            result.tokens_input,
                            result.tokens_output,
                            result.throughput_tokens_per_sec,
                            result.src_lang,
                            result.tgt_lang,
                            result.peak_memory_mb,
                            result.bleu_score,
                            result.comet_score,
                            result.cache_status,
                            result.tm_level,
                            result.cache_hit_rate,
                            json.dumps(result.errors),
                        ),
                    )

                conn.commit()
                logger.info(
                    f"Saved benchmark run {run.run_id} with {len(run.results)} results to database"
                )
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to save benchmark run {run.run_id}: {e}")
                raise
            finally:
                self._close_connection(conn)

    def list_runs(
        self,
        model_id: Optional[str] = None,
        device: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Tuple[str, str, str, str, int]]:
        """List benchmark runs with optional filtering.

        Args:
            model_id: Filter by model ID
            device: Filter by device (cpu, cuda, etc.)
            limit: Maximum number of results
            offset: Result offset for pagination

        Returns:
            List of tuples: (run_id, model_id, device, timestamp_utc, result_count)
        """
        conn = self._get_connection()
        try:
            query = """
                SELECT
                    r.run_id,
                    r.model_id,
                    r.device,
                    r.timestamp_utc,
                    COUNT(br.id) as result_count
                FROM benchmark_runs r
                LEFT JOIN benchmark_results br ON r.run_id = br.run_id
                WHERE 1=1
            """
            params: List[Any] = []

            if model_id:
                query += " AND r.model_id = ?"
                params.append(model_id)

            if device:
                query += " AND r.device = ?"
                params.append(device)

            query += " GROUP BY r.run_id ORDER BY r.timestamp_utc DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            return [
                (row["run_id"], row["model_id"], row["device"], row["timestamp_utc"], row["result_count"])
                for row in cursor.fetchall()
            ]
        finally:
            self._close_connection(conn)

    def get_run(self, run_id: str) -> Optional[BenchmarkRun]:
        """Retrieve a complete benchmark run.

        Args:
            run_id: Run identifier

        Returns:
            BenchmarkRun if found, None otherwise
        """
        conn = self._get_connection()
        try:
            # Fetch run metadata
            cursor = conn.execute("SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,))
            run_row = cursor.fetchone()
            if not run_row:
                return None

            # Fetch system info
            cursor = conn.execute("SELECT * FROM system_info WHERE run_id = ?", (run_id,))
            sys_row = cursor.fetchone()
            if not sys_row:
                logger.warning(f"Missing system_info for run {run_id}")
                return None

            # Fetch results
            cursor = conn.execute("SELECT * FROM benchmark_results WHERE run_id = ?", (run_id,))
            result_rows = cursor.fetchall()

            # Reconstruct objects - map DB fields to comprehensive SystemInfo
            system_info = SystemInfo(
                cpu_model=sys_row["cpu_model"],
                cpu_cores=sys_row["cpu_cores"],
                total_ram_gb=sys_row["total_ram_gb"],
                gpu_model=sys_row["gpu_model"],
                gpu_memory_gb=sys_row["gpu_vram_gb"],  # DB has gpu_vram_gb, SystemInfo uses gpu_memory_gb
                os_name=sys_row["os_name"],
                os_version=sys_row["os_version"],
                python_version=sys_row["python_version"],
                torch_version=sys_row["torch_version"],
                # Comprehensive SystemInfo has additional fields not in v4 DB schema
                # These will be NULL until SR-02 migration completes
                collected_at_utc=sys_row["timestamp_utc"],
            )

            results = [
                BenchmarkResult(
                    sample_id=row["sample_id"],
                    model_id=row["model_id"],
                    device=row["device"],
                    batch_size=row["batch_size"],
                    duration_seconds=row["duration_seconds"],
                    tokens_input=row["tokens_input"],
                    tokens_output=row["tokens_output"],
                    throughput_tokens_per_sec=row["throughput_tokens_per_sec"],
                    peak_memory_mb=row["peak_memory_mb"],
                    bleu_score=dict(row).get("bleu_score"),
                    comet_score=dict(row).get("comet_score"),
                    cache_status=dict(row).get("cache_status", "unknown"),
                    tm_level=dict(row).get("tm_level", "none"),
                    cache_hit_rate=dict(row).get("cache_hit_rate", 0.0),
                    errors=json.loads(row["errors"]),
                )
                for row in result_rows
            ]

            return BenchmarkRun(
                run_id=run_row["run_id"],
                model_id=run_row["model_id"],
                device=run_row["device"],
                batch_sizes=json.loads(run_row["batch_sizes"]),
                iterations=run_row["iterations"],
                corpus_category=run_row["corpus_category"],
                purpose=run_row["purpose"],
                tags=json.loads(run_row["tags"]),
                system_info=system_info,
                results=results,
                total_duration_seconds=run_row["total_duration_seconds"],
                timestamp_utc=run_row["timestamp_utc"],
                metadata=json.loads(run_row["metadata"]),
            )
        finally:
            self._close_connection(conn)

    def compare_runs(
        self, run_ids: List[str], metric: str = "throughput_tokens_per_sec"
    ) -> Dict[str, Any]:
        """Compare multiple benchmark runs on a specific metric.

        Args:
            run_ids: List of run IDs to compare
            metric: Metric to compare (default: throughput_tokens_per_sec)

        Returns:
            Dictionary with comparison data
        """
        runs = [self.get_run(run_id) for run_id in run_ids]
        runs = [r for r in runs if r is not None]

        if not runs:
            return {"error": "No valid runs found"}

        comparison = {
            "metric": metric,
            "runs": [],
        }

        for run in runs:
            if not run.results:
                continue

            # Calculate aggregate metric
            if metric == "throughput_tokens_per_sec":
                values = [r.throughput_tokens_per_sec for r in run.results]
            elif metric == "duration_seconds":
                values = [r.duration_seconds for r in run.results]
            elif metric == "peak_memory_mb":
                values = [r.peak_memory_mb for r in run.results if r.peak_memory_mb is not None]
            else:
                logger.warning(f"Unknown metric: {metric}")
                continue

            if values:
                comparison["runs"].append(
                    {
                        "run_id": run.run_id,
                        "model_id": run.model_id,
                        "device": run.device,
                        "timestamp": run.timestamp_utc,
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values),
                        "count": len(values),
                    }
                )

        return comparison

    def export_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Export a benchmark run as JSON-serializable dictionary.

        Args:
            run_id: Run identifier

        Returns:
            Dictionary representation of the run, or None if not found
        """
        run = self.get_run(run_id)
        if run is None:
            return None
        return run.to_dict()

    def import_run(self, data: Dict[str, Any]) -> None:
        """Import a benchmark run from JSON data.

        Args:
            data: Dictionary representation of a BenchmarkRun

        Raises:
            ValueError: If data is invalid
            sqlite3.Error: If database operation fails
        """
        try:
            run = BenchmarkRun.from_dict(data)
            self.save_run(run)
            logger.info(f"Imported benchmark run {run.run_id}")
        except Exception as e:
            logger.error(f"Failed to import benchmark run: {e}")
            raise

    def delete_run(self, run_id: str) -> bool:
        """Delete a benchmark run and all associated data.

        Args:
            run_id: Run identifier

        Returns:
            True if run was deleted, False if not found
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM benchmark_runs WHERE run_id = ?", (run_id,))
                deleted = cursor.rowcount > 0
                conn.commit()

                if deleted:
                    logger.info(f"Deleted benchmark run {run_id}")
                else:
                    logger.warning(f"Run {run_id} not found for deletion")

                return deleted
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to delete run {run_id}: {e}")
                raise
            finally:
                self._close_connection(conn)

    def get_schema_version(self) -> int:
        """Get current database schema version.

        Returns:
            Schema version number
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            self._close_connection(conn)

    def verify_integrity(self) -> bool:
        """Verify database integrity.

        Returns:
            True if integrity check passes
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            is_ok = result and result[0] == "ok"
            if is_ok:
                logger.info("Database integrity check passed")
            else:
                logger.error(f"Database integrity check failed: {result}")
            return is_ok
        finally:
            self._close_connection(conn)

    # -------------------------------------------------------------------------
    # Retention Policy Helpers (Phase 4.3)
    # -------------------------------------------------------------------------

    def get_retention_policies(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """Get retention policies from database.

        Args:
            enabled_only: Only return enabled policies

        Returns:
            List of policy dictionaries
        """
        conn = self._get_connection()
        try:
            if enabled_only:
                cursor = conn.execute(
                    "SELECT * FROM retention_policies WHERE enabled = 1 ORDER BY policy_name"
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM retention_policies ORDER BY policy_name"
                )

            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error:
            # Table may not exist in older schemas
            return []
        finally:
            self._close_connection(conn)

    def get_data_age_summary(self) -> Dict[str, Any]:
        """Get summary of data age across tables.

        Returns:
            Dictionary with data age statistics
        """
        conn = self._get_connection()
        try:
            summary = {
                "benchmark_runs": {},
                "benchmark_trends": {},
                "performance_baselines": {},
            }

            # benchmark_runs
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    MIN(timestamp_utc) as oldest,
                    MAX(timestamp_utc) as newest
                FROM benchmark_runs
            """)
            row = cursor.fetchone()
            if row:
                summary["benchmark_runs"] = {
                    "total": row["total"],
                    "oldest": row["oldest"],
                    "newest": row["newest"],
                }

            # benchmark_trends (may not exist in older schemas)
            try:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        MIN(created_at) as oldest,
                        MAX(created_at) as newest
                    FROM benchmark_trends
                """)
                row = cursor.fetchone()
                if row:
                    summary["benchmark_trends"] = {
                        "total": row["total"],
                        "oldest": row["oldest"],
                        "newest": row["newest"],
                    }
            except sqlite3.Error:
                pass

            # performance_baselines (may not exist in older schemas)
            try:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        MIN(created_at) as oldest,
                        MAX(created_at) as newest
                    FROM performance_baselines
                """)
                row = cursor.fetchone()
                if row:
                    summary["performance_baselines"] = {
                        "total": row["total"],
                        "oldest": row["oldest"],
                        "newest": row["newest"],
                    }
            except sqlite3.Error:
                pass

            return summary
        finally:
            self._close_connection(conn)

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics including size and table counts.

        Returns:
            Dictionary with database statistics
        """
        conn = self._get_connection()
        try:
            stats = {
                "schema_version": self.get_schema_version(),
                "tables": {},
                "file_size_bytes": 0,
            }

            # Get file size
            if self.db_path != ":memory:":
                stats["file_size_bytes"] = Path(self.db_path).stat().st_size

            # Get row counts for each table
            tables = [
                "benchmark_runs",
                "benchmark_results",
                "system_info",
                "benchmark_trends",
                "performance_baselines",
                "retention_policies",
            ]

            for table in tables:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats["tables"][table] = cursor.fetchone()[0]
                except sqlite3.Error:
                    stats["tables"][table] = 0

            return stats
        finally:
            self._close_connection(conn)
