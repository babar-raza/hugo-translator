"""Data retention policy engine for benchmark database.

Implements automated data retention with configurable policies:
- Hot data: Recent benchmark runs (keep all, 30 days default)
- Warm data: Older runs, aggregated (keep trends, 90 days default)
- Cold data: Archive or delete (>90 days default)

Provides:
- Policy-based retention execution
- Dry-run mode for safe testing
- Detailed logging of all actions
- Telemetry event emission

Phase 4.3: Data Retention & Export
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

logger = logging.getLogger(__name__)


@dataclass
class RetentionPolicy:
    """Retention policy definition.

    Attributes:
        id: Policy database ID
        policy_name: Unique policy name
        target_table: Table this policy applies to
        retention_days: Days to retain data
        enabled: Whether policy is active
        last_cleanup: Last cleanup timestamp
        created_at: Policy creation timestamp
        updated_at: Policy last update timestamp
    """

    id: int
    policy_name: str
    target_table: str
    retention_days: int
    enabled: bool
    last_cleanup: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "RetentionPolicy":
        """Create RetentionPolicy from database row."""
        return cls(
            id=row["id"],
            policy_name=row["policy_name"],
            target_table=row["target_table"],
            retention_days=row["retention_days"],
            enabled=bool(row["enabled"]),
            last_cleanup=row["last_cleanup"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class RetentionResult:
    """Result of retention execution.

    Attributes:
        policy_name: Name of executed policy
        target_table: Table affected
        rows_deleted: Number of rows deleted
        dry_run: Whether this was a dry run
        cutoff_date: Date before which data was deleted
        error: Error message if failed
    """

    policy_name: str
    target_table: str
    rows_deleted: int
    dry_run: bool
    cutoff_date: str
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "policy_name": self.policy_name,
            "target_table": self.target_table,
            "rows_deleted": self.rows_deleted,
            "dry_run": self.dry_run,
            "cutoff_date": self.cutoff_date,
            "error": self.error,
        }


class RetentionEngine:
    """Executes data retention policies on benchmark database.

    Features:
    - Load and execute retention policies from database
    - Support dry-run mode for safe testing
    - Log all retention actions
    - Emit telemetry events via SharedEngines
    - Handle multiple retention levels (hot/warm/cold)

    Example:
        engine = RetentionEngine(db_path="data/benchmarks.db")

        # List policies
        policies = engine.list_policies()

        # Dry run
        results = engine.execute_retention(dry_run=True)

        # Execute retention
        results = engine.execute_retention()
    """

    # Mapping of table names to their timestamp columns
    TABLE_TIMESTAMP_COLUMNS = {
        "benchmark_runs": "timestamp_utc",
        "benchmark_results": None,  # Joined with benchmark_runs
        "benchmark_trends": "created_at",
        "performance_baselines": "created_at",
        "recommendation_feedback": "timestamp_utc",
        "recommendation_weights": "timestamp_utc",
    }

    def __init__(
        self,
        db_path: Path | str,
        engines: Optional["SharedEngines"] = None,
    ):
        """Initialize retention engine.

        Args:
            db_path: Path to benchmark database
            engines: Optional SharedEngines for logging/telemetry
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        self.engines = engines

        if engines:
            logger.info("RetentionEngine initialized with SharedEngines support")

    def _create_connection(self) -> sqlite3.Connection:
        """Create database connection with proper settings.

        Returns:
            Configured SQLite connection
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def list_policies(self, enabled_only: bool = False) -> list[RetentionPolicy]:
        """List all retention policies.

        Args:
            enabled_only: Only return enabled policies

        Returns:
            List of RetentionPolicy objects
        """
        conn = self._create_connection()
        try:
            if enabled_only:
                cursor = conn.execute(
                    "SELECT * FROM retention_policies WHERE enabled = 1 ORDER BY policy_name"
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM retention_policies ORDER BY policy_name"
                )

            return [RetentionPolicy.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_policy(self, policy_name: str) -> RetentionPolicy | None:
        """Get a specific retention policy by name.

        Args:
            policy_name: Policy name to retrieve

        Returns:
            RetentionPolicy if found, None otherwise
        """
        conn = self._create_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM retention_policies WHERE policy_name = ?",
                (policy_name,),
            )
            row = cursor.fetchone()
            return RetentionPolicy.from_row(row) if row else None
        finally:
            conn.close()

    def update_policy(
        self,
        policy_name: str,
        retention_days: int | None = None,
        enabled: bool | None = None,
    ) -> bool:
        """Update a retention policy.

        Args:
            policy_name: Policy name to update
            retention_days: New retention days (optional)
            enabled: New enabled state (optional)

        Returns:
            True if policy was updated, False if not found
        """
        conn = self._create_connection()
        try:
            updates = []
            params = []

            if retention_days is not None:
                updates.append("retention_days = ?")
                params.append(retention_days)

            if enabled is not None:
                updates.append("enabled = ?")
                params.append(1 if enabled else 0)

            if not updates:
                return False

            updates.append("updated_at = ?")
            params.append(datetime.now(UTC).isoformat())
            params.append(policy_name)

            cursor = conn.execute(
                f"UPDATE retention_policies SET {', '.join(updates)} WHERE policy_name = ?",
                params,
            )
            conn.commit()

            updated = cursor.rowcount > 0
            if updated:
                logger.info(
                    f"Updated retention policy {policy_name}: "
                    f"retention_days={retention_days}, enabled={enabled}"
                )
            return updated
        finally:
            conn.close()

    def create_policy(
        self,
        policy_name: str,
        target_table: str,
        retention_days: int,
        enabled: bool = True,
    ) -> int:
        """Create a new retention policy.

        Args:
            policy_name: Unique policy name
            target_table: Table this policy applies to
            retention_days: Days to retain data
            enabled: Whether policy is active

        Returns:
            New policy ID

        Raises:
            ValueError: If target_table is not supported
            sqlite3.IntegrityError: If policy_name already exists
        """
        if target_table not in self.TABLE_TIMESTAMP_COLUMNS:
            raise ValueError(
                f"Unsupported target table: {target_table}. "
                f"Supported: {list(self.TABLE_TIMESTAMP_COLUMNS.keys())}"
            )

        conn = self._create_connection()
        try:
            now = datetime.now(UTC).isoformat()
            cursor = conn.execute(
                """
                INSERT INTO retention_policies
                (policy_name, target_table, retention_days, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (policy_name, target_table, retention_days, 1 if enabled else 0, now, now),
            )
            conn.commit()

            policy_id = cursor.lastrowid
            logger.info(
                f"Created retention policy {policy_name} (id={policy_id}): "
                f"table={target_table}, days={retention_days}, enabled={enabled}"
            )
            return policy_id
        finally:
            conn.close()

    def delete_policy(self, policy_name: str) -> bool:
        """Delete a retention policy.

        Args:
            policy_name: Policy name to delete

        Returns:
            True if policy was deleted, False if not found
        """
        conn = self._create_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM retention_policies WHERE policy_name = ?",
                (policy_name,),
            )
            conn.commit()

            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted retention policy {policy_name}")
            return deleted
        finally:
            conn.close()

    def get_retention_status(self) -> dict:
        """Get overall retention status and statistics.

        Returns:
            Dictionary with status information
        """
        conn = self._create_connection()
        try:
            policies = self.list_policies()

            status = {
                "total_policies": len(policies),
                "enabled_policies": sum(1 for p in policies if p.enabled),
                "disabled_policies": sum(1 for p in policies if not p.enabled),
                "policies": [],
                "table_statistics": {},
            }

            for policy in policies:
                # Get row counts and oldest timestamp for each table
                table_stats = self._get_table_statistics(conn, policy.target_table)

                policy_info = {
                    "name": policy.policy_name,
                    "table": policy.target_table,
                    "retention_days": policy.retention_days,
                    "enabled": policy.enabled,
                    "last_cleanup": policy.last_cleanup,
                    "rows_total": table_stats.get("total_rows", 0),
                    "rows_to_delete": self._count_rows_to_delete(
                        conn, policy.target_table, policy.retention_days
                    ),
                    "oldest_record": table_stats.get("oldest_timestamp"),
                }
                status["policies"].append(policy_info)

                # Update table statistics
                if policy.target_table not in status["table_statistics"]:
                    status["table_statistics"][policy.target_table] = table_stats

            return status
        finally:
            conn.close()

    def _get_table_statistics(
        self, conn: sqlite3.Connection, table_name: str
    ) -> dict:
        """Get statistics for a table.

        Args:
            conn: Database connection
            table_name: Table to get statistics for

        Returns:
            Dictionary with table statistics
        """
        try:
            # Get total row count
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            total_rows = cursor.fetchone()[0]

            # Get oldest timestamp
            timestamp_col = self.TABLE_TIMESTAMP_COLUMNS.get(table_name)
            oldest_timestamp = None

            if timestamp_col:
                cursor = conn.execute(
                    f"SELECT MIN({timestamp_col}) FROM {table_name}"
                )
                row = cursor.fetchone()
                oldest_timestamp = row[0] if row else None
            elif table_name == "benchmark_results":
                # Special case: join with benchmark_runs
                cursor = conn.execute("""
                    SELECT MIN(r.timestamp_utc)
                    FROM benchmark_results br
                    JOIN benchmark_runs r ON br.run_id = r.run_id
                """)
                row = cursor.fetchone()
                oldest_timestamp = row[0] if row else None

            return {
                "total_rows": total_rows,
                "oldest_timestamp": oldest_timestamp,
            }
        except sqlite3.Error as e:
            logger.warning(f"Failed to get statistics for {table_name}: {e}")
            return {"total_rows": 0, "oldest_timestamp": None}

    def _count_rows_to_delete(
        self, conn: sqlite3.Connection, table_name: str, retention_days: int
    ) -> int:
        """Count rows that would be deleted by retention policy.

        Args:
            conn: Database connection
            table_name: Table to check
            retention_days: Retention period in days

        Returns:
            Number of rows that would be deleted
        """
        try:
            cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()

            if table_name == "benchmark_results":
                # Special case: delete via run_id
                cursor = conn.execute(
                    """
                    SELECT COUNT(*) FROM benchmark_results
                    WHERE run_id IN (
                        SELECT run_id FROM benchmark_runs
                        WHERE timestamp_utc < ?
                    )
                    """,
                    (cutoff,),
                )
            elif table_name == "benchmark_runs":
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM benchmark_runs WHERE timestamp_utc < ?",
                    (cutoff,),
                )
            else:
                timestamp_col = self.TABLE_TIMESTAMP_COLUMNS.get(table_name)
                if not timestamp_col:
                    return 0
                cursor = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE {timestamp_col} < ?",
                    (cutoff,),
                )

            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.warning(f"Failed to count rows for {table_name}: {e}")
            return 0

    def execute_retention(
        self,
        policy_names: list[str] | None = None,
        dry_run: bool = False,
    ) -> list[RetentionResult]:
        """Execute retention policies.

        Args:
            policy_names: Specific policies to execute (None = all enabled)
            dry_run: If True, report what would be deleted without deleting

        Returns:
            List of RetentionResult objects
        """
        start_time = datetime.now(UTC)

        # Emit telemetry: retention started
        if self.engines:
            self.engines.telemetry.track_event(
                "benchmark_retention_started",
                dry_run=dry_run,
                policy_count=len(policy_names) if policy_names else "all",
            )

        logger.info(
            f"{'[DRY RUN] ' if dry_run else ''}Starting retention execution"
        )

        results = []
        conn = self._create_connection()

        try:
            # Get policies to execute
            if policy_names:
                policies = [
                    self.get_policy(name)
                    for name in policy_names
                    if self.get_policy(name)
                ]
            else:
                policies = self.list_policies(enabled_only=True)

            if not policies:
                logger.warning("No retention policies to execute")
                return results

            for policy in policies:
                result = self._execute_policy(conn, policy, dry_run)
                results.append(result)

                if not dry_run and not result.error:
                    # Update last_cleanup timestamp
                    conn.execute(
                        """
                        UPDATE retention_policies
                        SET last_cleanup = ?, updated_at = ?
                        WHERE policy_name = ?
                        """,
                        (
                            datetime.now(UTC).isoformat(),
                            datetime.now(UTC).isoformat(),
                            policy.policy_name,
                        ),
                    )

            if not dry_run:
                conn.commit()

            duration = (datetime.now(UTC) - start_time).total_seconds()
            total_deleted = sum(r.rows_deleted for r in results if not r.error)

            logger.info(
                f"{'[DRY RUN] ' if dry_run else ''}Retention completed: "
                f"{total_deleted} rows {'would be ' if dry_run else ''}deleted "
                f"from {len(results)} policies in {duration:.2f}s"
            )

            # Emit telemetry: retention completed
            if self.engines:
                self.engines.telemetry.track_event(
                    "benchmark_retention_completed",
                    dry_run=dry_run,
                    total_deleted=total_deleted,
                    policy_count=len(results),
                    duration_seconds=duration,
                )

            return results

        except Exception as e:
            conn.rollback()
            logger.error(f"Retention execution failed: {e}", exc_info=True)

            # Emit telemetry: retention failed
            if self.engines:
                self.engines.telemetry.track_event(
                    "benchmark_retention_failed",
                    error=str(e),
                    dry_run=dry_run,
                )

            raise RuntimeError(f"Retention execution failed: {e}") from e
        finally:
            conn.close()

    def _execute_policy(
        self,
        conn: sqlite3.Connection,
        policy: RetentionPolicy,
        dry_run: bool,
    ) -> RetentionResult:
        """Execute a single retention policy.

        Args:
            conn: Database connection
            policy: Policy to execute
            dry_run: If True, only count without deleting

        Returns:
            RetentionResult object
        """
        cutoff = datetime.now(UTC) - timedelta(days=policy.retention_days)
        cutoff_str = cutoff.isoformat()

        logger.info(
            f"{'[DRY RUN] ' if dry_run else ''}Executing policy {policy.policy_name}: "
            f"table={policy.target_table}, cutoff={cutoff_str[:10]}"
        )

        try:
            # Count rows first (for both dry run and actual deletion)
            rows_to_delete = self._count_rows_to_delete(
                conn, policy.target_table, policy.retention_days
            )

            if dry_run:
                logger.info(
                    f"[DRY RUN] Policy {policy.policy_name}: "
                    f"{rows_to_delete} rows would be deleted"
                )
                return RetentionResult(
                    policy_name=policy.policy_name,
                    target_table=policy.target_table,
                    rows_deleted=rows_to_delete,
                    dry_run=True,
                    cutoff_date=cutoff_str,
                )

            # Execute deletion
            deleted = self._delete_old_data(conn, policy.target_table, cutoff_str)

            logger.info(
                f"Policy {policy.policy_name}: deleted {deleted} rows "
                f"from {policy.target_table}"
            )

            return RetentionResult(
                policy_name=policy.policy_name,
                target_table=policy.target_table,
                rows_deleted=deleted,
                dry_run=False,
                cutoff_date=cutoff_str,
            )

        except Exception as e:
            logger.error(
                f"Policy {policy.policy_name} failed: {e}", exc_info=True
            )
            return RetentionResult(
                policy_name=policy.policy_name,
                target_table=policy.target_table,
                rows_deleted=0,
                dry_run=dry_run,
                cutoff_date=cutoff_str,
                error=str(e),
            )

    def _delete_old_data(
        self, conn: sqlite3.Connection, table_name: str, cutoff: str
    ) -> int:
        """Delete old data from a table.

        Args:
            conn: Database connection
            table_name: Table to delete from
            cutoff: Cutoff timestamp (ISO format)

        Returns:
            Number of rows deleted
        """
        if table_name == "benchmark_results":
            # Delete results for old runs (foreign key will cascade)
            # We need to get run_ids first, then delete from benchmark_runs
            # which will cascade to benchmark_results
            cursor = conn.execute(
                """
                SELECT run_id FROM benchmark_runs WHERE timestamp_utc < ?
                """,
                (cutoff,),
            )
            run_ids = [row[0] for row in cursor.fetchall()]

            if not run_ids:
                return 0

            # Count results to be deleted
            placeholders = ",".join("?" * len(run_ids))
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM benchmark_results WHERE run_id IN ({placeholders})",
                run_ids,
            )
            count = cursor.fetchone()[0]

            # Delete runs (cascades to results and system_info)
            conn.execute(
                f"DELETE FROM benchmark_runs WHERE run_id IN ({placeholders})",
                run_ids,
            )

            return count

        elif table_name == "benchmark_runs":
            # Delete runs (cascades to results and system_info)
            cursor = conn.execute(
                "DELETE FROM benchmark_runs WHERE timestamp_utc < ?",
                (cutoff,),
            )
            return cursor.rowcount

        else:
            timestamp_col = self.TABLE_TIMESTAMP_COLUMNS.get(table_name)
            if not timestamp_col:
                logger.warning(f"No timestamp column for table {table_name}")
                return 0

            cursor = conn.execute(
                f"DELETE FROM {table_name} WHERE {timestamp_col} < ?",
                (cutoff,),
            )
            return cursor.rowcount

    def vacuum_database(self) -> int:
        """Vacuum database to reclaim space after deletions.

        Returns:
            Database size reduction in bytes (approximate)
        """
        if self.db_path == ":memory:":
            return 0

        # Get size before vacuum
        size_before = Path(self.db_path).stat().st_size

        conn = self._create_connection()
        try:
            conn.execute("VACUUM")
            conn.close()

            # Get size after vacuum
            size_after = Path(self.db_path).stat().st_size
            reduction = size_before - size_after

            logger.info(
                f"Database vacuumed: {size_before:,} -> {size_after:,} bytes "
                f"({reduction:,} bytes reclaimed)"
            )

            return reduction
        except Exception as e:
            logger.error(f"Database vacuum failed: {e}")
            return 0
        finally:
            if conn:
                conn.close()
