# CLI Testing System Specification

A reusable system for comprehensive CLI testing that catches import errors, runtime errors, and validates all option combinations before they reach users.

## Problem Statement

CLIs that use **lazy imports** (to speed up `--help`) often have hidden `NameError` or `ImportError` bugs that only surface at runtime when specific code paths execute. Static type checkers (mypy, pyright) don't catch these because the imports exist in the codebase - they're just not loaded in the right scope.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLI Testing System                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │  Static Analysis │  │ Execution Smoke  │  │   Runtime    │  │
│  │   (AST-based)    │  │     Tests        │  │    Matrix    │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘  │
│           │                     │                    │          │
│           ▼                     ▼                    ▼          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    CI Integration                         │  │
│  │            (.github/workflows/cli_tests.yml)              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Component 1: Static Import Analyzer

**File:** `scripts/analyze_cli_imports.py`

### Purpose
Detects undefined names in Python functions BEFORE runtime using AST analysis.

### How It Works

1. Parse Python source into AST
2. Track all names defined at module level (imports, classes, functions, assignments)
3. For each function, track:
   - Parameters
   - Local assignments
   - Local imports (inside function body)
   - Comprehension variables
   - Nested function names
   - Closure names (from parent scopes)
4. Find all `Name` nodes with `Load` context (name usage)
5. Report names used but not defined in any accessible scope

### Key Classes

```python
@dataclass
class FunctionScope:
    name: str
    lineno: int
    qualified_name: str  # e.g., "outer_func.inner_func"
    parameters: Set[str]
    local_assignments: Set[str]
    local_imports: Set[str]
    names_used: Dict[str, int]  # name -> first line used
    comprehension_vars: Set[str]
    nested_function_names: Set[str]
    parent_scope: Optional['FunctionScope']  # For closure support

class ImportAnalyzer(ast.NodeVisitor):
    # Visits all nodes, tracks scope, finds undefined names
```

### Scope Rules

Names are available in a function if they come from:
1. Module-level imports/definitions
2. Function parameters
3. Local assignments (including `for` loop targets, `with` aliases, `except` names)
4. Local imports (inside the function)
5. Comprehension variables (list/dict/set comp, generator)
6. Nested function names
7. Closure scope (all of above from parent functions)
8. Python builtins
9. Common typing names (`Dict`, `List`, `Optional`, etc.)

### TYPE_CHECKING Handling

Names imported inside `if TYPE_CHECKING:` blocks are tracked separately and NOT counted as available at runtime (they're only for type hints).

### Usage

```bash
python scripts/analyze_cli_imports.py src/cli.py
# Exit 0 = no undefined names
# Exit 1 = undefined names found (prints details)
```

### Output Format

```
Analyzing src/cli.py for undefined names...
======================================================================

Found 3 potentially undefined names:

  ConfigService
    Line 245: translate_site
      config = ConfigService.load(args.site)

  ProgressTracker
    Line 312: translate_site
      tracker = ProgressTracker(total_files)

======================================================================
TOTAL: 3 undefined names in 3 locations

To fix: Add imports at function level or module level
```

---

## Component 2: Execution Smoke Tests

**File:** `scripts/test_cli_execution.py`

### Purpose
Verify that CLI commands actually execute without crashing. Tests argument parsing, mutual exclusion, and basic startup.

### Test Categories

| Category | What It Tests |
|----------|---------------|
| Help/Version | `--help` and `--version` display correctly |
| Required Args | Missing required arguments return exit code 2 |
| Mutual Exclusion | Conflicting options are rejected |
| Invalid Choices | Invalid enum values are rejected |
| Dry-Run Startup | Commands start without import errors |
| Production Commands | Real-world option combinations work |

### Key Functions

```python
def run_cli(args: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """Run CLI as subprocess, return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, "-m", "src.cli"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr

@dataclass
class TestResult:
    name: str
    command: str
    expected: str
    exit_code: int
    stdout: str
    stderr: str
    passed: bool
    error: Optional[str]
```

### Test Design Pattern

```python
def test_mutual_exclusion() -> TestResult:
    """TEST-004: Conflicting options should error."""
    exit_code, stdout, stderr = run_cli([
        "--site", "test",
        "--parallel-languages", "2",
        "--global-lang-rounds", "2"  # Conflicts!
    ])
    passed = exit_code == 2 and "cannot use both" in stderr.lower()
    return TestResult(
        name="TEST-004: Mutual exclusion",
        command="...",
        expected="Exit 2, mutual exclusion error",
        exit_code=exit_code,
        stdout=stdout[:500],
        stderr=stderr[:500],
        passed=passed,
        error=None if passed else "Should reject conflicting flags"
    )
```

---

## Component 3: Comprehensive Runtime Matrix

**File:** `scripts/test_cli_runtime.py`

### Purpose
Test ALL CLI option combinations to catch runtime errors that only occur with specific flag combinations.

### Test Strategy: Multi-Phase

Rather than testing the full cartesian product (which can be millions of combinations), use a smart multi-phase approach:

#### Phase 1a: Individual Options (~60 tests)
Test each option in isolation to catch basic import/runtime errors.

```python
all_individual_opts = (
    validation_opts + terminology_opts + model_opts + ...
)
for opt in all_individual_opts:
    if not opt:  # Skip empty
        continue
    run_test(["--site", "example", "--dry-run"] + opt)
```

#### Phase 1b: Pairwise Combinations (~600 tests)
Test each pair of option groups together. This catches most interaction bugs.

```python
option_groups = [
    ("validation", validation_opts),
    ("terminology", terminology_opts),
    ("model", model_opts),
    ("parallel", parallel_opts),
]

for i, (name1, opts1) in enumerate(option_groups):
    for j, (name2, opts2) in enumerate(option_groups):
        if j <= i:  # Skip duplicates
            continue
        for opt1 in opts1:
            for opt2 in opts2:
                run_test(base_args + opt1 + opt2)
```

#### Phase 2-4: Secondary Option Groups (~160 tests)
Test remaining option groups in smaller matrices:
- Resume × Cache options
- Verification × Output options
- Logging × Metrics × Commit × Benchmark

#### Phase 5: Production Combinations (~10 tests)
Test realistic production command lines:

```python
production_combos = [
    # Typical production run
    ["--enable-terminology", "--terminology-mode", "both",
     "--batch-size", "16", "--parallel-languages", "3", "--auto-commit"],
    # High-throughput GPU
    ["--batch-size", "32", "--load-mode", "fp16", "--device", "auto"],
    # Memory-constrained
    ["--batch-size", "4", "--load-mode", "int8", "--device", "cpu"],
    # ... more realistic scenarios
]
```

### Error Classification

```python
def classify_error(stderr: str) -> Optional[str]:
    """Classify error type from stderr output."""
    error_patterns = [
        ("NameError", "NameError"),        # Critical - missing import
        ("ImportError", "ImportError"),    # Critical - bad import
        ("ModuleNotFoundError", "ImportError"),
        ("AttributeError", "AttributeError"),  # Critical - wrong attribute
        ("TypeError", "TypeError"),        # Critical - wrong types
        ("ValueError", "ValueError"),      # Runtime error
        ("FileNotFoundError", "FileNotFoundError"),  # Config issue (OK)
        ("I/O operation on closed file", "IOError"),
        ("TIMEOUT", "Timeout"),
    ]

    for pattern, error_type in error_patterns:
        if pattern in stderr:
            return error_type
    return None
```

### Pass/Fail Criteria

```python
critical_errors = {"NameError", "ImportError", "AttributeError", "TypeError"}
passed = classify_error(stderr) not in critical_errors
```

Tests PASS if no critical errors, even if:
- Config file not found (expected in dry-run)
- Connection errors (no server running)
- File permission errors (environment issue)

### CLI Modes

```bash
# Quick mode (default): 29 tests, ~1 minute
python scripts/test_cli_runtime.py --quick

# Full mode: 845+ tests, ~45 minutes
python scripts/test_cli_runtime.py --full
```

---

## Component 4: CI Integration

**File:** `.github/workflows/cli_tests.yml`

### Workflow Structure

```yaml
name: CLI Tests

on:
  push:
    branches: [main]
    paths:
      - 'src/cli.py'
      - 'src/*/cli.py'
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  cli-static-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: python scripts/analyze_cli_imports.py src/cli.py

  cli-execution-tests:
    needs: cli-static-analysis
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: pip install -r requirements.txt
      - run: python scripts/test_cli_execution.py

  cli-runtime-tests:
    needs: cli-execution-tests
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/test_cli_runtime.py --quick
      - uses: actions/upload-artifact@v3
        with:
          name: cli-runtime-report
          path: reports/cli_runtime_test_report.md

  cli-full-matrix:
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/test_cli_runtime.py --full
```

### Job Dependencies

```
cli-static-analysis
        │
        ▼
cli-execution-tests
        │
        ▼
cli-runtime-tests (quick)
        │
        ▼ (manual trigger only)
cli-full-matrix
```

---

## Option Definition Pattern

### How to Define Option Groups

```python
# Pattern: List of lists, each inner list is one option variant
validation_opts = [
    [],                                    # No option (baseline)
    ["--validation-mode", "strict"],       # Single option
    ["--validation-mode", "lenient"],      # Another value
    ["--disable-validation"],              # Flag
    ["--max-retries", "3"],                # Option with value
]

# Options that work together
terminology_opts = [
    [],
    ["--enable-terminology"],
    ["--enable-terminology", "--terminology-mode", "both"],  # Combined
    ["--disable-terminology"],
]
```

### Mutually Exclusive Options

Handle in the option list (don't combine incompatible options):

```python
parallel_opts = [
    [],
    ["--parallel-languages", "2"],    # Either this...
    ["--global-lang-rounds", "3"],    # ...or this (not both)
]
# Don't include: ["--parallel-languages", "2", "--global-lang-rounds", "3"]
```

---

## Report Generation

### Report Format

```markdown
# CLI Runtime Test Report

Generated: 2024-01-15T10:30:00

## Summary

| Metric | Value |
|--------|-------|
| Total Tests | 845 |
| Passed | 845 |
| Failed | 0 |
| Pass Rate | 100.0% |

## Test Suites

### Basic Flags [PASS]
- Passed: 5
- Failed: 0

### Option Combination Matrix [PASS]
- Passed: 677
- Failed: 0

## Error Summary
(empty if all pass)
```

---

## Replication Checklist

To replicate this system in another project:

### 1. Create Static Analyzer
```bash
cp scripts/analyze_cli_imports.py your-project/scripts/
```

Customize:
- Add project-specific global names to `TYPING_NAMES`
- Adjust for project's import patterns

### 2. Create Execution Tests
```bash
cp scripts/test_cli_execution.py your-project/scripts/
```

Customize:
- Change `src.cli` to your CLI module
- Update test cases for your CLI's flags
- Update expected output strings

### 3. Create Runtime Matrix
```bash
cp scripts/test_cli_runtime.py your-project/scripts/
```

Customize:
- Define your option groups in `test_option_matrix()`
- Update production_combos for realistic scenarios
- Adjust timeout values for your CLI's startup time

### 4. Create CI Workflow
```bash
cp .github/workflows/cli_tests.yml your-project/.github/workflows/
```

Customize:
- Update paths for trigger conditions
- Adjust runner type (ubuntu-latest, self-hosted, etc.)
- Add dependencies installation step

### 5. Create Spec Document
```bash
cp specs/cli-testing.md your-project/specs/
```

Customize:
- Update CLI options matrix table
- Update quick reference commands

---

## Maintenance

### When Adding New CLI Options

1. Add to appropriate option group in `test_cli_runtime.py`
2. Run static analysis: `python scripts/analyze_cli_imports.py src/cli.py`
3. Run quick tests: `python scripts/test_cli_runtime.py --quick`
4. Update spec documentation

### When Changing Import Patterns

1. Ensure all command functions call `_import_heavy_deps()` or have local imports
2. Run static analysis to verify
3. Run full matrix to catch edge cases

---

## Performance Considerations

| Test Type | Tests | Time | When to Run |
|-----------|-------|------|-------------|
| Static Analysis | 2 files | ~5s | Every commit |
| Execution Smoke | ~15 | ~30s | Every commit |
| Runtime Quick | ~29 | ~1m | Every PR |
| Runtime Full | ~845 | ~45m | Manual/Weekly |

---

## Summary

This CLI testing system provides:

1. **Static Analysis** - Catches undefined names before runtime
2. **Execution Tests** - Validates argument parsing and basic startup
3. **Runtime Matrix** - Tests all option combinations for runtime errors
4. **CI Integration** - Automates testing on every change

The key insight is that **pairwise testing** catches most bugs without the exponential cost of full cartesian product testing.
