# CLI-001: Main Translation Command

**Feature:** `translate-hugo --site <site_id>`
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Primary CLI command for translating Hugo markdown content from source language to multiple target languages using configured translation models and Translation Memory.

---

## Entry Points

**CLI Command:**
```bash
translate-hugo --site products.aspose.net [options]
```

**Registration Site:**
- File: `src/cli.py`
- Lines: 214-593 (argument parser)
- Lines: 952-1533 (translate_site handler)
- Lines: 1535-1549 (main entry point)

**Symbol:** `cli.main() → translate_site(args: Namespace) → int`

---

## Inputs/Outputs

### Required Input

| Parameter | Type | Description | Validation |
|-----------|------|-------------|------------|
| `--site` | string | Site profile identifier | Must exist in config/site_profiles/{site_id}.yaml |

### Optional Inputs

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--input` | path | site.content_roots[0] | Source file or directory |
| `--target-langs` | list[string] | site.target_langs | Target language codes |
| `--output` | path | site.output_dir | Output directory |

### Output Format

**Exit Codes:**
- `0` - Success (all files translated)
- `1` - Failure (validation errors, IO errors, config errors)
- `130` - Interrupted (SIGINT/Ctrl+C)

**File Output Structure:**
```
{output_dir}/
  {lang1}/
    path/to/file.md
  {lang2}/
    path/to/file.md
```

**Side Effect Artifacts:**
- `.translation_progress/` - Progress tracking files
- `.translation_progress/locks/{site_id}.lock` - Concurrency lock
- `data/tm/l2_lmdb/` - Translation Memory updates
- `data/tm/l3_faiss/` - Semantic index updates

---

## Invariants

### Must (Critical)

1. **Multi-language subprocess isolation:**
   - WHEN: len(target_langs) > 1
   - THEN: MUST spawn separate subprocess per language
   - Evidence: `src/cli.py` lines 1090-1178
   - Rationale: Prevent M2M100 model state contamination between languages

   ```python
   # Lines 1095-1099
   if len(target_langs) > 1 and not getattr(args, '_single_lang_mode', False):
       logger.info(
           f"Multi-language translation detected ({len(target_langs)} languages). "
           f"Processing each language in separate subprocess to prevent state contamination..."
       )
   ```

2. **Atomic output writes:**
   - ALL translated files MUST be written atomically (temp + rename)
   - Evidence: `src/utils/atomic_write.py`
   - Rationale: Prevent corrupted files on crash

3. **Site profile validation:**
   - MUST validate site profile exists before initialization
   - MUST fail fast with clear error if profile missing
   - Evidence: `config_service.get_site_profile()` raises ValueError

### Should (Important)

4. **Progress file integrity:**
   - SHOULD create progress file on start (if --resume enabled)
   - SHOULD update progress after each file
   - SHOULD validate and recover corrupted progress files
   - Evidence: `src/cli.py` lines 1035-1063

5. **Graceful shutdown:**
   - SHOULD register signal handlers for SIGINT/SIGTERM
   - SHOULD save L3 index on shutdown
   - SHOULD complete current file before exit (first Ctrl+C)
   - Evidence: `setup_unified_signal_handler()` lines 867-932

### Never (Prohibited)

6. **NEVER skip subprocess isolation:**
   - Even with `--force-retranslate`, multi-language MUST use subprocesses
   - Bypassing isolation leads to silent corruption

7. **NEVER modify both parallel flags:**
   - Cannot use `--parallel-languages` AND `--global-lang-rounds` together
   - Evidence: Lines 198-202 raise ValueError

---

## Errors and Edge Cases

### Error Conditions

| Error | Exception | Exit Code | Recovery |
|-------|-----------|-----------|----------|
| Site profile not found | ValueError | 1 | Check config/site_profiles/ |
| Input path not found | - | 1 | Validate path |
| Output dir not writable | SystemExit | 1 | Check permissions |
| CUDA requested but unavailable | - | 1 | Use --device cpu |
| Lock already held | LockError | 1 | Wait or --force-restart |
| Validation rejection | TranslationRejectedError | 1 | Review errors, adjust config |

### Edge Cases

**Empty target_langs list:**
- Behavior: Use site profile target_langs
- Evidence: `src/cli.py` line 1086

**Single target language with multi-lang isolation:**
- Behavior: NO subprocess spawned (optimization)
- Evidence: `if len(target_langs) > 1` check

**Ctrl+C during translation:**
- First press: Graceful shutdown, saves progress
- Second press: Force exit (code 130), may lose progress
- Evidence: `interrupt_count` tracking in signal handler

**Corrupted progress file:**
- Behavior: Attempts recovery, backs up to `.corrupt`, starts fresh
- Evidence: Lines 1035-1063

**Missing L3 semantic TM:**
- Behavior: Falls back to L1+L2 only, logs warning
- Evidence: `try/except` in L3 initialization

---

## Config and Environment

### Configuration Files

**Site Profile** (config/site_profiles/{site_id}.yaml):
```yaml
site_id: products.aspose.net
content_roots:
  - /path/to/content
target_langs:
  - fr
  - de
  - es
output_dir: /path/to/output
default_model: m2m100_1.2b
```

**Global Config** (config/global.yaml):
```yaml
tm_data_dir: data/tm
model_cache_dir: ~/.cache/huggingface
```

### Environment Variables

| Variable | Default | Usage |
|----------|---------|-------|
| TELEMETRY_API_URL | http://localhost:8765 | Metrics endpoint |
| CONFIG_PATH | ./config | Config root override |
| TM_PATH | data/tm | TM storage override |

---

## Side Effects

### File System

**Reads:**
- `config/site_profiles/{site_id}.yaml`
- `config/global.yaml`
- `config/model_registry.yaml`
- Input markdown files

**Writes:**
- `{output_dir}/{lang}/{filename}` - Translated files
- `.translation_progress/progress_{timestamp}.json` - Progress tracking
- `.translation_progress/locks/{site_id}.lock` - File lock
- `data/tm/l2_lmdb/` - LMDB database updates
- `data/tm/l3_faiss/index.faiss` - Semantic index (on shutdown)

### Cache Updates

**Translation Memory:**
- L1 (in-memory): Updates on translation (unless --cache-write-mode=never)
- L2 (persistent): Writes to LMDB on successful translation
- L3 (semantic): Indexes embeddings, saved on shutdown

### Metrics Emission

**If `--metrics-file` specified:**
- `{path}_current.json` - Current state snapshot (updated every --metrics-interval)
- `{path}.ndjson` - Event stream (append-only)

**Prometheus metrics** (if configured):
- `translation_files_total`
- `translation_segments_total`
- `tm_hits_total{layer="l1|l2|l3"}`
- `validation_decisions_total{decision="accept|retry|reject"}`

### Network Calls

**Model Downloads:**
- First run: Downloads from HuggingFace hub (~500MB-2GB per model)
- Cached: Uses `~/.cache/huggingface/` (no network)

**Metrics Push:**
- If Prometheus Pushgateway configured: POST metrics periodically

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Entry point | src/cli.py | 1535-1549 | main() |
| Argument parser | src/cli.py | 214-593 | create_parser() |
| Main handler | src/cli.py | 952-1533 | translate_site() |
| Multi-lang isolation | src/cli.py | 1090-1178 | subprocess spawning logic |
| Signal handler | src/cli.py | 867-932 | setup_unified_signal_handler() |
| Progress tracking | src/cli.py | 1009-1074 | Progress initialization |
| Output validation | src/cli.py | 727-751 | validate_output_path() |

### Configuration Evidence

| File | Purpose | Schema Validation |
|------|---------|-------------------|
| pyproject.toml | Package definition, CLI script | setuptools |
| config/site_profiles/*.yaml | Site configuration | Pydantic SiteProfile |
| config/global.yaml | System defaults | Pydantic GlobalConfig |

### Test Evidence

**Existing Tests:**
- `tests/unit/test_cli_parser.py` - Argument parsing
- `tests/integration/test_cli_workflow.py` - E2E CLI tests
- `tests/unit/test_file_lock.py` - Concurrency control

**Missing Contract Tests:**
- Multi-language subprocess isolation (critical invariant #1)
- Atomic write behavior
- Signal handler shutdown sequence
- Progress file recovery

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_cli_main_translate.py`
2. **Test invariants:**
   - Multi-language subprocess isolation
   - Atomic file writes
   - Site profile validation
   - Signal handler behavior
3. **Test edge cases:**
   - Empty target langs
   - Corrupted progress files
   - Ctrl+C interruption
   - Disk full scenarios
4. **Link to spec:** Add docstring reference to this spec

**Blockers:** None

**Next Step:** Write contract test with `@pytest.mark.contract` marker and spec reference in docstring.

---

## Related Specs

- [API-001: translate_file Method](api-001-translate-file.md) - Called by this command
- [API-002: translate_directory Method](api-002-translate-directory.md) - Called by this command
- [CLI-002: Validation Control](cli-002-validation-control.md) - Validation flags
- [CLI-005: Resume Control](cli-005-resume-control.md) - Progress tracking flags
