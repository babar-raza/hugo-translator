"""Benchmarking system for persistent performance tracking.

This package provides:
- SQLite-backed storage for benchmark runs
- System information collection
- Benchmark corpus management
- CLI tools for running and analyzing benchmarks

Feature flag: features.enable_model_benchmarking in config/global.yaml
"""

from src.benchmarking.storage import BenchmarkDatabase

__all__ = ["BenchmarkDatabase"]
