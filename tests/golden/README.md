# Golden Test Suite - CLI Backward Compatibility

**Task:** P0-02-GOLDEN-TESTS
**Phase:** Phase 0 (Baseline Safety)
**Author:** Agent C (Tests & Verification Specialist)
**Date:** 2026-01-14

---

## Purpose

This golden test suite establishes the backward compatibility baseline for the Hugo Translation System CLI. All 4 golden tests MUST pass identically across refactoring phases P1-P5 to ensure no breaking changes are introduced.

**Key Principle:** These tests capture the CURRENT behavior (bugs and all) as the regression baseline. If the current CLI has bugs, the tests will fail - and that's EXPECTED. The baseline captures the reality, not the ideal.

---

## Test Philosophy

### Subprocess-Based Testing
Unlike integration tests that invoke Python APIs directly, golden tests run the CLI as a subprocess:
```python
subprocess.run([sys.executable, "-m", "src.cli", "--site", "test"])
```

**Why?** This captures the complete CLI surface area:
- Exit codes
- stdout/stderr separation
- Argument parsing
- Signal handling
- Subprocess isolation

### Output Normalization
CLI output contains non-deterministic elements that vary between runs:
- Timestamps (2026-01-14T18:07:19.123456)
- Absolute paths (C:\Users\...\hugo-translator\...)
- PIDs (Process ID: 12345)
- Durations (Completed in 1.23s)
- Progress percentages (75%)

The test suite normalizes these to placeholders:
```
2026-01-14T18:07:19 → <TIMESTAMP>
C:\Users\...\hugo-translator\src → <PROJECT_ROOT>/src
PID: 12345 → PID: <PID>
1.23s → <DURATION>
75% → <PROGRESS>
```

This ensures tests are deterministic and don't fail due to timing or environment differences.

### Snapshot Comparison
First run creates baseline snapshots in `fixtures/expected_outputs/`:
```
golden_01_multilang_strict.json
golden_02_single_no_validation_dry_run.json
golden_03_resume_mode.json
golden_04_diagnose_lock.json
```

Each snapshot contains:
```json
{
  "exit_code": 0,
  "stdout": "...",
  "stderr": "...",
  "duration": 0.0,
  "files_written": []
}
```

Subsequent runs compare against these baselines. Any deviation triggers test failure.

---

## 4 Golden Commands

### Test 1: Multi-Language Strict Translation
```bash
translate-hugo --site golden-test --target-langs es,fr --strict --dry-run
```

**Validates:**
- Multi-language processing (es, fr)
- Strict validation mode (zero tolerance for errors)
- Dry-run behavior (no file writes)
- Exit code handling (0 or 1 depending on validation)

**Why This Matters:**
- Tests the most complex code path (multi-language + validation)
- Ensures strict mode doesn't regress
- Validates dry-run prevents file modifications

**Expected Baseline:** May fail with exit code 1 if validation errors exist in current implementation. That's OK - baseline captures current state.

---

### Test 2: Single Language No Validation
```bash
translate-hugo --site golden-test --target-langs de --no-validation --dry-run
```

**Validates:**
- Single language processing (de only)
- Validation disabled (--no-validation flag)
- Dry-run behavior (no file writes)
- Exit code 0 (should always succeed with validation off)

**Why This Matters:**
- Tests the simplest success path
- Ensures --no-validation flag works
- Validates single-language isolation

**Expected Baseline:** Should succeed with exit code 0.

---

### Test 3: Resume Mode
```bash
translate-hugo --site golden-test --target-langs pt --resume --dry-run
```

**Validates:**
- Resume mode flag acceptance
- Skip logic for completed files
- Single language processing (pt)
- Dry-run behavior

**Why This Matters:**
- Tests the --resume flag (critical for long-running translations)
- Ensures skip logic doesn't break
- Validates incremental translation workflow

**Expected Baseline:** Should succeed with exit code 0 (no files to skip on first run).

---

### Test 4: Diagnostic Command
```bash
translate-hugo diagnose-lock --site golden-test
```

**Validates:**
- Special command invocation (not main translate)
- Lock diagnostics output
- Exit code 0 (diagnostics displayed)

**Why This Matters:**
- Tests completely different code path (lock management)
- Ensures special commands remain backward compatible
- Validates diagnostic output format

**Expected Baseline:** Should display lock status and exit with code 0.

---

## Usage

### First Run (Baseline Capture)
```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run golden tests (creates baselines)
pytest tests/golden/test_cli_backward_compat.py -v

# Verify baselines created
ls tests/golden/fixtures/expected_outputs/
```

**Expected Output:**
```
tests/golden/test_cli_backward_compat.py::test_golden_01_multilang_strict SKIPPED (baseline created)
tests/golden/test_cli_backward_compat.py::test_golden_02_single_no_validation_dry_run SKIPPED (baseline created)
tests/golden/test_cli_backward_compat.py::test_golden_03_resume_mode SKIPPED (baseline created)
tests/golden/test_cli_backward_compat.py::test_golden_04_diagnose_lock SKIPPED (baseline created)
```

### Subsequent Runs (Regression Detection)
```bash
# Run golden tests (compares against baselines)
pytest tests/golden/test_cli_backward_compat.py -v
```

**Expected Output (No Regressions):**
```
tests/golden/test_cli_backward_compat.py::test_golden_01_multilang_strict PASSED
tests/golden/test_cli_backward_compat.py::test_golden_02_single_no_validation_dry_run PASSED
tests/golden/test_cli_backward_compat.py::test_golden_03_resume_mode PASSED
tests/golden/test_cli_backward_compat.py::test_golden_04_diagnose_lock PASSED
```

**Expected Output (Breaking Change Detected):**
```
tests/golden/test_cli_backward_compat.py::test_golden_01_multilang_strict FAILED
AssertionError: Exit code mismatch: expected 0, got 1
```

### Update Baselines (After Intentional Breaking Changes)
```bash
# Update snapshots after intentional CLI changes
pytest tests/golden/test_cli_backward_compat.py --update-snapshots

# Or manually delete snapshots and re-run
rm tests/golden/fixtures/expected_outputs/*.json
pytest tests/golden/test_cli_backward_compat.py -v
```

**Warning:** Only update baselines when you INTEND to change CLI behavior. Updating baselines to "fix" a failing test defeats the purpose of golden tests.

---

## Maintenance Guidelines

### When to Update Baselines
Update baselines ONLY when:
1. **Intentional CLI behavior change** (e.g., new flag, changed output format)
2. **Bug fix that changes output** (e.g., fixing incorrect exit code)
3. **Phase milestone** (e.g., P1 → P2 transition with documented breaking changes)

**DO NOT** update baselines to make tests pass after unintentional regressions.

### Adding New Golden Tests
When adding a new golden command:
1. Add test method to `TestCLIBackwardCompatibility` class
2. Follow naming convention: `test_golden_XX_description`
3. Document what the test validates (docstring)
4. Run test to create baseline
5. Update this README with new command description

### Debugging Failures
If a golden test fails:
1. **Review the diff** - pytest shows baseline vs current output
2. **Check for breaking changes** - was CLI behavior intentionally changed?
3. **Verify normalization** - are timestamps/paths properly normalized?
4. **Reproduce manually** - run the CLI command manually to verify
5. **Document decision** - if updating baseline, document WHY in commit message

---

## Test Fixtures

### Minimal Test Files
Golden tests use minimal fixtures for fast execution:

**minimal_en.md** (50 lines):
- Title + description frontmatter
- 3 content sections
- Simple English text

**minimal_multilang.md** (30 lines):
- Title + description frontmatter
- 2 content sections
- Designed for multi-language testing

**Why Minimal?** Golden tests run on every CI build. Large fixtures slow down the build. Minimal fixtures provide sufficient coverage while keeping tests fast (< 1 minute total).

### Site Profile
Golden tests use a dedicated site profile: `config/site_profiles/golden-test.yaml`

**Key Settings:**
- content_roots: `tests/golden/fixtures`
- target_langs: `[es, fr, de, pt]`
- batch_size: 8 (small for fast testing)
- semantic_tm: disabled (faster testing)
- caching: disabled (deterministic behavior)

---

## Integration with CI/CD

### GitHub Actions
```yaml
- name: Run Golden Tests
  run: |
    pytest tests/golden/test_cli_backward_compat.py -v
```

### Pre-commit Hook
```bash
#!/bin/bash
# Run golden tests before commit
pytest tests/golden/test_cli_backward_compat.py -q || exit 1
```

### Docker
```dockerfile
# Run golden tests during build
RUN pytest tests/golden/test_cli_backward_compat.py -v
```

---

## FAQ

### Q: Why do tests skip on first run?
**A:** First run creates baseline snapshots. Tests need baselines to compare against, so they skip with a message: "Baseline snapshot created. Run tests again to validate."

### Q: What if current CLI has bugs?
**A:** That's EXPECTED. Golden tests capture current behavior, bugs and all. The baseline establishes the regression point. When you fix the bug, you'll update the baseline intentionally.

### Q: Why subprocess instead of in-process?
**A:** Subprocess testing captures the complete CLI surface area: exit codes, stdout/stderr separation, argument parsing, signal handling. In-process testing misses these.

### Q: How do I know if normalization is working?
**A:** Run the test twice consecutively. If it passes both times, normalization is working. If it fails on second run due to timestamps/paths, normalization needs improvement.

### Q: Can I run a single golden test?
**A:** Yes:
```bash
pytest tests/golden/test_cli_backward_compat.py::TestCLIBackwardCompatibility::test_golden_01_multilang_strict -v
```

### Q: What's the difference between golden tests and integration tests?
**A:**
- **Golden Tests:** Capture CLI behavior as regression baseline (subprocess-based, snapshot comparison)
- **Integration Tests:** Test specific features in isolation (in-process, assertion-based)

Both are valuable. Golden tests detect ANY change (regression safety). Integration tests verify specific behaviors (feature validation).

---

## Related Documentation

- **CLI Compatibility Contract:** `reports/agents/agent_a_d/p0_01_cli_docs/run_20260114_175109/CLI_COMPATIBILITY_CONTRACT.md`
- **Task Specification:** `reports/TASK_BACKLOG.md` (Task P0-02)
- **System Spec:** `specs/autonomous_workers/SYSTEM_SPEC.md` (Testing section)

---

## Support

For questions or issues with golden tests:
1. Check this README
2. Review test implementation: `test_cli_backward_compat.py`
3. Check CI logs for failure details
4. Contact: Agent C (Tests & Verification Specialist)

---

**Last Updated:** 2026-01-14
**Version:** 1.0.0 (Baseline)
