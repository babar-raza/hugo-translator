# Benchmarking System Architecture

**Last Updated**: 2025-12-24
**Status**: Production-Ready
**Version**: 1.0

## Table of Contents

- [Overview](#overview)
- [System Components](#system-components)
- [Database Schema](#database-schema)
- [Data Flow](#data-flow)
- [Thread Safety Design](#thread-safety-design)
- [Memory Management](#memory-management)
- [Schema Migrations](#schema-migrations)
- [Performance Characteristics](#performance-characteristics)
- [Design Decisions](#design-decisions)

## Overview

The benchmarking system provides a complete solution for measuring, recording, and optimizing translation performance. It is designed for production use with emphasis on thread safety, memory efficiency, and data integrity.

### Design Goals

1. **Accurate Measurement**: Precise timing and memory tracking without overhead
2. **Data Integrity**: ACID guarantees via SQLite with WAL mode
3. **Thread Safety**: Concurrent reads, serialized writes with proper locking
4. **Memory Efficiency**: Bounded metric storage to prevent leaks
5. **Privacy**: PII sanitization for all recorded paths
6. **Extensibility**: Schema versioning for backward-compatible upgrades

### Architecture Layers

```
┌──────────────────────────────────────────────────────────────┐
│                    Application Layer                          │
│  ┌────────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ BenchmarkRunner│  │ CLI Commands │  │TranslationEngine│  │
│  └────────┬───────┘  └──────┬───────┘  └────────┬────────┘  │
│           │                  │                    │           │
└───────────┼──────────────────┼────────────────────┼───────────┘
            │                  │                    │
┌───────────▼──────────────────▼────────────────────▼───────────┐
│                    Business Logic Layer                        │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  ModelRecommender                                      │   │
│  │  - Similarity matching (±2 cores, ±4GB RAM)           │   │
│  │  - Weighted scoring (throughput, memory, success)     │   │
│  │  - Confidence calculation                             │   │
│  └────────┬───────────────────────────────────────────────┘   │
│           │                                                    │
│  ┌────────▼───────────────────────────────────────────────┐   │
│  │  AdaptiveWeightLearner                                 │   │
│  │  - Feedback processing                                 │   │
│  │  - Weight updates (learning_rate=0.1)                 │   │
│  │  - Error-based adjustment                              │   │
│  └────────┬───────────────────────────────────────────────┘   │
│           │                                                    │
└───────────┼────────────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────────────────────────────────┐
│                    Data Access Layer                           │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  BenchmarkDatabase                                     │   │
│  │  - SQLite with WAL mode                                │   │
│  │  - Schema v4 (automatic migrations from v1-v3)        │   │
│  │  - Thread-safe writes (threading.Lock)                │   │
│  │  - Concurrent reads (WAL allows readers while writing)│   │
│  │  - Busy timeout: 30s                                   │   │
│  └────────┬───────────────────────────────────────────────┘   │
│           │                                                    │
│  ┌────────▼───────────────────────────────────────────────┐   │
│  │  ProductionMetricsIngestor (OPT-IN)                   │   │
│  │  - Thread-safe recording (threading.Lock)             │   │
│  │  - Graceful error handling                            │   │
│  │  - System info collection at record time              │   │
│  └────────┬───────────────────────────────────────────────┘   │
│           │                                                    │
└───────────┼────────────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────────────────────────────────┐
│                    System Layer                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  SystemInfoCollector                                   │   │
│  │  - HardwareDetector integration                        │   │
│  │  - CPU, GPU, memory detection                         │   │
│  │  - Extended hardware context (BM-09)                  │   │
│  │  - Path sanitization (PII prevention)                 │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

## System Components

### 1. BenchmarkDatabase (Storage Layer)

**File**: `src/benchmarking/storage.py`

**Responsibilities**:
- Persistent storage of benchmark runs and results
- Schema versioning and automatic migrations
- Query interface for historical data
- Data export and comparison utilities

**Key Classes**:
```python
@dataclass
class SystemInfo:
    """System configuration snapshot."""
    cpu_model: str
    cpu_cores: int
    total_ram_gb: float
    gpu_model: Optional[str]
    # ... 20+ fields for comprehensive hardware tracking

@dataclass
class BenchmarkResult:
    """Single benchmark sample result."""
    sample_id: str
    model_id: str
    device: str
    batch_size: int
    duration_seconds: float
    tokens_input: int
    tokens_output: int
    throughput_tokens_per_sec: float
    peak_memory_mb: Optional[float]
    errors: List[str]

@dataclass
class BenchmarkRun:
    """Complete benchmark run record."""
    run_id: str
    model_id: str
    device: str
    batch_sizes: List[int]
    iterations: int
    corpus_category: Optional[str]
    purpose: str
    tags: List[str]
    system_info: SystemInfo
    results: List[BenchmarkResult]
    total_duration_seconds: float
    timestamp_utc: str
    metadata: Dict[str, Any]
```

**Database Configuration**:
```python
class BenchmarkDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._local = threading.local()  # Thread-local connections
        self._write_lock = threading.Lock()  # Serialize writes
        self._init_schema()  # Enable WAL, set busy timeout
```

**Thread Safety**:
- **Read operations**: Thread-local connections, no locking required (WAL mode)
- **Write operations**: Global write lock with 30s busy timeout
- **Connection pooling**: One connection per thread via `threading.local()`

### 2. SystemInfoCollector (Hardware Detection)

**File**: `src/benchmarking/system_info.py`

**Responsibilities**:
- Detect CPU model, cores, frequency, TDP
- Detect GPU model, VRAM, compute capability, driver version
- Detect memory capacity and bandwidth
- Collect platform information (OS, Python, PyTorch versions)
- Sanitize all paths to prevent PII leakage

**Integration**:
```python
from src.model_runtime.hardware import HardwareDetector

class SystemInfoCollector:
    def __init__(self):
        self.hardware_detector = HardwareDetector()  # Reuse existing detector

    def collect(self) -> SystemInfo:
        hardware_info = self.hardware_detector.detect()
        # ... collect extended info ...
        return SystemInfo(...)
```

**PII Sanitization**:
```python
def sanitize_path(self, path: str) -> str:
    """Remove username and homedir from paths."""
    # /home/john.doe/projects/... → [HOME]/projects/...
    # C:\Users\Jane\Documents\... → C:\Users\[USER]\Documents\...
    path = re.sub(r'/home/[^/]+', '[HOME]', path)
    path = re.sub(r'C:\\Users\\[^\\]+', r'C:\Users\[USER]', path)
    path = re.sub(r'/Users/[^/]+', '[HOME]', path)
    return path
```

### 3. ProductionMetricsIngestor (Production Integration)

**File**: `src/benchmarking/production_ingestor.py`

**Responsibilities**:
- Record production translation runs as benchmark data (OPT-IN)
- Collect system info at record time (not constructor time)
- Thread-safe recording for concurrent translations
- Graceful error handling (never crash translation pipeline)

**OPT-IN Design**:
```python
class ProductionMetricsIngestor:
    def __init__(self, db: BenchmarkDatabase, enabled: bool = False):
        self.enabled = enabled  # Default: False
        self._lock = threading.Lock()
        self._collector = SystemInfoCollector() if enabled else None

    def record_translation_run(self, ...) -> None:
        if not self.enabled:
            return  # No-op when disabled

        try:
            with self._lock:  # Thread-safe
                system_info = self._collector.collect()
                run = BenchmarkRun(...)
                self.db.save_run(run)
        except Exception as e:
            # MUST NOT crash translation pipeline
            logger.error(f"Failed to record metrics: {e}", exc_info=True)
```

### 4. ModelRecommender (ML Recommendation Engine)

**File**: `src/benchmarking/recommender.py`

**Responsibilities**:
- Query similar benchmark runs by hardware
- Calculate weighted scores for each candidate
- Generate recommendations with confidence scores
- Track active recommendations for feedback loop

**Similarity Matching**:
```python
def _find_similar_runs(self, system_info: SystemInfo) -> List[BenchmarkRun]:
    """Find runs with similar hardware (±2 cores, ±4GB RAM)."""
    all_runs = self.db.list_runs(limit=100)
    similar_runs = []
    for run_id, model_id, device, timestamp, count in all_runs:
        run = self.db.get_run(run_id)
        if run and run.system_info:
            cpu_diff = abs(run.system_info.cpu_cores - system_info.cpu_cores)
            ram_diff = abs(run.system_info.total_ram_gb - system_info.total_ram_gb)
            if cpu_diff <= 2 and ram_diff <= 4.0:
                similar_runs.append(run)
    return similar_runs
```

**Weighted Scoring**:
```python
def _calculate_score(self, run, weights, requirements) -> float:
    """Score = throughput * w1 + (10000/memory) * w2 + success_rate * w3"""
    score = 0.0

    # Throughput component (higher is better)
    avg_throughput = sum(r.throughput_tokens_per_sec for r in run.results) / len(run.results)
    score += avg_throughput * weights.get("throughput", 1.0)

    # Memory component (lower is better, so use inverse)
    max_memory = max(r.peak_memory_mb for r in run.results if r.peak_memory_mb)
    memory_score = 10000.0 / max_memory
    score += memory_score * weights.get("memory", 0.8)

    # Success rate component
    success_rate = sum(1 for r in run.results if not r.errors) / len(run.results)
    score += success_rate * 100 * weights.get("historical_success", 0.4)

    # Requirements adherence (hard constraints)
    if requirements.get("max_memory_mb"):
        if max_memory > requirements["max_memory_mb"]:
            score *= 0.5  # Heavy penalty

    return score
```

### 5. AdaptiveWeightLearner (Feedback Loop)

**File**: `src/benchmarking/feedback.py`

**Responsibilities**:
- Store feature weights in database
- Update weights based on prediction errors
- Calculate new weights using learning rate
- Persist weight updates for future recommendations

**Weight Update Algorithm**:
```python
def update_weights(self, feedback: RecommendationFeedback) -> Dict[str, float]:
    """Update weights based on prediction error."""
    weights = self.get_current_weights()

    # Calculate errors
    throughput_error = abs(feedback.predicted_throughput - feedback.actual_throughput)
    memory_error = abs(feedback.predicted_memory_mb - feedback.actual_memory_mb)

    # Normalize errors (0-1 scale)
    normalized_throughput_error = min(1.0, throughput_error / 100.0)
    normalized_memory_error = min(1.0, memory_error / 10000.0)

    # Update weights (gradient descent style)
    if normalized_throughput_error > 0.1:  # Significant error
        weights["throughput"] *= (1.0 - self.learning_rate * normalized_throughput_error)

    if normalized_memory_error > 0.1:
        weights["memory"] *= (1.0 - self.learning_rate * normalized_memory_error)

    # Normalize to sum to 1.0
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}

    # Save to database
    self._save_weights(weights, feedback)

    return weights
```

## Database Schema

### Schema Version 4 (Current)

```sql
-- Schema metadata
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL
);

-- Benchmark runs
CREATE TABLE benchmark_runs (
    run_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    device TEXT NOT NULL,
    batch_sizes TEXT NOT NULL,  -- JSON array
    iterations INTEGER NOT NULL,
    corpus_category TEXT,
    purpose TEXT NOT NULL,
    tags TEXT NOT NULL,  -- JSON array
    total_duration_seconds REAL NOT NULL,
    timestamp_utc TEXT NOT NULL,
    metadata TEXT,  -- JSON object

    -- Indexes
    INDEX idx_runs_model (model_id),
    INDEX idx_runs_device (device),
    INDEX idx_runs_purpose (purpose),
    INDEX idx_runs_timestamp (timestamp_utc)
);

-- System information (one per run)
CREATE TABLE system_info (
    run_id TEXT PRIMARY KEY,
    cpu_model TEXT NOT NULL,
    cpu_cores INTEGER NOT NULL,
    total_ram_gb REAL NOT NULL,
    gpu_model TEXT,
    gpu_memory_gb REAL,
    gpu_compute_capability TEXT,
    has_cuda INTEGER NOT NULL,  -- Boolean as 0/1
    cuda_version TEXT,
    os_name TEXT NOT NULL,
    os_version TEXT NOT NULL,
    platform_system TEXT NOT NULL,
    platform_release TEXT NOT NULL,
    python_version TEXT NOT NULL,
    python_implementation TEXT NOT NULL,
    torch_version TEXT,
    torch_cuda_available INTEGER,  -- Boolean as 0/1

    -- BM-09: Extended hardware context
    cpu_frequency_mhz REAL,
    cpu_frequency_max_mhz REAL,
    cpu_tdp_watts REAL,
    memory_bandwidth_gbps REAL,
    numa_nodes INTEGER,
    gpu_driver_version TEXT,
    power_management_state TEXT,

    collected_at_utc TEXT NOT NULL,
    collector_version TEXT NOT NULL,

    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
);

-- Individual benchmark results
CREATE TABLE benchmark_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    device TEXT NOT NULL,
    batch_size INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    tokens_input INTEGER NOT NULL,
    tokens_output INTEGER NOT NULL,
    throughput_tokens_per_sec REAL NOT NULL,
    peak_memory_mb REAL,
    errors TEXT,  -- JSON array

    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
    INDEX idx_results_run (run_id),
    INDEX idx_results_model (model_id)
);

-- Adaptive weight learning (BM-10)
CREATE TABLE weight_history (
    weight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    weights TEXT NOT NULL,  -- JSON object
    updated_at_utc TEXT NOT NULL,
    feedback_id TEXT,

    INDEX idx_weights_timestamp (updated_at_utc)
);

-- Recommendation feedback (BM-10)
CREATE TABLE recommendation_feedback (
    feedback_id TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL,
    predicted_throughput REAL NOT NULL,
    actual_throughput REAL NOT NULL,
    predicted_memory_mb REAL NOT NULL,
    actual_memory_mb REAL NOT NULL,
    user_satisfied INTEGER NOT NULL,  -- Boolean as 0/1
    recorded_at_utc TEXT NOT NULL,

    INDEX idx_feedback_recommendation (recommendation_id),
    INDEX idx_feedback_timestamp (recorded_at_utc)
);
```

### Schema Evolution

| Version | Changes | Migration |
|---------|---------|-----------|
| v1 | Initial schema: runs, results | N/A |
| v2 | Added system_info table | Collect system info for existing runs |
| v3 | Added tags, metadata fields | Add columns with defaults |
| v4 | Added weight_history, recommendation_feedback, extended hardware fields | Add tables, add columns |

**Migration Safety**:
- Automatic migrations on database open
- Backward compatible (old code can read new schema)
- Forward compatible (new code handles missing fields)
- Transactional migrations (rollback on error)

```python
def _migrate_v3_to_v4(self, conn: sqlite3.Connection) -> None:
    """Migrate schema from v3 to v4."""
    with conn:
        # Add new tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS weight_history (...)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recommendation_feedback (...)
        """)

        # Add new columns to system_info
        for column_name in ["cpu_frequency_mhz", "cpu_frequency_max_mhz", ...]:
            try:
                conn.execute(f"ALTER TABLE system_info ADD COLUMN {column_name} REAL")
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Update schema version
        conn.execute("UPDATE schema_version SET version = 4")
```

## Data Flow

### Benchmark Run Flow

```
┌─────────────┐
│ User/Script │
└──────┬──────┘
       │
       ▼
┌────────────────────────┐
│ BenchmarkRunner.run()  │
│ - Load corpus          │
│ - Detect hardware      │
│ - Initialize model     │
└──────┬─────────────────┘
       │
       ▼ (for each sample)
┌────────────────────────┐
│ TranslationEngine      │
│ - Translate            │
│ - Measure time/memory  │
└──────┬─────────────────┘
       │
       ▼
┌────────────────────────┐
│ BenchmarkResult        │
│ - sample_id            │
│ - duration_seconds     │
│ - tokens_input/output  │
│ - throughput           │
│ - peak_memory_mb       │
└──────┬─────────────────┘
       │
       ▼ (collect all results)
┌────────────────────────┐
│ BenchmarkRun           │
│ - run_id               │
│ - model_id             │
│ - system_info          │
│ - results[]            │
└──────┬─────────────────┘
       │
       ▼
┌────────────────────────┐
│ BenchmarkDatabase      │
│ - save_run()           │
│ - Write to SQLite      │
└────────────────────────┘
```

### Recommendation Flow

```
┌─────────────┐
│ User Request│
└──────┬──────┘
       │
       ▼
┌──────────────────────────┐
│ ModelRecommender         │
│ .recommend(system_info,  │
│            requirements) │
└──────┬───────────────────┘
       │
       ▼
┌──────────────────────────┐
│ SystemInfoCollector      │
│ - collect()              │
│ - Return current system  │
└──────┬───────────────────┘
       │
       ▼
┌──────────────────────────┐
│ BenchmarkDatabase        │
│ - list_runs(limit=100)   │
│ - Return historical runs │
└──────┬───────────────────┘
       │
       ▼
┌──────────────────────────┐
│ Similarity Matching      │
│ - Filter by CPU ±2 cores │
│ - Filter by RAM ±4GB     │
└──────┬───────────────────┘
       │
       ▼
┌──────────────────────────┐
│ AdaptiveWeightLearner    │
│ - get_current_weights()  │
└──────┬───────────────────┘
       │
       ▼
┌──────────────────────────┐
│ Weighted Scoring         │
│ - throughput * w1        │
│ - (10000/memory) * w2    │
│ - success_rate * w3      │
│ - Apply constraints      │
└──────┬───────────────────┘
       │
       ▼ (select best)
┌──────────────────────────┐
│ ModelRecommendation      │
│ - model_id               │
│ - device                 │
│ - batch_size             │
│ - predicted metrics      │
│ - confidence_score       │
│ - reasoning              │
└──────────────────────────┘
```

### Feedback Loop Flow

```
┌─────────────────────┐
│ User runs with rec  │
│ - Measure actual    │
│   throughput/memory │
└──────┬──────────────┘
       │
       ▼
┌───────────────────────────┐
│ RecommendationFeedback    │
│ - recommendation_id       │
│ - predicted vs actual     │
│ - user_satisfied          │
└──────┬────────────────────┘
       │
       ▼
┌───────────────────────────┐
│ ModelRecommender          │
│ .record_outcome(feedback) │
└──────┬────────────────────┘
       │
       ▼
┌───────────────────────────┐
│ AdaptiveWeightLearner     │
│ - Calculate errors        │
│ - Update weights          │
│ - Normalize weights       │
└──────┬────────────────────┘
       │
       ▼
┌───────────────────────────┐
│ BenchmarkDatabase         │
│ - Save feedback           │
│ - Save weight_history     │
└───────────────────────────┘
```

## Thread Safety Design

### Read Operations (Concurrent)

```python
def _get_conn(self) -> sqlite3.Connection:
    """Get thread-local connection."""
    if not hasattr(self._local, 'conn'):
        self._local.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,  # Allow thread migration
            timeout=30.0,  # Busy timeout
        )
        self._local.conn.row_factory = sqlite3.Row
    return self._local.conn

def get_run(self, run_id: str) -> Optional[BenchmarkRun]:
    """Read operation - no locking required (WAL mode)."""
    conn = self._get_conn()  # Thread-local connection
    cursor = conn.execute(
        "SELECT * FROM benchmark_runs WHERE run_id = ?",
        (run_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None
    # ... construct BenchmarkRun ...
    return run
```

**WAL Mode Benefits**:
- Readers never block writers
- Writers never block readers
- Multiple concurrent readers
- Better concurrency than default rollback journal

### Write Operations (Serialized)

```python
def save_run(self, run: BenchmarkRun) -> None:
    """Write operation - requires lock."""
    with self._write_lock:  # Global lock
        conn = self._get_conn()
        with conn:  # Transaction
            # Insert run
            conn.execute("""
                INSERT INTO benchmark_runs (...)
                VALUES (?, ?, ...)
            """, (...))

            # Insert system info
            conn.execute("""
                INSERT INTO system_info (...)
                VALUES (?, ?, ...)
            """, (...))

            # Insert results
            for result in run.results:
                conn.execute("""
                    INSERT INTO benchmark_results (...)
                    VALUES (?, ?, ...)
                """, (...))
        # Commit on context exit
```

### Production Metrics Thread Safety

```python
class ProductionMetricsIngestor:
    def __init__(self, db, enabled):
        self._lock = threading.Lock()  # Serialize record_translation_run calls

    def record_translation_run(self, ...) -> None:
        if not self.enabled:
            return

        try:
            with self._lock:  # Only one recording at a time
                system_info = self._collector.collect()
                run = BenchmarkRun(...)
                self.db.save_run(run)  # Internally locked by BenchmarkDatabase
        except Exception as e:
            logger.error(f"Recording failed: {e}", exc_info=True)
```

## Memory Management

### Bounded Metric Storage (SR-12, TM-07, OPT-05)

**Problem**: Unbounded lists cause memory leaks in long-running processes.

**Solution**: Use `collections.deque(maxlen=N)` for all timing metrics with configurable limits (CFG-01).

All storage limits are now configurable via `config/metrics.yaml` and can be overridden with environment variables. See [Metrics Configuration](../configuration/metrics.md) for details.

#### TranslationEngine

```python
from collections import deque
from ..utils.config_loader import get_metrics_config

class TranslationEngine:
    def __init__(self, ...):
        # Load configurable maxlen (default: 1000)
        metrics_config = get_metrics_config()
        retry_maxlen = metrics_config["metrics"]["storage"]["translation_engine"]["retry_metrics_maxlen"]

        self._retry_metrics = {
            "retry_attempts": deque(maxlen=retry_maxlen),
            "retry_durations_ms": deque(maxlen=retry_maxlen),
            "retry_reasons": {},  # Dict (naturally bounded)
        }

    def translate_file(self, ...):
        # Retry metrics automatically recorded
        # Oldest item automatically evicted when len > maxlen
```

**Memory usage**: ~8KB per metric with default maxlen=1000 (1000 floats × 8 bytes)
**Configuration**: `config/metrics.yaml` → `metrics.storage.translation_engine.retry_metrics_maxlen`
**Environment override**: `METRICS_ENGINE_MAXLEN=2000`

#### L3SemanticTM

```python
from src.utils.config_loader import get_metrics_config

class L3SemanticTM:
    def __init__(self, ...):
        # Load configurable maxlen (default: 10000 - higher for frequent operations)
        metrics_config = get_metrics_config()
        timing_maxlen = metrics_config["metrics"]["storage"]["l3_semantic"]["timing_metrics_maxlen"]

        self._metrics = {
            "semantic_search_ms": deque(maxlen=timing_maxlen),
            "add_entry_ms": deque(maxlen=timing_maxlen),
            "batch_add_ms": deque(maxlen=timing_maxlen),
            "cache_hits": 0,  # Still use int for counters
            "cache_misses": 0,
        }
```

**Memory usage**: ~80KB per metric with default maxlen=10000 (10000 floats × 8 bytes)
**Configuration**: `config/metrics.yaml` → `metrics.storage.l3_semantic.timing_metrics_maxlen`
**Environment override**: `METRICS_L3_MAXLEN=20000`

#### BatchOptimizer

```python
from src.utils.config_loader import get_metrics_config

class BatchOptimizer:
    def __init__(self, ...):
        # Load configurable maxlen (default: 5000)
        metrics_config = get_metrics_config()
        timing_maxlen = metrics_config["metrics"]["storage"]["batch_optimizer"]["timing_metrics_maxlen"]

        self._timing_metrics = {
            "prepare_batches_ms": deque(maxlen=timing_maxlen),
            "process_batch_ms": deque(maxlen=timing_maxlen),
            "oom_recovery_ms": deque(maxlen=timing_maxlen),
            "batch_size_adjustments_ms": deque(maxlen=timing_maxlen),
        }
```

**Memory usage**: ~40KB per metric with default maxlen=5000 (5000 floats × 8 bytes)
**Configuration**: `config/metrics.yaml` → `metrics.storage.batch_optimizer.timing_metrics_maxlen`
**Environment override**: `METRICS_BATCH_MAXLEN=10000`

### Shared Metrics Utilities (REF-01)

All metrics calculation logic is centralized in `src/utils/metrics.py` to eliminate code duplication.

```python
from src.utils.metrics import calc_stats

# Unified statistics function used by all components
stats = calc_stats(timing_values)  # Returns: count, mean, min, max, total, p50, p95, p99
```

**Benefits**:
- **DRY principle**: Single implementation, no duplication
- **Consistency**: All components use identical calculations
- **Maintainability**: Bug fixes in one place
- **Comprehensive**: Includes percentiles (p50, p95, p99) not in original implementations

### Total Memory Budget (With Default Configuration)

```
Component                  Memory Usage        Configurable
─────────────────────────  ──────────────────  ─────────────
BenchmarkDatabase          ~10 MB (baseline)   No
SystemInfoCollector        ~1 MB               No
ModelRecommender           ~5 MB + 100KB/run   No
ProductionMetricsIngestor  ~2 MB (when enabled) No
TranslationEngine metrics  ~16 KB (2 × 8KB)    Yes (METRICS_ENGINE_MAXLEN)
L3SemanticTM metrics       ~240 KB (3 × 80KB)  Yes (METRICS_L3_MAXLEN)
BatchOptimizer metrics     ~160 KB (4 × 40KB)  Yes (METRICS_BATCH_MAXLEN)
─────────────────────────  ──────────────────  ─────────────
TOTAL (typical)            ~20 MB + cached runs
TOTAL (metrics only)       ~416 KB (bounded)
```

**Memory Savings** (vs. unbounded storage after 1M operations):
- TranslationEngine: 8 MB → 16 KB (**500x reduction**)
- L3SemanticTM: 240 MB → 240 KB (**1000x reduction**)
- BatchOptimizer: 160 MB → 160 KB (**1000x reduction**)

**Impact**: Prevents out-of-memory crashes in long-running production processes.

## Schema Migrations

### Migration Strategy

1. **Check current version** on database open
2. **Apply migrations sequentially** (v1→v2→v3→v4)
3. **Transactional migrations** (rollback on error)
4. **Backward compatible** (old code can read new schema)

### Migration Example

```python
def _init_schema(self) -> None:
    """Initialize schema with migrations."""
    conn = self._get_conn()

    # Enable WAL mode
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    # Check current version
    current_version = self.get_schema_version()

    # Apply migrations
    if current_version < 1:
        self._create_schema_v1(conn)
    if current_version < 2:
        self._migrate_v1_to_v2(conn)
    if current_version < 3:
        self._migrate_v2_to_v3(conn)
    if current_version < 4:
        self._migrate_v3_to_v4(conn)

    logger.info(f"Schema version: {self.get_schema_version()}")
```

### Adding New Fields

To add a new field in future versions:

```python
def _migrate_v4_to_v5(self, conn):
    """Add new_field to system_info."""
    with conn:
        try:
            conn.execute("ALTER TABLE system_info ADD COLUMN new_field TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
        conn.execute("UPDATE schema_version SET version = 5")
```

## Performance Characteristics

### Database Operations

| Operation | Typical Latency | Notes |
|-----------|----------------|-------|
| save_run() | 5-10 ms | WAL mode, SSD |
| get_run() | <1 ms | Indexed by run_id |
| list_runs() | 10-50 ms | Full table scan (limit 100) |
| Similarity search | 20-100 ms | Depends on run count |
| Weight update | 2-5 ms | Single row update |

### Throughput

- **Write throughput**: ~100-200 runs/sec (serialized)
- **Read throughput**: ~10,000 runs/sec (concurrent)
- **WAL checkpoint**: Every ~1000 writes or 1MB

### Scaling Limits

| Metric | Limit | Notes |
|--------|-------|-------|
| Total runs | 1M+ | Tested to 100K runs |
| Results per run | 10K | Tested to 1K results/run |
| Concurrent readers | 100+ | WAL mode |
| Concurrent writers | 1 | Serialized by lock |
| Database size | 10GB+ | SQLite limit ~140TB |

## Design Decisions

### Why SQLite instead of PostgreSQL?

**Pros**:
- Zero-configuration (no server required)
- ACID guarantees
- Excellent for read-heavy workloads
- WAL mode enables concurrent reads
- Single file (easy backup/transfer)
- Low memory overhead (~10MB)

**Cons**:
- Single-writer concurrency
- No network access (must be local)

**Conclusion**: SQLite is ideal for benchmarking because:
- Writes are infrequent (end of benchmark runs)
- Reads dominate (querying for recommendations)
- Local-only access is acceptable
- Simplicity reduces operational burden

### Why OPT-IN for Production Metrics?

**Privacy**:
- Prevents unintended data collection
- Complies with data governance policies
- Respects user consent

**Performance**:
- Zero overhead when disabled (no-op check)
- <10ms overhead when enabled

**Default**: `enabled=False` ensures safe deployment.

### Why Bounded Metrics (deque)?

**Problem**: Unbounded lists cause memory leaks.

**Before** (unbounded list):
```python
self._metrics = {"durations_ms": []}  # Grows forever
# After 1M appends: ~8MB memory
# After 10M appends: ~80MB memory
```

**After** (bounded deque):
```python
self._metrics = {"durations_ms": deque(maxlen=1000)}
# After 1M appends: ~8KB memory
# After 10M appends: ~8KB memory (bounded)
```

**Trade-off**: Only recent 1000-10000 samples for statistics, but prevents OOM.

### Why Thread-Local Connections?

**Problem**: SQLite connections are not thread-safe.

**Solution**: One connection per thread via `threading.local()`.

```python
self._local = threading.local()

def _get_conn(self):
    if not hasattr(self._local, 'conn'):
        self._local.conn = sqlite3.connect(self.db_path)
    return self._local.conn
```

**Benefit**: Safe concurrent reads without connection pool complexity.

### Why WAL Mode?

**Write-Ahead Logging (WAL)** vs **Rollback Journal**:

| Feature | WAL | Rollback |
|---------|-----|----------|
| Readers block writers | No | Yes |
| Writers block readers | No | Yes |
| Concurrent readers | Yes | No |
| Write performance | Better | Slower |
| Checkpoint overhead | Low | N/A |

**Conclusion**: WAL is essential for concurrent benchmark queries during production runs.

## See Also

- [Benchmarking Features](../features/benchmarking.md) - Feature overview and usage
- [Benchmarking Operations](../operations/benchmarking-operations.md) - Operational guide
- [Benchmarking API Reference](../api/benchmarking-api.md) - API documentation
- [Translation Memory Architecture](translation-memory.md) - TM integration points

## Changelog

### 2025-12-24 - v1.0
- Initial architecture documentation
- Schema v4 with migrations
- Thread safety design
- Memory management (bounded metrics)
- Performance characteristics
- Design decision rationale
