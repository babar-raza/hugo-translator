# CLI Testing Specification

## Overview

This document specifies the CLI testing strategy to ensure all CLI commands work correctly at runtime. It addresses the gap between static type checking and actual execution testing.

## Problem Statement

The CLI uses lazy imports to allow `--help` to work without heavy ML dependencies. However, this pattern can cause NameError at runtime if imports are not properly loaded when commands execute.

**Root Cause**: Functions define imports in `_import_heavy_deps()` but forget to call it or extract needed classes.

## Testing Strategy

### 1. Static Analysis (Pre-commit)

Run `scripts/analyze_cli_imports.py` to detect undefined names before runtime.

```bash
# Analyze main CLI
python scripts/analyze_cli_imports.py src/cli.py

# Analyze benchmarking CLI
python scripts/analyze_cli_imports.py src/benchmarking/cli.py
```

**Exit codes:**
- 0: No undefined names found
- 1: Undefined names detected (fix required)

### 2. Execution Smoke Tests

Run `scripts/test_cli_execution.py` to verify actual command execution.

```bash
python scripts/test_cli_execution.py
```

This tests:
- `--help` flag
- `--version` flag
- Required argument validation
- Mutual exclusion validation
- Basic command startup (dry-run mode)
- Production-like command combinations

### 3. Runtime Tests (Comprehensive)

Run `scripts/test_cli_runtime.py` for comprehensive runtime validation.

```bash
# Quick tests (default) - critical paths only
python scripts/test_cli_runtime.py --quick

# Full tests - all option combinations
python scripts/test_cli_runtime.py --full
```

This tests:
- Basic flags (--help, --version)
- Argument validation and mutual exclusion
- Dry-run startup with various option combinations
- All benchmarking CLI commands
- Option combination matrix (full mode)

Error classification:
- NameError, ImportError, AttributeError - Critical (test fails)
- TypeError, ValueError - Runtime errors (test fails)
- FileNotFoundError, ConfigError - Configuration issues (test passes)
- IOError, ConnectionError - Environment issues (logged)

### 4. CI Integration

CLI tests run automatically via `.github/workflows/cli_tests.yml`:

**Triggers:**
- Push to main (changes to CLI files)
- Pull requests to main
- Manual workflow dispatch

**Jobs:**
1. `cli-static-analysis` - Runs import analysis on both CLIs
2. `cli-execution-tests` - Runs smoke tests
3. `cli-runtime-tests` - Runs quick runtime tests
4. `cli-full-matrix` - Runs full option matrix (manual trigger only)

**Reports:**
- Uploaded as GitHub Actions artifacts
- Available in `reports/` directory locally

## CLI Options Matrix

### Main CLI (`src/cli.py`)

| Option | Type | Tested |
|--------|------|--------|
| `--site` | Required | Yes |
| `--input` | Optional | Yes |
| `--target-langs` | Optional | Yes |
| `--version` | Flag | Yes |
| `--help` | Flag | Yes |
| `--dry-run` | Flag | Yes |
| `--parallel-languages` | Optional | Yes |
| `--global-lang-rounds` | Optional | Yes |
| `--enable-terminology` | Flag | Yes |
| `--terminology-mode` | Choice | Yes |
| `--batch-size` | Optional | Yes |
| `--sort-segments-by-length` | Flag | Yes |
| `--validation-mode` | Choice | Yes |
| `--auto-commit` | Flag | Yes |
| `--resume` | Flag | Yes |
| `--force-restart` | Flag | Yes |

### Benchmarking CLI (`src/benchmarking/cli.py`)

| Command | Tested |
|---------|--------|
| `--help` | Yes |
| `--version` | Yes |
| `run` | No (requires torch) |
| `list` | No (requires DB) |
| `report` | No (requires DB) |
| `compare` | No (requires DB) |
| `recommend` | No (requires torch) |
| `migrate` | No (requires DB) |
| `aggregate` | No (requires DB) |
| `retention` | No (requires DB) |
| `export` | No (requires DB) |
| `archive` | No (requires DB) |

## Mutual Exclusion Rules

| Options | Rule |
|---------|------|
| `--parallel-languages` + `--global-lang-rounds` | Cannot use together (exit 2) |

## Import Pattern

All command functions MUST follow this pattern:

```python
def cmd_example(args: argparse.Namespace) -> int:
    """Command description."""
    # Load heavy dependencies AT START of function
    deps = _import_heavy_deps()
    ClassName = deps['ClassName']

    # Now use ClassName...
    obj = ClassName(args.param)
```

Or for src/cli.py (direct imports in try/except):

```python
def translate_site(args: argparse.Namespace) -> int:
    # Import all dependencies needed for translation
    try:
        from .module import ClassName
    except ImportError:
        from module import ClassName

    # Now use ClassName...
```

## Maintenance

When adding new CLI options:

1. Add the argument to `create_parser()`
2. If using new classes, add imports to the function
3. Run static analysis: `python scripts/analyze_cli_imports.py src/cli.py`
4. Run execution tests: `python scripts/test_cli_execution.py`
5. Update this spec with new options

## Test Reports

Reports are generated at:
- `reports/cli_execution_test_report.md` - Execution smoke test results
- `reports/cli_runtime_test_report.md` - Comprehensive runtime test results

## Quick Reference

```bash
# Run all CLI verification (quick)
python scripts/analyze_cli_imports.py src/cli.py && \
python scripts/analyze_cli_imports.py src/benchmarking/cli.py && \
python scripts/test_cli_execution.py && \
python scripts/test_cli_runtime.py --quick

# Run full verification (includes option matrix)
python scripts/analyze_cli_imports.py src/cli.py && \
python scripts/analyze_cli_imports.py src/benchmarking/cli.py && \
python scripts/test_cli_execution.py && \
python scripts/test_cli_runtime.py --full
```

## Windows Quick Reference

```powershell
# Quick verification
python scripts\analyze_cli_imports.py src\cli.py; `
python scripts\analyze_cli_imports.py src\benchmarking\cli.py; `
python scripts\test_cli_runtime.py --quick

# Full verification
python scripts\test_cli_runtime.py --full
```
