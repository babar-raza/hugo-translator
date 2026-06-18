# Autonomous Operation Guide

📋 Reported: This guide describes the agentic autonomous workflow modules as implemented in the codebase. Features are designed to be safe-by-default with `enabled: false` and `dry_run: true` in all configurations. Runtime behavior should be independently verified before enabling in production.

**Audience:** Site Operators, System Contributors
**Last Updated:** 2026-06-17
**Status:** 📋 Reported (code-verified, not runtime-verified)

---

## Overview

The Hugo Translator includes an optional autonomous workflow layer that allows the system to make limited decisions without direct human input. All autonomous features are **disabled by default** and must be explicitly enabled with careful review.

The autonomous system consists of seven modules that operate as an advisory layer above the core translation workers. They inspect state, select next actions, and record decisions — but do not take destructive actions unilaterally.

**Default safety posture for all modules:**
- `enabled: false` (must be explicitly set to `true` to activate)
- `dry_run: true` (decisions are logged but not executed)
- All decisions written to audit logs before any action is taken

---

## Module Reference

### 1. Supervisor Loop (`src/workers/supervisor_loop.py`)

📋 Reported: Implements an inspect-decide-execute-verify advisory loop above the worker orchestrator.

**What it does:**
- Inspects current system state (continuation state, task queue, run signals)
- Selects the next decision: `PROCEED`, `SKIP`, `BLOCK`, `CIRCUIT_BREAK`, or `RESUME`
- Writes decisions to `data/logs/supervisor_events.jsonl` — does NOT directly launch workers
- The worker orchestrator consumes these decisions via its trigger evaluation system

**Key design constraint:** The supervisor is advisory — it writes recommendations, not commands. It does not bypass CI gates, modify source code, or make irreversible changes.

**Running:**
```bash
# Single decision cycle (dry-run)
python -m src.workers.supervisor_loop --once --dry-run

# Inspect current state without taking action
python -m src.workers.supervisor_loop --once
```

**Output:** `data/logs/supervisor_events.jsonl` — one JSON event per line

**Decisions the supervisor can make:**
| Decision | Meaning |
|----------|---------|
| `PROCEED` | Continue with next scheduled work |
| `SKIP` | Skip current item (not ready or blocked) |
| `BLOCK` | Stop processing; requires human review |
| `CIRCUIT_BREAK` | Emergency stop; halt all work |
| `RESUME` | Resume from a previous INTERRUPTED state |

---

### 2. Task Queue (`src/workers/task_queue.py`)

📋 Reported: A structured, programmatic alternative to the prose-based `TASK_BACKLOG.md`.

**What it does:**
- Maintains a JSONL-format task backlog at `data/task_queue.jsonl`
- Supports priority levels: P0 (critical), P1 (high), P2 (medium), P3 (low)
- Status lifecycle: `pending` → `in_progress` → `completed` | `blocked`
- Provides `get_next_task()`, `queue_summary()`, and task update functions

**Integration status:** 📋 Reported as standalone utility, not yet consumed by `worker_orchestrator`. Integration deferred pending supervisor loop stabilization (see `task_queue.py` module docstring, TC-AGT-22).

**Format (one task per line in `data/task_queue.jsonl`):**
```json
{
    "task_id": "TC-AGT-01",
    "title": "Example task",
    "lane": "A",
    "priority": "P1",
    "status": "pending",
    "horizon": 1,
    "depends_on": [],
    "blockers": []
}
```

---

### 3. Continuation State (`src/workers/continuation_state.py`)

📋 Reported: Tracks progress across sessions so the worker can resume where it left off.

**What it does:**
- Maintains a state machine at `data/logs/continuation_state.json`
- Tracks: sites processed, files succeeded/failed, pending work, blockers, suggested next action
- On worker startup: reads state to determine what to prioritize
- Supports circuit-breaking when repeated failures indicate a systemic problem

**State lifecycle:**
```
IDLE → RUNNING → COMPLETED | FAILED | INTERRUPTED
                INTERRUPTED → RUNNING (resume via --resume flag)
```

**Key functions:**
- `load_state()` — returns current phase, run_id, pending work
- `should_resume()` — returns True if previous run was INTERRUPTED
- `is_circuit_broken()` — returns True if circuit breaker tripped
- `save_state()` — atomically writes updated state

**CLI integration:** Pass `--resume` flag to `autonomous_content_translation_worker` to activate resume logic.

---

### 4. Run Signal Emitter (`src/observability/run_signal_emitter.py`)

📋 Reported: Emits structured JSON signals describing run outcomes.

**What it does:**
- Produces `RunSignal` Pydantic objects describing translation run outcomes
- Signal verdicts: `CLEAN`, `DEGRADED`, `FAILED`
- Captures: file stats, validator stats, LLM usage, blockers encountered
- Output: written to `data/logs/run_signals.jsonl` or consumed by supervisor loop

**Signal structure:**
```python
RunSignal(
    status=RunStatus.CLEAN,         # CLEAN | DEGRADED | FAILED
    verdict=RunVerdict.ACCEPT,      # ACCEPT | REJECT | REVIEW
    production_safety=ProductionSafety.SAFE,
    file_stats=FileStats(total=10, success=9, failed=1),
    validator_stats=ValidatorStats(...),
    llm_usage=LLMUsage(dry_run=True, ...),
    blockers=[],
)
```

**Default:** `dry_run=True` on `LLMUsage` — LLM calls are logged but not executed unless explicitly enabled.

---

### 5. Blocker Classifier (`src/observability/blocker_classifier.py`)

📋 Reported: Classifies run failures into categories for root-cause analysis.

**What it does:**
- Takes a failure context (error message, logs) and returns a classification
- Classification categories: `TM_CORRUPTION`, `MODEL_FAILURE`, `VALIDATION_STORM`, `NETWORK_ERROR`, `CONFIG_DRIFT`, `UNKNOWN`
- Feeds into supervisor loop's BLOCK/CIRCUIT_BREAK decisions

**Default:** Does not make autonomous remediation decisions — provides classification only.

---

### 6. Contradiction Detector (`src/observability/contradiction_detector.py`)

📋 Reported: Detects configuration drift and contradictory settings.

**What it does:**
- Audits `config/global.yaml` and active runtime configuration for conflicts
- Detects: `enabled: true` committed to config (blocked by CI guardian), dry_run inconsistencies, validation mode conflicts
- Reports contradictions without taking action

**CLI:**
```bash
python -m src.observability.contradiction_detector
```

---

### 7. Run Summarizer (`src/observability/run_summarizer.py`)

📋 Reported: Generates human-readable summaries of translation run outcomes.

**What it does:**
- Reads `data/logs/run_signals.jsonl` and `data/logs/continuation_state.json`
- Produces a structured summary: files processed, quality metrics, blockers, recommended next action
- Output can be consumed by supervisor loop for decision-making

---

## Configuration

All agentic features are configured in `config/global.yaml`. The default is fully disabled:

```yaml
# config/global.yaml (defaults)
agentic:
  supervisor_loop:
    enabled: false
    dry_run: true
    max_circuit_breaker_trips: 3
  task_queue:
    enabled: false
    queue_file: data/task_queue.jsonl
  continuation_state:
    enabled: false
    state_file: data/logs/continuation_state.json
  blocker_classifier:
    enabled: false
    dry_run: true
```

**Warning:** Do not set `enabled: true` in committed configuration. The CI guardian (`release_gate.yml`, governance-check job) blocks any committed `enabled: true` in `agent_metrics` — the same policy applies to agentic modules. Enable only via runtime overrides during controlled testing.

---

## Audit Logs

All autonomous decisions are logged before any action:

| Log File | Content |
|----------|---------|
| `data/logs/supervisor_events.jsonl` | Supervisor decisions (one JSON per line) |
| `data/logs/continuation_state.json` | Current run phase and progress |
| `data/logs/run_signals.jsonl` | Run outcome signals |
| `data/task_queue.jsonl` | Programmatic task backlog |

---

## Safety Model

1. **Advisory only:** No module directly modifies files, launches processes, or triggers CI.
2. **Dry-run default:** All LLM calls and HTTP POSTs are logged but not executed by default.
3. **Circuit breaker:** After configurable failures, the supervisor emits CIRCUIT_BREAK and halts.
4. **Human-gated enablement:** Requires explicit `enabled: true` override (not committed to config).
5. **Full audit trail:** Every decision is timestamped and appended to JSONL logs before execution.

---

## Related Documentation

- [Agent Metrics API](../observability/agent-metrics-api.md) — External metrics posting (separate from agentic workflow)
- [Continuation State Tests](../../tests/unit/workers/test_continuation_state.py) — Behavior specification
- [Supervisor Loop Tests](../../tests/unit/workers/test_supervisor_loop.py) — Decision cycle specification
- [Task Queue Tests](../../tests/unit/workers/test_task_queue.py) — Queue operations
- [Run Signal Emitter Tests](../../tests/unit/observability/test_run_signal_emitter.py)
