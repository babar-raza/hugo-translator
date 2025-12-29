# Golden Repro Harness - Usage Guide

## Purpose

The golden repro harness validates that the lock contention fix (TC1/TC2) works correctly and prevents cascading 5-minute timeouts when translating multiple languages.

## Quick Start

### Unix/Linux/macOS
```bash
chmod +x tests/manual/golden_repro_lock_contention.sh
./tests/manual/golden_repro_lock_contention.sh
```

### Windows
```batch
tests\manual\golden_repro_lock_contention.bat
```

## What It Tests

1. **Environment Setup**: Verifies Python and project structure
2. **Clean State**: Removes old output and locks
3. **Pre-Translation Diagnostics**: Runs diagnose-lock to verify no lock
4. **Multi-Language Translation**: Translates 3 languages (ar, bg, cs)
5. **Performance**: Verifies completion in <60s (not 15+ minutes)
6. **Log Verification**: Checks for parent lock and child skip messages
7. **Output Completeness**: Verifies all languages produced output
8. **Lock Cleanup**: Verifies lock file removed after completion

## Expected Results

- **Duration**: <60 seconds (vs 900s with cascading timeouts)
- **Exit Code**: 0 (success)
- **Report**: Created in `reports/golden_repro/execution_<timestamp>.log`

## Interpreting Results

### Success
```
==========================================
GOLDEN REPRO HARNESS: SUCCESS
==========================================
✓ ALL CHECKS PASSED

Performance: 45s (95% improvement)
Parent lock: YES
Child skips: YES (3 occurrences)
Cascading timeouts: NO
```

### Failure - Cascading Timeout Detected
```
[FAIL] Translation timed out after 90s
This indicates cascading timeout bug is present
```

### Failure - Missing Parent Lock
```
[FAIL] Parent lock message not found in logs
```

## Regression Testing

Run this harness:
- Before production deployment (Gate 1 requirement)
- After any changes to lock implementation
- As part of CI/CD pipeline (recommended)
- When debugging lock-related issues

## Troubleshooting

### Test times out
- Check if old lock file exists: `python -m src.cli diagnose-lock --site test.golden.repro.net`
- Remove manually: `python -m src.cli unlock --site test.golden.repro.net --yes`

### Missing output directories
- Check translation_output log for errors
- Verify test corpus was created in `tests/fixtures/repro/source/`

### CI/CD Integration
```yaml
# Example GitHub Actions
- name: Run Golden Repro Harness
  run: |
    chmod +x tests/manual/golden_repro_lock_contention.sh
    ./tests/manual/golden_repro_lock_contention.sh
  timeout-minutes: 3
```
