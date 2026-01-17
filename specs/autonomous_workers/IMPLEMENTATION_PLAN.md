# Autonomous Workers Implementation Plan
**Version:** 1.0.0
**Status:** READY FOR IMPLEMENTATION
**Date:** 2026-01-16
**Lead Engineer:** Claude Sonnet 4.5

---

## Executive Summary

This document provides an evidence-based implementation plan for two NEW autonomous workers in the hugo-translator system:

1. **Worker #1: Autonomous Content Translation** - Scheduled content translation with git commits
2. **Worker #2: TM/Cache Improvement** - LLM-based translation quality improvement

Both workers will:
- Execute 4-5 times daily between 10:00-22:00 America/Los_Angeles
- Use CUDA when available with <=60% VRAM enforcement
- Leverage existing shared engines for telemetry, commits, and resource management
- Log to local-telemetry via API endpoints

---

## Table of Contents

1. [Evidence-Based Analysis](#1-evidence-based-analysis)
2. [Reusable Primitives Inventory](#2-reusable-primitives-inventory)
3. [Missing Components & Gaps](#3-missing-components--gaps)
4. [Implementation Task Cards](#4-implementation-task-cards)
5. [Documentation & Specs Plan](#5-documentation--specs-plan)
6. [Acceptance Tests](#6-acceptance-tests)

---

## 1. Evidence-Based Analysis

### 1.1 Existing Infrastructure (CONFIRMED)

**Shared Engines (8 Total) - ALL IMPLEMENTED:**

| Engine | Status | Location | Purpose |
|--------|--------|----------|---------|
| ProfileEngine | ✅ EXISTS | [src/shared_engines/profile_engine.py](../../src/shared_engines/profile_engine.py) | Site config resolution |
| LoggingEngine | ✅ EXISTS | [src/shared_engines/logging_engine.py](../../src/shared_engines/logging_engine.py) | Structured NDJSON logging |
| TelemetryEngine | ✅ EXISTS | [src/shared_engines/telemetry_engine.py](../../src/shared_engines/telemetry_engine.py) | Event tracking wrapper |
| JobEngine | ✅ EXISTS | [src/shared_engines/job_engine.py](../../src/shared_engines/job_engine.py) | Queue abstraction (memory/Redis) |
| CommitEngine | ✅ EXISTS | [src/shared_engines/commit_engine.py](../../src/shared_engines/commit_engine.py) | Git automation wrapper |
| LimitingEngine | ✅ EXISTS | [src/shared_engines/limiting_engine.py](../../src/shared_engines/limiting_engine.py) | Resource constraint enforcement |
| HealingEngine | ✅ EXISTS | [src/shared_engines/healing_engine.py](../../src/shared_engines/healing_engine.py) | Retry and recovery logic |
| TranslationBackend | ✅ EXISTS | [src/shared_engines/translation_backends.py](../../src/shared_engines/translation_backends.py) | MT/LLM backend abstraction |

**CompositionRoot Factory:**
- Location: [src/shared_engines/composition_root.py](../../src/shared_engines/composition_root.py)
- Creates all 8 engines from config with dependency injection
- Supports execution mode overrides (windows_cuda, docker_cpu, docker_gpu)

**Core Translation Primitives:**
- `TranslationEngine.translate_file()` - Single file translation ([src/translation_engine/engine.py](../../src/translation_engine/engine.py))
- `TranslationEngine.translate_directory()` - Batch directory translation ([src/translation_engine/engine.py](../../src/translation_engine/engine.py))
- Translation Memory (L1+L2+L3) - Full TM stack ([src/tm/](../../src/tm/))

**Hardware Management:**
- GPUManager - Detection, memory limits, device selection ([src/hardware/gpu_manager.py](../../src/hardware/gpu_manager.py))
- `enforce_memory_limit()` - Sets torch per-process memory fraction
- `get_gpu_memory()` - Real-time VRAM monitoring

**Telemetry Integration:**
- TranslationTelemetry - Local-telemetry integration ([src/observability/telemetry_integration.py](../../src/observability/telemetry_integration.py))
- Tracks: translation sessions, tokens, TM hits, validation results
- API endpoint: POST to local-telemetry SQLite DB

**Git Commit Automation:**
- GitCommitter - Enhanced commit messages ([src/observability/git_commit.py](../../src/observability/git_commit.py))
- GitCommitHelper - Reusable auto-commit function ([src/observability/git_commit_helper.py](../../src/observability/git_commit_helper.py))
- Signal blocking during critical git operations

### 1.2 Existing Autonomous Workers (10 Total)

**Reference:** [reports/autonomous_workers/INVENTORY.md](../../reports/autonomous_workers/INVENTORY.md)

| Worker | Purpose | Entrypoint | Status |
|--------|---------|------------|--------|
| Orchestrator | Job queue coordination | [src/orchestrator/__main__.py](../../src/orchestrator/__main__.py) | ✅ PRODUCTION |
| Worker-CPU | CPU-based translation execution | [src/workers/](../../src/workers/) | ✅ PRODUCTION |
| Worker-GPU | GPU-based translation execution | [src/workers/](../../src/workers/) | ✅ PRODUCTION |
| SweepScheduler | Periodic content scanning | [src/orchestrator/scheduler.py](../../src/orchestrator/scheduler.py) | ✅ PRODUCTION |
| FileWatcher | Real-time file change detection | [src/orchestrator/file_watcher.py](../../src/orchestrator/file_watcher.py) | ✅ PRODUCTION |
| BenchmarkScheduler | Model performance benchmarking | [src/benchmarking/scheduler.py](../../src/benchmarking/scheduler.py) | ✅ PRODUCTION |
| Telemetry Health Check | Daily telemetry validation | [.github/workflows/telemetry_health_check.yml](../../.github/workflows/telemetry_health_check.yml) | ✅ PRODUCTION |
| Dashboard | Benchmark visualization | [src/benchmarking/dashboard/](../../src/benchmarking/dashboard/) | ✅ PRODUCTION |
| Scheduled Backup | TM backup automation | (Planned) | 🔴 NOT IMPLEMENTED |

---

## 2. Reusable Primitives Inventory

### 2.1 Translation Execution

**Primary Primitive: TranslationEngine**

```python
# Location: src/translation_engine/engine.py
class TranslationEngine:
    def translate_file(
        self,
        source_file: Path,
        target_langs: List[str],
        src_lang: str = "en",
        **kwargs
    ) -> TranslationResult:
        """Translate single markdown file."""

    def translate_directory(
        self,
        source_dir: Path,
        target_langs: List[str],
        src_lang: str = "en",
        **kwargs
    ) -> DirectoryResult:
        """Translate all markdown files in directory."""
```

**Key Features:**
- YAML frontmatter preservation
- Hugo shortcode protection
- Translation Memory integration (L1+L2+L3)
- Validation suite (10 validators)
- Adaptive batching with OOM recovery
- Content hash tracking for change detection

**Evidence:** [src/translation_engine/engine.py:1-150](../../src/translation_engine/engine.py)

### 2.2 Telemetry & Observability

**Primary Primitive: TelemetryEngine**

```python
# Location: src/shared_engines/telemetry_engine.py
class TelemetryEngine:
    def track_translation_session(
        self,
        job_type: str,
        trigger_type: str = "cli",
        file_path: Optional[Path] = None,
        target_langs: Optional[List[str]] = None,
        **additional_context
    ):
        """Context manager for translation session tracking."""
```

**Underlying Client:**
- TranslationTelemetry ([src/observability/telemetry_integration.py](../../src/observability/telemetry_integration.py))
- Local-telemetry DB integration (SQLite)
- Event types: translation_started, translation_completed, translation_failed, tm_lookup, validation_*

**Evidence:** [src/shared_engines/telemetry_engine.py:1-172](../../src/shared_engines/telemetry_engine.py)

### 2.3 Git Commit Automation

**Primary Primitive: CommitEngine**

```python
# Location: src/shared_engines/commit_engine.py
class CommitEngine:
    def commit_if_enabled(
        self,
        output_files: List[Path],
        site_id: str,
        target_langs: List[str],
        run_id: str,
        translation_result: Optional[Any] = None,
        model_id: Optional[str] = None,
        tm_stats: Optional[Dict] = None,
    ) -> GitCommitResult:
        """Commit translation outputs if enabled."""
```

**Key Features:**
- Stages only specified output files
- Enhanced commit messages with TM stats
- Co-author attribution (Claude)
- Auto-push to remote (configurable)
- Signal blocking during git operations

**Evidence:** [src/shared_engines/commit_engine.py:1-243](../../src/shared_engines/commit_engine.py)

### 2.4 Resource Limiting & VRAM Management

**Primary Primitive: LimitingEngine**

```python
# Location: src/shared_engines/limiting_engine.py
class LimitingEngine:
    def enforce_gpu_memory_limit(self, device: str) -> bool:
        """Enforce GPU memory limit via torch.cuda.set_per_process_memory_fraction()."""

    def check_resources_available(
        self,
        required_memory_mb: Optional[float] = None,
        required_gpu_memory_mb: Optional[float] = None,
        device_required: str = "auto"
    ) -> bool:
        """Check if sufficient resources available."""

    def wait_for_resources(
        self,
        required_memory_mb: Optional[float] = None,
        required_gpu_memory_mb: Optional[float] = None,
        device_required: str = "auto",
        timeout: Optional[float] = None
    ) -> bool:
        """Wait for resources with timeout."""
```

**Underlying Components:**
- GPUManager ([src/hardware/gpu_manager.py](../../src/hardware/gpu_manager.py))
- ResourceMonitor ([src/benchmarking/resource_monitor.py](../../src/benchmarking/resource_monitor.py))
- Real-time VRAM monitoring
- Torch memory fraction enforcement

**Evidence:** [src/shared_engines/limiting_engine.py:1-387](../../src/shared_engines/limiting_engine.py)

### 2.5 Scheduling Infrastructure

**Existing Scheduler: SweepScheduler**

```python
# Location: src/orchestrator/scheduler.py
class SweepScheduler:
    def __init__(
        self,
        config_service: ConfigService,
        job_enqueue_callback: Callable[[TranslationJob], str],
        sweep_interval_minutes: int = 60,
    ):
        """Periodic content sweeping scheduler."""
```

**Key Features:**
- Background thread execution
- Configurable sweep intervals
- Site-specific last-sweep tracking
- Graceful start/stop

**Evidence:** [src/orchestrator/scheduler.py:1-100](../../src/orchestrator/scheduler.py)

---

## 3. Missing Components & Gaps

### 3.1 VRAM Budget Enforcement (NEW)

**Gap:** No centralized 60% VRAM enforcement

**Current State:**
- `max_gpu_memory_mb` config exists ([config/global.yaml:67](../../config/global.yaml))
- LimitingEngine supports `enforce_gpu_memory_limit()`
- BUT: No automatic calculation of 60% threshold

**Required Implementation:**

```python
# Location: src/hardware/vram_enforcer.py (NEW FILE)
class VRAMEnforcer:
    """Centralized VRAM budget enforcement at 60% threshold."""

    def __init__(self, budget_percent: float = 0.60):
        self.budget_percent = budget_percent
        self.gpu_manager = GPUManager()

    def enforce_budget(self, device: str) -> bool:
        """
        Enforce VRAM budget by setting torch memory fraction.

        Args:
            device: CUDA device (e.g., "cuda:0")

        Returns:
            True if budget enforced successfully
        """
        # Get total VRAM
        gpu_info = self.gpu_manager.get_gpu_memory(device_id=0)
        if not gpu_info:
            return False

        # Calculate 60% limit
        total_vram_mb = gpu_info.total_mb
        budget_mb = total_vram_mb * self.budget_percent

        # Set memory fraction
        fraction = self.budget_percent
        torch.cuda.set_per_process_memory_fraction(fraction, device_id)

        logger.info(
            f"Enforced VRAM budget: {budget_mb:.0f}MB / {total_vram_mb:.0f}MB "
            f"({self.budget_percent*100:.0f}%)"
        )
        return True
```

**Acceptance:** Unit test verifies 60% fraction set correctly

### 3.2 Scheduling Utilities for Pacific Time Windows (NEW)

**Gap:** No helper for "4-5x/day, 10:00-22:00 PT" scheduling

**Required Implementation:**

```python
# Location: src/scheduling/window_scheduler.py (NEW FILE)
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

class WindowScheduler:
    """Schedule executions within time windows."""

    def __init__(
        self,
        executions_per_day: tuple[int, int] = (4, 5),
        window_start: time = time(10, 0),
        window_end: time = time(22, 0),
        timezone: str = "America/Los_Angeles"
    ):
        self.executions_per_day = executions_per_day
        self.window_start = window_start
        self.window_end = window_end
        self.timezone = ZoneInfo(timezone)

    def should_execute_now(self) -> bool:
        """Check if current time is within execution window."""
        now = datetime.now(tz=self.timezone)
        current_time = now.time()

        # Check if within window
        if not (self.window_start <= current_time <= self.window_end):
            return False

        # Calculate if this is an execution slot
        # (Implementation: Track last N executions, ensure 4-5 per day)
        return self._calculate_execution_slot(now)

    def next_execution_time(self) -> datetime:
        """Calculate next execution time."""
        # Implementation: Random jitter within window, respecting frequency
        pass
```

**Acceptance:** Unit test verifies 4-5 executions scheduled within 10:00-22:00 PT

### 3.3 Autonomous Worker Skeletons (NEW)

**Gap:** No dedicated workers for content translation and TM improvement

**Required Workers:**

1. **ContentTranslationWorker** - Scheduled content translation
2. **TMImprovementWorker** - LLM-based TM enhancement

See [Section 4](#4-implementation-task-cards) for detailed task cards.

### 3.4 LLM Backend for Ollama (PARTIAL)

**Current State:**
- LLMBackend exists ([src/shared_engines/translation_backends.py](../../src/shared_engines/translation_backends.py))
- Supports API-based LLMs (Claude, GPT-4)

**Gap:**
- No Ollama integration (local LLM support)

**Required Enhancement:**

```python
# Location: src/shared_engines/translation_backends.py (MODIFY)
class OllamaBackend(ITranslationBackend):
    """Ollama local LLM backend."""

    def __init__(
        self,
        model_id: str = "llama2",
        base_url: str = "http://localhost:11434"
    ):
        self.model_id = model_id
        self.base_url = base_url
        self.client = ollama.Client(host=base_url)

    def translate(self, text: str, src_lang: str, tgt_lang: str, **kwargs) -> str:
        """Translate using Ollama."""
        prompt = f"Translate from {src_lang} to {tgt_lang}: {text}"
        response = self.client.generate(model=self.model_id, prompt=prompt)
        return response['response']
```

**Acceptance:** Integration test verifies Ollama translation with fallback to API LLM

---

## 4. Implementation Task Cards

### Phase 1: Foundation Components (3-5 days)

#### TASK-001: VRAM Budget Enforcer
**Effort:** 4 hours
**Dependencies:** None
**Priority:** HIGH

**Objective:** Implement centralized 60% VRAM enforcement

**Files to CREATE:**
- `src/hardware/vram_enforcer.py`
- `tests/unit/hardware/test_vram_enforcer.py`

**Implementation:**
```python
class VRAMEnforcer:
    def __init__(self, budget_percent: float = 0.60):
        """Initialize with 60% default budget."""

    def enforce_budget(self, device: str) -> bool:
        """Set torch memory fraction to 60% of total VRAM."""

    def get_current_usage(self) -> Dict[str, float]:
        """Get current VRAM usage vs budget."""

    def check_budget_exceeded(self) -> bool:
        """Check if current usage exceeds 60% budget."""
```

**Acceptance Criteria:**
- ✅ VRAMEnforcer class implements 60% enforcement
- ✅ Unit test verifies memory fraction set correctly
- ✅ Integration test with GPUManager confirms VRAM limited
- ✅ Works with both single and multi-GPU systems

**Evidence Collection:**
```bash
# Verify 60% limit enforced
python -c "
from src.hardware.vram_enforcer import VRAMEnforcer
enforcer = VRAMEnforcer(budget_percent=0.60)
assert enforcer.enforce_budget('cuda:0')
print('✅ VRAM budget enforced at 60%')
"
```

---

#### TASK-002: Window Scheduler
**Effort:** 6 hours
**Dependencies:** None
**Priority:** HIGH

**Objective:** Implement Pacific Time window scheduling (10:00-22:00, 4-5x/day)

**Files to CREATE:**
- `src/scheduling/__init__.py`
- `src/scheduling/window_scheduler.py`
- `tests/unit/scheduling/test_window_scheduler.py`

**Implementation:**
```python
class WindowScheduler:
    def __init__(
        self,
        executions_per_day: tuple[int, int] = (4, 5),
        window_start: time = time(10, 0),
        window_end: time = time(22, 0),
        timezone: str = "America/Los_Angeles",
        jitter_minutes: int = 15
    ):
        """Initialize scheduler with Pacific Time window."""

    def should_execute_now(self) -> bool:
        """Check if within execution window and slot."""

    def next_execution_time(self) -> datetime:
        """Calculate next execution with random jitter."""

    def get_execution_history(self) -> List[datetime]:
        """Get today's execution timestamps."""

    def record_execution(self) -> None:
        """Record current execution timestamp."""
```

**Acceptance Criteria:**
- ✅ WindowScheduler respects 10:00-22:00 PT window
- ✅ Schedules 4-5 executions per day (random)
- ✅ Adds jitter (±15 minutes) to avoid clock-based patterns
- ✅ Unit test with mocked timezone
- ✅ Integration test runs across midnight boundary

**Evidence Collection:**
```bash
# Simulate 24 hours of scheduling
pytest tests/unit/scheduling/test_window_scheduler.py -v
```

---

#### TASK-003: Ollama Backend
**Effort:** 8 hours
**Dependencies:** None
**Priority:** MEDIUM

**Objective:** Add Ollama local LLM support to TranslationBackend

**Files to MODIFY:**
- `src/shared_engines/translation_backends.py` (add OllamaBackend)
- `tests/unit/shared_engines/test_translation_backends.py`

**Files to CREATE:**
- `tests/integration/test_ollama_backend.py`

**Implementation:**
```python
class OllamaBackend(ITranslationBackend):
    def __init__(
        self,
        model_id: str = "llama2:7b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.3,
        fallback_backend: Optional[ITranslationBackend] = None
    ):
        """Initialize Ollama backend with fallback."""

    def translate(self, text: str, src_lang: str, tgt_lang: str, **kwargs) -> str:
        """Translate using Ollama with automatic fallback on error."""

    def is_available(self) -> bool:
        """Check if Ollama server is reachable."""
```

**Acceptance Criteria:**
- ✅ OllamaBackend implements ITranslationBackend
- ✅ Supports configurable models (llama2, mistral, codellama)
- ✅ Automatic fallback to API LLM on connection error
- ✅ Unit test with mocked Ollama client
- ✅ Integration test with real Ollama server (optional)
- ✅ Configuration via `config/global.yaml`

**Configuration Example:**
```yaml
# config/global.yaml
translation_backends:
  ollama:
    enabled: true
    base_url: "http://localhost:11434"
    model_id: "llama2:7b"
    temperature: 0.3
    fallback_to_api_llm: true
```

**Evidence Collection:**
```bash
# Test Ollama backend
pytest tests/integration/test_ollama_backend.py -v -k "test_translate_with_ollama"
```

---

### Phase 2: Worker #1 - Content Translation (5-7 days)

#### TASK-004: ContentTranslationWorker Skeleton
**Effort:** 6 hours
**Dependencies:** TASK-001, TASK-002
**Priority:** HIGH

**Objective:** Create autonomous content translation worker

**Files to CREATE:**
- `src/workers/content_translation_worker.py`
- `tests/unit/workers/test_content_translation_worker.py`
- `scripts/run_content_translation_worker.py`

**Implementation:**
```python
# src/workers/content_translation_worker.py
import logging
from pathlib import Path
from typing import List, Dict, Any

from src.shared_engines.composition_root import CompositionRoot
from src.hardware.vram_enforcer import VRAMEnforcer
from src.scheduling.window_scheduler import WindowScheduler

logger = logging.getLogger(__name__)


class ContentTranslationWorker:
    """
    Autonomous content translation worker.

    Scheduled Execution:
    - Runs 4-5 times per day
    - Active window: 10:00-22:00 America/Los_Angeles
    - Uses CUDA with <=60% VRAM
    - Commits only touched files
    - Logs to local-telemetry
    """

    def __init__(
        self,
        config_root: str = "config",
        execution_mode: str = "windows_cuda"
    ):
        """Initialize worker with shared engines."""
        # Create engines from config
        self.engines = CompositionRoot.create_from_config({
            "config_root": config_root,
            "execution_mode": execution_mode,
            "telemetry_enabled": True,
            "commit_enabled": True
        })

        # VRAM enforcement
        self.vram_enforcer = VRAMEnforcer(budget_percent=0.60)

        # Scheduling
        self.scheduler = WindowScheduler(
            executions_per_day=(4, 5),
            window_start=time(10, 0),
            window_end=time(22, 0),
            timezone="America/Los_Angeles"
        )

        logger.info("ContentTranslationWorker initialized")

    def run_translation_cycle(
        self,
        content_roots: List[Path],
        target_langs: List[str],
        site_id: str
    ) -> Dict[str, Any]:
        """
        Execute single translation cycle.

        Args:
            content_roots: List of content directories to scan
            target_langs: Target language codes
            site_id: Site identifier for config

        Returns:
            Execution report with stats
        """
        # 1. Check if within execution window
        if not self.scheduler.should_execute_now():
            logger.debug("Outside execution window, skipping")
            return {"status": "skipped", "reason": "outside_window"}

        # 2. Enforce VRAM budget
        device = self.engines.limiting.auto_select_device()
        if device.startswith("cuda"):
            self.vram_enforcer.enforce_budget(device)

        # 3. Check resource availability
        if not self.engines.limiting.check_resources_available(
            required_memory_mb=2048,
            required_gpu_memory_mb=4096,
            device_required=device
        ):
            logger.warning("Insufficient resources, skipping cycle")
            return {"status": "skipped", "reason": "insufficient_resources"}

        # 4. Execute translation
        run_id = f"content_worker_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        with self.engines.telemetry.track_translation_session(
            job_type="autonomous_content_translation",
            trigger_type="scheduled",
            site_id=site_id
        ) as ctx:
            try:
                # Translate directories
                from src.translation_engine.engine import TranslationEngine
                engine = TranslationEngine(
                    model_loader=...,  # Use engines.translation backend
                    tm=...,
                    config_service=self.engines.profile.config_service
                )

                all_output_files = []
                for content_root in content_roots:
                    result = engine.translate_directory(
                        source_dir=content_root,
                        target_langs=target_langs,
                        src_lang="en"
                    )

                    all_output_files.extend(result.output_files)

                    ctx.set_metrics(
                        files_translated=result.files_translated,
                        segments_translated=result.segments_translated,
                        tm_hits=result.tm_stats.get("hits", 0)
                    )

                # 5. Commit touched files only
                commit_result = self.engines.commit.commit_if_enabled(
                    output_files=all_output_files,
                    site_id=site_id,
                    target_langs=target_langs,
                    run_id=run_id,
                    model_id="m2m100_418m"  # or from config
                )

                # 6. Record execution
                self.scheduler.record_execution()

                return {
                    "status": "success",
                    "files_translated": len(all_output_files),
                    "commit_hash": commit_result.commit_hash_short,
                    "run_id": run_id
                }

            except Exception as e:
                logger.error(f"Translation cycle failed: {e}", exc_info=True)
                ctx.set_metrics(error=str(e))
                return {
                    "status": "failed",
                    "error": str(e),
                    "run_id": run_id
                }

    def run_forever(
        self,
        content_roots: List[Path],
        target_langs: List[str],
        site_id: str,
        poll_interval_seconds: int = 300
    ):
        """
        Run worker in continuous loop.

        Args:
            content_roots: Content directories to monitor
            target_langs: Target languages
            site_id: Site identifier
            poll_interval_seconds: Time between checks (default: 5 minutes)
        """
        logger.info(
            f"Starting ContentTranslationWorker: "
            f"poll_interval={poll_interval_seconds}s, "
            f"window=10:00-22:00 PT, "
            f"frequency=4-5x/day"
        )

        while True:
            try:
                report = self.run_translation_cycle(
                    content_roots=content_roots,
                    target_langs=target_langs,
                    site_id=site_id
                )

                logger.info(f"Cycle complete: {report}")

            except KeyboardInterrupt:
                logger.info("Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)

            # Sleep until next check
            time.sleep(poll_interval_seconds)
```

**Entrypoint Script:**
```python
# scripts/run_content_translation_worker.py
import sys
from pathlib import Path
from src.workers.content_translation_worker import ContentTranslationWorker

def main():
    worker = ContentTranslationWorker(
        config_root="config",
        execution_mode="windows_cuda"
    )

    # Example: Translate Aspose products site
    worker.run_forever(
        content_roots=[
            Path("../products.aspose.net/content"),
            Path("../docs.aspose.net/content")
        ],
        target_langs=["de", "fr", "es", "ja"],
        site_id="products.aspose.net",
        poll_interval_seconds=300
    )

if __name__ == "__main__":
    main()
```

**Acceptance Criteria:**
- ✅ Worker respects 10:00-22:00 PT window
- ✅ Executes 4-5x per day (verify over 3 days)
- ✅ VRAM limited to 60% (verify with nvidia-smi)
- ✅ Commits only touched files (verify git log)
- ✅ Telemetry logged to local-telemetry DB
- ✅ Unit test with mocked engines
- ✅ Integration test with real translation

**Evidence Collection:**
```bash
# Run worker for 24 hours (log executions)
python scripts/run_content_translation_worker.py 2>&1 | tee worker.log

# Verify execution count
grep "Cycle complete" worker.log | grep -c "success"  # Should be 4-5

# Verify VRAM usage
nvidia-smi --query-gpu=memory.used,memory.total --format=csv --loop=10

# Verify commits
git log --oneline --since="24 hours ago" --grep="autonomous_content_translation"

# Verify telemetry
sqlite3 ../local-telemetry/data/telemetry.db \
  "SELECT COUNT(*) FROM translation_runs WHERE trigger_type='scheduled' AND created_at > datetime('now', '-1 day');"
```

---

### Phase 3: Worker #2 - TM Improvement (5-7 days)

#### TASK-005: TMImprovementWorker Skeleton
**Effort:** 8 hours
**Dependencies:** TASK-001, TASK-002, TASK-003
**Priority:** HIGH

**Objective:** Create TM/cache improvement worker using LLM

**Files to CREATE:**
- `src/workers/tm_improvement_worker.py`
- `tests/unit/workers/test_tm_improvement_worker.py`
- `scripts/run_tm_improvement_worker.py`

**Implementation:**
```python
# src/workers/tm_improvement_worker.py
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.shared_engines.composition_root import CompositionRoot
from src.hardware.vram_enforcer import VRAMEnforcer
from src.scheduling.window_scheduler import WindowScheduler
from src.tm import TranslationMemory

logger = logging.getLogger(__name__)


class TMImprovementWorker:
    """
    Autonomous TM/cache improvement worker using LLM.

    Scheduled Execution:
    - Runs 4-5 times per day
    - Active window: 10:00-22:00 America/Los_Angeles
    - Uses LLM (Ollama preferred, fallback to API)
    - Improves translations in TM L2/L3 stores
    - Writes back to TM for next translation run
    """

    def __init__(
        self,
        config_root: str = "config",
        execution_mode: str = "windows_cuda",
        tm_root: Path = Path("data/tm"),
        llm_backend: str = "ollama"  # "ollama", "claude", "gpt4"
    ):
        """Initialize worker with shared engines and TM."""
        # Create engines with LLM backend
        self.engines = CompositionRoot.create_from_config({
            "config_root": config_root,
            "execution_mode": execution_mode,
            "telemetry_enabled": True,
            "commit_enabled": False,  # TM worker doesn't commit
            "translation_backend": "llm",  # Use LLM backend
            "llm_backend_type": llm_backend
        })

        # TM access
        from src.tm import create_translation_memory
        self.tm = create_translation_memory(tm_root)

        # VRAM enforcement (if using Ollama with GPU)
        self.vram_enforcer = VRAMEnforcer(budget_percent=0.60)

        # Scheduling
        self.scheduler = WindowScheduler(
            executions_per_day=(4, 5),
            window_start=time(10, 0),
            window_end=time(22, 0),
            timezone="America/Los_Angeles"
        )

        logger.info(f"TMImprovementWorker initialized with {llm_backend} backend")

    def select_candidates_for_improvement(
        self,
        max_candidates: int = 100,
        quality_threshold: float = 0.80
    ) -> List[Dict[str, Any]]:
        """
        Select translation candidates for LLM improvement.

        Selection Criteria:
        - Low L3 similarity scores (<0.80)
        - High TM hit count (frequently used)
        - Recent translations (within last 30 days)
        - Segments with validation warnings

        Args:
            max_candidates: Maximum number to select
            quality_threshold: Similarity threshold for selection

        Returns:
            List of candidates with metadata
        """
        # Query TM L2 store for candidates
        # (Implementation: Use LMDB cursor + FAISS similarity scoring)

        candidates = []

        # Example candidate:
        # {
        #     "source_text": "Welcome to our documentation",
        #     "target_text": "Willkommen zu unserer Dokumentation",
        #     "src_lang": "en",
        #     "tgt_lang": "de",
        #     "tm_key": "hash123",
        #     "hit_count": 45,
        #     "similarity_score": 0.75,
        #     "last_used": "2026-01-15"
        # }

        return candidates[:max_candidates]

    def improve_translation_with_llm(
        self,
        candidate: Dict[str, Any]
    ) -> Optional[str]:
        """
        Improve translation using LLM with context and terminology.

        Args:
            candidate: Translation candidate dict

        Returns:
            Improved translation or None if LLM fails
        """
        # Build LLM prompt with:
        # 1. Source text
        # 2. Current translation
        # 3. Terminology hints (from config/terminology.yaml)
        # 4. Style guidelines
        # 5. Request: "Improve this translation for accuracy and fluency"

        prompt = f"""
You are a professional translator improving an existing translation.

Source Language: {candidate['src_lang']}
Target Language: {candidate['tgt_lang']}

Source Text:
{candidate['source_text']}

Current Translation:
{candidate['target_text']}

Instructions:
1. Review the current translation for accuracy and fluency
2. Preserve terminology and proper nouns
3. Improve clarity and naturalness
4. Maintain the same tone and formality level

Provide ONLY the improved translation, no explanations.
"""

        try:
            # Use LLM backend
            improved = self.engines.translation.backend.translate(
                text=candidate['source_text'],
                src_lang=candidate['src_lang'],
                tgt_lang=candidate['tgt_lang'],
                context=candidate['target_text'],  # Pass current as context
                temperature=0.3  # Low temperature for consistency
            )

            logger.debug(
                f"Improved translation: "
                f"Original: {candidate['target_text'][:50]}... → "
                f"Improved: {improved[:50]}..."
            )

            return improved

        except Exception as e:
            logger.error(f"LLM improvement failed: {e}")
            return None

    def write_back_to_tm(
        self,
        candidate: Dict[str, Any],
        improved_translation: str
    ) -> bool:
        """
        Write improved translation back to TM.

        Args:
            candidate: Original candidate dict
            improved_translation: Improved translation text

        Returns:
            True if write successful
        """
        try:
            # Update L2 store (LMDB)
            self.tm.l2_store.put(
                key=candidate['tm_key'],
                value=improved_translation,
                metadata={
                    "improved_by": "llm",
                    "improvement_date": datetime.now().isoformat(),
                    "original_translation": candidate['target_text']
                }
            )

            # Update L3 embeddings (FAISS)
            self.tm.l3_store.update_embedding(
                key=candidate['tm_key'],
                text=improved_translation
            )

            logger.info(f"Updated TM entry: {candidate['tm_key']}")
            return True

        except Exception as e:
            logger.error(f"TM write failed: {e}")
            return False

    def run_improvement_cycle(self) -> Dict[str, Any]:
        """
        Execute single TM improvement cycle.

        Returns:
            Execution report with stats
        """
        # 1. Check if within execution window
        if not self.scheduler.should_execute_now():
            logger.debug("Outside execution window, skipping")
            return {"status": "skipped", "reason": "outside_window"}

        # 2. Enforce VRAM budget (if using GPU-accelerated LLM)
        device = self.engines.limiting.auto_select_device()
        if device.startswith("cuda"):
            self.vram_enforcer.enforce_budget(device)

        # 3. Select candidates
        candidates = self.select_candidates_for_improvement(
            max_candidates=100,
            quality_threshold=0.80
        )

        if not candidates:
            logger.info("No candidates found for improvement")
            return {"status": "skipped", "reason": "no_candidates"}

        # 4. Process improvements
        run_id = f"tm_worker_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        with self.engines.telemetry.track_translation_session(
            job_type="autonomous_tm_improvement",
            trigger_type="scheduled"
        ) as ctx:
            improved_count = 0
            failed_count = 0

            for candidate in candidates:
                try:
                    # Improve with LLM
                    improved = self.improve_translation_with_llm(candidate)

                    if improved:
                        # Write back to TM
                        if self.write_back_to_tm(candidate, improved):
                            improved_count += 1
                        else:
                            failed_count += 1
                    else:
                        failed_count += 1

                except Exception as e:
                    logger.error(f"Improvement failed for candidate: {e}")
                    failed_count += 1

            # 5. Record execution
            self.scheduler.record_execution()

            ctx.set_metrics(
                candidates_processed=len(candidates),
                improvements_written=improved_count,
                failures=failed_count
            )

            return {
                "status": "success",
                "candidates_processed": len(candidates),
                "improvements_written": improved_count,
                "failures": failed_count,
                "run_id": run_id
            }

    def run_forever(self, poll_interval_seconds: int = 300):
        """
        Run worker in continuous loop.

        Args:
            poll_interval_seconds: Time between checks (default: 5 minutes)
        """
        logger.info(
            f"Starting TMImprovementWorker: "
            f"poll_interval={poll_interval_seconds}s, "
            f"window=10:00-22:00 PT, "
            f"frequency=4-5x/day"
        )

        while True:
            try:
                report = self.run_improvement_cycle()
                logger.info(f"Cycle complete: {report}")

            except KeyboardInterrupt:
                logger.info("Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)

            # Sleep until next check
            time.sleep(poll_interval_seconds)
```

**Entrypoint Script:**
```python
# scripts/run_tm_improvement_worker.py
import sys
from pathlib import Path
from src.workers.tm_improvement_worker import TMImprovementWorker

def main():
    worker = TMImprovementWorker(
        config_root="config",
        execution_mode="windows_cuda",
        tm_root=Path("data/tm"),
        llm_backend="ollama"  # Prefer Ollama, fallback to API
    )

    worker.run_forever(poll_interval_seconds=300)

if __name__ == "__main__":
    main()
```

**Acceptance Criteria:**
- ✅ Worker respects 10:00-22:00 PT window
- ✅ Executes 4-5x per day (verify over 3 days)
- ✅ Uses Ollama LLM (verify via logs)
- ✅ Fallback to API LLM if Ollama unavailable
- ✅ VRAM limited to 60% (verify with nvidia-smi)
- ✅ Writes improvements back to TM L2/L3
- ✅ Telemetry logged to local-telemetry DB
- ✅ Unit test with mocked TM and LLM
- ✅ Integration test with real TM store

**Evidence Collection:**
```bash
# Run worker for 24 hours
python scripts/run_tm_improvement_worker.py 2>&1 | tee tm_worker.log

# Verify execution count
grep "Cycle complete" tm_worker.log | grep -c "success"  # Should be 4-5

# Verify TM improvements written
grep "improvements_written" tm_worker.log | tail -n 10

# Verify VRAM usage
nvidia-smi --query-gpu=memory.used,memory.total --format=csv --loop=10

# Verify telemetry
sqlite3 ../local-telemetry/data/telemetry.db \
  "SELECT COUNT(*) FROM translation_runs WHERE job_type='autonomous_tm_improvement' AND created_at > datetime('now', '-1 day');"

# Verify TM updates
python -c "
from src.tm import create_translation_memory
from pathlib import Path
tm = create_translation_memory(Path('data/tm'))
stats = tm.get_stats()
print(f'TM L2 entries: {stats.l2_entries}')
print(f'TM L3 embeddings: {stats.l3_embeddings}')
"
```

---

### Phase 4: Integration & Deployment (3-5 days)

#### TASK-006: Docker Compose Integration
**Effort:** 4 hours
**Dependencies:** TASK-004, TASK-005
**Priority:** MEDIUM

**Objective:** Add workers to docker-compose.yml

**Files to MODIFY:**
- `docker-compose.yml`
- `.dockerignore`

**Implementation:**
```yaml
# docker-compose.yml (ADD)
services:
  # Existing services...

  content-translation-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    container_name: hugo-translator-content-worker
    restart: unless-stopped
    environment:
      - EXECUTION_MODE=docker_gpu
      - WORKER_TYPE=content_translation
      - POLL_INTERVAL=300
      - LOG_LEVEL=INFO
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ../content:/content:rw
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    networks:
      - hugo-translator-net

  tm-improvement-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    container_name: hugo-translator-tm-worker
    restart: unless-stopped
    environment:
      - EXECUTION_MODE=docker_gpu
      - WORKER_TYPE=tm_improvement
      - POLL_INTERVAL=300
      - LLM_BACKEND=ollama
      - LOG_LEVEL=INFO
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    networks:
      - hugo-translator-net
    depends_on:
      - ollama

  ollama:
    image: ollama/ollama:latest
    container_name: hugo-translator-ollama
    restart: unless-stopped
    volumes:
      - ./data/ollama:/root/.ollama
    ports:
      - "11434:11434"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    networks:
      - hugo-translator-net
```

**Dockerfile:**
```dockerfile
# docker/Dockerfile.worker
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements/base.txt requirements/gpu.txt ./
RUN pip install --no-cache-dir -r base.txt -r gpu.txt

# Copy source
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/

# Entrypoint
COPY docker/worker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

**Entrypoint Script:**
```bash
#!/bin/bash
# docker/worker-entrypoint.sh

set -e

# Determine worker type
WORKER_TYPE=${WORKER_TYPE:-"content_translation"}

echo "Starting worker: $WORKER_TYPE"
echo "Execution mode: $EXECUTION_MODE"
echo "Poll interval: $POLL_INTERVAL"

# Run appropriate worker
if [ "$WORKER_TYPE" = "content_translation" ]; then
    exec python scripts/run_content_translation_worker.py
elif [ "$WORKER_TYPE" = "tm_improvement" ]; then
    exec python scripts/run_tm_improvement_worker.py
else
    echo "Unknown worker type: $WORKER_TYPE"
    exit 1
fi
```

**Acceptance Criteria:**
- ✅ Both workers start via docker-compose
- ✅ Workers access mounted content volumes
- ✅ GPU passthrough works (nvidia-smi inside container)
- ✅ Ollama service accessible at ollama:11434
- ✅ Logs written to mounted data/ directory
- ✅ Workers restart on crash (restart: unless-stopped)

**Evidence Collection:**
```bash
# Start services
docker-compose up -d content-translation-worker tm-improvement-worker ollama

# Verify running
docker ps | grep hugo-translator

# Check GPU access
docker exec hugo-translator-content-worker nvidia-smi

# Check worker logs
docker logs -f hugo-translator-content-worker
docker logs -f hugo-translator-tm-worker

# Verify Ollama
curl http://localhost:11434/api/version
```

---

#### TASK-007: Windows Task Scheduler Integration
**Effort:** 3 hours
**Dependencies:** TASK-004, TASK-005
**Priority:** LOW

**Objective:** Create Windows Task Scheduler scripts for native execution

**Files to CREATE:**
- `scripts/windows/schedule_content_worker.ps1`
- `scripts/windows/schedule_tm_worker.ps1`

**Implementation:**
```powershell
# scripts/windows/schedule_content_worker.ps1
$TaskName = "HugoTranslator-ContentWorker"
$ScriptPath = "$PSScriptRoot\..\..\venv\Scripts\python.exe"
$Arguments = "$PSScriptRoot\..\run_content_translation_worker.py"
$WorkingDir = "$PSScriptRoot\..\.."

# Create scheduled task (runs continuously, restart on failure)
$Action = New-ScheduledTaskAction -Execute $ScriptPath -Argument $Arguments -WorkingDirectory $WorkingDir
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force

Write-Host "Registered task: $TaskName"
Write-Host "To start: Start-ScheduledTask -TaskName '$TaskName'"
```

**Acceptance Criteria:**
- ✅ PowerShell script registers Windows scheduled task
- ✅ Task starts on system boot
- ✅ Task restarts on failure (up to 3 times)
- ✅ Logs written to data/logs/
- ✅ Manual start/stop via PowerShell

**Evidence Collection:**
```powershell
# Register tasks
.\scripts\windows\schedule_content_worker.ps1
.\scripts\windows\schedule_tm_worker.ps1

# Verify tasks
Get-ScheduledTask | Where-Object {$_.TaskName -like "HugoTranslator-*"}

# Start tasks
Start-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Start-ScheduledTask -TaskName "HugoTranslator-TMWorker"

# Check status
Get-ScheduledTask -TaskName "HugoTranslator-*" | Select-Object TaskName, State, LastRunTime
```

---

#### TASK-008: Configuration Examples
**Effort:** 2 hours
**Dependencies:** None
**Priority:** LOW

**Objective:** Create example configs for both workers

**Files to CREATE:**
- `config/workers/content_translation.example.yaml`
- `config/workers/tm_improvement.example.yaml`

**Content Translation Config:**
```yaml
# config/workers/content_translation.example.yaml
worker:
  name: "content-translation-worker"
  type: "content_translation"

  # Scheduling
  schedule:
    window_start: "10:00"  # Pacific Time
    window_end: "22:00"    # Pacific Time
    executions_per_day_min: 4
    executions_per_day_max: 5
    jitter_minutes: 15
    poll_interval_seconds: 300  # 5 minutes

  # Content roots to monitor
  content_roots:
    - path: "../products.aspose.net/content"
      site_id: "products.aspose.net"
      target_langs: ["de", "fr", "es", "ja", "zh"]
    - path: "../docs.aspose.net/content"
      site_id: "docs.aspose.net"
      target_langs: ["de", "fr", "es", "ja", "zh"]

  # Resource limits
  resources:
    vram_budget_percent: 0.60  # 60% VRAM limit
    required_memory_mb: 2048
    required_gpu_memory_mb: 4096

  # Git commit settings
  git:
    enabled: true
    auto_push: true
    commit_only_touched: true

  # Telemetry
  telemetry:
    enabled: true
    trigger_type: "scheduled"
```

**TM Improvement Config:**
```yaml
# config/workers/tm_improvement.example.yaml
worker:
  name: "tm-improvement-worker"
  type: "tm_improvement"

  # Scheduling (same window as content worker)
  schedule:
    window_start: "10:00"  # Pacific Time
    window_end: "22:00"    # Pacific Time
    executions_per_day_min: 4
    executions_per_day_max: 5
    jitter_minutes: 15
    poll_interval_seconds: 300  # 5 minutes

  # TM paths
  tm:
    root: "data/tm"
    max_candidates_per_cycle: 100
    quality_threshold: 0.80  # Select entries below 80% similarity

  # LLM backend
  llm:
    backend: "ollama"  # ollama, claude, gpt4
    ollama:
      base_url: "http://localhost:11434"
      model_id: "llama2:7b"
      temperature: 0.3
      fallback_to_api: true
    claude:
      model_id: "claude-sonnet-4-5"
      api_key_env: "ANTHROPIC_API_KEY"
      temperature: 0.3
    gpt4:
      model_id: "gpt-4-turbo"
      api_key_env: "OPENAI_API_KEY"
      temperature: 0.3

  # Resource limits
  resources:
    vram_budget_percent: 0.60  # 60% VRAM limit
    required_memory_mb: 2048
    required_gpu_memory_mb: 4096

  # Telemetry
  telemetry:
    enabled: true
    trigger_type: "scheduled"
```

**Acceptance Criteria:**
- ✅ Example configs provide all settings
- ✅ Configs include comments explaining each field
- ✅ Workers load and validate configs

---

### Phase 5: Testing & Validation (3-5 days)

#### TASK-009: Unit Tests
**Effort:** 8 hours
**Dependencies:** TASK-001 through TASK-005
**Priority:** HIGH

**Test Coverage Requirements:**
- VRAMEnforcer: 90%+
- WindowScheduler: 90%+
- OllamaBackend: 85%+
- ContentTranslationWorker: 80%+
- TMImprovementWorker: 80%+

**Files to CREATE:**
- `tests/unit/hardware/test_vram_enforcer.py`
- `tests/unit/scheduling/test_window_scheduler.py`
- `tests/unit/shared_engines/test_ollama_backend.py`
- `tests/unit/workers/test_content_translation_worker.py`
- `tests/unit/workers/test_tm_improvement_worker.py`

**Example Test:**
```python
# tests/unit/scheduling/test_window_scheduler.py
import pytest
from datetime import datetime, time
from zoneinfo import ZoneInfo
from unittest.mock import patch

from src.scheduling.window_scheduler import WindowScheduler


class TestWindowScheduler:
    def test_within_window(self):
        """Test execution within 10:00-22:00 PT window."""
        scheduler = WindowScheduler(
            executions_per_day=(4, 5),
            window_start=time(10, 0),
            window_end=time(22, 0),
            timezone="America/Los_Angeles"
        )

        # Mock time to 12:00 PT
        with patch('src.scheduling.window_scheduler.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(
                2026, 1, 16, 12, 0, 0,
                tzinfo=ZoneInfo("America/Los_Angeles")
            )

            # Should be within window
            assert scheduler.should_execute_now()

    def test_outside_window(self):
        """Test execution outside window (before 10:00)."""
        scheduler = WindowScheduler()

        # Mock time to 8:00 PT
        with patch('src.scheduling.window_scheduler.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(
                2026, 1, 16, 8, 0, 0,
                tzinfo=ZoneInfo("America/Los_Angeles")
            )

            # Should be outside window
            assert not scheduler.should_execute_now()

    def test_execution_frequency(self):
        """Test 4-5 executions per day limit."""
        scheduler = WindowScheduler(executions_per_day=(4, 5))

        # Record 5 executions
        for _ in range(5):
            scheduler.record_execution()

        # 6th execution should be blocked
        assert not scheduler._check_daily_limit()
```

**Acceptance Criteria:**
- ✅ All unit tests pass
- ✅ Coverage >= 80% for all new modules
- ✅ Tests use mocking for external dependencies
- ✅ Tests run in <10 seconds total

**Evidence Collection:**
```bash
# Run unit tests with coverage
pytest tests/unit/ -v --cov=src --cov-report=html --cov-report=term

# Verify coverage thresholds
coverage report --fail-under=80

# Generate HTML report
open htmlcov/index.html
```

---

#### TASK-010: Integration Tests
**Effort:** 6 hours
**Dependencies:** TASK-009
**Priority:** HIGH

**Test Scenarios:**
1. Content worker end-to-end (translation + commit)
2. TM worker end-to-end (improvement + TM update)
3. VRAM enforcement validation
4. Scheduling window validation (24-hour simulation)
5. Ollama backend with fallback

**Files to CREATE:**
- `tests/integration/test_content_worker_e2e.py`
- `tests/integration/test_tm_worker_e2e.py`
- `tests/integration/test_vram_enforcement.py`
- `tests/integration/test_scheduling_24h_simulation.py`

**Example Test:**
```python
# tests/integration/test_content_worker_e2e.py
import pytest
from pathlib import Path
from src.workers.content_translation_worker import ContentTranslationWorker


@pytest.mark.integration
@pytest.mark.gpu
def test_content_worker_full_cycle(tmp_path):
    """Test full content worker cycle: scan → translate → commit."""
    # Setup test content
    content_root = tmp_path / "content"
    content_root.mkdir()
    (content_root / "example.md").write_text(
        "---\ntitle: Test\n---\n\nHello world"
    )

    # Initialize worker
    worker = ContentTranslationWorker(
        config_root="config",
        execution_mode="windows_cuda"
    )

    # Run single cycle
    report = worker.run_translation_cycle(
        content_roots=[content_root],
        target_langs=["de"],
        site_id="test.example.com"
    )

    # Verify results
    assert report["status"] == "success"
    assert report["files_translated"] > 0
    assert "commit_hash" in report

    # Verify translated file exists
    de_file = content_root / "de" / "example.md"
    assert de_file.exists()
    assert "Hallo Welt" in de_file.read_text()
```

**Acceptance Criteria:**
- ✅ All integration tests pass
- ✅ Tests use real components (no mocks)
- ✅ Tests clean up temp files
- ✅ Tests marked with @pytest.mark.integration
- ✅ Tests run in <60 seconds total

**Evidence Collection:**
```bash
# Run integration tests
pytest tests/integration/ -v -m integration

# Run GPU tests (if GPU available)
pytest tests/integration/ -v -m gpu

# Run with resource monitoring
pytest tests/integration/ -v --durations=10
```

---

#### TASK-011: Contract Tests
**Effort:** 4 hours
**Dependencies:** TASK-010
**Priority:** MEDIUM

**Contract Tests (NEW):**
- `CONTRACT-013`: VRAM budget enforcement (<=60%)
- `CONTRACT-014`: Pacific Time window scheduling
- `CONTRACT-015`: LLM backend fallback (Ollama → API)
- `CONTRACT-016`: TM write-back integrity

**Files to CREATE:**
- `tests/contract/test_vram_budget_contract.py`
- `tests/contract/test_scheduling_window_contract.py`
- `tests/contract/test_llm_fallback_contract.py`
- `tests/contract/test_tm_writeback_contract.py`

**Example Contract:**
```python
# tests/contract/test_vram_budget_contract.py
"""
CONTRACT-013: VRAM Budget Enforcement

Invariant: Workers must enforce <=60% VRAM budget when using CUDA.

Verification:
1. Worker starts with CUDA device
2. VRAMEnforcer sets memory fraction to 0.60
3. Peak VRAM usage during translation <= 60% total VRAM
4. Violation triggers warning + batch reduction
"""

import pytest
import torch
from src.hardware.vram_enforcer import VRAMEnforcer


@pytest.mark.contract
@pytest.mark.gpu
def test_vram_budget_contract():
    """Verify VRAM budget enforcement at 60%."""
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")

    # Get total VRAM
    total_vram_mb = torch.cuda.get_device_properties(0).total_memory / (1024**2)

    # Enforce 60% budget
    enforcer = VRAMEnforcer(budget_percent=0.60)
    assert enforcer.enforce_budget("cuda:0")

    # Verify memory fraction set
    # (Note: torch doesn't expose get_per_process_memory_fraction,
    #  so we verify by attempting allocation)
    expected_budget_mb = total_vram_mb * 0.60

    # Attempt to allocate 70% (should fail)
    with pytest.raises(RuntimeError):
        x = torch.zeros(int(total_vram_mb * 0.70 * 1024 * 1024 / 4), device="cuda")

    # Attempt to allocate 50% (should succeed)
    x = torch.zeros(int(total_vram_mb * 0.50 * 1024 * 1024 / 4), device="cuda")
    assert x.device.type == "cuda"

    # Cleanup
    del x
    torch.cuda.empty_cache()
```

**Acceptance Criteria:**
- ✅ All 4 new contracts pass
- ✅ Contracts use real components (no mocks)
- ✅ Contracts fail on violation (negative tests)
- ✅ Contracts marked with @pytest.mark.contract

**Evidence Collection:**
```bash
# Run contract tests
pytest tests/contract/ -v -m contract

# Verify new contracts
pytest tests/contract/ -v -k "test_vram_budget_contract or test_scheduling_window_contract"
```

---

## 5. Documentation & Specs Plan

### 5.1 Existing Documentation to UPDATE

**File:** [src/shared_engines/README.md](../../src/shared_engines/README.md)

**Changes Required:**
- Update status table (all engines marked as ✅ DONE)
- Add new sections:
  - VRAMEnforcer integration
  - WindowScheduler usage
  - OllamaBackend configuration
- Update file structure to include scheduling/ directory

**Evidence:** README accurately reflects implementation status

---

**File:** [config/global.yaml](../../config/global.yaml)

**Changes Required:**
- Add `autonomous_workers` section:
  ```yaml
  autonomous_workers:
    enabled: true
    workers:
      content_translation:
        enabled: true
        schedule:
          window_start: "10:00"
          window_end: "22:00"
          timezone: "America/Los_Angeles"
          frequency_per_day: [4, 5]
        resources:
          vram_budget_percent: 0.60
      tm_improvement:
        enabled: true
        schedule:
          window_start: "10:00"
          window_end: "22:00"
          timezone: "America/Los_Angeles"
          frequency_per_day: [4, 5]
        llm_backend: "ollama"
  ```

**Evidence:** Workers load config correctly

---

### 5.2 New Documentation to CREATE

**File:** `docs/workers/autonomous_workers.md` (NEW)

**Content:**
- Overview of autonomous workers architecture
- Content Translation Worker guide
- TM Improvement Worker guide
- Configuration reference
- Deployment options (Docker vs Windows)
- Troubleshooting guide

**Evidence:** Documentation covers all worker features

---

**File:** `docs/workers/scheduling.md` (NEW)

**Content:**
- Scheduling concepts (windows, frequency, jitter)
- Pacific Time window configuration
- Execution history tracking
- Debugging scheduling issues

**Evidence:** Documentation includes examples

---

**File:** `specs/features/worker-001-content-translation.md` (NEW)

**Content:**
```markdown
# WORKER-001: Autonomous Content Translation

## Overview
Scheduled content translation worker for Hugo sites.

## Requirements
- REQ-001: Execute 4-5 times daily between 10:00-22:00 PT
- REQ-002: Use CUDA with <=60% VRAM enforcement
- REQ-003: Commit only touched files with semantic messages
- REQ-004: Log all operations to local-telemetry
- REQ-005: Support multiple content roots per site

## Architecture
- Shared Engines: TelemetryEngine, CommitEngine, LimitingEngine
- Scheduling: WindowScheduler with jitter
- VRAM: VRAMEnforcer at 60% budget

## Configuration
[Configuration examples...]

## Testing
- CONTRACT-013: VRAM budget <= 60%
- CONTRACT-014: Scheduling window respected
- Integration: End-to-end translation + commit

## Acceptance
- ✅ Worker executes 4-5x/day within window
- ✅ VRAM usage <= 60% total VRAM
- ✅ Git commits contain only translated files
- ✅ Telemetry events recorded in local-telemetry DB
```

**Evidence:** Spec covers all requirements

---

**File:** `specs/features/worker-002-tm-improvement.md` (NEW)

**Content:**
```markdown
# WORKER-002: TM/Cache Improvement Worker

## Overview
LLM-based translation quality improvement worker.

## Requirements
- REQ-001: Execute 4-5 times daily between 10:00-22:00 PT
- REQ-002: Use Ollama LLM (prefer local, fallback to API)
- REQ-003: Improve low-quality TM entries (<80% similarity)
- REQ-004: Write improvements back to TM L2/L3
- REQ-005: Use CUDA with <=60% VRAM enforcement

## Architecture
- Shared Engines: TelemetryEngine, TranslationBackend (LLM)
- TM Access: Direct L2 LMDB + L3 FAISS
- LLM: OllamaBackend with API fallback

## Candidate Selection
- Low similarity scores (<0.80)
- High TM hit count (frequently used)
- Recent usage (last 30 days)
- Validation warnings flagged

## LLM Prompting
[Prompt template with context...]

## Configuration
[Configuration examples...]

## Testing
- CONTRACT-015: LLM fallback works (Ollama → API)
- CONTRACT-016: TM write-back preserves integrity
- Integration: End-to-end improvement cycle

## Acceptance
- ✅ Worker executes 4-5x/day within window
- ✅ Ollama used when available, fallback works
- ✅ TM L2/L3 updated with improvements
- ✅ Telemetry events recorded
```

**Evidence:** Spec covers all requirements

---

### 5.3 Updated Repository Structure

**New Directories:**
```
src/
├── scheduling/                    # NEW: Scheduling utilities
│   ├── __init__.py
│   └── window_scheduler.py
├── workers/                       # NEW: Autonomous workers
│   ├── __init__.py
│   ├── content_translation_worker.py
│   └── tm_improvement_worker.py

tests/
├── unit/
│   ├── scheduling/                # NEW: Scheduler tests
│   └── workers/                   # NEW: Worker tests
├── integration/
│   └── test_*_worker_e2e.py      # NEW: E2E worker tests
└── contract/
    └── test_*_contract.py        # NEW: Contract tests

docs/
└── workers/                       # NEW: Worker documentation
    ├── autonomous_workers.md
    └── scheduling.md

config/
└── workers/                       # NEW: Worker configs
    ├── content_translation.example.yaml
    └── tm_improvement.example.yaml

scripts/
├── run_content_translation_worker.py   # NEW
├── run_tm_improvement_worker.py        # NEW
└── windows/                            # NEW: Windows Task Scheduler
    ├── schedule_content_worker.ps1
    └── schedule_tm_worker.ps1

docker/
├── Dockerfile.worker              # NEW
└── worker-entrypoint.sh           # NEW
```

**Evidence:** All new directories created with proper structure

---

## 6. Acceptance Tests

### 6.1 Pre-Implementation Baseline

**Run BEFORE starting implementation:**

```bash
# 1. Capture current test status
pytest --collect-only > reports/baseline_tests.txt

# 2. Verify existing contracts pass
pytest tests/contract/ -v --tb=short

# 3. Verify GPU manager works
python -c "from src.hardware.gpu_manager import GPUManager; mgr = GPUManager(); caps = mgr.detect(); print(caps.to_dict())"

# 4. Verify telemetry integration
python -c "from src.observability.telemetry_integration import get_telemetry; t = get_telemetry('test'); print('Telemetry OK')"

# 5. Verify shared engines exist
python -c "from src.shared_engines.composition_root import CompositionRoot; engines = CompositionRoot.create_from_config({}); print(engines)"
```

**Expected Output:**
- All existing contracts pass (INV-001 through INV-012)
- GPU detected (if available)
- Telemetry client initialized
- 8 shared engines created

---

### 6.2 Component-Level Acceptance

**TASK-001 Acceptance (VRAMEnforcer):**

```bash
# Test: VRAM enforcement at 60%
python -c "
from src.hardware.vram_enforcer import VRAMEnforcer
import torch

if torch.cuda.is_available():
    enforcer = VRAMEnforcer(budget_percent=0.60)
    assert enforcer.enforce_budget('cuda:0'), 'Failed to enforce budget'

    # Get VRAM info
    info = enforcer.get_current_usage()
    print(f'Total VRAM: {info[\"total_mb\"]:.0f} MB')
    print(f'Budget: {info[\"budget_mb\"]:.0f} MB ({info[\"budget_percent\"]*100:.0f}%)')
    print('✅ VRAM enforcement PASSED')
else:
    print('⚠️ CUDA not available, skipping test')
"
```

**Expected:** Budget set to 60% of total VRAM

---

**TASK-002 Acceptance (WindowScheduler):**

```bash
# Test: Scheduling within 10:00-22:00 PT, 4-5x/day
pytest tests/unit/scheduling/test_window_scheduler.py -v

# Simulate 24 hours (fast-forward time)
python -c "
from src.scheduling.window_scheduler import WindowScheduler
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

scheduler = WindowScheduler()

# Simulate 24-hour period
executions = []
start = datetime(2026, 1, 16, 0, 0, 0, tzinfo=ZoneInfo('America/Los_Angeles'))

for hour in range(24):
    current_time = start + timedelta(hours=hour)

    with patch('src.scheduling.window_scheduler.datetime') as mock_dt:
        mock_dt.now.return_value = current_time

        if scheduler.should_execute_now():
            executions.append(current_time)
            scheduler.record_execution()

print(f'Executions in 24h: {len(executions)}')
assert 4 <= len(executions) <= 5, f'Expected 4-5 executions, got {len(executions)}'

# Verify all within window
for exec_time in executions:
    hour = exec_time.hour
    assert 10 <= hour <= 22, f'Execution at {hour}:00 outside 10:00-22:00 window'

print('✅ Window scheduling PASSED')
"
```

**Expected:** 4-5 executions scheduled between 10:00-22:00 PT

---

**TASK-003 Acceptance (OllamaBackend):**

```bash
# Test: Ollama backend with fallback
pytest tests/integration/test_ollama_backend.py -v

# Manual test (requires Ollama running)
python -c "
from src.shared_engines.translation_backends import OllamaBackend, MTBackend

# Create backend with fallback
fallback = MTBackend(model_id='m2m100_418m')
ollama = OllamaBackend(
    model_id='llama2:7b',
    base_url='http://localhost:11434',
    fallback_backend=fallback
)

# Test translation
if ollama.is_available():
    result = ollama.translate('Hello world', 'en', 'de')
    print(f'Ollama translation: {result}')
    print('✅ Ollama backend PASSED')
else:
    print('⚠️ Ollama not available, testing fallback...')
    result = ollama.translate('Hello world', 'en', 'de')
    print(f'Fallback translation: {result}')
    print('✅ Fallback backend PASSED')
"
```

**Expected:** Ollama translates if available, falls back to MT otherwise

---

**TASK-004 Acceptance (ContentTranslationWorker):**

```bash
# Test: Content worker end-to-end
pytest tests/integration/test_content_worker_e2e.py -v

# Manual smoke test (5-minute run)
python scripts/run_content_translation_worker.py &
WORKER_PID=$!

sleep 300  # Run for 5 minutes

kill $WORKER_PID

# Verify logs
grep "ContentTranslationWorker initialized" data/logs/hugo-translator.ndjson
grep "Cycle complete" data/logs/hugo-translator.ndjson

# Verify VRAM usage
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

**Expected:**
- Worker starts successfully
- At least 1 cycle completes (if within window)
- VRAM usage <= 60% total
- Telemetry events logged

---

**TASK-005 Acceptance (TMImprovementWorker):**

```bash
# Test: TM worker end-to-end
pytest tests/integration/test_tm_worker_e2e.py -v

# Manual smoke test (5-minute run)
python scripts/run_tm_improvement_worker.py &
WORKER_PID=$!

sleep 300

kill $WORKER_PID

# Verify TM updates
python -c "
from src.tm import create_translation_memory
from pathlib import Path

tm = create_translation_memory(Path('data/tm'))
stats = tm.get_stats()

print(f'L2 entries: {stats.l2_entries}')
print(f'L3 embeddings: {stats.l3_embeddings}')

# Check for recent improvements
# (Implementation: Query L2 metadata for 'improved_by: llm')
print('✅ TM worker PASSED')
"
```

**Expected:**
- Worker starts successfully
- At least 1 improvement cycle completes
- TM L2/L3 updated with improved translations
- Telemetry events logged

---

### 6.3 End-to-End System Acceptance

**Full System Test (24-hour run):**

```bash
# Day 1: Start both workers (Docker deployment)
docker-compose up -d content-translation-worker tm-improvement-worker ollama

# Monitor for 24 hours
for i in {1..288}; do  # 288 = 24 hours / 5 minutes
    echo "=== Hour $((i/12)) ==="

    # Check worker status
    docker ps | grep hugo-translator

    # Check VRAM usage
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv

    # Check execution counts
    docker logs hugo-translator-content-worker 2>&1 | grep -c "Cycle complete: success"
    docker logs hugo-translator-tm-worker 2>&1 | grep -c "Cycle complete: success"

    sleep 300  # 5 minutes
done

# Day 2: Verify results
echo "=== Execution Summary ==="

# Content worker executions
CONTENT_EXEC=$(docker logs hugo-translator-content-worker 2>&1 | grep "Cycle complete: success" | wc -l)
echo "Content worker executions: $CONTENT_EXEC (expected: 4-5)"

# TM worker executions
TM_EXEC=$(docker logs hugo-translator-tm-worker 2>&1 | grep "Cycle complete: success" | wc -l)
echo "TM worker executions: $TM_EXEC (expected: 4-5)"

# Verify commits
GIT_COMMITS=$(git log --oneline --since="24 hours ago" --grep="autonomous_content_translation" | wc -l)
echo "Git commits: $GIT_COMMITS"

# Verify telemetry
TELEMETRY_COUNT=$(sqlite3 ../local-telemetry/data/telemetry.db \
  "SELECT COUNT(*) FROM translation_runs WHERE trigger_type='scheduled' AND created_at > datetime('now', '-1 day');")
echo "Telemetry events: $TELEMETRY_COUNT"

# Verify VRAM compliance
PEAK_VRAM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
TOTAL_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)
VRAM_PERCENT=$(echo "scale=2; $PEAK_VRAM / $TOTAL_VRAM * 100" | bc)
echo "Peak VRAM usage: ${VRAM_PERCENT}% (expected: <=60%)"

echo ""
echo "=== Acceptance Criteria ==="
[ $CONTENT_EXEC -ge 4 ] && [ $CONTENT_EXEC -le 5 ] && echo "✅ Content worker frequency: PASS" || echo "❌ Content worker frequency: FAIL"
[ $TM_EXEC -ge 4 ] && [ $TM_EXEC -le 5 ] && echo "✅ TM worker frequency: PASS" || echo "❌ TM worker frequency: FAIL"
[ $GIT_COMMITS -ge 4 ] && echo "✅ Git commits: PASS" || echo "❌ Git commits: FAIL"
[ $TELEMETRY_COUNT -ge 8 ] && echo "✅ Telemetry events: PASS" || echo "❌ Telemetry events: FAIL"
[ $(echo "$VRAM_PERCENT <= 60" | bc) -eq 1 ] && echo "✅ VRAM budget: PASS" || echo "❌ VRAM budget: FAIL"
```

**Expected Results:**
- ✅ Content worker: 4-5 executions in 24h
- ✅ TM worker: 4-5 executions in 24h
- ✅ All executions between 10:00-22:00 PT
- ✅ Git commits created for translated files
- ✅ Telemetry events logged (>=8 total)
- ✅ Peak VRAM usage <= 60% total VRAM
- ✅ No worker crashes or errors

---

### 6.4 Contract Compliance Validation

**Run ALL contract tests:**

```bash
# Existing contracts (must still pass)
pytest tests/contract/ -v -k "test_inv"

# New contracts (must pass)
pytest tests/contract/ -v -k "test_vram_budget_contract"
pytest tests/contract/ -v -k "test_scheduling_window_contract"
pytest tests/contract/ -v -k "test_llm_fallback_contract"
pytest tests/contract/ -v -k "test_tm_writeback_contract"

# Generate contract report
pytest tests/contract/ --tb=short --junitxml=reports/contract_results.xml
```

**Expected:** ALL contracts pass (INV-001 through INV-016)

---

## 7. Risk Register & Mitigation

### Risk 1: VRAM Enforcement Insufficient
**Likelihood:** MEDIUM
**Impact:** HIGH
**Mitigation:**
- Implement VRAMEnforcer with torch memory fraction
- Add runtime monitoring with budget_exceeded alerts
- Adaptive batching reduces load on constraint violation
- Fallback to CPU if VRAM budget consistently exceeded

---

### Risk 2: Scheduling Window Overlap
**Likelihood:** LOW
**Impact:** MEDIUM
**Mitigation:**
- WindowScheduler uses random jitter (±15 minutes)
- Execution history tracking prevents double-execution
- LimitingEngine resource checks prevent overload
- Workers queue operations if resources unavailable

---

### Risk 3: Ollama Unavailable
**Likelihood:** MEDIUM
**Impact:** LOW
**Mitigation:**
- OllamaBackend has automatic fallback to API LLM
- TM worker logs fallback events for monitoring
- Retry logic for transient Ollama connection errors
- Configuration supports disabling TM worker if needed

---

### Risk 4: Git Merge Conflicts
**Likelihood:** MEDIUM
**Impact:** MEDIUM
**Mitigation:**
- ContentTranslationWorker commits only language-specific files
- Per-language branches prevent cross-language conflicts
- CommitEngine signal blocking prevents partial commits
- Auto-push ensures local commits don't accumulate

---

### Risk 5: Telemetry DB Lock Contention
**Likelihood:** LOW
**Impact:** LOW
**Mitigation:**
- Local-telemetry uses WAL mode (concurrent reads/writes)
- Telemetry writes are async (non-blocking)
- Workers use separate telemetry sessions (no shared state)
- Graceful degradation if telemetry write fails

---

## 8. Success Criteria Summary

### Functional Requirements
- ✅ Worker #1 translates content 4-5x/day, 10:00-22:00 PT
- ✅ Worker #2 improves TM 4-5x/day, 10:00-22:00 PT
- ✅ Both use CUDA with <=60% VRAM enforcement
- ✅ Worker #1 commits only touched files
- ✅ Worker #2 writes improvements to TM L2/L3
- ✅ Both log to local-telemetry via API

### Non-Functional Requirements
- ✅ Reuse all 8 shared engines
- ✅ No breaking changes to existing CLI
- ✅ Test coverage >= 80% for new code
- ✅ All contract tests pass (INV-001 through INV-016)
- ✅ Documentation complete and accurate

### Deployment Requirements
- ✅ Docker Compose deployment works
- ✅ Windows Task Scheduler deployment works
- ✅ Configuration examples provided
- ✅ Troubleshooting guide available

---

## 9. File Manifest

### Files to CREATE (22 total)

**Source Code (8 files):**
1. `src/hardware/vram_enforcer.py`
2. `src/scheduling/__init__.py`
3. `src/scheduling/window_scheduler.py`
4. `src/workers/__init__.py`
5. `src/workers/content_translation_worker.py`
6. `src/workers/tm_improvement_worker.py`
7. `scripts/run_content_translation_worker.py`
8. `scripts/run_tm_improvement_worker.py`

**Tests (12 files):**
9. `tests/unit/hardware/test_vram_enforcer.py`
10. `tests/unit/scheduling/test_window_scheduler.py`
11. `tests/unit/workers/test_content_translation_worker.py`
12. `tests/unit/workers/test_tm_improvement_worker.py`
13. `tests/integration/test_content_worker_e2e.py`
14. `tests/integration/test_tm_worker_e2e.py`
15. `tests/integration/test_vram_enforcement.py`
16. `tests/integration/test_scheduling_24h_simulation.py`
17. `tests/contract/test_vram_budget_contract.py`
18. `tests/contract/test_scheduling_window_contract.py`
19. `tests/contract/test_llm_fallback_contract.py`
20. `tests/contract/test_tm_writeback_contract.py`

**Docker (3 files):**
21. `docker/Dockerfile.worker`
22. `docker/worker-entrypoint.sh`
23. `scripts/windows/schedule_content_worker.ps1`

**Configuration (2 files):**
24. `config/workers/content_translation.example.yaml`
25. `config/workers/tm_improvement.example.yaml`

**Documentation (4 files):**
26. `docs/workers/autonomous_workers.md`
27. `docs/workers/scheduling.md`
28. `specs/features/worker-001-content-translation.md`
29. `specs/features/worker-002-tm-improvement.md`

### Files to MODIFY (4 total)

1. `src/shared_engines/translation_backends.py` - Add OllamaBackend
2. `src/shared_engines/README.md` - Update status table
3. `config/global.yaml` - Add autonomous_workers section
4. `docker-compose.yml` - Add worker services

---

## 10. Implementation Timeline

### Phase 1: Foundation (Days 1-5)
- Day 1: TASK-001 (VRAMEnforcer)
- Day 2: TASK-002 (WindowScheduler)
- Days 3-4: TASK-003 (OllamaBackend)
- Day 5: Phase 1 review + fixes

### Phase 2: Worker #1 (Days 6-12)
- Days 6-8: TASK-004 (ContentTranslationWorker)
- Days 9-10: Worker #1 testing
- Days 11-12: Worker #1 documentation

### Phase 3: Worker #2 (Days 13-19)
- Days 13-16: TASK-005 (TMImprovementWorker)
- Days 17-18: Worker #2 testing
- Day 19: Worker #2 documentation

### Phase 4: Integration (Days 20-24)
- Day 20: TASK-006 (Docker Compose)
- Day 21: TASK-007 (Windows Task Scheduler)
- Day 22: TASK-008 (Configuration examples)
- Days 23-24: Integration testing

### Phase 5: Validation (Days 25-29)
- Days 25-26: TASK-009 (Unit tests)
- Day 27: TASK-010 (Integration tests)
- Day 28: TASK-011 (Contract tests)
- Day 29: 24-hour system acceptance test

### Phase 6: Documentation & Handoff (Days 30-32)
- Day 30: Final documentation updates
- Day 31: Deployment guides + troubleshooting
- Day 32: Code review + handoff

**Total Duration:** 32 days (6.4 weeks)

---

## 11. Post-Implementation Checklist

- [ ] All 11 task cards completed
- [ ] All 29 new files created
- [ ] All 4 modified files updated
- [ ] All unit tests pass (coverage >= 80%)
- [ ] All integration tests pass
- [ ] All contract tests pass (INV-001 through INV-016)
- [ ] 24-hour acceptance test pass
- [ ] Documentation complete
- [ ] Docker Compose deployment verified
- [ ] Windows Task Scheduler deployment verified
- [ ] Configuration examples validated
- [ ] Troubleshooting guide tested
- [ ] Code review approved
- [ ] Handoff documentation delivered

---

## Appendix A: Commands Quick Reference

### Development

```bash
# Run unit tests
pytest tests/unit/ -v --cov=src

# Run integration tests
pytest tests/integration/ -v

# Run contract tests
pytest tests/contract/ -v

# Run specific worker test
pytest tests/integration/test_content_worker_e2e.py -v

# Check VRAM enforcement
python -c "from src.hardware.vram_enforcer import VRAMEnforcer; e=VRAMEnforcer(); e.enforce_budget('cuda:0')"

# Simulate scheduling
python -c "from src.scheduling.window_scheduler import WindowScheduler; s=WindowScheduler(); print(s.should_execute_now())"
```

### Deployment (Docker)

```bash
# Start workers
docker-compose up -d content-translation-worker tm-improvement-worker ollama

# View logs
docker logs -f hugo-translator-content-worker
docker logs -f hugo-translator-tm-worker

# Check status
docker ps | grep hugo-translator

# Stop workers
docker-compose stop content-translation-worker tm-improvement-worker
```

### Deployment (Windows)

```bash
# Register scheduled tasks
.\scripts\windows\schedule_content_worker.ps1
.\scripts\windows\schedule_tm_worker.ps1

# Start tasks
Start-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Start-ScheduledTask -TaskName "HugoTranslator-TMWorker"

# Check status
Get-ScheduledTask -TaskName "HugoTranslator-*"
```

### Monitoring

```bash
# Check VRAM usage
nvidia-smi --query-gpu=memory.used,memory.total --format=csv --loop=10

# Check execution count (content worker)
docker logs hugo-translator-content-worker 2>&1 | grep -c "Cycle complete: success"

# Check execution count (TM worker)
docker logs hugo-translator-tm-worker 2>&1 | grep -c "Cycle complete: success"

# Check telemetry
sqlite3 ../local-telemetry/data/telemetry.db \
  "SELECT COUNT(*) FROM translation_runs WHERE trigger_type='scheduled' AND created_at > datetime('now', '-1 day');"

# Check git commits
git log --oneline --since="24 hours ago" --grep="autonomous"

# Check TM stats
python -c "from src.tm import create_translation_memory; from pathlib import Path; tm=create_translation_memory(Path('data/tm')); print(tm.get_stats())"
```

---

## Appendix B: Key Code References

### Shared Engines
- CompositionRoot: [src/shared_engines/composition_root.py:267-461](../../src/shared_engines/composition_root.py)
- TelemetryEngine: [src/shared_engines/telemetry_engine.py:21-172](../../src/shared_engines/telemetry_engine.py)
- CommitEngine: [src/shared_engines/commit_engine.py:22-243](../../src/shared_engines/commit_engine.py)
- LimitingEngine: [src/shared_engines/limiting_engine.py:39-387](../../src/shared_engines/limiting_engine.py)

### Hardware Management
- GPUManager: [src/hardware/gpu_manager.py:84-725](../../src/hardware/gpu_manager.py)
- ResourceMonitor: [src/benchmarking/resource_monitor.py](../../src/benchmarking/resource_monitor.py)

### Translation & TM
- TranslationEngine: [src/translation_engine/engine.py:1-150](../../src/translation_engine/engine.py)
- TranslationMemory: [src/tm/](../../src/tm/)
- GitCommitHelper: [src/observability/git_commit_helper.py:1-100](../../src/observability/git_commit_helper.py)

### Existing Scheduler
- SweepScheduler: [src/orchestrator/scheduler.py:35-100](../../src/orchestrator/scheduler.py)

---

## Appendix C: Configuration Schema

### Autonomous Workers Config

```yaml
# config/global.yaml (ADD)
autonomous_workers:
  # Global settings
  enabled: true
  poll_interval_seconds: 300  # 5 minutes

  # Worker-specific settings
  workers:
    content_translation:
      enabled: true
      schedule:
        window_start: "10:00"  # Pacific Time
        window_end: "22:00"
        timezone: "America/Los_Angeles"
        frequency_per_day: [4, 5]  # Min, max
        jitter_minutes: 15
      content_roots:
        - path: "../products.aspose.net/content"
          site_id: "products.aspose.net"
          target_langs: ["de", "fr", "es", "ja", "zh"]
        - path: "../docs.aspose.net/content"
          site_id: "docs.aspose.net"
          target_langs: ["de", "fr", "es", "ja", "zh"]
      resources:
        vram_budget_percent: 0.60
        required_memory_mb: 2048
        required_gpu_memory_mb: 4096
      git:
        enabled: true
        auto_push: true
        commit_only_touched: true
      telemetry:
        enabled: true
        trigger_type: "scheduled"

    tm_improvement:
      enabled: true
      schedule:
        window_start: "10:00"
        window_end: "22:00"
        timezone: "America/Los_Angeles"
        frequency_per_day: [4, 5]
        jitter_minutes: 15
      tm:
        root: "data/tm"
        max_candidates_per_cycle: 100
        quality_threshold: 0.80
      llm:
        backend: "ollama"  # ollama, claude, gpt4
        ollama:
          base_url: "http://localhost:11434"
          model_id: "llama2:7b"
          temperature: 0.3
          fallback_to_api: true
        claude:
          model_id: "claude-sonnet-4-5"
          api_key_env: "ANTHROPIC_API_KEY"
          temperature: 0.3
        gpt4:
          model_id: "gpt-4-turbo"
          api_key_env: "OPENAI_API_KEY"
          temperature: 0.3
      resources:
        vram_budget_percent: 0.60
        required_memory_mb: 2048
        required_gpu_memory_mb: 4096
      telemetry:
        enabled: true
        trigger_type: "scheduled"
```

---

**END OF IMPLEMENTATION PLAN**

For questions or clarifications, refer to:
- Master Plan: [plans/autonomous_workers/MASTER_PLAN.md](../../plans/autonomous_workers/MASTER_PLAN.md)
- System Spec: [specs/autonomous_workers/SYSTEM_SPEC.md](../../specs/autonomous_workers/SYSTEM_SPEC.md)
- Compatibility Spec: [specs/autonomous_workers/COMPATIBILITY_SPEC.md](../../specs/autonomous_workers/COMPATIBILITY_SPEC.md)
