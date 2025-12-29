# API-002: translate_directory Method

**Feature:** Batch translation of directory with parallel processing
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Batch translation method that scans a directory for markdown files and translates them in parallel or sequential mode. Includes file filtering, progress tracking, and file-level locking to prevent concurrent translations of the same site.

---

## Entry Points

**API Method:**
```python
engine.translate_directory(
    site_id: str,
    directory: Path,
    target_langs: List[str],
    recursive: bool = True,
    parallel: bool = True,
    max_workers: Optional[int] = None,
) -> DirectoryResult
```

**Registration Site:**
- File: `src/translation_engine/engine.py`
- Lines: 1764-1913 (method signature and implementation)
- Symbol: `TranslationEngine.translate_directory()`

---

## Inputs/Outputs

### Input Parameters

```python
site_id: str                    # Site profile identifier
directory: Path                 # Directory to scan for markdown files
target_langs: List[str]         # Target language codes (e.g., ['fr', 'de'])
recursive: bool = True          # Scan subdirectories if True
parallel: bool = True           # Use parallel processing if True
max_workers: Optional[int] = None  # Max parallel workers (auto if None)
```

**Evidence:** Lines 1764-1772 in `src/translation_engine/engine.py`

### Output: DirectoryResult

```python
@dataclass
class DirectoryResult:
    success: bool               # Overall success status
    directory: Path             # Directory that was processed
    total_files: int            # Total markdown files found
    successful_files: int       # Successfully translated files
    failed_files: int           # Failed translation files
    files: List[Path]           # All file paths processed
    errors: List[str]           # Error messages (if any)
```

**Evidence:** Return type in method signature line 1772, import from `models.py` line 42

---

## Invariants

### Must (Critical)

1. **File-level locking:**
   - MUST acquire lock before translating directory
   - Lock file: `.translation_progress/locks/{site_id}.lock`
   - Lock timeout: 300 seconds (5 minutes)
   - Evidence: Lines 1790-1802
   ```python
   lock_dir = Path(".translation_progress") / "locks"
   lock_file = lock_dir / f"{site_id}.lock"
   lock = FileLock(lock_file, timeout=300.0)
   ```

2. **Always release lock:**
   - MUST release lock even if translation fails
   - Evidence: Lines 1810-1812 (finally block)
   ```python
   finally:
       lock.release()
   ```

3. **Source file filtering:**
   - MUST filter out already-translated files (e.g., index.fr.md)
   - Uses site profile's localization strategy
   - Evidence: Lines 1878-1884
   ```python
   site_profile = self.config.get_site_profile(site_id)
   if site_profile:
       md_files = filter_source_files(md_files, site_profile, target_langs)
   ```

4. **Glob pattern based on recursive flag:**
   - IF recursive=True → pattern = `**/*.md` (all subdirectories)
   - IF recursive=False → pattern = `*.md` (current directory only)
   - Evidence: Lines 1871, 1838

5. **Delegate to translate_file:**
   - Each file MUST be translated via `translate_file()` method
   - Ensures consistent validation, TM lookup, atomic writes
   - Evidence: Implementation in `_translate_directory_sequential` and `_translate_directory_parallel`

### Should (Important)

6. **Parallel mode selection:**
   - SHOULD use parallel mode if parallel=True AND len(files) > 1
   - SHOULD use sequential mode if parallel=False OR only 1 file
   - Evidence: Lines 1894-1903

7. **Telemetry tracking:**
   - SHOULD track batch operation with `job_type="translate_directory"`
   - SHOULD extract business context from representative file (first .md)
   - Evidence: Lines 1835-1854

8. **Graceful shutdown support:**
   - SHOULD register telemetry context for interrupt handling
   - Evidence: Lines 1856-1861

### Never (Prohibited)

9. **NEVER allow concurrent site translations:**
   - Reject with `LockError` if lock cannot be acquired
   - Evidence: Lines 1798-1800
   ```python
   raise LockError(
       f"Another translation is in progress for site '{site_id}'. "
       f"Wait for it to complete or remove lock file: {lock_file}"
   )
   ```

10. **NEVER translate already-translated files:**
    - File naming pattern detection prevents retranslating index.fr.md, etc.
    - Evidence: `filter_source_files()` call lines 1881

---

## Decision Logic Flow

```
translate_directory(site_id, directory, target_langs, ...):
  ┌─────────────────────────────────┐
  │ 1. Acquire file lock             │
  └────┬────────────────────────────┘
       │
       ├─ Lock acquired?
       │  ├─→ Yes: proceed
       │  └─→ No: raise LockError
       │
  ┌────▼────────────────────────────┐
  │ 2. Find markdown files           │
  └────┬────────────────────────────┘
       │
       ├─ Glob pattern based on recursive flag
       │  ├─→ recursive=True: **/*.md
       │  └─→ recursive=False: *.md
       │
  ┌────▼────────────────────────────┐
  │ 3. Filter source files           │
  └────┬────────────────────────────┘
       │
       ├─ Remove already-translated files
       │  (e.g., index.fr.md if fr in target_langs)
       │
  ┌────▼────────────────────────────┐
  │ 4. Choose processing mode        │
  └────┬────────────────────────────┘
       │
       ├─ parallel=True AND len(files) > 1?
       │  ├─→ Yes: _translate_directory_parallel()
       │  └─→ No: _translate_directory_sequential()
       │
  ┌────▼────────────────────────────┐
  │ 5. Process each file             │
  └────┬────────────────────────────┘
       │
       ├─ Call translate_file() for each
       │  └─→ Aggregate results into DirectoryResult
       │
  ┌────▼────────────────────────────┐
  │ 6. Release lock (finally)        │
  └────┬────────────────────────────┘
       │
       ▼
     Return DirectoryResult
```

**Evidence:** Flow implemented in lines 1764-1913

---

## Parallel vs Sequential Processing

### Parallel Mode (_translate_directory_parallel)

**Activation:**
- `parallel=True` AND `len(files) > 1`

**Implementation:**
- Uses `ThreadPoolExecutor` with configurable workers
- Default workers: `os.cpu_count()` or passed `max_workers`
- Evidence: Lines 2075+ (`_translate_directory_parallel` method)

**Concurrency Safety:**
- Each file translation is independent
- TM L2 (LMDB) handles concurrent writes
- File locks prevent writing same output file twice

### Sequential Mode (_translate_directory_sequential)

**Activation:**
- `parallel=False` OR `len(files) == 1`

**Implementation:**
- Simple loop over files
- Progress tracker integration (RES-02)
- Evidence: Lines 1989+ (`_translate_directory_sequential` method)

**Benefits:**
- Simpler error handling
- Progress tracking per file
- Lower memory footprint

---

## Configuration

### File Lock Configuration

```python
lock_dir = Path(".translation_progress") / "locks"
lock_timeout = 300.0  # seconds (5 minutes)
```

**Evidence:** Lines 1791-1793

### Max Workers (Parallel Mode)

- Auto-detect: `os.cpu_count()`
- Override: Pass `max_workers` parameter
- Typical: 4-8 workers for CPU-bound translation

**Evidence:** Documentation references to `max_workers` parameter

---

## Errors and Edge Cases

### Error Handling

**LockError:**
- Raised if lock acquisition fails
- User action: Wait or manually remove lock file
- Evidence: Lines 1798-1804

**Empty directory:**
- Behavior: Return success with total_files=0
- Evidence: Lines 1888-1891
```python
if not md_files:
    logger.warning(f"No markdown files found in {directory}")
    result.success = True
    return result
```

**All files filtered out:**
- Behavior: Same as empty directory
- Example: Directory only contains translated files like index.fr.md

**Exception during translation:**
- Behavior: Catch exception, log error, set result.success=False
- Lock still released in finally block
- Evidence: Lines 1907-1912

### Edge Cases

**Single file with parallel=True:**
- Behavior: Use sequential mode (parallel optimization skipped)
- Evidence: Lines 1894-1903 (len(files) > 1 check)

**Non-existent directory:**
- Behavior: glob returns empty list → same as empty directory
- No explicit validation (relies on Path.glob behavior)

**Mixed file types:**
- Behavior: Only *.md files processed (glob pattern)
- Other files ignored

**Recursive with deep nesting:**
- Behavior: All subdirectories scanned
- No depth limit

---

## Side Effects

### File System

**Reads:**
- Scans directory with glob pattern
- Reads each markdown file via `translate_file()`
- Reads site profile YAML

**Writes:**
- Lock file: `.translation_progress/locks/{site_id}.lock`
- Output files: Delegated to `translate_file()`
- Progress files: If progress tracker enabled

### Translation Memory

**Updates:**
- L1/L2/L3 caches updated per file
- Delegated to `translate_file()`

### Metrics

**Telemetry:**
- Job type: `translate_directory`
- Tracked metrics: total_files, successful_files, failed_files, duration
- Evidence: Lines 1844-1854, 1948-1954

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Method signature | src/translation_engine/engine.py | 1764-1772 | translate_directory() |
| Lock acquisition | Same | 1790-1812 | Lock creation and try/finally |
| File discovery | Same | 1870-1876 | Glob pattern and filtering |
| Source file filtering | Same | 1878-1884 | filter_source_files() call |
| Mode selection | Same | 1894-1903 | Parallel vs sequential |
| Sequential implementation | Same | 1989+ | _translate_directory_sequential() |
| Parallel implementation | Same | 2075+ | _translate_directory_parallel() |

### Dependencies

| Dependency | Purpose | Import |
|------------|---------|--------|
| FileLock | Site-level locking | src/utils/file_lock.py |
| filter_source_files | Source file filtering | src/utils/file_filters.py |
| DirectoryResult | Return type | src/translation_engine/models.py |
| ThreadPoolExecutor | Parallel processing | concurrent.futures |

### Test Evidence

**Existing Tests:**
- `tests/unit/test_parallel_translation.py` - Parallel vs sequential comparison
- `tests/unit/test_file_lock.py` - Lock integration
- `tests/unit/test_engine_progress_integration.py` - Progress tracking integration

**Missing Contract Tests:**
- File lock enforcement (concurrent access rejection)
- Source file filtering (no retranslation)
- Lock release on error (finally block)
- Parallel vs sequential result consistency

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_api_translate_directory.py`
2. **Test critical invariants:**
   - File lock prevents concurrent site translations
   - Source file filtering excludes translated files
   - Lock always released (even on exception)
   - Delegate to translate_file for each file
3. **Test edge cases:**
   - Empty directory
   - Single file (parallel mode)
   - Lock acquisition failure
   - All files filtered out
4. **Test modes:**
   - Parallel vs sequential result consistency
   - Max workers configuration
5. **Link to spec:** Add docstring `CONTRACT: specs/features/api-002-translate-directory.md`

**Blockers:** None

---

## Related Specs

- [API-001: translate_file Method](api-001-translate-file.md) - Called for each file
- [CLI-001: Main Translation Command](cli-001-main-translate.md) - CLI wrapper
- [CLI-005: Resume Control](cli-005-resume-control.md) - Progress tracking integration
- [SYS-001: File Locking](sys-001-file-locking.md) - Lock implementation
