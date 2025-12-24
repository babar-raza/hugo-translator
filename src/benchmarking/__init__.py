"""Benchmarking system for persistent performance tracking.

This package provides:
- SQLite-backed storage for benchmark runs
- System information collection
- Benchmark corpus management
- CLI tools for running and analyzing benchmarks
- Query API for filtering and aggregating runs

Feature flag: features.enable_model_benchmarking in config/global.yaml
"""

from src.benchmarking.query import BenchmarkQueryAPI, BenchmarkQueryBuilder
from src.benchmarking.statistics import (
    BenchmarkStatistics,
    StatisticalSummary,
    ComparisonResult,
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
