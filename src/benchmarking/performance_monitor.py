"""Performance monitoring for benchmark queries.

Tracks query execution time, slow query detection, and performance telemetry.

Features:
- Query duration tracking
- Slow query logging (configurable threshold)
- Performance metrics aggregation
- Telemetry integration
- Query pattern analysis

Example:
    monitor = PerformanceMonitor(slow_threshold_ms=500)

    # Monitor a query
    with monitor.track_query("get_performance_trends", model_id="m2m100"):
        result = execute_query()

    # Check for slow queries
    slow_queries = monitor.get_slow_queries()
    for query in slow_queries:
        print(f"Slow query: {query['name']} took {query['duration_ms']}ms")
"""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

logger = logging.getLogger(__name__)


@dataclass
class QueryMetric:
    """Single query execution metric."""
    name: str
    duration_ms: float
    timestamp: str
    params: dict[str, any] = field(default_factory=dict)
    row_count: int | None = None
    cache_hit: bool = False


class PerformanceMonitor:
    """Monitor and track benchmark query performance.

    Provides query execution tracking, slow query detection, and performance
    telemetry for analytics queries.

    Example:
        monitor = PerformanceMonitor(slow_threshold_ms=500)

        # Track query execution
        with monitor.track_query("get_trends", model_id="m2m100", device="cpu"):
            results = query_database()

        # Get statistics
        stats = monitor.get_stats()
        print(f"Avg query time: {stats['avg_duration_ms']:.2f}ms")

        # Check slow queries
        if monitor.has_slow_queries():
            slow = monitor.get_slow_queries()
            print(f"Found {len(slow)} slow queries")
    """

    def __init__(
        self,
        slow_threshold_ms: float = 500.0,
        engines: Optional["SharedEngines"] = None
    ):
        """Initialize performance monitor.

        Args:
            slow_threshold_ms: Threshold for slow query logging (milliseconds)
            engines: Optional SharedEngines for telemetry
        """
        self.slow_threshold_ms = slow_threshold_ms
        self.engines = engines

        # Query metrics storage
        self._metrics: list[QueryMetric] = []
        self._slow_queries: list[QueryMetric] = []

        # Aggregated statistics
        self._total_queries = 0
        self._total_duration_ms = 0.0
        self._cache_hits = 0

        logger.info(
            f"PerformanceMonitor initialized: slow_threshold={slow_threshold_ms}ms"
        )

    @contextmanager
    def track_query(
        self,
        query_name: str,
        **params
    ) -> Generator[None, None, None]:
        """Track query execution time (context manager).

        Args:
            query_name: Name/identifier for the query
            **params: Query parameters for logging

        Yields:
            None

        Example:
            with monitor.track_query("get_trends", model_id="m2m100"):
                results = execute_query()
        """
        start_time = time.perf_counter()
        start_timestamp = datetime.now(UTC).isoformat()

        try:
            yield
        finally:
            # Calculate duration
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000

            # Create metric
            metric = QueryMetric(
                name=query_name,
                duration_ms=duration_ms,
                timestamp=start_timestamp,
                params=params
            )

            # Record metric
            self._record_metric(metric)

    def record_query(
        self,
        query_name: str,
        duration_ms: float,
        row_count: int | None = None,
        cache_hit: bool = False,
        **params
    ) -> None:
        """Record a completed query execution.

        Args:
            query_name: Name/identifier for the query
            duration_ms: Query duration in milliseconds
            row_count: Number of rows returned
            cache_hit: Whether result came from cache
            **params: Query parameters for logging
        """
        metric = QueryMetric(
            name=query_name,
            duration_ms=duration_ms,
            timestamp=datetime.now(UTC).isoformat(),
            params=params,
            row_count=row_count,
            cache_hit=cache_hit
        )

        self._record_metric(metric)

    def _record_metric(self, metric: QueryMetric) -> None:
        """Record a query metric.

        Args:
            metric: Query metric to record
        """
        # Store metric
        self._metrics.append(metric)

        # Update statistics
        self._total_queries += 1
        self._total_duration_ms += metric.duration_ms

        if metric.cache_hit:
            self._cache_hits += 1

        # Check if slow query
        if metric.duration_ms > self.slow_threshold_ms:
            self._slow_queries.append(metric)
            logger.warning(
                f"Slow query detected: {metric.name} took {metric.duration_ms:.2f}ms "
                f"(threshold: {self.slow_threshold_ms}ms) - params: {metric.params}"
            )

            # Emit telemetry for slow query
            if self.engines:
                self.engines.telemetry.track_event(
                    "benchmark_slow_query",
                    query_name=metric.name,
                    duration_ms=metric.duration_ms,
                    threshold_ms=self.slow_threshold_ms,
                    params=metric.params
                )
        else:
            logger.debug(
                f"Query: {metric.name} completed in {metric.duration_ms:.2f}ms"
            )

        # Emit telemetry for all queries
        if self.engines:
            self.engines.telemetry.track_event(
                "benchmark_query_executed",
                query_name=metric.name,
                duration_ms=metric.duration_ms,
                cache_hit=metric.cache_hit,
                row_count=metric.row_count
            )

        # Trim metrics list if too large (keep last 1000)
        if len(self._metrics) > 1000:
            self._metrics = self._metrics[-1000:]

    def get_stats(self) -> dict[str, any]:
        """Get performance statistics.

        Returns:
            Dictionary with performance metrics:
            - total_queries: Total number of queries tracked
            - total_duration_ms: Total execution time
            - avg_duration_ms: Average query duration
            - slow_queries_count: Number of slow queries detected
            - slow_threshold_ms: Slow query threshold
            - cache_hits: Number of cache hits
            - cache_hit_rate: Cache hit rate (0.0 to 1.0)
        """
        avg_duration = (
            self._total_duration_ms / self._total_queries
            if self._total_queries > 0 else 0.0
        )

        cache_hit_rate = (
            self._cache_hits / self._total_queries
            if self._total_queries > 0 else 0.0
        )

        return {
            "total_queries": self._total_queries,
            "total_duration_ms": self._total_duration_ms,
            "avg_duration_ms": avg_duration,
            "slow_queries_count": len(self._slow_queries),
            "slow_threshold_ms": self.slow_threshold_ms,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": cache_hit_rate,
        }

    def get_slow_queries(self, limit: int = 10) -> list[dict[str, any]]:
        """Get list of slow queries.

        Args:
            limit: Maximum number of queries to return

        Returns:
            List of slow query details (sorted by duration, slowest first)
        """
        # Sort by duration (slowest first)
        sorted_queries = sorted(
            self._slow_queries,
            key=lambda m: m.duration_ms,
            reverse=True
        )

        # Convert to dictionaries
        return [
            {
                "name": m.name,
                "duration_ms": m.duration_ms,
                "timestamp": m.timestamp,
                "params": m.params,
                "row_count": m.row_count,
            }
            for m in sorted_queries[:limit]
        ]

    def has_slow_queries(self) -> bool:
        """Check if any slow queries have been detected.

        Returns:
            True if slow queries exist
        """
        return len(self._slow_queries) > 0

    def get_query_patterns(self) -> dict[str, dict[str, any]]:
        """Analyze query patterns and performance by query name.

        Returns:
            Dictionary mapping query names to their statistics
        """
        patterns = {}

        for metric in self._metrics:
            if metric.name not in patterns:
                patterns[metric.name] = {
                    "count": 0,
                    "total_duration_ms": 0.0,
                    "min_duration_ms": float('inf'),
                    "max_duration_ms": 0.0,
                    "cache_hits": 0,
                }

            p = patterns[metric.name]
            p["count"] += 1
            p["total_duration_ms"] += metric.duration_ms
            p["min_duration_ms"] = min(p["min_duration_ms"], metric.duration_ms)
            p["max_duration_ms"] = max(p["max_duration_ms"], metric.duration_ms)

            if metric.cache_hit:
                p["cache_hits"] += 1

        # Calculate averages and rates
        for name, stats in patterns.items():
            stats["avg_duration_ms"] = stats["total_duration_ms"] / stats["count"]
            stats["cache_hit_rate"] = (
                stats["cache_hits"] / stats["count"] if stats["count"] > 0 else 0.0
            )

        return patterns

    def reset(self) -> None:
        """Reset all metrics and statistics."""
        self._metrics.clear()
        self._slow_queries.clear()
        self._total_queries = 0
        self._total_duration_ms = 0.0
        self._cache_hits = 0
        logger.info("Performance monitor reset")

    def log_summary(self) -> None:
        """Log a summary of performance statistics."""
        stats = self.get_stats()

        logger.info("=== Performance Monitor Summary ===")
        logger.info(f"Total queries: {stats['total_queries']}")
        logger.info(f"Average duration: {stats['avg_duration_ms']:.2f}ms")
        logger.info(
            f"Slow queries: {stats['slow_queries_count']} "
            f"(>{stats['slow_threshold_ms']}ms)"
        )
        logger.info(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")

        if self.has_slow_queries():
            logger.warning("Slowest queries:")
            for query in self.get_slow_queries(5):
                logger.warning(
                    f"  - {query['name']}: {query['duration_ms']:.2f}ms "
                    f"(params: {query['params']})"
                )
