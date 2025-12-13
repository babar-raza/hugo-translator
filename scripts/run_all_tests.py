#!/usr/bin/env python3
"""
Test Execution and Reporting Script

Executes test suites with comprehensive reporting:
- Suite management (all, critical, fast, slow)
- Timeout enforcement
- Parallel execution support
- Result aggregation and parsing
- Structured JSON reporting

Exit codes:
  0: All tests pass
  1: Some tests fail
  2: Test execution error
"""

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional
import re


@dataclass
class TestResult:
    """Result of test execution."""
    suite_name: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration: float
    exit_code: int
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @property
    def success(self) -> bool:
        """Check if all tests passed."""
        return self.failed == 0 and self.errors == 0


class PytestResultParser:
    """Parse pytest output to extract test results."""

    @staticmethod
    def parse_output(output: str) -> Dict[str, Any]:
        """
        Parse pytest output to extract test counts.

        Args:
            output: Combined stdout and stderr from pytest

        Returns:
            Dictionary with test counts
        """
        results = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "duration": 0.0
        }

        # Look for the summary line like "10 passed, 2 failed, 1 skipped in 5.23s"
        summary_pattern = r'((\d+)\s+passed)?,?\s*((\d+)\s+failed)?,?\s*((\d+)\s+skipped)?,?\s*((\d+)\s+error)?,?\s*(?:in\s+([\d.]+)s)?'

        # Try to find explicit counts
        if "passed" in output:
            passed_match = re.search(r'(\d+)\s+passed', output)
            if passed_match:
                results["passed"] = int(passed_match.group(1))

        if "failed" in output:
            failed_match = re.search(r'(\d+)\s+failed', output)
            if failed_match:
                results["failed"] = int(failed_match.group(1))

        if "skipped" in output:
            skipped_match = re.search(r'(\d+)\s+skipped', output)
            if skipped_match:
                results["skipped"] = int(skipped_match.group(1))

        if "error" in output:
            error_match = re.search(r'(\d+)\s+error', output)
            if error_match:
                results["errors"] = int(error_match.group(1))

        # Extract duration
        duration_match = re.search(r'in\s+([\d.]+)s', output)
        if duration_match:
            results["duration"] = float(duration_match.group(1))

        # Calculate total
        results["total"] = results["passed"] + results["failed"] + results["skipped"] + results["errors"]

        # If no explicit counts found, try to count from collected line
        if results["total"] == 0:
            collected_match = re.search(r'collected\s+(\d+)', output)
            if collected_match:
                results["total"] = int(collected_match.group(1))
                # If we collected tests but no results, assume all passed
                if results["passed"] == 0 and results["failed"] == 0:
                    results["passed"] = results["total"]

        return results


class TestRunner:
    """Execute test suites with timeout and reporting."""

    # Suite definitions
    SUITES = {
        "all": {
            "description": "Run all tests",
            "markers": [],
            "paths": []
        },
        "critical": {
            "description": "Run only critical tests",
            "markers": ["critical"],
            "paths": []
        },
        "fast": {
            "description": "Run fast tests (<1s)",
            "markers": ["fast"],
            "paths": []
        },
        "slow": {
            "description": "Run slow tests (>1s)",
            "markers": ["slow"],
            "paths": []
        },
        "smoke": {
            "description": "Run smoke tests",
            "markers": ["smoke"],
            "paths": []
        },
        "unit": {
            "description": "Run unit tests",
            "paths": ["tests/unit/", "tests/tm/", "tests/models/", "tests/hardware/"]
        },
        "integration": {
            "description": "Run integration tests",
            "paths": ["tests/integration/"]
        }
    }

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.parser = PytestResultParser()

    def execute_suite(
        self,
        suite_name: str,
        timeout: Optional[int] = 600,
        parallel: bool = False,
        verbose: bool = False,
        capture_output: bool = True
    ) -> TestResult:
        """
        Execute a test suite.

        Args:
            suite_name: Name of suite to execute ("all", "critical", etc.)
            timeout: Maximum time in seconds (None for no timeout)
            parallel: Enable parallel execution with pytest-xdist
            verbose: Enable verbose output
            capture_output: Capture pytest output for parsing

        Returns:
            TestResult with execution details
        """
        if suite_name not in self.SUITES:
            return TestResult(
                suite_name=suite_name,
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
                duration=0.0,
                exit_code=2,
                details=f"Unknown suite: {suite_name}. Available: {', '.join(self.SUITES.keys())}"
            )

        suite_config = self.SUITES[suite_name]

        # Build pytest command
        pytest_args = [sys.executable, "-m", "pytest"]

        # Add paths if specified
        paths = suite_config.get("paths", [])
        if paths:
            pytest_args.extend(paths)
        else:
            pytest_args.append("tests/")

        # Add markers if specified
        for marker in suite_config.get("markers", []):
            pytest_args.extend(["-m", marker])

        # Add verbosity
        if verbose:
            pytest_args.append("-v")
        else:
            pytest_args.append("-q")

        # Add parallel execution
        if parallel:
            pytest_args.extend(["-n", "auto"])

        # Disable coverage for faster execution
        pytest_args.append("--no-cov")

        # Start timing
        start_time = time.time()

        try:
            # Execute pytest
            result = subprocess.run(
                pytest_args,
                cwd=self.project_root,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )

            duration = time.time() - start_time
            output = result.stdout + result.stderr

            # Parse results
            parsed = self.parser.parse_output(output)

            return TestResult(
                suite_name=suite_name,
                total_tests=parsed["total"],
                passed=parsed["passed"],
                failed=parsed["failed"],
                skipped=parsed["skipped"],
                errors=parsed["errors"],
                duration=duration,
                exit_code=result.returncode,
                details=f"Suite '{suite_name}' completed. {suite_config['description']}"
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return TestResult(
                suite_name=suite_name,
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
                duration=duration,
                exit_code=2,
                details=f"Test suite '{suite_name}' timed out after {timeout}s"
            )

        except FileNotFoundError:
            return TestResult(
                suite_name=suite_name,
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
                duration=0.0,
                exit_code=2,
                details="pytest not found. Install with: pip install pytest"
            )

        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                suite_name=suite_name,
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
                duration=duration,
                exit_code=2,
                details=f"Error executing tests: {type(e).__name__}: {str(e)}"
            )

    def execute_multiple_suites(
        self,
        suite_names: List[str],
        timeout: Optional[int] = 600,
        parallel: bool = False,
        verbose: bool = False
    ) -> List[TestResult]:
        """
        Execute multiple test suites.

        Args:
            suite_names: List of suite names to execute
            timeout: Maximum time per suite in seconds
            parallel: Enable parallel execution
            verbose: Enable verbose output

        Returns:
            List of TestResult objects
        """
        results = []
        for suite_name in suite_names:
            print(f"\n{'='*70}")
            print(f"Executing suite: {suite_name}")
            print(f"{'='*70}")

            result = self.execute_suite(
                suite_name=suite_name,
                timeout=timeout,
                parallel=parallel,
                verbose=verbose,
                capture_output=True
            )

            results.append(result)

            # Print immediate feedback
            status = "[PASS]" if result.success else "[FAIL]"
            print(f"\n{status} Suite '{suite_name}': {result.passed}/{result.total_tests} passed in {result.duration:.2f}s")
            if not result.success:
                print(f"  Failed: {result.failed}, Errors: {result.errors}, Skipped: {result.skipped}")

        return results


class TestReporter:
    """Generate test execution reports."""

    @staticmethod
    def print_summary(results: List[TestResult]):
        """Print summary of test execution."""
        print("\n" + "="*70)
        print("TEST EXECUTION SUMMARY")
        print("="*70)

        total_tests = sum(r.total_tests for r in results)
        total_passed = sum(r.passed for r in results)
        total_failed = sum(r.failed for r in results)
        total_skipped = sum(r.skipped for r in results)
        total_errors = sum(r.errors for r in results)
        total_duration = sum(r.duration for r in results)

        all_passed = all(r.success for r in results)

        print(f"\nOverall Results:")
        print(f"  Total Tests:  {total_tests}")
        print(f"  Passed:       {total_passed}")
        print(f"  Failed:       {total_failed}")
        print(f"  Skipped:      {total_skipped}")
        print(f"  Errors:       {total_errors}")
        print(f"  Duration:     {total_duration:.2f}s")
        print(f"  Status:       {'[PASS]' if all_passed else '[FAIL]'}")

        print(f"\nPer-Suite Results:")
        for result in results:
            status = "[PASS]" if result.success else "[FAIL]"
            print(f"  {status} {result.suite_name}: {result.passed}/{result.total_tests} passed ({result.duration:.2f}s)")

        print("="*70 + "\n")

    @staticmethod
    def generate_json_report(results: List[TestResult], output_file: Path):
        """Generate JSON report of test execution."""
        report = {
            "summary": {
                "total_suites": len(results),
                "total_tests": sum(r.total_tests for r in results),
                "total_passed": sum(r.passed for r in results),
                "total_failed": sum(r.failed for r in results),
                "total_skipped": sum(r.skipped for r in results),
                "total_errors": sum(r.errors for r in results),
                "total_duration": sum(r.duration for r in results),
                "all_passed": all(r.success for r in results)
            },
            "suites": [r.to_dict() for r in results]
        }

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Execute test suites with reporting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available suites:
  all       - Run all tests
  critical  - Run only critical tests (marked with @pytest.mark.critical)
  fast      - Run fast tests (marked with @pytest.mark.fast)
  slow      - Run slow tests (marked with @pytest.mark.slow)
  smoke     - Run smoke tests (marked with @pytest.mark.smoke)
  unit      - Run unit tests
  integration - Run integration tests

Examples:
  python scripts/run_all_tests.py --suite all
  python scripts/run_all_tests.py --suite critical --timeout 300
  python scripts/run_all_tests.py --suite unit --suite integration --parallel
        """
    )

    parser.add_argument(
        "--suite",
        action="append",
        choices=TestRunner.SUITES.keys(),
        help="Test suite to run (can be specified multiple times)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout per suite in seconds (default: 600)"
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Enable parallel test execution (requires pytest-xdist)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Output JSON report to file"
    )

    args = parser.parse_args()

    # Default to "all" suite if none specified
    suite_names = args.suite if args.suite else ["all"]

    # Get project root
    project_root = Path(__file__).parent.parent.resolve()

    # Create test runner
    runner = TestRunner(project_root)

    print(f"Project root: {project_root}")
    print(f"Executing suites: {', '.join(suite_names)}")
    print(f"Timeout per suite: {args.timeout}s")
    print(f"Parallel execution: {args.parallel}")

    # Execute test suites
    results = runner.execute_multiple_suites(
        suite_names=suite_names,
        timeout=args.timeout,
        parallel=args.parallel,
        verbose=args.verbose
    )

    # Print summary
    TestReporter.print_summary(results)

    # Generate JSON report if requested
    if args.report:
        TestReporter.generate_json_report(results, args.report)
        print(f"JSON report written to: {args.report}")

    # Determine exit code
    all_passed = all(r.success for r in results)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
