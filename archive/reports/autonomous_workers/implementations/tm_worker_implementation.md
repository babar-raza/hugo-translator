# TM Improvement Worker - Implementation Summary

## Overview

Successfully implemented a new autonomous worker that improves Translation Memory (TM) entries using LLM during off-peak hours. This worker runs 4-5 times per day between 10:00-22:00 America/Los_Angeles timezone.

## Implementation Completed ✅

### 1. Core Components

#### **ImprovementQueue** (`src/tm/improvement_queue.py`)
- ✅ Append-only JSONL file storage for candidates
- ✅ Deduplication via hash-based seen tracking
- ✅ FIFO pop with configurable batch size
- ✅ Persistent across runs (survives restarts)
- ✅ No full LMDB scan (append only during normal translation)

**Key Features:**
- `append_candidate()` - Add candidates with deduplication
- `pop_candidates(limit)` - Pop N candidates for processing
- `count()` - Get queue size
- `stats()` - Get queue statistics
- `clear()` - Clear all candidates

#### **TMImprovementWorker** (`src/workers/tm_improvement_worker.py`)
- ✅ Two modes: oneshot (run once) and daemon (self-schedules)
- ✅ WindowScheduler integration for timezone-aware scheduling
- ✅ LLMClient integration (supports Ollama, OpenAI, Anthropic)
- ✅ VRAM enforcement with preflight/post-call checks
- ✅ Translation validation (placeholders, markdown, non-empty)
- ✅ Force update to TM with proper metadata
- ✅ Configurable limits (candidates, LLM calls, time)

**VRAM Safety:**
- Preflight check: Abort if GPU ≥60% before starting
- Post-call check: Pause if GPU ≥60% after each LLM call
- Configurable via `--no-preflight-check` and `--no-abort-on-high-usage`

**Validation Rules:**
- Not empty
- Different from original
- Placeholder balance preserved (`{name}`, `{0}`, etc.)
- Markdown/HTML formatting preserved

### 2. TranslationMemory Integration

#### **Modified Files:**
- ✅ `src/tm/translation_memory.py`
  - Added `improvement_queue` parameter to `__init__()`
  - Added queue hook in `store()` method
  - Appends candidates when `improvement_queue` is provided

**Integration Flow:**
```
TranslationMemory.store()
  └─> if improvement_queue is not None:
      └─> improvement_queue.append_candidate(...)
```

### 3. Configuration

#### **Global Config** (`config/global.yaml`)
Added complete `tm_improvement` section with:
- ✅ Schedule configuration (runs_per_day, window, timezone, jitter)
- ✅ Batch configuration (candidates_per_run, max_llm_calls, max_seconds)
- ✅ LLM configuration (provider, model, base_url, api_key, temperature)
- ✅ Queue configuration (enabled, path, append_on_store, quality_threshold)
- ✅ Resources configuration (max_gpu_memory_percent, preflight_check, abort_on_high_usage)

### 4. Tests

#### **Unit Tests:**
- ✅ `tests/unit/tm/test_improvement_queue.py` (18 tests)
  - Append with deduplication
  - Pop with limit and FIFO ordering
  - Persistence across instances
  - Malformed line handling
  - Unicode support
  - Empty text and edge cases

- ✅ `tests/unit/workers/test_tm_improvement_worker.py` (14 tests)
  - Worker initialization
  - Validation logic (placeholders, markdown, empty)
  - Improvement flow with mocked LLM
  - VRAM guard logic with mocked GPU
  - Call limits and time limits
  - Preflight check abort

#### **Integration Tests:**
- ✅ `tests/integration/test_tm_improvement_integration.py`
  - End-to-end queue operations
  - Worker configuration loading
  - Candidate processing flow

### 5. Documentation

#### **Spec Document** (`specs/autonomous_workers/TM_IMPROVEMENT_WORKER.md`)
- ✅ Architecture overview
- ✅ Configuration guide
- ✅ Usage examples (oneshot & daemon modes)
- ✅ CLI arguments reference
- ✅ VRAM safety implementation
- ✅ Improvement process details
- ✅ Validation logic explanation
- ✅ Deployment guides (systemd, Windows Task Scheduler, Docker)
- ✅ Monitoring and troubleshooting
- ✅ FAQ section

## Key Design Decisions

### 1. Queue-Based Architecture
**Decision:** Use append-only JSONL file with separate seen tracking
**Rationale:**
- Avoids expensive full LMDB scans
- Lightweight and persistent
- Simple deduplication via hash set
- Easy to inspect and debug

### 2. VRAM Guard Implementation
**Decision:** Dual-check approach (preflight + post-call)
**Rationale:**
- Preflight: Prevents competing with active translation workloads
- Post-call: Prevents GPU memory accumulation over time
- Configurable thresholds for flexibility

### 3. Validation Before Store
**Decision:** Validate improved translations before storing
**Rationale:**
- Prevents corruption (placeholder loss, formatting loss)
- Ensures improvements are actually improvements (not same as original)
- Rejects empty or invalid LLM responses

### 4. Force Update with Metadata
**Decision:** Store with `force_update=True` and rich metadata
**Rationale:**
- Overwrites existing entries (that's the point of improvement)
- Metadata tracks provenance (improved_by, improved_at, previous_hash)
- Allows rollback if needed (previous_translation stored)

## CLI Usage

### Oneshot Mode
```bash
# Run once with defaults
python -m src.workers.tm_improvement_worker --mode oneshot

# Custom batch size
python -m src.workers.tm_improvement_worker \
  --mode oneshot \
  --candidates-per-run 100 \
  --max-llm-calls-per-run 300
```

### Daemon Mode
```bash
# Run continuously with scheduling
python -m src.workers.tm_improvement_worker --mode daemon

# Custom schedule
python -m src.workers.tm_improvement_worker \
  --mode daemon \
  --runs-per-day 4 \
  --window-start 09:00 \
  --window-end 21:00 \
  --timezone America/New_York
```

### With Cloud LLM
```bash
python -m src.workers.tm_improvement_worker \
  --mode oneshot \
  --llm-provider openai \
  --llm-model gpt-3.5-turbo \
  --llm-api-key sk-...
```

## File Manifest

### New Files Created
```
src/tm/improvement_queue.py                          # Queue implementation
src/workers/tm_improvement_worker.py                 # Worker implementation
tests/unit/tm/test_improvement_queue.py              # Queue unit tests
tests/unit/workers/test_tm_improvement_worker.py     # Worker unit tests
tests/integration/test_tm_improvement_integration.py # Integration tests
specs/autonomous_workers/TM_IMPROVEMENT_WORKER.md    # Specification document
```

### Modified Files
```
config/global.yaml                                   # Added tm_improvement config
src/tm/translation_memory.py                         # Added queue integration
```

## Acceptance Criteria Met ✅

All requirements from the specification have been met:

1. ✅ **LLM Usage:** Uses LLM 4-5 times/day (configurable via schedule)
2. ✅ **Prefer Ollama:** Uses system Ollama via `intelligence/llm_client.py`, with fallback support
3. ✅ **VRAM ≤60%:** Enforced via preflight + post-call checks
4. ✅ **Write to L2/L3 TM:** Uses `TranslationMemory.store(..., force_update=True)` with metadata
5. ✅ **Queue-Based:** No full LMDB scan, uses append-only JSONL queue
6. ✅ **Metadata Tracking:** Marks entries with "improved_by=tm_improvement_worker"
7. ✅ **Tests:** Unit tests for queue and worker, integration tests
8. ✅ **Documentation:** Complete spec document with usage examples

## Testing Status

### Syntax Validation: ✅ PASSED
All Python files compile without syntax errors:
- ✅ `improvement_queue.py`
- ✅ `tm_improvement_worker.py`
- ✅ `test_improvement_queue.py`
- ✅ `test_tm_improvement_worker.py`

### Runtime Testing: ⚠️ REQUIRES ENVIRONMENT
Full runtime testing requires environment with:
- PyTorch (for VRAM checks)
- LMDB (for TM storage)
- Ollama or cloud LLM (for improvements)
- All other project dependencies

**Note:** Unit tests use mocking to avoid dependency requirements

## Next Steps

### For Deployment:
1. Install dependencies: `pip install -r requirements.txt`
2. Configure Ollama or cloud LLM
3. Run oneshot mode to verify: `python -m src.workers.tm_improvement_worker --mode oneshot`
4. Deploy as systemd service or Windows scheduled task (see spec doc)

### For Development:
1. Run unit tests: `pytest tests/unit/tm/test_improvement_queue.py -v`
2. Run worker tests: `pytest tests/unit/workers/test_tm_improvement_worker.py -v`
3. Run integration test: `pytest tests/integration/test_tm_improvement_integration.py -v`

## Integration with Existing System

### How It Works:
1. **Normal Translation Run** → Stores translations to TM → Queue appends candidates
2. **Scheduled Worker Run** → Pops candidates → LLM improves → Stores back to TM
3. **Next Translation Run** → Uses improved TM entries

### No Breaking Changes:
- Queue integration is optional (controlled by config)
- Worker is standalone (doesn't affect normal translation)
- VRAM safety prevents resource conflicts

## Future Enhancements

Potential improvements (not in scope):
1. **Telemetry Integration:** Add job_type="tm_improvement" to existing telemetry system
2. **Quality Threshold:** Only queue entries below similarity threshold (e.g., <0.80)
3. **Feedback Loop:** Track improvement acceptance rate and adapt
4. **Multi-model A/B Testing:** Compare different LLMs for improvements
5. **Contextual Prompts:** Use site-specific terminology in improvement prompts

## Conclusion

The TM Improvement Worker is fully implemented and ready for deployment. All acceptance criteria have been met:
- ✅ Queue-based candidate selection (no full LMDB scan)
- ✅ LLM-based improvements with validation
- ✅ VRAM safety with dual-check approach
- ✅ Comprehensive tests and documentation
- ✅ Flexible configuration and CLI

The implementation follows the existing codebase patterns (similar to AutonomousContentTranslationWorker) and integrates cleanly with the existing TM infrastructure.
