"""Benchmark query builder and API for filtering and aggregating runs.

This module provides a fluent query builder for constructing complex
queries against the benchmark database, plus a high-level API for
common query patterns.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .storage import BenchmarkDatabase, BenchmarkRun, SystemInfo

logger = logging.getLogger(__name__)


@dataclass
class QueryFilter:
    """Individual filter component."""

    field: str
    operator: str  # "=", ">=", "<=", "LIKE", "IN"
    value: Any
    table: str = "benchmark_runs"  # or "system_info"


class BenchmarkQueryBuilder:
    """Fluent API for building benchmark queries.

    Example:
        query = (BenchmarkQueryBuilder()
                .by_model("facebook/m2m100_418M")
                .by_device("cpu")
                .by_throughput_range(min_tps=50.0)
                .sort_by("timestamp_utc", ascending=False)
                .limit(10))
        sql, params = query.build()
    """

    def __init__(self):
        self._filters: List[QueryFilter] = []
        self._sort_field: Optional[str] = None
        self._sort_ascending: bool = True
        self._limit_n: Optional[int] = None
        self._offset_n: int = 0

    def by_model(self, model_id: str) -> "BenchmarkQueryBuilder":
        """Filter by model ID."""
        self._filters.append(QueryFilter("model_id", "=", model_id, "benchmark_runs"))
        return self

    def by_device(self, device: str) -> "BenchmarkQueryBuilder":
        """Filter by device (cpu, cuda, etc.)."""
        self._filters.append(QueryFilter("device", "=", device, "benchmark_runs"))
        return self

    def by_hardware(
        self,
        cpu_cores: Optional[int] = None,
        ram_gb_min: Optional[float] = None,
        ram_gb_max: Optional[float] = None,
        gpu_model: Optional[str] = None,
    ) -> "BenchmarkQueryBuilder":
        """Filter by hardware configuration."""
        if cpu_cores is not None:
            self._filters.append(QueryFilter("cpu_cores", "=", cpu_cores, "system_info"))
        if ram_gb_min is not None:
            self._filters.append(QueryFilter("total_ram_gb", ">=", ram_gb_min, "system_info"))
        if ram_gb_max is not None:
            self._filters.append(QueryFilter("total_ram_gb", "<=", ram_gb_max, "system_info"))
        if gpu_model is not None:
            self._filters.append(QueryFilter("gpu_model", "LIKE", f"%{gpu_model}%", "system_info"))
        return self

    def by_throughput_range(
        self, min_tps: Optional[float] = None, max_tps: Optional[float] = None
    ) -> "BenchmarkQueryBuilder":
        """Filter by throughput range (requires aggregation in query execution)."""
        # This will be handled by the API layer via subquery
        if min_tps is not None:
            self._filters.append(
                QueryFilter("throughput_tokens_per_sec", ">=", min_tps, "benchmark_results")
            )
        if max_tps is not None:
            self._filters.append(
                QueryFilter("throughput_tokens_per_sec", "<=", max_tps, "benchmark_results")
            )
        return self

    def by_date_range(
        self, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> "BenchmarkQueryBuilder":
        """Filter by timestamp range."""
        if start is not None:
            self._filters.append(QueryFilter("timestamp_utc", ">=", start.isoformat(), "benchmark_runs"))
        if end is not None:
            self._filters.append(QueryFilter("timestamp_utc", "<=", end.isoformat(), "benchmark_runs"))
        return self

    def by_tags(self, *tags: str, match_all: bool = True) -> "BenchmarkQueryBuilder":
        """Filter by tags (JSON array match)."""
        # SQLite JSON handling - will use JSON_EXTRACT or similar
        for tag in tags:
            # Store tags filter for special handling in build()
            self._filters.append(QueryFilter("tags", "LIKE", f'%"{tag}"%', "benchmark_runs"))
        return self

    def by_corpus_category(self, category: str) -> "BenchmarkQueryBuilder":
        """Filter by corpus category."""
        self._filters.append(QueryFilter("corpus_category", "=", category, "benchmark_runs"))
        return self

    def sort_by(self, field: str, ascending: bool = True) -> "BenchmarkQueryBuilder":
        """Sort results by field."""
        self._sort_field = field
        self._sort_ascending = ascending
        return self

    def limit(self, n: int) -> "BenchmarkQueryBuilder":
        """Limit number of results."""
        self._limit_n = n
        return self

    def offset(self, n: int) -> "BenchmarkQueryBuilder":
        """Offset results (for pagination)."""
        self._offset_n = n
        return self

    def build(self) -> Tuple[str, List[Any]]:
        """Build SQL query and parameters.

        Returns:
            Tuple of (sql_query, parameters)
        """
        # Determine if we need to join with system_info or benchmark_results
        needs_system_join = any(f.table == "system_info" for f in self._filters)
        needs_results_join = any(f.table == "benchmark_results" for f in self._filters)

        # Base query
        query = "SELECT DISTINCT r.* FROM benchmark_runs r"
        params: List[Any] = []

        # Add joins
        if needs_system_join:
            query += " LEFT JOIN system_info s ON r.run_id = s.run_id"
        if needs_results_join:
            query += " LEFT JOIN benchmark_results br ON r.run_id = br.run_id"

        # Add WHERE clause
        if self._filters:
            query += " WHERE "
            conditions = []
            for f in self._filters:
                prefix = {"benchmark_runs": "r", "system_info": "s", "benchmark_results": "br"}[
                    f.table
                ]
                if f.operator == "LIKE":
                    conditions.append(f"{prefix}.{f.field} {f.operator} ?")
                    params.append(f.value)
                elif f.operator == "IN":
                    placeholders = ",".join("?" * len(f.value))
                    conditions.append(f"{prefix}.{f.field} IN ({placeholders})")
                    params.extend(f.value)
                else:
                    conditions.append(f"{prefix}.{f.field} {f.operator} ?")
                    params.append(f.value)
            query += " AND ".join(conditions)

        # Add ORDER BY
        if self._sort_field:
            direction = "ASC" if self._sort_ascending else "DESC"
            query += f" ORDER BY r.{self._sort_field} {direction}"
        else:
            # Default sort by timestamp descending
            query += " ORDER BY r.timestamp_utc DESC"

        # Add LIMIT/OFFSET
        if self._limit_n is not None:
            query += f" LIMIT {self._limit_n}"
        if self._offset_n > 0:
            query += f" OFFSET {self._offset_n}"

        return query, params


class BenchmarkQueryAPI:
    """High-level API for querying benchmarks.

    This class wraps BenchmarkQueryBuilder and provides convenience
    methods for common query patterns.
    """

    def __init__(self, db: BenchmarkDatabase):
        """Initialize query API.

        Args:
            db: BenchmarkDatabase instance
        """
        self.db = db

    def query(self, builder: BenchmarkQueryBuilder) -> List[BenchmarkRun]:
        """Execute a query built with BenchmarkQueryBuilder.

        Args:
            builder: Configured query builder

        Returns:
            List of matching BenchmarkRun objects
        """
        sql, params = builder.build()
        logger.debug(f"Executing query: {sql} with params: {params}")

        conn = self.db._get_connection()
        try:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            # Convert rows to run_ids, then fetch full runs
            run_ids = [row["run_id"] for row in rows]
            runs = [self.db.get_run(run_id) for run_id in run_ids]
            return [r for r in runs if r is not None]
        finally:
            self.db._close_connection(conn)

    def aggregate(
        self, builder: BenchmarkQueryBuilder, metric: str, func: str = "avg"
    ) -> Optional[float]:
        """Aggregate a metric across query results.

        Args:
            builder: Query builder for filtering
            metric: Metric field name (e.g., "throughput_tokens_per_sec")
            func: Aggregation function ("avg", "min", "max", "sum", "count")

        Returns:
            Aggregated value, or None if no results
        """
        runs = self.query(builder)
        if not runs:
            return None

        # Extract metric values from results
        values = []
        for run in runs:
            for result in run.results:
                if hasattr(result, metric):
                    val = getattr(result, metric)
                    if val is not None:
                        values.append(val)

        if not values:
            return None

        # Apply aggregation function
        if func == "avg":
            return sum(values) / len(values)
        elif func == "min":
            return min(values)
        elif func == "max":
            return max(values)
        elif func == "sum":
            return sum(values)
        elif func == "count":
            return float(len(values))
        else:
            raise ValueError(f"Unknown aggregation function: {func}")

    def group_by(
        self, builder: BenchmarkQueryBuilder, group_field: str, metric: str
    ) -> Dict[str, float]:
        """Group results and aggregate by field.

        Args:
            builder: Query builder for filtering
            group_field: Field to group by (e.g., "device", "model_id")
            metric: Metric to aggregate

        Returns:
            Dictionary mapping group values to aggregated metric
        """
        runs = self.query(builder)
        if not runs:
            return {}

        # Group runs by field
        groups: Dict[str, List[float]] = {}
        for run in runs:
            if hasattr(run, group_field):
                group_val = getattr(run, group_field)
            else:
                continue

            if group_val not in groups:
                groups[group_val] = []

            for result in run.results:
                if hasattr(result, metric):
                    val = getattr(result, metric)
                    if val is not None:
                        groups[group_val].append(val)

        # Aggregate each group
        return {
            group: sum(values) / len(values) if values else 0.0 for group, values in groups.items()
        }

    def find_best(
        self,
        hardware_profile: Optional[Dict[str, Any]] = None,
        metric: str = "throughput_tokens_per_sec",
        limit: int = 1,
    ) -> List[BenchmarkRun]:
        """Find best performing runs for a hardware profile.

        Args:
            hardware_profile: Dict with keys like cpu_cores, ram_gb, gpu_model
            metric: Metric to optimize
            limit: Number of results to return

        Returns:
            List of top-performing runs
        """
        builder = BenchmarkQueryBuilder()

        if hardware_profile:
            builder.by_hardware(
                cpu_cores=hardware_profile.get("cpu_cores"),
                ram_gb_min=hardware_profile.get("ram_gb_min"),
                ram_gb_max=hardware_profile.get("ram_gb_max"),
                gpu_model=hardware_profile.get("gpu_model"),
            )

        # Sort by metric (descending for throughput)
        builder.sort_by("timestamp_utc", ascending=False).limit(limit * 10)

        runs = self.query(builder)

        # Sort by actual metric value from results
        runs_with_metric = []
        for run in runs:
            if run.results:
                avg_metric = sum(
                    getattr(r, metric) for r in run.results if hasattr(r, metric) and getattr(r, metric) is not None
                ) / len([r for r in run.results if hasattr(r, metric) and getattr(r, metric) is not None])
                runs_with_metric.append((run, avg_metric))

        runs_with_metric.sort(key=lambda x: x[1], reverse=True)
        return [run for run, _ in runs_with_metric[:limit]]

    def find_similar_hardware(
        self, system_info: SystemInfo, tolerance: float = 0.2
    ) -> List[BenchmarkRun]:
        """Find runs on similar hardware.

        Args:
            system_info: SystemInfo to match against
            tolerance: Tolerance for RAM matching (0.2 = ±20%)

        Returns:
            List of runs on similar hardware
        """
        ram_min = system_info.total_ram_gb * (1 - tolerance)
        ram_max = system_info.total_ram_gb * (1 + tolerance)

        builder = BenchmarkQueryBuilder().by_hardware(
            cpu_cores=system_info.cpu_cores, ram_gb_min=ram_min, ram_gb_max=ram_max
        )

        if system_info.gpu_model:
            # Extract GPU family (e.g., "RTX 3080" -> "RTX")
            gpu_family = system_info.gpu_model.split()[0] if system_info.gpu_model else None
            if gpu_family:
                builder.by_hardware(gpu_model=gpu_family)

        return self.query(builder)
