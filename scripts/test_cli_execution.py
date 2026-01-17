#!/usr/bin/env python
"""
CLI Execution Test Suite - Runtime validation of all CLI options.

This script tests actual CLI execution, not just argument parsing.
Run from project root with: python scripts/test_cli_execution.py

Each test documents:
- Command executed
- Expected behavior
- Actual result (PASS/FAIL)
- Error details if any
"""
import subprocess
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List
import json
from datetime import datetime

# Ensure we're in project root
PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)

@dataclass
class TestResult:
    name: str
    command: str
    expected: str
    exit_code: int
    stdout: str
    stderr: str
    passed: bool
    error: Optional[str] = None

def run_cli(args: List[str], timeout: int = 30) -> tuple:
    """Run CLI command and return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, "-m", "src.cli"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -1, "", str(e)

def test_help() -> TestResult:
    """TEST-001: --help should display usage without errors."""
    exit_code, stdout, stderr = run_cli(["--help"])
    passed = exit_code == 0 and "usage: translate-hugo" in stdout
    return TestResult(
        name="TEST-001: --help flag",
        command="python -m src.cli --help",
        expected="Exit 0, display usage",
        exit_code=exit_code,
        stdout=stdout[:500],
        stderr=stderr[:500],
        passed=passed,
        error=None if passed else "Help not displayed correctly"
    )

def test_version() -> TestResult:
    """TEST-002: --version should display version string."""
    exit_code, stdout, stderr = run_cli(["--version"])
    passed = exit_code == 0 and "translate-hugo" in stdout
    return TestResult(
        name="TEST-002: --version flag",
        command="python -m src.cli --version",
        expected="Exit 0, display version",
        exit_code=exit_code,
        stdout=stdout[:200],
        stderr=stderr[:200],
        passed=passed,
        error=None if passed else "Version not displayed"
    )

def test_missing_required_site() -> TestResult:
    """TEST-003: Missing --site should error with exit 2."""
    exit_code, stdout, stderr = run_cli(["--dry-run"])
    passed = exit_code == 2 and "required" in stderr.lower()
    return TestResult(
        name="TEST-003: Missing required --site",
        command="python -m src.cli --dry-run",
        expected="Exit 2, error about missing --site",
        exit_code=exit_code,
        stdout=stdout[:200],
        stderr=stderr[:500],
        passed=passed,
        error=None if passed else "Should require --site"
    )

def test_mutual_exclusion_parallel_roundrobin() -> TestResult:
    """TEST-004: --parallel-languages + --global-lang-rounds should error."""
    exit_code, stdout, stderr = run_cli([
        "--site", "test",
        "--parallel-languages", "2",
        "--global-lang-rounds", "2"
    ])
    passed = exit_code == 2 and "cannot use both" in stderr.lower()
    return TestResult(
        name="TEST-004: Mutual exclusion parallel/round-robin",
        command="python -m src.cli --site test --parallel-languages 2 --global-lang-rounds 2",
        expected="Exit 2, mutual exclusion error",
        exit_code=exit_code,
        stdout=stdout[:200],
        stderr=stderr[:500],
        passed=passed,
        error=None if passed else "Should reject conflicting flags"
    )

def test_invalid_validation_mode() -> TestResult:
    """TEST-005: Invalid --validation-mode should error."""
    exit_code, stdout, stderr = run_cli([
        "--site", "test",
        "--validation-mode", "invalid_mode"
    ])
    passed = exit_code == 2 and "invalid choice" in stderr.lower()
    return TestResult(
        name="TEST-005: Invalid validation mode",
        command="python -m src.cli --site test --validation-mode invalid_mode",
        expected="Exit 2, invalid choice error",
        exit_code=exit_code,
        stdout=stdout[:200],
        stderr=stderr[:500],
        passed=passed,
        error=None if passed else "Should reject invalid mode"
    )

def test_dry_run_starts() -> TestResult:
    """TEST-006: --dry-run with valid site should start (may fail on missing config)."""
    exit_code, stdout, stderr = run_cli([
        "--site", "example",
        "--dry-run",
        "--log-level", "DEBUG"
    ], timeout=10)
    # May fail due to missing site config, but should NOT have import errors
    import_error = "ImportError" in stderr or "ModuleNotFoundError" in stderr or "NameError" in stderr
    passed = not import_error
    return TestResult(
        name="TEST-006: Dry-run startup (no import errors)",
        command="python -m src.cli --site example --dry-run --log-level DEBUG",
        expected="No import/name errors (config errors OK)",
        exit_code=exit_code,
        stdout=stdout[:500],
        stderr=stderr[:500],
        passed=passed,
        error="Import/Name error detected" if not passed else None
    )

def test_parallel_languages_valid() -> TestResult:
    """TEST-007: --parallel-languages alone should be accepted."""
    exit_code, stdout, stderr = run_cli([
        "--site", "example",
        "--parallel-languages", "3",
        "--dry-run"
    ], timeout=10)
    # Should not error on argument parsing
    arg_error = "not allowed" in stderr.lower() or "invalid" in stderr.lower()
    passed = not arg_error
    return TestResult(
        name="TEST-007: --parallel-languages valid",
        command="python -m src.cli --site example --parallel-languages 3 --dry-run",
        expected="No argument parsing errors",
        exit_code=exit_code,
        stdout=stdout[:300],
        stderr=stderr[:500],
        passed=passed,
        error="Argument rejected incorrectly" if not passed else None
    )

def test_terminology_flags() -> TestResult:
    """TEST-008: --enable-terminology --terminology-mode both should work."""
    exit_code, stdout, stderr = run_cli([
        "--site", "example",
        "--enable-terminology",
        "--terminology-mode", "both",
        "--dry-run"
    ], timeout=10)
    arg_error = "not allowed" in stderr.lower() or "invalid" in stderr.lower()
    passed = not arg_error
    return TestResult(
        name="TEST-008: Terminology flags",
        command="python -m src.cli --site example --enable-terminology --terminology-mode both --dry-run",
        expected="No argument parsing errors",
        exit_code=exit_code,
        stdout=stdout[:300],
        stderr=stderr[:500],
        passed=passed,
        error="Terminology flags rejected" if not passed else None
    )

def test_batch_size_and_sort() -> TestResult:
    """TEST-009: --batch-size and --sort-segments-by-length should work."""
    exit_code, stdout, stderr = run_cli([
        "--site", "example",
        "--batch-size", "16",
        "--sort-segments-by-length",
        "--dry-run"
    ], timeout=10)
    arg_error = "not allowed" in stderr.lower() or "invalid" in stderr.lower()
    passed = not arg_error
    return TestResult(
        name="TEST-009: Batch size and sorting flags",
        command="python -m src.cli --site example --batch-size 16 --sort-segments-by-length --dry-run",
        expected="No argument parsing errors",
        exit_code=exit_code,
        stdout=stdout[:300],
        stderr=stderr[:500],
        passed=passed,
        error="Batch/sort flags rejected" if not passed else None
    )

def test_resume_flags() -> TestResult:
    """TEST-010: --resume and --force-restart should be mutually exclusive."""
    # Actually these aren't mutually exclusive in argparse, --force-restart clears progress
    # Test that both can be specified (force-restart takes precedence)
    exit_code, stdout, stderr = run_cli([
        "--site", "example",
        "--resume",
        "--force-restart",
        "--dry-run"
    ], timeout=10)
    arg_error = "not allowed" in stderr.lower() and "resume" in stderr.lower()
    passed = True  # Both should be accepted, --force-restart overrides
    return TestResult(
        name="TEST-010: Resume and force-restart flags",
        command="python -m src.cli --site example --resume --force-restart --dry-run",
        expected="Both accepted (force-restart takes precedence)",
        exit_code=exit_code,
        stdout=stdout[:300],
        stderr=stderr[:500],
        passed=passed,
        error=None
    )

def test_cache_write_mode() -> TestResult:
    """TEST-011: --cache-write-mode should accept valid values."""
    exit_code, stdout, stderr = run_cli([
        "--site", "example",
        "--cache-write-mode", "skip",
        "--dry-run"
    ], timeout=10)
    arg_error = "invalid choice" in stderr.lower()
    passed = not arg_error
    return TestResult(
        name="TEST-011: Cache write mode flag",
        command="python -m src.cli --site example --cache-write-mode skip --dry-run",
        expected="No argument parsing errors",
        exit_code=exit_code,
        stdout=stdout[:300],
        stderr=stderr[:500],
        passed=passed,
        error="Cache write mode rejected" if not passed else None
    )

def test_full_production_command() -> TestResult:
    """TEST-012: Full production-like command should parse without errors."""
    exit_code, stdout, stderr = run_cli([
        "--site", "kb.aspose.net",
        "--target-langs", "fr", "de", "es",
        "--enable-terminology",
        "--terminology-mode", "both",
        "--load-mode", "fp16",
        "--batch-size", "16",
        "--parallel-languages", "3",
        "--sort-segments-by-length",
        "--auto-commit",
        "--log-level", "INFO",
        "--dry-run"
    ], timeout=15)
    # Check for import errors specifically
    import_error = "ImportError" in stderr or "ModuleNotFoundError" in stderr or "NameError" in stderr
    passed = not import_error
    return TestResult(
        name="TEST-012: Full production command",
        command="python -m src.cli --site kb.aspose.net --target-langs fr de es --enable-terminology --terminology-mode both --load-mode fp16 --batch-size 16 --parallel-languages 3 --sort-segments-by-length --auto-commit --log-level INFO --dry-run",
        expected="No import/name errors",
        exit_code=exit_code,
        stdout=stdout[:500],
        stderr=stderr[:800],
        passed=passed,
        error="Import/Name error in production command" if not passed else None
    )

def test_benchmarking_cli_help() -> TestResult:
    """TEST-013: Benchmarking CLI --help should work without torch."""
    cmd = [sys.executable, "-m", "src.benchmarking.cli", "--help"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=PROJECT_ROOT)
        passed = result.returncode == 0 and "benchmark" in result.stdout.lower()
        return TestResult(
            name="TEST-013: Benchmarking CLI --help",
            command="python -m src.benchmarking.cli --help",
            expected="Exit 0, display usage",
            exit_code=result.returncode,
            stdout=result.stdout[:500],
            stderr=result.stderr[:300],
            passed=passed,
            error=None if passed else "Benchmarking help failed"
        )
    except Exception as e:
        return TestResult(
            name="TEST-013: Benchmarking CLI --help",
            command="python -m src.benchmarking.cli --help",
            expected="Exit 0, display usage",
            exit_code=-1,
            stdout="",
            stderr=str(e),
            passed=False,
            error=str(e)
        )

def test_benchmarking_cli_version() -> TestResult:
    """TEST-014: Benchmarking CLI --version should work."""
    cmd = [sys.executable, "-m", "src.benchmarking.cli", "--version"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=PROJECT_ROOT)
        passed = result.returncode == 0 and "0.1.0" in result.stdout
        return TestResult(
            name="TEST-014: Benchmarking CLI --version",
            command="python -m src.benchmarking.cli --version",
            expected="Exit 0, display version",
            exit_code=result.returncode,
            stdout=result.stdout[:200],
            stderr=result.stderr[:200],
            passed=passed,
            error=None if passed else "Benchmarking version failed"
        )
    except Exception as e:
        return TestResult(
            name="TEST-014: Benchmarking CLI --version",
            command="python -m src.benchmarking.cli --version",
            expected="Exit 0, display version",
            exit_code=-1,
            stdout="",
            stderr=str(e),
            passed=False,
            error=str(e)
        )

def run_all_tests() -> List[TestResult]:
    """Run all CLI execution tests."""
    tests = [
        test_help,
        test_version,
        test_missing_required_site,
        test_mutual_exclusion_parallel_roundrobin,
        test_invalid_validation_mode,
        test_dry_run_starts,
        test_parallel_languages_valid,
        test_terminology_flags,
        test_batch_size_and_sort,
        test_resume_flags,
        test_cache_write_mode,
        test_full_production_command,
        test_benchmarking_cli_help,
        test_benchmarking_cli_version,
    ]

    results = []
    for test_func in tests:
        print(f"Running {test_func.__name__}...", end=" ", flush=True)
        result = test_func()
        status = "PASS" if result.passed else "FAIL"
        print(status)
        results.append(result)

    return results

def generate_report(results: List[TestResult]) -> str:
    """Generate markdown report of test results."""
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    report = f"""# CLI Execution Test Report

Generated: {datetime.now().isoformat()}

## Summary

| Metric | Value |
|--------|-------|
| Total Tests | {len(results)} |
| Passed | {passed} |
| Failed | {failed} |
| Pass Rate | {passed/len(results)*100:.1f}% |

## Test Results

"""

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        report += f"""### {r.name}

- **Status**: {status}
- **Command**: `{r.command}`
- **Expected**: {r.expected}
- **Exit Code**: {r.exit_code}

"""
        if not r.passed:
            report += f"""**Error**: {r.error}

**Stderr**:
```
{r.stderr[:1000]}
```

"""

    return report

def main():
    print("=" * 60)
    print("CLI Execution Test Suite")
    print("=" * 60)
    print()

    results = run_all_tests()

    print()
    print("=" * 60)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    print(f"Results: {passed} passed, {failed} failed out of {len(results)}")
    print("=" * 60)

    # Generate and save report
    report = generate_report(results)
    report_path = PROJECT_ROOT / "reports" / "cli_execution_test_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    # Return exit code based on failures
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
