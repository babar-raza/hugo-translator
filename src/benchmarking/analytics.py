"""Analytics query API for benchmark database.

Provides high-level query methods for dashboard and analysis:
- Performance trends over time
- Baseline comparisons
- Throughput distributions
- Model/device comparisons

Returns pandas DataFrames for easy analysis and visualization.
Implements Phase 4.1 analytics requirements with Phase 4.2 optimizations:
- Query result caching (LRU + TTL)
- Connection pooling
- Performance monitoring
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

from src.benchmarking.query_cache import QueryCache, make_cache_key
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


class AnalyticsQueryAPI:
    """High-level analytics queries for benchmark data.

    Provides pandas DataFrame-based query methods for:
    - Performance trends (time-series)
    - Baseline comparisons
    - Throughput distributions
    - Model/device performance analysis

    Example:
        api = AnalyticsQueryAPI(db_path="data/benchmarks.db")

        # Get daily trends for last 30 days
        trends = api.get_performance_trends("m2m100_418m", "cpu", "daily", 30)

        # Compare against baseline
        comparison = api.compare_performance("m2m100_418m", "cpu", "2024-01-01", "2024-02-01")

        # Get throughput distribution
        dist = api.get_throughput_distribution("m2m100_418m", "cpu", days=7)
    """

    def __init__(
        self,
        db_path: Path | str,
        engines: Optional["SharedEngines"] = None,
        cache_max_size: int = 100,
        cache_ttl_seconds: int = 300,
        pool_size: int = 5,
        enable_caching: bool = True,
        enable_pooling: bool = True,
        enable_monitoring: bool = True
    ):
        """Initialize analytics API.

        Args:
            db_path: Path to benchmark database
            engines: Optional SharedEngines for logging/telemetry
            cache_max_size: Maximum cache entries (default 100)
            cache_ttl_seconds: Cache TTL in seconds (default 300)
            pool_size: Connection pool size (default 5)
            enable_caching: Enable query result caching (default True)
            enable_pooling: Enable connection pooling (default True)
            enable_monitoring: Enable performance monitoring (default True)

        Raises:
            ImportError: If pandas is not available
        """
        if not PANDAS_AVAILABLE:
            raise ImportError(
                "pandas is required for analytics queries. "
                "Install with: pip install pandas"
            )

        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        self.engines = engines

        # Phase 4.2 optimizations
        self._enable_caching = enable_caching
        self._enable_pooling = enable_pooling
        self._enable_monitoring = enable_monitoring

        # Initialize query cache
        self._cache: Optional[QueryCache] = None
        if enable_caching:
            self._cache = QueryCache(max_size=cache_max_size, ttl_seconds=cache_ttl_seconds)
            logger.info(f"Query cache enabled: max_size={cache_max_size}, ttl={cache_ttl_seconds}s")

        # Initialize connection pool
        self._pool: Optional[ConnectionPool] = None
        if enable_pooling and db_path != ":memory:":
            self._pool = ConnectionPool(db_path, pool_size=pool_size)
            logger.info(f"Connection pool enabled: pool_size={pool_size}")

        # Initialize performance monitor
        self._monitor: Optional[PerformanceMonitor] = None
        if enable_monitoring:
            self._monitor = PerformanceMonitor(slow_threshold_ms=500.0, engines=engines)
            logger.info("Performance monitoring enabled")

        if engines:
            logger.info("AnalyticsQueryAPI initialized with SharedEngines support")

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
            # Return a simple context manager for non-pooled connections
            return _SimpleConnectionContext(self._create_connection())

    def close(self) -> None:
        """Close resources (connection pool, etc.)."""
        if self._pool:
            self._pool.close_all()
            logger.info("Connection pool closed")

    def get_cache_stats(self) -> Optional[Dict]:
        """Get query cache statistics.

        Returns:
            Cache statistics dict or None if caching disabled
        """
        if self._cache:
            return self._cache.get_stats()
        return None

    def get_monitor_stats(self) -> Optional[Dict]:
        """Get performance monitor statistics.

        Returns:
            Monitor statistics dict or None if monitoring disabled
        """
        if self._monitor:
            return self._monitor.get_stats()
        return None

    def invalidate_cache(self, pattern: Optional[str] = None) -> int:
        """Invalidate cached query results.

        Args:
            pattern: Optional pattern to match (None clears all)

        Returns:
            Number of entries invalidated
        """
        if not self._cache:
            return 0

        if pattern:
            return self._cache.invalidate_pattern(pattern)
        else:
            stats = self._cache.get_stats()
            self._cache.clear()
            return stats["size"]

    def _emit_query_event(self, query_type: str, duration_seconds: float, **kwargs) -> None:
        """Emit telemetry event for query execution.

        Args:
            query_type: Type of query executed
            duration_seconds: Query duration
            **kwargs: Additional query parameters
        """
        if self.engines:
            self.engines.telemetry.track_event(
                "benchmark_query_executed",
                query_type=query_type,
                duration_seconds=duration_seconds,
                **kwargs
            )

    def get_performance_trends(
        self,
        model_id: str,
        device: str,
        time_window: str = "daily",
        lookback_days: int = 30
    ) -> pd.DataFrame:
        """Get performance trends over time.

        Args:
            model_id: Model identifier
            device: Device name
            time_window: Time window ('hourly', 'daily', 'weekly', 'monthly')
            lookback_days: Number of days to look back

        Returns:
            DataFrame with columns: window_start, window_end, sample_count,
            avg_throughput, p50_throughput, p95_throughput, p99_throughput,
            avg_duration, avg_memory_mb

        Raises:
            ValueError: If time_window is invalid
        """
        start_time = datetime.now(UTC)

        valid_windows = ['hourly', 'daily', 'weekly', 'monthly']
        if time_window not in valid_windows:
            raise ValueError(
                f"Invalid time_window: {time_window}. "
                f"Must be one of: {valid_windows}"
            )

        # Check cache first
        cache_key = make_cache_key(
            "trends",
            model_id=model_id,
            device=device,
            window=time_window,
            days=lookback_days
        )

        if self._cache:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                if self._monitor:
                    self._monitor.record_query(
                        "get_performance_trends",
                        duration_ms,
                        row_count=len(cached_result),
                        cache_hit=True,
                        model_id=model_id,
                        device=device
                    )
                logger.debug(f"get_performance_trends: cache hit ({len(cached_result)} rows)")
                return cached_result

        # Cache miss - query database
        with self._get_connection() as conn:
            query = """
                SELECT
                    window_start,
                    window_end,
                    sample_count,
                    avg_throughput,
                    p50_throughput,
                    p95_throughput,
                    p99_throughput,
                    avg_duration,
                    avg_memory_mb
                FROM benchmark_trends
                WHERE model_id = ?
                  AND device = ?
                  AND time_window = ?
                  AND window_start >= datetime('now', ?)
                ORDER BY window_start
            """

            df = pd.read_sql_query(
                query,
                conn,
                params=(model_id, device, time_window, f"-{lookback_days} days")
            )

            # Convert timestamp columns to datetime
            if not df.empty:
                df['window_start'] = pd.to_datetime(df['window_start'])
                df['window_end'] = pd.to_datetime(df['window_end'])

        duration = (datetime.now(UTC) - start_time).total_seconds()
        duration_ms = duration * 1000

        # Record query in monitor
        if self._monitor:
            self._monitor.record_query(
                "get_performance_trends",
                duration_ms,
                row_count=len(df),
                cache_hit=False,
                model_id=model_id,
                device=device
            )

        # Store in cache
        if self._cache:
            self._cache.set(cache_key, df)

        self._emit_query_event(
            "get_performance_trends",
            duration,
            model_id=model_id,
            device=device,
            time_window=time_window,
            lookback_days=lookback_days,
            rows_returned=len(df)
        )

        logger.debug(
            f"get_performance_trends: {len(df)} rows in {duration:.3f}s "
            f"({model_id}/{device}/{time_window})"
        )

        return df

    def get_performance_baselines(
        self,
        model_id: str,
        device: str,
        baseline_type: Optional[str] = None
    ) -> pd.DataFrame:
        """Get performance baselines for model/device.

        Args:
            model_id: Model identifier
            device: Device name
            baseline_type: Optional baseline type filter

        Returns:
            DataFrame with columns: baseline_type, baseline_date,
            avg_throughput, p50_throughput, p95_throughput,
            sample_count, metadata, created_at
        """
        start_time = datetime.now(UTC)

        # Check cache first
        cache_key = make_cache_key(
            "baselines",
            model_id=model_id,
            device=device,
            type=baseline_type
        )

        if self._cache:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                if self._monitor:
                    self._monitor.record_query(
                        "get_performance_baselines",
                        duration_ms,
                        row_count=len(cached_result),
                        cache_hit=True,
                        model_id=model_id,
                        device=device
                    )
                logger.debug(f"get_performance_baselines: cache hit ({len(cached_result)} rows)")
                return cached_result

        # Cache miss - query database
        with self._get_connection() as conn:
            if baseline_type:
                query = """
                    SELECT
                        baseline_type,
                        baseline_date,
                        avg_throughput,
                        p50_throughput,
                        p95_throughput,
                        sample_count,
                        metadata,
                        created_at
                    FROM performance_baselines
                    WHERE model_id = ? AND device = ? AND baseline_type = ?
                    ORDER BY baseline_date DESC
                """
                params = (model_id, device, baseline_type)
            else:
                query = """
                    SELECT
                        baseline_type,
                        baseline_date,
                        avg_throughput,
                        p50_throughput,
                        p95_throughput,
                        sample_count,
                        metadata,
                        created_at
                    FROM performance_baselines
                    WHERE model_id = ? AND device = ?
                    ORDER BY baseline_date DESC
                """
                params = (model_id, device)

            df = pd.read_sql_query(query, conn, params=params)

            # Convert timestamp columns
            if not df.empty:
                df['baseline_date'] = pd.to_datetime(df['baseline_date'])
                df['created_at'] = pd.to_datetime(df['created_at'])

        duration = (datetime.now(UTC) - start_time).total_seconds()
        duration_ms = duration * 1000

        # Record query in monitor
        if self._monitor:
            self._monitor.record_query(
                "get_performance_baselines",
                duration_ms,
                row_count=len(df),
                cache_hit=False,
                model_id=model_id,
                device=device
            )

        # Store in cache
        if self._cache:
            self._cache.set(cache_key, df)

        self._emit_query_event(
            "get_performance_baselines",
            duration,
            model_id=model_id,
            device=device,
            baseline_type=baseline_type,
            rows_returned=len(df)
        )

        return df

    def compare_performance(
        self,
        model_id: str,
        device: str,
        baseline_date: str,
        current_date: Optional[str] = None
    ) -> Dict[str, float]:
        """Compare current performance against baseline.

        Args:
            model_id: Model identifier
            device: Device name
            baseline_date: Baseline date (YYYY-MM-DD)
            current_date: Current date for comparison (defaults to today)

        Returns:
            Dictionary with comparison metrics:
            - baseline_throughput: Baseline avg throughput
            - current_throughput: Current avg throughput
            - throughput_change_pct: Percentage change
            - baseline_p95: Baseline p95 throughput
            - current_p95: Current p95 throughput
            - p95_change_pct: Percentage change in p95
        """
        start_time = datetime.now(UTC)

        if current_date is None:
            current_date = datetime.now(UTC).date().isoformat()

        # Check cache first
        cache_key = make_cache_key(
            "compare_performance",
            model_id=model_id,
            device=device,
            baseline=baseline_date,
            current=current_date
        )

        if self._cache:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                if self._monitor:
                    self._monitor.record_query(
                        "compare_performance",
                        duration_ms,
                        cache_hit=True,
                        model_id=model_id,
                        device=device
                    )
                logger.debug("compare_performance: cache hit")
                return cached_result

        # Cache miss - query database
        with self._get_connection() as conn:
            # Get baseline
            cursor = conn.execute("""
                SELECT avg_throughput, p95_throughput
                FROM performance_baselines
                WHERE model_id = ? AND device = ? AND baseline_date = ?
            """, (model_id, device, baseline_date))

            baseline_row = cursor.fetchone()
            if not baseline_row:
                return {
                    "error": f"No baseline found for {baseline_date}",
                    "baseline_throughput": 0.0,
                    "current_throughput": 0.0,
                    "throughput_change_pct": 0.0
                }

            baseline_throughput = baseline_row["avg_throughput"]
            baseline_p95 = baseline_row["p95_throughput"]

            # Get current performance (last 7 days before current_date)
            cursor = conn.execute("""
                SELECT
                    AVG(throughput_tokens_per_sec) as avg_throughput
                FROM benchmark_results br
                JOIN benchmark_runs r ON br.run_id = r.run_id
                WHERE r.model_id = ?
                  AND r.device = ?
                  AND DATE(r.timestamp_utc) <= ?
                  AND DATE(r.timestamp_utc) > DATE(?, '-7 days')
            """, (model_id, device, current_date, current_date))

            current_row = cursor.fetchone()
            if not current_row or current_row["avg_throughput"] is None:
                return {
                    "error": "No current data found",
                    "baseline_throughput": baseline_throughput,
                    "baseline_p95": baseline_p95,
                    "current_throughput": 0.0,
                    "throughput_change_pct": 0.0
                }

            current_throughput = current_row["avg_throughput"]

            # Calculate p95 for current period
            cursor = conn.execute("""
                SELECT throughput_tokens_per_sec
                FROM benchmark_results br
                JOIN benchmark_runs r ON br.run_id = r.run_id
                WHERE r.model_id = ?
                  AND r.device = ?
                  AND DATE(r.timestamp_utc) <= ?
                  AND DATE(r.timestamp_utc) > DATE(?, '-7 days')
                ORDER BY throughput_tokens_per_sec
            """, (model_id, device, current_date, current_date))

            throughputs = [row[0] for row in cursor.fetchall()]
            current_p95 = self._percentile(throughputs, 95) if throughputs else 0.0

        # Calculate changes
        throughput_change = (
            ((current_throughput - baseline_throughput) / baseline_throughput * 100)
            if baseline_throughput > 0 else 0.0
        )

        p95_change = (
            ((current_p95 - baseline_p95) / baseline_p95 * 100)
            if baseline_p95 > 0 else 0.0
        )

        duration = (datetime.now(UTC) - start_time).total_seconds()
        duration_ms = duration * 1000

        # Record query in monitor
        if self._monitor:
            self._monitor.record_query(
                "compare_performance",
                duration_ms,
                cache_hit=False,
                model_id=model_id,
                device=device
            )

        result = {
            "baseline_throughput": baseline_throughput,
            "current_throughput": current_throughput,
            "throughput_change_pct": throughput_change,
            "baseline_p95": baseline_p95,
            "current_p95": current_p95,
            "p95_change_pct": p95_change
        }

        # Store in cache
        if self._cache:
            self._cache.set(cache_key, result)

        self._emit_query_event(
            "compare_performance",
            duration,
            model_id=model_id,
            device=device,
            baseline_date=baseline_date,
            current_date=current_date
        )

        return result

    def get_throughput_distribution(
        self,
        model_id: str,
        device: str,
        days: int = 7
    ) -> pd.DataFrame:
        """Get throughput distribution for recent data.

        Args:
            model_id: Model identifier
            device: Device name
            days: Number of days to include

        Returns:
            DataFrame with throughput values for distribution analysis
        """
        start_time = datetime.now(UTC)

        # Check cache first
        cache_key = make_cache_key(
            "distribution",
            model_id=model_id,
            device=device,
            days=days
        )

        if self._cache:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                if self._monitor:
                    self._monitor.record_query(
                        "get_throughput_distribution",
                        duration_ms,
                        row_count=len(cached_result),
                        cache_hit=True,
                        model_id=model_id,
                        device=device
                    )
                logger.debug(f"get_throughput_distribution: cache hit ({len(cached_result)} rows)")
                return cached_result

        # Cache miss - query database
        with self._get_connection() as conn:
            query = """
                SELECT
                    r.timestamp_utc,
                    br.batch_size,
                    br.throughput_tokens_per_sec,
                    br.duration_seconds,
                    br.peak_memory_mb
                FROM benchmark_results br
                JOIN benchmark_runs r ON br.run_id = r.run_id
                WHERE r.model_id = ?
                  AND r.device = ?
                  AND r.timestamp_utc >= datetime('now', ?)
                ORDER BY r.timestamp_utc
            """

            df = pd.read_sql_query(
                query,
                conn,
                params=(model_id, device, f"-{days} days")
            )

            if not df.empty:
                df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])

        duration = (datetime.now(UTC) - start_time).total_seconds()
        duration_ms = duration * 1000

        # Record query in monitor
        if self._monitor:
            self._monitor.record_query(
                "get_throughput_distribution",
                duration_ms,
                row_count=len(df),
                cache_hit=False,
                model_id=model_id,
                device=device
            )

        # Store in cache
        if self._cache:
            self._cache.set(cache_key, df)

        self._emit_query_event(
            "get_throughput_distribution",
            duration,
            model_id=model_id,
            device=device,
            days=days,
            rows_returned=len(df)
        )

        return df

    def get_model_comparison(
        self,
        model_ids: List[str],
        device: str,
        days: int = 30
    ) -> pd.DataFrame:
        """Compare multiple models on same device.

        Args:
            model_ids: List of model identifiers to compare
            device: Device name
            days: Number of days to include

        Returns:
            DataFrame with comparison metrics per model
        """
        start_time = datetime.now(UTC)

        # Check cache first
        cache_key = make_cache_key(
            "model_comparison",
            models="|".join(sorted(model_ids)),
            device=device,
            days=days
        )

        if self._cache:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                if self._monitor:
                    self._monitor.record_query(
                        "get_model_comparison",
                        duration_ms,
                        row_count=len(cached_result),
                        cache_hit=True,
                        device=device
                    )
                logger.debug(f"get_model_comparison: cache hit ({len(cached_result)} rows)")
                return cached_result

        # Cache miss - query database
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(model_ids))
            query = f"""
                SELECT
                    r.model_id,
                    COUNT(*) as sample_count,
                    AVG(br.throughput_tokens_per_sec) as avg_throughput,
                    AVG(br.duration_seconds) as avg_duration,
                    AVG(br.peak_memory_mb) as avg_memory_mb,
                    MIN(br.throughput_tokens_per_sec) as min_throughput,
                    MAX(br.throughput_tokens_per_sec) as max_throughput
                FROM benchmark_results br
                JOIN benchmark_runs r ON br.run_id = r.run_id
                WHERE r.model_id IN ({placeholders})
                  AND r.device = ?
                  AND r.timestamp_utc >= datetime('now', ?)
                GROUP BY r.model_id
                ORDER BY avg_throughput DESC
            """

            params = tuple(model_ids) + (device, f"-{days} days")
            df = pd.read_sql_query(query, conn, params=params)

        duration = (datetime.now(UTC) - start_time).total_seconds()
        duration_ms = duration * 1000

        # Record query in monitor
        if self._monitor:
            self._monitor.record_query(
                "get_model_comparison",
                duration_ms,
                row_count=len(df),
                cache_hit=False,
                device=device
            )

        # Store in cache
        if self._cache:
            self._cache.set(cache_key, df)

        self._emit_query_event(
            "get_model_comparison",
            duration,
            model_count=len(model_ids),
            device=device,
            days=days,
            rows_returned=len(df)
        )

        return df

    def get_device_comparison(
        self,
        model_id: str,
        devices: List[str],
        days: int = 30
    ) -> pd.DataFrame:
        """Compare model performance across devices.

        Args:
            model_id: Model identifier
            devices: List of device names to compare
            days: Number of days to include

        Returns:
            DataFrame with comparison metrics per device
        """
        start_time = datetime.now(UTC)

        # Check cache first
        cache_key = make_cache_key(
            "device_comparison",
            model_id=model_id,
            devices="|".join(sorted(devices)),
            days=days
        )

        if self._cache:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                if self._monitor:
                    self._monitor.record_query(
                        "get_device_comparison",
                        duration_ms,
                        row_count=len(cached_result),
                        cache_hit=True,
                        model_id=model_id
                    )
                logger.debug(f"get_device_comparison: cache hit ({len(cached_result)} rows)")
                return cached_result

        # Cache miss - query database
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(devices))
            query = f"""
                SELECT
                    r.device,
                    COUNT(*) as sample_count,
                    AVG(br.throughput_tokens_per_sec) as avg_throughput,
                    AVG(br.duration_seconds) as avg_duration,
                    AVG(br.peak_memory_mb) as avg_memory_mb
                FROM benchmark_results br
                JOIN benchmark_runs r ON br.run_id = r.run_id
                WHERE r.model_id = ?
                  AND r.device IN ({placeholders})
                  AND r.timestamp_utc >= datetime('now', ?)
                GROUP BY r.device
                ORDER BY avg_throughput DESC
            """

            params = (model_id,) + tuple(devices) + (f"-{days} days",)
            df = pd.read_sql_query(query, conn, params=params)

        duration = (datetime.now(UTC) - start_time).total_seconds()
        duration_ms = duration * 1000

        # Record query in monitor
        if self._monitor:
            self._monitor.record_query(
                "get_device_comparison",
                duration_ms,
                row_count=len(df),
                cache_hit=False,
                model_id=model_id
            )

        # Store in cache
        if self._cache:
            self._cache.set(cache_key, df)

        self._emit_query_event(
            "get_device_comparison",
            duration,
            model_id=model_id,
            device_count=len(devices),
            days=days,
            rows_returned=len(df)
        )

        return df

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

        values = sorted(values)
        n = len(values)
        k = (n - 1) * percentile / 100
        f = int(k)
        c = k - f

        if f + 1 < n:
            return values[f] + c * (values[f + 1] - values[f])
        else:
            return values[f]
