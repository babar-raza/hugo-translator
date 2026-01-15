"""Time-series aggregation for benchmark data.

Provides pre-aggregated statistics at multiple time windows for dashboard performance:
- Hourly, daily, weekly, monthly aggregations
- Percentile calculations (p50, p95, p99)
- Incremental aggregation (only process new data)
- Performance baseline tracking

Implements Phase 4.1 analytics requirements with Phase 4.2 optimizations:
- Connection pooling
- Performance monitoring
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

from src.benchmarking.connection_pool import ConnectionPool
from src.benchmarking.performance_monitor import PerformanceMonitor

logger = logging.getLogger(__name__)


class _SimpleConnectionContext:
    """Simple context manager for non-pooled connections."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()
        return False


@dataclass
class AggregationWindow:
    """Time window definition for aggregation."""
    name: str  # 'hourly', 'daily', 'weekly', 'monthly'
    hours: int  # Window size in hours


# Predefined aggregation windows
AGGREGATION_WINDOWS = [
    AggregationWindow("hourly", 1),
    AggregationWindow("daily", 24),
    AggregationWindow("weekly", 168),  # 7 * 24
    AggregationWindow("monthly", 720),  # 30 * 24
]


class TimeSeriesAggregator:
    """Aggregates benchmark results into time-series trends.

    Features:
    - Pre-aggregate at multiple time windows
    - Calculate percentiles (p50, p95, p99)
    - Incremental aggregation (only new data)
    - Store in benchmark_trends table

    Example:
        aggregator = TimeSeriesAggregator(db_path="data/benchmarks.db")
        aggregator.aggregate_all()  # Aggregate all new data
        aggregator.aggregate_model("m2m100_418m", "cpu")  # Aggregate specific model
    """

    def __init__(
        self,
        db_path: Path | str,
        engines: Optional["SharedEngines"] = None,
        pool_size: int = 3,
        enable_pooling: bool = True,
        enable_monitoring: bool = True
    ):
        """Initialize aggregator.

        Args:
            db_path: Path to benchmark database
            engines: Optional SharedEngines for logging/telemetry
            pool_size: Connection pool size (default 3)
            enable_pooling: Enable connection pooling (default True)
            enable_monitoring: Enable performance monitoring (default True)
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        self.engines = engines

        # Phase 4.2 optimizations
        self._enable_pooling = enable_pooling
        self._enable_monitoring = enable_monitoring

        # Initialize connection pool
        self._pool: Optional[ConnectionPool] = None
        if enable_pooling and db_path != ":memory:":
            self._pool = ConnectionPool(db_path, pool_size=pool_size)
            logger.info(f"Connection pool enabled for aggregator: pool_size={pool_size}")

        # Initialize performance monitor
        self._monitor: Optional[PerformanceMonitor] = None
        if enable_monitoring:
            self._monitor = PerformanceMonitor(slow_threshold_ms=1000.0, engines=engines)
            logger.info("Performance monitoring enabled for aggregator")

        if engines:
            logger.info("TimeSeriesAggregator initialized with SharedEngines support")

    def _create_connection(self) -> sqlite3.Connection:
        """Create database connection (without pooling).

        Returns:
            Configured SQLite connection
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_connection(self):
        """Get database connection (with optional pooling).

        Returns:
            Connection context manager
        """
        if self._pool:
            return self._pool.get_connection()
        else:
            return _SimpleConnectionContext(self._create_connection())

    def close(self) -> None:
        """Close resources (connection pool, etc.)."""
        if self._pool:
            self._pool.close_all()
            logger.info("Aggregator connection pool closed")

    def get_monitor_stats(self) -> Optional[dict]:
        """Get performance monitor statistics.

        Returns:
            Monitor statistics dict or None if monitoring disabled
        """
        if self._monitor:
            return self._monitor.get_stats()
        return None


    def aggregate_all(self, lookback_days: int = 90) -> int:
        """Aggregate all models and devices for all time windows.

        Args:
            lookback_days: Number of days to look back for data

        Returns:
            Number of trend records created

        Raises:
            RuntimeError: If aggregation fails
        """
        # Emit telemetry: aggregation started
        if self.engines:
            self.engines.telemetry.track_event(
                "benchmark_aggregation_started",
                lookback_days=lookback_days
            )

        logger.info(f"Starting aggregation for all models (lookback: {lookback_days} days)")
        start_time = datetime.now(UTC)

        try:
            with self._get_connection() as conn:
                # Get unique model/device combinations
                cursor = conn.execute("""
                    SELECT DISTINCT model_id, device
                    FROM benchmark_runs
                    WHERE timestamp_utc >= datetime('now', ?)
                    ORDER BY model_id, device
                """, (f"-{lookback_days} days",))

                combinations = [(row["model_id"], row["device"]) for row in cursor.fetchall()]

                if not combinations:
                    logger.info("No benchmark data found for aggregation")
                    return 0

                logger.info(f"Found {len(combinations)} model/device combinations to aggregate")

                total_trends = 0
                for model_id, device in combinations:
                    trends = self.aggregate_model(
                        model_id=model_id,
                        device=device,
                        lookback_days=lookback_days,
                        conn=conn
                    )
                    total_trends += trends
                    logger.debug(f"  {model_id}/{device}: {trends} trends created")

                conn.commit()

            duration = (datetime.now(UTC) - start_time).total_seconds()
            duration_ms = duration * 1000

            # Record in monitor
            if self._monitor:
                self._monitor.record_query(
                    "aggregate_all",
                    duration_ms,
                    row_count=total_trends,
                    combinations=len(combinations)
                )

            logger.info(
                f"Aggregation completed: {total_trends} trends in {duration:.2f}s "
                f"({len(combinations)} combinations)"
            )

            # Emit telemetry: aggregation completed
            if self.engines:
                self.engines.telemetry.track_event(
                    "benchmark_aggregation_completed",
                    trends_created=total_trends,
                    combinations=len(combinations),
                    duration_seconds=duration
                )

            return total_trends

        except Exception as e:
            logger.error(f"Aggregation failed: {e}", exc_info=True)

            # Emit telemetry: aggregation failed
            if self.engines:
                self.engines.telemetry.track_event(
                    "benchmark_aggregation_failed",
                    error=str(e)
                )

            raise RuntimeError(f"Aggregation failed: {e}") from e

    def aggregate_model(
        self,
        model_id: str,
        device: str,
        lookback_days: int = 90,
        conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """Aggregate benchmark results for a specific model/device.

        Args:
            model_id: Model identifier
            device: Device name
            lookback_days: Number of days to look back
            conn: Optional database connection (for batch operations)

        Returns:
            Number of trend records created
        """
        should_close = conn is None
        if conn is None:
            conn = self._create_connection()

        try:
            total_trends = 0

            for window in AGGREGATION_WINDOWS:
                trends = self._aggregate_window(
                    conn=conn,
                    model_id=model_id,
                    device=device,
                    window=window,
                    lookback_days=lookback_days
                )
                total_trends += trends

            if should_close:
                conn.commit()

            return total_trends

        except Exception as e:
            if should_close:
                conn.rollback()
            raise
        finally:
            if should_close:
                conn.close()

    def _aggregate_window(
        self,
        conn: sqlite3.Connection,
        model_id: str,
        device: str,
        window: AggregationWindow,
        lookback_days: int
    ) -> int:
        """Aggregate data for a specific time window.

        Args:
            conn: Database connection
            model_id: Model identifier
            device: Device name
            window: Aggregation window definition
            lookback_days: Number of days to look back

        Returns:
            Number of trend records created
        """
        # Calculate window boundaries
        now = datetime.now(UTC)
        lookback_start = now - timedelta(days=lookback_days)

        # Get last aggregated window for this combination
        cursor = conn.execute("""
            SELECT MAX(window_end) as last_window
            FROM benchmark_trends
            WHERE model_id = ? AND device = ? AND time_window = ?
        """, (model_id, device, window.name))

        row = cursor.fetchone()
        last_window = row["last_window"] if row and row["last_window"] else None

        if last_window:
            # Incremental: only aggregate since last window
            start_time = datetime.fromisoformat(last_window)
        else:
            # Full aggregation
            start_time = lookback_start

        # Generate time windows
        windows = self._generate_time_windows(start_time, now, window.hours)

        if not windows:
            return 0

        trends_created = 0

        for window_start, window_end in windows:
            # Fetch results in this window
            cursor = conn.execute("""
                SELECT
                    br.throughput_tokens_per_sec,
                    br.duration_seconds,
                    br.peak_memory_mb
                FROM benchmark_results br
                JOIN benchmark_runs r ON br.run_id = r.run_id
                WHERE r.model_id = ?
                  AND r.device = ?
                  AND r.timestamp_utc >= ?
                  AND r.timestamp_utc < ?
                ORDER BY br.throughput_tokens_per_sec
            """, (model_id, device, window_start.isoformat(), window_end.isoformat()))

            results = cursor.fetchall()

            if not results:
                continue

            # Calculate statistics
            throughputs = [r["throughput_tokens_per_sec"] for r in results]
            durations = [r["duration_seconds"] for r in results]
            memories = [r["peak_memory_mb"] for r in results if r["peak_memory_mb"] is not None]

            stats = self._calculate_statistics(throughputs, durations, memories)

            # Insert trend record
            conn.execute("""
                INSERT OR REPLACE INTO benchmark_trends
                (model_id, device, time_window, window_start, window_end,
                 sample_count, avg_throughput, p50_throughput, p95_throughput, p99_throughput,
                 avg_duration, avg_memory_mb, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                model_id,
                device,
                window.name,
                window_start.isoformat(),
                window_end.isoformat(),
                stats["sample_count"],
                stats["avg_throughput"],
                stats["p50_throughput"],
                stats["p95_throughput"],
                stats["p99_throughput"],
                stats["avg_duration"],
                stats["avg_memory_mb"],
                now.isoformat()
            ))

            trends_created += 1

        return trends_created

    def _generate_time_windows(
        self,
        start: datetime,
        end: datetime,
        window_hours: int
    ) -> List[Tuple[datetime, datetime]]:
        """Generate time window boundaries.

        Args:
            start: Start time
            end: End time
            window_hours: Window size in hours

        Returns:
            List of (window_start, window_end) tuples
        """
        windows = []
        current = start.replace(minute=0, second=0, microsecond=0)

        while current < end:
            window_end = current + timedelta(hours=window_hours)
            if window_end > end:
                window_end = end

            windows.append((current, window_end))
            current = window_end

        return windows

    def _calculate_statistics(
        self,
        throughputs: List[float],
        durations: List[float],
        memories: List[float]
    ) -> dict:
        """Calculate aggregated statistics.

        Args:
            throughputs: List of throughput values
            durations: List of duration values
            memories: List of memory values

        Returns:
            Dictionary with statistics
        """
        return {
            "sample_count": len(throughputs),
            "avg_throughput": sum(throughputs) / len(throughputs) if throughputs else 0.0,
            "p50_throughput": self._percentile(throughputs, 50),
            "p95_throughput": self._percentile(throughputs, 95),
            "p99_throughput": self._percentile(throughputs, 99),
            "avg_duration": sum(durations) / len(durations) if durations else 0.0,
            "avg_memory_mb": sum(memories) / len(memories) if memories else None,
        }

    def _percentile(self, values: List[float], percentile: int) -> float:
        """Calculate percentile.

        Args:
            values: Sorted list of values
            percentile: Percentile (0-100)

        Returns:
            Percentile value
        """
        if not values:
            return 0.0

        # Values should already be sorted from SQL ORDER BY
        n = len(values)
        k = (n - 1) * percentile / 100
        f = int(k)
        c = k - f

        if f + 1 < n:
            return values[f] + c * (values[f + 1] - values[f])
        else:
            return values[f]

    def create_baseline(
        self,
        model_id: str,
        device: str,
        baseline_type: str,
        days_back: int = 30
    ) -> Optional[int]:
        """Create performance baseline from recent data.

        Args:
            model_id: Model identifier
            device: Device name
            baseline_type: Type of baseline ('daily', 'weekly', 'monthly')
            days_back: Number of days to include in baseline

        Returns:
            Baseline ID if created, None if insufficient data
        """
        conn = self._create_connection()
        try:
            # Fetch results from last N days
            cursor = conn.execute("""
                SELECT throughput_tokens_per_sec
                FROM benchmark_results br
                JOIN benchmark_runs r ON br.run_id = r.run_id
                WHERE r.model_id = ?
                  AND r.device = ?
                  AND r.timestamp_utc >= datetime('now', ?)
                ORDER BY throughput_tokens_per_sec
            """, (model_id, device, f"-{days_back} days"))

            throughputs = [row[0] for row in cursor.fetchall()]

            if len(throughputs) < 10:
                logger.warning(
                    f"Insufficient data for baseline: {len(throughputs)} samples "
                    f"(need at least 10)"
                )
                return None

            # Calculate baseline statistics
            avg_throughput = sum(throughputs) / len(throughputs)
            p50_throughput = self._percentile(throughputs, 50)
            p95_throughput = self._percentile(throughputs, 95)

            # Insert baseline
            baseline_date = datetime.now(UTC).date().isoformat()
            metadata = json.dumps({
                "days_back": days_back,
                "source": "automatic"
            })

            cursor = conn.execute("""
                INSERT OR REPLACE INTO performance_baselines
                (model_id, device, baseline_type, baseline_date,
                 avg_throughput, p50_throughput, p95_throughput,
                 sample_count, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                model_id,
                device,
                baseline_type,
                baseline_date,
                avg_throughput,
                p50_throughput,
                p95_throughput,
                len(throughputs),
                metadata,
                datetime.now(UTC).isoformat()
            ))

            baseline_id = cursor.lastrowid
            conn.commit()

            logger.info(
                f"Created baseline {baseline_id} for {model_id}/{device}: "
                f"avg={avg_throughput:.2f}, p50={p50_throughput:.2f}, p95={p95_throughput:.2f} "
                f"({len(throughputs)} samples)"
            )

            return baseline_id

        finally:
            conn.close()

    def cleanup_old_trends(self, retention_days: int = 365) -> int:
        """Remove old trend data according to retention policy.

        Args:
            retention_days: Keep trends newer than this

        Returns:
            Number of records deleted
        """
        conn = self._create_connection()
        try:
            cursor = conn.execute("""
                DELETE FROM benchmark_trends
                WHERE created_at < datetime('now', ?)
            """, (f"-{retention_days} days",))

            deleted = cursor.rowcount
            conn.commit()

            logger.info(f"Cleaned up {deleted} old trend records (retention: {retention_days} days)")
            return deleted

        finally:
            conn.close()
