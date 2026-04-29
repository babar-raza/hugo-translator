# Benchmarking System

**Last Updated**: 2025-12-24
**Status**: Production-Ready
**Version**: 1.0

## Overview

The Hugo Translation System includes a comprehensive benchmarking system for measuring translation performance, recording production metrics, and generating ML-based model recommendations. The system enables data-driven optimization of translation workflows through automated performance tracking and adaptive learning.

### Purpose

- **Performance Measurement**: Accurately measure translation throughput, memory usage, and latency
- **Model Comparison**: Compare different translation models and configurations on your hardware
- **Production Learning**: Optionally record real translation workloads to improve recommendations (OPT-IN)
- **Adaptive Recommendations**: Get ML-based suggestions for optimal model configurations based on system capabilities and historical performance

### Key Benefits

- **Informed Decisions**: Choose models based on real benchmark data, not guesswork
- **Resource Optimization**: Identify memory and throughput bottlenecks before production
- **Continuous Improvement**: Learn from production workloads to refine recommendations over time
- **Hardware Awareness**: Benchmarks automatically detect and record system capabilities

## Architecture

The benchmarking system consists of five core components:

```
┌─────────────────────────────────────────────────────────────┐
│                    Benchmarking System                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────┐      ┌──────────────────────┐          │
│  │ BenchmarkDatabase│◄────┤ SystemInfoCollector │          │
│  │  (storage.py)   │      │  (system_info.py)   │          │
│  │                 │      │  - Hardware detect  │          │
│  │  - SQLite DB    │      │  - PII sanitization│          │
│  │  - Schema v4    │      └──────────────────────┘          │
│  │  - Migrations   │                                        │
│  └────────┬────────┘                                        │
│           │                                                  │
│  ┌────────▼────────────────────────────────────────┐       │
│  │  ProductionMetricsIngestor (OPT-IN)            │       │
│  │  (production_ingestor.py)                      │       │
│  │  - Records translation runs                     │       │
│  │  - Thread-safe                                  │       │
│  │  - Enabled=False default                        │       │
│  └────────┬────────────────────────────────────────┘       │
│           │                                                  │
│  ┌────────▼────────────────────────────────────────┐       │
│  │  ModelRecommender                               │       │
│  │  (recommender.py)                               │       │
│  │  - ML-based scoring                             │       │
│  │  - System similarity matching                   │       │
│  │  - Confidence scoring                           │       │
│  └────────┬────────────────────────────────────────┘       │
│           │                                                  │
│  ┌────────▼────────────────────────────────────────┐       │
│  │  AdaptiveWeightLearner                          │       │
│  │  (feedback.py)                                  │       │
│  │  - Feedback loop                                │       │
│  │  - Weight updates                               │       │
│  │  - Prediction refinement                        │       │
│  └─────────────────────────────────────────────────┘       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
        ▲                                    ▲
        │                                    │
┌───────┴──────────┐              ┌─────────┴──────────┐
│ TranslationEngine│              │  Benchmark Runner  │
│ (BM-08 timing)   │              │  (runner.py)       │
└──────────────────┘              └────────────────────┘
```

### Component Descriptions

1. **BenchmarkDatabase** (`src/benchmarking/storage.py`)
   - SQLite-based persistent storage with WAL mode for concurrent reads
   - Schema version 4 with automatic migrations from v1-v3
   - Stores benchmark runs, system info, and detailed results
   - Thread-safe write operations

2. **SystemInfoCollector** (`src/benchmarking/system_info.py`)
   - Detects CPU, GPU, memory, and platform information
   - Sanitizes paths to prevent PII (username/homedir) leakage
   - Extended hardware context: CPU frequency, NUMA nodes, power state
   - Reuses `HardwareDetector` from model runtime

3. **ProductionMetricsIngestor** (`src/benchmarking/production_ingestor.py`)
   - **OPT-IN** by design: `enabled=False` default
   - Records production translation runs as benchmark data
   - Thread-safe for concurrent translations
   - Graceful error handling (never crashes translation pipeline)

4. **ModelRecommender** (`src/benchmarking/recommender.py`)
   - ML-based recommendation engine
   - Finds similar benchmark runs by hardware (±2 cores, ±4GB RAM)
   - Weighted scoring: throughput, memory, historical success
   - Confidence scoring based on data availability

5. **AdaptiveWeightLearner** (`src/benchmarking/feedback.py`)
   - Feedback loop for continuous improvement
   - Updates feature weights based on prediction accuracy
   - Learns from actual vs. predicted performance
   - Configurable learning rate (default: 0.1)

## Configuration

### OPT-IN Production Metrics

Production metrics recording is **disabled by default** and must be explicitly enabled:

```python
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.production_ingestor import ProductionMetricsIngestor

# Initialize database
db = BenchmarkDatabase("data/benchmarks/production.db")

# Enable production metrics (OPT-IN)
ingestor = ProductionMetricsIngestor(db, enabled=True)
```

**Privacy Design**:
- All system paths are sanitized to remove usernames and home directories
- Only aggregated performance metrics are recorded
- No translation content or source files are stored
- Can be disabled at any time without data loss

### Database Location

```yaml
# config/benchmarking.yaml
database:
  path: "data/benchmarks/benchmarks.db"
  wal_mode: true  # Enable Write-Ahead Logging for concurrent reads
  busy_timeout_ms: 30000  # 30 second timeout for write locks
```

### Benchmark Corpus

```yaml
# config/benchmark_corpus.yaml
corpus:
  tiny:
    min_length: 10
    max_length: 50
    sample_count: 10

  small:
    min_length: 20
    max_length: 100
    sample_count: 50

  medium:
    min_length: 50
    max_length: 200
    sample_count: 200
```

## Usage Examples

### Running a Benchmark

```bash
# Quick benchmark with tiny corpus
python -m src.benchmarking.cli run \
    --model facebook/m2m100_418M \
    --device cpu \
    --batch-size 8 \
    --corpus tiny \
    --output data/benchmarks/benchmarks.db

# Comprehensive benchmark
python -m src.benchmarking.cli run \
    --model facebook/m2m100_418M \
    --device cpu \
    --batch-sizes 4,8,16 \
    --iterations 3 \
    --corpus small \
    --output data/benchmarks/benchmarks.db \
    --verbose
```

### Comparing Models

```bash
# Compare HuggingFace vs CTranslate2
python -m src.benchmarking.cli compare \
    --models facebook/m2m100_418M,ct2/m2m100_418m \
    --device cpu \
    --batch-size 8 \
    --corpus small \
    --output-report comparison_report.json
```

### Getting Recommendations

```python
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.recommender import ModelRecommender
from src.benchmarking.system_info import SystemInfoCollector

# Initialize components
db = BenchmarkDatabase("data/benchmarks/benchmarks.db")
recommender = ModelRecommender(db)
collector = SystemInfoCollector()

# Get current system info
system_info = collector.collect()

# Get recommendation
recommendation = recommender.recommend(
    system_info=system_info,
    requirements={
        "max_memory_mb": 4000,  # 4GB limit
        "min_throughput": 30.0,  # 30 tokens/sec minimum
    }
)

print(f"Recommended: {recommendation.model_id}")
print(f"Device: {recommendation.device}")
print(f"Batch size: {recommendation.batch_size}")
print(f"Predicted throughput: {recommendation.predicted_throughput:.1f} tokens/sec")
print(f"Predicted memory: {recommendation.predicted_memory_mb:.0f} MB")
print(f"Confidence: {recommendation.confidence_score:.2f}")
print(f"Reasoning: {recommendation.reasoning}")
```

### Recording Production Metrics

```python
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.production_ingestor import ProductionMetricsIngestor

# Initialize with OPT-IN enabled
db = BenchmarkDatabase("data/benchmarks/production.db")
ingestor = ProductionMetricsIngestor(db, enabled=True)

# Record translation run
ingestor.record_translation_run(
    file_path="content/blog/post.md",
    target_lang="es",
    segments_translated=150,
    segments_from_tm=120,
    segments_translated_new=30,
    translation_model="facebook/m2m100_418M",
    retry_count=2,
    success=True,
    duration_seconds=45.2,
)
```

### Providing Feedback

```python
from src.benchmarking.feedback import RecommendationFeedback

# After using a recommendation, provide feedback
feedback = RecommendationFeedback(
    recommendation_id=recommendation.recommendation_id,
    predicted_throughput=recommendation.predicted_throughput,
    actual_throughput=32.5,  # Measured actual throughput
    predicted_memory_mb=recommendation.predicted_memory_mb,
    actual_memory_mb=3800.0,  # Measured actual memory
    user_satisfied=True,
)

recommender.record_outcome(feedback)
```

## Performance Characteristics

### Database Operations

- **Write**: ~5-10ms per benchmark run (SQLite WAL mode)
- **Read**: <1ms for single run lookup
- **Query**: 10-50ms for similarity search (100 runs)
- **Concurrent reads**: Supported via WAL mode
- **Concurrent writes**: Serialized with 30s timeout

### Memory Usage

- **BenchmarkDatabase**: ~10MB baseline (SQLite connection pool)
- **SystemInfoCollector**: ~1MB (hardware detection)
- **ModelRecommender**: ~5MB + 100KB per cached run
- **ProductionMetricsIngestor**: ~2MB (when enabled)

**Bounded Metrics** (BM-07 fix):
- All timing metrics use `deque(maxlen=N)` to prevent memory leaks
- TranslationEngine: maxlen=1000 (~8KB)
- L3SemanticTM: maxlen=10000 (~80KB)
- BatchOptimizer: maxlen=5000 (~40KB)

### Timing Instrumentation (BM-08)

Detailed timing metrics are automatically recorded:

```python
# TranslationEngine
translation_duration_ms = [...]  # Per-file translation times

# L3SemanticTM
semantic_search_ms = [...]  # Semantic search latencies
add_entry_ms = [...]  # Entry addition times
batch_add_ms = [...]  # Batch addition times

# BatchOptimizer
prepare_batches_ms = [...]  # Batch preparation overhead
process_batch_ms = [...]  # Batch processing times
oom_recovery_ms = [...]  # OOM recovery times
batch_size_adjustments_ms = [...]  # Adjustment times
```

## Security Considerations

### PII Sanitization

The `SystemInfoCollector` automatically sanitizes all paths to prevent personal information leakage:

```python
# Before sanitization
"/home/john.doe/projects/hugo-translator/data/benchmarks/test.db"

# After sanitization
"[HOME]/projects/hugo-translator/data/benchmarks/test.db"
```

**Sanitized Elements**:
- Usernames in paths
- Home directories
- Absolute paths converted to relative
- Windows drive letters preserved

### OPT-IN Design

Production metrics ingestion is **OPT-IN** by default:

```python
# Default: Disabled (safe for all environments)
ingestor = ProductionMetricsIngestor(db)  # enabled=False

# Explicit opt-in required
ingestor = ProductionMetricsIngestor(db, enabled=True)
```

**Rationale**:
- Prevents unintended data collection
- Respects user privacy
- Complies with data governance policies
- Requires explicit consent

## Best Practices

### 1. Run Benchmarks Before Production

Always benchmark on target hardware before deploying:

```bash
# Benchmark all models you're considering
python -m src.benchmarking.cli run \
    --models facebook/m2m100_418M,ct2/m2m100_418m,ct2/m2m100_418m_int8 \
    --device cpu \
    --batch-sizes 4,8,16 \
    --iterations 5 \
    --corpus medium
```

### 2. Use Recommendations with Requirements

Provide constraints to get practical recommendations:

```python
recommendation = recommender.recommend(
    system_info=system_info,
    requirements={
        "max_memory_mb": available_memory * 0.7,  # 70% of available
        "min_throughput": target_throughput,
    }
)
```

### 3. Provide Feedback for Learning

Close the feedback loop to improve future recommendations:

```python
# After running with recommendation
feedback = RecommendationFeedback(
    recommendation_id=rec.recommendation_id,
    predicted_throughput=rec.predicted_throughput,
    actual_throughput=measured_throughput,
    predicted_memory_mb=rec.predicted_memory_mb,
    actual_memory_mb=measured_memory,
    user_satisfied=True,
)
recommender.record_outcome(feedback)
```

### 4. Monitor Production Metrics (Optional)

If you enable production metrics, monitor them regularly:

```python
# Query recent production runs
runs = db.list_runs(purpose="production", limit=100)

# Analyze trends
for run_id, model_id, device, timestamp, count in runs:
    run = db.get_run(run_id)
    print(f"{model_id}: {run.total_duration_seconds:.1f}s")
```

## Integration with Translation Engine

### Automatic Timing Collection (BM-08)

The translation engine automatically collects timing metrics:

```python
# src/translation_engine/engine.py
from collections import deque

class TranslationEngine:
    def __init__(self, ...):
        # Bounded metrics to prevent memory leak
        self._timing_metrics = {
            "translation_duration_ms": deque(maxlen=1000),
            "tm_lookup_ms": deque(maxlen=1000),
            "validation_ms": deque(maxlen=1000),
        }

    def translate_file(self, ...):
        start = time.perf_counter()
        # ... translation logic ...
        duration_ms = (time.perf_counter() - start) * 1000
        self._timing_metrics["translation_duration_ms"].append(duration_ms)
```

### Production Metrics Hook

```python
# Optional: Enable production metrics in TranslationEngine
engine = TranslationEngine(
    model=model,
    tm=tm,
    production_metrics=ProductionMetricsIngestor(db, enabled=True)
)
```

## Troubleshooting

### Issue: Database locked errors

**Symptom**: `sqlite3.OperationalError: database is locked`

**Cause**: Concurrent writes without WAL mode or insufficient timeout

**Solution**:
```python
# Ensure WAL mode is enabled
db = BenchmarkDatabase(db_path)
db._init_schema()  # Automatically enables WAL

# Increase busy timeout if needed
# Set in config/benchmarking.yaml:
database:
  busy_timeout_ms: 60000  # 60 seconds
```

### Issue: Recommendations are inaccurate

**Symptom**: Predicted throughput/memory far from actual

**Cause**: Insufficient benchmark data or outdated weights

**Solution**:
```bash
# Run more benchmarks on similar hardware
python -m src.benchmarking.cli run \
    --iterations 10 \
    --corpus medium

# Provide feedback to update weights
# (see "Providing Feedback" section above)
```

### Issue: Memory leak in long-running processes

**Symptom**: Memory usage grows unbounded over time

**Cause**: Unbounded timing metric lists (pre-BM-07)

**Solution**: Verify bounded deque usage:
```python
# Should be deque with maxlen, not list
assert isinstance(engine._timing_metrics["translation_duration_ms"], deque)
assert engine._timing_metrics["translation_duration_ms"].maxlen == 1000
```

### Issue: PII leakage in system info

**Symptom**: Usernames visible in stored paths

**Cause**: Sanitization failure

**Solution**: Verify sanitization:
```python
collector = SystemInfoCollector()
info = collector.collect()

# Check for common PII patterns
assert "[HOME]" in str(info.to_dict()) or "/" not in str(info.to_dict())
```

## See Also

- [Benchmarking Architecture](../architecture/benchmarking-system.md) - Technical deep dive
- [Benchmarking Operations](../operations/benchmarking-operations.md) - Operational runbook
- [Benchmarking API Reference](../api/benchmarking-api.md) - API documentation
- [CPU Benchmarks](../performance/cpu-benchmarks.md) - Performance results and guidance
- [Benchmarking Examples](../examples/benchmarking-examples.md) - Detailed usage examples

## Changelog

### 2025-12-24 - v1.0
- Initial production-ready release
- Schema v4 with automatic migrations
- OPT-IN production metrics (SR-11)
- Bounded metric storage (SR-12, TM-07, OPT-05)
- ML-based recommendations
- Adaptive weight learning
- PII sanitization
- Integration tests passing
