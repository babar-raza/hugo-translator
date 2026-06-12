#!/usr/bin/env python3
"""Automated quality checks for the codebase."""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class CheckResult:
    """Result of a single quality check."""

    check_name: str
    passed: bool
    message: str
    details: str | None = None
    duration_seconds: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class QualityChecker:
    """Run automated quality checks on the codebase."""

    def __init__(self, project_root: Path):
        """Initialize quality checker.

        Args:
            project_root: Root directory of project
        """
        self.project_root = Path(project_root)
        self.results: list[CheckResult] = []

    def check_todos(self) -> CheckResult:
        """Check for TODO/FIXME comments in source code."""
        import time

        start = time.time()

        try:
            result = subprocess.run(
                ["grep", "-r", "-E", "TODO|FIXME", "src/"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            todo_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0

            if todo_count == 0:
                return CheckResult(
                    check_name="todos",
                    passed=True,
                    message="No TODO/FIXME comments found",
                    duration_seconds=time.time() - start,
                )
            else:
                return CheckResult(
                    check_name="todos",
                    passed=False,
                    message=f"Found {todo_count} TODO/FIXME comments",
                    details=result.stdout[:500],
                    duration_seconds=time.time() - start,
                )

        except FileNotFoundError:
            return CheckResult(
                check_name="todos",
                passed=True,
                message="grep not available, skipping check",
                duration_seconds=time.time() - start,
            )

    def check_print_statements(self) -> CheckResult:
        """Check for print() statements in source code (should use logging)."""
        import time

        start = time.time()

        try:
            result = subprocess.run(
                ["grep", "-r", "-E", "^[^#]*print\\(", "src/"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            # Filter out test files
            lines = [
                line for line in result.stdout.strip().split("\n") if line and "/test" not in line
            ]
            print_count = len(lines)

            if print_count == 0:
                return CheckResult(
                    check_name="print_statements",
                    passed=True,
                    message="No print() statements found in non-test code",
                    duration_seconds=time.time() - start,
                )
            else:
                return CheckResult(
                    check_name="print_statements",
                    passed=False,
                    message=f"Found {print_count} print() statements (use logger instead)",
                    details="\n".join(lines[:10]),
                    duration_seconds=time.time() - start,
                )

        except FileNotFoundError:
            return CheckResult(
                check_name="print_statements",
                passed=True,
                message="grep not available, skipping check",
                duration_seconds=time.time() - start,
            )

    def check_file_structure(self) -> CheckResult:
        """Check that required files and directories exist."""
        import time

        start = time.time()

        required_files = [
            "README.md",
            "config/global.yaml",
            "config/target_languages.yaml",
            "config/quality_rubric.yaml",
            "src/benchmarking/__init__.py",
            "src/model_runtime/__init__.py",
        ]

        required_dirs = [
            "src",
            "tests",
            "config",
            "docs",
            "scripts",
            "models",
        ]

        missing_files = []
        missing_dirs = []

        for file_path in required_files:
            if not (self.project_root / file_path).exists():
                missing_files.append(file_path)

        for dir_path in required_dirs:
            if not (self.project_root / dir_path).is_dir():
                missing_dirs.append(dir_path)

        if not missing_files and not missing_dirs:
            return CheckResult(
                check_name="file_structure",
                passed=True,
                message="All required files and directories exist",
                duration_seconds=time.time() - start,
            )
        else:
            details = ""
            if missing_files:
                details += f"Missing files: {', '.join(missing_files)}\n"
            if missing_dirs:
                details += f"Missing directories: {', '.join(missing_dirs)}"

            return CheckResult(
                check_name="file_structure",
                passed=False,
                message=f"Missing {len(missing_files)} files and {len(missing_dirs)} directories",
                details=details.strip(),
                duration_seconds=time.time() - start,
            )

    def check_yaml_syntax(self) -> CheckResult:
        """Check YAML files for syntax errors."""
        import time

        start = time.time()

        try:
            import yaml
        except ImportError:
            return CheckResult(
                check_name="yaml_syntax",
                passed=True,
                message="PyYAML not installed, skipping check",
                duration_seconds=time.time() - start,
            )

        yaml_files = list(self.project_root.glob("config/**/*.yaml"))
        errors = []

        for yaml_file in yaml_files:
            try:
                with open(yaml_file) as f:
                    yaml.safe_load(f)
            except yaml.YAMLError as e:
                errors.append(f"{yaml_file.name}: {str(e)[:100]}")

        if not errors:
            return CheckResult(
                check_name="yaml_syntax",
                passed=True,
                message=f"All {len(yaml_files)} YAML files have valid syntax",
                duration_seconds=time.time() - start,
            )
        else:
            return CheckResult(
                check_name="yaml_syntax",
                passed=False,
                message=f"Found {len(errors)} YAML syntax errors",
                details="\n".join(errors),
                duration_seconds=time.time() - start,
            )

    def check_json_syntax(self) -> CheckResult:
        """Check JSON files for syntax errors."""
        import time

        start = time.time()

        json_files = list(self.project_root.glob("config/**/*.json"))
        errors = []

        for json_file in json_files:
            try:
                with open(json_file) as f:
                    json.load(f)
            except json.JSONDecodeError as e:
                errors.append(f"{json_file.name}: {str(e)[:100]}")

        if not errors:
            return CheckResult(
                check_name="json_syntax",
                passed=True,
                message=f"All {len(json_files)} JSON files have valid syntax",
                duration_seconds=time.time() - start,
            )
        else:
            return CheckResult(
                check_name="json_syntax",
                passed=False,
                message=f"Found {len(errors)} JSON syntax errors",
                details="\n".join(errors),
                duration_seconds=time.time() - start,
            )

    def check_python_syntax(self) -> CheckResult:
        """Check Python files for syntax errors."""
        import py_compile
        import time

        start = time.time()

        python_files = list(self.project_root.glob("src/**/*.py"))
        python_files.extend(self.project_root.glob("scripts/*.py"))
        python_files.extend(self.project_root.glob("tests/**/*.py"))

        errors = []

        for py_file in python_files:
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{py_file.name}: {str(e)[:100]}")

        if not errors:
            return CheckResult(
                check_name="python_syntax",
                passed=True,
                message=f"All {len(python_files)} Python files have valid syntax",
                duration_seconds=time.time() - start,
            )
        else:
            return CheckResult(
                check_name="python_syntax",
                passed=False,
                message=f"Found {len(errors)} Python syntax errors",
                details="\n".join(errors),
                duration_seconds=time.time() - start,
            )

    def check_hardcoded_paths(self) -> CheckResult:
        """Check for hardcoded localhost/127.0.0.1 references."""
        import time

        start = time.time()

        try:
            result = subprocess.run(
                ["grep", "-r", "-E", "localhost|127\\.0\\.0\\.1", "src/"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            # Filter out comments and acceptable uses
            lines = []
            for line in result.stdout.strip().split("\n"):
                if line and "#" not in line.split(":")[1] if ":" in line else True:
                    lines.append(line)

            if len(lines) == 0 or (len(lines) == 1 and not lines[0]):
                return CheckResult(
                    check_name="hardcoded_paths",
                    passed=True,
                    message="No hardcoded localhost/127.0.0.1 found",
                    duration_seconds=time.time() - start,
                )
            else:
                return CheckResult(
                    check_name="hardcoded_paths",
                    passed=False,
                    message=f"Found {len(lines)} hardcoded localhost/127.0.0.1 references",
                    details="\n".join(lines[:5]),
                    duration_seconds=time.time() - start,
                )

        except FileNotFoundError:
            return CheckResult(
                check_name="hardcoded_paths",
                passed=True,
                message="grep not available, skipping check",
                duration_seconds=time.time() - start,
            )

    def run_all_checks(self, checks: list[str] | None = None) -> list[CheckResult]:
        """Run all quality checks.

        Args:
            checks: Optional list of specific checks to run

        Returns:
            List of check results
        """
        all_checks = {
            "todos": self.check_todos,
            "print_statements": self.check_print_statements,
            "file_structure": self.check_file_structure,
            "yaml_syntax": self.check_yaml_syntax,
            "json_syntax": self.check_json_syntax,
            "python_syntax": self.check_python_syntax,
            "hardcoded_paths": self.check_hardcoded_paths,
        }

        results = []

        for check_name, check_func in all_checks.items():
            if checks is None or check_name in checks:
                print(f"Running check: {check_name}...", file=sys.stderr)
                result = check_func()
                results.append(result)

        return results


def main():
    parser = argparse.ArgumentParser(description="Run automated quality checks")
    parser.add_argument("--check", type=str, help="Run specific check only")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--list", action="store_true", help="List available checks")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    checker = QualityChecker(project_root)

    if args.list:
        print("Available checks:")
        print("  - todos: Check for TODO/FIXME comments")
        print("  - print_statements: Check for print() statements")
        print("  - file_structure: Check required files/directories exist")
        print("  - yaml_syntax: Check YAML syntax")
        print("  - json_syntax: Check JSON syntax")
        print("  - python_syntax: Check Python syntax")
        print("  - hardcoded_paths: Check for hardcoded localhost/127.0.0.1")
        return 0

    # Run checks
    checks = [args.check] if args.check else None
    results = checker.run_all_checks(checks=checks)

    # Output results
    if args.json:
        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_checks": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "results": [r.to_dict() for r in results],
        }
        print(json.dumps(report, indent=2))
    else:
        print("\nQuality Check Report")
        print("=" * 60)

        passed_count = 0
        failed_count = 0

        for result in results:
            status = "✓" if result.passed else "✗"
            print(f"\n{status} {result.check_name}: {result.message}")

            if not result.passed and result.details:
                print(f"  Details:\n{result.details[:200]}")

            if result.passed:
                passed_count += 1
            else:
                failed_count += 1

        print()
        print("=" * 60)
        print(f"Total: {len(results)} | Passed: {passed_count} | Failed: {failed_count}")

        if failed_count > 0:
            print("\n❌ Quality checks FAILED")
        else:
            print("\n✅ All quality checks PASSED")

    # Exit code
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
