#!/usr/bin/env python3
"""
Smoke Test Runner

Executes smoke tests with configurable modes:
- --quick: Run essential tests only (~20 tests, <30s)
- --full: Run all smoke tests (~50 tests, <60s)

Features:
- Timeout enforcement
- Result reporting
- Exit code based on test results
- Parallel execution support
- Clear output formatting
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple


class SmokeTestRunner:
    """Runner for smoke tests with timeout and result tracking."""

    def __init__(self, project_root: Path, timeout: int = 120):
        self.project_root = project_root
        self.timeout = timeout
        self.tests_dir = project_root / "tests" / "smoke"

    def run_pytest(
        self,
        test_files: Optional[List[str]] = None,
        markers: Optional[str] = None,
        verbose: bool = True,
        parallel: bool = False
    ) -> Tuple[int, str, float]:
        """
        Run pytest with specified options.

        Args:
            test_files: Specific test files to run (None = all smoke tests)
            markers: Pytest markers to filter tests
            verbose: Enable verbose output
            parallel: Run tests in parallel (using pytest-xdist if available)

        Returns:
            (exit_code, output, elapsed_time)
        """
        cmd = [sys.executable, "-m", "pytest"]

        # Add test directory or specific files
        if test_files:
            for tf in test_files:
                cmd.append(str(self.tests_dir / tf))
        else:
            cmd.append(str(self.tests_dir))

        # Add markers
        if markers:
            cmd.extend(["-m", markers])

        # Verbosity
        if verbose:
            cmd.append("-v")

        # Parallel execution
        if parallel:
            try:
                # Check if pytest-xdist is available
                import xdist
                cmd.extend(["-n", "auto"])
            except ImportError:
                print("Warning: pytest-xdist not installed, running serially")

        # Add timing info
        cmd.append("--durations=10")

        # Capture output
        cmd.extend(["--tb=short"])

        print(f"Running: {' '.join(cmd)}")
        print(f"Timeout: {self.timeout}s")
        print()

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            elapsed = time.time() - start_time

            return result.returncode, result.stdout + result.stderr, elapsed

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            error_msg = f"ERROR: Smoke tests exceeded timeout of {self.timeout}s"
            return 1, error_msg, elapsed

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"ERROR: Failed to run smoke tests: {e}"
            return 1, error_msg, elapsed

    def parse_pytest_output(self, output: str) -> dict:
        """
        Parse pytest output to extract test results.

        Returns:
            Dictionary with test statistics
        """
        stats = {
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': 0,
            'total': 0,
            'duration': 0.0
        }

        # Look for pytest summary line
        # Example: "===== 10 passed, 2 warnings in 5.23s ====="
        for line in output.split('\n'):
            if '=====' in line and 'passed' in line:
                # Extract numbers
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'passed':
                        stats['passed'] = int(parts[i-1])
                    elif part == 'failed':
                        stats['failed'] = int(parts[i-1])
                    elif part == 'skipped':
                        stats['skipped'] = int(parts[i-1])
                    elif part == 'error' or part == 'errors':
                        stats['errors'] = int(parts[i-1])
                    elif part.endswith('s') and 'in' in parts[i-1:i+1]:
                        try:
                            stats['duration'] = float(part.rstrip('s'))
                        except ValueError:
                            pass

        stats['total'] = stats['passed'] + stats['failed'] + stats['skipped'] + stats['errors']

        return stats

    def run_quick_tests(self) -> int:
        """
        Run essential smoke tests only.

        Quick mode tests:
        - GPU detection
        - TM L1/L2 initialization
        - Config loading
        - Model registry
        - Basic TM lookup

        Target: ~20 tests in <30s
        """
        print("=" * 70)
        print("SMOKE TESTS - QUICK MODE")
        print("=" * 70)
        print("Running essential tests (~20 tests, target <30s)")
        print()

        # Quick tests - only critical path tests, limited integration
        test_selection = [
            "test_critical_paths.py::test_gpu_detection_smoke",
            "test_critical_paths.py::test_tm_l1_initialization",
            "test_critical_paths.py::test_tm_l2_initialization",
            "test_critical_paths.py::test_tm_l3_initialization",
            "test_critical_paths.py::test_config_loading_smoke",
            "test_critical_paths.py::test_model_registry_initialization",
            "test_critical_paths.py::test_translation_memory_initialization",
            "test_critical_paths.py::test_translation_memory_lookup_chain",
            "test_critical_paths.py::test_critical_imports",
            "test_integration_smoke.py::test_simple_translation_pipeline",
            "test_integration_smoke.py::test_tm_lookup_chain",
            "test_integration_smoke.py::test_quality_validation_placeholder_check",
            "test_integration_smoke.py::test_config_hardware_integration",
        ]

        exit_code, output, elapsed = self.run_pytest(
            test_files=None,  # Run all with marker filter
            markers="smoke",
            verbose=True,
            parallel=False  # Quick mode runs serially for consistency
        )

        # Parse results
        stats = self.parse_pytest_output(output)

        # Print output
        print(output)
        print()
        print("=" * 70)
        print("QUICK SMOKE TEST RESULTS")
        print("=" * 70)
        print(f"Tests run: {stats['total']}")
        print(f"Passed: {stats['passed']}")
        print(f"Failed: {stats['failed']}")
        print(f"Skipped: {stats['skipped']}")
        print(f"Errors: {stats['errors']}")
        print(f"Duration: {elapsed:.2f}s")
        print()

        if elapsed > 30:
            print(f"⚠️  Warning: Quick tests exceeded 30s target ({elapsed:.2f}s)")

        if exit_code == 0:
            print("✅ Quick smoke tests PASSED")
        else:
            print("❌ Quick smoke tests FAILED")

        return exit_code

    def run_full_tests(self) -> int:
        """
        Run all smoke tests.

        Full mode tests:
        - All critical path tests
        - All integration tests
        - System compatibility checks

        Target: ~50 tests in <60s
        """
        print("=" * 70)
        print("SMOKE TESTS - FULL MODE")
        print("=" * 70)
        print("Running all smoke tests (~50 tests, target <60s)")
        print()

        exit_code, output, elapsed = self.run_pytest(
            markers="smoke",
            verbose=True,
            parallel=True  # Full mode can use parallel execution
        )

        # Parse results
        stats = self.parse_pytest_output(output)

        # Print output
        print(output)
        print()
        print("=" * 70)
        print("FULL SMOKE TEST RESULTS")
        print("=" * 70)
        print(f"Tests run: {stats['total']}")
        print(f"Passed: {stats['passed']}")
        print(f"Failed: {stats['failed']}")
        print(f"Skipped: {stats['skipped']}")
        print(f"Errors: {stats['errors']}")
        print(f"Duration: {elapsed:.2f}s")
        print()

        if elapsed > 60:
            print(f"⚠️  Warning: Full tests exceeded 60s target ({elapsed:.2f}s)")

        if exit_code == 0:
            print("✅ Full smoke tests PASSED")
        else:
            print("❌ Full smoke tests FAILED")

        return exit_code

    def check_test_speed(self) -> bool:
        """
        Verify that smoke tests complete within time limits.

        Returns:
            True if tests meet speed requirements
        """
        print("Checking smoke test speed...")
        print()

        exit_code, output, elapsed = self.run_pytest(
            markers="smoke",
            verbose=False,
            parallel=True
        )

        stats = self.parse_pytest_output(output)

        print(f"Smoke tests completed in {elapsed:.2f}s")
        print(f"Tests run: {stats['total']}")
        print()

        if elapsed <= 60:
            print(f"✅ Speed check PASSED (target: <60s, actual: {elapsed:.2f}s)")
            return True
        else:
            print(f"❌ Speed check FAILED (target: <60s, actual: {elapsed:.2f}s)")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run smoke tests with configurable modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run quick smoke tests (essential tests only, <30s)
  python scripts/run_smoke_tests.py --quick

  # Run full smoke tests (all tests, <60s)
  python scripts/run_smoke_tests.py --full

  # Check test speed
  python scripts/run_smoke_tests.py --check-speed

  # Run with custom timeout
  python scripts/run_smoke_tests.py --full --timeout 120
"""
    )

    parser.add_argument(
        '--quick',
        action='store_true',
        help='Run quick smoke tests (essential only, ~20 tests, <30s)'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Run full smoke tests (all tests, ~50 tests, <60s)'
    )
    parser.add_argument(
        '--check-speed',
        action='store_true',
        help='Verify smoke tests meet speed requirements'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=120,
        help='Timeout in seconds (default: 120)'
    )
    parser.add_argument(
        '--project-root',
        type=Path,
        default=Path(__file__).parent.parent,
        help='Project root directory'
    )

    args = parser.parse_args()

    # Create runner
    runner = SmokeTestRunner(
        project_root=args.project_root,
        timeout=args.timeout
    )

    # Determine mode
    if args.check_speed:
        success = runner.check_test_speed()
        return 0 if success else 1
    elif args.quick:
        return runner.run_quick_tests()
    elif args.full:
        return runner.run_full_tests()
    else:
        # Default to quick mode
        print("No mode specified, running quick smoke tests")
        print("Use --quick, --full, or --check-speed")
        print()
        return runner.run_quick_tests()


if __name__ == "__main__":
    sys.exit(main())
