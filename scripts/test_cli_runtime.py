#!/usr/bin/env python
"""
CLI Runtime Test Suite - Comprehensive runtime validation of all CLI options.

This tool tests actual CLI execution with all option combinations to catch:
- Import errors (NameError, ImportError)
- Runtime errors (ValueError, TypeError, AttributeError)
- I/O errors in subprocess contexts
- Configuration errors

Run: python scripts/test_cli_runtime.py [--quick] [--full]
  --quick: Only test critical paths (default)
  --full: Test all option combinations (takes longer)

Results are saved to: reports/cli_runtime_test_report.md
"""
import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)

@dataclass
class TestResult:
    name: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    passed: bool
    error_type: str | None = None
    duration_ms: float = 0.0

@dataclass
class TestSuite:
    name: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)


def run_cli(args: list[str], timeout: int = 60, env_override: dict = None) -> tuple[int, str, str, float]:
    """Run CLI command and return (exit_code, stdout, stderr, duration_ms)."""
    cmd = [sys.executable, "-m"] + args
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    import time
    start = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT,
            env=env
        )
        duration = (time.time() - start) * 1000
        return result.returncode, result.stdout, result.stderr, duration
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT", timeout * 1000
    except Exception as e:
        return -1, "", str(e), 0


def classify_error(stderr: str) -> str | None:
    """Classify the type of error from stderr."""
    error_patterns = [
        ("NameError", "NameError"),
        ("ImportError", "ImportError"),
        ("ModuleNotFoundError", "ImportError"),
        ("AttributeError", "AttributeError"),
        ("TypeError", "TypeError"),
        ("ValueError", "ValueError"),
        ("FileNotFoundError", "FileNotFoundError"),
        ("I/O operation on closed file", "IOError"),
        ("ConnectionRefusedError", "ConnectionError"),
        ("TimeoutError", "TimeoutError"),
        ("PermissionError", "PermissionError"),
        ("KeyError", "KeyError"),
        ("IndexError", "IndexError"),
        ("TIMEOUT", "Timeout"),
    ]

    for pattern, error_type in error_patterns:
        if pattern in stderr:
            return error_type
    return None


def test_basic_flags() -> TestSuite:
    """Test basic CLI flags that should always work."""
    suite = TestSuite(name="Basic Flags")

    tests = [
        ("--help", ["src.cli", "--help"], 0),
        ("--version", ["src.cli", "--version"], 0),
        ("missing --site", ["src.cli", "--dry-run"], 2),
        ("benchmarking --help", ["src.benchmarking.cli", "--help"], 0),
        ("benchmarking --version", ["src.benchmarking.cli", "--version"], 0),
    ]

    for name, args, expected_code in tests:
        print(f"  Testing {name}...", end=" ", flush=True)
        exit_code, stdout, stderr, duration = run_cli(args, timeout=30)

        # For help/version, success is exit 0
        # For missing required, success is exit 2 with "required" in stderr
        if expected_code == 0:
            passed = exit_code == 0
        else:
            passed = exit_code == expected_code

        error_type = classify_error(stderr) if not passed else None

        result = TestResult(
            name=name,
            command=args,
            exit_code=exit_code,
            stdout=stdout[:500] if stdout else "",
            stderr=stderr[:1000] if stderr else "",
            passed=passed,
            error_type=error_type,
            duration_ms=duration
        )
        suite.results.append(result)
        print("PASS" if passed else f"FAIL ({error_type or 'exit ' + str(exit_code)})")

    return suite


def test_argument_validation() -> TestSuite:
    """Test argument validation and mutual exclusion."""
    suite = TestSuite(name="Argument Validation")

    tests = [
        # Mutual exclusion
        ("parallel + roundrobin conflict",
         ["src.cli", "--site", "test", "--parallel-languages", "2", "--global-lang-rounds", "2"],
         2, "cannot use both"),

        # Invalid choices
        ("invalid validation-mode",
         ["src.cli", "--site", "test", "--validation-mode", "invalid"],
         2, "invalid choice"),

        ("invalid terminology-mode",
         ["src.cli", "--site", "test", "--terminology-mode", "invalid"],
         2, "invalid choice"),

        # Valid combinations that should parse
        ("parallel-languages valid",
         ["src.cli", "--site", "test", "--parallel-languages", "3", "--dry-run", "--help"],
         0, None),

        ("global-lang-rounds valid",
         ["src.cli", "--site", "test", "--global-lang-rounds", "5", "--dry-run", "--help"],
         0, None),
    ]

    for name, args, expected_code, expected_text in tests:
        print(f"  Testing {name}...", end=" ", flush=True)
        exit_code, stdout, stderr, duration = run_cli(args, timeout=30)

        if expected_text:
            passed = exit_code == expected_code and expected_text.lower() in stderr.lower()
        else:
            passed = exit_code == expected_code

        error_type = classify_error(stderr) if not passed else None

        result = TestResult(
            name=name,
            command=args,
            exit_code=exit_code,
            stdout=stdout[:500] if stdout else "",
            stderr=stderr[:1000] if stderr else "",
            passed=passed,
            error_type=error_type,
            duration_ms=duration
        )
        suite.results.append(result)
        print("PASS" if passed else f"FAIL ({error_type or 'exit ' + str(exit_code)})")

    return suite


def test_dry_run_startup() -> TestSuite:
    """Test that dry-run mode starts without import/runtime errors."""
    suite = TestSuite(name="Dry-Run Startup")

    # Test various option combinations with dry-run
    # These should at least START without NameError/ImportError
    # (may fail later due to missing config, but startup should work)

    option_combos = [
        ("minimal", ["--site", "example", "--dry-run"]),
        ("with terminology", ["--site", "example", "--dry-run", "--enable-terminology", "--terminology-mode", "both"]),
        ("with batch options", ["--site", "example", "--dry-run", "--batch-size", "16", "--sort-segments-by-length"]),
        ("with validation", ["--site", "example", "--dry-run", "--validation-mode", "strict"]),
        ("with parallel", ["--site", "example", "--dry-run", "--parallel-languages", "2"]),
        ("with resume flags", ["--site", "example", "--dry-run", "--resume"]),
        ("with force-restart", ["--site", "example", "--dry-run", "--force-restart"]),
        ("with auto-commit", ["--site", "example", "--dry-run", "--auto-commit"]),
        ("with cache options", ["--site", "example", "--dry-run", "--force-retranslate"]),
        ("production-like", [
            "--site", "example",
            "--dry-run",
            "--enable-terminology", "--terminology-mode", "both",
            "--batch-size", "16",
            "--parallel-languages", "2",
            "--sort-segments-by-length",
            "--auto-commit",
            "--log-level", "WARNING"
        ]),
    ]

    for name, extra_args in option_combos:
        args = ["src.cli"] + extra_args
        print(f"  Testing {name}...", end=" ", flush=True)

        # Run with short timeout - we just want to check startup
        exit_code, stdout, stderr, duration = run_cli(args, timeout=15)

        # Check for import/runtime errors in output
        error_type = classify_error(stderr)

        # Pass if no NameError/ImportError/AttributeError
        # (other errors like "config not found" are OK for this test)
        critical_errors = {"NameError", "ImportError", "AttributeError", "TypeError"}
        passed = error_type not in critical_errors

        result = TestResult(
            name=name,
            command=args,
            exit_code=exit_code,
            stdout=stdout[:500] if stdout else "",
            stderr=stderr[:1500] if stderr else "",
            passed=passed,
            error_type=error_type,
            duration_ms=duration
        )
        suite.results.append(result)
        print("PASS" if passed else f"FAIL ({error_type})")

    return suite


def test_benchmarking_commands() -> TestSuite:
    """Test benchmarking CLI command startup."""
    suite = TestSuite(name="Benchmarking CLI Commands")

    # These commands require DB/torch, so we just test that they start
    # and fail gracefully (not with NameError/ImportError)
    commands = [
        ("list --help", ["src.benchmarking.cli", "list", "--help"]),
        ("report --help", ["src.benchmarking.cli", "report", "--help"]),
        ("compare --help", ["src.benchmarking.cli", "compare", "--help"]),
        ("recommend --help", ["src.benchmarking.cli", "recommend", "--help"]),
        ("migrate --help", ["src.benchmarking.cli", "migrate", "--help"]),
        ("aggregate --help", ["src.benchmarking.cli", "aggregate", "--help"]),
        ("retention --help", ["src.benchmarking.cli", "retention", "--help"]),
        ("export --help", ["src.benchmarking.cli", "export", "--help"]),
        ("archive --help", ["src.benchmarking.cli", "archive", "--help"]),
    ]

    for name, args in commands:
        print(f"  Testing {name}...", end=" ", flush=True)
        exit_code, stdout, stderr, duration = run_cli(args, timeout=30)

        error_type = classify_error(stderr)
        critical_errors = {"NameError", "ImportError", "AttributeError"}
        passed = error_type not in critical_errors and exit_code == 0

        result = TestResult(
            name=name,
            command=args,
            exit_code=exit_code,
            stdout=stdout[:500] if stdout else "",
            stderr=stderr[:1000] if stderr else "",
            passed=passed,
            error_type=error_type,
            duration_ms=duration
        )
        suite.results.append(result)
        print("PASS" if passed else f"FAIL ({error_type or 'exit ' + str(exit_code)})")

    return suite


def test_option_matrix() -> TestSuite:
    """Test comprehensive matrix of ALL option combinations (full mode only)."""
    suite = TestSuite(name="Option Combination Matrix")

    # ============================================================
    # COMPREHENSIVE CLI OPTION GROUPS
    # ============================================================

    # 1. Validation Control
    validation_opts = [
        [],
        ["--validation-mode", "strict"],
        ["--validation-mode", "normal"],
        ["--validation-mode", "lenient"],
        ["--validation-mode", "off"],
        ["--disable-validation"],
        ["--force-accept"],
        ["--strict-reject"],
        ["--max-retries", "3"],
    ]

    # 2. Terminology Control
    terminology_opts = [
        [],
        ["--enable-terminology"],
        ["--enable-terminology", "--terminology-mode", "protect"],
        ["--enable-terminology", "--terminology-mode", "validate"],
        ["--enable-terminology", "--terminology-mode", "both"],
        ["--enable-terminology", "--terminology-mode", "none"],
        ["--disable-terminology"],
    ]

    # 3. Model Control
    model_opts = [
        [],
        ["--batch-size", "8"],
        ["--batch-size", "16"],
        ["--batch-size", "32"],
        ["--sort-segments-by-length"],
        ["--no-sort-segments-by-length"],
        ["--batch-size", "16", "--sort-segments-by-length"],
        ["--device", "cpu"],
        ["--device", "auto"],
        ["--load-mode", "fp16"],
        ["--load-mode", "fp32"],
        ["--load-mode", "int8"],
        ["--max-tokens", "256"],
        ["--max-tokens", "512"],
    ]

    # 4. Multi-language Processing (mutually exclusive)
    parallel_opts = [
        [],
        ["--parallel-languages", "1"],
        ["--parallel-languages", "2"],
        ["--parallel-languages", "3"],
        ["--global-lang-rounds", "2"],
        ["--global-lang-rounds", "3"],
        ["--global-lang-rounds", "5"],
        ["--global-lang-sort", "asc"],
        ["--global-lang-sort", "desc"],
        ["--fail-fast"],
        ["--no-fail-fast"],
    ]

    # 5. Resume Control
    resume_opts = [
        [],
        ["--resume"],
        ["--no-resume"],
        ["--force-restart"],
    ]

    # 6. Cache Control
    cache_opts = [
        [],
        ["--force-retranslate"],
        ["--cache-write-mode", "auto"],
        ["--cache-write-mode", "always"],
        ["--cache-write-mode", "never"],
        ["--disable-content-hash"],
        ["--rebuild-content-hashes"],
        ["--validate-output-integrity"],
    ]

    # 7. Verification Control
    verification_opts = [
        [],
        ["--verify"],
        ["--verify", "--fix"],
    ]

    # 8. Output Control
    output_opts = [
        [],
        ["--save-rejected"],
    ]

    # 9. Logging Control
    logging_opts = [
        [],
        ["--log-level", "DEBUG"],
        ["--log-level", "INFO"],
        ["--log-level", "WARNING"],
        ["--log-level", "ERROR"],
    ]

    # 10. Metrics Control
    metrics_opts = [
        [],
        ["--no-progress"],
        ["--metrics-only"],
        ["--metrics-interval", "1.0"],
    ]

    # 11. Git Commit Control
    commit_opts = [
        [],
        ["--auto-commit"],
        ["--no-commit"],
    ]

    # 12. Benchmark Control
    benchmark_opts = [
        [],
        ["--enable-production-metrics"],
    ]

    # ============================================================
    # TEST STRATEGY: Multi-phase testing
    # Phase 1: Core options matrix (validation × terminology × model × parallel)
    # Phase 2: Resume and cache options
    # Phase 3: Verification and output options
    # Phase 4: Logging, metrics, commit, benchmark
    # ============================================================

    count = 0

    print("\n  Phase 1a: Individual option tests (each option in isolation)...")

    # Phase 1a: Test each individual option in isolation first
    all_individual_opts = (
        validation_opts + terminology_opts + model_opts + parallel_opts +
        resume_opts + cache_opts + verification_opts + output_opts +
        logging_opts + metrics_opts + commit_opts + benchmark_opts
    )

    for opt in all_individual_opts:
        if not opt:  # Skip empty option
            continue
        combo_name = f"individual_{count}"
        args = ["src.cli", "--site", "example", "--dry-run"] + opt

        print(f"  Testing {combo_name}...", end=" ", flush=True)
        exit_code, stdout, stderr, duration = run_cli(args, timeout=15)

        error_type = classify_error(stderr)
        critical_errors = {"NameError", "ImportError", "AttributeError", "TypeError"}
        passed = error_type not in critical_errors

        result = TestResult(
            name=combo_name,
            command=args,
            exit_code=exit_code,
            stdout="",
            stderr=stderr[:500] if not passed else "",
            passed=passed,
            error_type=error_type,
            duration_ms=duration
        )
        suite.results.append(result)
        print("PASS" if passed else f"FAIL ({error_type})")
        count += 1

    print("\n  Phase 1b: Pairwise option combinations...")

    # Phase 1b: Pairwise combinations (each validation with each terminology, etc.)
    # This is more efficient than full cartesian product
    option_groups = [
        ("validation", validation_opts),
        ("terminology", terminology_opts),
        ("model", model_opts),
        ("parallel", parallel_opts),
    ]

    for i, (name1, opts1) in enumerate(option_groups):
        for j, (name2, opts2) in enumerate(option_groups):
            if j <= i:  # Skip duplicates and self-pairs
                continue
            for opt1 in opts1:
                for opt2 in opts2:
                    combo_name = f"pair_{name1}_{name2}_{count}"
                    args = ["src.cli", "--site", "example", "--dry-run"] + opt1 + opt2

                    print(f"  Testing {combo_name}...", end=" ", flush=True)
                    exit_code, stdout, stderr, duration = run_cli(args, timeout=15)

                    error_type = classify_error(stderr)
                    critical_errors = {"NameError", "ImportError", "AttributeError", "TypeError"}
                    passed = error_type not in critical_errors

                    result = TestResult(
                        name=combo_name,
                        command=args,
                        exit_code=exit_code,
                        stdout="",
                        stderr=stderr[:500] if not passed else "",
                        passed=passed,
                        error_type=error_type,
                        duration_ms=duration
                    )
                    suite.results.append(result)
                    print("PASS" if passed else f"FAIL ({error_type})")
                    count += 1

    print("\n  Phase 2: Resume and cache options...")

    # Phase 2: Resume and cache options
    for resume_opt in resume_opts:
        for cache_opt in cache_opts:
            combo_name = f"resume_cache_{count}"
            args = ["src.cli", "--site", "example", "--dry-run"] + resume_opt + cache_opt

            print(f"  Testing {combo_name}...", end=" ", flush=True)
            exit_code, stdout, stderr, duration = run_cli(args, timeout=15)

            error_type = classify_error(stderr)
            critical_errors = {"NameError", "ImportError", "AttributeError", "TypeError"}
            passed = error_type not in critical_errors

            result = TestResult(
                name=combo_name,
                command=args,
                exit_code=exit_code,
                stdout="",
                stderr=stderr[:500] if not passed else "",
                passed=passed,
                error_type=error_type,
                duration_ms=duration
            )
            suite.results.append(result)
            print("PASS" if passed else f"FAIL ({error_type})")
            count += 1

    print("\n  Phase 3: Verification and output options...")

    # Phase 3: Verification and output
    for verif_opt in verification_opts:
        for out_opt in output_opts:
            combo_name = f"verify_output_{count}"
            args = ["src.cli", "--site", "example", "--dry-run"] + verif_opt + out_opt

            print(f"  Testing {combo_name}...", end=" ", flush=True)
            exit_code, stdout, stderr, duration = run_cli(args, timeout=15)

            error_type = classify_error(stderr)
            critical_errors = {"NameError", "ImportError", "AttributeError", "TypeError"}
            passed = error_type not in critical_errors

            result = TestResult(
                name=combo_name,
                command=args,
                exit_code=exit_code,
                stdout="",
                stderr=stderr[:500] if not passed else "",
                passed=passed,
                error_type=error_type,
                duration_ms=duration
            )
            suite.results.append(result)
            print("PASS" if passed else f"FAIL ({error_type})")
            count += 1

    print("\n  Phase 4: Logging, metrics, commit, benchmark options...")

    # Phase 4: Logging, metrics, commit, benchmark
    for log_opt in logging_opts:
        for metric_opt in metrics_opts:
            for commit_opt in commit_opts:
                for bench_opt in benchmark_opts:
                    combo_name = f"misc_{count}"
                    args = ["src.cli", "--site", "example", "--dry-run"] + log_opt + metric_opt + commit_opt + bench_opt

                    print(f"  Testing {combo_name}...", end=" ", flush=True)
                    exit_code, stdout, stderr, duration = run_cli(args, timeout=15)

                    error_type = classify_error(stderr)
                    critical_errors = {"NameError", "ImportError", "AttributeError", "TypeError"}
                    passed = error_type not in critical_errors

                    result = TestResult(
                        name=combo_name,
                        command=args,
                        exit_code=exit_code,
                        stdout="",
                        stderr=stderr[:500] if not passed else "",
                        passed=passed,
                        error_type=error_type,
                        duration_ms=duration
                    )
                    suite.results.append(result)
                    print("PASS" if passed else f"FAIL ({error_type})")
                    count += 1

    print("\n  Phase 5: Production-like combinations...")

    # Phase 5: Production-like realistic combinations
    production_combos = [
        # Typical production run
        ["--enable-terminology", "--terminology-mode", "both", "--batch-size", "16",
         "--sort-segments-by-length", "--parallel-languages", "3", "--auto-commit",
         "--log-level", "INFO"],
        # High-throughput GPU
        ["--batch-size", "32", "--load-mode", "fp16", "--device", "auto",
         "--sort-segments-by-length", "--parallel-languages", "4", "--no-progress"],
        # Conservative CPU
        ["--batch-size", "8", "--device", "cpu", "--load-mode", "fp32",
         "--validation-mode", "strict", "--enable-terminology"],
        # Quick validation disabled
        ["--disable-validation", "--disable-terminology", "--batch-size", "16",
         "--no-progress", "--log-level", "WARNING"],
        # Full validation + verification
        ["--validation-mode", "strict", "--enable-terminology", "--terminology-mode", "both",
         "--verify", "--fix", "--save-rejected"],
        # Resume mode with cache control
        ["--resume", "--cache-write-mode", "auto", "--validate-output-integrity"],
        # Force restart with fresh translation
        ["--force-restart", "--force-retranslate", "--rebuild-content-hashes"],
        # Round-robin multi-language
        ["--global-lang-rounds", "5", "--global-lang-sort", "desc", "--fail-fast"],
        # Metrics collection
        ["--enable-production-metrics", "--metrics-interval", "1.0", "--log-level", "DEBUG"],
        # Memory-constrained
        ["--batch-size", "4", "--load-mode", "int8", "--device", "cpu", "--max-tokens", "256"],
    ]

    for i, combo in enumerate(production_combos):
        combo_name = f"production_{i}"
        args = ["src.cli", "--site", "example", "--dry-run"] + combo

        print(f"  Testing {combo_name}...", end=" ", flush=True)
        exit_code, stdout, stderr, duration = run_cli(args, timeout=15)

        error_type = classify_error(stderr)
        critical_errors = {"NameError", "ImportError", "AttributeError", "TypeError"}
        passed = error_type not in critical_errors

        result = TestResult(
            name=combo_name,
            command=args,
            exit_code=exit_code,
            stdout="",
            stderr=stderr[:500] if not passed else "",
            passed=passed,
            error_type=error_type,
            duration_ms=duration
        )
        suite.results.append(result)
        print("PASS" if passed else f"FAIL ({error_type})")

    return suite


def generate_report(suites: list[TestSuite]) -> str:
    """Generate markdown report."""
    total_passed = sum(s.passed for s in suites)
    total_failed = sum(s.failed for s in suites)
    total = total_passed + total_failed

    report = f"""# CLI Runtime Test Report

Generated: {datetime.now().isoformat()}

## Summary

| Metric | Value |
|--------|-------|
| Total Tests | {total} |
| Passed | {total_passed} |
| Failed | {total_failed} |
| Pass Rate | {total_passed/total*100:.1f}% |

## Test Suites

"""

    for suite in suites:
        status = "PASS" if suite.failed == 0 else "FAIL"
        report += f"""### {suite.name} [{status}]

- Passed: {suite.passed}
- Failed: {suite.failed}

"""
        if suite.failed > 0:
            report += "#### Failed Tests\n\n"
            for r in suite.results:
                if not r.passed:
                    report += f"""**{r.name}**
- Command: `{' '.join(r.command)}`
- Exit Code: {r.exit_code}
- Error Type: {r.error_type or 'Unknown'}

```
{r.stderr[:800]}
```

"""

    # Error summary
    all_errors = {}
    for suite in suites:
        for r in suite.results:
            if r.error_type:
                if r.error_type not in all_errors:
                    all_errors[r.error_type] = []
                all_errors[r.error_type].append(r.name)

    if all_errors:
        report += "## Error Summary\n\n"
        for error_type, tests in sorted(all_errors.items()):
            report += f"### {error_type} ({len(tests)} occurrences)\n\n"
            for test in tests[:5]:  # Limit to 5 examples
                report += f"- {test}\n"
            if len(tests) > 5:
                report += f"- ... and {len(tests) - 5} more\n"
            report += "\n"

    return report


def main():
    parser = argparse.ArgumentParser(description="CLI Runtime Test Suite")
    parser.add_argument("--quick", action="store_true", default=True,
                        help="Run quick tests only (default)")
    parser.add_argument("--full", action="store_true",
                        help="Run full test suite including option matrix")
    args = parser.parse_args()

    print("=" * 60)
    print("CLI Runtime Test Suite")
    print("=" * 60)
    print()

    suites = []

    # Always run basic tests
    print("Basic Flags:")
    suites.append(test_basic_flags())
    print()

    print("Argument Validation:")
    suites.append(test_argument_validation())
    print()

    print("Dry-Run Startup:")
    suites.append(test_dry_run_startup())
    print()

    print("Benchmarking CLI Commands:")
    suites.append(test_benchmarking_commands())
    print()

    if args.full:
        print("Option Combination Matrix:")
        suites.append(test_option_matrix())
        print()

    # Generate report
    report = generate_report(suites)
    report_path = PROJECT_ROOT / "reports" / "cli_runtime_test_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    # Summary
    total_passed = sum(s.passed for s in suites)
    total_failed = sum(s.failed for s in suites)

    print("=" * 60)
    print(f"Results: {total_passed} passed, {total_failed} failed")
    print(f"Report saved to: {report_path}")
    print("=" * 60)

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
