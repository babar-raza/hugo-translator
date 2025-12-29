# Core Invariants - Hugo Translation System

**Purpose:** Single source of truth for system-wide invariants
**Status:** 🔒 LOCKED - Changes require spec review + contract test updates
**Last Updated:** 2025-12-26

---

## Overview

This document consolidates all cross-cutting invariants from feature specifications into a single canonical reference. Each invariant is:
- **Evidence-backed** with exact code locations
- **Contract-tested** with verification status
- **Cross-referenced** to feature specs

**Hierarchy of Truth:**
1. This document defines WHAT must be true
2. Contract tests verify it IS true
3. Feature specs explain WHY it's true

---

## INV-001: Multi-Language Subprocess Isolation

**Statement:** When translating to multiple target languages, each language MUST execute in a separate subprocess to prevent model state contamination.

### Specification

**Trigger Condition:**
```python
IF len(target_langs) > 1 THEN
    spawn_subprocess_per_language()
ELSE
    translate_in_current_process()
```

**Rationale:**
- M2M100 model maintains internal state (attention weights, token embeddings)
- Sequential multi-language translation in same process causes cross-language contamination
- Subprocess isolation ensures clean model state per language

**Evidence:**
- File: [src/cli.py](../src/cli.py)
- Lines: 1090-1178 (subprocess spawning logic)
- Lines: 1095-1099 (multi-language detection)
```python
if len(target_langs) > 1 and not getattr(args, '_single_lang_mode', False):
    logger.info(
        f"Multi-language translation detected ({len(target_langs)} languages). "
        f"Processing each language in separate subprocess to prevent state contamination..."
    )
```

**Exceptions:** NONE (critical safety invariant)

**Contract Test:** `tests/contract/test_cli_subprocess_isolation.py` (CONTRACT-001)
**Contract Status:** scaffolded
**Feature Spec:** [CLI-001: Main Translation Command](features/cli-001-main-translate.md#invariants)

---

## INV-002: Atomic File Writes

**Statement:** All translated output files MUST be written atomically using temp file + rename pattern to prevent corruption on crash or interruption.

### Specification

**Write Pattern:**
```python
1. Write to temporary file: {output_path}.tmp.{pid}
2. Fsync temporary file (flush to disk)
3. Atomic rename: temp → final path
4. On exception: Delete temp file, do not touch final path
```

**Guarantees:**
- Final file is EITHER old version OR new version (never partial)
- Crash during write leaves final file unchanged
- No corrupted/truncated output files

**Evidence:**
- File: [src/utils/atomic_write.py](../src/utils/atomic_write.py) (full file)
- Usage: [src/translation_engine/engine.py](../src/translation_engine/engine.py) (translate_file method)
- Implementation: Temp file + fsync + os.replace()

**Exceptions:** NONE (all output writes must be atomic)

**Contract Test:** `tests/contract/test_atomic_writes.py` (CONTRACT-002)
**Contract Status:** scaffolded
**Feature Spec:** [API-001: translate_file Method](features/api-001-translate-file.md#invariants)

---

## INV-003: Translation Memory Lookup Order

**Statement:** Translation Memory lookups MUST follow L1 → L2 → L3 cascade order, stopping at first hit.

### Specification

**Lookup Cascade:**
```python
def lookup(site_id, src_lang, tgt_lang, text):
    # L1: In-memory LRU cache (fastest, ephemeral)
    if match := l1_cache.exact_lookup(...):
        return match

    # L2: LMDB persistent store (fast, exact match)
    if match := l2_persistent.exact_lookup(...):
        l1_cache.store(match)  # Promote to L1
        return match

    # L3: FAISS semantic search (slow, fuzzy match)
    if match := l3_semantic.semantic_search(..., threshold=0.85):
        l2_persistent.store(match)  # Promote to L2
        l1_cache.store(match)       # Promote to L1
        return match

    return None  # Cache miss, translate with model
```

**Rationale:**
- Performance: L1 (< 1μs) → L2 (< 1ms) → L3 (< 100ms)
- Accuracy: L1/L2 exact match → L3 fuzzy match (threshold-based)
- Cache warming: Promote hits up the hierarchy

**Evidence:**
- File: [src/tm/__init__.py](../src/tm/__init__.py) (TranslationMemory.lookup method)
- L1: [src/tm/l1_cache.py](../src/tm/l1_cache.py)
- L2: [src/tm/l2_persistent.py](../src/tm/l2_persistent.py)
- L3: [src/tm/l3_semantic.py](../src/tm/l3_semantic.py)

**Performance Contract:**
- L3 MUST NOT be called if L1 or L2 hit
- L2 MUST NOT be called if L1 hit

**Exceptions:**
- If L3 disabled/unavailable → fallback to L1+L2 only
- If `--no-cache` flag set → skip all TM layers

**Contract Test:** `tests/contract/test_tm_lookup_order.py` (CONTRACT-003)
**Contract Status:** scaffolded
**Feature Specs:**
- [TM-001: L1 In-Memory Cache](features/tm-001-l1-cache.md)
- [TM-002: L2 Persistent Store](features/tm-002-l2-persistent-store.md)
- [TM-003: L3 Semantic Search](features/tm-003-l3-semantic-search.md)

---

## INV-004: Critical Validators Always REJECT

**Statement:** Errors from critical validators (PlaceholderValidator, CodeBlockValidator, LinkValidator) MUST cause immediate REJECT decision, bypassing retry logic and error thresholds.

### Specification

**Critical Validators:**
```python
CRITICAL_VALIDATORS = {
    "PlaceholderValidator",    # {{CODE_1}}, {{LINK_2}} preservation
    "CodeBlockValidator",       # ```python ... ``` preservation
    "LinkValidator",            # [text](url) syntax preservation
}
```

**Decision Logic:**
```python
def decide(validation_result, retry_count):
    # Step 1: Check critical validators FIRST
    for issue in validation_result.errors:
        if issue.validator_name in CRITICAL_VALIDATORS:
            return REJECT, f"Critical {issue.validator_name} failed"

    # Step 2: Standard error threshold checks
    if error_count >= reject_on_error_count:
        return REJECT, "Error threshold exceeded"

    # Step 3: Retry logic (if budget available)
    # ...
```

**Bypass Rules:**
- Critical failures bypass `reject_on_error_count` threshold
- Critical failures bypass retry logic (no retry attempts)
- Critical failures bypass `accept_after_max_retries` setting
- Critical failures apply in ALL modes (strict, normal, lenient)

**Rationale:**
- Syntactic corruption (missing placeholder, broken code fence) is non-negotiable
- Retrying won't fix structural errors (model can't guess missing syntax)
- Corrupted output breaks downstream rendering (Hugo, markdown parsers)

**Evidence:**
- File: [src/translation_engine/validation/decision_engine.py](../src/translation_engine/validation/decision_engine.py)
- Lines: 59-63 (CRITICAL_VALIDATORS set definition)
- Lines: 196-210 (_check_critical_failure method)
- Comment line 9: "REJECT if critical validator failed"

**Exceptions:** NONE (critical validators are hardcoded, non-configurable)

**Contract Test:** `tests/contract/test_validation_critical.py` (CONTRACT-004)
**Contract Status:** ready_to_run
**Feature Specs:**
- [VAL-001: Validation Decision Engine](features/val-001-decision-engine.md#invariants)
- [VAL-002: Critical Validators](features/val-002-critical-validators.md#invariants)

---

## INV-005: Validation Mode CLI Override

**Statement:** CLI validation flags (`--strict`, `--lenient`, `--no-validation`) MUST override site profile validation settings.

### Specification

**Override Precedence:**
```
CLI flags > Site profile config > Global defaults
```

**Override Logic:**
```python
if args.no_validation:
    enable_validation = False
elif args.strict:
    validation_mode = "strict"
    reject_on_error_count = 1
elif args.lenient:
    validation_mode = "lenient"
    reject_on_error_count = 5
else:
    # Use site profile settings
    validation_mode = site_profile.validation_mode
    reject_on_error_count = site_profile.reject_on_error_count
```

**Evidence:**
- File: [src/cli.py](../src/cli.py)
- Lines: 290-298 (validation control flags)
- Lines: 148-149 (override application)

**Exceptions:** NONE (user intent via CLI always takes precedence)

**Contract Test:** `tests/contract/test_validation_modes.py` (CONTRACT-005)
**Contract Status:** scaffolded
**Feature Spec:** [CLI-002: Validation Control Flags](features/cli-002-validation-control.md#invariants)

---

## INV-006: File Locking Prevents Concurrent Translation

**Statement:** Only one translation process per site MUST be allowed at a time, enforced by exclusive file lock.

### Specification

**Lock Mechanism:**
```python
lock_file = Path(".translation_progress/locks/{site_id}.lock")
lock = FileLock(lock_file, timeout=300.0)  # 5 minute timeout

try:
    lock.acquire(blocking=True, timeout=300)
    # Translate directory
finally:
    lock.release()  # MUST release even on exception
```

**Lock Behavior:**
- Lock is **exclusive** (only one holder at a time)
- Lock is **blocking** (wait up to timeout for lock release)
- Lock is **site-scoped** (different sites can run concurrently)
- Lock is **file-based** (works across processes and machines with shared filesystem)

**Error Handling:**
```python
if lock.acquire() fails after timeout:
    raise LockError(
        f"Another translation is in progress for site '{site_id}'. "
        f"Wait for it to complete or remove lock file: {lock_file}"
    )
```

**Rationale:**
- Prevents TM corruption from concurrent writes (LMDB single writer)
- Prevents progress file corruption
- Prevents duplicate translations (wasted resources)

**Evidence:**
- File: [src/utils/file_lock.py](../src/utils/file_lock.py) (FileLock implementation)
- Usage: [src/translation_engine/engine.py](../src/translation_engine/engine.py) lines 1790-1812 (translate_directory)
- Lock directory: `.translation_progress/locks/`

**Exceptions:**
- User can force-remove lock file manually
- Use `--force-restart` to clear lock and restart

**Contract Test:** `tests/contract/test_file_locking.py` (CONTRACT-006)
**Contract Status:** deferred_phase_2
**Feature Spec:** [API-002: translate_directory Method](features/api-002-translate-directory.md#invariants)

---

## INV-007: Resume Skips Completed Files

**Statement:** When resume is enabled, translation MUST skip files marked as completed in progress tracker.

### Specification

**Skip Logic:**
```python
if progress_tracker:
    progress_tracker.load()  # Load from .translation_progress/{site_id}/

for file in markdown_files:
    if progress_tracker and file in progress_tracker.completed_files:
        logger.info(f"Skipping {file} (already translated)")
        continue

    # Translate file
    result = translate_file(...)

    if result.success:
        progress_tracker.mark_completed(file)
        progress_tracker.save()
```

**Progress File Structure:**
```python
.translation_progress/
  {site_id}/
    progress.pkl          # Serialized ProgressTracker
    completed_files.txt   # Human-readable list (optional)
```

**Resume Behavior:**
- `--resume` (default): Load progress, skip completed
- `--no-resume`: Ignore progress, translate all
- `--force-restart`: Delete progress, translate all

**Evidence:**
- File: [src/cli.py](../src/cli.py)
- Lines: 1009-1013 (resume flag handling)
- Lines: 1380 (progress tracker creation)
- Lines: 1471, 1498, 1517, 1524 (resume instruction messages)
- ProgressTracker: [src/observability/progress.py](../src/observability/progress.py)

**Exceptions:**
- Corrupted progress file → log warning, start fresh
- `--force-restart` flag → clear progress regardless

**Contract Test:** `tests/contract/test_resume_skip_completed.py` (CONTRACT-007)
**Contract Status:** deferred_phase_2
**Feature Spec:** [CLI-005: Resume Control](features/cli-005-resume-control.md#invariants)

---

## INV-008: L2 Corruption Detection and Graceful Degradation

**Statement:** L2 persistent TM MUST detect corrupted cache entries on read and degrade gracefully by returning None (cache miss) without crashing.

### Specification

**Corruption Detection:**
```python
def exact_lookup(site_id, src_lang, tgt_lang, text):
    try:
        value_bytes = lmdb_txn.get(key)
        value_dict = json.loads(value_bytes.decode("utf-8"))
        entry = TranslationEntry.from_dict(value_dict)

        # Validate entry integrity
        if not entry.is_valid():
            logger.warning(f"Invalid cache entry detected: {key}")
            return None  # Treat as cache miss

        return entry

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.warning(f"Corrupted cache entry detected: {key}, error: {e}")
        return None  # Graceful degradation, treat as cache miss
```

**Validation Rules (TranslationEntry.is_valid):**
- Required fields non-empty: source_text, translation, site_id, src_lang, tgt_lang
- Optional fields correct type: context (str), metadata (dict), timestamp (str)

**Write Protection:**
```python
def store(entry):
    if not entry.is_valid():
        raise ValueError("Translation entry failed validation")
    # Only valid entries written to L2
```

**Rationale:**
- Disk corruption, incomplete writes, encoding errors happen
- Crashing on bad cache entry breaks entire translation
- Graceful degradation: log + return None → triggers fresh translation

**Evidence:**
- File: [src/tm/l2_persistent.py](../src/tm/l2_persistent.py)
- Lines: 144-164 (corruption detection in exact_lookup)
- Lines: 214-220 (validation before write)
- Lines: 51-78 (is_valid method)

**Exceptions:** NONE (all L2 reads must handle corruption)

**Contract Test:** `tests/contract/test_tm_l2_corruption.py` (CONTRACT-008)
**Contract Status:** deferred_phase_2
**Feature Spec:** [TM-002: L2 Persistent Store](features/tm-002-l2-persistent-store.md#invariants)

---

## INV-009: L3 Periodic Saves

**Statement:** L3 semantic TM MUST trigger periodic saves after N additions to prevent data loss on crash.

### Specification

**Save Trigger:**
```python
def add_entry(...):
    # Add embedding to FAISS index
    self.index.add(embedding)
    self.metadata.append(entry)

    self._additions_since_save += 1

    # Periodic save check
    if self.save_interval > 0 and self._additions_since_save >= self.save_interval:
        self._trigger_save()
        self._additions_since_save = 0  # Reset counter
```

**Save Modes:**
- **Synchronous** (async_save=False): Blocks add_entry until save completes
- **Asynchronous** (async_save=True): Submit to background thread, non-blocking

**Save Lock (Prevent Concurrent Saves):**
```python
if not self._save_lock.acquire(blocking=False):
    logger.debug("Periodic save skipped - already in progress")
    return False  # Skip this save, will retry on next trigger
```

**Configuration:**
```python
save_interval: int = 100    # Save every N additions (0 = disabled)
save_timeout: float = 5.0   # Max seconds for save (documentation only, not enforced)
async_save: bool = False    # Background thread vs blocking
```

**Rationale:**
- L3 index lives in memory (FAISS), lost on crash if not saved
- Saving after every add is too slow (1000s of additions)
- Periodic saves balance performance vs. data loss risk

**Evidence:**
- File: [src/tm/l3_semantic.py](../src/tm/l3_semantic.py)
- Lines: 227-241 (periodic save trigger in add_entry)
- Lines: 243-298 (_trigger_save and _do_save implementation)
- Lines: 59-80 (initialization with save_interval config)

**Exceptions:**
- save_interval=0 → periodic saves disabled (only save on shutdown)
- Save failure → log error, increment save_failures, continue (don't crash)

**Contract Test:** `tests/contract/test_tm_l3_periodic_save.py` (CONTRACT-009)
**Contract Status:** deferred_phase_2
**Feature Spec:** [TM-003: L3 Semantic Search](features/tm-003-l3-semantic-search.md#invariants)

---

## Cross-Cutting Concerns

### Shutdown Sequence

**Invariant:** Graceful shutdown MUST save L3 index and progress tracker.

**Trigger:** SIGINT (Ctrl+C), SIGTERM, or clean process exit

**Sequence:**
```python
1. Signal handler receives interrupt
2. Set shutdown flag (allow current file to complete)
3. Complete in-progress file translation
4. Save L3 index to disk (blocking)
5. Save progress tracker
6. Release file lock
7. Exit with code 130 (interrupted)
```

**Evidence:**
- File: [src/cli.py](../src/cli.py) lines 867-932 (setup_unified_signal_handler)
- File: [src/observability/graceful_shutdown.py](../src/observability/graceful_shutdown.py)

**Related:** INV-009 (L3 saves), INV-007 (progress tracking)

---

### Configuration Precedence

**Invariant:** Configuration sources follow strict precedence order.

**Precedence (Highest to Lowest):**
```
1. CLI flags (--strict, --no-cache, etc.)
2. Environment variables (TM_PATH, MODEL_CACHE, etc.)
3. Site profile config (config/site_profiles/{site_id}.yaml)
4. Global config (config/global.yaml)
5. Code defaults (hardcoded fallbacks)
```

**Evidence:**
- Config loading: [src/config/config_service.py](../src/config/config_service.py)
- CLI overrides: [src/cli.py](../src/cli.py) lines 148-202

**Related:** INV-005 (validation mode override)

---

## Verification Summary

| Invariant | Contract Test | Status | Priority |
|-----------|---------------|--------|----------|
| INV-001 | CONTRACT-001 | scaffolded | CRITICAL |
| INV-002 | CONTRACT-002 | scaffolded | CRITICAL |
| INV-003 | CONTRACT-003 | scaffolded | CRITICAL |
| INV-004 | CONTRACT-004 | ready_to_run | CRITICAL |
| INV-005 | CONTRACT-005 | scaffolded | HIGH |
| INV-006 | CONTRACT-006 | deferred_phase_2 | HIGH |
| INV-007 | CONTRACT-007 | deferred_phase_2 | HIGH |
| INV-008 | CONTRACT-008 | deferred_phase_2 | HIGH |
| INV-009 | CONTRACT-009 | deferred_phase_2 | MEDIUM |

**Phase 1 Target:** Implement CONTRACT-001 through CONTRACT-004 (4 critical tests)

---

## Maintenance Guidelines

### Adding New Invariants

1. **Detect invariant:** During spec writing or code review
2. **Document here:** Add to this file with full specification
3. **Create contract test:** Write executable verification
4. **Link bidirectionally:** Spec → Contract, Contract → Spec
5. **Update traceability matrix:** Add to `15_traceability_matrix.yml`

### Modifying Existing Invariants

**REQUIRES:**
- ✅ Spec review and approval
- ✅ Contract test update (must pass before merge)
- ✅ Feature spec update (cross-references)
- ✅ Traceability matrix update

**PROHIBITED:**
- ❌ Silently changing invariant behavior
- ❌ Removing contract tests
- ❌ Weakening safety guarantees without documentation

---

## Evidence Index

**Core Files:**
- Translation Engine: [src/translation_engine/engine.py](../src/translation_engine/engine.py)
- CLI Entry Point: [src/cli.py](../src/cli.py)
- TM System: [src/tm/__init__.py](../src/tm/__init__.py)
- Validation: [src/translation_engine/validation/decision_engine.py](../src/translation_engine/validation/decision_engine.py)
- Utilities: [src/utils/atomic_write.py](../src/utils/atomic_write.py), [src/utils/file_lock.py](../src/utils/file_lock.py)

**Contract Tests:**
- Directory: [tests/contract/](../tests/contract/)
- Config: [pytest.ini](../pytest.ini) (contract marker)
- README: [tests/contract/README.md](../tests/contract/README.md)

**Traceability:**
- Matrix: [reports/driftless/15_traceability_matrix.yml](../reports/driftless/15_traceability_matrix.yml)
- Manifest: [reports/driftless/spec_mining_manifest.yml](../reports/driftless/spec_mining_manifest.yml)

---

## Related Documents

- [Driftless Governance System](../docs/development/driftless.md)
- [Configuration Schema](configuration.md)
- [Spec Mining Manifest](../reports/driftless/spec_mining_manifest.yml)
- [Traceability Matrix](../reports/driftless/15_traceability_matrix.yml)
- [Gap Closure Plan](../reports/driftless/16_gap_closure_plan.md)
