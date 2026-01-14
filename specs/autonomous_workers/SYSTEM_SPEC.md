# Autonomous Workers System - Technical Specification
**Version:** 2.0.0
**Status:** DRAFT - Implementation Pending
**Last Updated:** 2026-01-14
**Supersedes:** Distributed worker design (implicit, not previously spec'd)

---

## Document Purpose

This specification defines the unified architecture for autonomous workers in the Hugo Translation System. It supersedes the previous ad-hoc worker implementations with a formal shared-engine architecture.

**Scope:**
- 8 SharedEngines interfaces and implementations
- Dual-run execution modes (Windows CUDA, Docker CPU/GPU)
- Translation backend abstraction (MT ↔ LLM switching)
- Benchmark DB integration with resource stats
- Worker lifecycle and configuration precedence

**Out of Scope:**
- Individual worker business logic (covered in existing specs)
- CLI command specifications (see [cli-001-main-translate.md](../features/cli-001-main-translate.md))
- Translation Memory layers (see [tm-001](../features/tm-001-l1-cache.md), [tm-002](../features/tm-002-l2-persistent-store.md), [tm-003](../features/tm-003-l3-semantic-search.md))

---

## System Overview

### Architecture Principles

1. **Shared Engines:** All processes (CLI, workers, orchestrator) use the same 8 unified engines
2. **Dependency Injection:** CompositionRoot creates and wires engine instances from configuration
3. **Backward Compatibility:** Existing CLI behavior preserved (INV-001 through INV-009 maintained)
4. **Mode Isolation:** Execution mode determines device policy (CPU-only enforcement in docker_cpu mode)
5. **Pluggable Backends:** Translation backend (MT/LLM) selectable per site or per job
6. **Observable:** All operations emit structured telemetry events

### Component Diagram (High-Level)

```
┌─────────────────────────────────────────────────────────────────┐
│                      Hugo Translation System                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐   ┌────────────────┐   ┌───────────────────┐  │
│  │ Manual CLI  │   │  Orchestrator  │   │ Workers (CPU/GPU) │  │
│  └──────┬──────┘   └────────┬───────┘   └─────────┬─────────┘  │
│         │                    │                      │            │
│         └────────────────────┼──────────────────────┘            │
│                              │                                   │
│                   ┌──────────▼──────────┐                        │
│                   │  CompositionRoot    │                        │
│                   │ (Engine Factory)    │                        │
│                   └──────────┬──────────┘                        │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐              │
│         │            SharedEngines (8)            │              │
│         │                                         │              │
│  ┌──────▼──────┐  ┌──────────┐  ┌──────────────┐ │             │
│  │Translation  │  │Telemetry │  │ JobEngine    │ │             │
│  │  Engine     │  │ Engine   │  │              │ │             │
│  └─────────────┘  └──────────┘  └──────────────┘ │             │
│                                                    │             │
│  ┌──────────────┐  ┌──────────┐  ┌─────────────┐ │             │
│  │Profile       │  │ Logging  │  │CommitEngine │ │             │
│  │ Engine       │  │ Engine   │  │             │ │             │
│  └──────────────┘  └──────────┘  └─────────────┘ │             │
│                                                    │             │
│  ┌──────────────┐  ┌───────────────────────────┐ │             │
│  │Limiting      │  │ HealingEngine             │ │             │
│  │ Engine       │  │                           │ │             │
│  └──────────────┘  └───────────────────────────┘ │             │
│                                                    │             │
│  └────────────────────────────────────────────────┘             │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 1. Shared Engines Specification

### 1.1 TranslationEngine

**Purpose:** Core translation orchestration with pluggable backends

**Interface:**
```python
class ITranslationBackend(ABC):
    """Abstract translation backend."""

    @abstractmethod
    def translate(self, text: str, src_lang: str, tgt_lang: str, **kwargs) -> str:
        """Translate text using this backend."""
        pass

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Backend model identifier."""
        pass

class TranslationEngine:
    """Enhanced translation engine with backend abstraction."""

    def __init__(self,
                 backend: ITranslationBackend,
                 config_service: ConfigService,
                 telemetry: TelemetryEngine,
                 logging: LoggingEngine,
                 tm: TranslationMemory,
                 **kwargs):
        self.backend = backend
        self.config_service = config_service
        self.telemetry = telemetry
        self.logging = logging
        self.tm = tm

    def translate_file(self,
                       source_file: str,
                       target_langs: List[str],
                       backend_override: Optional[str] = None,
                       **kwargs) -> TranslationResult:
        """Translate file using configured or overridden backend."""
        pass
```

**Backend Implementations:**

1. **MTBackend** (Machine Translation)
   - Models: M2M100, NLLB
   - Device: CPU or CUDA
   - Batching: Adaptive (4-16 segments)
   - TM Integration: Full (L1+L2+L3)

2. **LLMBackend** (Large Language Model)
   - Models: Claude Sonnet/Opus, GPT-4
   - API: REST (Anthropic, OpenAI)
   - Batching: Single-item (API constraint)
   - TM Integration: Full (same as MT)

**Backend Selection Precedence:**
```
1. Job-level override (TranslationJob.backend_override)
2. Site profile config (site_profiles/{site}.yaml: translation_backend)
3. Global config (config/global.yaml: translation_backend)
4. Default: "mt"
```

**Configuration:**
```yaml
# config/global.yaml
translation_backend: "mt"  # Default for all sites

backends:
  mt:
    default_model: "nllb_200_1.3B"
    device: "auto"
    batch_size: 4

  llm:
    default_model: "claude-sonnet-4"
    api_key_env: "ANTHROPIC_API_KEY"
    max_tokens: 4096
    temperature: 0.3
    cache_responses: true
```

**Invariants:**
- INV-001 (subprocess isolation) maintained
- INV-002 (atomic writes) maintained
- INV-003 (TM lookup order) applies to both backends
- Backend type logged to telemetry and benchmark DB

---

### 1.2 TelemetryEngine

**Purpose:** Unified telemetry for internal logging + benchmark data

**Interface:**
```python
class TelemetryEngine:
    """Unified telemetry engine."""

    def __init__(self,
                 internal_db_path: str,          # Local-Telemetry DB
                 benchmark_db_path: Optional[str] = None):  # Benchmark DB
        self.internal_tel = TelemetryIntegration(internal_db_path)
        self.benchmark_db = BenchmarkDatabase(benchmark_db_path) if benchmark_db_path else None

    def emit(self, event_type: str, data: dict):
        """Emit structured event to internal telemetry."""
        pass

    def log_model_run(self, run_data: ModelRunData):
        """Log model run to benchmark DB with resource stats."""
        pass

    def get_stats(self, window: str = "24h") -> dict:
        """Query aggregated telemetry stats."""
        pass
```

**Event Types (New):**
- `orchestrator_started`
- `orchestrator_stopped`
- `job_enqueued` (source: orchestrator, file_watcher, sweep_scheduler)
- `job_dispatched` (worker picked up job)
- `file_watch_triggered`
- `sweep_started`
- `sweep_completed`
- `backup_started`
- `backup_completed`
- `backup_failed`

**Benchmark DB Schema:**
```sql
CREATE TABLE model_runs (
    run_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,

    -- Model
    model_id TEXT NOT NULL,
    backend TEXT NOT NULL,  -- 'MTBackend', 'LLMBackend'
    device TEXT NOT NULL,   -- 'cpu', 'cuda:0'

    -- Job context
    site_id TEXT,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    file_path TEXT,

    -- Performance
    duration_seconds REAL NOT NULL,
    segments_processed INTEGER NOT NULL,
    tokens_processed INTEGER,
    batch_size INTEGER,

    -- Resources
    vram_used_mb REAL,
    vram_available_mb REAL,
    ram_used_mb REAL,
    cpu_percent REAL,

    -- Quality
    tm_hit_rate REAL,
    validation_pass_rate REAL,

    -- Metadata
    worker_id TEXT,
    execution_mode TEXT,
    metadata TEXT
);
```

**Fallback Behavior:**
- If benchmark DB unavailable: Log to internal telemetry as `model_run_fallback` event
- Do NOT crash translation if telemetry fails

---

### 1.3 JobEngine

**Purpose:** Unified job queue abstraction

**Interface:**
```python
class JobEngine:
    """Unified job queue."""

    def __init__(self, backend: JobQueueBackend):
        self.backend = backend  # JobQueue or RedisJobQueue

    def enqueue(self, job: TranslationJob) -> str:
        """Add job to queue, return job_id."""
        pass

    def dequeue(self) -> Optional[TranslationJob]:
        """Get next job from queue (priority-ordered)."""
        pass

    def get_status(self, job_id: str) -> JobStatus:
        """Query job status."""
        pass

    def update_status(self, job_id: str, status: str, **kwargs):
        """Update job status."""
        pass

    def list_pending(self, limit: int = 100) -> List[TranslationJob]:
        """List pending jobs."""
        pass
```

**Queue Backends:**
1. **Memory (JobQueue):** In-process FIFO queue with priority
2. **Redis (RedisJobQueue):** Distributed queue via sorted set

**Job Priority Levels:**
- 3: FileWatcher (reactive, immediate translation)
- 5: Manual CLI (user-initiated)
- 7: SweepScheduler (batch, low priority)

---

### 1.4 ProfileEngine

**Purpose:** Site profile resolution with precedence

**Interface:**
```python
class ProfileEngine:
    """Site profile resolution."""

    def __init__(self, config_root: str):
        self.config_service = ConfigService(config_root)

    def get_profile(self, site_id: str) -> SiteProfile:
        """Load site profile."""
        pass

    def list_sites(self) -> List[str]:
        """List all configured sites."""
        pass

    def resolve_config(self, site_id: str, key: str, default=None):
        """Resolve config value with precedence: site > global > default."""
        pass
```

**Configuration Precedence:**
```
1. CLI arguments (highest)
2. Environment variables
3. Site profile (config/site_profiles/{site_id}.yaml)
4. Global config (config/global.yaml)
5. Code defaults (lowest)
```

---

### 1.5 LoggingEngine

**Purpose:** Structured logging (NDJSON)

**Interface:**
```python
class LoggingEngine:
    """Structured logging."""

    def __init__(self, log_file: str, log_level: str = "INFO"):
        self.logger = StructuredLogger(log_file, log_level)

    def info(self, message: str, **context):
        """Log info-level message."""
        pass

    def error(self, message: str, exc_info=None, **context):
        """Log error-level message."""
        pass

    def with_context(self, **context) -> LoggingEngine:
        """Return logger with bound context."""
        pass
```

**Log Format (NDJSON):**
```json
{
  "timestamp": "2026-01-14T12:00:00Z",
  "level": "INFO",
  "component": "worker",
  "message": "Job processing started",
  "context": {
    "job_id": "job-123",
    "worker_id": "worker-cpu-1",
    "correlation_id": "cor-456"
  }
}
```

---

### 1.6 CommitEngine

**Purpose:** Git commit automation

**Interface:**
```python
class CommitEngine:
    """Git commit automation."""

    def __init__(self, enabled: bool, auto_push: bool, co_author: str):
        self.enabled = enabled
        self.auto_push = auto_push
        self.co_author = co_author

    def commit_if_enabled(self, site_id: str, lang: str, files: List[str]):
        """Commit files if enabled."""
        pass
```

**Configuration:**
```yaml
# config/global.yaml
git_commit:
  enabled: true
  auto_push: true
  commit_template: "chore: translate {file_count} files to {languages}"
  co_author_name: "Hugo Translator"
  co_author_email: "noreply@aspose.com"
```

---

### 1.7 LimitingEngine

**Purpose:** Resource limits (CPU/RAM/VRAM)

**Interface:**
```python
class LimitingEngine:
    """Resource limits."""

    def __init__(self,
                 max_gpu_memory_mb: int = 4096,
                 max_cpu_percent: float = 80.0,
                 max_ram_percent: float = 85.0):
        self.gpu_limiter = GPUMemoryLimiter(max_gpu_memory_mb)
        self.cpu_limiter = CPULimiter(max_cpu_percent)
        self.ram_limiter = RAMLimiter(max_ram_percent)

    def check_resources_available(self) -> bool:
        """Check if resources available."""
        pass

    def wait_for_resources(self, timeout: float = 300.0):
        """Block until resources available."""
        pass
```

---

### 1.8 HealingEngine

**Purpose:** Retry and recovery logic

**Interface:**
```python
class HealingEngine:
    """Retry and recovery."""

    def __init__(self, max_retries: int = 3, backoff_factor: float = 1.5):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def with_retry(self, fn: Callable, *args, **kwargs):
        """Execute function with retry logic."""
        pass

    def _reduce_batch_size(self):
        """Adaptive batch reduction on OOM."""
        pass
```

**Retry Strategy:**
- OOM errors: Reduce batch size by 50%, retry up to 3 times
- Transient errors: Exponential backoff (1.5^attempt seconds)
- Permanent errors: Fail immediately (no retry)

---

## 2. CompositionRoot

**Purpose:** Central factory for creating SharedEngines from configuration

**Interface:**
```python
@dataclass
class SharedEngines:
    """Container for all engine instances."""
    translation: TranslationEngine
    telemetry: TelemetryEngine
    job: JobEngine
    profile: ProfileEngine
    logging: LoggingEngine
    commit: CommitEngine
    limiting: LimitingEngine
    healing: HealingEngine

class CompositionRoot:
    """Engine factory."""

    @staticmethod
    def create_from_config(config_path: str, mode: str = "auto") -> SharedEngines:
        """Create engines from configuration."""
        pass
```

**Instantiation Order (Dependency-Aware):**
1. ProfileEngine (needed by others)
2. LoggingEngine
3. TelemetryEngine
4. JobEngine
5. LimitingEngine
6. HealingEngine
7. CommitEngine
8. TranslationEngine (last, depends on many others)

---

## 3. Execution Modes

### 3.1 Execution Mode Enum

```python
class ExecutionMode(Enum):
    WINDOWS_CUDA = "windows_cuda"   # Native Windows with CUDA GPU
    DOCKER_CPU = "docker_cpu"        # Docker container CPU-only
    DOCKER_GPU = "docker_gpu"        # Docker container with GPU passthrough
```

### 3.2 Device Policy

**Policy Enforcement:**

| Mode | Requested Device | Actual Device | CUDA_VISIBLE_DEVICES | Notes |
|------|------------------|---------------|----------------------|-------|
| `WINDOWS_CUDA` | `auto` | `cuda:0` or `cpu` | Not set | Auto-detect GPU |
| `WINDOWS_CUDA` | `cpu` | `cpu` | Not set | User choice |
| `WINDOWS_CUDA` | `cuda:0` | `cuda:0` | Not set | User choice |
| `DOCKER_CPU` | Any | `cpu` (forced) | `` (empty) | CPU-only enforced |
| `DOCKER_GPU` | `cuda:0` | `cuda:0` | `0` | GPU passthrough required |

**Enforcement Implementation:**
```python
class DevicePolicy:
    @staticmethod
    def enforce(mode: ExecutionMode, requested_device: str) -> str:
        if mode == ExecutionMode.DOCKER_CPU:
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            if torch.cuda.is_available():
                raise RuntimeError("GPU detected in docker_cpu mode")
            return "cpu"

        elif mode == ExecutionMode.DOCKER_GPU:
            if requested_device.startswith("cuda") and not torch.cuda.is_available():
                raise RuntimeError("GPU not available")
            return requested_device

        elif mode == ExecutionMode.WINDOWS_CUDA:
            if requested_device == "auto":
                return "cuda:0" if torch.cuda.is_available() else "cpu"
            return requested_device
```

### 3.3 Worker Configuration

**WorkerConfig Dataclass:**
```python
@dataclass
class WorkerConfig:
    worker_id: str
    mode: ExecutionMode
    config_path: str
    device: str
    redis_host: Optional[str] = None
    redis_port: int = 6379
    redis_db: int = 0
    poll_interval: int = 5
    max_retries: int = 3
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        return cls(
            worker_id=os.getenv("WORKER_ID", f"worker-{socket.gethostname()}"),
            mode=ExecutionMode(os.getenv("EXECUTION_MODE", "docker_cpu")),
            config_path=os.getenv("CONFIG_PATH", "./config"),
            device=os.getenv("DEVICE", "auto"),
            redis_host=os.getenv("REDIS_HOST"),
            redis_port=int(os.getenv("REDIS_PORT", "6379")),
            redis_db=int(os.getenv("REDIS_DB", "0")),
            poll_interval=int(os.getenv("POLL_INTERVAL", "5")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            log_level=os.getenv("LOG_LEVEL", "INFO")
        )
```

### 3.4 WorkerRunner

**Unified Worker Execution:**
```python
class WorkerRunner:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.engines = CompositionRoot.create_from_config(
            config_path=config.config_path,
            mode="worker"
        )
        self._running = True

    def run(self):
        logger = self.engines.logging
        logger.info(f"Worker {self.config.worker_id} starting in {self.config.mode} mode")

        # Enforce device policy
        if self.config.mode == ExecutionMode.DOCKER_CPU:
            DevicePolicy.enforce(self.config.mode, self.config.device)

        # Main polling loop
        while self._running:
            try:
                job = self.engines.job.dequeue()
                if job:
                    self._process_job(job)
                else:
                    time.sleep(self.config.poll_interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)

    def _process_job(self, job: TranslationJob):
        result = self.engines.translation.translate_files(
            input_paths=job.input_paths,
            site_id=job.site_id,
            target_langs=job.target_langs
        )

        if result.success:
            self.engines.commit.commit_if_enabled(
                site_id=job.site_id,
                lang=result.target_lang,
                files=result.output_files
            )
```

---

## 4. Configuration Schema

### 4.1 Global Config Enhancements

**New Section: Execution Modes**
```yaml
# config/global.yaml

# NEW SECTION
execution:
  default_mode: "docker_cpu"
  enforce_mode_policy: true

  modes:
    docker_cpu:
      device: "cpu"
      max_gpu_memory_mb: 0
      allow_gpu_fallback: false

    docker_gpu:
      device: "cuda:0"
      max_gpu_memory_mb: 4096
      allow_gpu_fallback: true

    windows_cuda:
      device: "auto"
      max_gpu_memory_mb: 4096
      allow_gpu_fallback: true

# NEW SECTION
translation_backend: "mt"  # Default backend

backends:
  mt:
    default_model: "nllb_200_1.3B"
    device: "auto"
    batch_size: 4

  llm:
    default_model: "claude-sonnet-4"
    api_key_env: "ANTHROPIC_API_KEY"
    max_tokens: 4096
    temperature: 0.3
    cache_responses: true

# EXISTING (no changes)
tm_defaults:
  use_semantic_tm: true
  semantic_threshold: 0.80
  # ... rest unchanged
```

### 4.2 Site Profile Enhancements

**Backend Selection Per Site:**
```yaml
# config/site_profiles/premium_docs.yaml

site_id: "premium_docs"
site_name: "Premium Documentation"

# Override global backend for this site
translation_backend: "llm"

# LLM-specific config
llm_config:
  model_id: "claude-opus-4"
  temperature: 0.2

# Existing config unchanged
source_lang: "en"
target_langs: ["es", "fr", "de"]
content_roots:
  - "./content/premium-docs"
```

---

## 5. Worker Migration Strategy

### 5.1 Backward-Compatible Adapter Pattern

**Old Code (Before Migration):**
```python
# src/workers/job_processor.py (old)
class JobProcessor:
    def __init__(self, queue, config_service):
        self.queue = queue
        self.config_service = config_service
        self.engine = TranslationEngine(config_service, ...)
```

**New Code (After Migration, Backward Compatible):**
```python
# src/workers/job_processor.py (new)
class JobProcessor:
    def __init__(self,
                 queue=None,
                 config_service=None,
                 engines: Optional[SharedEngines] = None):
        if engines:
            # NEW PATH: Use shared engines
            self.queue = engines.job
            self.config_service = engines.profile
            self.engine = engines.translation
            self.logger = engines.logging
        else:
            # OLD PATH: Direct instantiation (deprecated)
            warnings.warn(
                "Instantiating JobProcessor without SharedEngines is deprecated",
                DeprecationWarning
            )
            self.queue = queue
            self.config_service = config_service
            self.engine = TranslationEngine(config_service, ...)
            self.logger = logging.getLogger(__name__)
```

**Migration Phases:**
1. Add optional `engines` parameter
2. Route through engines if provided, else use old path
3. Update entrypoints to pass engines
4. Deprecate old path (warnings)
5. Remove old path in next major version

---

## 6. Testing Requirements

### 6.1 Contract Tests (Must Pass)

**Existing:**
- CONTRACT-001: Subprocess isolation
- CONTRACT-002: Atomic writes
- CONTRACT-003: TM lookup order
- CONTRACT-004: Critical validators
- CONTRACT-005: Validation mode CLI override
- CONTRACT-006: File locking
- CONTRACT-007: Resume skip completed
- CONTRACT-008: L2 corruption detection
- CONTRACT-009: L3 periodic saves

**New:**
- CONTRACT-010: CLI flag precedence
- CONTRACT-011: Output file structure
- CONTRACT-012: Exit codes
- CONTRACT-013: Device policy enforcement
- CONTRACT-014: Backend selection precedence

### 6.2 Golden Tests

**Commands:**
1. `translate-hugo translate ./test_fixtures/docs --target-langs es,fr --strict`
2. `translate-hugo translate ./test_fixtures/docs --target-langs de --no-validation --dry-run`
3. `translate-hugo translate ./test_fixtures/docs --target-langs pt --resume`
4. `translate-hugo verify ./test_fixtures/docs --target-langs es --fix`

**Assertion:** Output (stdout, stderr, files, exit code) identical before and after refactoring

### 6.3 Performance Tests

**Acceptance Criteria:**
- Single-file translation: ±10% of baseline
- Directory translation: ±20% of baseline
- Memory usage: <2x baseline
- GPU memory: Respects max_gpu_memory_mb

### 6.4 Phase 0 Baseline Metrics (Captured 2026-01-14)

**Test Inventory:**
- Total Test Files: 235
- Total Test Functions: 3,650
- Total Test Classes: 601

**Test Suite Breakdown:**
- Unit Tests: 187 files, 3,171 functions (86.9% of total)
- Integration Tests: 46 files, 464 functions (12.7% of total)
- Contract Tests: 1 file, 11 functions (0.3% of total)
- Golden Tests: 1 file, 4 functions (0.1% of total)

**Contract Coverage Status:**
- COVERED: 6/26 clauses (23%)
  - OUTPUT-001, OUTPUT-002, OUTPUT-003, OUTPUT-005
  - BEHAVIOR-009 (INV-004: Critical validators)
  - BEHAVIOR-011 (Dry-run no writes)
- PARTIAL: 6/26 clauses (23%)
  - INPUT-001 (Flag names - golden tests only)
  - INPUT-005 (Config precedence - implicit)
  - INPUT-007 (Special commands - diagnose-lock only)
  - BEHAVIOR-004 (File locking - partial)
  - BEHAVIOR-005 (Resume - flag acceptance only)
  - BEHAVIOR-010 (Validation override - partial)
- GAP: 14/26 clauses (54%)
  - All INPUT-002/003/004/006 (flag validation, precedence, exclusion, env vars)
  - OUTPUT-004 (file write locations)
  - All BEHAVIOR-001/002/003/006/007/008 (subprocess, fail-fast, atomic writes, TM, L2/L3)
  - All PERFORMANCE-001/002/003 (throughput, memory, GPU limits)

**Core Invariants Coverage:**
- INV-001 (Subprocess isolation): GAP
- INV-002 (Atomic writes): GAP
- INV-003 (TM lookup order): GAP
- INV-004 (Critical validators): COVERED (test_validation_critical.py, 11 tests)
- INV-005 (Validation CLI override): PARTIAL
- INV-006 (File locking): PARTIAL
- INV-007 (Resume skip): PARTIAL
- INV-008 (L2 corruption): GAP
- INV-009 (L3 periodic saves): GAP

**Module Coverage Estimates (test file counts):**
- translation_engine: HIGH (27 test files)
- validation: HIGH (12 test files)
- observability: HIGH (11 test files)
- cli: MEDIUM (10 test files)
- model_runtime: MEDIUM (6 test files)
- terminology: MEDIUM (6 test files)
- verification: MEDIUM (4 test files)
- utils: LOW (3 test files)

**Baseline Files:**
- `reports/baseline/phase0_test_results.csv` (3,650 test entries)
- `reports/baseline/phase0_coverage_report.txt` (coverage breakdown)
- `reports/baseline/phase0_test_summary.md` (comprehensive summary)

**Known Limitations:**
- Tests analyzed but NOT executed (pytest not installed)
- Pass/fail status unknown (all marked NOT_RUN)
- Coverage percentages estimated from test counts (actual line coverage unavailable)
- Recommended: Install pytest and pytest-cov for Phase 1 to capture actual metrics

**Phase 1 Recommendations:**
1. Install pytest/pytest-cov and execute full test suite
2. Create contract tests for INV-001, INV-002, INV-003, INV-006, INV-007, INV-008, INV-009
3. Add integration tests for flag validation (INPUT-002/003/004)
4. Create performance baseline tests (PERFORMANCE-001/002/003)
5. Expand golden test suite to 6+ commands

---

## 7. Deployment Templates

### 7.1 Windows Service (NSSM)

**Install Script:**
```powershell
# scripts/install_windows_service.ps1
nssm install HugoTranslator-orchestrator python "-m src.orchestrator"
nssm set HugoTranslator-orchestrator AppEnvironmentExtra "EXECUTION_MODE=windows_cuda"
nssm start HugoTranslator-orchestrator
```

### 7.2 Docker Compose

**Enhanced docker-compose.yml:**
```yaml
services:
  worker-cpu:
    environment:
      - EXECUTION_MODE=docker_cpu  # NEW
      - DEVICE=cpu
      - CUDA_VISIBLE_DEVICES=      # Empty = no GPU
```

---

## 8. Observability

### 8.1 Telemetry Events

**New Events:**
- `orchestrator_started`, `orchestrator_stopped`
- `job_enqueued`, `job_dispatched`
- `file_watch_triggered`
- `sweep_started`, `sweep_completed`
- `backup_started`, `backup_completed`, `backup_failed`

### 8.2 Metrics

**Benchmark DB Queries:**
- Model performance by backend (MT vs LLM)
- Resource utilization (VRAM, RAM, CPU)
- Throughput (segments/second by model)
- TM hit rates by site

---

## 9. Backward Compatibility Guarantees

### 9.1 CLI Behavior

**Unchanged:**
- All CLI flags work identically
- Output file structure unchanged
- Exit codes unchanged (0, 1, 130)
- Log format unchanged (NDJSON)
- Progress tracking format unchanged

**Verified By:**
- Golden tests (4 commands)
- Contract tests (9 existing + 5 new)

### 9.2 Configuration

**Unchanged:**
- Existing global.yaml configs work without modification
- Existing site profiles work without modification
- ENV vars work identically

**New (Optional):**
- `execution.modes` section (defaults provided)
- `translation_backend` config (defaults to "mt")
- `backends` section (defaults provided)

### 9.3 Core Invariants

All existing invariants (INV-001 through INV-009) maintained:
- Subprocess isolation for multi-language
- Atomic file writes
- TM lookup order (L1 → L2 → L3)
- Critical validators always reject
- Validation mode CLI override
- File locking prevents concurrent translation
- Resume skips completed files
- L2 corruption detection
- L3 periodic saves

---

## 10. Migration Checklist

**Phase 0: Baseline Safety**
- [ ] Document CLI surface
- [ ] Create golden test suite
- [ ] Define compatibility contract
- [ ] Capture baseline metrics

**Phase 1: Core Shared Engines**
- [ ] Implement 8 engines
- [ ] Create CompositionRoot
- [ ] Refactor CLI to use engines
- [ ] Golden tests pass

**Phase 2: Dual-Run Execution**
- [ ] Implement execution modes
- [ ] Create WorkerRunner
- [ ] CPU-only enforcement verified
- [ ] Deployment templates tested

**Phase 3: Backend Switching**
- [ ] Implement backend abstraction
- [ ] Create BackendRegistry
- [ ] Configure backends in site profiles
- [ ] Test with both backends

**Phase 4: Benchmark DB**
- [ ] Create schema
- [ ] Implement stats collectors
- [ ] Integrate with TranslationEngine
- [ ] Verify data logged

**Phase 5: Migrate Workers**
- [ ] Migrate Worker-CPU/GPU
- [ ] Migrate Orchestrator
- [ ] Migrate FileWatcher
- [ ] Migrate SweepScheduler
- [ ] Fix GitHub Actions paths
- [ ] Enhance scheduled backup

**Phase 6: Repo Organization**
- [ ] Generate file manifest
- [ ] Create organization plan
- [ ] Execute reorganization
- [ ] Update documentation

**Final Acceptance**
- [ ] All golden tests pass
- [ ] All contract tests pass
- [ ] Full test suite passes (70% unit, 50% integration)
- [ ] Performance within ±20%
- [ ] Dual-run modes verified
- [ ] Backend switching verified
- [ ] Benchmark DB verified

---

## 11. References

**Related Specifications:**
- [CLI-001: Main Translation Command](../features/cli-001-main-translate.md)
- [TM-001: L1 Cache](../features/tm-001-l1-cache.md)
- [TM-002: L2 Persistent Store](../features/tm-002-l2-persistent-store.md)
- [TM-003: L3 Semantic Search](../features/tm-003-l3-semantic-search.md)
- [VAL-001: Validation Decision Engine](../features/val-001-decision-engine.md)
- [Core Invariants](../core_invariants.md)

**Implementation Plans:**
- [Master Plan](../../plans/autonomous_workers/MASTER_PLAN.md)
- [Task Cards](../../plans/autonomous_workers/TASKCARDS.md)
- [Architecture Diagram](../../reports/autonomous_workers/ARCH_DIAGRAM.md)
- [Risk Register](../../plans/autonomous_workers/RISK_REGISTER.md)

**Evidence:**
- [Worker Inventory](../../reports/autonomous_workers/INVENTORY.md)
- [Worker Deep-Dive Notes](../../reports/autonomous_workers/WORKER_NOTES/)
- [Evidence Log](../../reports/autonomous_workers/EVIDENCE_DEEPDIVE.log)

---

**END OF SYSTEM SPECIFICATION**
