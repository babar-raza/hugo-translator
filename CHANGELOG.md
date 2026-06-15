# Changelog

All notable changes to the Hugo Translation System are documented in this file.

## [Unreleased]

### Added

- **Agentic Architecture Modules** — 9 modules providing autonomous runtime capabilities:
  - `supervisor_loop` — inspect-decide-execute cycle for autonomous workers
  - `task_queue` — persistent priority queue with retry and dead-letter support
  - `continuation_state` — cross-session run state tracking
  - `run_signal_emitter` — emits structured run-signal JSON after translation runs
  - `blocker_classifier` — LLM-backed classification of translation blockers
  - `contradiction_detector` — detects contradictions in translated content
  - `run_summarizer` — generates natural-language summaries of translation runs
  - `evidence_declaration` — structured evidence schema for review/audit consumption
  - `model_selector` — adaptive model selection based on run history
  - All modules disabled by default (`enabled: false`); config stubs in `global.yaml`
  - 197 unit tests across all modules
- **Daemon mode agentic hooks** — continuation state and signal emission wired into `_run_daemon()` (mirrors oneshot pattern)
- **Governance CI gate** — `check_governance.py --strict` added to both GitLab CI and GitHub Actions
- **Incident response runbook** — 5 failure scenarios with detection/response/prevention (`docs/operations/incident-response.md`)
- **SBOM** — 844-package software bill of materials (`requirements/sbom.json`)

### Changed

- **Security scan now blocking** — bandit SAST fails pipeline on HIGH severity findings (0 HIGH baseline verified)
- **Coverage gate enforced** — `pytest --cov-fail-under=15` in CI (previously config-only, unenforced)
- **GitHub Actions parity** — governance-check job, agentic module tests, and coverage gate added to `release_gate.yml`

### Fixed

- **Worker hook config access** — hooks now call `config_service.get_config()` instead of non-existent `load_global_config()`

---

> **Deployment note**: The features below are fully implemented. However, CHH-02 through CHH-05
> (Redis locking, Docker metadata volume, Prometheus metrics, automatic cleanup) are only
> active in the **Docker / distributed deployment** path. The default **Windows-native deployment**
> (Task Scheduler + autonomous workers) does not use Redis or Docker — those features are
> silently no-op'd in that configuration, which is safe and correct. CHH-01 and the benchmarking
> system work in both deployment paths.

### Changed (BREAKING)

- **Content hash tracking now enabled by default** (GAP-01, CHH-01)
  - More accurate change detection eliminates false positives from `git checkout`, `touch`, etc.
  - First run after upgrade will hash all files (one-time ~1% performance cost)
  - Creates `.translation_metadata.json` in output directory
  - Opt-out: Use `--disable-content-hash` CLI flag or set `enable_content_hash_tracking: false`

### Added

- **Content Hash Production Hardening** (CHH-02 through CHH-05): Production-grade enhancements to content hash tracking
  - **CHH-02 Multi-Worker Concurrency** (GAP-02, HIGH): Redis distributed locking for safe metadata updates across workers
    - Prevents race conditions in multi-worker Docker deployments (4-8 workers typical)
    - Automatic fallback to direct write if Redis unavailable (with warning)
    - Configurable lock timeout (default: 30s, production: 60s for high contention)
    - Metrics: `metadata_lock_acquire_duration_seconds`, `metadata_lock_timeouts`
  - **CHH-03 Dedicated Metadata Volume** (GAP-03, MEDIUM): Persistent metadata storage in dedicated Docker volume
    - Volume `metadata_storage` mounted at `/data/metadata` (separate from content mounts)
    - Metadata persists across container recreation and updates
    - Survives `docker-compose down` and system restarts
    - Configuration: `metadata_dir: "/data/metadata"` in `config/global.yaml`
  - **CHH-04 Prometheus Metrics** (GAP-04, MEDIUM): Comprehensive observability for content hash operations
    - Histograms: `content_hash_compute_duration_seconds`, `metadata_save_duration_seconds`, `metadata_lock_acquire_duration_seconds`
    - Counters: `content_hash_cache_hits`, `content_hash_cache_misses`, `content_hash_changes_detected`, `content_hash_no_change`
    - Gauges: `metadata_file_size_bytes`, `metadata_tracked_files`
    - Grafana dashboard: `docker/grafana/dashboards/content-hash-tracking.json` (9 panels)
    - Alert rules: Lock timeouts, slow hashing, high contention, large metadata files
  - **CHH-05 Automatic Cleanup** (GAP-05, LOW): Age-based metadata removal to prevent unbounded growth
    - Removes entries not seen in X days (default: 30 days, configurable)
    - Cleanup triggers: On load (default) and/or on save (optional)
    - Safe handling of invalid timestamps (preserved rather than deleted)
    - Configuration: `auto_cleanup` section in `config/global.yaml`
    - Test coverage: 12 unit tests, all passing
  - Documentation:
    - Architecture: [docs/architecture/content-hash-production.md](docs/architecture/content-hash-production.md)
    - Operations: [docs/operations/content-hash-operations.md](docs/operations/content-hash-operations.md)
    - Metrics: [docs/observability/content-hash-metrics.md](docs/observability/content-hash-metrics.md)
    - Implementation: [CHH-05_IMPLEMENTATION_SUMMARY.md](CHH-05_IMPLEMENTATION_SUMMARY.md)

- **Benchmarking System v1.0**: Comprehensive performance measurement and ML-based model recommendations
  - **BenchmarkDatabase** (SR-11): SQLite storage with schema v4 and automatic migrations (v1→v2→v3→v4)
  - **SystemInfoCollector** (BM-09): Hardware detection with PII sanitization and extended context
  - **ProductionMetricsIngestor** (SR-11): OPT-IN production metrics recording (enabled=False default)
  - **ModelRecommender**: ML-based recommendations with system similarity matching (±2 cores, ±4GB RAM)
  - **AdaptiveWeightLearner**: Feedback loop for continuous improvement (learning_rate=0.1)
  - **Timing Instrumentation** (BM-08): Performance metrics in TranslationEngine, L3SemanticTM, BatchOptimizer

- **Metrics Configuration System** (CFG-01): YAML-based configuration for metrics storage limits and thresholds
  - Configuration file: `config/metrics.yaml` with comprehensive defaults
  - Environment variable overrides: `METRICS_ENGINE_MAXLEN`, `METRICS_L3_MAXLEN`, `METRICS_BATCH_MAXLEN`, `METRICS_PERCENTILES`
  - Runtime tuning without code changes for production optimization
  - Configurable percentiles (p50/p95/p99), minimum sample requirements, performance thresholds
  - Thread-safe configuration loading with caching via `ConfigService.get_metrics_config()`
  - Standalone helper function `get_metrics_config()` for global access
  - Documentation: [docs/configuration/metrics.md](docs/configuration/metrics.md)

- **Agent Metrics API Integration** (Plan v6): Profile-driven per-run metrics posting to Google Sheet
  - 17-field Pydantic-validated payload (timestamp, agent identity, scope, item counts, LLM tokens)
  - ScopeResolver with 4-level priority cascade and configurable mappings
  - Scope audit hard gate (`python -m src.observability.metrics_scope --audit`)
  - ContextVar-based LLM accounting (attempted/completed/failed calls, token usage)
  - Evidence system: sidecar JSON (schema_version=2), JSONL ledger, posted markers
  - Non-blocking worker hooks in content translation and TM improvement workers
  - Safety: enabled=false, dry_run=true defaults; test row cap (3/sprint); env-only secrets
  - 143 new tests (115 unit + 28 integration), all passing
  - Documentation: [docs/observability/agent-metrics-api.md](docs/observability/agent-metrics-api.md)

- **Comprehensive Negative Test Coverage** (SR-14): 45 test cases covering edge cases, error handling, and concurrency
  - Storage layer negative tests (17 cases): Malformed data, SQL injection prevention, corrupted database recovery
  - Recommender negative tests (18 cases): No historical data, conflicting requirements, NaN/infinity handling
  - Concurrency integration tests (10 cases): 100 concurrent writes, mixed operations stress testing, thread safety validation
  - Files: `tests/unit/benchmarking/test_storage_negative.py`, `test_recommender_negative.py`, `tests/integration/test_benchmarking_concurrency.py`

### Fixed

- **OBS-01**: Fixed `_last_batch_time` initialization in `ProgressTracker.__init__` to prevent potential `AttributeError`. Removed fragile `hasattr()` check in `batch_completed()`. ([progress.py:281](src/observability/progress.py#L281))

- **SR-12**: Fixed memory leak in TranslationEngine retry metrics by replacing unbounded lists with `deque(maxlen=N)` where N is configurable via `config/metrics.yaml` (default: 1000). Memory savings: 8 MB → 16 KB after 1M operations (500x reduction). ([engine.py:339-349](src/translation_engine/engine.py#L339-L349))

- **TM-07**: Fixed memory leak in L3SemanticTM timing metrics by replacing unbounded lists with `deque(maxlen=N)` where N is configurable via `config/metrics.yaml` (default: 10000). Memory savings: 240 MB → 240 KB after 1M operations (1000x reduction). ([l3_semantic.py:98-109](src/tm/l3_semantic.py#L98-L109))

- **OPT-05**: Fixed memory leak in BatchOptimizer timing metrics by replacing unbounded lists with `deque(maxlen=N)` where N is configurable via `config/metrics.yaml` (default: 5000). Memory savings: 160 MB → 160 KB after 1M operations (1000x reduction). ([batch_optimizer.py:96-106](src/orchestration/batch_optimizer.py#L96-L106))

- **SR-13**: Fixed integration test imports after ProductionMetricsIngestor implementation

### Refactored

- **REF-01**: Extracted shared `calc_stats()` utility to eliminate code duplication across metrics collection
  - Created `src/utils/metrics.py` with comprehensive statistics calculation (count, mean, min, max, total, p50, p95, p99)
  - Replaced duplicate implementations in `TranslationEngine`, `L3SemanticTM`, and `BatchOptimizer`
  - Enhanced percentile calculation with minimum sample requirements (p95: 20 samples, p99: 100 samples)
  - Single source of truth for all metrics calculations across the system
  - Full documentation including edge case handling and performance characteristics

### Performance

- **OBS-03**: Replaced O(n) `list.pop(0)` operations with O(1) `collections.deque` for time window calculations:
  - `_segment_times`: `deque(maxlen=100)` for segment timing
  - `_batch_times`: `deque(maxlen=50)` for batch timing
  - `EMACalculator._samples`: `deque(maxlen=window_size)` for EMA calculations
  ([progress.py:318-320](src/observability/progress.py#L318-L320))

- **Unicode logging**: Replaced Unicode arrow character (`U+2192`) with ASCII `->` in log messages to avoid `UnicodeEncodeError` on Windows cp1252 consoles:
  - [engine.py:1118](src/translation_engine/engine.py#L1118) - Force retranslate language pair
  - [engine.py:1420](src/translation_engine/engine.py#L1420) - File-based localization
  - [batch_optimizer.py:295](src/orchestration/batch_optimizer.py#L295) - OOM batch size reduction
  - [batch_optimizer.py:392](src/orchestration/batch_optimizer.py#L392) - Batch size adjustment

### Documentation

- **Metrics Configuration Documentation**: Comprehensive guide for production tuning
  - Created [docs/configuration/metrics.md](docs/configuration/metrics.md) with configuration reference, tuning guidelines, troubleshooting
  - Updated [docs/architecture/benchmarking-system.md](docs/architecture/benchmarking-system.md) with bounded storage, memory savings analysis, shared utilities section
  - Updated [docs/operations/benchmarking-operations.md](docs/operations/benchmarking-operations.md) with metrics configuration tuning section
  - Updated [docs/api/benchmarking-api.md](docs/api/benchmarking-api.md) with Configuration API documentation (`get_metrics_config()`, `calc_stats()`)
  - Updated [README.md](README.md) with metrics configuration quick start and cross-references
  - Updated key configuration files section to include `config/metrics.yaml`

- Added Implementation Notes section to [docs/reference/observability-cli.md](docs/reference/observability-cli.md) covering:
  - Time window performance (deque usage)
  - Thread safety guarantees
  - EMA throughput calculation
  - Windows console compatibility

## [1.0.0] - 2024-12-22

### Added

- Production-grade progress tracking with real-time CLI metrics
- ETA calculation using Exponential Moving Average (EMA)
- Metrics file output (JSON snapshot + NDJSON stream)
- Two-terminal setup support (logs + metrics)
- `metrics_tail.py` utility for Windows-compatible metrics streaming
- CLI flags: `--metrics-file`, `--metrics-interval`, `--metrics-only`, `--no-progress`

### Features

- Rolling throughput calculation with configurable EMA alpha
- Cache hit rate tracking (L1/L2/L3 breakdown)
- Token counting (input/output)
- Error tracking by type
- Milestone callbacks for progress events
