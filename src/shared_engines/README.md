# Shared Engines

**Purpose:** Unified interface layer enabling both manual CLI and autonomous worker execution modes.

---

## Overview

The Shared Engines architecture provides 8 core engines that abstract away implementation details and enable dependency injection for different execution contexts:

- **Manual CLI Mode:** User runs `translate-hugo` command directly on Windows with CUDA GPU
- **Autonomous Worker Mode:** Docker containers poll job queues (Redis) and execute jobs with CPU or GPU

**Key Principle:** Same translation logic, different execution runtime.

---

## The 8 Engines

### 1. Translation Engine
**Purpose:** Unified translation interface with pluggable backends
**Backends:**
- `MTBackend`: Machine Translation (M2M100, NLLB) for offline GPU execution
- `LLMBackend`: Large Language Models (Claude, GPT-4) for API-based translation

**Why:** Enables future migration from local MT models to LLM APIs without changing worker code.

### 2. Telemetry Engine
**Purpose:** Event logging and metrics collection
**Backends:**
- Local-Telemetry DB (SQLite) for operational events
- BenchmarkDB (SQLite) for performance metrics

**Why:** Unified observability across manual runs and worker pools.

### 3. Job Engine
**Purpose:** Job queue abstraction
**Backends:**
- `JobQueue`: In-memory FIFO queue for manual mode
- `RedisJobQueue`: Redis-backed queue for distributed workers

**Why:** Manual CLI doesn't need Redis; workers do. Same interface for both.

### 4. Profile Engine
**Purpose:** Site profile and configuration resolution
**Features:**
- Loads site-specific config from `config/site_profiles/*.yaml`
- Resolves precedence: site > global > default
- Lists available sites

**Why:** Centralizes configuration logic across all execution modes.

### 5. Logging Engine
**Purpose:** Structured NDJSON logging
**Features:**
- Correlation IDs for distributed tracing
- Context binding for worker metadata
- Log levels: DEBUG, INFO, WARNING, ERROR

**Why:** Consistent log format for parsing and analysis (Elasticsearch, Loki).

### 6. Commit Engine
**Purpose:** Automated git commit workflow
**Features:**
- Auto-commits translated files to git
- Generates semantic commit messages
- Optional auto-push to remote
- Respects `git_commit.enabled` config

**Why:** Enables versioning and rollback for autonomous workers.

### 7. Limiting Engine
**Purpose:** Resource constraint enforcement
**Monitors:**
- GPU memory (VRAM)
- CPU utilization
- RAM usage

**Why:** Prevents OOM crashes and ensures fair resource sharing among workers.

### 8. Healing Engine
**Purpose:** Retry and recovery logic
**Handles:**
- Out-of-memory errors (reduce batch size)
- Transient errors (exponential backoff)
- Validation failures (retry with different settings)

**Why:** Autonomous workers must recover from failures without human intervention.

---

## Composition Root

The `CompositionRoot` is the single entry point for creating all 8 engines from configuration:

```python
from shared_engines.composition_root import CompositionRoot

# Create engines from config
engines = CompositionRoot.create_from_config(
    config_path="config/global.yaml",
    mode="auto"  # or "manual", "worker-cpu", "worker-gpu"
)

# Access engines
engines.translation.translate_file(...)
engines.telemetry.emit("event", {...})
engines.logging.info("message", correlation_id="...")
engines.commit.commit_if_enabled(...)
```

**Dependency Order:**
1. ProfileEngine (loads config, needed by others)
2. LoggingEngine (for debug output during setup)
3. TelemetryEngine (for event tracking)
4. JobEngine (requires ProfileEngine for backend selection)
5. LimitingEngine (requires ProfileEngine for thresholds)
6. HealingEngine (requires ProfileEngine for retry config)
7. CommitEngine (requires ProfileEngine for git settings)
8. TranslationEngine (depends on all others)

---

## Design Principles

### 1. Backend Abstraction
Each engine has an interface + multiple implementations:
- `ITranslationBackend` → `MTBackend`, `LLMBackend`
- `IJobQueue` → `JobQueue`, `RedisJobQueue`

**Why:** Swap implementations without changing calling code.

### 2. Configuration-Driven
All engine settings come from `config/global.yaml` or ENV vars:
- Paths: Log files, DB locations
- Limits: GPU memory, batch size
- Backends: Which queue, which translation backend

**Why:** No hard-coded paths or settings in code.

### 3. Graceful Degradation
Optional features fail gracefully:
- BenchmarkDB unavailable? → Log warning, continue
- Redis unavailable? → Fall back to in-memory queue
- GPU unavailable? → Fall back to CPU

**Why:** Autonomous workers shouldn't crash on non-critical failures.

### 4. Testability
All engines use dependency injection:
- Mock backends in tests (no real DB/Redis/GPU needed)
- Unit tests verify logic without I/O
- Integration tests verify real backend integration

**Why:** Fast, reliable test suite.

---

## Migration Strategy

**Phase 1:** Create engines (non-breaking)
- Implement all 8 engines
- Create CompositionRoot
- **CLI still uses old code paths**

**Phase 2:** Parallel execution (non-breaking)
- CLI calls CompositionRoot
- Engines used for telemetry/logging only
- **Translation still uses old TranslationEngine directly**

**Phase 3:** Full migration (breaking for internal code, not CLI)
- CLI uses `engines.translation` instead of direct instantiation
- Remove old code paths
- **Golden tests verify no behavior change**

**Phase 4:** New features
- Add `--backend llm` CLI flag
- Enable worker orchestration
- **New capabilities, backward compatible CLI**

---

## File Structure

```
src/shared_engines/
├── __init__.py                   # Package exports
├── README.md                     # This file
├── composition_root.py           # Engine factory
├── telemetry_engine.py           # Telemetry abstraction
├── job_engine.py                 # Job queue abstraction
├── profile_engine.py             # Config resolution
├── logging_engine.py             # Structured logging
├── commit_engine.py              # Git automation
├── limiting_engine.py            # Resource constraints
└── healing_engine.py             # Retry logic

src/translation_engine/backends/
├── __init__.py
├── interface.py                  # ITranslationBackend
├── mt_backend.py                 # M2M100, NLLB
└── llm_backend.py                # Claude, GPT-4

tests/unit/shared_engines/
├── test_composition_root.py
├── test_telemetry_engine.py
├── test_job_engine.py
├── test_profile_engine.py
├── test_logging_engine.py
├── test_commit_engine.py
├── test_limiting_engine.py
└── test_healing_engine.py
```

---

## Status

**Current Phase:** Phase 1 - Task P1-01 (Create Directory Structure)
**Implementation Status:** 🔨 IN PROGRESS

| Engine | Status | Implementation Task |
|--------|--------|---------------------|
| Directory Structure | ✅ DONE | P1-01 |
| TranslationEngine Backend | 🔴 TODO | P1-02 |
| TelemetryEngine | 🔴 TODO | P1-03 |
| JobEngine | 🔴 TODO | P1-04 |
| ProfileEngine | 🔴 TODO | P1-05 |
| LoggingEngine | 🔴 TODO | P1-06 |
| CommitEngine | 🔴 TODO | P1-07 |
| LimitingEngine | 🔴 TODO | P1-08 |
| HealingEngine | 🔴 TODO | P1-09 |
| CompositionRoot | 🔴 TODO | P1-10 |
| CLI Integration (Phase 1) | 🔴 TODO | P1-11 |
| CLI Integration (Phase 2) | 🔴 TODO | P1-12 |

---

## References

- **Master Plan:** `plans/autonomous_workers/MASTER_PLAN.md`
- **Task Cards:** `plans/autonomous_workers/TASKCARDS.md`
- **Compatibility Spec:** `specs/autonomous_workers/COMPATIBILITY_SPEC.md`
- **System Spec:** `specs/autonomous_workers/SYSTEM_SPEC.md`
