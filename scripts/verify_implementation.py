#!/usr/bin/env python3
"""
Implementation Verification Script

Validates all implementation claims systematically:
- File existence checks
- Test collection and counting
- Import validation
- Syntax checking
- Directory structure validation
- Report generation (JSON + Markdown)

Exit codes:
  0: All checks pass
  1: Some checks fail
  2: Verification error
"""

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional
import importlib.util


@dataclass
class VerificationResult:
    """Result of a single verification check."""
    check_name: str
    expected: Any
    actual: Any
    passed: bool
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class VerificationSuite:
    """Main verification suite for implementation validation."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.results: List[VerificationResult] = []

    def verify_files(self, expected_files: List[str]) -> List[VerificationResult]:
        """
        Verify that expected files exist.

        Args:
            expected_files: List of file paths relative to project root

        Returns:
            List of verification results
        """
        results = []
        existing_files = []
        missing_files = []

        for file_path in expected_files:
            full_path = self.project_root / file_path
            exists = full_path.exists()

            if exists:
                existing_files.append(file_path)
            else:
                missing_files.append(file_path)

            results.append(VerificationResult(
                check_name=f"file_exists:{file_path}",
                expected=True,
                actual=exists,
                passed=exists,
                details=f"File {'exists' if exists else 'missing'}: {file_path}"
            ))

        # Summary result
        all_exist = len(missing_files) == 0
        results.append(VerificationResult(
            check_name="file_existence_summary",
            expected=len(expected_files),
            actual=len(existing_files),
            passed=all_exist,
            details=f"{len(existing_files)}/{len(expected_files)} files exist. Missing: {missing_files if missing_files else 'none'}"
        ))

        self.results.extend(results)
        return results

    def verify_directory_structure(self, expected_dirs: List[str]) -> List[VerificationResult]:
        """
        Verify that expected directories exist.

        Args:
            expected_dirs: List of directory paths relative to project root

        Returns:
            List of verification results
        """
        results = []
        existing_dirs = []
        missing_dirs = []

        for dir_path in expected_dirs:
            full_path = self.project_root / dir_path
            exists = full_path.is_dir()

            if exists:
                existing_dirs.append(dir_path)
            else:
                missing_dirs.append(dir_path)

            results.append(VerificationResult(
                check_name=f"directory_exists:{dir_path}",
                expected=True,
                actual=exists,
                passed=exists,
                details=f"Directory {'exists' if exists else 'missing'}: {dir_path}"
            ))

        # Summary result
        all_exist = len(missing_dirs) == 0
        results.append(VerificationResult(
            check_name="directory_structure_summary",
            expected=len(expected_dirs),
            actual=len(existing_dirs),
            passed=all_exist,
            details=f"{len(existing_dirs)}/{len(expected_dirs)} directories exist. Missing: {missing_dirs if missing_dirs else 'none'}"
        ))

        self.results.extend(results)
        return results

    def verify_tests(self, min_expected_tests: int = 0) -> List[VerificationResult]:
        """
        Verify test collection and counting using pytest.

        Args:
            min_expected_tests: Minimum number of tests expected

        Returns:
            List of verification results
        """
        results = []

        try:
            # Use pytest to collect tests without running them
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "-q"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60
            )

            # Parse pytest output to count tests
            output = result.stdout + result.stderr
            test_count = 0

            # Look for "X selected" or "X test" in output
            import re
            matches = re.findall(r'(\d+)\s+(?:test|selected)', output)
            if matches:
                test_count = int(matches[-1])

            passed = test_count >= min_expected_tests

            results.append(VerificationResult(
                check_name="test_collection",
                expected=f">= {min_expected_tests}",
                actual=test_count,
                passed=passed,
                details=f"Collected {test_count} tests (expected >= {min_expected_tests})"
            ))

        except subprocess.TimeoutExpired:
            results.append(VerificationResult(
                check_name="test_collection",
                expected=f">= {min_expected_tests}",
                actual="TIMEOUT",
                passed=False,
                details="Test collection timed out after 60 seconds"
            ))
        except FileNotFoundError:
            results.append(VerificationResult(
                check_name="test_collection",
                expected=f">= {min_expected_tests}",
                actual="PYTEST_NOT_FOUND",
                passed=False,
                details="pytest not found. Install with: pip install pytest"
            ))
        except Exception as e:
            results.append(VerificationResult(
                check_name="test_collection",
                expected=f">= {min_expected_tests}",
                actual=f"ERROR: {type(e).__name__}",
                passed=False,
                details=f"Error collecting tests: {str(e)}"
            ))

        self.results.extend(results)
        return results

    def verify_imports(self, modules: List[str]) -> List[VerificationResult]:
        """
        Verify that specified modules can be imported.

        Args:
            modules: List of module names to import (e.g., "src.hardware.gpu_manager")

        Returns:
            List of verification results
        """
        results = []
        successful_imports = []
        failed_imports = []

        # Save current directory and change to project root
        import os
        original_dir = os.getcwd()
        os.chdir(self.project_root)

        # Add project root to path if not already there
        sys_path_modified = False
        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))
            sys_path_modified = True

        try:
            for module_name in modules:
                try:
                    # Try to import the module
                    spec = importlib.util.find_spec(module_name)
                    if spec is None:
                        raise ImportError(f"Module {module_name} not found")

                    # Actually import it
                    module = importlib.import_module(module_name)
                    successful_imports.append(module_name)

                    results.append(VerificationResult(
                        check_name=f"import:{module_name}",
                        expected="SUCCESS",
                        actual="SUCCESS",
                        passed=True,
                        details=f"Successfully imported {module_name}"
                    ))

                except Exception as e:
                    failed_imports.append(module_name)
                    results.append(VerificationResult(
                        check_name=f"import:{module_name}",
                        expected="SUCCESS",
                        actual=f"FAILED: {type(e).__name__}",
                        passed=False,
                        details=f"Failed to import {module_name}: {str(e)}"
                    ))

            # Summary result
            all_imported = len(failed_imports) == 0
            results.append(VerificationResult(
                check_name="import_validation_summary",
                expected=len(modules),
                actual=len(successful_imports),
                passed=all_imported,
                details=f"{len(successful_imports)}/{len(modules)} modules imported successfully. Failed: {failed_imports if failed_imports else 'none'}"
            ))

        finally:
            # Restore original directory
            os.chdir(original_dir)

            # Remove project root from path if we added it
            if sys_path_modified and str(self.project_root) in sys.path:
                sys.path.remove(str(self.project_root))

        self.results.extend(results)
        return results

    def verify_syntax(self, files: List[str]) -> List[VerificationResult]:
        """
        Verify Python syntax for specified files.

        Args:
            files: List of Python file paths relative to project root

        Returns:
            List of verification results
        """
        results = []
        valid_files = []
        invalid_files = []

        for file_path in files:
            full_path = self.project_root / file_path

            if not full_path.exists():
                results.append(VerificationResult(
                    check_name=f"syntax:{file_path}",
                    expected="VALID",
                    actual="FILE_NOT_FOUND",
                    passed=False,
                    details=f"File not found: {file_path}"
                ))
                invalid_files.append(file_path)
                continue

            try:
                # Use AST parser to check syntax (no temp files needed)
                with open(full_path, 'r', encoding='utf-8') as f:
                    source_code = f.read()

                # Try to parse as AST - this will raise SyntaxError if invalid
                compile(source_code, str(full_path), 'exec')

                valid_files.append(file_path)
                results.append(VerificationResult(
                    check_name=f"syntax:{file_path}",
                    expected="VALID",
                    actual="VALID",
                    passed=True,
                    details=f"Valid Python syntax: {file_path}"
                ))

            except SyntaxError as e:
                invalid_files.append(file_path)
                results.append(VerificationResult(
                    check_name=f"syntax:{file_path}",
                    expected="VALID",
                    actual="INVALID",
                    passed=False,
                    details=f"Syntax error in {file_path} line {e.lineno}: {e.msg}"
                ))
            except Exception as e:
                invalid_files.append(file_path)
                results.append(VerificationResult(
                    check_name=f"syntax:{file_path}",
                    expected="VALID",
                    actual=f"ERROR: {type(e).__name__}",
                    passed=False,
                    details=f"Error checking syntax for {file_path}: {str(e)}"
                ))

        # Summary result
        all_valid = len(invalid_files) == 0
        results.append(VerificationResult(
            check_name="syntax_validation_summary",
            expected=len(files),
            actual=len(valid_files),
            passed=all_valid,
            details=f"{len(valid_files)}/{len(files)} files have valid syntax. Invalid: {invalid_files if invalid_files else 'none'}"
        ))

        self.results.extend(results)
        return results

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of all verification results.

        Returns:
            Dictionary with summary statistics
        """
        total_checks = len(self.results)
        passed_checks = sum(1 for r in self.results if r.passed)
        failed_checks = total_checks - passed_checks

        return {
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "pass_rate": passed_checks / total_checks if total_checks > 0 else 0.0,
            "all_passed": failed_checks == 0
        }


class Reporter:
    """Generate verification reports in various formats."""

    @staticmethod
    def generate_json_report(results: List[VerificationResult], summary: Dict[str, Any], output_file: Path):
        """Generate JSON report."""
        report = {
            "summary": summary,
            "results": [r.to_dict() for r in results]
        }

        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)

    @staticmethod
    def generate_markdown_report(results: List[VerificationResult], summary: Dict[str, Any]) -> str:
        """Generate Markdown report."""
        lines = []
        lines.append("# Implementation Verification Report\n")
        lines.append(f"## Summary\n")
        lines.append(f"- **Total Checks:** {summary['total_checks']}")
        lines.append(f"- **Passed:** {summary['passed_checks']}")
        lines.append(f"- **Failed:** {summary['failed_checks']}")
        lines.append(f"- **Pass Rate:** {summary['pass_rate']:.1%}")
        lines.append(f"- **Overall Status:** {'[PASS]' if summary['all_passed'] else '[FAIL]'}\n")

        # Group results by category
        categories = {}
        for result in results:
            category = result.check_name.split(':')[0] if ':' in result.check_name else result.check_name
            if category not in categories:
                categories[category] = []
            categories[category].append(result)

        lines.append("## Detailed Results\n")
        for category, category_results in categories.items():
            lines.append(f"### {category.replace('_', ' ').title()}\n")
            for result in category_results:
                status = "[PASS]" if result.passed else "[FAIL]"
                lines.append(f"- {status} **{result.check_name}**")
                lines.append(f"  - Expected: `{result.expected}`")
                lines.append(f"  - Actual: `{result.actual}`")
                if result.details:
                    lines.append(f"  - Details: {result.details}")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def print_console_report(results: List[VerificationResult], summary: Dict[str, Any]):
        """Print report to console."""
        print("\n" + "="*70)
        print("IMPLEMENTATION VERIFICATION REPORT")
        print("="*70)
        print(f"\nSummary:")
        print(f"  Total Checks:  {summary['total_checks']}")
        print(f"  Passed:        {summary['passed_checks']}")
        print(f"  Failed:        {summary['failed_checks']}")
        print(f"  Pass Rate:     {summary['pass_rate']:.1%}")
        print(f"  Overall:       {'[PASS]' if summary['all_passed'] else '[FAIL]'}")

        # Show failed checks
        failed_results = [r for r in results if not r.passed]
        if failed_results:
            print(f"\nFailed Checks ({len(failed_results)}):")
            for result in failed_results:
                print(f"  [X] {result.check_name}")
                print(f"     Expected: {result.expected}")
                print(f"     Actual:   {result.actual}")
                if result.details:
                    print(f"     Details:  {result.details}")
                print()

        print("="*70 + "\n")


def get_expected_files() -> List[str]:
    """Get list of expected files from implementation plans."""
    # This would ideally parse plan documents, but for now we'll hardcode key files
    return [
        "scripts/verify_implementation.py",
        "src/hardware/gpu_manager.py",
        "config/global.yaml",
        "tests/verification/__init__.py",
    ]


def get_expected_directories() -> List[str]:
    """Get list of expected directories."""
    return [
        "scripts",
        "src",
        "tests",
        "config",
        "docs",
        "plans",
        "reports",
    ]


def get_expected_modules() -> List[str]:
    """Get list of expected importable modules."""
    return [
        # Add key modules here - will be populated as implementation progresses
    ]


def print_checklist(phase: Optional[str] = None):
    """
    Print verification checklist for specified phase.

    Args:
        phase: Phase name (design, implementation, integration, production) or None for all
    """
    checklists = {
        "design": {
            "name": "Phase 1: Design Review",
            "items": [
                "Requirement Clarity - All requirements are clear and unambiguous",
                "Scope Definition - Scope is well-defined (what's in, what's out)",
                "Dependencies Identified - All dependencies are documented",
                "Edge Cases Considered - Edge cases and failure modes identified",
                "API Contracts Defined - Input/output contracts are documented",
                "Test Strategy Planned - How will this be tested?",
                "Rollback Plan Exists - How to undo changes if verification fails?"
            ]
        },
        "implementation": {
            "name": "Phase 2: Implementation",
            "items": [
                "Files Created - All planned files are created",
                "Syntax Valid - No syntax errors",
                "Imports Work - All imports resolve correctly",
                "Unit Tests Written - Each function has unit tests",
                "Tests Pass - All unit tests pass",
                "Code Style - Follows project conventions",
                "Documentation Added - Docstrings and comments present",
                "No TODOs - No placeholder code or TODOs left"
            ]
        },
        "integration": {
            "name": "Phase 3: Integration",
            "items": [
                "Integration Tests Written - Tests for interactions with other components",
                "Integration Tests Pass - All integration tests pass",
                "Smoke Tests Pass - Quick end-to-end tests pass",
                "No Regressions - Existing functionality still works",
                "Performance Acceptable - No unexpected performance degradation",
                "Error Handling Robust - Errors are caught and handled gracefully",
                "Observability Added - Logging/metrics for the new feature",
                "Documentation Updated - User-facing docs updated if needed"
            ]
        },
        "production": {
            "name": "Phase 4: Production Readiness",
            "items": [
                "All Tests Pass - 100% of tests passing (no skipped critical tests)",
                "Code Coverage Acceptable - Meets project coverage threshold",
                "Documentation Complete - All docs updated",
                "Security Review Done - No security vulnerabilities",
                "Performance Benchmarked - Meets performance requirements",
                "Monitoring Configured - Metrics/logs are being collected",
                "Rollback Tested - Rollback procedure has been tested",
                "Deployment Plan Ready - Deployment steps documented",
                "Stakeholder Approval - (If required) Stakeholders signed off"
            ]
        }
    }

    print("\n" + "="*70)
    print("VERIFICATION CHECKLIST")
    print("="*70 + "\n")

    # If phase specified, show only that phase
    if phase and phase in checklists:
        phases_to_show = [phase]
    else:
        phases_to_show = ["design", "implementation", "integration", "production"]

    for phase_name in phases_to_show:
        if phase_name not in checklists:
            continue

        checklist = checklists[phase_name]
        print(f"{checklist['name']}")
        print("-" * len(checklist['name']))

        for i, item in enumerate(checklist['items'], 1):
            print(f"  [ ] {i}. {item}")

        print()

    print("="*70)
    print("\nFor detailed workflow, see: docs/VERIFICATION_WORKFLOW.md")
    print("To run verification: python scripts/verify_implementation.py --strict")
    print("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Verify implementation completeness")
    parser.add_argument("--strict", action="store_true", help="Fail on any error")
    parser.add_argument("--report", type=Path, help="Output JSON report to file")
    parser.add_argument("--markdown", type=Path, help="Output Markdown report to file")
    parser.add_argument("--min-tests", type=int, default=0, help="Minimum expected test count")
    parser.add_argument("--checklist", action="store_true", help="Print verification checklist")
    parser.add_argument("--phase", type=str, choices=["design", "implementation", "integration", "production"],
                        help="Show checklist for specific phase only")

    args = parser.parse_args()

    # If --checklist flag is set, print checklist and exit
    if args.checklist:
        print_checklist(phase=args.phase)
        return 0

    # Get project root (parent of scripts directory)
    project_root = Path(__file__).parent.parent.resolve()

    # Create verification suite
    suite = VerificationSuite(project_root)

    # Run verifications
    print("Running implementation verification...")
    print(f"Project root: {project_root}\n")

    print("1. Verifying directory structure...")
    suite.verify_directory_structure(get_expected_directories())

    print("2. Verifying file existence...")
    suite.verify_files(get_expected_files())

    print("3. Collecting and counting tests...")
    suite.verify_tests(min_expected_tests=args.min_tests)

    print("4. Validating Python syntax...")
    python_files = [f for f in get_expected_files() if f.endswith('.py')]
    suite.verify_syntax(python_files)

    print("5. Validating imports...")
    suite.verify_imports(get_expected_modules())

    # Get summary
    summary = suite.get_summary()

    # Generate reports
    Reporter.print_console_report(suite.results, summary)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        Reporter.generate_json_report(suite.results, summary, args.report)
        print(f"JSON report written to: {args.report}")

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown_content = Reporter.generate_markdown_report(suite.results, summary)
        with open(args.markdown, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        print(f"Markdown report written to: {args.markdown}")

    # Determine exit code
    if not summary['all_passed']:
        if args.strict:
            print("VERIFICATION FAILED (strict mode)")
            return 1
        else:
            print("VERIFICATION COMPLETED WITH FAILURES")
            return 1
    else:
        print("VERIFICATION PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
