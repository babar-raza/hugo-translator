"""Benchmarking system for persistent performance tracking.

This package provides:
- SQLite-backed storage for benchmark runs
- System information collection
- Benchmark corpus management
- CLI tools for running and analyzing benchmarks
- Query API for filtering and aggregating runs

Feature flag: features.enable_model_benchmarking in config/global.yaml

Note: Heavy ML dependencies (torch) are lazily imported to allow
CLI --help to work without the full ML stack installed.
"""
from typing import TYPE_CHECKING

# TYPE_CHECKING guard: These imports are only used for type hints
# and won't be executed at runtime
if TYPE_CHECKING:
    from src.benchmarking.query import BenchmarkQueryAPI, BenchmarkQueryBuilder
    from src.benchmarking.statistics import (
        BenchmarkStatistics,
        ComparisonResult,
        StatisticalSummary,
    )
    from src.benchmarking.storage import BenchmarkDatabase

__all__ = [
    "BenchmarkDatabase",
    "BenchmarkQueryAPI",
    "BenchmarkQueryBuilder",
    "BenchmarkStatistics",
    "StatisticalSummary",
    "ComparisonResult",
]


def __getattr__(name):
    """Lazy import for heavy dependencies."""
    if name == "BenchmarkDatabase":
        from src.benchmarking.storage import BenchmarkDatabase
        return BenchmarkDatabase
    elif name == "BenchmarkQueryAPI":
        from src.benchmarking.query import BenchmarkQueryAPI
        return BenchmarkQueryAPI
    elif name == "BenchmarkQueryBuilder":
        from src.benchmarking.query import BenchmarkQueryBuilder
        return BenchmarkQueryBuilder
    elif name == "BenchmarkStatistics":
        from src.benchmarking.statistics import BenchmarkStatistics
        return BenchmarkStatistics
    elif name == "StatisticalSummary":
        from src.benchmarking.statistics import StatisticalSummary
        return StatisticalSummary
    elif name == "ComparisonResult":
        from src.benchmarking.statistics import ComparisonResult
        return ComparisonResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
