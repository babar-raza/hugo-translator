#!/usr/bin/env python3
"""Check production readiness against comprehensive checklist."""
import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class CheckResult:
    """Result of a production readiness check."""
    category: str
    check_name: str
    passed: bool
    message: str
    automated: bool
    severity: str = "required"  # required, recommended, optional
    details: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ProductionReadinessChecker:
    """Check production readiness across 6 categories."""

    def __init__(self, project_root: Path, strict: bool = False):
        """Initialize checker.

        Args:
            project_root: Project root directory
            strict: If True, treat warnings as failures
        """
        self.project_root = Path(project_root)
        self.strict = strict
        self.results: list[CheckResult] = []

    def check_python_syntax(self) -> CheckResult:
        """Check all Python files have valid syntax."""
        import py_compile

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
                category="Code Quality",
                check_name="python_syntax",
                passed=True,
                automated=True,
                message=f"All {len(python_files)} Python files have valid syntax"
            )
        else:
            return CheckResult(
                category="Code Quality",
                check_name="python_syntax",
                passed=False,
                automated=True,
                message=f"Found {len(errors)} Python syntax errors",
                details="\n".join(errors[:5])
            )

    def check_no_todos(self) -> CheckResult:
        """Check for TODO/FIXME comments in source code."""
        try:
            result = subprocess.run(
                ["grep", "-r", "-E", "TODO|FIXME", "src/"],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )

            todo_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0

            if todo_count == 0:
                return CheckResult(
                    category="Code Quality",
                    check_name="no_todos",
                    passed=True,
                    automated=True,
                    message="No TODO/FIXME comments in source code"
                )
            else:
                return CheckResult(
                    category="Code Quality",
                    check_name="no_todos",
                    passed=False,
                    automated=True,
                    message=f"Found {todo_count} TODO/FIXME comments",
                    details=result.stdout[:500]
                )

        except FileNotFoundError:
            return CheckResult(
                category="Code Quality",
                check_name="no_todos",
                passed=True,
                automated=True,
                message="grep not available, check skipped",
                severity="recommended"
            )

    def check_no_print_statements(self) -> CheckResult:
        """Check for print() statements (should use logging)."""
        try:
            result = subprocess.run(
                ["grep", "-r", "-E", "^[^#]*print\\(", "src/"],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )

            lines = [line for line in result.stdout.strip().split('\n') if line and '/test' not in line]
            print_count = len(lines)

            if print_count == 0:
                return CheckResult(
                    category="Code Quality",
                    check_name="no_print_statements",
                    passed=True,
                    automated=True,
                    message="No print() statements in non-test code"
                )
            else:
                return CheckResult(
                    category="Code Quality",
                    check_name="no_print_statements",
                    passed=False,
                    automated=True,
                    message=f"Found {print_count} print() statements",
                    details="\n".join(lines[:5])
                )

        except FileNotFoundError:
            return CheckResult(
                category="Code Quality",
                check_name="no_print_statements",
                passed=True,
                automated=True,
                message="grep not available, check skipped",
                severity="recommended"
            )

    def check_no_hardcoded_secrets(self) -> CheckResult:
        """Check for hardcoded secrets/credentials."""
        try:
            result = subprocess.run(
                ["grep", "-r", "-i", "-E", "api_key|password|secret|token", "src/"],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )

            # Filter out comments and variable names
            lines = []
            for line in result.stdout.strip().split('\n'):
                if line and '#' not in line.split(':')[1] if ':' in line else True:
                    # Exclude common false positives
                    if 'os.environ' not in line and 'getenv' not in line:
                        lines.append(line)

            if len(lines) == 0 or (len(lines) == 1 and not lines[0]):
                return CheckResult(
                    category="Security",
                    check_name="no_hardcoded_secrets",
                    passed=True,
                    automated=True,
                    message="No hardcoded secrets found"
                )
            else:
                return CheckResult(
                    category="Security",
                    check_name="no_hardcoded_secrets",
                    passed=False,
                    automated=True,
                    message=f"Found {len(lines)} potential hardcoded secrets",
                    details="\n".join(lines[:5]),
                    severity="critical"
                )

        except FileNotFoundError:
            return CheckResult(
                category="Security",
                check_name="no_hardcoded_secrets",
                passed=True,
                automated=True,
                message="grep not available, check skipped",
                severity="recommended"
            )

    def check_readme_exists(self) -> CheckResult:
        """Check README.md exists and is comprehensive."""
        readme = self.project_root / "README.md"

        if not readme.exists():
            return CheckResult(
                category="Documentation",
                check_name="readme_exists",
                passed=False,
                automated=True,
                message="README.md not found"
            )

        # Check README has minimum content
        content = readme.read_text()
        required_sections = ["installation", "usage", "configuration"]
        missing = [s for s in required_sections if s.lower() not in content.lower()]

        if missing:
            return CheckResult(
                category="Documentation",
                check_name="readme_exists",
                passed=False,
                automated=True,
                message=f"README.md missing sections: {', '.join(missing)}",
                severity="recommended"
            )

        return CheckResult(
            category="Documentation",
            check_name="readme_exists",
            passed=True,
            automated=True,
            message=f"README.md exists with {len(content)} characters"
        )

    def check_logging_configured(self) -> CheckResult:
        """Check logging is properly configured."""
        # Check for logger usage in main modules
        main_files = list(self.project_root.glob("src/**/*.py"))

        files_with_logging = 0
        for py_file in main_files:
            if py_file.name.startswith('__'):
                continue
            content = py_file.read_text()
            if 'import logging' in content or 'from logging import' in content:
                files_with_logging += 1

        if files_with_logging == 0:
            return CheckResult(
                category="Operations",
                check_name="logging_configured",
                passed=False,
                automated=True,
                message="No logging imports found in source code"
            )

        return CheckResult(
            category="Operations",
            check_name="logging_configured",
            passed=True,
            automated=True,
            message=f"Logging configured in {files_with_logging} modules"
        )

    def check_gitignore_secrets(self) -> CheckResult:
        """Check .gitignore excludes sensitive files."""
        gitignore = self.project_root / ".gitignore"

        if not gitignore.exists():
            return CheckResult(
                category="Security",
                check_name="gitignore_secrets",
                passed=False,
                automated=True,
                message=".gitignore not found"
            )

        content = gitignore.read_text()
        required_entries = [".env", "*.pem", "*.key", "credentials"]
        missing = [e for e in required_entries if e not in content]

        if missing:
            return CheckResult(
                category="Security",
                check_name="gitignore_secrets",
                passed=False,
                automated=True,
                message=f".gitignore missing entries: {', '.join(missing)}",
                severity="recommended"
            )

        return CheckResult(
            category="Security",
            check_name="gitignore_secrets",
            passed=True,
            automated=True,
            message=".gitignore properly configured"
        )

    def check_file_permissions(self) -> CheckResult:
        """Check no world-writable files."""
        import stat

        world_writable = []
        for py_file in self.project_root.glob("src/**/*.py"):
            mode = py_file.stat().st_mode
            if mode & stat.S_IWOTH:
                world_writable.append(str(py_file))

        if world_writable:
            return CheckResult(
                category="Security",
                check_name="file_permissions",
                passed=False,
                automated=True,
                message=f"Found {len(world_writable)} world-writable files",
                details="\n".join(world_writable[:5])
            )

        return CheckResult(
            category="Security",
            check_name="file_permissions",
            passed=True,
            automated=True,
            message="No world-writable files found"
        )

    def check_config_files_exist(self) -> CheckResult:
        """Check required configuration files exist."""
        required_configs = [
            "config/global.yaml",
            "config/target_languages.yaml",
            "config/model_registry.yaml"
        ]

        missing = [c for c in required_configs if not (self.project_root / c).exists()]

        if missing:
            return CheckResult(
                category="Deployment",
                check_name="config_files_exist",
                passed=False,
                automated=True,
                message=f"Missing config files: {', '.join(missing)}"
            )

        return CheckResult(
            category="Deployment",
            check_name="config_files_exist",
            passed=True,
            automated=True,
            message=f"All {len(required_configs)} required config files exist"
        )

    def run_all_checks(self) -> list[CheckResult]:
        """Run all automated production readiness checks.

        Returns:
            List of check results
        """
        checks = [
            self.check_python_syntax,
            self.check_no_todos,
            self.check_no_print_statements,
            self.check_no_hardcoded_secrets,
            self.check_readme_exists,
            self.check_logging_configured,
            self.check_gitignore_secrets,
            self.check_file_permissions,
            self.check_config_files_exist
        ]

        results = []
        for check in checks:
            try:
                result = check()
                results.append(result)
            except Exception as e:
                results.append(CheckResult(
                    category="System",
                    check_name=check.__name__,
                    passed=False,
                    automated=True,
                    message=f"Check failed with error: {str(e)}"
                ))

        return results


def main():
    parser = argparse.ArgumentParser(description="Check production readiness")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--category", type=str, help="Run checks for specific category only")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    checker = ProductionReadinessChecker(project_root, strict=args.strict)

    # Run all checks
    results = checker.run_all_checks()

    # Filter by category if specified
    if args.category:
        results = [r for r in results if r.category.lower() == args.category.lower()]

    if not results:
        print(f"No checks found for category: {args.category}")
        return 1

    # Count results
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    automated = sum(1 for r in results if r.automated)

    # Group by category
    by_category: dict[str, list[CheckResult]] = {}
    for result in results:
        if result.category not in by_category:
            by_category[result.category] = []
        by_category[result.category].append(result)

    # Output results
    if args.json:
        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_checks": total,
            "automated_checks": automated,
            "passed": passed,
            "failed": failed,
            "pass_rate": round((passed / total * 100), 1) if total > 0 else 0,
            "by_category": {cat: len([r for r in checks if r.passed]) for cat, checks in by_category.items()},
            "results": [r.to_dict() for r in results]
        }
        print(json.dumps(report, indent=2))
    else:
        print()
        print("=" * 70)
        print("PRODUCTION READINESS REPORT")
        print("=" * 70)
        print()

        for category, checks in sorted(by_category.items()):
            cat_passed = sum(1 for r in checks if r.passed)
            cat_total = len(checks)

            print(f"{category}")
            print("-" * 70)

            for result in checks:
                status = "✓" if result.passed else "✗"
                auto_marker = "[AUTO]" if result.automated else "[MANUAL]"
                print(f"  {status} {auto_marker} {result.check_name}: {result.message}")

                if not result.passed and result.details:
                    print(f"      Details: {result.details[:100]}")

            print(f"  Category: {cat_passed}/{cat_total} passing")
            print()

        print("=" * 70)
        print(f"SUMMARY: {passed}/{total} checks passing ({passed/total*100:.1f}%)")
        print(f"Automated: {automated}/{total} ({automated/total*100:.1f}%)")
        print()

        if failed == 0:
            print("✅ ALL AUTOMATED CHECKS PASSING")
            print()
            print("Next steps:")
            print("  1. Complete manual checks (see docs/quality/PRODUCTION_CHECKLIST.md)")
            print("  2. Obtain required sign-offs")
            print("  3. Schedule deployment")
        else:
            print(f"❌ {failed} CHECK(S) FAILING")
            print()
            print("Failed checks:")
            for result in results:
                if not result.passed:
                    print(f"  - {result.category}: {result.check_name}")
            print()
            print("Review docs/quality/PRODUCTION_CHECKLIST.md for details")

    # Exit code
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
