#!/usr/bin/env python3
"""
Production Readiness Validation Runner

Wrapper that executes production_readiness_check.py and validates results.

Features:
- Execute production_readiness_check.py
- Capture and parse output
- Validate exit code and check results
- Generate evidence report with audit trail
- Support retry logic for transient failures
- Strict mode (fail on warnings)

Usage:
    python scripts/validate_production_readiness.py --strict
    python scripts/validate_production_readiness.py --report reports/readiness_validation.json
    python scripts/validate_production_readiness.py --retry 3
"""
import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class CheckResult:
    """Result of a single readiness check."""
    name: str
    passed: bool
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ValidationReport:
    """Complete validation report with evidence."""
    timestamp: str
    command: str
    exit_code: int
    execution_time: float
    checks: List[CheckResult]
    stdout: str
    stderr: str
    passed: bool
    retry_count: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp,
            'command': self.command,
            'exit_code': self.exit_code,
            'execution_time': self.execution_time,
            'checks': [asdict(c) for c in self.checks],
            'stdout': self.stdout,
            'stderr': self.stderr,
            'passed': self.passed,
            'retry_count': self.retry_count,
            'warnings': self.warnings
        }


class ReadinessRunner:
    """Executes production_readiness_check.py and captures results."""

    def __init__(self, project_root: Path, python_executable: str = sys.executable):
        self.project_root = project_root
        self.python_executable = python_executable
        self.script_path = project_root / "scripts" / "production_readiness_check.py"

    def execute(self, strict: bool = False, timeout: int = 120) -> Tuple[int, str, str, float]:
        """
        Execute production_readiness_check.py.

        Args:
            strict: Enable strict mode in the check script
            timeout: Timeout in seconds

        Returns:
            (exit_code, stdout, stderr, execution_time)
        """
        if not self.script_path.exists():
            raise FileNotFoundError(f"Script not found: {self.script_path}")

        cmd = [
            self.python_executable,
            str(self.script_path),
            "--project-root", str(self.project_root)
        ]

        if strict:
            cmd.append("--strict")

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=timeout
            )

            execution_time = time.time() - start_time

            return result.returncode, result.stdout, result.stderr, execution_time

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            error_msg = f"Production readiness check timed out after {timeout}s"
            return 1, "", error_msg, execution_time

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Failed to execute readiness check: {e}"
            return 1, "", error_msg, execution_time


class OutputParser:
    """Parses production_readiness_check.py output."""

    def parse(self, stdout: str, stderr: str) -> List[CheckResult]:
        """
        Parse check results from output.

        The output format is:
        ✓ Check Name: message
        ✗ Check Name: message
        """
        checks = []
        lines = stdout.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for check result lines
            if line.startswith('✓') or line.startswith('✗'):
                passed = line.startswith('✓')

                # Remove status symbol
                line = line[1:].strip()

                # Split on first colon
                if ':' in line:
                    name, message = line.split(':', 1)
                    name = name.strip()
                    message = message.strip()

                    checks.append(CheckResult(
                        name=name,
                        passed=passed,
                        message=message
                    ))

        return checks

    def extract_summary(self, stdout: str) -> Optional[str]:
        """Extract summary line from output."""
        lines = stdout.split('\n')
        for line in lines:
            if 'RESULTS:' in line:
                return line.strip()
        return None

    def extract_warnings(self, stdout: str) -> List[str]:
        """Extract warnings from output."""
        warnings = []
        lines = stdout.split('\n')

        for line in lines:
            line = line.strip()
            if 'warning' in line.lower():
                warnings.append(line)

        return warnings


class ResultValidator:
    """Validates check results against criteria."""

    def __init__(self, strict: bool = False):
        self.strict = strict

    def validate(self, checks: List[CheckResult], exit_code: int, warnings: List[str]) -> bool:
        """
        Validate that all checks passed.

        Args:
            checks: List of check results
            exit_code: Exit code from script
            warnings: List of warning messages

        Returns:
            True if validation passed
        """
        # Check exit code
        if exit_code != 0:
            return False

        # Check all checks passed
        all_passed = all(check.passed for check in checks)
        if not all_passed:
            return False

        # In strict mode, fail on warnings
        if self.strict and warnings:
            return False

        return True

    def get_failed_checks(self, checks: List[CheckResult]) -> List[CheckResult]:
        """Get list of failed checks."""
        return [check for check in checks if not check.passed]


class EvidenceReporter:
    """Generates evidence reports for audit trail."""

    def generate_report(
        self,
        validation: ValidationReport,
        output_path: Optional[Path] = None
    ) -> str:
        """
        Generate validation report.

        Args:
            validation: Validation report data
            output_path: Optional path to save report (JSON format)

        Returns:
            Report as JSON string
        """
        report_dict = validation.to_dict()
        report_json = json.dumps(report_dict, indent=2)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report_json)

        return report_json

    def generate_markdown_report(self, validation: ValidationReport) -> str:
        """Generate human-readable markdown report."""
        lines = [
            "# Production Readiness Validation Report",
            "",
            f"**Timestamp:** {validation.timestamp}",
            f"**Command:** `{validation.command}`",
            f"**Exit Code:** {validation.exit_code}",
            f"**Execution Time:** {validation.execution_time:.2f}s",
            f"**Status:** {'✅ PASSED' if validation.passed else '❌ FAILED'}",
            ""
        ]

        if validation.retry_count > 0:
            lines.append(f"**Retries:** {validation.retry_count}")
            lines.append("")

        # Check results
        lines.append("## Check Results")
        lines.append("")

        passed_checks = [c for c in validation.checks if c.passed]
        failed_checks = [c for c in validation.checks if not c.passed]

        lines.append(f"**Total Checks:** {len(validation.checks)}")
        lines.append(f"**Passed:** {len(passed_checks)}")
        lines.append(f"**Failed:** {len(failed_checks)}")
        lines.append("")

        if failed_checks:
            lines.append("### Failed Checks")
            lines.append("")
            for check in failed_checks:
                lines.append(f"- ❌ **{check.name}**: {check.message}")
            lines.append("")

        lines.append("### All Checks")
        lines.append("")
        for check in validation.checks:
            status = "✅" if check.passed else "❌"
            lines.append(f"- {status} **{check.name}**: {check.message}")
        lines.append("")

        # Warnings
        if validation.warnings:
            lines.append("## Warnings")
            lines.append("")
            for warning in validation.warnings:
                lines.append(f"- ⚠️  {warning}")
            lines.append("")

        # Evidence
        lines.append("## Execution Evidence")
        lines.append("")
        lines.append("### Standard Output")
        lines.append("```")
        lines.append(validation.stdout)
        lines.append("```")
        lines.append("")

        if validation.stderr:
            lines.append("### Standard Error")
            lines.append("```")
            lines.append(validation.stderr)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


class ProductionReadinessValidator:
    """Main validator orchestrating the validation process."""

    def __init__(
        self,
        project_root: Path,
        strict: bool = False,
        max_retries: int = 0,
        retry_delay: int = 5
    ):
        self.project_root = project_root
        self.strict = strict
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self.runner = ReadinessRunner(project_root)
        self.parser = OutputParser()
        self.validator = ResultValidator(strict=strict)
        self.reporter = EvidenceReporter()

    def validate(self) -> ValidationReport:
        """
        Run complete validation process.

        Returns:
            ValidationReport with results and evidence
        """
        retry_count = 0
        last_report = None

        while retry_count <= self.max_retries:
            # Execute check
            exit_code, stdout, stderr, execution_time = self.runner.execute(
                strict=self.strict,
                timeout=120
            )

            # Parse results
            checks = self.parser.parse(stdout, stderr)
            warnings = self.parser.extract_warnings(stdout)

            # Validate results
            passed = self.validator.validate(checks, exit_code, warnings)

            # Create report
            report = ValidationReport(
                timestamp=datetime.now().isoformat(),
                command=f"python scripts/production_readiness_check.py --project-root {self.project_root}",
                exit_code=exit_code,
                execution_time=execution_time,
                checks=checks,
                stdout=stdout,
                stderr=stderr,
                passed=passed,
                retry_count=retry_count,
                warnings=warnings
            )

            last_report = report

            # If passed, return immediately
            if passed:
                return report

            # Check if retry is appropriate
            if retry_count < self.max_retries:
                # Check if failure might be transient
                if self._is_transient_failure(checks, stderr):
                    print(f"Transient failure detected, retrying in {self.retry_delay}s...")
                    print(f"Retry {retry_count + 1}/{self.max_retries}")
                    time.sleep(self.retry_delay)
                    retry_count += 1
                    continue
                else:
                    # Non-transient failure, don't retry
                    break
            else:
                break

        return last_report

    def _is_transient_failure(self, checks: List[CheckResult], stderr: str) -> bool:
        """
        Determine if failure might be transient.

        Transient failures:
        - Network/connection issues
        - Temporary resource unavailability
        - Timeout errors

        Non-transient failures:
        - Config errors
        - Missing files
        - Code errors
        """
        transient_indicators = [
            'timeout',
            'connection',
            'network',
            'temporary',
            'retry',
            'unavailable',
            'busy'
        ]

        # Check stderr for transient indicators
        stderr_lower = stderr.lower()
        for indicator in transient_indicators:
            if indicator in stderr_lower:
                return True

        # Check failed checks
        for check in checks:
            if not check.passed:
                message_lower = check.message.lower()
                for indicator in transient_indicators:
                    if indicator in message_lower:
                        return True

        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate production readiness with evidence reporting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate production readiness
  python scripts/validate_production_readiness.py

  # Strict mode (fail on warnings)
  python scripts/validate_production_readiness.py --strict

  # Generate evidence report
  python scripts/validate_production_readiness.py --report reports/readiness_validation.json

  # Retry on transient failures
  python scripts/validate_production_readiness.py --retry 3

  # Markdown report
  python scripts/validate_production_readiness.py --markdown reports/readiness_validation.md
"""
    )

    parser.add_argument(
        '--strict',
        action='store_true',
        help='Strict mode: fail on warnings'
    )
    parser.add_argument(
        '--report',
        type=Path,
        help='Generate JSON evidence report at specified path'
    )
    parser.add_argument(
        '--markdown',
        type=Path,
        help='Generate markdown report at specified path'
    )
    parser.add_argument(
        '--retry',
        type=int,
        default=0,
        help='Number of retries on transient failures (default: 0)'
    )
    parser.add_argument(
        '--retry-delay',
        type=int,
        default=5,
        help='Delay between retries in seconds (default: 5)'
    )
    parser.add_argument(
        '--project-root',
        type=Path,
        default=Path(__file__).parent.parent,
        help='Project root directory'
    )

    args = parser.parse_args()

    # Create validator
    validator = ProductionReadinessValidator(
        project_root=args.project_root,
        strict=args.strict,
        max_retries=args.retry,
        retry_delay=args.retry_delay
    )

    # Run validation
    print("=" * 70)
    print("PRODUCTION READINESS VALIDATION")
    print("=" * 70)
    print(f"Project root: {args.project_root}")
    print(f"Strict mode: {args.strict}")
    print(f"Max retries: {args.retry}")
    print()

    report = validator.validate()

    # Print summary
    print()
    print("=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"Timestamp: {report.timestamp}")
    print(f"Execution time: {report.execution_time:.2f}s")
    print(f"Exit code: {report.exit_code}")
    print(f"Retry count: {report.retry_count}")
    print()

    print(f"Checks: {len(report.checks)}")
    passed_count = sum(1 for c in report.checks if c.passed)
    print(f"Passed: {passed_count}")
    print(f"Failed: {len(report.checks) - passed_count}")
    print()

    if report.warnings:
        print(f"Warnings: {len(report.warnings)}")
        for warning in report.warnings:
            print(f"  ⚠️  {warning}")
        print()

    # Show failed checks
    failed_checks = validator.validator.get_failed_checks(report.checks)
    if failed_checks:
        print("Failed checks:")
        for check in failed_checks:
            print(f"  ❌ {check.name}: {check.message}")
        print()

    # Generate reports
    if args.report:
        json_report = validator.reporter.generate_report(report, args.report)
        print(f"Evidence report saved to: {args.report}")

    if args.markdown:
        md_report = validator.reporter.generate_markdown_report(report)
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(md_report)
        print(f"Markdown report saved to: {args.markdown}")

    # Final status
    print()
    if report.passed:
        print("✅ Production readiness validation PASSED")
        return 0
    else:
        print("❌ Production readiness validation FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
