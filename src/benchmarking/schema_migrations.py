"""Schema migration framework for benchmark database.

Provides a structured approach to database schema evolution with:
- Version-based migrations (up and down)
- Rollback capability
- Migration history tracking
- Pre/post validation hooks
- SharedEngines integration for logging and telemetry

This module implements Phase 4.1 of the autonomous workers migration,
adding analytics and time-series tables to the benchmark database.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

logger = logging.getLogger(__name__)


@dataclass
class Migration:
    """Single database migration definition.

    Attributes:
        version: Target schema version
        description: Human-readable description
        up_sql: SQL statements for upgrade (list of strings)
        down_sql: SQL statements for rollback (list of strings)
        pre_check: Optional validation before migration
        post_check: Optional validation after migration
    """

    version: int
    description: str
    up_sql: List[str]
    down_sql: List[str]
    pre_check: Optional[Callable[[sqlite3.Connection], bool]] = None
    post_check: Optional[Callable[[sqlite3.Connection], bool]] = None


class MigrationError(Exception):
    """Raised when migration fails."""
    pass


class MigrationManager:
    """Manages database schema migrations.

    Features:
    - Apply migrations sequentially from current to target version
    - Rollback to previous versions
    - Validate migrations before/after execution
    - Emit telemetry events via SharedEngines
    - Log all operations via LoggingEngine

    Example:
        manager = MigrationManager(db_path="data/benchmarks.db", engines=engines)
        manager.migrate_to(8)  # Upgrade to v8
        manager.rollback_to(7)  # Rollback to v7
    """

    def __init__(
        self,
        db_path: Path | str,
        engines: Optional["SharedEngines"] = None
    ):
        """Initialize migration manager.

        Args:
            db_path: Path to SQLite database
            engines: Optional SharedEngines for logging/telemetry
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        self.engines = engines
        self._migrations: List[Migration] = []
        self._register_migrations()

        if engines:
            logger.info("MigrationManager initialized with SharedEngines support")

    def _register_migrations(self) -> None:
        """Register all available migrations.

        This method defines the migration path for the benchmark database.
        Migrations are applied sequentially based on version number.
        """
        # Migration v7 -> v8: Analytics & Time-Series
        self._migrations.append(Migration(
            version=8,
            description="Add analytics tables: benchmark_trends, performance_baselines, retention_policies",
            up_sql=[
                # benchmark_trends: Pre-aggregated time-series data
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
                """,
                # Indices for efficient trend queries
                """
                CREATE INDEX IF NOT EXISTS idx_trends_model_device
                ON benchmark_trends(model_id, device)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_trends_window
                ON benchmark_trends(time_window, window_start)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_trends_model_device_window
                ON benchmark_trends(model_id, device, time_window, window_start)
                """,

                # performance_baselines: Historical performance baselines
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
                """,
                # Indices for baseline lookups
                """
                CREATE INDEX IF NOT EXISTS idx_baselines_model_device
                ON performance_baselines(model_id, device)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_baselines_type_date
                ON performance_baselines(baseline_type, baseline_date)
                """,

                # retention_policies: Configurable data retention
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
                """,
                # Insert default retention policies
                """
                INSERT INTO retention_policies
                (policy_name, target_table, retention_days, enabled, created_at, updated_at)
                VALUES
                ('benchmark_results_90d', 'benchmark_results', 90, 1, datetime('now'), datetime('now')),
                ('benchmark_trends_365d', 'benchmark_trends', 365, 1, datetime('now'), datetime('now')),
                ('performance_baselines_730d', 'performance_baselines', 730, 1, datetime('now'), datetime('now'))
                """,
            ],
            down_sql=[
                "DROP TABLE IF EXISTS retention_policies",
                "DROP INDEX IF EXISTS idx_baselines_type_date",
                "DROP INDEX IF EXISTS idx_baselines_model_device",
                "DROP TABLE IF EXISTS performance_baselines",
                "DROP INDEX IF EXISTS idx_trends_model_device_window",
                "DROP INDEX IF EXISTS idx_trends_window",
                "DROP INDEX IF EXISTS idx_trends_model_device",
                "DROP TABLE IF EXISTS benchmark_trends",
            ],
            post_check=self._validate_v8_schema
        ))

        # Migration v8 -> v9: Query Optimization Indices (Phase 4.2)
        self._migrations.append(Migration(
            version=9,
            description="Add query optimization indices for common query patterns",
            up_sql=[
                # Optimize trend queries with window_start filter
                """
                CREATE INDEX IF NOT EXISTS idx_trends_model_device_start
                ON benchmark_trends(model_id, device, window_start)
                """,
                # Optimize baseline queries with baseline_type filter
                """
                CREATE INDEX IF NOT EXISTS idx_baselines_model_device_type
                ON performance_baselines(model_id, device, baseline_type)
                """,
                # Optimize results queries with timestamp filter
                """
                CREATE INDEX IF NOT EXISTS idx_results_run_timestamp
                ON benchmark_results(run_id, sample_id)
                """,
            ],
            down_sql=[
                "DROP INDEX IF EXISTS idx_results_run_timestamp",
                "DROP INDEX IF EXISTS idx_baselines_model_device_type",
                "DROP INDEX IF EXISTS idx_trends_model_device_start",
            ],
        ))

    def _validate_v8_schema(self, conn: sqlite3.Connection) -> bool:
        """Validate schema v8 tables exist with correct structure.

        Args:
            conn: Database connection

        Returns:
            True if validation passes

        Raises:
            MigrationError: If validation fails
        """
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

        required_tables = {
            "benchmark_trends",
            "performance_baselines",
            "retention_policies"
        }

        missing = required_tables - tables
        if missing:
            raise MigrationError(f"Schema v8 validation failed: missing tables {missing}")

        # Verify retention policies have default entries
        cursor = conn.execute("SELECT COUNT(*) FROM retention_policies")
        policy_count = cursor.fetchone()[0]
        if policy_count < 3:
            raise MigrationError(
                f"Schema v8 validation failed: expected 3+ retention policies, found {policy_count}"
            )

        logger.info("Schema v8 validation passed")
        return True

    def get_current_version(self) -> int:
        """Get current database schema version.

        Returns:
            Current version number (0 if no schema_version table)
        """
        conn = self._create_connection()
        try:
            cursor = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            # schema_version table doesn't exist
            return 0
        finally:
            conn.close()

    def _create_connection(self) -> sqlite3.Connection:
        """Create database connection with proper settings.

        Returns:
            Configured SQLite connection
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def migrate_to(self, target_version: int, dry_run: bool = False) -> None:
        """Migrate database to target version.

        Args:
            target_version: Target schema version
            dry_run: If True, validate but don't execute migrations

        Raises:
            MigrationError: If migration fails
            ValueError: If target version is invalid
        """
        current_version = self.get_current_version()

        if target_version == current_version:
            logger.info(f"Database already at version {target_version}")
            return

        if target_version < current_version:
            raise ValueError(
                f"Cannot migrate backwards with migrate_to(). "
                f"Current: {current_version}, Target: {target_version}. "
                f"Use rollback_to() instead."
            )

        # Emit telemetry: migration started
        if self.engines:
            self.engines.telemetry.track_event(
                "benchmark_schema_migration_started",
                from_version=current_version,
                to_version=target_version,
                dry_run=dry_run
            )

        logger.info(
            f"{'[DRY RUN] ' if dry_run else ''}Migrating database from v{current_version} to v{target_version}"
        )

        # Find migrations to apply
        migrations_to_apply = [
            m for m in self._migrations
            if current_version < m.version <= target_version
        ]

        if not migrations_to_apply:
            raise ValueError(
                f"No migrations defined between v{current_version} and v{target_version}"
            )

        # Sort by version
        migrations_to_apply.sort(key=lambda m: m.version)

        conn = self._create_connection()
        try:
            for migration in migrations_to_apply:
                self._apply_migration(conn, migration, dry_run=dry_run)

            if not dry_run:
                conn.commit()
                logger.info(f"Migration to v{target_version} completed successfully")

                # Emit telemetry: migration completed
                if self.engines:
                    self.engines.telemetry.track_event(
                        "benchmark_schema_migration_completed",
                        from_version=current_version,
                        to_version=target_version
                    )
        except Exception as e:
            conn.rollback()
            logger.error(f"Migration failed: {e}", exc_info=True)

            # Emit telemetry: migration failed
            if self.engines:
                self.engines.telemetry.track_event(
                    "benchmark_schema_migration_failed",
                    from_version=current_version,
                    to_version=target_version,
                    error=str(e)
                )

            raise MigrationError(f"Migration to v{target_version} failed: {e}") from e
        finally:
            conn.close()

    def rollback_to(self, target_version: int, dry_run: bool = False) -> None:
        """Rollback database to previous version.

        Args:
            target_version: Target schema version (must be < current)
            dry_run: If True, validate but don't execute rollback

        Raises:
            MigrationError: If rollback fails
            ValueError: If target version is invalid
        """
        current_version = self.get_current_version()

        if target_version == current_version:
            logger.info(f"Database already at version {target_version}")
            return

        if target_version > current_version:
            raise ValueError(
                f"Cannot rollback forwards. "
                f"Current: {current_version}, Target: {target_version}. "
                f"Use migrate_to() instead."
            )

        logger.warning(
            f"{'[DRY RUN] ' if dry_run else ''}Rolling back database from v{current_version} to v{target_version}"
        )

        # Find migrations to rollback (reverse order)
        migrations_to_rollback = [
            m for m in self._migrations
            if target_version < m.version <= current_version
        ]

        if not migrations_to_rollback:
            raise ValueError(
                f"No migrations defined between v{target_version} and v{current_version}"
            )

        # Sort by version descending (rollback newest first)
        migrations_to_rollback.sort(key=lambda m: m.version, reverse=True)

        conn = self._create_connection()
        try:
            for migration in migrations_to_rollback:
                self._rollback_migration(conn, migration, dry_run=dry_run)

            if not dry_run:
                conn.commit()
                logger.info(f"Rollback to v{target_version} completed successfully")
        except Exception as e:
            conn.rollback()
            logger.error(f"Rollback failed: {e}", exc_info=True)
            raise MigrationError(f"Rollback to v{target_version} failed: {e}") from e
        finally:
            conn.close()

    def _apply_migration(
        self,
        conn: sqlite3.Connection,
        migration: Migration,
        dry_run: bool = False
    ) -> None:
        """Apply a single migration.

        Args:
            conn: Database connection
            migration: Migration to apply
            dry_run: If True, validate but don't execute

        Raises:
            MigrationError: If migration fails
        """
        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Applying migration v{migration.version}: {migration.description}")

        # Run pre-check if defined
        if migration.pre_check:
            if not migration.pre_check(conn):
                raise MigrationError(f"Pre-check failed for migration v{migration.version}")

        # Execute upgrade SQL
        if not dry_run:
            for sql in migration.up_sql:
                try:
                    conn.execute(sql)
                except Exception as e:
                    raise MigrationError(
                        f"Failed to execute migration v{migration.version} SQL: {e}\nSQL: {sql[:100]}..."
                    ) from e

            # Record migration in schema_version
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (migration.version, datetime.now(UTC).isoformat())
            )

        # Run post-check if defined
        if migration.post_check and not dry_run:
            if not migration.post_check(conn):
                raise MigrationError(f"Post-check failed for migration v{migration.version}")

        logger.info(f"Migration v{migration.version} applied successfully")

    def _rollback_migration(
        self,
        conn: sqlite3.Connection,
        migration: Migration,
        dry_run: bool = False
    ) -> None:
        """Rollback a single migration.

        Args:
            conn: Database connection
            migration: Migration to rollback
            dry_run: If True, validate but don't execute

        Raises:
            MigrationError: If rollback fails
        """
        logger.warning(
            f"{'[DRY RUN] ' if dry_run else ''}Rolling back migration v{migration.version}: {migration.description}"
        )

        # Execute downgrade SQL
        if not dry_run:
            for sql in migration.down_sql:
                try:
                    conn.execute(sql)
                except Exception as e:
                    raise MigrationError(
                        f"Failed to rollback migration v{migration.version} SQL: {e}\nSQL: {sql[:100]}..."
                    ) from e

            # Remove migration from schema_version
            conn.execute(
                "DELETE FROM schema_version WHERE version = ?",
                (migration.version,)
            )

        logger.info(f"Migration v{migration.version} rolled back successfully")

    def list_migrations(self) -> List[dict]:
        """List all available migrations with status.

        Returns:
            List of migration info dictionaries
        """
        current_version = self.get_current_version()

        result = []
        for migration in sorted(self._migrations, key=lambda m: m.version):
            result.append({
                "version": migration.version,
                "description": migration.description,
                "applied": migration.version <= current_version,
                "current": migration.version == current_version
            })

        return result
