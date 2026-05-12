# Task Backlog - Phase 6 Remediation

---

## Workstream: INT-REMED-20260511 - Integration Test Failure Remediation
**Plan**: `plans/healing/integration-test-failure-remediation-contract.md`
**Added**: 2026-05-11
**Status**: IN_PROGRESS
**Primary rule**: execute only `verified_ready` taskcards; blocked or partial taskcards require additional evidence first.

### ORCH-INT-G0: Gate 0 environment and worktree lock
**Owner-agent**: Orchestrator / Agent E
**Status**: PASS
**Impacted paths**: `reports/PLAN_SOURCES.md`, `reports/PLAN_INDEX.md`, `reports/STATUS.md`, `reports/CHANGELOG.md`
**Acceptance criteria**: branch, commit, dirty worktree, Python, pytest, and dependency state captured.
**Evidence**: `reports/STATUS.md`, `reports/CHANGELOG.md`

### TC-B01: Fix invalid SiteProfile fixture ID
**Owner-agent**: Agent B
**Status**: PLANNED
**Scope**: `tests/integration/test_e2e_validation.py`
**Acceptance criteria**: fixture uses a valid `site_id` matching `^[a-z0-9.-]+$`; assertions are not weakened.
**Tests**: `python -m pytest tests/integration/test_e2e_validation.py -q --tb=short`
**Risk**: Low, test fixture only.

### TC-B02: Update RecommendationFeedback fixtures
**Owner-agent**: Agent B
**Status**: PLANNED
**Scope**: `tests/integration/test_benchmarking_e2e.py`
**Acceptance criteria**: test fixtures match current `RecommendationFeedback` required fields; Windows temp DB handles do not leak.
**Tests**: `python -m pytest tests/integration/test_benchmarking_e2e.py -q --tb=short`
**Risk**: Medium, benchmark DB lifecycle can leak handles on Windows.

### TC-B04: Rate volatility transition assertion
**Owner-agent**: Agent B
**Status**: PLANNED
**Scope**: `tests/integration/test_stats_accuracy.py`
**Acceptance criteria**: test verifies transition volatility, not steady-state uniform samples; no assertion weakening.
**Tests**: `python -m pytest tests/integration/test_stats_accuracy.py -q --tb=short`
**Risk**: Low, test timing correction.

### TC-D01: Persist BenchmarkDB extended fields
**Owner-agent**: Agent B
**Status**: PLANNED
**Scope**: `src/benchmarking/storage.py`
**Acceptance criteria**: extended `SystemInfo` fields round-trip through save/load; schema version remains v10.
**Tests**: `python -m pytest tests/integration/test_systeminfo_persistence.py -q --tb=short`
**Regression tests**: `python -m pytest tests/unit/benchmarking/test_migrations.py tests/unit/benchmarking/test_schema_migrations_v8.py -q --tb=short`
**Risk**: High, benchmark persistence compatibility.

### TC-H02: Windows-safe benchmark CLI output encoding
**Owner-agent**: Agent B
**Status**: PLANNED
**Scope**: `src/benchmarking/cli.py`
**Acceptance criteria**: CLI does not emit characters that fail under Windows charmap stdout/stderr; help and migrate commands still work.
**Tests**: targeted benchmark CLI migrate/help tests from `tests/integration/test_benchmarking_cli.py`
**Risk**: Medium, CLI user-facing output.

### Blocked Items Preserved
- TC-A01 quality metrics optional dependency contract.
- TC-D02 legacy migration compatibility.
- TC-E01 Redis queue test/API contract.
- TC-F01 real TM integrity verifier.
- TC-F02 CLI `--source` compatibility.
- TC-G01 shortcode preservation contract.
- TC-H01 benchmark CLI schema fixture repair.
- TC-I01 nested list renderer diagnosis.
- TC-Z01 remaining failure audit.

---

## WS-MLD-20260417 — Mixed-Language Defect Detection, Healing & Prevention (harmonic-snacking-kernighan)

**Plan**: `C:\Users\prora\.claude\plans\harmonic-snacking-kernighan.md`
**Added**: 2026-04-17
**Status**: IN_PROGRESS

### TC-MLD-01: Prevention fixes + regression tests
**Status**: IN_PROGRESS
**Scope**:
- `src/translation_engine/extractor/text_unit_extractor.py`: zip strict=True; fallback sets None not ""
- `src/translation_engine/reconstructor/ast_renderer.py`: _missing_node_count; AST_FALLBACK warning; placeholder leak
- `src/translation_engine/engine.py`: expose missing_node_count in stats; soft contamination queue
- Tests: `tests/unit/translation_engine/extractor/test_fallback_empty_translation.py`
- Tests: `tests/unit/translation_engine/reconstructor/test_ast_renderer_missing_node.py`
- Tests: `tests/unit/translation_engine/reconstructor/test_placeholder_leak.py`
- Tests: `tests/integration/test_mixed_language_detection.py`

### TC-MLD-02: L2 cache audit + purge script
**Status**: IN_PROGRESS
**Scope**: `scripts/audit_l2_cache_contamination.py`

### TC-MLD-03: Detection enhancement
**Status**: IN_PROGRESS
**Scope**: `scripts/scan_language_contamination.py` — multi-site profiles, block-level, JSON output, parallelism

### TC-MLD-04: Force-retranslation script
**Status**: IN_PROGRESS
**Scope**: `scripts/force_retranslate_contaminated.py`

### TC-MLD-05: Full scan run + cache repair + retranslation + verification
**Status**: CLOSED — 2026-04-17
**Evidence**:
- L2 cache: 2,569 → 0 contaminated entries (`reports/l2_audit_after_repair.json`)
- Site scan: 183,658 files, 93 script-mixing → 89 queued + outputs deleted
- Live run: 0 PLACEHOLDER_LEAK, 0 CASE 4, 113 AST_FALLBACK warnings in add-barcode-in-asp-dotnet-mvc — subsequently confirmed as leaf-extraction false positives (no content leak); rendered output was already correct. True-gap detector repaired in TC-MLD-06.
- Post-retranslation re-scan pending queue drain

### TC-MLD-06: Refine AST_FALLBACK detector — exclude leaf-extraction false positives
**Status**: CLOSED — 2026-04-17
**Scope**: `src/translation_engine/reconstructor/ast_renderer.py`, `tests/unit/translation_engine/reconstructor/test_ast_renderer_leaf_extraction.py`
**Root cause**: The extractor has two paths for formatted containers. Path B (leaf extraction) creates TextUnits only for leaf TEXT children; the container address is never in `unit_map`. The renderer was firing AST_FALLBACK on the container even though `_apply_to_node` recurses into children and correctly translates the TEXT leaves. All 113 warnings from the live run on `add-barcode-in-asp-dotnet-mvc` were false positives.
**Fix**: Added `_has_descendant_in_unit_map()` recursive helper in `_apply_to_node`. Before incrementing `_missing_node_count`, the helper checks whether any descendant node is in `unit_map`. If yes → leaf-extraction case, content IS translated at child level → suppress warning. Only fire for true gaps (no descendant in unit_map).
**Fix type**: Detector / observability correctness — NOT a translation-path or content-quality fix. Rendered Markdown output was already correct before this change; no output files changed.
**Tests**: 4 new regression tests in `test_ast_renderer_leaf_extraction.py` — all pass.
**Pilot evidence**: 30-file probe (2,754 units) after fix: 0 AST_FALLBACK warnings, 0 true `_missing_node_count`. Confirms detector soundness. Does NOT prove true gaps can never exist; future non-zero `_missing_node_count` is a genuine signal.
**Acceptance criteria**: detector soundness (A) satisfied. Content quality (C) unchanged by design.

---

## WS-STALE-TEST-DEBT — Pre-existing Stale Test Failures (gleaming-crunching-liskov addendum)

**Plan**: `C:\Users\prora\.claude\plans\gleaming-crunching-liskov.md` (Section F)
**Added**: 2026-04-18
**Status**: NOT STARTED
**Priority**: Medium — failures pollute test signal but do not affect production runtime

**Background**: ~148 pre-existing failures existed before commit b4fe7cf. All are Class B (test API mismatch — production interfaces changed, tests not updated). None are regressions from b4fe7cf.

### STE-01: test_decision_engine.py — 24 failures
**Root cause**: `ValidationDecisionEngine` API changed; tests expect old error-count threshold behavior
**Action**: Read current `ValidationDecisionEngine` — update tests to match actual behavior. Do not change production code.

### STE-02: test_language_consistency_validator.py — 15 failures
**Root cause**: Validator internal behavior changed; test mocks out of sync
**Action**: Audit validator behavior, update test expectations or mocks.

### STE-03: test_ast_renderer_bold_normalization.py — 22 failures
**Root cause**: Tests reference `_normalize_bold_markers()` method that does not exist in ASTRenderer
**Action**: Either implement `_normalize_bold_markers()` if M2M100 bold corruption is still a production concern, OR delete the test file if no longer needed. Do not add dead stubs.

### STE-04: tests/unit/benchmarking/test_cli.py — 48 failures
**Root cause**: Tests patch `src.benchmarking.cli.BenchmarkDatabase` at module level, but the class is imported lazily inside functions via a `deps` dict; module-level patch target does not exist.
**Action**: Fix test patching strategy — patch inside-function lazy imports correctly (use `mocker.patch` at the right scope, or inject via the `deps` dict pattern that the code actually uses).

### STE-05: Scattered failures (~39) — test_backends.py, test_purity_threshold_override.py, test_engine_detector_wiring.py, vram tests, runner tests
**Root cause**: Various stale mocks, missing methods, torch stub pollution in test ordering
**Action**: Fix individually on a case-by-case basis. Lowest priority within this workstream.

---

## WS-HEAL-20260418 — Test Failure Healing (gleaming-crunching-liskov)

**Plan**: `C:\Users\prora\.claude\plans\gleaming-crunching-liskov.md` (Sections A-I)
**Added**: 2026-04-18
**Status**: IN_PROGRESS

### HEAL-F5: Remove collection blocker (frontmatter validation import)
**Status**: PENDING
**File**: `tests/unit/validation/test_frontmatter_validation.py`
**Root cause**: Imports `_extract_translatable_frontmatter_text` from `src.translation_engine.engine` — function does not exist at HEAD. Blocks unit test collection.
**Action**: Delete file (function permanently removed from engine.py).

### HEAL-F6: Verify test_reconstruction_fix.py state
**Status**: PENDING
**File**: `tests/regression/test_reconstruction_fix.py`
**Action**: Run `python -m pytest tests/regression/test_reconstruction_fix.py --tb=short -q`. If passing → close. If still failing → investigate and fix.

### HEAL-F1: Fix window scheduler datetime mock (8 tests)
**Status**: PENDING
**File**: `tests/unit/workers/test_window_scheduler.py`
**Root cause**: `datetime` selectively imported; patching class only leaves `timedelta` unpatched; `datetime.combine()` on mock returns MagicMock → TypeError in arithmetic.
**Fix**: Update patch strategy — mock `datetime.now.return_value`, delegate `datetime.combine.side_effect` to real `datetime.combine`.

### HEAL-F7: Fix atomic write exception type (1 test)
**Status**: PENDING
**File**: `tests/contract/test_inv002_atomic_writes.py`
**Root cause**: Production code raises `PermissionDeniedError` (custom), test expects builtin `PermissionError`.
**Fix**: Update one failing assertion to expect `PermissionDeniedError` from `src.utils.atomic_write`.

### HEAL-F3: Align orphan sweep test assertions (2 tests)
**Status**: PENDING
**File**: `tests/unit/workers/test_orphan_sweep.py`
**Root cause**: `recover_orphaned_commit_manifests` is a confirmed stub returning 0; tests assert `result >= 2`.
**Fix**: Align assertions to what the legacy path can actually return; add comment documenting why manifest recovery is disabled.

### HEAL-F9: Fix glossary integration (1 test, Class A)
**Status**: PENDING
**Files**: `tests/regression/test_glossary_integration.py`, `src/translation_engine/quality/glossary_corrector.py`
**Root cause**: GlossaryCorrector not firing in pipeline; untranslated English appears instead of glossary-corrected output.
**Action**: Investigate GlossaryCorrector wiring in engine pipeline. Determine if corrector is bypassed, wrong signal, or test setup missing config key.

### HEAL-F4-F10: Fix code blocks in list items (19 tests, Class A)
**Status**: PENDING
**Files**: `src/translation_engine/parser/hugo_parser.py`, `src/translation_engine/extractor/text_unit_extractor.py`
**Root cause**: Parser does not create CODE_BLOCK nodes inside LIST_ITEM context; `_has_block_content()` method missing from extractor; `_collect_text_from_node(CODE_BLOCK)` returns empty string.
**Action**: Fix parser (CODE_BLOCK token processing inside LIST_ITEM), add `_has_block_content()` to extractor, fix `_collect_text_from_node()` for CODE_BLOCK nodes.

---

## WS-PRODREADY-20260417 — Production Readiness Final Sprint (stateless-drifting-mccarthy)

**Plan**: `C:\Users\prora\.claude\plans\stateless-drifting-mccarthy.md` (Sections O-Q)
**Added**: 2026-04-17
**Status**: IN_PROGRESS (1 item remaining)

### TC-N-ENV: Fix env-var availability in Task Scheduler context
**Status**: CLOSED — 2026-04-17
**Fix**: `src/utils/config_loader.py` — dotenv loaded at `ConfigService.__init__()`. `ASPOSE_NET_CONTENT` resolves without bash export.
**Commit**: `37b8dc3`
**Evidence**: `python -c "import os; os.environ.pop('ASPOSE_NET_CONTENT',None); from src.utils.config_loader import ConfigService; ConfigService('config/'); print(os.environ['ASPOSE_NET_CONTENT'])"` → `D:/onedrive/Documents/GitHub/aspose.net/content`

### TC-N-PC: Pre-commit hooks
**Status**: CLOSED — 2026-04-17
**Result**: `ruff` and `ruff-format` failed on pre-existing code only. Zero failures in sprint-changed files. Acceptable per plan guardrail K3.

### TC-N-F2: Worker oneshot — skip_first pagination live proof
**Status**: IN_PROGRESS — worker running, chunk 0 translating 25 files
**Precondition**: TC-N-ENV (closed). Worker started: `2026-04-17 11:24:47`.
**Required evidence**: "Chunk 0: N/25" + "Chunk 1: N/25" in worker log; no TypeError

### [Supporting] recover_orphaned_commit_manifests stub
**Status**: CLOSED — 2026-04-17
**Fix**: Added stub to `src/observability/git_commit_helper.py` so worker no longer fails with ImportError on startup
**Commit**: `37b8dc3`

---

**Plan**: [20260129_003000_phase6_remediation.md](plans/from_chat/20260129_003000_phase6_remediation.md)
**Created**: 2026-01-29 00:30:00 UTC
**Status**: IN_PROGRESS

---

## Overview

Comprehensive remediation of 5 quality gaps identified during Phase 6 CLI-Only Forced Translation validation. Target: Improve pass rate from 13.3% to ≥50%.

---

## Workstream 1: Classification Logic Enhancement
**Owner**: Agent B (Code Implementation)
**Priority**: HIGH
**Status**: PENDING

### Tasks

#### TASK-1.1: Refactor classify_failure() for Multi-Failure Detection
**File**: `reports/phase6_cli_forced_translate/20260128-2139/run_batch23.py:155-200`
**Status**: PENDING

**Description**: Update `classify_failure()` to detect and return ALL failures, not just first match.

**Current Behavior**:
```python
def classify_failure(verify_data: Optional[Dict]) -> Tuple[str, str]:
    # Sequential if-elif-else stops at first match
    if not checks.get("markdown_fidelity", {}).get("passed", True):
        return "FAIL_MARKDOWN_FIDELITY", "..."
    if not untranslated_check.get("passed", True):
        return "FAIL_UNTRANSLATED_PROSE", "..."
    # ... stops at first match
```

**Target Behavior**:
```python
def classify_failure(verify_data: Optional[Dict]) -> Tuple[str, List[Dict]]:
    all_failures = []
    # Collect ALL failures
    if not checks.get("markdown_fidelity", {}).get("passed", True):
        all_failures.append({"category": "FAIL_MARKDOWN_FIDELITY", "reason": "..."})
    if not untranslated_check.get("passed", True):
        all_failures.append({"category": "FAIL_UNTRANSLATED_PROSE", "reason": "..."})
    # ... check all conditions

    # Determine primary category (most severe)
    primary = determine_primary_failure(all_failures)
    return primary, all_failures
```

**Acceptance Criteria**:
- Returns tuple: (primary_category: str, all_failures: List[Dict])
- `all_failures` contains every failed check with category + reason
- Primary category uses severity ranking (UNTRANSLATED > MARKDOWN_FIDELITY > CODE_SPAN > OTHER)

---

#### TASK-1.2: Update Progress Record Schema
**File**: `reports/phase6_cli_forced_translate/20260128-2139/run_batch23.py:292-306`
**Status**: PENDING

**Description**: Add "combined_failures" field to progress records for multi-failure tracking.

**Current Schema**:
```json
{
  "status": "FAIL_MARKDOWN_FIDELITY",
  "reason": "Bold/italic/heading/list structure mismatch"
}
```

**Target Schema**:
```json
{
  "status": "FAIL_MARKDOWN_FIDELITY",
  "reason": "Bold/italic/heading/list structure mismatch",
  "combined_failures": [
    {"category": "FAIL_MARKDOWN_FIDELITY", "reason": "Bold: 13→14, Links: 4→5"},
    {"category": "FAIL_OTHER", "reason": "Line count: 30 vs 45.6 threshold"}
  ]
}
```

**Acceptance Criteria**:
- All progress records include "combined_failures" field (empty list if single failure)
- Schema backward compatible (reason still present)
- JSON serialization works correctly

---

#### TASK-1.3: Update Batch Runners with New Classification
**Files**:
- `reports/phase6_cli_forced_translate/20260128-2139/run_batch23.py`
- `reports/phase6_cli_forced_translate/20260128-2139/run_batch_mode.py`
**Status**: PENDING

**Description**: Update both batch runners to use new multi-failure classification API.

**Changes**:
```python
# Old
status, reason = classify_failure(verify_data)

# New
primary_status, all_failures = classify_failure(verify_data)
reason = all_failures[0]["reason"] if all_failures else None

progress_record = {
    "status": primary_status,
    "reason": reason,
    "combined_failures": all_failures,
    # ...
}
```

**Acceptance Criteria**:
- Both runners use new API
- No regressions in existing functionality
- Test runs produce valid progress.ndjson

---

#### TASK-1.4: Write Unit Tests for Multi-Failure Scenarios
**File**: `tests/unit/test_classification_logic.py` (new)
**Status**: PENDING

**Description**: Create comprehensive unit tests covering multi-failure detection.

**Test Cases**:
1. Single failure (markdown fidelity only)
2. Multiple failures (markdown + line count)
3. All checks failing
4. Primary category selection (severity ranking)
5. No verification data (edge case)

**Acceptance Criteria**:
- All test cases pass
- Coverage ≥90% for classify_failure()
- Tests run in CI/pytest suite

---

#### TASK-1.5: Validate on Known Multi-Failure Cases
**Status**: PENDING

**Description**: Test new classification on 71 known "Verification failed" generic error files.

**Evidence Command**:
```bash
# Extract multi-failure candidates
python -c "
import json
with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]
multi = [r for r in records if r['reason'] == 'Verification failed']
print(f'Multi-failure candidates: {len(multi)}')
for r in multi[:5]:
    print(f\"  {r['source_path']}\")
" > multi_failure_candidates.txt

# Re-verify with new classification
for file in $(cat multi_failure_candidates.txt); do
    python scripts/e2e_verify_single_file.py \
        --source "D:\...\content\\${file}" \
        --target "D:\...\content\\$(echo $file | sed 's/en/fr/')" \
        --lang fr \
        --json-output "retest_${file}.json"
    # Check combined_failures field populated
    cat "retest_${file}.json" | jq '.combined_failures'
done
```

**Acceptance Criteria**:
- At least 50 of 71 files show multiple failures in combined_failures
- FAIL_OTHER percentage drops significantly
- All files have accurate primary category

---

## Workstream 2: Verifier Failure Investigation
**Owner**: Agent C (Investigation & Diagnostics)
**Priority**: HIGH
**Status**: PENDING

### Tasks

#### TASK-2.1: Extract and Catalog 49 No-Data Cases
**Status**: PENDING

**Description**: Create structured catalog of all 49 "no verification data" cases with metadata.

**Evidence Command**:
```bash
python -c "
import json
with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]
no_data = [r for r in records if r.get('reason') == 'No verification data']
print(f'Total no-data cases: {len(no_data)}')

# Export detailed catalog
import csv
with open('no_data_catalog.csv', 'w', newline='', encoding='utf-8') as csvfile:
    fieldnames = ['family', 'subdomain', 'source_path', 'target_path', 'batch_num']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for r in no_data:
        writer.writerow({
            'family': r['family'],
            'subdomain': r['subdomain'],
            'source_path': r['source_path'],
            'target_path': r['target_path'],
            'batch_num': r.get('batch_num', 'N/A')
        })
print('Catalog written to no_data_catalog.csv')
"
```

**Acceptance Criteria**:
- CSV catalog with all 49 cases
- Includes family, subdomain, paths, batch number
- Ready for systematic investigation

---

#### TASK-2.2: Check Target File Existence
**Status**: PENDING

**Description**: Verify whether target files actually exist for no-data cases (translation may have failed silently).

**Evidence Command**:
```bash
# Check file existence
python -c "
import json
from pathlib import Path

CONTENT_ROOT = Path(r'D:\\onedrive\\Documents\\GitHub\\aspose.net\\content')

with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]
no_data = [r for r in records if r.get('reason') == 'No verification data']

exists_count = 0
missing_count = 0

for r in no_data:
    target_path = CONTENT_ROOT / r['target_path']
    if target_path.exists():
        exists_count += 1
        print(f'EXISTS: {r[\"target_path\"]}')
    else:
        missing_count += 1
        print(f'MISSING: {r[\"target_path\"]}')

print(f'\\nSummary:')
print(f'  Files exist: {exists_count}')
print(f'  Files missing: {missing_count}')
"
```

**Acceptance Criteria**:
- Categorized: X files exist, Y files missing
- If missing: translation failed (investigate TASK-2.3)
- If exist: verifier crashed (investigate TASK-2.4)

---

#### TASK-2.3: Analyze Translation Logs for Missing Files
**Status**: PENDING (depends on TASK-2.2)

**Description**: For files where target doesn't exist, review translation logs to determine why.

**Evidence Command**:
```bash
# For each missing file, check batch translation log
# Batch logs: logs/batch_{batch_num}__translate.log

python -c "
import json
from pathlib import Path

with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]
no_data = [r for r in records if r.get('reason') == 'No verification data']

# Group by batch
from collections import defaultdict
by_batch = defaultdict(list)
for r in no_data:
    by_batch[r.get('batch_num', 'unknown')].append(r)

for batch_num, files in sorted(by_batch.items()):
    print(f'Batch {batch_num}: {len(files)} files')
    log_path = f'reports/phase6_cli_forced_translate/20260128-2139/logs/batch_{batch_num}__translate.log'
    # Analyze log for errors
"
```

**Acceptance Criteria**:
- Root cause identified for missing files
- Common error patterns documented
- Fix proposed for translation failure mode

---

#### TASK-2.4: Analyze Verifier Logs for Crashed Cases
**Status**: PENDING (depends on TASK-2.2)

**Description**: For files where target exists but no JSON produced, analyze verifier logs for crash patterns.

**Evidence Command**:
```bash
# Check verifier logs for exceptions
grep -i "error\|exception\|traceback" reports/phase6_cli_forced_translate/20260128-2139/logs/*__verify.log

# Specific check for no-data cases
python -c "
import json
from pathlib import Path

with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]
no_data = [r for r in records if r.get('reason') == 'No verification data']

for r in no_data:
    # Compute file_key
    import hashlib
    path_hash = hashlib.md5(r['source_path'].encode('utf-8')).hexdigest()[:8]
    subdomain_sanitized = r['subdomain'].replace('.', '_')
    file_key = f\"{r['family']}__{subdomain_sanitized}__{path_hash}\"

    log_path = Path(f'reports/phase6_cli_forced_translate/20260128-2139/logs/{file_key}__verify.log')
    if log_path.exists():
        with open(log_path) as f:
            content = f.read()
            if 'error' in content.lower() or 'exception' in content.lower():
                print(f'{file_key}: ERROR DETECTED')
                print(content[-500:])  # Last 500 chars
                print('---')
"
```

**Acceptance Criteria**:
- Exception patterns identified
- Common crash causes documented
- Fix proposed for verifier robustness

---

#### TASK-2.5: Add Verifier Pre-Flight Checks
**File**: `scripts/e2e_verify_single_file.py`
**Status**: PENDING (depends on TASK-2.2, TASK-2.4)

**Description**: Add pre-flight validation to catch errors before JSON write failure.

**Checks to Add**:
1. Target file exists and readable
2. Target file valid UTF-8
3. Target file not empty
4. Source file exists and readable
5. Write permission for JSON output path

**Acceptance Criteria**:
- All pre-flight checks implemented
- Errors return structured JSON with error field
- No crash scenarios leave JSON unwritten

---

#### TASK-2.6: Add Verifier Exception Handling
**File**: `scripts/e2e_verify_single_file.py`
**Status**: PENDING (depends on TASK-2.4)

**Description**: Wrap verifier logic in try-except to always produce JSON, even on error.

**Target Pattern**:
```python
def main():
    try:
        # Pre-flight checks
        validate_inputs()

        # Run verification
        results = run_verification()

        # Write JSON
        with open(json_output, 'w') as f:
            json.dump(results, f, indent=2)

        sys.exit(0 if results['passed'] else 1)

    except Exception as e:
        # Always write JSON, even on error
        error_result = {
            "passed": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        with open(json_output, 'w') as f:
            json.dump(error_result, f, indent=2)
        sys.exit(1)
```

**Acceptance Criteria**:
- All code paths produce JSON output
- Errors include structured diagnostic info
- Exit codes still indicate failure

---

## Workstream 3: Threshold Appropriateness Review
**Owner**: Agent C (Investigation & Diagnostics)
**Priority**: MEDIUM
**Status**: PENDING

### Tasks

#### TASK-3.1: Extract Line Count Failure Data
**Status**: PENDING

**Description**: Collect all 15 line count threshold failures with source/target line counts.

**Evidence Command**:
```bash
python -c "
import json
with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]

# Find line count failures in reason field
line_fails = [r for r in records if 'Line count too low' in str(r.get('reason', ''))]

print(f'Line count failures: {len(line_fails)}')
print('\\nDetails:')
for r in line_fails:
    print(f\"  {r['source_path']}\")
    print(f\"    Reason: {r['reason']}\")
    print()
" > line_count_analysis.txt
```

**Acceptance Criteria**:
- List of 15 files with line counts
- Source lines, target lines, threshold documented
- Ready for linguistic analysis

---

#### TASK-3.2: Analyze Passing File Line Count Ratios
**Status**: PENDING

**Description**: Calculate line count ratios for passing files to determine normal EN→FR compression.

**Evidence Command**:
```bash
python -c "
import json
from pathlib import Path

# Need to parse verify.json for each passing file to get line counts
ARTIFACTS_DIR = Path('reports/phase6_cli_forced_translate/20260128-2139/artifacts')

with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]

passing = [r for r in records if r['status'] == 'PASS']

ratios = []
for r in passing:
    # Compute file_key to find verify.json
    import hashlib
    path_hash = hashlib.md5(r['source_path'].encode('utf-8')).hexdigest()[:8]
    subdomain_sanitized = r['subdomain'].replace('.', '_')
    file_key = f\"{r['family']}__{subdomain_sanitized}__{path_hash}\"

    verify_json = ARTIFACTS_DIR / f'{file_key}__verify.json'
    if verify_json.exists():
        with open(verify_json) as f:
            verify_data = json.load(f)
            line_check = verify_data.get('checks', {}).get('line_count', {})
            src_lines = line_check.get('source', 0)
            tgt_lines = line_check.get('target', 0)
            if src_lines > 0:
                ratio = tgt_lines / src_lines
                ratios.append(ratio)

if ratios:
    import statistics
    print(f'Sample size: {len(ratios)} passing files')
    print(f'Mean ratio: {statistics.mean(ratios):.2%}')
    print(f'Median ratio: {statistics.median(ratios):.2%}')
    print(f'Min ratio: {min(ratios):.2%}')
    print(f'Max ratio: {max(ratios):.2%}')
    print(f'\\nCurrent threshold: 95%')
    print(f'Recommendation: ???')
"
```

**Acceptance Criteria**:
- Mean/median EN→FR line count ratio calculated
- Distribution analysis complete
- Data-driven recommendation for threshold

---

#### TASK-3.3: Research French Language Efficiency
**Status**: PENDING

**Description**: Research linguistic literature on French vs English text length.

**Research Questions**:
1. Is French typically shorter or longer than English?
2. What's typical compression ratio for technical documentation?
3. Are there domain-specific patterns (API docs vs narrative)?

**Sources to Check**:
- Translation industry standards
- Academic papers on language efficiency
- Translation memory statistics from other projects

**Acceptance Criteria**:
- Summary of research findings
- Citation of authoritative sources
- Comparison to empirical data from TASK-3.2

---

#### TASK-3.4: Propose Threshold Update
**Status**: PENDING (depends on TASK-3.2, TASK-3.3)

**Description**: Based on empirical data and research, propose new threshold or keep 95%.

**Decision Matrix**:
- If mean ratio ≥95%: Keep 95% threshold (failures are legitimate)
- If mean ratio 90-94%: Relax to 90% (current threshold too strict)
- If mean ratio <90%: Investigate further (unusual pattern)

**Acceptance Criteria**:
- Clear recommendation with justification
- Risk analysis (false negatives from relaxing)
- Implementation plan if change approved

---

## Workstream 4: AST Reconstruction Improvement
**Owner**: Agent B (Code Implementation)
**Priority**: HIGH
**Status**: PENDING

### Tasks

#### TASK-4.1: Extract and Categorize Markdown Fidelity Failures
**Status**: PENDING

**Description**: Analyze 37 markdown fidelity failures to identify common patterns.

**Evidence Command**:
```bash
python -c "
import json
from collections import Counter

with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]

md_fails = [r for r in records if r['status'] == 'FAIL_MARKDOWN_FIDELITY']

print(f'Total markdown fidelity failures: {len(md_fails)}')
print('\\nPattern analysis:')

# Analyze which element types fail most
bold_mismatches = []
italic_mismatches = []
for r in md_fails:
    m = r.get('metrics', {})
    bold_src = m.get('bold_src', 0)
    bold_tgt = m.get('bold_tgt', 0)
    italic_src = m.get('italic_src', 0)
    italic_tgt = m.get('italic_tgt', 0)

    if bold_src != bold_tgt:
        bold_mismatches.append((r['source_path'], bold_src, bold_tgt))
    if italic_src != italic_tgt:
        italic_mismatches.append((r['source_path'], italic_src, italic_tgt))

print(f'\\nBold mismatches: {len(bold_mismatches)}')
for path, src, tgt in bold_mismatches[:5]:
    print(f'  {path}: {src} → {tgt} (delta: {tgt-src:+d})')

print(f'\\nItalic mismatches: {len(italic_mismatches)}')
for path, src, tgt in italic_mismatches[:5]:
    print(f'  {path}: {src} → {tgt} (delta: {tgt-src:+d})')
" > markdown_pattern_analysis.txt
```

**Acceptance Criteria**:
- Patterns identified (bold most common? italic? lists?)
- Delta analysis (+1, -1, larger changes?)
- Top 10 files for manual inspection

---

#### TASK-4.2: Manual Inspection of Top Failures
**Status**: PENDING (depends on TASK-4.1)

**Description**: Manually inspect 5 worst markdown fidelity failures to understand root cause.

**Process**:
1. Unzip failure bundle
2. Diff source.md vs target.md
3. Identify where formatting lost (bold, italic, lists, etc.)
4. Trace back to AST reconstruction code

**Acceptance Criteria**:
- Root cause hypothesis for each of 5 cases
- Common patterns identified across cases
- Specific code locations identified for fixes

---

#### TASK-4.3: Review AST Renderer Code
**File**: `src/translation_engine/reconstructor/ast_renderer.py`
**Status**: PENDING (depends on TASK-4.2)

**Description**: Review AST renderer implementation for bold/italic/list preservation issues.

**Focus Areas**:
1. Bold span rendering logic
2. Italic span rendering logic
3. Link rendering
4. List nesting preservation
5. Heading level preservation

**Acceptance Criteria**:
- Code review notes documenting potential issues
- Specific functions/lines flagged for fixes
- Test cases identified for each issue

---

#### TASK-4.4: Implement Bold/Italic Preservation Fixes
**File**: `src/translation_engine/reconstructor/ast_renderer.py`
**Status**: PENDING (depends on TASK-4.3)

**Description**: Fix identified issues with bold/italic preservation during AST rendering.

**Acceptance Criteria**:
- Bold span counts match source ±1 tolerance
- Italic span counts match source ±1 tolerance
- Existing regression tests still pass
- New tests added for fixed cases

---

#### TASK-4.5: Implement List/Link Preservation Fixes
**File**: `src/translation_engine/reconstructor/ast_renderer.py`
**Status**: PENDING (depends on TASK-4.3)

**Description**: Fix identified issues with list nesting and link preservation.

**Acceptance Criteria**:
- List nesting depth preserved
- Link counts match source
- List item counts match source
- No list concatenation regressions

---

#### TASK-4.6: Add Regression Tests for Formatting
**File**: `tests/regression/test_markdown_formatting_preservation.py` (new)
**Status**: PENDING (depends on TASK-4.4, TASK-4.5)

**Description**: Create comprehensive regression test suite for markdown formatting preservation.

**Test Cases**:
1. Bold spans preserved (multiple bold in same paragraph)
2. Italic spans preserved (nested emphasis)
3. Bold+italic combination preserved
4. Links preserved (inline and reference style)
5. Nested lists preserved (3+ levels)
6. Heading levels preserved
7. Mixed formatting in complex documents

**Acceptance Criteria**:
- All test cases pass
- Tests use real-world samples from Phase 6 failures
- Tests run in CI/pytest suite

---

#### TASK-4.7: Validate Fixes on Known Failures
**Status**: PENDING (depends on TASK-4.4, TASK-4.5, TASK-4.6)

**Description**: Re-translate and verify the 37 markdown fidelity failures with fixed code.

**Evidence Command**:
```bash
# Extract list of 37 files
python -c "
import json
with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    records = [json.loads(line) for line in f]
md_fails = [r for r in records if r['status'] == 'FAIL_MARKDOWN_FIDELITY']
with open('md_fails_retest.txt', 'w') as out:
    for r in md_fails:
        out.write(r['source_path'] + '\\n')
"

# Re-translate each file
python -m src.cli \
    --site docs.aspose.net \
    --input md_fails_retest.txt \
    --target-langs fr \
    --force-retranslate

# Re-verify each file
# (automated verification loop)

# Compare pass rates
echo "Before: 0/37 passed (100% failure)"
echo "After: ???/37 passed (target: ≥80% passing)"
```

**Acceptance Criteria**:
- ≥80% of previous failures now pass (30/37 files)
- Remaining failures investigated separately
- No new regressions introduced

---

## Workstream 5: Batch-23 Duplication Bug Fix
**Owner**: Agent B (Code Implementation)
**Priority**: MEDIUM
**Status**: PENDING

### Tasks

#### TASK-5.1: Identify Duplication Root Cause
**File**: `reports/phase6_cli_forced_translate/20260128-2139/run_batch23.py:346-363`
**Status**: PENDING

**Description**: Analyze batching logic to determine where 132 duplicates originated.

**Code to Analyze**:
```python
# Create batches
all_batches = []
for site_id, rows in sites.items():
    # Split into batches of BATCH_SIZE
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i+BATCH_SIZE]
        all_batches.append(batch)
```

**Hypothesis**: Batch boundaries overlap due to off-by-one error or incorrect range step.

**Acceptance Criteria**:
- Root cause definitively identified
- Reproducible test case created
- Fix design documented

---

#### TASK-5.2: Fix Batch Boundary Calculation
**File**: `reports/phase6_cli_forced_translate/20260128-2139/run_batch23.py:346-363`
**Status**: PENDING (depends on TASK-5.1)

**Description**: Implement fix to prevent batch overlap.

**Potential Fixes**:
1. Add deduplication check before appending batch
2. Fix range calculation (verify step is correct)
3. Add assertion to validate total files == sum of batch sizes

**Acceptance Criteria**:
- No duplicate files in batch creation
- Total files in all batches equals inventory size (248)
- Test with Phase 6 inventory confirms 248 unique files

---

#### TASK-5.3: Add Deduplication Guard
**File**: `reports/phase6_cli_forced_translate/20260128-2139/run_batch23.py:237-311`
**Status**: PENDING (depends on TASK-5.2)

**Description**: Add runtime deduplication check to catch regressions.

**Guard Logic**:
```python
# In verify_batch() before processing
seen_paths = set()
for row in batch_rows:
    source_path = row["source_path"]
    if source_path in seen_paths:
        print(f"ERROR: Duplicate file in batch: {source_path}")
        raise ValueError(f"Duplicate file detected: {source_path}")
    seen_paths.add(source_path)
```

**Acceptance Criteria**:
- Duplicate detection added to batch processing
- Raises clear error if duplicate detected
- Logs duplicate path for debugging

---

#### TASK-5.4: Add Unit Test for Batch Logic
**File**: `tests/unit/test_batch_creation.py` (new)
**Status**: PENDING (depends on TASK-5.2)

**Description**: Create unit test to prevent future batch duplication regressions.

**Test Cases**:
1. Single site, exact multiple of batch size (23, 46, 69 files)
2. Single site, non-multiple (25, 50, 100 files)
3. Multiple sites with varying file counts
4. Edge case: 1 file per site
5. Edge case: 0 files (empty inventory)

**Acceptance Criteria**:
- All test cases pass
- Tests validate: no duplicates, all files included, batch sizes ≤23
- Tests run in CI/pytest suite

---

#### TASK-5.5: Validate Fix with Phase 6 Inventory
**Status**: PENDING (depends on TASK-5.2, TASK-5.3)

**Description**: Run fixed batch runner on Phase 6 inventory to confirm 248 unique records.

**Evidence Command**:
```bash
# Clear previous progress
rm reports/phase6_cli_forced_translate/20260128-2139/progress.ndjson

# Run fixed batch-23 runner
python reports/phase6_cli_forced_translate/20260128-2139/run_batch23.py

# Validate no duplicates
python -c "
import json
with open('reports/phase6_cli_forced_translate/20260128-2139/progress.ndjson') as f:
    records = [json.loads(line) for line in f]

total = len(records)
unique_paths = len(set(r['source_path'] for r in records))

print(f'Total records: {total}')
print(f'Unique paths: {unique_paths}')

if total != unique_paths:
    print(f'ERROR: {total - unique_paths} duplicates detected')
    sys.exit(1)
elif total != 248:
    print(f'ERROR: Expected 248 records, got {total}')
    sys.exit(1)
else:
    print('✓ No duplicates, all 248 files processed exactly once')
"
```

**Acceptance Criteria**:
- Exactly 248 records in progress.ndjson
- All 248 paths unique
- No files missing, no files duplicated

---

## Integration & Validation Tasks
**Owner**: Agent B (Code Implementation)
**Priority**: CRITICAL
**Status**: PENDING

### TASK-INT-1: Merge All Fixes into Single Branch
**Status**: PENDING (depends on all workstream tasks)

**Description**: Integrate all fixes from 5 workstreams into unified codebase.

**Process**:
1. Create integration branch: `feature/phase6-remediation`
2. Cherry-pick all commits from workstream branches
3. Resolve any merge conflicts
4. Run full test suite

**Acceptance Criteria**:
- All fixes integrated without conflicts
- No regressions introduced
- Git history clean and documented

---

### TASK-INT-2: Run Full Pytest Suite
**Status**: PENDING (depends on TASK-INT-1)

**Evidence Command**:
```bash
pytest tests/ -v --tb=short
```

**Acceptance Criteria**:
- All tests pass (0 failures)
- No new warnings introduced
- Coverage maintained or improved

---

### TASK-INT-3: Manual Smoke Test on 5 Sample Files
**Status**: PENDING (depends on TASK-INT-1)

**Description**: Manually verify 5 diverse files translate and verify successfully.

**Sample Files**:
1. Simple page (low complexity)
2. API reference (code-heavy)
3. Tutorial (prose-heavy)
4. Nested lists (structure complexity)
5. Large document (>500 lines)

**Process**:
```bash
# Translate
python -m src.cli \
    --site docs.aspose.net \
    --input smoke_test_files.txt \
    --target-langs fr \
    --force-retranslate

# Verify
for file in $(cat smoke_test_files.txt); do
    python scripts/e2e_verify_single_file.py \
        --source "$file" \
        --target "${file/en/fr}" \
        --lang fr \
        --json-output "smoke_${file}.json"
done

# Check results
python -c "
import json
from pathlib import Path
results = []
for p in Path('.').glob('smoke_*.json'):
    with open(p) as f:
        data = json.load(f)
        results.append(data.get('passed', False))
print(f'Smoke test: {sum(results)}/{len(results)} passed')
"
```

**Acceptance Criteria**:
- ≥4/5 files pass all quality gates
- Any failures have clear diagnostic info
- No crashes or infrastructure errors

---

### TASK-INT-4: Re-Run Phase 6 Validation (Full 248 Files)
**Status**: PENDING (depends on TASK-INT-2, TASK-INT-3)

**Description**: Execute complete Phase 6 validation with all fixes applied.

**Process**:
```bash
# Create new run directory
mkdir -p reports/phase6_cli_forced_translate/RERUN_20260129
cd reports/phase6_cli_forced_translate/RERUN_20260129

# Copy inventory
cp ../20260128-2139/inventory.csv .
cp ../20260128-2139/inventory_by_combo/ . -r

# Copy fixed batch-23 runner
cp ../../../<fixed_runner_path>/run_batch23.py .

# Execute
python run_batch23.py | tee full_run.log
```

**Acceptance Criteria**:
- All 248 files processed
- No crashes or infrastructure failures
- Progress.ndjson contains exactly 248 unique records

---

### TASK-INT-5: Compare Pass Rates (Before vs After)
**Status**: PENDING (depends on TASK-INT-4)

**Evidence Command**:
```bash
python -c "
import json

print('BEFORE REMEDIATION:')
with open('reports/phase6_cli_forced_translate/20260128-2139/progress_deduplicated.ndjson') as f:
    before = [json.loads(line) for line in f]
pass_before = sum(1 for r in before if r['status'] == 'PASS')
print(f'  Pass rate: {pass_before}/{len(before)} ({100*pass_before/len(before):.1f}%)')

print('\\nAFTER REMEDIATION:')
with open('reports/phase6_cli_forced_translate/RERUN_20260129/progress.ndjson') as f:
    after = [json.loads(line) for line in f]
pass_after = sum(1 for r in after if r['status'] == 'PASS')
print(f'  Pass rate: {pass_after}/{len(after)} ({100*pass_after/len(after):.1f}%)')

print('\\nIMPROVEMENT:')
improvement = pass_after - pass_before
pct_improvement = 100 * (pass_after/len(after) - pass_before/len(before))
print(f'  Absolute: +{improvement} files')
print(f'  Relative: +{pct_improvement:.1f} percentage points')

print('\\nTARGET: ≥50% pass rate')
if pass_after / len(after) >= 0.50:
    print('✓ TARGET ACHIEVED')
else:
    print('✗ TARGET NOT MET - Further investigation required')
"
```

**Acceptance Criteria**:
- Pass rate ≥50% (target met)
- Absolute improvement ≥80 files (33→113+)
- No regressions (passing files still pass)

---

### TASK-INT-6: Validate Acceptance Criteria
**Status**: PENDING (depends on TASK-INT-4, TASK-INT-5)

**Description**: Verify all plan acceptance criteria met.

**Criteria Checklist**:
- [ ] FAIL_OTHER <10% (was 70%)
- [ ] No verification data cases = 0 (was 49)
- [ ] Pass rate ≥50% (was 13.3%)
- [ ] No duplicates in progress.ndjson (was 132)
- [ ] FAIL_MARKDOWN_FIDELITY <5% (was 15%)

**Evidence**: Run all comparison scripts from plan's "Evidence Commands for Post-Remediation Validation" section.

**Acceptance Criteria**:
- All 5 criteria met
- Evidence documented in validation report
- Any unmet criteria have mitigation plan

---

## Documentation Tasks
**Owner**: Agent D (Documentation)
**Priority**: MEDIUM
**Status**: PENDING

### TASK-DOC-1: Create Remediation Report
**File**: `reports/phase6_cli_forced_translate/REMEDIATION_REPORT.md` (new)
**Status**: PENDING (depends on TASK-INT-6)

**Content**:
1. Executive summary (pass rate improvement, key fixes)
2. Detailed findings from each workstream
3. Before/after metrics comparison
4. Remaining issues (if any)
5. Recommendations for production deployment

**Acceptance Criteria**:
- Comprehensive report documenting entire remediation process
- Includes all evidence commands and results
- Executive summary suitable for stakeholder communication

---

### TASK-DOC-2: Update FINAL_RESULTS.md
**File**: `reports/phase6_cli_forced_translate/20260128-2139/FINAL_RESULTS.md`
**Status**: PENDING (depends on TASK-DOC-1)

**Updates**:
- Add "Remediation Status" section
- Link to REMEDIATION_REPORT.md
- Update "Next Steps" with completion status

**Acceptance Criteria**:
- FINAL_RESULTS.md reflects remediation completion
- Links to follow-up documentation
- Status clearly indicates "REMEDIATED" for completed gaps

---

### TASK-DOC-3: Update PLAN_SOURCES.md
**File**: `reports/PLAN_SOURCES.md`
**Status**: PENDING (depends on TASK-DOC-1, TASK-DOC-2)

**Updates**:
- Mark Phase 6 remediation section as COMPLETE
- Add links to remediation report and re-run results
- Update status from "AWAITING USER INPUT" to "COMPLETE"

**Acceptance Criteria**:
- PLAN_SOURCES.md reflects project completion
- All links functional
- Status accurately reflects project state

---

## Success Metrics Dashboard

### Current Status (Before Remediation)
| Metric | Value | Target |
|--------|-------|--------|
| Pass Rate | 13.3% (33/248) | ≥50% |
| FAIL_OTHER | 70.2% (174/248) | <10% |
| No Verification Data | 19.8% (49/248) | 0% |
| Markdown Fidelity Failures | 14.9% (37/248) | <5% |
| Duplicate Records | 132 | 0 |

### Target Status (After Remediation)
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Pass Rate | TBD | ≥50% | ⏳ PENDING |
| FAIL_OTHER | TBD | <10% | ⏳ PENDING |
| No Verification Data | TBD | 0% | ⏳ PENDING |
| Markdown Fidelity Failures | TBD | <5% | ⏳ PENDING |
| Duplicate Records | TBD | 0 | ⏳ PENDING |

---

## Task Dependencies

```
Workstream 1 (Classification):
  TASK-1.1 → TASK-1.2 → TASK-1.3 → TASK-1.4 → TASK-1.5

Workstream 2 (Verifier):
  TASK-2.1 → TASK-2.2 → [TASK-2.3, TASK-2.4] → TASK-2.5 → TASK-2.6

Workstream 3 (Threshold):
  TASK-3.1 → [TASK-3.2, TASK-3.3] → TASK-3.4

Workstream 4 (AST):
  TASK-4.1 → TASK-4.2 → TASK-4.3 → [TASK-4.4, TASK-4.5] → TASK-4.6 → TASK-4.7

Workstream 5 (Batch):
  TASK-5.1 → TASK-5.2 → [TASK-5.3, TASK-5.4] → TASK-5.5

Integration:
  [All Workstreams] → TASK-INT-1 → TASK-INT-2 → TASK-INT-3 → TASK-INT-4 → TASK-INT-5 → TASK-INT-6

Documentation:
  TASK-INT-6 → TASK-DOC-1 → TASK-DOC-2 → TASK-DOC-3
```

---

## Next Steps

1. **Agent Assignment**: Assign Agent B, Agent C, Agent D based on workstream ownership
2. **Parallel Execution**: Launch Workstreams 1-5 in parallel (independent tasks)
3. **Progress Tracking**: Update task status in this file as work completes
4. **Quality Gates**: Each task must pass 12-dimension self-review before marking complete
5. **Integration**: Merge all fixes and run full validation
6. **Sign-Off**: Review final metrics against acceptance criteria

---

**Backlog Status**: Ready for agent assignment and execution
**Last Updated**: 2026-01-29 00:30:00 UTC

---
---

# Task Backlog - Telemetry HTTP API Consistency

**Plan**: [hidden-marinating-dongarra.md](C:\Users\prora\.claude\plans\hidden-marinating-dongarra.md)
**Created**: 2026-02-03
**Status**: READY_FOR_EXECUTION

---

## Overview

Systematic update to consistently use local-telemetry HTTP REST API (v2.2.0) across all services (manual/automatic). Update documentation and configuration to reflect implemented truth. **Key Finding:** HTTP API integration already works correctly—only documentation and configuration templates needed.

**Scope:**
- ✅ No code changes required (HTTP API already implemented correctly)
- 📝 Documentation updates (remove outdated package references)
- ⚙️ Configuration templates (standardize token handling)
- ✅ Validation (verify all 50+ integration points)

---

## Workstream A: Discovery & Architecture Validation
**Owner**: Agent A (Discovery)
**Priority**: HIGH
**Status**: ✅ COMPLETE (exploration phase completed in plan mode)

### Findings Summary

#### FINDING-A.1: 50+ Integration Points Use HTTP API Correctly
**Status**: ✅ VERIFIED

**Evidence**: Exploration agent (a7c84e1) found:
- Primary abstraction: `src/observability/telemetry_integration.py` - `TranslationTelemetry` class
- Uses `requests` library for HTTP calls to `http://localhost:8765`
- Graceful degradation when API unavailable
- Integration points:
  1. CLI entry (`src/cli.py`)
  2. Translation engine (`src/translation_engine/engine.py`)
  3. Distributed workers
  4. Batch orchestrator

**Conclusion**: All integration points already use HTTP API correctly. No code changes needed.

---

#### FINDING-A.2: Documentation State
**Status**: ✅ VERIFIED

**Evidence**: Exploration agent (af6b644) found 15 documentation files:
- ✅ `docs/reference/local-telemetry.md` - Perfect HTTP API v2.2.0 reference
- ⚠️ `docs/operations/TELEMETRY_MIGRATION_GUIDE.md` - May reference old package installation
- ⚠️ `docs/operations/TELEMETRY_ROLLBACK_GUIDE.md` - May reference old package patterns

**Conclusion**: Minor documentation cleanup needed (Task 1).

---

#### FINDING-A.3: Configuration State
**Status**: ✅ VERIFIED

**Evidence**: Exploration agent (ade45d7) found:
- `.env` (dev): `METRICS_API_URL=http://localhost:8765`, `METRICS_API_ENABLED=true`, `METRICS_API_TOKEN=test-token-12345`
- `config/global.yaml`: telemetry config present with timeout/retry settings
- `docker-compose.yml`: telemetry service configured correctly
- ⚠️ `.env.production` - MISSING
- ⚠️ `.env.test` - MISSING

**Conclusion**: Configuration consistency needed (Task 2).

---

## Workstream B: Documentation Updates
**Owner**: Agent D (Documentation)
**Priority**: HIGH
**Status**: PENDING

### Tasks

#### TASK-TELEM-1.1: Audit Migration Guide
**File**: `docs/operations/TELEMETRY_MIGRATION_GUIDE.md`
**Status**: PENDING

**Description**: Read migration guide and check for outdated "pip install" or package references.

**Evidence Command**:
```bash
grep -i "pip install\|package\|import telemetry" docs/operations/TELEMETRY_MIGRATION_GUIDE.md
```

**Expected Findings**:
- References to "telemetry package installation" (if present, remove)
- Instructions for package management (if present, replace with HTTP API docs)

**Acceptance Criteria**:
- No references to "pip install telemetry" or package management
- All instructions point to HTTP API as integration method
- References `docs/reference/local-telemetry.md` as canonical source

---

#### TASK-TELEM-1.2: Audit Rollback Guide
**File**: `docs/operations/TELEMETRY_ROLLBACK_GUIDE.md`
**Status**: PENDING

**Description**: Read rollback guide and update to focus on configuration toggle, not package removal.

**Evidence Command**:
```bash
grep -i "uninstall\|package\|pip" docs/operations/TELEMETRY_ROLLBACK_GUIDE.md
```

**Expected Findings**:
- References to package uninstallation (if present, remove)
- Outdated rollback procedures (if present, update)

**Acceptance Criteria**:
- Rollback procedure: disable `METRICS_API_ENABLED=false` in `.env`
- No references to package removal
- Clear steps for disabling/enabling telemetry via configuration

---

#### TASK-TELEM-1.3: Update Migration Guide (if needed)
**File**: `docs/operations/TELEMETRY_MIGRATION_GUIDE.md`
**Status**: PENDING (depends on TASK-TELEM-1.1)

**Description**: Remove package references and emphasize HTTP API as only integration method.

**Changes**:
- Remove: Any "pip install telemetry" instructions
- Add: HTTP API is the **only** integration method
- Add: Reference to `docs/reference/local-telemetry.md`

**Acceptance Criteria**:
- Clear statement: HTTP API is primary integration
- No confusion about package vs API
- Links to canonical API documentation

---

#### TASK-TELEM-1.4: Update Rollback Guide (if needed)
**File**: `docs/operations/TELEMETRY_ROLLBACK_GUIDE.md`
**Status**: PENDING (depends on TASK-TELEM-1.2)

**Description**: Focus rollback procedure on configuration toggle.

**Changes**:
- Remove: Package uninstall procedures
- Add: Configuration-based rollback (toggle `.env` flag)

**Acceptance Criteria**:
- Rollback = set `METRICS_API_ENABLED=false`
- No references to package removal
- Graceful degradation behavior documented

---

#### TASK-TELEM-1.5: Create Environment Variables Guide
**File**: `docs/setup/ENVIRONMENT_VARIABLES.md` (new)
**Status**: PENDING

**Description**: Document required environment variables for each deployment type.

**Content**:
1. Development environment (`METRICS_API_URL`, `METRICS_API_ENABLED`, `METRICS_API_TOKEN`)
2. Production environment (same variables, different values)
3. Test environment (telemetry disabled)
4. How to verify telemetry working (`curl http://localhost:8765/health`)

**Acceptance Criteria**:
- All environment types documented
- Clear examples for each environment
- Health check instructions included

---

## Workstream C: Configuration Templates
**Owner**: Agent B (Implementation)
**Priority**: HIGH
**Status**: PENDING

### Tasks

#### TASK-TELEM-2.1: Audit Configuration Files
**Status**: PENDING

**Description**: Comprehensive audit of all telemetry configuration files.

**Evidence Command**:
```bash
# Find all telemetry config references
grep -r "METRICS_API\|telemetry:" config/ .env* docker-compose.yml
```

**Acceptance Criteria**:
- List of all files with telemetry configuration
- Identification of inconsistencies
- Ready for template creation

---

#### TASK-TELEM-2.2: Create .env.production Template
**File**: `.env.production` (new)
**Status**: PENDING (depends on TASK-TELEM-2.1)

**Description**: Create production environment template with proper token handling.

**Content**:
```env
METRICS_API_URL=http://telemetry-service:8765
METRICS_API_ENABLED=true
METRICS_API_TOKEN=${TELEMETRY_TOKEN}  # Must be set in deployment
```

**Acceptance Criteria**:
- Template file created
- Token placeholder documented
- Production URL configured (not localhost)

---

#### TASK-TELEM-2.3: Create .env.test Template
**File**: `.env.test` (new)
**Status**: PENDING (depends on TASK-TELEM-2.1)

**Description**: Create test environment template with telemetry disabled.

**Content**:
```env
METRICS_API_URL=http://localhost:8765
METRICS_API_ENABLED=false  # Disabled for unit tests
METRICS_API_TOKEN=test-token-not-used
```

**Acceptance Criteria**:
- Template file created
- Telemetry disabled for tests
- Clear comment explaining why disabled

---

#### TASK-TELEM-2.4: Verify Global Config
**File**: `config/global.yaml`
**Status**: PENDING (depends on TASK-TELEM-2.1)

**Description**: Verify telemetry section in global config is complete and correct.

**Check**:
```yaml
telemetry:
  enabled: true
  api_url: "http://localhost:8765"
  api_token: "${METRICS_API_TOKEN}"
  timeout_seconds: 5
  retry_attempts: 3
```

**Acceptance Criteria**:
- All settings present
- Timeout/retry settings appropriate
- Token reads from environment variable

---

#### TASK-TELEM-2.5: Document Configuration Pattern
**Status**: PENDING (depends on TASK-TELEM-2.2, TASK-TELEM-2.3, TASK-TELEM-2.4)

**Description**: Document standardized configuration pattern in environment variables guide.

**Updates to**: `docs/setup/ENVIRONMENT_VARIABLES.md`

**Content**:
- Development configuration pattern
- Production configuration pattern
- Test configuration pattern
- Fallback behavior when token missing

**Acceptance Criteria**:
- All patterns documented
- Examples provided for each environment
- Graceful degradation behavior explained

---

## Workstream D: Code Validation (No Changes)
**Owner**: Agent C (Tests & Verification)
**Priority**: MEDIUM
**Status**: PENDING

### Tasks

#### TASK-TELEM-3.1: Verify Abstraction Layer Uses HTTP
**File**: `src/observability/telemetry_integration.py`
**Status**: PENDING

**Description**: Verify `TranslationTelemetry` uses `requests` library for HTTP calls.

**Evidence Command**:
```bash
grep -n "import requests\|requests.post\|requests.patch" src/observability/telemetry_integration.py
```

**Acceptance Criteria**:
- `requests` library used for HTTP calls
- Endpoints match API v2.2.0 spec (`/api/v1/runs`, `/api/v1/runs/{id}/associate-commit`)
- No direct telemetry package imports (except graceful degradation fallback)

---

#### TASK-TELEM-3.2: Verify No Direct Package Imports
**Status**: PENDING

**Description**: Verify codebase only has expected ImportError fallback, no direct package usage.

**Evidence Command**:
```bash
# Should only find the try/except ImportError block
grep -r "from telemetry\|import telemetry" src/ --exclude-dir=__pycache__
```

**Expected Result**:
- Only 1 occurrence: `src/observability/telemetry_integration.py` line ~417 (graceful degradation)
- No other imports found

**Acceptance Criteria**:
- Only expected ImportError fallback found
- No production code imports telemetry package
- Graceful degradation pattern correct

---

#### TASK-TELEM-3.3: Verify Integration Points
**Status**: PENDING

**Description**: Verify CLI/engine/workers use `TranslationTelemetry` instance correctly.

**Evidence Command**:
```bash
# Check CLI initialization
grep -n "TranslationTelemetry\|telemetry" src/cli.py | head -20

# Check engine usage
grep -n "self.telemetry" src/translation_engine/engine.py | head -20
```

**Acceptance Criteria**:
- CLI initializes telemetry from global config
- Engine receives telemetry instance
- Workers use telemetry for task reporting
- No direct API calls (all through abstraction)

---

#### TASK-TELEM-3.4: Integration Test - Manual Translation
**Status**: PENDING (depends on TASK-TELEM-3.1, TASK-TELEM-3.2, TASK-TELEM-3.3)

**Description**: Run manual translation and verify telemetry events recorded.

**Evidence Command**:
```bash
# Ensure telemetry API running
docker-compose up -d local-telemetry
curl http://localhost:8765/health

# Run translation
python src/cli.py translate \
  --site kb.aspose.net \
  --input test_fixtures/sample.md \
  --target-langs fr \
  --validation-mode normal

# Verify telemetry events
curl http://localhost:8765/api/v1/runs?agent_name=hugo-translator | jq '.runs[-1]'
```

**Acceptance Criteria**:
- Translation completes successfully
- Telemetry event created with correct `agent_name=hugo-translator`
- Event includes start_time, status, file counts

---

## Workstream E: End-to-End Validation
**Owner**: Agent C (Tests & Verification)
**Priority**: HIGH
**Status**: PENDING

### Tasks

#### TASK-TELEM-4.1: E2E Test - Batch Translation
**Status**: PENDING

**Description**: Test batch translation telemetry tracking.

**Evidence Command**:
```bash
# Create test batch (5 files)
cat > /tmp/test_batch_5.txt <<EOF
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\net\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\python\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\java\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\cpp\_index.md
EOF

# Translate batch
python src/cli.py translate \
  --site kb.aspose.net \
  --input /tmp/test_batch_5.txt \
  --target-langs fr de \
  --validation-mode normal

# Verify batch telemetry
curl http://localhost:8765/api/v1/runs?job_type=translate_batch | jq '.runs[-1]'
```

**Acceptance Criteria**:
- Batch translation completes successfully
- Telemetry event shows `job_type=translate_batch`
- File counts correct (5 files × 2 languages = 10 translations)

---

#### TASK-TELEM-4.2: E2E Test - Git Commit Association
**Status**: PENDING

**Description**: Verify git commits are associated with telemetry events.

**Evidence Command**:
```bash
# Translate sample
python src/cli.py translate \
  --site kb.aspose.net \
  --input /tmp/test_sample.txt \
  --target-langs fr \
  --validation-mode normal

# Get event ID from logs/output
# (Would need to parse from CLI output or logs)
EVENT_ID="..."

# Make git commit (should auto-associate)
cd D:\onedrive\Documents\GitHub\aspose.net
git add content/kb.aspose.net/slides/fr/
git commit -m "test: telemetry validation translation"

# Verify commit association
curl http://localhost:8765/api/v1/runs/${EVENT_ID} | jq '.git_commit'
```

**Acceptance Criteria**:
- Git commit SHA appears in telemetry event
- Association happens automatically (via git hooks or post-commit logic)
- Telemetry event updated with commit info

---

#### TASK-TELEM-4.3: E2E Test - Graceful Degradation
**Status**: PENDING

**Description**: Verify translation succeeds when telemetry API unavailable.

**Evidence Command**:
```bash
# Stop telemetry API
docker-compose stop local-telemetry

# Run translation (should succeed with warning)
python src/cli.py translate \
  --site kb.aspose.net \
  --input test_fixtures/sample.md \
  --target-langs fr \
  2>&1 | tee graceful_degradation_test.log

# Check translation succeeded
test -f output/fr/sample.md && echo "PASS: Graceful degradation works" || echo "FAIL: Translation blocked by telemetry"

# Check log for appropriate warning
grep -i "telemetry.*unavailable\|telemetry.*failed" graceful_degradation_test.log
```

**Acceptance Criteria**:
- Translation completes successfully (telemetry failure doesn't block)
- Warning logged about telemetry unavailability
- Output file created correctly

---

#### TASK-TELEM-4.4: Health Check Validation
**Status**: PENDING

**Description**: Document and verify telemetry API health check.

**Evidence Command**:
```bash
# Health check
curl http://localhost:8765/health | jq '.'

# Expected response:
# {
#   "status": "healthy",
#   "version": "2.2.0",
#   "uptime_seconds": 12345
# }
```

**Acceptance Criteria**:
- Health endpoint responds correctly
- Version matches expected (v2.2.0)
- Health check documented in environment variables guide

---

## Workstream F: Evidence Bundle Creation
**Owner**: Agent D (Documentation)
**Priority**: MEDIUM
**Status**: PENDING

### Tasks

#### TASK-TELEM-5.1: Create Evidence Directory
**Status**: PENDING

**Description**: Create structured evidence bundle directory.

**Evidence Command**:
```bash
mkdir -p runs/telemetry_consistency_validation_$(date +%Y%m%d_%H%M%S)
cd runs/telemetry_consistency_validation_*
mkdir -p {docs,config,tests,evidence}
```

**Acceptance Criteria**:
- Directory structure created
- Ready for artifact collection

---

#### TASK-TELEM-5.2: Collect Documentation Diffs
**Status**: PENDING (depends on Workstream B completion)

**Description**: Capture all documentation changes.

**Evidence Command**:
```bash
git diff docs/operations/TELEMETRY_*.md > docs/docs_updates.patch
git diff docs/setup/ENVIRONMENT_VARIABLES.md >> docs/docs_updates.patch
```

**Acceptance Criteria**:
- Patch file with all doc changes
- Ready for review and evidence bundle

---

#### TASK-TELEM-5.3: Collect Configuration Inventory
**Status**: PENDING (depends on Workstream C completion)

**Description**: Save all telemetry configuration files.

**Evidence Command**:
```bash
cat .env > config/config_inventory.txt
echo "---" >> config/config_inventory.txt
grep -A 10 "telemetry:" config/global.yaml >> config/config_inventory.txt
echo "---" >> config/config_inventory.txt
grep -A 5 "local-telemetry:" docker-compose.yml >> config/config_inventory.txt
echo "---" >> config/config_inventory.txt
cat .env.production >> config/config_inventory.txt
echo "---" >> config/config_inventory.txt
cat .env.test >> config/config_inventory.txt
```

**Acceptance Criteria**:
- All config files inventoried
- Before/after comparison possible

---

#### TASK-TELEM-5.4: Collect Test Results
**Status**: PENDING (depends on Workstream E completion)

**Description**: Save all E2E test results and telemetry API responses.

**Evidence Command**:
```bash
# Save integration test results
curl http://localhost:8765/api/v1/runs?limit=10 > tests/telemetry_test_events.json

# Save health check
curl http://localhost:8765/health > tests/telemetry_health.json

# Save graceful degradation test log
cp graceful_degradation_test.log tests/
```

**Acceptance Criteria**:
- All test results captured
- Telemetry events saved for review
- Health check status documented

---

#### TASK-TELEM-5.5: Write Validation Report
**File**: `VALIDATION_REPORT.md` (in evidence bundle)
**Status**: PENDING (depends on all workstreams)

**Description**: Comprehensive validation report documenting all findings and test results.

**Content**:
1. Executive Summary (key finding: HTTP API already works)
2. Documentation Updates (files changed, diffs)
3. Configuration Templates (created files, patterns)
4. Code Validation (50+ integration points verified)
5. E2E Test Results (manual, batch, git, graceful degradation)
6. Success Metrics (all criteria met)
7. Recommendations (deployment ready)

**Acceptance Criteria**:
- All findings documented
- All test results included
- Clear success/failure for each criterion

---

#### TASK-TELEM-5.6: Create Evidence Bundle
**Status**: PENDING (depends on TASK-TELEM-5.1-5.5)

**Description**: Compress all evidence into distributable bundle.

**Evidence Command**:
```bash
cd runs/telemetry_consistency_validation_*
tar -czf telemetry_consistency_evidence.tar.gz \
  docs/ config/ tests/ evidence/ VALIDATION_REPORT.md
```

**Acceptance Criteria**:
- Compressed bundle created
- Contains all documentation, config, tests, evidence
- Ready for distribution/archival

---

## Integration & Final Deliverables
**Owner**: Agent B (Implementation) + Agent D (Documentation)
**Priority**: CRITICAL
**Status**: PENDING

### Tasks

#### TASK-TELEM-INT-1: Update STATUS.md
**File**: `reports/STATUS.md` (update or create)
**Status**: PENDING (depends on all workstreams)

**Description**: Document final status of telemetry consistency project.

**Content**:
- Per-task status (all tasks with completion status)
- Owner assignments
- Self-review scores (all >=4/5)
- Remaining gaps (none expected)

**Acceptance Criteria**:
- All tasks marked COMPLETE
- All self-reviews passing (>=4/5 on 12 dimensions)
- No open gaps

---

#### TASK-TELEM-INT-2: Create CHANGELOG.md
**File**: `reports/CHANGELOG.md` (update or create)
**Status**: PENDING (depends on all workstreams)

**Description**: Document all changes made during telemetry consistency project.

**Content**:
1. Documentation Updates
   - TELEMETRY_MIGRATION_GUIDE.md (removed package refs)
   - TELEMETRY_ROLLBACK_GUIDE.md (config-based rollback)
   - ENVIRONMENT_VARIABLES.md (created)

2. Configuration Templates
   - .env.production (created)
   - .env.test (created)

3. Validation Results
   - 50+ integration points verified
   - E2E tests passed (manual, batch, git, graceful degradation)

**Acceptance Criteria**:
- All changes documented
- Test commands included
- Deployment instructions clear

---

## Success Metrics

### Target Status (After Completion)
| Metric | Target | Status |
|--------|--------|--------|
| Documentation Accuracy | Zero package references | ⏳ PENDING |
| Configuration Consistency | All environments documented | ⏳ PENDING |
| Integration Points Verified | 50+ verified using HTTP API | ⏳ PENDING |
| Manual Translation Test | Events recorded in API | ⏳ PENDING |
| Batch Translation Test | Events recorded in API | ⏳ PENDING |
| Git Commit Association | Commits linked to events | ⏳ PENDING |
| Graceful Degradation | Translation succeeds when API down | ⏳ PENDING |
| Evidence Bundle | Created with all artifacts | ⏳ PENDING |

---

## Task Dependencies

```
Workstream A (Discovery): ✅ COMPLETE (exploration phase)

Workstream B (Documentation):
  TASK-TELEM-1.1 → TASK-TELEM-1.3 (if needed)
  TASK-TELEM-1.2 → TASK-TELEM-1.4 (if needed)
  TASK-TELEM-1.5 (create environment guide)

Workstream C (Configuration):
  TASK-TELEM-2.1 → [TASK-TELEM-2.2, TASK-TELEM-2.3, TASK-TELEM-2.4] → TASK-TELEM-2.5

Workstream D (Code Validation):
  TASK-TELEM-3.1, TASK-TELEM-3.2, TASK-TELEM-3.3 → TASK-TELEM-3.4

Workstream E (E2E Validation):
  TASK-TELEM-4.1, TASK-TELEM-4.2, TASK-TELEM-4.3, TASK-TELEM-4.4 (parallel)

Workstream F (Evidence):
  [All Workstreams B-E] → TASK-TELEM-5.1 → [TASK-TELEM-5.2, TASK-TELEM-5.3, TASK-TELEM-5.4] → TASK-TELEM-5.5 → TASK-TELEM-5.6

Integration:
  [Workstream F] → TASK-TELEM-INT-1 → TASK-TELEM-INT-2
```

---

## Next Steps

1. **Spawn Agents**: Create agent folders for Workstreams B, C, D, E, F
2. **Parallel Execution**: Launch Workstreams B, C, D, E in parallel
3. **Self-Review**: Each task requires 12-dimension self-review (score >=4/5)
4. **Evidence Collection**: Workstream F collects all artifacts
5. **Final Deliverables**: STATUS.md, CHANGELOG.md, evidence bundle

---

**Risk Level**: LOW (documentation and templates only, no code changes)
**Estimated Timeline**: 4-5 hours
**Stop-the-Line Conditions**:
- Graceful degradation breaks during testing
- Integration tests show telemetry not working
- Configuration changes break existing functionality

---

**Last Updated**: 2026-02-03

---
---

# Discovery Summary - 2026-02-03

**Orchestrator Discovery Phase**: COMPLETE
**Discovery Date**: 2026-02-03
**Discovery Method**: TODO/FIXME scan + specs review + technical debt inventory + existing backlog analysis

---

## Work Inventory Discovered

### 1. Phase 6 Remediation (HIGH Priority)
**Status**: IN_PROGRESS
**Location**: Lines 0-1172 (this file)
**Scope**: 5 workstreams with 50+ tasks targeting 13.3% → ≥50% pass rate improvement
**Owner Assignments**:
- Agent B (Implementation): Workstreams 1, 4, 5 (Classification, AST, Batch)
- Agent C (Investigation): Workstreams 2, 3 (Verifier, Threshold)
- Agent D (Documentation): Documentation tasks

**Key Gaps**:
- FAIL_OTHER: 70.2% (target: <10%)
- No verification data: 49 cases (target: 0)
- Markdown fidelity failures: 37 cases (target: <5%)
- Batch duplication: 132 duplicates (target: 0)

**Next Action**: Spawn agents for Workstreams 1-2 (highest impact)

---

### 2. Telemetry HTTP API Consistency (COMPLETE)
**Status**: ✅ COMPLETE
**Location**: Lines 1176-1936 (this file)
**Completion**: 2026-02-03, 7/8 metrics achieved (87.5%), quality score 5.0/5
**Evidence**: `runs/telemetry_consistency_validation_20260203/VALIDATION_REPORT.md`
**Remaining Work**: Optional documentation update (LOW priority)

---

### 3. Specs Backlog (MEDIUM Priority)
**Status**: PENDING
**Location**: `specs/_backlog.yml`
**Scope**: 5 items (1 P0, 3 P1, 1 P2)

**Items**:
- P0: specscan tool not present (owner: spec_harden)
- P1: Verify runtime units (owner: spec_verify)
- P1: Verify entrypoints (owner: spec_verify)
- P1: Verify features (owner: spec_verify)
- P2: Tighten governance gates (owner: spec_harden)

**Next Action**: Address after Phase 6 Remediation complete

---

### 4. Technical Debt (LOW Priority)
**Status**: DOCUMENTED
**Location**: `docs/technical_debt/TODO_FIXME_ITEMS.md`
**Scope**: 3 items, all non-blocking, 2-4 hours total

**Items**:
1. Subprocess statistics return (1-2 hours, LOW priority)
2. Dashboard security hardening (4-8 hours, MEDIUM if deploying publicly)
3. TM query for missing segment count (2-3 hours, LOW priority)

**Next Action**: Defer to post-production maintenance

---

## Priority Matrix

| Priority | Work Item | Impact | Effort | Next Step |
|----------|-----------|--------|--------|-----------|
| **HIGH** | Phase 6 Remediation WS1 (Classification) | Critical quality improvement | 5 tasks | ✅ Spawn Agent B |
| **HIGH** | Phase 6 Remediation WS2 (Verifier) | Critical reliability fix | 6 tasks | ✅ Spawn Agent C |
| **HIGH** | Phase 6 Remediation WS4 (AST) | Formatting preservation | 7 tasks | Spawn Agent B (after WS1) |
| **MEDIUM** | Phase 6 Remediation WS5 (Batch) | Deduplication fix | 5 tasks | Spawn Agent B (after WS4) |
| **MEDIUM** | Specs P0-P1 Items | Verification tooling | 4 tasks | Queue for next cycle |
| **LOW** | Technical Debt Items | Enhancements | 3 tasks | Defer to maintenance |

---

## Agent Spawn Plan (Top 5 Tasks)

### Immediate Spawn (Phase 1)

**Agent 1 (Implementation - Workstream 1)**:
- **Type**: Agent B (Code Implementation)
- **Tasks**: TASK-1.1 through TASK-1.5 (Multi-failure classification)
- **Deliverables**: Refactored classify_failure(), updated progress schema, unit tests
- **Evidence**: Test output showing multi-failure detection working

**Agent 2 (Investigation - Workstream 2)**:
- **Type**: Agent C (Investigation & Diagnostics)
- **Tasks**: TASK-2.1 through TASK-2.3 (No-data cases investigation)
- **Deliverables**: Catalog of 49 cases, existence check, root cause analysis
- **Evidence**: CSV catalog, log analysis, fix proposals

### Queued Spawn (Phase 2)

**Agent 3 (Implementation - Workstream 4)**:
- **Type**: Agent B (Code Implementation)
- **Tasks**: TASK-4.1 through TASK-4.4 (AST formatting preservation)
- **Depends On**: Agent 1 completion
- **Deliverables**: Bold/italic preservation fixes, regression tests

**Agent 4 (Implementation - Workstream 5)**:
- **Type**: Agent B (Code Implementation)
- **Tasks**: TASK-5.1 through TASK-5.3 (Batch deduplication)
- **Depends On**: Agent 3 completion
- **Deliverables**: Fixed batch logic, deduplication guard, unit tests

**Agent 5 (Documentation - Final)**:
- **Type**: Agent D (Documentation)
- **Tasks**: TASK-DOC-1 through TASK-DOC-3 (Remediation report)
- **Depends On**: All workstreams complete
- **Deliverables**: Remediation report, updated status tracking

---

## Discovery Evidence

**TODO/FIXME Scan**:
- Command: `find . -type f \( -name "*.py" -o -name "*.md" \) -exec grep -l "TODO\|FIXME\|HACK\|XXX" {} \;`
- Status: Timed out (10s), but existing inventory in `docs/technical_debt/TODO_FIXME_ITEMS.md` is comprehensive

**Specs Review**:
- Source: `specs/_backlog.yml`
- Items: 5 (1 P0, 3 P1, 1 P2)
- Status: All PENDING, systematic verification needed

**Technical Debt Inventory**:
- Source: `docs/technical_debt/TODO_FIXME_ITEMS.md`
- Created: 2026-01-17
- Status: DOCUMENTED, all items non-blocking

**Existing Backlogs**:
- Phase 6 Remediation: Comprehensive 5-workstream plan (IN_PROGRESS)
- Telemetry Consistency: Complete (7/8 metrics, 5.0/5 quality)

---

## Orchestrator Status

**Current Phase**: Step 1 (Spawn Agents)
**Next Actions**:
1. Spawn Agent 1 (Implementation) for Workstream 1 (Classification)
2. Spawn Agent 2 (Investigation) for Workstream 2 (Verifier)
3. Monitor progress via agent evidence reports
4. Route any <4/5 scores back for hardening
5. Proceed to Phase 2 agent spawning upon completion

**Stop-the-Line Conditions**:
- Self-review score <4/5 on any dimension
- Breaking changes to existing tests
- Silent data loss or corruption
- Evidence gaps preventing validation

---

**Discovery Completed**: 2026-02-03
**Discovery Duration**: 15 minutes
**Work Items Identified**: 4 categories, 60+ total tasks
**Highest Priority**: Phase 6 Remediation Workstreams 1-2

---

---

# Task Backlog - CT2 Models for 17-Language Aspose.Slides Translation

**Plan**: [hidden-marinating-dongarra.md](C:\Users\prora\.claude\plans\hidden-marinating-dongarra.md)
**Created**: 2026-02-04
**Status**: READY_FOR_EXECUTION

---

## Project Overview

**Objective**: Use pre-existing CT2 models from `D:\models\opus_mt_ct2` for high-performance CPU-based translation of Aspose.Slides content across 17 languages **with ZERO code changes**.

**Key Constraints**:
- ❌ **NO code modifications** - No changes to src/cli.py or any Python files
- ❌ **NO breaking changes** - No regression risk
- ✅ **Configuration only** - Use existing ModelRegistry CLI flag mechanisms
- ✅ **Test 17 languages first** - Validate CT2 models work before expanding
- ✅ **CPU-only execution** - Must preserve running GPU processes (VRAM 70%, CPU 95%)
- ✅ **Incremental translation** - Only translate files/languages not yet done (skip existing)
- ✅ **Active monitoring** - Watch process, capture issues, kill-on-flaw, retry with fine-tuning

**Target Languages (17 only)**: ar, ca, cs, da, fr, he, it, ko, nl, pl, pt, ro, ru, sv, tr, uk, zh

**Success Criteria**:
- ✅ Pass rate ≥90% across all 17 languages (STRICT - Phase 6 quality target)
- ✅ FAIL_OTHER <10%
- ✅ FAIL_MARKDOWN <5%
- ✅ No duplicate records
- ✅ Translation speed ≥50 tokens/sec average (CT2 INT8)
- ✅ All 17 languages complete successfully
- ✅ Zero code changes (config swap only)

**Expected Performance**:
- Sampling: 20 files × 17 languages = 340 translations (~1 hour)
- Bulk: ~200 files × 17 languages = 3,400 translations (~24-36 hours)
- Speed: 50-100 tokens/sec (CT2 INT8 on CPU)

---

## Workstream 1: Registry Setup & Validation
**Owner**: Agent A (Discovery)
**Priority**: CRITICAL
**Status**: PENDING

### Tasks

#### TASK-CT2-001: Create Custom CT2 Registry + Validate All Models
**Files**:
- `config/custom_ct2_registry.yaml` (NEW)
- `D:\models\opus_mt_ct2\en-XX\ct2_int8` (READ)
**Status**: PENDING

**Description**: Create custom CT2 model registry with 17 Opus-MT CT2 INT8 entries and pre-validate all models before starting translation.

**Scope**:
1. Generate custom registry YAML with 17 model entries
2. Validate all 17 CT2 models (check files exist, CT2 format correct)
3. Verify model selection logic picks correct CT2 models for each language
4. Perform temporary registry swap (backup → swap → restore workflow)

**Implementation Steps**:

**Step 1: Generate Custom Registry**
```bash
# Create generator script
cat > /tmp/generate_ct2_registry.py << 'EOF'
import yaml
from pathlib import Path

HF_MODEL_MAP = {
    "ar": "Helsinki-NLP/opus-mt-en-ar",
    "ca": "Helsinki-NLP/opus-mt-en-ca",
    "cs": "Helsinki-NLP/opus-mt-en-cs",
    "da": "Helsinki-NLP/opus-mt-en-da",
    "fr": "Helsinki-NLP/opus-mt-en-fr",
    "he": "Helsinki-NLP/opus-mt-en-he",
    "it": "Helsinki-NLP/opus-mt-en-it",
    "ko": "Helsinki-NLP/opus-mt-tc-big-en-ko",
    "nl": "Helsinki-NLP/opus-mt-en-nl",
    "pl": "Helsinki-NLP/opus-mt-en-pl",
    "pt": "Helsinki-NLP/opus-mt-en-pt",
    "ro": "Helsinki-NLP/opus-mt-en-ro",
    "ru": "Helsinki-NLP/opus-mt-en-ru",
    "sv": "Helsinki-NLP/opus-mt-en-sv",
    "tr": "Helsinki-NLP/opus-mt-en-tr",
    "uk": "Helsinki-NLP/opus-mt-en-uk",
    "zh": "Helsinki-NLP/opus-mt-en-zh",
}

models = []
for lang, hf_id in HF_MODEL_MAP.items():
    models.append({
        "model_id": f"opus_mt_en_{lang}_ct2_int8",
        "name": f"Opus-MT English-{lang.upper()} (CT2 INT8)",
        "backend": "ctranslate2",
        "local_path": f"D:\\models\\opus_mt_ct2\\en-{lang}\\ct2_int8",
        "hf_model_id": hf_id,
        "supported_pairs": [["en", lang]],
        "model_size_mb": 80,
        "min_ram_gb": 0.5,
        "optimal_device": "cpu",
        "parameters": 77000000,
        "license": "Apache-2.0",
        "description": f"Opus-MT English-{lang.upper()} model, CT2 INT8 quantized for CPU efficiency"
    })

output_path = Path("config/custom_ct2_registry.yaml")
with open(output_path, "w", encoding="utf-8") as f:
    yaml.dump({"models": models}, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

print(f"✅ Generated {output_path} with {len(models)} model entries")
EOF

# Run generator
python /tmp/generate_ct2_registry.py
```

**Step 2: Pre-Validate All CT2 Models**
```bash
# Validation script
cat > /tmp/validate_ct2_models.py << 'EOF'
from pathlib import Path

ct2_base = Path("D:/models/opus_mt_ct2")
target_langs = ["ar", "ca", "cs", "da", "fr", "he", "it", "ko", "nl", "pl", "pt", "ro", "ru", "sv", "tr", "uk", "zh"]

results = {}
for lang in target_langs:
    model_path = ct2_base / f"en-{lang}" / "ct2_int8"

    # Check all required files
    required_files = ["config.json", "model.bin", "source.spm", "target.spm", "shared_vocabulary.json", "vmap.txt"]
    all_exist = all((model_path / f).exists() for f in required_files)

    results[lang] = {
        "path": model_path,
        "valid": all_exist and model_path.exists(),
        "exists": model_path.exists()
    }

    status = "✅" if results[lang]["valid"] else "❌"
    print(f"{status} en-{lang}: {model_path}")

    if not results[lang]["valid"]:
        missing = [f for f in required_files if not (model_path / f).exists()]
        if missing:
            print(f"    Missing files: {missing}")

valid_count = sum(1 for r in results.values() if r["valid"])
print(f"\n✅ Validation Summary: {valid_count}/{len(target_langs)} models valid")

if valid_count < len(target_langs):
    print("\n❌ Failed models:")
    for lang, result in results.items():
        if not result["valid"]:
            print(f"  - en-{lang}: {result['path']}")
    exit(1)
EOF

# Run validation
python /tmp/validate_ct2_models.py
```

**Step 3: Verify Model Selection Logic**
```bash
# Test script for model selection
cat > /tmp/verify_model_selection.py << 'EOF'
# First, perform registry swap
import shutil
from pathlib import Path

backup_path = Path("config/model_registry.yaml.backup")
registry_path = Path("config/model_registry.yaml")
custom_registry = Path("config/custom_ct2_registry.yaml")

# Backup original
shutil.copy(registry_path, backup_path)
print(f"✅ Backed up {registry_path} → {backup_path}")

# Swap to custom
shutil.copy(custom_registry, registry_path)
print(f"✅ Swapped {custom_registry} → {registry_path}")

# Test model selection
from src.model_runtime.registry import ModelRegistry
from src.model_runtime.hardware import HardwareInfo

registry = ModelRegistry("config/model_registry.yaml")
hardware = HardwareInfo.detect()

ct2_langs = ["ar", "ca", "cs", "da", "fr", "he", "it", "ko", "nl", "pl", "pt", "ro", "ru", "sv", "tr", "uk", "zh"]
for lang in ct2_langs:
    try:
        model = registry.recommend_model("en", lang, hardware, prefer_quality=False)
        expected = f"opus_mt_en_{lang}_ct2_int8"
        status = "✅" if model.model_id == expected else "❌"
        print(f"{status} en→{lang}: {model.model_id} (expected: {expected})")
        if model.model_id != expected:
            exit(1)
    except Exception as e:
        print(f"❌ en→{lang}: ERROR - {e}")
        exit(1)

# Restore original
shutil.copy(backup_path, registry_path)
print(f"\n✅ Restored {backup_path} → {registry_path}")
print("✅ All 17 languages select correct CT2 models")
EOF

# Run verification
python /tmp/verify_model_selection.py
```

**Acceptance Criteria**:
- ✅ `config/custom_ct2_registry.yaml` created with 17 entries
- ✅ All 17 CT2 models validated (files exist, CT2 format correct)
- ✅ All 17 languages select correct Opus-MT CT2 models
- ✅ Registry swap workflow tested (backup → swap → restore)
- ✅ YAML is valid and parseable

**Evidence Commands**:
```bash
# Verify registry created
ls -lh config/custom_ct2_registry.yaml
cat config/custom_ct2_registry.yaml | grep "model_id:" | wc -l  # Should be 17

# Verify all models validated
python /tmp/validate_ct2_models.py

# Verify model selection
python /tmp/verify_model_selection.py
```

**Files Created**:
- `config/custom_ct2_registry.yaml` (NEW - 17 model entries)

**Files Modified**: NONE (zero code changes)

**Dependencies**: NONE

**Self-Review Dimensions**: 12/12 required (score ≥4/5 on each)

---

## Workstream 2: Sampling Run with Active Monitoring
**Owner**: Agent C (Tests & Verification)
**Priority**: CRITICAL
**Status**: PENDING (depends on CT2-001)

### Tasks

#### TASK-CT2-002: Execute Sampling Run (20 files × 17 languages) with Kill-On-Flaw Monitoring
**Files**:
- `artifacts/aspose_slides_sample_20.txt` (NEW - input file list)
- `runs/ct2_sampling_*/` (NEW - output directory)
**Status**: PENDING (depends on CT2-001)

**Description**: Run sampling translation with 20 files × 17 languages (340 translations), with real-time monitoring, kill-on-flaw capability, and automatic retry with fine-tuning.

**Scope**:
1. Create input file list (20 Aspose.Slides sample files)
2. Perform registry swap (backup → swap)
3. Run translation with CT2 models (device=cpu, batch_size=8, 17 languages)
4. **Active monitoring**: Watch logs, check quality gates, kill if pass rate <70%
5. **Automatic retry**: If failures occur, retry with reduced batch_size (8→4→2)
6. Restore original registry after completion
7. Capture evidence (metadata, logs, pass rate)

**Implementation Steps**:

**Step 1: Create Input File List (20 samples)**
```bash
# Create sample list (20 diverse Aspose.Slides files)
cat > artifacts/aspose_slides_sample_20.txt << 'EOF'
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\file-format\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\add-text-to-presentation\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\create-presentation\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\open-presentation\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\save-presentation\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\net\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\python\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\java\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\cpp\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\android\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\features\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\getting-started\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\net\create\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\net\open\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\net\save\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\python\create\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\python\open\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\java\create\_index.md
D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en\cpp\create\_index.md
EOF

echo "✅ Created input file list with 20 files"
```

**Step 2: Registry Swap + Translation Execution**
```bash
# Backup original registry
cp config/model_registry.yaml config/model_registry.yaml.backup
echo "✅ Backed up original registry"

# Swap to custom CT2 registry
cp config/custom_ct2_registry.yaml config/model_registry.yaml
echo "✅ Swapped to custom CT2 registry"

# Run translation (writes directly to aspose.net corpus - in-place mode)
python -m src.cli translate \
  --device cpu \
  --batch-size 8 \
  --target-langs ar,ca,cs,da,fr,he,it,ko,nl,pl,pt,ro,ru,sv,tr,uk,zh \
  --site kb.aspose.net \
  --input artifacts/aspose_slides_sample_20.txt \
  --validation-mode normal \
  --terminology-mode auto \
  --skip-existing \
  2>&1 | tee runs/ct2_sampling_$(date +%Y%m%d_%H%M%S)/translation.log

# Capture exit code
EXIT_CODE=$?

# Restore original registry
cp config/model_registry.yaml.backup config/model_registry.yaml
echo "✅ Restored original registry"

exit $EXIT_CODE
```

**Step 3: Active Monitoring (Run in Parallel with Translation)**
```bash
# Monitor translation progress in real-time
MONITOR_SCRIPT=/tmp/monitor_sampling.sh
cat > $MONITOR_SCRIPT << 'EOF'
#!/bin/bash

OUTPUT_DIR="runs/ct2_sampling_$(date +%Y%m%d)*"
CHECK_INTERVAL=60  # Check every 60 seconds

while true; do
  sleep $CHECK_INTERVAL

  # Check if translation still running
  pgrep -f "src.cli translate" > /dev/null || break

  # Read metadata
  METADATA="$OUTPUT_DIR/output/.translation_metadata.json"
  if [ -f "$METADATA" ]; then
    PASS_RATE=$(cat "$METADATA" | jq -r '.pass_rate // 0')
    TOTAL=$(cat "$METADATA" | jq -r '.total_files // 0')
    PASSED=$(cat "$METADATA" | jq -r '.passed // 0')

    echo "[$(date)] Progress: $PASSED/$TOTAL passed ($PASS_RATE)"

    # Kill-on-flaw: If pass rate <70% and at least 50 files processed
    if (( $(echo "$PASS_RATE < 0.70" | bc -l) )) && [ $TOTAL -ge 50 ]; then
      echo "❌ KILL SIGNAL: Pass rate $PASS_RATE below 70% threshold"
      pkill -f "src.cli translate"
      exit 1
    fi
  fi
done

echo "✅ Monitoring complete"
EOF

chmod +x $MONITOR_SCRIPT
$MONITOR_SCRIPT &
MONITOR_PID=$!
echo "✅ Started monitoring process (PID: $MONITOR_PID)"
```

**Step 4: Automatic Retry with Reduced Batch Size (If Needed)**
```bash
# After translation completes, check if retry needed
METADATA="runs/ct2_sampling_*/output/.translation_metadata.json"
PASS_RATE=$(cat "$METADATA" | jq -r '.pass_rate // 0')

if (( $(echo "$PASS_RATE < 0.90" | bc -l) )); then
  echo "⚠️ Pass rate $PASS_RATE below 90% threshold. Extracting failed files..."

  # Extract failed files
  python -c "
import json
with open('$METADATA') as f:
    data = json.load(f)
failed = [f['file_path'] for f in data.get('files', []) if f.get('status') != 'PASS']
with open('artifacts/failed_files_retry.txt', 'w') as out:
    out.write('\n'.join(failed))
print(f'Captured {len(failed)} failed files for retry')
"

  # Retry with batch_size=4
  echo "🔁 Retrying failed files with batch_size=4..."
  cp config/custom_ct2_registry.yaml config/model_registry.yaml

  python -m src.cli translate \
    --device cpu \
    --batch-size 4 \
    --target-langs ar,ca,cs,da,fr,he,it,ko,nl,pl,pt,ro,ru,sv,tr,uk,zh \
    --site kb.aspose.net \
    --input artifacts/failed_files_retry.txt \
    --validation-mode normal \
    --skip-existing

  cp config/model_registry.yaml.backup config/model_registry.yaml
fi
```

**Acceptance Criteria**:
- ✅ 340 translations complete (20 files × 17 languages)
- ✅ Pass rate ≥90% (STRICT - Phase 6 quality target)
- ✅ FAIL_OTHER <10%, FAIL_MARKDOWN <5%
- ✅ Translation speed ≥50 tokens/sec average (CT2 INT8)
- ✅ All 17 languages complete successfully
- ✅ Monitoring captured issues and killed process if pass rate <70%
- ✅ Failed files retried with reduced batch size (if needed)
- ✅ Evidence captured: metadata, logs, pass rate

**Evidence Commands**:
```bash
# Check translation completed
ls -lh runs/ct2_sampling_*/output/.translation_metadata.json

# Check pass rate
cat runs/ct2_sampling_*/output/.translation_metadata.json | jq '.pass_rate'

# Check translation speed
grep "CT2 timing" runs/ct2_sampling_*/output/*.log | \
  awk '{print $(NF-1)}' | \
  awk '{sum+=$1; count++} END {print "Average:", sum/count, "tokens/sec"}'

# Check model usage
grep "Loading CTranslate2 model" runs/ct2_sampling_*/output/*.log | \
  awk -F' ' '{print $(NF-1)}' | \
  awk -F'/' '{print $NF}' | \
  sort | uniq -c
```

**Files Created**:
- `artifacts/aspose_slides_sample_20.txt` (NEW - input file list)
- `runs/ct2_sampling_*/output/.translation_metadata.json` (NEW - telemetry)
- `runs/ct2_sampling_*/output/*.log` (NEW - logs)
- `artifacts/failed_files_retry.txt` (NEW - if retry needed)

**Files Modified**: NONE (translations written in-place to aspose.net corpus)

**Dependencies**: CT2-001 (Registry Setup & Validation)

**Self-Review Dimensions**: 12/12 required (score ≥4/5 on each)

---

## Workstream 3: Evidence Analysis & Go/No-Go Decision
**Owner**: Agent D (Documentation)
**Priority**: CRITICAL
**Status**: PENDING (depends on CT2-002)

### Tasks

#### TASK-CT2-003: Analyze Sampling Results & Make Go/No-Go Decision
**Files**:
- `runs/ct2_sampling_*/SAMPLING_SUMMARY.md` (NEW - analysis report)
- `runs/ct2_sampling_evidence_*.tar.gz` (NEW - evidence bundle)
**Status**: PENDING (depends on CT2-002)

**Description**: Analyze sampling run results, create evidence bundle, and make go/no-go decision for bulk run based on ≥90% pass rate threshold.

**Scope**:
1. Extract and analyze sampling metadata (pass rate, FAIL_OTHER, FAIL_MARKDOWN, speed)
2. Validate all success criteria met
3. Create SAMPLING_SUMMARY.md report with go/no-go decision
4. Create evidence bundle (metadata, logs, summary)
5. If GO: proceed to CT2-004 (git commit)
6. If NO-GO: stop, investigate failures, do not proceed to bulk

**Implementation Steps**:

**Step 1: Extract Sampling Metadata**
```bash
# Parse metadata
python -c "
import json
with open('runs/ct2_sampling_*/output/.translation_metadata.json') as f:
    data = json.load(f)

print(f\"Pass Rate: {data.get('pass_rate', 0):.1%}\")
print(f\"Total Files: {data.get('total_files', 0)}\")
print(f\"Passed: {data.get('passed', 0)}\")
print(f\"Failed: {data.get('failed', 0)}\")
print(f\"FAIL_OTHER Rate: {data.get('fail_other_rate', 0):.1%}\")
print(f\"FAIL_MARKDOWN Rate: {data.get('fail_markdown_rate', 0):.1%}\")
"
```

**Step 2: Generate SAMPLING_SUMMARY.md**
```bash
python -c "
import json
from datetime import datetime

with open('runs/ct2_sampling_*/output/.translation_metadata.json') as f:
    data = json.load(f)

summary = f'''# CT2 Sampling Run Evidence

**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Files**: 20
**Languages**: 17 (ar, ca, cs, da, fr, he, it, ko, nl, pl, pt, ro, ru, sv, tr, uk, zh)
**Total Translations**: {data['total_files']}
**Pass Rate**: {data['pass_rate']:.1%}
**FAIL_OTHER**: {data.get('fail_other_rate', 0):.1%}
**FAIL_MARKDOWN**: {data.get('fail_markdown_rate', 0):.1%}

## Go/No-Go Decision

'''

if data['pass_rate'] >= 0.90:
    summary += '''### ✅ GO Decision: Proceed to Bulk Run

Pass rate meets ≥90% threshold. Quality gates validated.

**Next Steps**:
1. Commit custom registry and sampling evidence (CT2-004)
2. Execute bulk run (CT2-005)
'''
else:
    summary += f'''### ❌ NO-GO Decision: Do NOT Proceed to Bulk

Pass rate {data['pass_rate']:.1%} below 90% threshold. Investigation required.

**Next Steps**:
1. Investigate failure patterns
2. Analyze specific failure categories
3. Do NOT proceed to bulk run until pass rate ≥90%
'''

with open('runs/ct2_sampling_*/SAMPLING_SUMMARY.md', 'w') as out:
    out.write(summary)

print('✅ Generated SAMPLING_SUMMARY.md')
"
```

**Step 3: Create Evidence Bundle**
```bash
# Create evidence directory
EVIDENCE_DIR="runs/ct2_sampling_evidence_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVIDENCE_DIR"

# Collect artifacts
cp runs/ct2_sampling_*/output/.translation_metadata.json "$EVIDENCE_DIR/"
cp runs/ct2_sampling_*/output/*.log "$EVIDENCE_DIR/" 2>/dev/null || true
cp runs/ct2_sampling_*/SAMPLING_SUMMARY.md "$EVIDENCE_DIR/"
cp config/custom_ct2_registry.yaml "$EVIDENCE_DIR/"

# Archive bundle
tar -czf "$EVIDENCE_DIR.tar.gz" -C "$EVIDENCE_DIR" .
echo "✅ Evidence bundle created: $EVIDENCE_DIR.tar.gz"
```

**Acceptance Criteria**:
- ✅ SAMPLING_SUMMARY.md created with go/no-go decision
- ✅ Evidence bundle contains: metadata, logs, summary, registry
- ✅ Clear go/no-go decision based on ≥90% pass rate threshold
- ✅ If NO-GO: investigation plan documented
- ✅ If GO: ready to proceed to git commit and bulk run

**Evidence Commands**:
```bash
# Read summary
cat runs/ct2_sampling_*/SAMPLING_SUMMARY.md

# Verify bundle contents
tar -tzf runs/ct2_sampling_evidence_*.tar.gz

# Check go/no-go decision
grep "GO Decision" runs/ct2_sampling_*/SAMPLING_SUMMARY.md
```

**Files Created**:
- `runs/ct2_sampling_*/SAMPLING_SUMMARY.md` (NEW - analysis report)
- `runs/ct2_sampling_evidence_*.tar.gz` (NEW - evidence bundle)

**Files Modified**: NONE

**Dependencies**: CT2-002 (Sampling Run)

**Self-Review Dimensions**: 12/12 required (score ≥4/5 on each)

---

## Workstream 4: Git Commit (If GO Decision)
**Owner**: Agent B (Implementation)
**Priority**: HIGH
**Status**: PENDING (depends on CT2-003 GO decision)

### Tasks

#### TASK-CT2-004: Commit Custom Registry and Sampling Evidence
**Status**: PENDING (depends on CT2-003 GO decision)

**Description**: Commit custom CT2 registry and sampling evidence to git after sampling achieves ≥90% pass rate.

**Scope**:
1. Add custom registry to git
2. Add sampling evidence bundle to git
3. Create commits with proper messages
4. Do NOT push to remote (user decision)

**Implementation Steps**:

**Step 1: Commit Custom Registry**
```bash
git add config/custom_ct2_registry.yaml

git commit -m "config: add custom CT2 model registry for D:\models\opus_mt_ct2

- 17 Opus-MT CT2 INT8 models for CPU efficiency
- Supports languages: ar, ca, cs, da, fr, he, it, ko, nl, pl, pt, ro, ru, sv, tr, uk, zh
- Validated with 20-file sampling run (≥90% pass rate)
- Used via temporary registry swap (no code changes needed)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**Step 2: Commit Sampling Evidence**
```bash
git add runs/ct2_sampling_*/SAMPLING_SUMMARY.md
git add runs/ct2_sampling_evidence_*.tar.gz

git commit -m "docs: CT2 sampling run evidence (20 files × 17 languages)

Pass rate: [X]% (≥90% threshold met)
Quality gates validated, proceeding to bulk run.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**Acceptance Criteria**:
- ✅ Custom registry committed to git
- ✅ Sampling evidence committed to git
- ✅ Commit messages follow convention
- ✅ Do NOT push to remote (user decides when to push)

**Evidence Commands**:
```bash
# Verify commits
git log --oneline -2

# Verify files staged
git status
```

**Files Created**: NONE (commits only)

**Files Modified**: NONE (commits only)

**Dependencies**: CT2-003 GO decision

**Self-Review Dimensions**: 12/12 required (score ≥4/5 on each)

---

## Workstream 5: Bulk Run (If GO Decision)
**Owner**: Agent C (Tests & Verification) + Agent E (Observability)
**Priority**: CRITICAL
**Status**: PENDING (depends on CT2-003 GO decision)

### Tasks

#### TASK-CT2-005: Execute Bulk Run (Full Corpus × 17 languages) with Active Monitoring
**Files**:
- `artifacts/aspose_slides_full_corpus.txt` (NEW - full input list)
- `runs/ct2_bulk_*/` (NEW - output directory)
**Status**: PENDING (depends on CT2-003 GO decision)

**Description**: Execute full corpus translation (~200 files × 17 languages = 3,400 translations) with active monitoring every 10 minutes, kill-on-flaw capability, and 3-level retry strategy.

**Scope**:
1. Discover all Aspose.Slides English files
2. Perform registry swap
3. Run bulk translation with CT2 models (incremental mode - skip existing)
4. **Active monitoring**: Check progress every 10 minutes, kill if pass rate <70%
5. **3-level retry**: batch_size 8→4→2 for failed files
6. Restore original registry
7. Create final evidence bundle

**Implementation Steps**:

**Step 1: Discover Full Corpus**
```bash
# Discover all Aspose.Slides English files
python scripts/e2e_discover_paths.ps1 \
  --site kb.aspose.net \
  --product slides \
  --output artifacts/aspose_slides_full_corpus.txt

# Verify file count
wc -l artifacts/aspose_slides_full_corpus.txt
```

**Step 2: Registry Swap + Bulk Translation**
```bash
# Backup and swap
cp config/model_registry.yaml config/model_registry.yaml.backup
cp config/custom_ct2_registry.yaml config/model_registry.yaml

# Run bulk translation (incremental mode)
python -m src.cli translate \
  --device cpu \
  --batch-size 8 \
  --target-langs ar,ca,cs,da,fr,he,it,ko,nl,pl,pt,ro,ru,sv,tr,uk,zh \
  --site kb.aspose.net \
  --input artifacts/aspose_slides_full_corpus.txt \
  --validation-mode normal \
  --terminology-mode auto \
  --resume-on-failure \
  --skip-existing \
  2>&1 | tee runs/ct2_bulk_$(date +%Y%m%d_%H%M%S)/translation.log

# Restore
cp config/model_registry.yaml.backup config/model_registry.yaml
```

**Step 3: Active Monitoring (Every 10 Minutes)**
```bash
# Monitoring script
MONITOR_SCRIPT=/tmp/monitor_bulk.sh
cat > $MONITOR_SCRIPT << 'EOF'
#!/bin/bash

OUTPUT_DIR="runs/ct2_bulk_*"
CHECK_INTERVAL=600  # Check every 10 minutes

while true; do
  sleep $CHECK_INTERVAL

  # Check if translation still running
  pgrep -f "src.cli translate" > /dev/null || break

  # Read metadata
  METADATA="$OUTPUT_DIR/output/.translation_metadata.json"
  if [ -f "$METADATA" ]; then
    PASS_RATE=$(cat "$METADATA" | jq -r '.pass_rate // 0')
    TOTAL=$(cat "$METADATA" | jq -r '.total_files // 0')
    PASSED=$(cat "$METADATA" | jq -r '.passed // 0')

    echo "[$(date)] Progress: $PASSED/$TOTAL passed ($PASS_RATE)"

    # Kill-on-flaw: If pass rate <70% and at least 200 files processed
    if (( $(echo "$PASS_RATE < 0.70" | bc -l) )) && [ $TOTAL -ge 200 ]; then
      echo "❌ KILL SIGNAL: Pass rate $PASS_RATE below 70% threshold"
      pkill -f "src.cli translate"
      exit 1
    fi

    # Health checks
    CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}')
    RAM_USAGE=$(free -h | grep "Mem:" | awk '{print $3}')
    echo "  CPU: $CPU_USAGE%, RAM: $RAM_USAGE"
  fi
done

echo "✅ Monitoring complete"
EOF

chmod +x $MONITOR_SCRIPT
$MONITOR_SCRIPT &
```

**Step 4: 3-Level Retry for Failed Files**
```bash
# After bulk completes, check for failures
METADATA="runs/ct2_bulk_*/output/.translation_metadata.json"
PASS_RATE=$(cat "$METADATA" | jq -r '.pass_rate // 0')

if (( $(echo "$PASS_RATE < 0.90" | bc -l) )); then
  echo "⚠️ Pass rate $PASS_RATE below 90%. Starting 3-level retry..."

  # Extract failed files
  python -c "
import json
with open('$METADATA') as f:
    data = json.load(f)
failed = [f['file_path'] for f in data.get('files', []) if f.get('status') != 'PASS']
with open('artifacts/bulk_failed_retry.txt', 'w') as out:
    out.write('\n'.join(failed))
"

  # Attempt 1: batch_size=8 (already done)
  # Attempt 2: batch_size=4
  echo "🔁 Retry attempt 2/3: batch_size=4"
  cp config/custom_ct2_registry.yaml config/model_registry.yaml
  python -m src.cli translate \
    --device cpu \
    --batch-size 4 \
    --target-langs ar,ca,cs,da,fr,he,it,ko,nl,pl,pt,ro,ru,sv,tr,uk,zh \
    --site kb.aspose.net \
    --input artifacts/bulk_failed_retry.txt \
    --validation-mode normal \
    --skip-existing
  cp config/model_registry.yaml.backup config/model_registry.yaml

  # Check if still failures
  PASS_RATE=$(cat "$METADATA" | jq -r '.pass_rate // 0')
  if (( $(echo "$PASS_RATE < 0.90" | bc -l) )); then
    # Attempt 3: batch_size=2
    echo "🔁 Retry attempt 3/3: batch_size=2"
    cp config/custom_ct2_registry.yaml config/model_registry.yaml
    python -m src.cli translate \
      --device cpu \
      --batch-size 2 \
      --target-langs ar,ca,cs,da,fr,he,it,ko,nl,pl,pt,ro,ru,sv,tr,uk,zh \
      --site kb.aspose.net \
      --input artifacts/bulk_failed_retry.txt \
      --validation-mode normal \
      --skip-existing
    cp config/model_registry.yaml.backup config/model_registry.yaml
  fi
fi
```

**Step 5: Create Final Evidence Bundle**
```bash
# Create final evidence directory
EVIDENCE_DIR="runs/ct2_bulk_evidence_final_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVIDENCE_DIR"

# Collect all artifacts
cp runs/ct2_bulk_*/output/.translation_metadata.json "$EVIDENCE_DIR/"
cp runs/ct2_bulk_*/output/*.log "$EVIDENCE_DIR/"
cp artifacts/bulk_failed_retry.txt "$EVIDENCE_DIR/" 2>/dev/null || true

# Generate final report
python -c "
import json
from datetime import datetime

with open('$EVIDENCE_DIR/.translation_metadata.json') as f:
    data = json.load(f)

report = f'''# CT2 Bulk Run Final Evidence

**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Corpus Size**: ~200 files
**Languages**: 17 (ar, ca, cs, da, fr, he, it, ko, nl, pl, pt, ro, ru, sv, tr, uk, zh)
**Total Translations**: {data['total_files']}
**Pass Rate**: {data['pass_rate']:.1%}
**FAIL_OTHER**: {data.get('fail_other_rate', 0):.1%}
**FAIL_MARKDOWN**: {data.get('fail_markdown_rate', 0):.1%}

## Success Metrics

'''

if data['pass_rate'] >= 0.90:
    report += '✅ All success criteria met. Translation complete.\\n'
else:
    report += f'⚠️ Pass rate {data[\"pass_rate\"]:.1%} below 90% threshold. Manual review needed.\\n'

with open('$EVIDENCE_DIR/FINAL_REPORT.md', 'w') as out:
    out.write(report)
"

# Archive bundle
tar -czf "$EVIDENCE_DIR.tar.gz" -C "$EVIDENCE_DIR" .
echo "✅ Final evidence bundle created: $EVIDENCE_DIR.tar.gz"
```

**Acceptance Criteria**:
- ✅ Full corpus translated (~3,400 translations)
- ✅ Pass rate ≥90% (or documented failures for manual review)
- ✅ FAIL_OTHER <10%, FAIL_MARKDOWN <5%
- ✅ Active monitoring captured issues every 10 minutes
- ✅ 3-level retry attempted for all failures
- ✅ Final evidence bundle created with all artifacts

**Evidence Commands**:
```bash
# Check bulk completion
ls -lh runs/ct2_bulk_*/output/.translation_metadata.json

# Check final pass rate
cat runs/ct2_bulk_*/output/.translation_metadata.json | jq '.pass_rate'

# Check evidence bundle
tar -tzf runs/ct2_bulk_evidence_final_*.tar.gz

# Read final report
cat runs/ct2_bulk_evidence_final_*/FINAL_REPORT.md
```

**Files Created**:
- `artifacts/aspose_slides_full_corpus.txt` (NEW - full input list)
- `runs/ct2_bulk_*/output/.translation_metadata.json` (NEW - telemetry)
- `runs/ct2_bulk_*/output/*.log` (NEW - logs)
- `runs/ct2_bulk_evidence_final_*/FINAL_REPORT.md` (NEW - final report)
- `runs/ct2_bulk_evidence_final_*.tar.gz` (NEW - evidence bundle)

**Files Modified**: Translations written in-place to aspose.net corpus

**Dependencies**: CT2-003 GO decision

**Self-Review Dimensions**: 12/12 required (score ≥4/5 on each)

---

## Success Metrics Dashboard

### Target Status (After Completion)
| Metric | Target | Status |
|--------|--------|--------|
| Registry Created | 17 model entries | ⏳ PENDING (CT2-001) |
| Models Validated | All 17 valid | ⏳ PENDING (CT2-001) |
| Sampling Pass Rate | ≥90% | ⏳ PENDING (CT2-002) |
| Sampling Speed | ≥50 tokens/sec | ⏳ PENDING (CT2-002) |
| Go/No-Go Decision | GO (≥90%) | ⏳ PENDING (CT2-003) |
| Git Commits | Registry + Evidence | ⏳ PENDING (CT2-004) |
| Bulk Pass Rate | ≥90% | ⏳ PENDING (CT2-005) |
| Total Translations | ~3,400 | ⏳ PENDING (CT2-005) |
| Zero Code Changes | No Python changes | ⏳ PENDING (All) |

---

## Task Dependencies

```
CT2-001 (Registry Setup) → CT2-002 (Sampling Run) → CT2-003 (Analysis) → [CT2-004 (Commit), CT2-005 (Bulk)]

Critical Path:
  CT2-001 (Setup: 30 min) → CT2-002 (Sampling: 1 hour) → CT2-003 (Analysis: 15 min) → CT2-004 (Commit: 10 min) → CT2-005 (Bulk: 24-36 hours)

Total Timeline: ~1 day setup + 1-1.5 days bulk execution
```

---

## 12-Dimension Self-Review Checklist

Each task must score ≥4/5 on ALL 12 dimensions:

1. **Correctness**: Implementation matches specification
2. **Completeness**: All acceptance criteria met
3. **Testing**: Evidence commands executed and validated
4. **Documentation**: Clear evidence captured
5. **Error Handling**: Graceful degradation and retry logic
6. **Performance**: Meets speed and efficiency targets
7. **Security**: No credential leaks, proper permissions
8. **Maintainability**: Clear code/config structure
9. **Observability**: Adequate logging and telemetry
10. **Reversibility**: Easy to revert changes
11. **Scalability**: Handles full corpus load
12. **User Impact**: Minimal disruption, clear communication

**Stop-the-Line Conditions** (score <4/5 triggers re-work):
- Breaking changes introduced
- Pass rate <70% (kill signal)
- Zero code changes violated
- Silent failures or data loss
- Missing evidence or validation gaps

---

## Orchestrator Status

**Current Phase**: Ready for Step 3 (Spawn Agents)
**Next Actions**:
1. Spawn Agent A for CT2-001 (Registry Setup & Validation)
2. Monitor CT2-001 progress via evidence report
3. Upon CT2-001 completion, spawn Agent C for CT2-002 (Sampling Run)
4. Upon CT2-002 completion, spawn Agent D for CT2-003 (Analysis & Go/No-Go)
5. If GO decision:
   - Spawn Agent B for CT2-004 (Git Commit)
   - Spawn Agent C + E for CT2-005 (Bulk Run with monitoring)

**Risk Level**: MINIMAL (config-only, easy revert)
**Confidence Level**: VERY HIGH (95%+)
**User Decisions**: ALL 13 FINALIZED (no blockers)

---

**Backlog Status**: Ready for agent spawning
**Last Updated**: 2026-02-04
**User Approval**: PENDING

---

## Update — 2026-02-03 (Phase 6 Wave 2 Complete)

**Orchestrator Execution Progress**: Wave 2 agents completed successfully

### Workstream Completion Updates

**Workstream 1 (Classification Logic Enhancement)**:
- **Status**: ✅ COMPLETE (was PENDING)
- **Agent**: a88a321 (Agent B - Implementation)
- **Completion Date**: 2026-02-03
- **Tasks**: 5/5 complete (TASK-1.1 through TASK-1.5)
- **Self-Review Score**: 59/60 (98.3%)
- **Evidence**: `reports/agents/workstream1_classification/evidence.md`

**Workstream 2 (Verifier Failure Investigation)**:
- **Status**: ✅ COMPLETE (was PENDING)
- **Agent**: a744812 (Agent C - Investigation & Diagnostics)
- **Completion Date**: 2026-02-03
- **Tasks**: 3/3 complete (TASK-2.1 through TASK-2.3)
- **Self-Review Score**: 50/50 (100%)
- **Evidence**: Investigation reports in `reports/agents/workstream2_verifier/`

**Workstream 4 (AST Reconstruction Improvement)**:
- **Status**: ✅ COMPLETE (was PENDING)
- **Agent**: a6637d3 (Agent B - Implementation)
- **Completion Date**: 2026-02-03
- **Tasks**: 7/7 complete (TASK-4.1 through TASK-4.7)
- **Self-Review Score**: 58/60 (96.7%)
- **Evidence**: `reports/agents/workstream4_ast/evidence.md`
- **Key Achievement**: Fixed markdown formatting preservation (~255 lines in ast_renderer.py)

**Workstream 5 (Batch Deduplication Bug Fix)**:
- **Status**: ✅ COMPLETE (was PENDING)
- **Agent**: a7511bb (Agent B - Implementation)
- **Completion Date**: 2026-02-03
- **Tasks**: 5/5 complete (TASK-5.1 through TASK-5.5)
- **Self-Review Score**: 60/60 (100%)
- **Evidence**: `reports/agents/workstream5_batch/evidence.md`
- **Key Achievement**: 248 files → 248 unique records (0 duplicates)

### Updated Priority Matrix

| Priority | Work Item | Status | Tasks | Quality | Next Action |
|----------|-----------|--------|-------|---------|-------------|
| **HIGH** | Phase 6 WS1 (Classification) | ✅ COMPLETE | 5/5 | 98.3% | Integration testing |
| **HIGH** | Phase 6 WS2 (Verifier) | ✅ COMPLETE | 3/3 | 100% | Implement fixes |
| **HIGH** | Phase 6 WS4 (AST) | ✅ COMPLETE | 7/7 | 96.7% | Integration testing |
| **HIGH** | Phase 6 WS5 (Batch) | ✅ COMPLETE | 5/5 | 100% | Integration testing |
| **MEDIUM** | Phase 6 WS3 (Threshold) | ⏳ PENDING | 0/4 | - | Optional analysis |
| **HIGH** | Phase 6 Integration | ⏳ PENDING | 0/6 | - | **NEXT** |
| **MEDIUM** | Specs P0-P1 Items | ⏳ PENDING | 0/5 | - | Queue for next cycle |
| **LOW** | Technical Debt | ⏳ PENDING | 0/3 | - | Defer |

### Remaining Work Assessment

**Critical Path** (Integration & Validation):
1. **TASK-INT-1**: Merge all fixes into integration branch
2. **TASK-INT-2**: Run full pytest suite
3. **TASK-INT-3**: Manual smoke test (5 files)
4. **TASK-INT-4**: Re-run Phase 6 validation (248 files)
5. **TASK-INT-5**: Compare before/after pass rates
6. **TASK-INT-6**: Validate acceptance criteria

**Documentation Path**:
1. **TASK-DOC-1**: Create Phase 6 remediation report
2. **TASK-DOC-2**: Update FINAL_RESULTS.md
3. **TASK-DOC-3**: Update PLAN_SOURCES.md

### Evidence Summary

**All agents passed orchestrator quality gates (≥4/5 on all 12 dimensions)**:
- No stop-the-line conditions triggered
- Comprehensive evidence captured for all tasks
- Test coverage: 16+16+16 = 48+ tests created
- Code changes: ~750 lines across 3 core modules

**Expected Combined Impact**:
- FAIL_OTHER: 174 → 49 (-71.8%)
- Markdown fidelity: 37 → ≤7 (≥80% improvement)
- Batch duplicates: 233 → 0 (100% elimination)
- No verification data: 49 → 1 (98% reduction with WS2 fixes)
- **Target pass rate**: 13.3% → 60-70% (+4-5x improvement)

### Next Orchestrator Actions

**Option 1 (RECOMMENDED)**: Spawn integration testing agent
- **Agent Type**: Agent C (Tests & Verification)
- **Tasks**: TASK-INT-1 through TASK-INT-6
- **Estimated Duration**: 2-3 hours
- **Risk**: LOW (all fixes have unit tests)

**Option 2**: Spawn documentation agent first
- **Agent Type**: Agent D (Docs & Specs)
- **Tasks**: TASK-DOC-1 through TASK-DOC-3
- **Estimated Duration**: 1 hour
- **Purpose**: Document current state before integration testing

**Option 3**: Spawn WS3 threshold analysis agent
- **Agent Type**: Agent C (Investigation)
- **Tasks**: TASK-3.1 through TASK-3.4
- **Estimated Duration**: 1-2 hours
- **Purpose**: Analyze 106 FAIL_LINE_COUNT cases to inform threshold tuning

---

# Worker System Fix + Self-Healing Governance
**Plan**: [expressive-wibbling-teapot.md](plans/from_chat/20260206_110000_worker_system_fix_and_governance.md)
**Created**: 2026-02-06
**Status**: IN_PROGRESS

---

## Overview

Worker health audit (2026-02-06) found both autonomous workers offline for 13 days (since Jan 24). Root causes: L3SemanticTM API mismatch (2 bugs), missing Task Scheduler registration, missing Python packages, no watchdog/heartbeat/preflight system. 12 tasks across 5 workstreams.

---

## Workstream WF-1: Worker Code Fixes (F1+F2)
**Owner**: Agent B (Code Implementation)
**Priority**: CRITICAL
**Status**: PENDING

### TASK-F1: Fix L3SemanticTM device kwarg in Content Worker
**File**: `src/workers/autonomous_content_translation_worker.py:203-206`
**Status**: PENDING
**Risk**: LOW (single-line parameter rename)

**Description**: Change `device="cpu"` to `use_gpu=False` in L3SemanticTM constructor call.

**Acceptance Criteria**:
- `python -c "from src.workers.autonomous_content_translation_worker import AutonomousContentTranslationWorker; print('OK')"` passes
- Worker oneshot run does NOT contain `unexpected keyword argument 'device'`

### TASK-F2: Fix L3SemanticTM device kwarg in TM Worker
**File**: `src/workers/tm_improvement_worker.py:291-294`
**Status**: PENDING
**Risk**: LOW (single-line parameter rename)

**Description**: Change `device=self.config.device` to `use_gpu=(self.config.device == "cuda")` in L3SemanticTM constructor call.

**Acceptance Criteria**:
- `python -c "from src.workers.tm_improvement_worker import TMImprovementWorker; print('OK')"` passes
- Worker oneshot run does NOT contain `unexpected keyword argument 'device'`

---

## Workstream WF-2: Dependencies & Environment (F3+F4)
**Owner**: Agent E (Ops & Infra)
**Priority**: HIGH
**Status**: PENDING

### TASK-F3: Install Missing Python Packages
**Action**: `pip install fasttext-wheel sacremoses`
**Status**: PENDING
**Risk**: LOW (additive, no code changes)

**Acceptance Criteria**:
- `python -c "import fasttext; print('OK')"` passes
- `python -c "import sacremoses; print('OK')"` passes

### TASK-F4: Register Windows Task Scheduler Tasks
**Action**: Run `scripts/setup_task_scheduler.ps1` as Administrator
**Status**: PENDING
**Risk**: MEDIUM (requires admin privileges, system-level change)
**Prereq**: F1+F2+F3 verified

**Acceptance Criteria**:
- `Get-ScheduledTask | Where-Object { $_.TaskName -like 'HugoTranslator-*' }` shows ContentWorker + TMWorker in Ready state

---

## Workstream WF-3: CI/CD Fixes (F5+F6)
**Owner**: Agent E (Ops & Infra)
**Priority**: MEDIUM
**Status**: PENDING

### TASK-F5: Fix CLI Tests GitHub Actions Workflow
**File**: `.github/workflows/cli_tests.yml`
**Status**: PENDING
**Risk**: LOW (CI-only, no prod impact)

**Description**: Upgrade actions/checkout@v3→v4, actions/setup-python@v4→v5, add timeout-minutes, investigate requirements path error.

**Acceptance Criteria**:
- `gh workflow run "CLI Tests"` completes with `success`
- No deprecated action warnings

### TASK-F6: Fix Telemetry Health Check Workflow
**File**: `.github/workflows/telemetry_health_check.yml`
**Status**: PENDING
**Risk**: LOW (CI-only)

**Description**: Add timeout-minutes:10 to prevent 24h hang, upgrade action versions, document self-hosted requirement.

**Acceptance Criteria**:
- Workflow fails fast with timeout (not 24h hang)

---

## Workstream WF-4: Full Validation (F7)
**Owner**: Agent C (Tests & Verification)
**Priority**: HIGH
**Status**: PENDING
**Prereq**: WF-1 + WF-2 all verified

### TASK-F7: Full Worker Startup Validation
**Status**: PENDING
**Risk**: MEDIUM (end-to-end, may surface new issues)

**Description**: Run both workers in oneshot mode with CUDA and verify clean startup/execution/shutdown.

**Acceptance Criteria**:
- Content worker: No kwarg errors, `Initialized TranslationMemory`, `Initialized TranslationEngine`, no `fasttext package not installed`, clean exit
- TM worker: No kwarg errors, `Initialized TranslationMemory`, `LLM client initialized: ollama/llama2`, `Run #1 completed`, clean exit

---

## Workstream WF-5: Self-Healing Governance (G1-G5)
**Owner**: Agent B (Code) + Agent E (Ops)
**Priority**: HIGH
**Status**: PENDING
**Prereq**: WF-4 (F7) verified

### TASK-G1: Worker Watchdog Script
**File**: `scripts/worker_watchdog.ps1` (NEW)
**Owner**: Agent E (Ops)
**Status**: PENDING
**Risk**: MEDIUM (new component, process management)

**Description**: PowerShell script that checks worker liveness via PID files + heartbeat files, auto-restarts dead workers, has circuit breaker (max 5 restarts/hour).

**Acceptance Criteria**:
- Detects dead workers when run manually
- Restarts workers using existing .bat scripts
- Logs to `data/logs/watchdog.log`
- Circuit breaker triggers after 5 restarts in 1 hour

### TASK-G2: Heartbeat Emission in Workers
**Files**: `src/workers/autonomous_content_translation_worker.py`, `src/workers/tm_improvement_worker.py`
**Owner**: Agent B (Code)
**Status**: PENDING
**Risk**: LOW (additive, writes small files)

**Description**: Workers write heartbeat JSON files and PID files for watchdog monitoring. Heartbeat at start/end of each run cycle.

**Acceptance Criteria**:
- `data/logs/content_worker.heartbeat` created with valid JSON during oneshot run
- `data/logs/content_worker.pid` created with valid PID
- Same for tm_worker

### TASK-G3: Pre-Run Dependency Health Gate
**Files**: `src/workers/autonomous_content_translation_worker.py`, `src/workers/tm_improvement_worker.py`
**Owner**: Agent B (Code)
**Status**: PENDING
**Risk**: LOW (fail-safe: skip run, don't crash)

**Description**: Preflight check before each run: GPU availability, config validity, disk space, Ollama reachability (TM worker). Returns False → graceful skip, not crash.

**Acceptance Criteria**:
- With Ollama stopped: TM worker logs `PREFLIGHT FAIL: Ollama not reachable`, exits code 0
- With valid config: Worker proceeds normally

### TASK-G4: Worker Health GitHub Actions Workflow
**File**: `.github/workflows/worker_health_check.yml` (NEW)
**Owner**: Agent E (Ops)
**Status**: PENDING
**Risk**: LOW (CI-only, workflow_dispatch only)

**Description**: Manual-trigger CI workflow that runs health_check.py, checks processes, GPU status. Ready for self-hosted runner when available.

**Acceptance Criteria**:
- YAML passes lint
- `gh workflow list` shows Worker Health Check
- Runs on workflow_dispatch

### TASK-G5: Register Watchdog in Task Scheduler
**File**: `scripts/setup_task_scheduler.ps1` (MODIFY)
**Owner**: Agent E (Ops)
**Status**: PENDING
**Risk**: MEDIUM (system-level, requires admin)
**Prereq**: G1 verified

**Acceptance Criteria**:
- `Get-ScheduledTask -TaskName 'HugoTranslator-Watchdog'` shows Ready state
- Runs every 5 minutes
- `data/logs/watchdog.log` has entries after 5 min wait

---

## Execution Phases

| Phase | Tasks | Parallel | Prereqs |
|-------|-------|----------|---------|
| 1 | F1, F2, F3 | ✅ Yes | None |
| 2 | F4, F5, F6 | ✅ Yes | Phase 1 for F4 |
| 3 | F7 | No | Phase 1+2 |
| 4 | G1, G2 | ✅ Yes | Phase 3 |
| 5 | G3, G4, G5 | ✅ Yes | Phase 4 for G5 |

---

---

## Workstream 6: E2E Scheduled Trigger Verification
**Owner**: Agent E (Observability & Ops)
**Priority**: HIGH
**Status**: IN_PROGRESS
**Plan Source**: C:\Users\prora\.claude\plans\expressive-wibbling-teapot.md — ADDENDUM 3
**Created**: 2026-02-07 18:32 UTC

### Context
All worker fixes (F1-F7) and governance layer (G1-G5) are complete. Workers start correctly via Task Scheduler and run in daemon mode. Telemetry integration (T1) and oneshot verification (T2/T3) are complete. However, the full production path — Task Scheduler → daemon process → WindowScheduler sleep → scheduled run → telemetry + git commit — has never been tested since fixes were applied.

### Tasks

#### TASK-6.1: Phase 0 — Baseline Capture & Production Worker Shutdown
**Status**: PENDING
**Acceptance**: No worker processes running, watchdog disabled, telemetry baseline captured, auto_push=false

#### TASK-6.2: Phase 1 — Register Temporary E2E Tasks
**Status**: PENDING
**Acceptance**: Both HugoTranslator-E2E-ContentWorker and HugoTranslator-E2E-TMWorker tasks show Ready state

#### TASK-6.3: Phase 2 — Observe Startup
**Status**: PENDING
**Acceptance**: Tasks transition Ready→Running, heartbeats show starting→sleeping, PID files created

#### TASK-6.4: Phase 3 — Observe Daemon Run
**Status**: PENDING
**Acceptance**: Heartbeats transition to run_completed for both workers within 10 minutes of window_start

#### TASK-6.5: Phase 4 — Verify 5 Dimensions
**Status**: PENDING
**Acceptance Criteria**:
- Telemetry: New translate_directory + tm_improvement runs at localhost:8765
- Git: Auto-commit in test output directory with proper format
- Logs: Full daemon lifecycle in e2e_{content,tm}_worker.log
- Heartbeats: status=run_completed with fresh timestamps
- PIDs: Valid PIDs matching running processes

#### TASK-6.6: Phase 5 — Cleanup & Restore Production
**Status**: PENDING
**Acceptance**: E2E tasks unregistered, watchdog re-enabled, auto_push=true, production tasks intact


---

## Workstream 7: Corruption Prevention - Stop Bad Translations Overwriting Good Files
**Owner**: Agent B (Implementation), Agent C (Verification)
**Priority**: CRITICAL
**Status**: PENDING
**Plan Source**: C:\Users\prora\.claude\plans\streamed-juggling-twilight.md
**Created**: 2026-02-10
**Estimated**: ~12 hours (8 hours implementation + 4 hours VFV)

### Context

**Critical Data Loss Issue**: Good translations are being replaced with multi-language garbage despite initial fixes (commits 2b57397, 42c7fe5). User feedback: "good translation was replaced with bad one" - compress-files-online/index.ar.md had proper Arabic replaced with mixed English/garbage (user discarded changes).

**Root Cause - 3-Agent Investigation (ad2fdfb, ab0ac25, aa0d3fe)**:
- **8 validation bypass routes** identified (exception swallowing, batch failures don't propagate, write-before-verify, etc.)
- **Initial fixes insufficient**: Fixed FastText instantiation bug but exception swallowing still allows other errors through
- **User requirement**: "the check must be not to replace the file if it contains bad translation"
- **Testing requirement**: "plan must include vfv loop for translation through cli...then run...through worker"

### Implementation Tasks (Phase 1-5)

#### TASK-7.1: Phase 1.1 - Fix Exception Handling (No More Swallowing)
**File**: `src/translation_engine/engine.py` (lines 1492-1495)
**Owner**: Agent B (Implementation)
**Status**: PENDING
**Risk**: MEDIUM (changes exception flow, must test thoroughly)

**Description**: Replace bare `except Exception` with specific exception handling. ImportError → fatal (block write), IOError → non-fatal (allow write), ValueError → decide based on context. No catch-all that allows writes.

**Acceptance Criteria**:
- If FastText unavailable: logs ERROR, sets result.success=False, continues to next language
- If existing file unreadable: logs WARNING, allows write (new translation)
- If detection uncertain: logs WARNING, decides based on existing file quality
- No "Language validation failed (non-fatal)" warnings in logs
- VFV CLI test: bad translation blocked with clear error message

#### TASK-7.2: Phase 1.2 - Make Language Detection Mandatory
**File**: `src/translation_engine/extractor/text_unit_extractor.py` (lines 903-908)
**Owner**: Agent B (Implementation)
**Status**: PENDING
**Risk**: LOW (fail-safe improvement)

**Description**: Change detector unavailable behavior from `return True` (bypass) to `raise RuntimeError`. No translations without language validation.

**Acceptance Criteria**:
- With FastText & langdetect uninstalled: raises RuntimeError "Language detector required"
- Translation process stops immediately (doesn't proceed without validation)
- Clear error message guides user to install detectors

#### TASK-7.3: Phase 1.3 - Propagate Batch Failures to File Level
**File**: `src/translation_engine/engine.py` (line 2040+)
**Owner**: Agent B (Implementation)
**Status**: PENDING
**Risk**: MEDIUM (adds new validation logic, must not break good translations)

**Description**: After `batch_translate_units()`, check `extractor.batch_stats`. If >10% of batches failed purity, block write. Pass batch_stats to validation context.

**Acceptance Criteria**:
- With high batch failure rate (>10%): logs ERROR "HIGH PURITY FAILURE RATE", sets result.success=False
- With low batch failure rate (<10%): proceeds normally
- Batch statistics visible in logs for debugging
- VFV Edge Case test: high batch failure rate blocks write

#### TASK-7.4: Phase 2.1 - Pre-Write Existing File Quality Check
**File**: `src/translation_engine/engine.py` (before line 1495)
**Owner**: Agent B (Implementation)
**Status**: PENDING
**Risk**: HIGH (adds file comparison logic, critical for preventing data loss)
**Prereq**: TASK-7.1

**Description**: Before write, if output file exists: read existing, detect language, compare confidence. BLOCK if: (1) existing correct + new wrong, (2) existing higher confidence than new, (4) both wrong. ALLOW if: (3) existing wrong + new correct (healing).

**Acceptance Criteria**:
- Existing good file + bad new translation: logs "OVERWRITE BLOCKED", sets result.success=False
- Existing bad file + good new translation: logs "HEALING OVERWRITE", allows write
- Both wrong: logs "OVERWRITE BLOCKED", blocks write
- Existing unreadable: logs WARNING, allows write (failsafe)
- VFV Edge Case test: existing good file NOT overwritten

#### TASK-7.5: Phase 2.2 - Add File-Level Language Purity Verification
**File**: `src/translation_engine/engine.py` (new method + integration)
**Owner**: Agent B (Implementation)
**Status**: PENDING
**Risk**: MEDIUM (adds new verification layer)
**Prereq**: TASK-7.3

**Description**: Add `_verify_final_file_purity()` method. Splits content into paragraphs, detects language for each, fails if >5% wrong language. Catches issues batch-level checks missed.

**Acceptance Criteria**:
- Method `_verify_final_file_purity()` implemented with paragraph splitting
- If >5% paragraphs wrong language: returns passed=False with reason
- Integrated before write operation in main translation loop
- VFV CLI test: mixed-language file blocked with "FINAL PURITY CHECK FAILED"

#### TASK-7.6: Phase 3.1 - Restructure Write Flow (Verify THEN Write)
**File**: `src/translation_engine/engine.py` (lines 1433-1525)
**Owner**: Agent B (Implementation)
**Status**: PENDING
**Risk**: HIGH (major refactor of write flow, must preserve all functionality)
**Prereq**: TASK-7.1, TASK-7.4, TASK-7.5

**Description**: Change flow from write→verify→decide to validate→decide→write. Run ALL validation (pre-write detection, existing file check, final purity, verification suite) BEFORE write. Only write if validation_passed=True.

**Acceptance Criteria**:
- Validation runs before any file write operations
- If validation fails: no file written, result.success=False with error message
- If validation passes: write file, add to outputs
- All existing validation preserved (no regression)
- VFV CLI test: validation failure prevents file creation

#### TASK-7.7: Phase 4.1 - Re-Validate Individual Fallback Translations
**File**: `src/translation_engine/extractor/text_unit_extractor.py` (lines 677-714)
**Owner**: Agent B (Implementation)
**Status**: PENDING
**Risk**: LOW (adds validation to fallback path)

**Description**: In `_fallback_to_individual()`, after translating each unit individually, validate language. If wrong language with high confidence (>70%), mark unit as failed (empty string). Track in batch_stats['individual_purity_failures'].

**Acceptance Criteria**:
- Individual translations validated with language detection
- Wrong-language results marked empty (not returned as valid)
- Failures tracked in batch_stats for visibility
- VFV CLI test: individual fallback path validates correctly

#### TASK-7.8: Phase 5.1 - Make Quality Gates Mandatory in Production
**Files**: `src/translation_engine/engine.py` (line 196), `config/global.yaml`
**Owner**: Agent B (Implementation)
**Status**: PENDING
**Risk**: LOW (configuration change)
**Prereq**: TASK-7.1 through TASK-7.7

**Description**: Change `enable_validation` default from False to True. Add quality gate configuration section to global.yaml with production-safe defaults.

**Acceptance Criteria**:
- engine.py line 196: `enable_validation: bool = True`
- global.yaml has new section: `translation_engine.enable_validation: true`, `require_language_detector: true`, etc.
- All validation enabled by default (must explicitly disable)
- Documentation updated with new defaults

### Verification Tasks (VFV Loops)

#### TASK-7.9: VFV Loop 1 - CLI Translation Verification
**Owner**: Agent C (Verification)
**Status**: PENDING
**Risk**: LOW (testing only)
**Prereq**: TASK-7.1 through TASK-7.8

**Description**: V1: Test single file translation (compress-files-online/index.md → ar) with --force-retranslate. F1: Fix any issues found. V2: Re-test to verify fixes.

**Acceptance Criteria**:
- Translation completes without validation bypass warnings
- If validation fails: write BLOCKED with clear error message
- Existing good files NOT overwritten by bad translations
- Logs show which validation gate acted (exception type, existing file check, purity check)
- verify_corruption_fixes.py all tests pass

#### TASK-7.10: VFV Loop 2 - Worker Translation Verification
**Owner**: Agent C (Verification)
**Status**: PENDING
**Risk**: LOW (testing only)
**Prereq**: TASK-7.9 (VFV Loop 1 passes)

**Description**: Run worker in oneshot mode on SAME file as CLI test. Verify worker produces same quality as CLI. Check commits created with validated files only.

**Acceptance Criteria**:
- Worker produces SAME quality as CLI for same file
- Batch-level purity failures propagate to file-level decision
- Existing good files NOT overwritten
- Files that pass validation ARE committed to git
- Commit includes only quality-validated files
- No "Language validation failed (non-fatal)" warnings
- Git diff shows only high-quality translations (no mixed-language content)

#### TASK-7.11: VFV Loop 3 - Edge Cases Verification
**Owner**: Agent C (Verification)
**Status**: PENDING
**Risk**: LOW (testing only)
**Prereq**: TASK-7.10 (VFV Loop 2 passes)

**Description**: Test 3 problematic scenarios: (1) Malay vs Indonesian confusion, (2) Existing good file protection, (3) High batch failure rate.

**Acceptance Criteria**:
- Test 1: If model produces Indonesian instead of Malay, write BLOCKED
- Test 2: Existing good file NOT overwritten even with --force-retranslate
- Test 3: If >10% batches fail purity, file write BLOCKED with clear log message
- All edge cases handled correctly (no crashes, no data loss)

---

## Execution Order - Corruption Prevention

| Phase | Tasks | Parallel | Prereqs | Estimated |
|-------|-------|----------|---------|-----------|
| 1A | 7.1, 7.2 | ✅ Yes | None | 2 hours |
| 1B | 7.3 | No | 7.1 | 1 hour |
| 2 | 7.4, 7.5 | ✅ Yes | 7.1, 7.3 | 2 hours |
| 3 | 7.6 | No | 7.1, 7.4, 7.5 | 2 hours |
| 4 | 7.7 | No | None (can parallel with 1-3) | 1 hour |
| 5 | 7.8 | No | 7.1-7.7 complete | 30 min |
| VFV1 | 7.9 | No | 7.8 | 1 hour |
| VFV2 | 7.10 | No | 7.9 passes | 1 hour |
| VFV3 | 7.11 | No | 7.10 passes | 1 hour |

**Total Estimated Time**: ~11.5 hours (8 hours implementation + 3.5 hours VFV)

---

## Success Criteria - Corruption Prevention

✅ **No more corruption**:
- Files with bad translations NEVER written to disk
- Existing good files NEVER overwritten by bad translations
- Quality downgrades BLOCKED at write time

✅ **Validation enforced**:
- All validation failures BLOCK writes (no bypasses)
- Batch-level failures propagate to file-level decisions
- Individual fallback translations re-validated
- No catch-all exception handlers that allow writes

✅ **Quality gates mandatory**:
- Validation enabled by default in production
- Language detector required (fail if unavailable)
- Clear error messages when validation blocks writes

✅ **VFV loops pass**:
- CLI translation produces validated output
- Worker produces same quality as CLI
- Both block bad translations consistently
- Commits contain only validated files
- Edge cases handled properly

✅ **Zero regressions**:
- Good translations still work normally
- Performance impact < 10% (validation overhead)
- All existing tests pass
- Quality improvement visible in logs

---

## Rollback Plan - Corruption Prevention

If issues occur after implementation:

1. **Quick revert**: `git log --oneline -5` → find commit before fix → `git checkout <commit>`
2. **Stop workers**: `Stop-Process -Name python -Force`
3. **Disable Task Scheduler**: Until validated in production
4. **Restore corrupted files**: `cd D:\onedrive\Documents\GitHub\aspose.net` → `git checkout HEAD -- <files>`

## Update — 2026-02-16 22:36 PKT

### Orchestrator Backlog Merge (Worker Health + Runtime Drift)

Sources merged this pass:
- `plans/healing/worker-health-audit-healing-20260216.md`
- `docs/technical_debt/TODO_FIXME_ITEMS.md`
- `docker-compose.yml`
- `scripts/setup_task_scheduler.ps1`
- `scripts/check_worker_health.ps1`
- `reports/agents/Agent_A/ORCH-AW-001/run_20260216_223609/artifacts/*`
- `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/artifacts/*`

### Parallel Workstreams (max 5 active)

| ID | Scope | Owner-Agent | Status | Risk |
|---|---|---|---|---|
| ORCH-AW-001 | Repo/runtime worker topology and deployment drift baseline | Agent A | Done | Medium |
| ORCH-AW-002 | Fix detector wiring crash in TranslationEngine (SR-03) | Agent B | Done | High |
| ORCH-AW-003 | Validate worker behavior via targeted tests + manual oneshot run | Agent C | Done | Medium |
| ORCH-AW-004 | Sync docs/specs with SR-03 changes and runtime findings | Agent D | Done | Low |
| ORCH-AW-005 | Observability/ops triage for backlog, dependency, timeout-loop blockers | Agent E | In Progress | High |

### Normalized Tasks

#### ORCH-AW-001
- Scope: Build evidence-backed worker topology and runtime drift snapshot for current host.
- Owner-agent: Agent A (Discovery & Architecture)
- Affected paths: `docker-compose.yml`, `scripts/setup_task_scheduler.ps1`, `scripts/check_worker_health.ps1`, `src/workers/__main__.py`, `reports/agents/Agent_A/ORCH-AW-001/run_20260216_223609/**`
- Acceptance criteria: Runtime capabilities detected; active worker containers/services enumerated; repo-vs-runtime drift explicitly listed with evidence links.
- Required tests: Read-only verification commands (`docker ps`, task scheduler query, worker pattern scan).
- Required docs/spec updates: `reports/STATUS.md` summary entry for drift findings.
- Evidence: `reports/agents/Agent_A/ORCH-AW-001/run_20260216_223609/evidence.md`

#### ORCH-AW-002
- Scope: Remove `TranslationEngine.detector` attribute crash path and preserve compatibility.
- Owner-agent: Agent B (Implementation)
- Affected paths: `src/translation_engine/engine.py`, `tests/unit/translation_engine/test_engine_detector_wiring.py`, `reports/agents/Agent_B/ORCH-AW-002/run_20260216_223609/**`
- Acceptance criteria: No `"has no attribute 'detector'"` failure in current oneshot logs; regression tests green.
- Required tests: `pytest` worker slice including new detector wiring tests.
- Required docs/spec updates: Document SR-03 delta in operations/spec docs.
- Evidence: `reports/agents/Agent_B/ORCH-AW-002/run_20260216_223609/evidence.md`

#### ORCH-AW-003
- Scope: Verify behavior of autonomous workers after SR-03 patch with tests + manual trigger evidence.
- Owner-agent: Agent C (Tests & Verification)
- Affected paths: `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/**`
- Acceptance criteria: Target pytest suite passes; manual oneshot execution evidence captured; unresolved failures converted into backlog gaps.
- Required tests: `.venv\\Scripts\\python.exe -m pytest ...` worker suite.
- Required docs/spec updates: Feed new blockers into healing plan/task backlog.
- Evidence: `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/evidence.md`

#### ORCH-AW-004
- Scope: Merge-update docs/specs to match observed worker behavior and known blockers.
- Owner-agent: Agent D (Docs & Specs)
- Affected paths: `docs/operations/troubleshooting.md`, `specs/autonomous_workers/AUTONOMOUS_CONTENT_TRANSLATION_WORKER.md`, `reports/agents/Agent_D/ORCH-AW-004/run_20260216_223609/**`
- Acceptance criteria: Update sections appended with timestamp; evidence links included; no existing content removed.
- Required tests: N/A (documentation task); validate referenced paths exist.
- Required docs/spec updates: Included in task scope.
- Evidence: `reports/agents/Agent_D/ORCH-AW-004/run_20260216_223609/evidence.md`

#### ORCH-AW-005
- Scope: Triages workload/dependency observability and convert unresolved issues into executable hardening tasks.
- Owner-agent: Agent E (Observability & Ops)
- Affected paths: `plans/healing/worker-health-audit-healing-20260216.md`, `reports/agents/Agent_E/ORCH-AW-005/run_20260216_223609/**`
- Acceptance criteria: Queue/backlog/dependency unknowns are explicit; newly observed timeout-loop issue mapped to new taskcard (`SR-04`).
- Required tests: `scripts/check_worker_health.ps1` run + evidence capture.
- Required docs/spec updates: Add new gap/taskcard in healing plan and status report.
- Evidence: `reports/agents/Agent_E/ORCH-AW-005/run_20260216_223609/evidence.md`

### Legacy Notes (Preserved)
- Existing Phase 6 task IDs (`TASK-1.x`, `TASK-2.x`) remain valid historical backlog items; this update does not delete or rewrite them.
- Technical-debt TODO inventory remains at `docs/technical_debt/TODO_FIXME_ITEMS.md` and is now linked to orchestrator tracking via ORCH-AW-005.



---

## WORKSTREAM: VRAM-Aware Model Lifecycle
**Date Added**: 2026-02-21
**Plan Source**: `plans/from_chat/20260221_0000_from_chat_vram-lifecycle.md`
**Status**: VRAM-001 COMPLETE; VRAM-002, VRAM-003, VRAM-004 PENDING

### Context
Workers were holding 12-16 GB of RTX 4090 VRAM during all sleep gaps (~80 min content worker, ~6 h TM worker).
5 code changes implemented and verified. Unit tests, live evidence, and docs are the remaining deliverables.

---

#### VRAM-001 (COMPLETE)
- **Scope**: Implement VRAM lifecycle: offload before sleep, reload on wake — 5 changes across 5 files
- **Owner-agent**: Orchestrator (implemented inline)
- **Affected paths**:
  - `src/model_runtime/loader.py` (CTranslate2Backend.unload() — lines 1049-1051)
  - `src/workers/autonomous_content_translation_worker.py` (_offload_models() — lines 317-338, daemon loop 538-539)
  - `src/intelligence/llm_client.py` (unload_from_server() — lines 194-197)
  - `src/tm/l3_semantic.py` (offload_to_cpu() — lines 503-528; reload_to_gpu() — lines 530-553)
  - `src/workers/tm_improvement_worker.py` (_offload_resources() — lines 447-478; daemon 671; _execute_improvement_run 803)
  - `scripts/start_workers.ps1` (SelfPidFile parameter)
  - `scripts/_disable_tasks.ps1` (NEW — bulk Task Scheduler disable)
- **Acceptance criteria**: All 5 changes present (verified by Explore agent a5314d0); [VRAM] log events appear in worker logs after first run
- **Evidence**: Explore agent verification report (session 2026-02-21)
- **Status**: DONE

---

#### VRAM-002 (PENDING)
- **Scope**: Write unit tests for all 5 VRAM lifecycle changes (~40 test cases across 4 test files)
- **Owner-agent**: Agent B (Tests & Verification)
- **Affected paths**:
  - `tests/unit/workers/test_content_worker_vram.py` (NEW — test _offload_models())
  - `tests/unit/workers/test_tm_worker_vram.py` (NEW — test _offload_resources(), reload_to_gpu on run)
  - `tests/unit/model_runtime/test_loader_ct2_unload.py` (NEW — test CT2 cuda.empty_cache)
  - `tests/unit/translation_memory/test_l3_offload.py` (NEW — test offload_to_cpu/reload_to_gpu)
- **Acceptance criteria**:
  - All 4 test files created; all tests pass with .venv pytest
  - `_offload_models()`: test no-op when no model loaded, test calls unload_all() when models present, test gc.collect() + empty_cache() called
  - `unload_from_server()`: test no-op for non-Ollama providers, test calls provider.shutdown()
  - `offload_to_cpu()`: test FAISS index moved CPU, test encoder device changed, test thread-safe
  - `reload_to_gpu()`: test FAISS index moved GPU, test encoder device changed, test no-op if already on GPU
  - `_offload_resources()`: test Ollama unload called, test l3.offload_to_cpu called, test cache flush
- **Required tests**: .venv/Scripts/python.exe -m pytest tests/unit/workers/test_content_worker_vram.py tests/unit/workers/test_tm_worker_vram.py tests/unit/model_runtime/test_loader_ct2_unload.py tests/unit/translation_memory/test_l3_offload.py -v
- **Required docs/spec updates**: None (implementation-only)
- **Evidence**: `reports/agents/Agent_B/VRAM-002/run_<timestamp>/evidence.md`

---

#### VRAM-003 (PENDING)
- **Scope**: Collect live evidence that VRAM lifecycle works in production (log events + nvidia-smi readings)
- **Owner-agent**: Agent C (Verification & Evidence)
- **Affected paths**:
  - `data/logs/content_worker.log` (grep [VRAM] events)
  - `data/logs/tm_worker.log` (grep [VRAM] events)
  - `reports/agents/Agent_C/VRAM-003/run_<timestamp>/evidence.md`
- **Acceptance criteria**:
  - Content worker log shows `[VRAM] Offloading N model(s) before sleep` then `[VRAM] Models offloaded`
  - TM worker log shows `[VRAM] Signalled Ollama to unload` or similar
  - nvidia-smi reading taken while both workers sleeping shows <1 GB (or document baseline if workers not running)
  - Evidence file captures all readings with timestamps
- **Required tests**: N/A (evidence collection)
- **Required docs/spec updates**: None
- **Evidence**: `reports/agents/Agent_C/VRAM-003/run_<timestamp>/evidence.md`
- **Note**: Requires workers to be running at least one cycle; may need to trigger a --run-immediately pass first

---

#### VRAM-004 (PENDING)
- **Scope**: Update MEMORY.md + worker operations docs to document VRAM lifecycle behaviour
- **Owner-agent**: Agent D (Docs & Specs)
- **Affected paths**:
  - `C:\Users\prora\.claude\projects\c--Users-prora-OneDrive-Documents-GitHub-hugo-translator\memory\MEMORY.md`
  - Existing worker docs (if any) in `docs/operations/` or `specs/autonomous_workers/`
- **Acceptance criteria**:
  - MEMORY.md records: _offload_models() called before each sleep in content worker; _offload_resources() in TM worker; unload_from_server() for Ollama; offload_to_cpu()/reload_to_gpu() for L3 FAISS
  - Note added: Task Scheduler re-enables tasks after disable; use _disable_tasks.ps1 with admin elevation
  - All referenced line numbers match current implementation
- **Required tests**: N/A (documentation task)
- **Required docs/spec updates**: Included in task scope
- **Evidence**: `reports/agents/Agent_D/VRAM-004/run_<timestamp>/evidence.md`

---

### Legacy Notes (Preserved)
- Existing workstreams (ORCH-AW-001 through ORCH-AW-005) remain valid
- VRAM workstream does not modify or invalidate any prior tasks

## Workstream: TS-ROBUST-001 — Task Scheduler Robustness (2026-02-27)
_Spawned by: Orchestrator | Owner-agent: B (Implementation)_

### Task TS-ROBUST-001-A: Update trigger definitions
- Scope: scripts/setup_task_scheduler.ps1 lines 84, 126, 214
- Action: Replace single AtStartup with [AtLogon+delay, AtStartup+delay] array
- Acceptance: Each worker task shows 2 triggers in Get-ScheduledTask output
- Risk: LOW — script re-runnable, tasks can be deleted/re-registered

### Task TS-ROBUST-001-B: Reduce watchdog interval
- Scope: scripts/setup_task_scheduler.ps1 line 173
- Action: Change -Hours 1 to -Minutes 15
- Acceptance: Trigger interval = PT15M

### Task TS-ROBUST-001-C: Add MultipleInstances IgnoreNew
- Scope: scripts/setup_task_scheduler.ps1 settings objects for tasks 1, 2, 4
- Action: Add -MultipleInstances IgnoreNew parameter
- Acceptance: Settings.MultipleInstances = IgnoreNew

### Task TS-ROBUST-001-D: Re-register and verify tasks
- Scope: Run setup_task_scheduler.ps1 with elevation
- Action: Verify via PowerShell evidence commands
- Acceptance: All 4 tasks Ready, heartbeats fresh after simulated start

---

# Workstream: Publish-Readiness Remediation
**Plan**: [20260417_publish_readiness.md](plans/from_chat/20260417_publish_readiness.md)
**Added**: 2026-04-17
**Status**: IN_PROGRESS

## Stage 1 — Confirmed Pipeline Bugs

### TASK-S1A: Remove hardcoded Ollama args from start_workers.ps1
**File**: `scripts/start_workers.ps1:102-103`
**Owner**: Agent B
**Priority**: CRITICAL — silently misconfigures every TM worker run
**Status**: PENDING

### TASK-S1B: Fix content hash tracker initialization in engine.py
**File**: `src/translation_engine/engine.py:411-416`
**Owner**: Agent B
**Priority**: HIGH — feature documented as "enabled by default" is dead code
**Status**: PENDING

### TASK-S1D: Fix CI regression gate
**File**: `.github/workflows/release_gate.yml`
**Owner**: Agent B
**Priority**: HIGH — regression tests silently pass regardless of outcome
**Status**: PENDING

## Stage 3 — Documentation

### TASK-S3A: Rewrite README.md architecture + fix content-hash claim
### TASK-S3B: Create AGENTS.md
### TASK-S3C: Create docs/getting-started/ONBOARDING.md
### TASK-S3D: Create docs/operations/windows-native-deployment.md
### TASK-S3E: Archive docs/_audit/, stale reports
### TASK-S3F: CHANGELOG disclaimer + scripts/README.md

## Stage 2 — Pipeline Architecture

### TASK-S2A: Completion-aware file selection
### TASK-S2B: L3 FAISS delete-before-add
### TASK-S2C: Retranslate queue

---

## Workstream: WS-LMDB-HEAL-20260418 — L2 LMDB Post-Sprint Gap Resolution
_Added: 2026-04-18 | Plan: `plans/healing/lmdb-post-sprint-gaps.md`_
_TM test fixes plan: `plans/healing/test-gaps-post-sprint.md`_

### Status Summary

| Task    | Status   | Blocker                                          |
|---------|----------|--------------------------------------------------|
| LMDB-01 | DONE     | —                                                |
| LMDB-02 | DONE     | —                                                |
| LMDB-06 | DONE     | —                                                |
| TM-01   | DONE     | —                                                |
| TM-02   | DONE     | —                                                |
| TM-03   | DONE     | —                                                |
| TM-04   | DONE     | —                                                |
| LMDB-07 | EXECUTING| None — running now                               |
| TM-05   | BLOCKED  | TestASTEndToEnd: 3/5 fail; skip guard pre-exists |
| LMDB-03 | BLOCKED  | Workers running; requires maintenance window     |
| LMDB-04 | BLOCKED  | Workers running; requires user confirmation      |
| LMDB-05 | BLOCKED  | Depends on LMDB-03 + LMDB-04                    |

### LMDB-07 (EXECUTING)
- **Scope**: Delete ~112 GB orphaned LMDB test artifacts from `C:\Users\prora\AppData\Local\Temp`
- **Owner-agent**: Orchestrator (PowerShell runbook)
- **Impacted paths**: `%TEMP%\tmp*` dirs containing `l2.lmdb` or `tm.lmdb`
- **Acceptance**: Before count > 0; after count = 0; evidence file saved
- **Risk**: LOW — temp files only; no source or production data
- **Evidence**: `plans/healing/lmdb-07-temp-cleanup-evidence.txt`

### LMDB-04 Maintenance Window (BLOCKED — awaiting user confirmation)
- **Scope**: Stop 4 Task Scheduler tasks; compact `data/tm/l2.lmdb`; delete `data/tm/l2_lmdb`
- **Owner-agent**: Orchestrator (PowerShell + bash runbook)
- **Preconditions**: LMDB-03 gap assessment run first (inside same window)
- **Impacted paths**: `data/tm/l2.lmdb`, `data/tm/l2_lmdb`, `data/tm_test/l2_lmdb`
- **Acceptance**: `data.mdb` < 1800 MiB; entry count ≥ 696,933; stale dirs deleted
- **Risk**: MEDIUM — requires worker downtime; backup auto-created by compact script
- **Evidence**: `plans/healing/lmdb-04-compact-evidence.txt`

### LMDB-03 (Runs inside LMDB-04 window)
- **Scope**: Count entries in `l2_lmdb` absent from `l2.lmdb`; merge if any found
- **Evidence**: `plans/healing/lmdb-03-gap-assessment.txt`

### LMDB-05 (After LMDB-04)
- **Scope**: Re-enable workers; validate single-database convergence; no MapFullError
- **Evidence**: `plans/healing/lmdb-05-convergence-evidence.txt`

### TM-05 (BLOCKED — needs investigation)
- **Scope**: Determine why 3 of 5 `TestASTEndToEnd` tests fail with `RuntimeError("Translation failed: []")`
- **Notes**: Skip guard pre-exists at lines 66-69 of `test_ast_e2e_validation.py`; model IS present; 2 tests pass

### Integration tests unblock dependency
- `test_parallel_mode.py` + `test_roundrobin_mode.py` Fixes 1 & 2 will fully green after LMDB-04 releases the l2.lmdb lock

---

## WS-HEAL-20260418-AST (TC-AST-03) — Ancestor-Aware Gap Counting

### TC-AST-03 (DONE — 2026-04-18, commit pending)
- **Scope**: Make `_apply_to_node()` ancestor-aware so STRONG/EMPHASIS nodes inside Path A PARAGRAPH units are not counted as missing-node gaps
- **Root cause**: `_has_descendant_in_unit_map()` (TC-MLD-06) only checks descendants; Path A PARAGRAPH ancestor coverage was not checked, producing 112 false-positive STRONG nodes (39.3%) on `barcode/add-barcode-in-asp-dotnet-mvc`
- **Fix**: Added `ancestor_in_unit_map: bool = False` param to `_apply_to_node`; propagated through recursion; added `and not ancestor_in_unit_map` guard before `_missing_node_count += 1`
- **Result**: `ast_fallback_node_tolerance` reset from 0.5 → 0.0 (intended strict production setting)
- **Tests**: 5 new regression tests in `tests/unit/translation_engine/reconstructor/test_ast_renderer_ancestor_coverage.py` — all pass
- **Files**: `src/translation_engine/reconstructor/ast_renderer.py`, `config/global.yaml`
- **Plan ref**: `plans/healing/AUDIT-20260418-AST-translation-quality.md`

---

## WS-MLD-20260421 — Mixed-Language Contamination: Investigate, Fix, Heal, Verify (quiet-coalescing-pebble)

**Plan**: `C:\Users\prora\.claude\plans\quiet-coalescing-pebble.md`
**Added**: 2026-04-21
**Status**: IN_PROGRESS

### TC-FIX-01: Remove `accept_after_max_retries=True` from lenient mode
**Status**: DONE — 2026-04-21
**File**: `src/translation_engine/engine.py` (~line 378)
**Root cause (RC-1)**: Lenient mode was writing wrong-language files to disk after all validation retries exhausted.
**Fix**: Removed the `accept_after_max_retries: true` override from the lenient mode config dict. Lenient mode now inherits `accept_after_max_retries: false` from `validation.yaml`, consistent with all other modes.
**Acceptance**: Line removed; stale lenient-mode unit test updated to match new behavior.

### TC-FIX-02: Remove `--fast` from post-run contamination scan; raise timeout
**Status**: DONE — 2026-04-21
**File**: `src/workers/autonomous_content_translation_worker.py` (~line 1173)
**Root cause (RC-2)**: `--fast` (regex-only) was blind to same-script contamination (English in Spanish/French/German).
**Fix**: `--fast` removed; `--workers 16` added; timeout raised 180s → 600s.
**Acceptance**: Post-run scan now runs langdetect sentence analysis. Same-script contamination detected.

### TC-FIX-03: Enable LLM escalation for CASE 4 stuck files
**Status**: DONE — 2026-04-21
**File**: `config/global.yaml` (line 632)
**Root cause (RC-3)**: CASE 4 files looped to quarantine without LLM fallback. 87 queue entries, 4 at retry≥2.
**Fix**: `llm_escalation_enabled: false` → `true`
**Acceptance**: On next worker run, files with retry_count≥2 receive LLM escalation via `professionalize_llm`.

### TC-FIX-04: Enable SemanticSimilarityValidator
**Status**: DONE — 2026-04-21
**File**: `config/validation.yaml` (~line 126)
**Change**: `enabled: false` → `true`; warn_threshold: 0.55; error_threshold: 0.40
**Acceptance**: Validator runs in translation pipeline; warns on semantic drift; does not block passing translations.

### TC-FIX-05: Bold normalization P1 pattern fix (ast_renderer.py)
**Status**: DONE — 2026-04-21
**File**: `src/translation_engine/reconstructor/ast_renderer.py`
**Root cause**: P1 pattern `{2,}` required 3+ words; 2-word phrases (e.g. `* Exportação PDF*`) not normalized. Greedy repetition also captured trailing space into group → `**Text **` output.
**Fix**: `{2,}` → `{1,}`; replaced `r'**\1**'` with `lambda m: f'**{m.group(1).rstrip()}**'`.
**Tests**: All 23 bold normalization tests pass.

### TC-FIX-06: Lithuanian threshold stale test fix
**Status**: DONE — 2026-04-21
**File**: `tests/unit/translation_engine/test_purity_threshold_override.py` (line 382)
**Fix**: Updated expected value `0.30` → `0.15` (matches TC-13 config change from prior session).

### TC-INV-02: Full contamination scan (background)
**Status**: IN_PROGRESS
**Command**: `scan_language_contamination.py --profiles-dir config/site_profiles --all-languages --block-level --check-repetition --workers 16 --json-output reports/agents/contamination_audit/inventory_20260421.json`
**Output**: Pending — `reports/agents/contamination_audit/inventory_20260421.json`

### TC-CLEAN-01: Repair L2 cache (937 contaminated entries)
**Status**: BLOCKED — LMDB lock held by worker process
**Pending**: Run `audit_l2_cache_contamination.py --repair` once lock is released.
**Evidence (dry run)**: `reports/agents/contamination_audit/l2_audit_20260421.json` — 937 contaminated entries (Spanish→Arabic/Bulgarian key collision)

### TC-CLEAN-02: Queue contaminated output files for retranslation
**Status**: PENDING — depends on TC-INV-02 + TC-CLEAN-01

### TC-CLEAN-03: Retranslate — worker oneshot per affected site
**Status**: PENDING — depends on TC-CLEAN-02

### TC-VFY-01: Second full scan — compare before/after contaminated counts
**Status**: PENDING — depends on TC-CLEAN-03

### TC-VFY-03: Unit test — lenient mode no longer accepts after max retries
**Status**: PENDING

### TC-VFY-06: Safety proof document
**Status**: PENDING

---

## WS-P0-SHIPPING-20260425 — Shipping Gate P0 Fixes (peaceful-soaring-falcon)

**Plan**: `C:\Users\prora\.claude\plans\peaceful-soaring-falcon.md`
**Added**: 2026-04-25
**Status**: COMPLETE

### Summary

All P0 shipping gate blockers verified complete as of 2026-04-25.

| Task | Status | Files |
|------|--------|-------|
| P0-B: Baseline artifact | COMPLETE | `reports/baseline/gate-baseline-20260424.{txt,json}` |
| P0-C: CI gate | COMPLETE | `.github/workflows/release_gate.yml` |
| P0-D: Placeholder leak block | COMPLETE | `src/translation_engine/reconstructor/ast_renderer.py`, `src/translation_engine/engine.py`, `tests/unit/translation_engine/reconstructor/test_placeholder_leak.py` |
| P0-E: Frontmatter fallback log | COMPLETE | `src/translation_engine/parser/hugo_parser.py`, `tests/unit/translation_engine/parser/test_hugo_parser.py` |
| P0-F: Hugo build fixture | COMPLETE | `tests/fixtures/hugo_site/`, `.github/workflows/release_gate.yml`, `reports/audit/hugo_build_20260425.log` |
| P0-G: Bold normalization | COMPLETE (prior) | `src/translation_engine/reconstructor/ast_renderer.py` |
| P0-H: Dry-run manifest | COMPLETE (prior) | `src/cli.py:1384`, `tests/unit/test_cli_dry_run_manifest.py` |

### Next steps (P1 focus)

- WS-STALE-TEST-DEBT: Resolve remaining ~148 stale test failures (STE-01/02/04/05)
- P1-3: Enable SemanticSimilarityValidator in validation.yaml (normal mode)
- P1-4: Add ruff lint step to CI
- P1-5: Expand CI test coverage to >7% (currently ~7% of test files)
- GATE-09: Create more comprehensive test fixture content (5+ files per language, shortcodes, tables, code blocks)
