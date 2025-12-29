# API-001: TranslationEngine.translate_file()

**Feature:** Single file translation method
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Translates a single Hugo markdown file to one or more target languages using Translation Memory, model inference, and validation pipeline. Returns detailed result with success status, output paths, statistics, and validation data.

---

## Entry Points

**API Method:**
```python
engine.translate_file(
    site_id: str,
    file_path: Path,
    target_langs: List[str],
    force: bool = False,
    validate: Optional[bool] = None
) -> TranslationResult
```

**Registration Site:**
- File: `src/translation_engine/engine.py`
- Symbol: `TranslationEngine.translate_file()`
- Evidence: Method is public (no leading underscore)

---

## Inputs/Outputs

### Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| site_id | str | Yes | - | Site profile identifier |
| file_path | Path | Yes | - | Source markdown file path |
| target_langs | List[str] | Yes | - | Target language codes (e.g., ['fr', 'de']) |
| force | bool | No | False | Bypass TM cache, force fresh translation |
| validate | Optional[bool] | No | None | Override validation setting (None = use config) |

### Output Type: TranslationResult

```python
@dataclass
class TranslationResult:
    success: bool                              # Overall success flag
    file_path: Path                            # Source file path
    outputs: Dict[str, Path]                   # {lang_code: output_file_path}
    stats: TranslationStats                    # Translation metrics
    errors: List[str]                          # Error messages
    warnings: List[str]                        # Warning messages
    validation_result: Optional[ValidationResult]  # Validation details
    validation_decision: Optional[ValidationDecision]  # ACCEPT/RETRY/REJECT
    decision_reason: Optional[str]             # Decision explanation
    retry_attempts: int                        # Number of retries performed
    retry_history: List[Dict]                  # Retry attempt details
    verification_result: Optional[Any]         # Post-translation verification (VA-03)
    skipped_langs: List[str]                   # Languages skipped (existing output)
    skip_reasons: Dict[str, str]               # {lang: reason}
```

### Translation Statistics

```python
@dataclass
class TranslationStats:
    total_segments: int                        # Total segments processed
    tm_hits: int                               # TM cache hits (L1+L2+L3)
    l1_hits: int                               # L1 in-memory hits
    l2_hits: int                               # L2 persistent hits
    l3_hits: int                               # L3 semantic hits
    translated_segments: int                   # New model translations
    skipped_segments: int                      # Excluded segments
    duration_seconds: float                    # Total time
    model_used: Optional[str]                  # Model ID
    tokens_input: int                          # Input tokens (TEL-04)
    tokens_output: int                         # Output tokens
    tokens_cached: int                         # Tokens saved via TM
    validation_passed: bool                    # Validation success
    validation_decision: str                   # accept/retry/reject

    # Properties
    @property
    tm_hit_rate: float                         # tm_hits / total_segments

    @property
    token_cache_rate: float                    # tokens_cached / tokens_total
```

---

## Invariants

### Must (Critical)

1. **Atomic output writes:**
   - ALL output files MUST be written atomically (temp file + rename)
   - Evidence: Uses `atomic_write()` from `src/utils/atomic_write.py`
   - Rationale: Prevent corrupted files on crash/interrupt

2. **TM lookup order:**
   - Translation Memory lookups MUST follow L1 → L2 → L3 order
   - Evidence: `TranslationMemory.exact_lookup()` implements cascade
   - Rationale: Performance (fast → slow), cache hierarchy

3. **Validation before write:**
   - IF validation enabled, MUST validate translation before writing
   - MUST NOT write file if decision is REJECT
   - Evidence: Decision engine check before `_write_output()`

4. **TM update only on ACCEPT:**
   - MUST NOT store translation in TM if validation decision is REJECT or RETRY (without eventual ACCEPT)
   - Evidence: TM update happens after successful write
   - Rationale: Preserve TM quality

### Should (Important)

5. **Progress tracking:**
   - SHOULD update progress tracker after each language translation
   - Evidence: `progress_tracker.mark_translation_complete()` calls

6. **Metrics emission:**
   - SHOULD emit telemetry for translation session
   - SHOULD track tokens (input/output/cached)
   - Evidence: Telemetry context manager usage

7. **Skip existing outputs:**
   - SHOULD check if output file exists and is newer than source
   - SHOULD skip translation if mtime check passes (unless force=True)
   - Evidence: Skip logic based on file modification time

### Never (Prohibited)

8. **NEVER modify source file:**
   - Source file is read-only input, must never be modified
   - Only output files in `{output_dir}/{lang}/` may be written

9. **NEVER write partial results on error:**
   - If translation fails, do not write partial/incomplete output
   - Exception: May write if decision is ACCEPT with warnings

---

## Errors and Edge Cases

### Exceptions Raised

| Exception | Condition | Handling |
|-----------|-----------|----------|
| ValueError | site_id not found in config | Fail fast, clear error message |
| TranslationRejectedError | Validation decision = REJECT | Logged, not written, success=False |
| TranslationRetryableError | Validation decision = RETRY (max retries reached) | Logged, retry attempted |
| ShutdownRequested | Graceful shutdown signal | Clean exit, progress saved |
| DiskFullError | Insufficient disk space | Clear error with space info |
| PermissionError | Output dir not writable | Clear error with path |
| LockError | Concurrent translation detected | User instructed to wait or --force-restart |

### Edge Cases

**File already translated (mtime check):**
- Behavior: Skip translation, add to `skipped_langs` with reason
- Override: `force=True` bypasses check
- Evidence: Modification time comparison logic

**Empty markdown file:**
- Behavior: Extract 0 segments, create empty output with frontmatter only
- Success: True (nothing to translate)

**Missing target language in model:**
- Behavior: Log error, skip language, success=False
- Evidence: Model capability check before translation

**TM hit rate = 100%:**
- Behavior: No model loading, pure cache retrieval
- Performance: <100ms for small files
- Evidence: Model only loaded if translated_segments > 0

**Validation RETRY → RETRY → ACCEPT:**
- Behavior: Retry with feedback, eventual success after 2 retries
- Evidence: Retry loop with max_retry_attempts limit

**Validation RETRY → RETRY → max retries:**
- Behavior: Decision based on `accept_after_max_retries` config
  - If True: ACCEPT (best effort, log warning)
  - If False: REJECT (raise TranslationRejectedError)
- Evidence: Decision engine max retry logic

---

## Config and Environment

### Site Profile Config

```yaml
site_id: products.aspose.net
default_source_lang: en
default_model: m2m100_1.2b
output_dir: /path/to/output
frontmatter_config:
  translatable_fields:
    - title
    - description
  protected_fields:
    - url
    - date
```

### Engine Configuration

Passed via `TranslationEngine.__init__()`:
```python
enable_validation: bool = False       # Enable validation pipeline
validation_mode: str = "normal"       # strict/normal/lenient
max_retries: int = 2                  # Max retry attempts
dry_run: bool = False                 # Preview mode, no writes
force_retranslate: bool = False       # Bypass cache
```

### Environment Variables

| Variable | Usage | Default |
|----------|-------|---------|
| TM_PATH | Translation Memory data directory | data/tm |
| MODEL_CACHE | HuggingFace cache directory | ~/.cache/huggingface |

---

## Side Effects

### File System Operations

**Reads:**
- `{file_path}` - Source markdown file
- `config/site_profiles/{site_id}.yaml` - Site configuration
- `data/tm/l2_lmdb/` - L2 cache lookups
- `data/tm/l3_faiss/` - L3 semantic index

**Writes:**
- `{output_dir}/{lang}/{filename}` - Translated output (atomic)
- `data/tm/l2_lmdb/` - L2 cache updates (on ACCEPT)
- `.translation_progress/progress_*.json` - Progress file update

**Disk Space Check:**
- Pre-write check: Warns if free space < 2x file size
- Evidence: Log warning in `_write_output()` method

### Cache Updates

**L1 (In-Memory):**
- Updated immediately on successful translation
- Evicts LRU entries if cache full (max_size=10000)

**L2 (LMDB Persistent):**
- Updated on ACCEPT decision after file write
- ACID guarantees (atomic commit)

**L3 (FAISS Semantic):**
- Embeddings generated and indexed on ACCEPT
- Index saved to disk on engine shutdown
- Not saved per-file (performance optimization)

### Metrics Emission

**Telemetry (if enabled):**
```python
telemetry.track_translation_session(
    job_type="translate_file",
    file_path=file_path,
    target_langs=target_langs,
    segments_total=stats.total_segments,
    segments_cached=stats.tm_hits,
    duration_ms=stats.duration_seconds * 1000,
)
```

**Production Metrics (if ingestor configured):**
```python
production_ingestor.record_translation_run(
    file_path=str(file_path),
    target_lang=target_lang,
    success=success,
    validation_passed=stats.validation_passed,
)
```

**Progress Tracker (if configured):**
- Marks file as started
- Updates on each language completion
- Marks file as complete/failed

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Method definition | src/translation_engine/engine.py | ~150-400 | translate_file() |
| Validation integration | src/translation_engine/engine.py | ~350-380 | validation loop |
| TM lookup | src/tm/translation_memory.py | ~80-120 | exact_lookup() |
| Atomic write | src/utils/atomic_write.py | ~40-100 | atomic_write() |
| Decision engine | src/translation_engine/validation/decision_engine.py | ~50-150 | decide() |

### Data Model Evidence

| Model | File | Lines | Purpose |
|-------|------|-------|---------|
| TranslationResult | src/translation_engine/models.py | ~50-80 | Return type |
| TranslationStats | src/translation_engine/models.py | ~100-150 | Metrics |
| ValidationDecision | src/translation_engine/models.py | ~20-30 | Enum |

### Test Evidence

**Existing Tests:**
- `tests/unit/test_engine_*.py` - Unit tests for engine methods
- `tests/integration/test_e2e_validation.py` - Validation pipeline E2E

**Missing Contract Tests:**
- Atomic write verification (crash during write)
- TM lookup order enforcement
- Validation decision enforcement (REJECT must not write)
- Skip existing file behavior

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_api_translate_file.py`
2. **Test invariants:**
   - Atomic write behavior (simulate crash)
   - TM lookup order (mock layers, verify call sequence)
   - Validation before write (REJECT must not write file)
   - TM update only on ACCEPT (verify no rejected translations in TM)
3. **Test edge cases:**
   - Empty file
   - 100% TM hit rate
   - Retry → max retries
   - Disk full scenario
4. **Link to spec:** Add docstring `CONTRACT: specs/features/api-001-translate-file.md`

**Blockers:** None

---

## Related Specs

- [CLI-001: Main Translation Command](cli-001-main-translate.md) - Calls this method
- [TM-001: L1 In-Memory Cache](tm-001-l1-cache.md) - Used for lookups
- [TM-002: L2 Persistent Store](tm-002-l2-persistent.md) - Used for lookups
- [VAL-001: Decision Engine](val-001-decision-engine.md) - Validation decisions
- [API-002: translate_directory Method](api-002-translate-directory.md) - Batch version
