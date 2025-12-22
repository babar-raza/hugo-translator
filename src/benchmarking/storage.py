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

logger = logging.getLogger(__name__)


@dataclass
class SystemInfo:
    """System configuration snapshot."""

    cpu_model: str
    cpu_cores: int
    total_ram_gb: float
    gpu_model: Optional[str] = None
    gpu_vram_gb: Optional[float] = None
    os_name: str = ""
    os_version: str = ""
    python_version: str = ""
    torch_version: str = ""
    transformers_version: str = ""
    timestamp_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemInfo":
        """Create SystemInfo from dictionary."""
        return cls(**data)


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
    peak_memory_mb: Optional[float] = None
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

    SCHEMA_VERSION = 1

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
            conn.close()

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
                     purpose, tags, total_duration_seconds, timestamp_utc, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        si.gpu_vram_gb,
                        si.os_name,
                        si.os_version,
                        si.python_version,
                        si.torch_version,
                        si.transformers_version,
                        si.timestamp_utc,
                    ),
                )

                # Insert results
                for result in run.results:
                    conn.execute(
                        """
                        INSERT INTO benchmark_results
                        (run_id, sample_id, model_id, device, batch_size, duration_seconds,
                         tokens_input, tokens_output, throughput_tokens_per_sec,
                         peak_memory_mb, errors)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            result.peak_memory_mb,
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

            # Reconstruct objects
            system_info = SystemInfo(
                cpu_model=sys_row["cpu_model"],
                cpu_cores=sys_row["cpu_cores"],
                total_ram_gb=sys_row["total_ram_gb"],
                gpu_model=sys_row["gpu_model"],
                gpu_vram_gb=sys_row["gpu_vram_gb"],
                os_name=sys_row["os_name"],
                os_version=sys_row["os_version"],
                python_version=sys_row["python_version"],
                torch_version=sys_row["torch_version"],
                transformers_version=sys_row["transformers_version"],
                timestamp_utc=sys_row["timestamp_utc"],
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
