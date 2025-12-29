# CLI-005: Resume Control (Crash Recovery)

**Feature:** CLI flags for crash recovery and progress resumption
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Command-line flags that enable crash recovery: `--resume` (default), `--no-resume`, and `--force-restart`. Allows translation jobs to resume from last checkpoint after interruptions (Ctrl+C, crashes, errors) without retranslating completed files.

---

## Entry Points

**CLI Flags:**
```bash
translate-hugo --site SITE --resume          # Resume from checkpoint (default)
translate-hugo --site SITE --no-resume       # Start fresh, ignore checkpoint
translate-hugo --site SITE --force-restart   # Clear checkpoint and start fresh
```

**Parser Registration:**
- File: `src/cli.py`
- Lines: 500-525 (resume control argument group)
- Argument group: "Resume Control (Crash Recovery)"

**Usage Site:**
- Lines: 1009-1013 (resume flag handling)
- Lines: 1380 (progress tracker creation)
- Lines: 1471, 1498, 1517, 1524 (resume instructions in error messages)

---

## Inputs/Outputs

### Input: --resume

```bash
--resume
```

**Behavior:**
- Load progress from `.translation_progress/{site_id}/progress.pkl` if exists
- Skip files already translated successfully
- Resume from last checkpoint
- **Default:** Enabled (action="store_true", default=True)

**Evidence:** Lines 502-508

### Input: --no-resume

```bash
--no-resume
```

**Behavior:**
- Ignore existing progress checkpoint
- Start translation from beginning
- Do not delete checkpoint (use --force-restart for that)
- Sets `resume=False`

**Evidence:** Lines 510-516

### Input: --force-restart

```bash
--force-restart
```

**Behavior:**
- Clear all progress for site
- Delete `.translation_progress/{site_id}/` directory
- Start fresh translation
- Overrides --resume even if specified
- Sets `restart=True`

**Evidence:** Lines 517-522

### Input: --clear-all-progress

```bash
--clear-all-progress
```

**Behavior:**
- Clear progress for all sites
- Delete entire `.translation_progress/` directory
- Destructive operation (asks for confirmation)

**Evidence:** Line 524

### Output: Resume Behavior

**Resume enabled (default):**
```python
progress_tracker = ProgressTracker(site_id=site_id)
progress_tracker.load()  # Load from .translation_progress/{site_id}/
# Skip files in progress_tracker.completed_files
```

**Resume disabled:**
```python
progress_tracker = None  # No checkpoint loading or saving
# Translate all files from scratch
```

**Force restart:**
```python
progress_tracker = ProgressTracker(site_id=site_id)
progress_tracker.clear()  # Delete checkpoint files
# Start fresh translation
```

**Evidence:** Lines 1009-1013, 1380

---

## Invariants

### Must (Critical)

1. **--force-restart overrides --resume:**
   - IF both flags specified → force_restart takes precedence
   - Evidence: Lines 1011-1013
   ```python
   if overrides.force_restart and overrides.resume:
       logger.info("Note: --force-restart overrides --resume")
       resume_enabled = False
   ```

2. **Progress directory structure:**
   - Progress files MUST be stored in `.translation_progress/{site_id}/`
   - Checkpoint file: `progress.pkl`
   - Lock file: `.translation_progress/locks/{site_id}.lock`
   - Evidence: Lines 1380 (ProgressTracker creation), lock directory in API-002 spec

3. **Save progress on interruption:**
   - MUST save progress when:
     - User presses Ctrl+C (SIGINT)
     - Translation fails with exception
     - Partial directory translation completes
   - Evidence: Lines 1471, 1498, 1517, 1524 (resume instruction messages)

4. **Default behavior is resume:**
   - IF no flags specified → resume enabled (default=True)
   - Evidence: Lines 502-508 (--resume default=True)

### Should (Important)

5. **Log resume instruction on error:**
   - SHOULD print "Resume with the same command" after saving progress
   - Evidence: Lines 1471, 1498, 1517, 1524
   ```python
   logger.info("Progress saved. Resume with the same command.")
   ```

6. **Create progress tracker conditionally:**
   - SHOULD create ProgressTracker only if resume_enabled=True
   - Evidence: Lines 1380
   ```python
   if translation_progress_tracker is None and resume_enabled:
       translation_progress_tracker = ProgressTracker(...)
   ```

### Never (Prohibited)

7. **NEVER delete progress without --force-restart:**
   - --no-resume MUST NOT delete checkpoint files
   - Only ignore existing checkpoint
   - Evidence: Distinction between --no-resume and --force-restart flags

8. **NEVER save progress if resume disabled:**
   - IF --no-resume → progress_tracker=None → no checkpoint writes
   - Evidence: Conditional progress tracker creation lines 1380

---

## Progress Storage Format

### Progress File Structure

```python
.translation_progress/
├── {site_id}/
│   ├── progress.pkl              # Serialized ProgressTracker state
│   ├── completed_files.txt       # Human-readable list (optional)
│   └── stats.json                # Aggregated stats (optional)
└── locks/
    └── {site_id}.lock            # File lock for concurrent protection
```

**Evidence:** Directory structure from ProgressTracker implementation, lock file from API-002 spec

### ProgressTracker State (Inferred)

```python
@dataclass
class ProgressTracker:
    site_id: str
    completed_files: Set[Path]         # Files successfully translated
    failed_files: Dict[Path, str]      # Files that failed with error messages
    target_langs: List[str]            # Target languages being processed
    start_time: float                  # Timestamp of first run
    last_save_time: float              # Timestamp of last checkpoint
```

**Evidence:** Inferred from usage patterns and resume functionality requirements

---

## Resume Flow

```
CLI Argument Parsing:
  ┌─────────────────────────────────┐
  │ 1. Parse resume flags            │
  └────┬────────────────────────────┘
       │
       ├─ --force-restart? → resume_enabled=False, clear checkpoint
       ├─ --no-resume? → resume_enabled=False
       └─ --resume or default? → resume_enabled=True
       │
  ┌────▼────────────────────────────┐
  │ 2. Check for existing progress   │
  └────┬────────────────────────────┘
       │
       ├─ resume_enabled AND checkpoint exists?
       │  └─→ Load ProgressTracker from .pkl file
       ├─ resume_enabled AND no checkpoint?
       │  └─→ Create new ProgressTracker
       └─ resume_enabled=False?
          └─→ progress_tracker=None
       │
  ┌────▼────────────────────────────┐
  │ 3. Translate directory           │
  └────┬────────────────────────────┘
       │
       ├─ For each file:
       │  ├─ IF file in completed_files → skip
       │  └─ ELSE → translate file
       │
  ┌────▼────────────────────────────┐
  │ 4. Save progress periodically    │
  └────┬────────────────────────────┘
       │
       ├─ After each file success → save checkpoint
       ├─ On Ctrl+C → save checkpoint and exit
       └─ On error → save checkpoint and exit
       │
       ▼
     Resume available for next run
```

**Evidence:** Flow implemented across cli.py lines 1009-1013, 1380, 1471, 1498, 1517, 1524

---

## Examples

### Example 1: Default Resume Behavior

```bash
# First run (interrupted by Ctrl+C after 50/100 files)
translate-hugo --site products.aspose.net --langs fr de es
# Progress saved: 50/100 files completed

# Second run (resumes from file 51)
translate-hugo --site products.aspose.net --langs fr de es
# Skips first 50 files, continues from file 51
```

### Example 2: Force Restart

```bash
# Clear progress and start fresh
translate-hugo --site products.aspose.net --force-restart --langs fr
# Deletes .translation_progress/products.aspose.net/
# Translates all files from beginning
```

### Example 3: Disable Resume

```bash
# Ignore existing progress (but don't delete it)
translate-hugo --site products.aspose.net --no-resume --langs fr
# Existing checkpoint ignored
# Translates all files from beginning
# Checkpoint files remain on disk
```

### Example 4: Clear All Progress

```bash
# Nuclear option: clear all sites
translate-hugo --clear-all-progress
# Deletes entire .translation_progress/ directory
# Requires confirmation prompt (destructive)
```

---

## Errors and Edge Cases

### Edge Cases

**Both --resume and --force-restart:**
- Behavior: --force-restart wins, resume disabled
- Evidence: Lines 1011-1013 (explicit override logic)

**Corrupted progress file:**
- Behavior: Log warning, start fresh translation
- Risk: Retranslate all files if pickle loading fails
- Mitigation: Robust pickle loading with exception handling

**Progress from different target_langs:**
- Behavior: May cause unexpected skips if langs changed
- Example: First run with ['fr'], second run with ['de'] → no files skipped
- Recommendation: Track target_langs in checkpoint

**Manual deletion of checkpoint:**
- Behavior: Same as --no-resume (checkpoint not found)
- No error, just starts fresh

**Concurrent runs (different sites):**
- Behavior: Each site has own checkpoint directory
- No conflict (site-level isolation)

**Concurrent runs (same site):**
- Behavior: File lock prevents concurrent access
- Second run blocks or fails with LockError
- Evidence: API-002 file locking invariant

---

## Side Effects

### File System

**Reads:**
- `.translation_progress/{site_id}/progress.pkl` (if resume enabled)

**Writes:**
- `.translation_progress/{site_id}/progress.pkl` (periodic checkpoint saves)
- Lock file during translation (see API-002)

**Deletes:**
- `.translation_progress/{site_id}/` (if --force-restart)
- `.translation_progress/` (if --clear-all-progress)

### Logging

**Resume messages:**
```python
logger.info("Note: --force-restart overrides --resume")
logger.info("Progress saved. Resume with the same command.")
logger.info("Progress saved. Fix the issue and resume with the same command.")
```

**Evidence:** Lines 1012, 1471, 1498, 1517, 1524

### No Network Effects

- No external API calls
- Local file system only

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Argument group | src/cli.py | 500-525 | Resume Control group |
| --resume flag | src/cli.py | 502-508 | resume arg |
| --no-resume flag | src/cli.py | 510-516 | no-resume arg |
| --force-restart flag | src/cli.py | 517-522 | force-restart arg |
| --clear-all-progress | src/cli.py | 524 | clear-all-progress arg |
| Override logic | src/cli.py | 1009-1013 | force_restart override |
| Tracker creation | src/cli.py | 1380 | ProgressTracker instantiation |
| Resume messages | src/cli.py | 1471, 1498, 1517, 1524 | logger.info calls |

### Dependencies

| Dependency | Purpose | Evidence |
|------------|---------|----------|
| ProgressTracker | Checkpoint management | src/observability/progress.py (inferred) |
| pickle | Serialization | Standard library |
| Path | File path handling | pathlib |

### Test Evidence

**Existing Tests:**
- `tests/unit/test_cli_resume.py` - Resume flag parsing
- `tests/unit/test_progress_tracker.py` - ProgressTracker unit tests
- `tests/integration/test_interrupt_resume.py` - E2E interrupt and resume

**Missing Contract Tests:**
- --force-restart clears progress
- --force-restart overrides --resume
- Resume skips completed files
- Progress saved on Ctrl+C
- Corrupted checkpoint fallback

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_cli_resume_control.py`
2. **Test invariants:**
   - --force-restart overrides --resume
   - Progress directory structure (.translation_progress/{site_id}/)
   - Default behavior is resume
   - --no-resume does not delete checkpoint
3. **Test edge cases:**
   - Both --resume and --force-restart
   - Corrupted progress file
   - Progress from different target_langs
   - Concurrent runs (same site blocked)
4. **Test interrupt handling:**
   - Ctrl+C saves progress
   - Resume skips completed files
5. **Link to spec:** Add docstring `CONTRACT: specs/features/cli-005-resume-control.md`

**Blockers:** None

---

## Related Specs

- [CLI-001: Main Translation Command](cli-001-main-translate.md) - Main CLI entry point
- [API-002: translate_directory Method](api-002-translate-directory.md) - Directory translation with locking
- [SYS-002: Progress Tracking](sys-002-progress-tracking.md) - ProgressTracker implementation
- [SYS-001: File Locking](sys-001-file-locking.md) - Concurrent access prevention
