# Benchmarking API Reference

**Last Updated**: 2025-12-24
**Status**: Production-Ready
**Version**: 1.0

## Overview

This document provides a complete API reference for the benchmarking system. All classes and methods are documented with signatures, parameters, return types, and usage examples.

## Table of Contents

- [Storage Layer](#storage-layer)
- [System Information](#system-information)
- [Production Metrics](#production-metrics)
- [Model Recommendation](#model-recommendation)
- [Feedback Loop](#feedback-loop)
- [Configuration](#configuration)

## Storage Layer

### BenchmarkDatabase

File: `src/benchmarking/storage.py`

Main database interface for storing and retrieving benchmark runs.

#### Constructor

```python
def __init__(self, db_path: Path)
```

**Parameters**:
- `db_path` (Path): Path to SQLite database file

**Example**:
```python
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
```

#### save_run()

```python
def save_run(self, run: BenchmarkRun) -> None
```

Save a complete benchmark run to database.

**Parameters**:
- `run` (BenchmarkRun): Benchmark run to save

**Raises**:
- `sqlite3.Error`: If database operation fails

**Example**:
```python
run = BenchmarkRun(
    run_id="test_run_001",
    model_id="facebook/m2m100_418M",
    device="cpu",
    batch_sizes=[8],
    iterations=10,
    corpus_category="small",
    purpose="development",
    tags=["test", "cpu"],
    system_info=system_info,
    results=[...],
    total_duration_seconds=120.5,
)
db.save_run(run)
```

#### get_run()

```python
def get_run(self, run_id: str) -> Optional[BenchmarkRun]
```

Retrieve a benchmark run by ID.

**Parameters**:
- `run_id` (str): Unique run identifier

**Returns**:
- `BenchmarkRun` if found, `None` otherwise

**Example**:
```python
run = db.get_run("test_run_001")
if run:
    print(f"Model: {run.model_id}")
    print(f"Results: {len(run.results)}")
```

#### list_runs()

```python
def list_runs(
    self,
    model_id: Optional[str] = None,
    device: Optional[str] = None,
    purpose: Optional[str] = None,
    limit: int = 100
) -> List[Tuple[str, str, str, str, int]]
```

List benchmark runs with optional filtering.

**Parameters**:
- `model_id` (Optional[str]): Filter by model ID
- `device` (Optional[str]): Filter by device (cpu/cuda)
- `purpose` (Optional[str]): Filter by purpose (development/production/comparison)
- `limit` (int): Maximum number of runs to return (default: 100)

**Returns**:
- List of tuples: (run_id, model_id, device, timestamp_utc, result_count)

**Example**:
```python
# Get all CPU runs
cpu_runs = db.list_runs(device="cpu", limit=50)

# Get production runs
prod_runs = db.list_runs(purpose="production", limit=100)

for run_id, model_id, device, timestamp, count in cpu_runs:
    print(f"{run_id}: {model_id} on {device} ({count} results)")
```

#### compare_runs()

```python
def compare_runs(
    self,
    run_ids: List[str],
    metric: str = "throughput_tokens_per_sec"
) -> Dict[str, Dict[str, float]]
```

Compare performance metrics across multiple runs.

**Parameters**:
- `run_ids` (List[str]): List of run IDs to compare
- `metric` (str): Metric to compare (default: "throughput_tokens_per_sec")

**Returns**:
- Dictionary mapping run_id to statistics (mean, min, max, p50, p95, p99)

**Example**:
```python
comparison = db.compare_runs(
    run_ids=["run_001", "run_002", "run_003"],
    metric="throughput_tokens_per_sec"
)

for run_id, stats in comparison.items():
    print(f"{run_id}: mean={stats['mean']:.1f}, p95={stats['p95']:.1f}")
```

#### get_schema_version()

```python
def get_schema_version(self) -> int
```

Get current database schema version.

**Returns**:
- Integer schema version (1-4)

**Example**:
```python
version = db.get_schema_version()
print(f"Schema version: {version}")
```

### Data Classes

#### SystemInfo

```python
@dataclass
class SystemInfo:
    cpu_model: str
    cpu_cores: int
    total_ram_gb: float
    gpu_model: Optional[str] = None
    gpu_memory_gb: Optional[float] = None
    # ... additional fields
```

See [System Information](#system-information) for full details.

#### BenchmarkResult

```python
@dataclass
class BenchmarkResult:
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
```

#### BenchmarkRun

```python
@dataclass
class BenchmarkRun:
    run_id: str
    model_id: str
    device: str
    batch_sizes: List[int]
    iterations: int
    corpus_category: Optional[str]
    purpose: str  # "development", "production", "comparison"
    tags: List[str]
    system_info: SystemInfo
    results: List[BenchmarkResult]
    total_duration_seconds: float
    timestamp_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## System Information

### SystemInfoCollector

File: `src/benchmarking/system_info.py`

Collects comprehensive system hardware and software information.

#### Constructor

```python
def __init__(self)
```

**Example**:
```python
from src.benchmarking.system_info import SystemInfoCollector

collector = SystemInfoCollector()
```

#### collect()

```python
def collect(self) -> SystemInfo
```

Collect complete system information.

**Returns**:
- `SystemInfo` object with hardware and platform details

**Example**:
```python
info = collector.collect()

print(f"CPU: {info.cpu_model}")
print(f"Cores: {info.cpu_cores}")
print(f"RAM: {info.total_ram_gb:.1f} GB")
if info.gpu_model:
    print(f"GPU: {info.gpu_model}")
    print(f"VRAM: {info.gpu_memory_gb:.1f} GB")
```

#### sanitize_path()

```python
def sanitize_path(self, path: str) -> str
```

Remove PII (usernames, home directories) from file paths.

**Parameters**:
- `path` (str): File path to sanitize

**Returns**:
- Sanitized path with `[HOME]` or `[USER]` placeholders

**Example**:
```python
original = "/home/john.doe/projects/hugo-translator/data/tm"
sanitized = collector.sanitize_path(original)
# Result: "[HOME]/projects/hugo-translator/data/tm"
```

### SystemInfo

```python
@dataclass
class SystemInfo:
    # Hardware
    cpu_model: str
    cpu_cores: int
    total_ram_gb: float

    # GPU (optional)
    gpu_model: Optional[str] = None
    gpu_memory_gb: Optional[float] = None
    gpu_compute_capability: Optional[str] = None
    has_cuda: bool = False
    cuda_version: Optional[str] = None

    # Extended hardware context (BM-09)
    cpu_frequency_mhz: Optional[float] = None
    cpu_frequency_max_mhz: Optional[float] = None
    memory_bandwidth_gbps: Optional[float] = None
    numa_nodes: int = 1

    # Platform
    os_name: str = ""
    os_version: str = ""
    python_version: str = ""
    torch_version: Optional[str] = None

    # Metadata
    collected_at_utc: str = ""
    collector_version: str = "1.0.1"
```

## Production Metrics

### ProductionMetricsIngestor

File: `src/benchmarking/production_ingestor.py`

Records production translation runs as benchmark data (OPT-IN).

#### Constructor

```python
def __init__(self, db: BenchmarkDatabase, enabled: bool = False)
```

**Parameters**:
- `db` (BenchmarkDatabase): Database instance
- `enabled` (bool): Enable recording (default: False - OPT-IN)

**Example**:
```python
from src.benchmarking.production_ingestor import ProductionMetricsIngestor

# Disabled by default (OPT-IN)
ingestor = ProductionMetricsIngestor(db)

# Explicitly enable
ingestor_enabled = ProductionMetricsIngestor(db, enabled=True)
```

#### record_translation_run()

```python
def record_translation_run(
    self,
    file_path: str,
    target_lang: str,
    segments_translated: int,
    segments_from_tm: int,
    segments_translated_new: int,
    translation_model: str,
    retry_count: int,
    success: bool,
    duration_seconds: float = 0.0,
) -> None
```

Record a production translation run.

**Parameters**:
- `file_path` (str): Path to translated file
- `target_lang` (str): Target language code
- `segments_translated` (int): Total segments translated
- `segments_from_tm` (int): Segments from translation memory
- `segments_translated_new` (int): Newly translated segments
- `translation_model` (str): Model ID used
- `retry_count` (int): Number of retries
- `success` (bool): Whether translation succeeded
- `duration_seconds` (float): Total duration (default: 0.0)

**Notes**:
- No-op when `enabled=False`
- Never crashes translation pipeline (catches all exceptions)
- Thread-safe

**Example**:
```python
ingestor = ProductionMetricsIngestor(db, enabled=True)

ingestor.record_translation_run(
    file_path="content/blog/post.md",
    target_lang="es",
    segments_translated=150,
    segments_from_tm=120,
    segments_translated_new=30,
    translation_model="facebook/m2m100_418M",
    retry_count=0,
    success=True,
    duration_seconds=45.2,
)
```

## Model Recommendation

### ModelRecommender

File: `src/benchmarking/recommender.py`

Generates ML-based model configuration recommendations.

#### Constructor

```python
def __init__(self, db: BenchmarkDatabase, learning_rate: float = 0.1)
```

**Parameters**:
- `db` (BenchmarkDatabase): Database instance
- `learning_rate` (float): Learning rate for weight updates (0-1, default: 0.1)

**Example**:
```python
from src.benchmarking.recommender import ModelRecommender

recommender = ModelRecommender(db, learning_rate=0.1)
```

#### recommend()

```python
def recommend(
    self,
    system_info: SystemInfo,
    requirements: Optional[Dict[str, any]] = None,
) -> ModelRecommendation
```

Generate a model recommendation.

**Parameters**:
- `system_info` (SystemInfo): Current system hardware
- `requirements` (Optional[Dict]): Optional constraints:
  - `max_memory_mb` (int): Maximum memory limit
  - `min_throughput` (float): Minimum throughput requirement
  - `prefer_quality` (bool): Prefer quality over speed

**Returns**:
- `ModelRecommendation` with best configuration

**Example**:
```python
from src.benchmarking.system_info import SystemInfoCollector

collector = SystemInfoCollector()
system_info = collector.collect()

recommendation = recommender.recommend(
    system_info=system_info,
    requirements={
        "max_memory_mb": 4000,
        "min_throughput": 30.0,
    }
)

print(f"Recommended: {recommendation.model_id}")
print(f"Batch size: {recommendation.batch_size}")
print(f"Confidence: {recommendation.confidence_score:.2f}")
```

#### record_outcome()

```python
def record_outcome(self, feedback: RecommendationFeedback) -> None
```

Record recommendation outcome for learning.

**Parameters**:
- `feedback` (RecommendationFeedback): Actual vs. predicted performance

**Example**:
```python
from src.benchmarking.feedback import RecommendationFeedback

feedback = RecommendationFeedback(
    recommendation_id=recommendation.recommendation_id,
    predicted_throughput=recommendation.predicted_throughput,
    actual_throughput=32.5,
    predicted_memory_mb=recommendation.predicted_memory_mb,
    actual_memory_mb=3800.0,
    user_satisfied=True,
)

recommender.record_outcome(feedback)
```

### ModelRecommendation

```python
@dataclass
class ModelRecommendation:
    recommendation_id: str
    model_id: str
    device: str
    batch_size: int
    predicted_throughput: float
    predicted_memory_mb: float
    confidence_score: float  # 0-1, higher is better
    reasoning: str  # Human-readable explanation
```

## Feedback Loop

### AdaptiveWeightLearner

File: `src/benchmarking/feedback.py`

Learns from recommendation feedback to improve future suggestions.

#### Constructor

```python
def __init__(self, db: BenchmarkDatabase, learning_rate: float = 0.1)
```

**Parameters**:
- `db` (BenchmarkDatabase): Database instance
- `learning_rate` (float): Learning rate for weight updates (0-1, default: 0.1)

**Example**:
```python
from src.benchmarking.feedback import AdaptiveWeightLearner

learner = AdaptiveWeightLearner(db, learning_rate=0.1)
```

#### get_current_weights()

```python
def get_current_weights(self) -> Dict[str, float]
```

Get current feature weights.

**Returns**:
- Dictionary of feature weights (normalized to sum to 1.0)

**Default Weights**:
```python
{
    "throughput": 1.0,
    "memory": 0.8,
    "historical_success": 0.4,
}
```

**Example**:
```python
weights = learner.get_current_weights()
print(f"Throughput weight: {weights['throughput']:.2f}")
print(f"Memory weight: {weights['memory']:.2f}")
```

#### update_weights()

```python
def update_weights(self, feedback: RecommendationFeedback) -> Dict[str, float]
```

Update weights based on prediction error.

**Parameters**:
- `feedback` (RecommendationFeedback): Feedback with actual metrics

**Returns**:
- Updated weights dictionary

**Example**:
```python
new_weights = learner.update_weights(feedback)
print(f"Updated weights: {new_weights}")
```

### RecommendationFeedback

```python
@dataclass
class RecommendationFeedback:
    recommendation_id: str
    predicted_throughput: float
    actual_throughput: float
    predicted_memory_mb: float
    actual_memory_mb: float
    user_satisfied: bool
```

## Error Handling

All API methods follow these error handling conventions:

### Storage Operations

```python
try:
    db.save_run(run)
except sqlite3.Error as e:
    logger.error(f"Database error: {e}")
    # Handle error (retry, fallback, alert)
```

### Production Metrics

```python
# ProductionMetricsIngestor never raises exceptions
# Always catches and logs errors internally
ingestor.record_translation_run(...)  # Safe to call, never crashes
```

### System Information

```python
try:
    info = collector.collect()
except Exception as e:
    logger.warning(f"System info collection failed: {e}")
    # Falls back to minimal info
```

## Thread Safety

### Thread-Safe Components

- `BenchmarkDatabase`: Uses thread-local connections + write lock
- `ProductionMetricsIngestor`: Uses threading.Lock for serialization
- `ModelRecommender`: Read-only operations are thread-safe
- `AdaptiveWeightLearner`: Write operations use database lock

### Usage in Multi-Threaded Context

```python
import concurrent.futures

db = BenchmarkDatabase(db_path)  # Single instance
ingestor = ProductionMetricsIngestor(db, enabled=True)

def translate_file(file_path):
    # Each thread can safely record metrics
    ingestor.record_translation_run(...)

# Safe: Multiple threads recording concurrently
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    executor.map(translate_file, file_paths)
```

## Performance Characteristics

| Operation | Typical Latency | Concurrent? |
|-----------|----------------|-------------|
| `save_run()` | 5-10 ms | No (serialized) |
| `get_run()` | <1 ms | Yes (WAL mode) |
| `list_runs()` | 10-50 ms | Yes |
| `recommend()` | 20-100 ms | Yes |
| `record_translation_run()` | <10 ms | No (serialized) |
| `collect()` (SystemInfo) | 50-200 ms | Yes |

## Configuration

### get_metrics_config()

File: `src/utils/config_loader.py`

Retrieve metrics configuration with defaults and environment variable overrides.

```python
def get_metrics_config() -> Dict[str, Any]
```

**Returns**:
- `Dict[str, Any]`: Configuration dictionary with structure:
  ```python
  {
      "metrics": {
          "storage": {
              "translation_engine": {"retry_metrics_maxlen": int},
              "l3_semantic": {"timing_metrics_maxlen": int},
              "batch_optimizer": {"timing_metrics_maxlen": int}
          },
          "statistics": {
              "percentiles": List[float],
              "min_samples_for_p95": int,
              "min_samples_for_p99": int
          },
          "thresholds": {
              "l3_search_timeout_ms": int,
              "retry_max_duration_ms": int,
              ...
          }
      }
  }
  ```

**Example**:
```python
from src.utils.config_loader import get_metrics_config

config = get_metrics_config()

# Get storage limits
engine_maxlen = config["metrics"]["storage"]["translation_engine"]["retry_metrics_maxlen"]
l3_maxlen = config["metrics"]["storage"]["l3_semantic"]["timing_metrics_maxlen"]

# Use in component initialization
from collections import deque

self._retry_metrics = {
    "retry_attempts": deque(maxlen=engine_maxlen),
    "retry_durations_ms": deque(maxlen=engine_maxlen),
}
```

**Configuration Sources** (in priority order):
1. Environment variables (highest priority)
   - `METRICS_ENGINE_MAXLEN` → `retry_metrics_maxlen`
   - `METRICS_L3_MAXLEN` → `timing_metrics_maxlen` (L3)
   - `METRICS_BATCH_MAXLEN` → `timing_metrics_maxlen` (Batch)
   - `METRICS_PERCENTILES` → `percentiles` (comma-separated)
2. `config/metrics.yaml` file
3. Built-in defaults (lowest priority)

**Defaults**:
```python
{
    "metrics": {
        "storage": {
            "translation_engine": {"retry_metrics_maxlen": 1000},
            "l3_semantic": {"timing_metrics_maxlen": 10000},
            "batch_optimizer": {"timing_metrics_maxlen": 5000}
        },
        "statistics": {
            "percentiles": [0.50, 0.95, 0.99],
            "min_samples_for_p95": 20,
            "min_samples_for_p99": 100
        },
        "thresholds": {
            "l3_search_timeout_ms": 100,
            "retry_max_duration_ms": 30000,
            ...
        }
    }
}
```

**Thread Safety**: This function caches the configuration on first call and reuses it. The cache is module-level and thread-safe for reads.

See [Metrics Configuration](../configuration/metrics.md) for complete documentation on tuning and environment variables.

### calc_stats()

File: `src/utils/metrics.py`

Calculate comprehensive statistics from timing values.

```python
def calc_stats(values: List[float]) -> Dict[str, float]
```

**Parameters**:
- `values` (List[float] | deque): Numeric values (supports both list and deque)

**Returns**:
- `Dict[str, float]` with keys:
  - `count`: Number of values
  - `mean`: Average value
  - `min`: Minimum value
  - `max`: Maximum value
  - `total`: Sum of all values
  - `p50`: 50th percentile (median)
  - `p95`: 95th percentile (requires min_samples_for_p95)
  - `p99`: 99th percentile (requires min_samples_for_p99)

**Example**:
```python
from collections import deque
from src.utils.metrics import calc_stats

# Collect timing data
timings = deque(maxlen=1000)
for operation in operations:
    start = time.perf_counter()
    operation()
    timings.append((time.perf_counter() - start) * 1000)

# Calculate statistics
stats = calc_stats(timings)
print(f"Mean: {stats['mean']:.2f} ms")
print(f"P95: {stats['p95']:.2f} ms")
print(f"P99: {stats['p99']:.2f} ms")
```

**Edge Cases**:
- Empty values: Returns all zeros
- `len(values) < 20`: p95 falls back to max
- `len(values) < 100`: p99 falls back to max

**Performance**: O(n log n) due to sorting for percentiles. Cached results recommended for frequent access.

## See Also

- [Benchmarking Features](../features/benchmarking.md) - Feature overview
- [Benchmarking Architecture](../architecture/benchmarking-system.md) - Design details
- [Benchmarking Examples](../examples/benchmarking-examples.md) - Usage examples
- [Benchmarking Operations](../operations/benchmarking-operations.md) - Operational guide
- [Metrics Configuration](../configuration/metrics.md) - Configuration reference

## Changelog

### 2025-12-24 - v1.0
- Initial API reference
- Complete method documentation
- Usage examples
- Error handling patterns
- Thread safety guidelines
- Added configuration API documentation (get_metrics_config, calc_stats)
- Documented bounded storage configuration system
