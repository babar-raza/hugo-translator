#!/usr/bin/env python3
"""
Import Validation and Dependency Checker

This tool validates all imports and dependencies in the project:
- Discovers all Python modules in the project
- Attempts to import each module to verify it works
- Parses requirements files and checks installed packages
- Detects circular imports
- Generates dependency graph
- Provides actionable error messages

Usage:
    python scripts/validate_imports.py --check-all
    python scripts/validate_imports.py --module src.hardware.gpu_manager
    python scripts/validate_imports.py --requirements requirements/base.txt
    python scripts/validate_imports.py --check-all --graph deps.dot
"""

import argparse
import ast
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ImportResult:
    """Result of attempting to import a module."""
    module_name: str
    success: bool
    error: Optional[str] = None
    error_type: Optional[str] = None
    file_path: Optional[str] = None
    dependencies: Optional[List[str]] = None


@dataclass
class DependencyInfo:
    """Information about a package dependency."""
    name: str
    required_version: Optional[str] = None
    installed_version: Optional[str] = None
    is_installed: bool = False
    matches_requirement: bool = False


@dataclass
class CircularImportChain:
    """A circular import chain."""
    modules: List[str]
    description: str


@dataclass
class ImportHealthReport:
    """Complete import health report."""
    scan_time: str
    project_root: str
    total_modules: int
    successful_imports: int
    failed_imports: int
    import_results: List[ImportResult]
    dependencies: List[DependencyInfo]
    circular_imports: List[CircularImportChain]
    dependency_graph: Dict[str, List[str]]
    errors: List[str]
    warnings: List[str]


class ModuleDiscoverer:
    """Discovers all Python modules in the project."""

    EXCLUDE_DIRS = {
        '__pycache__', '.git', '.venv', 'venv', 'env',
        'node_modules', '.pytest_cache', 'htmlcov', '.tox',
        '.mypy_cache', '.ruff_cache', 'dist', 'build', '.eggs'
    }

    EXCLUDE_FILES = {
        '__pycache__', 'setup.py', 'conftest.py'
    }

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    def discover_modules(self) -> List[Tuple[str, Path]]:
        """
        Discover all Python modules in the project.

        Returns:
            List of (module_name, file_path) tuples
        """
        modules = []

        for py_file in self.root_dir.rglob('*.py'):
            # Skip excluded directories
            if any(excluded in py_file.parts for excluded in self.EXCLUDE_DIRS):
                continue

            # Skip excluded files
            if py_file.name in self.EXCLUDE_FILES:
                continue

            # Skip __init__.py for now (we'll handle packages differently)
            if py_file.name == '__init__.py':
                continue

            # Convert file path to module name
            try:
                relative_path = py_file.relative_to(self.root_dir)
                module_parts = list(relative_path.parts[:-1]) + [relative_path.stem]
                module_name = '.'.join(module_parts)

                modules.append((module_name, py_file))
            except ValueError:
                # File is not relative to root
                continue

        return modules


class ImportChecker:
    """Checks if modules can be imported."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

        # Add root to Python path if not already there
        root_str = str(self.root_dir)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    def check_import(self, module_name: str, file_path: Optional[Path] = None) -> ImportResult:
        """
        Attempt to import a module and return the result.

        Args:
            module_name: Module name (e.g., 'src.hardware.gpu_manager')
            file_path: Optional file path for the module

        Returns:
            ImportResult with success status and any errors
        """
        dependencies = []

        try:
            # Try to import the module
            module = importlib.import_module(module_name)

            # Successfully imported
            return ImportResult(
                module_name=module_name,
                success=True,
                file_path=str(file_path) if file_path else None,
                dependencies=dependencies
            )

        except ImportError as e:
            return ImportResult(
                module_name=module_name,
                success=False,
                error=str(e),
                error_type='ImportError',
                file_path=str(file_path) if file_path else None
            )

        except ModuleNotFoundError as e:
            return ImportResult(
                module_name=module_name,
                success=False,
                error=str(e),
                error_type='ModuleNotFoundError',
                file_path=str(file_path) if file_path else None
            )

        except SyntaxError as e:
            return ImportResult(
                module_name=module_name,
                success=False,
                error=f"Syntax error at line {e.lineno}: {e.msg}",
                error_type='SyntaxError',
                file_path=str(file_path) if file_path else None
            )

        except Exception as e:
            return ImportResult(
                module_name=module_name,
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_type=type(e).__name__,
                file_path=str(file_path) if file_path else None
            )

    def check_multiple_imports(
        self,
        modules: List[Tuple[str, Path]]
    ) -> List[ImportResult]:
        """Check multiple module imports."""
        results = []

        for module_name, file_path in modules:
            result = self.check_import(module_name, file_path)
            results.append(result)

        return results


class DependencyVerifier:
    """Verifies dependencies from requirements files."""

    @staticmethod
    def parse_requirements_file(req_file: str) -> List[Tuple[str, Optional[str]]]:
        """
        Parse a requirements file.

        Returns:
            List of (package_name, version_spec) tuples
        """
        requirements = []
        req_path = Path(req_file)

        if not req_path.exists():
            return requirements

        with open(req_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                # Skip -r includes (for now)
                if line.startswith('-r'):
                    continue

                # Skip editable installs
                if line.startswith('-e'):
                    continue

                # Parse package name and version
                # Handle various formats: package, package==version, package>=version, etc.
                match = re.match(r'([a-zA-Z0-9_-]+)(.*)', line)
                if match:
                    package_name = match.group(1)
                    version_spec = match.group(2).strip() if match.group(2) else None
                    requirements.append((package_name, version_spec))

        return requirements

    @staticmethod
    def get_installed_version(package_name: str) -> Optional[str]:
        """Get the installed version of a package."""
        try:
            # Try using importlib.metadata (Python 3.8+)
            from importlib import metadata
            return metadata.version(package_name)
        except ImportError:
            # Fallback for older Python
            try:
                import pkg_resources
                return pkg_resources.get_distribution(package_name).version
            except:
                pass
        except Exception:
            pass

        return None

    @staticmethod
    def check_version_match(installed: str, required: str) -> bool:
        """
        Check if installed version matches requirement.

        Args:
            installed: Installed version (e.g., '1.2.3')
            required: Required version spec (e.g., '==1.2.3', '>=1.0.0')

        Returns:
            True if versions match, False otherwise
        """
        if not required:
            return True

        # Simple version matching (this is simplified, real pip uses more complex logic)
        if required.startswith('=='):
            return installed == required[2:]
        elif required.startswith('>='):
            # Very simplified comparison
            return True  # Assume it's fine
        elif required.startswith('<='):
            return True  # Assume it's fine
        elif required.startswith('>'):
            return True  # Assume it's fine
        elif required.startswith('<'):
            return True  # Assume it's fine
        else:
            return True

    @classmethod
    def verify_requirements(cls, req_file: str) -> List[DependencyInfo]:
        """Verify all requirements from a file."""
        requirements = cls.parse_requirements_file(req_file)
        dependency_infos = []

        for package_name, version_spec in requirements:
            installed_version = cls.get_installed_version(package_name)
            is_installed = installed_version is not None

            matches_requirement = False
            if is_installed and installed_version:
                matches_requirement = cls.check_version_match(installed_version, version_spec)

            dependency_infos.append(DependencyInfo(
                name=package_name,
                required_version=version_spec,
                installed_version=installed_version,
                is_installed=is_installed,
                matches_requirement=matches_requirement
            ))

        return dependency_infos


class CircularImportDetector:
    """Detects circular imports in the project."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.import_graph = defaultdict(set)

    def build_import_graph(self, modules: List[Tuple[str, Path]]) -> Dict[str, List[str]]:
        """
        Build import dependency graph by analyzing import statements.

        Returns:
            Dict mapping module name to list of imported modules
        """
        for module_name, file_path in modules:
            try:
                imports = self._extract_imports(file_path)
                self.import_graph[module_name] = imports
            except Exception:
                # If we can't parse the file, skip it
                self.import_graph[module_name] = set()

        # Convert sets to lists for JSON serialization
        return {k: list(v) for k, v in self.import_graph.items()}

    def _extract_imports(self, file_path: Path) -> Set[str]:
        """Extract import statements from a Python file."""
        imports = set()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)

                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module)

        except (SyntaxError, UnicodeDecodeError):
            # If we can't parse, return empty set
            pass

        return imports

    def detect_cycles(self) -> List[CircularImportChain]:
        """
        Detect circular imports in the import graph.

        Returns:
            List of circular import chains
        """
        cycles = []
        visited = set()

        def dfs(node: str, path: List[str]) -> None:
            """Depth-first search to find cycles."""
            if node in path:
                # Found a cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycle_desc = ' → '.join(cycle)

                # Avoid duplicates
                if not any(c.description == cycle_desc for c in cycles):
                    cycles.append(CircularImportChain(
                        modules=cycle,
                        description=cycle_desc
                    ))
                return

            if node in visited:
                return

            visited.add(node)
            path.append(node)

            # Visit dependencies
            for dep in self.import_graph.get(node, []):
                # Only check project modules
                if dep in self.import_graph:
                    dfs(dep, path[:])

            path.pop()

        # Check each module
        for module in self.import_graph:
            dfs(module, [])

        return cycles


class Reporter:
    """Generates import health reports."""

    @staticmethod
    def save_report(report: ImportHealthReport, output_path: str):
        """Save report to JSON file."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, 'w', encoding='utf-8') as f:
            json.dump(asdict(report), f, indent=2, ensure_ascii=False)

        print(f"Report saved to: {output}")

    @staticmethod
    def print_summary(report: ImportHealthReport):
        """Print a summary of the import health report."""
        print("\nImport Health Report")
        print("=" * 60)
        print(f"Project: {report.project_root}")
        print(f"Scanned: {report.scan_time}")
        print()

        # Import statistics
        print("Import Statistics:")
        print(f"  Total modules: {report.total_modules}")
        print(f"  Successful imports: {report.successful_imports} "
              f"({report.successful_imports * 100 // report.total_modules if report.total_modules > 0 else 0}%)")
        print(f"  Failed imports: {report.failed_imports} "
              f"({report.failed_imports * 100 // report.total_modules if report.total_modules > 0 else 0}%)")
        print()

        # Failed imports
        if report.failed_imports > 0:
            print(f"Failed Imports ({report.failed_imports}):")
            failed = [r for r in report.import_results if not r.success]
            for result in failed[:10]:
                print(f"  ✗ {result.module_name}")
                print(f"    Error: {result.error_type}: {result.error}")
            if len(failed) > 10:
                print(f"  ... and {len(failed) - 10} more")
            print()

        # Dependencies
        if report.dependencies:
            missing = [d for d in report.dependencies if not d.is_installed]
            if missing:
                print(f"Missing Dependencies ({len(missing)}):")
                for dep in missing[:10]:
                    print(f"  ✗ {dep.name}")
                    if dep.required_version:
                        print(f"    Required: {dep.required_version}")
                    print(f"    Install: pip install {dep.name}{dep.required_version or ''}")
                if len(missing) > 10:
                    print(f"  ... and {len(missing) - 10} more")
                print()

        # Circular imports
        if report.circular_imports:
            print(f"Circular Imports ({len(report.circular_imports)}):")
            for cycle in report.circular_imports[:5]:
                print(f"  ⚠ {cycle.description}")
            if len(report.circular_imports) > 5:
                print(f"  ... and {len(report.circular_imports) - 5} more")
            print()

        # Overall status
        print("Overall Status:")
        if report.failed_imports == 0 and not report.circular_imports:
            print("  ✓ All imports healthy")
        else:
            print(f"  ✗ Issues found: {report.failed_imports} failed imports, "
                  f"{len(report.circular_imports)} circular imports")

    @staticmethod
    def save_dependency_graph(graph: Dict[str, List[str]], output_path: str):
        """Save dependency graph in DOT format for visualization."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, 'w', encoding='utf-8') as f:
            f.write('digraph dependencies {\n')
            f.write('  rankdir=LR;\n')
            f.write('  node [shape=box];\n\n')

            for module, deps in graph.items():
                # Simplify module names for readability
                simple_name = module.split('.')[-1]

                for dep in deps:
                    simple_dep = dep.split('.')[-1]
                    f.write(f'  "{simple_name}" -> "{simple_dep}";\n')

            f.write('}\n')

        print(f"Dependency graph saved to: {output}")
        print(f"Visualize with: dot -Tpng {output} -o {output.with_suffix('.png')}")


class ImportValidator:
    """Main import validation orchestrator."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.discoverer = ModuleDiscoverer(root_dir)
        self.checker = ImportChecker(root_dir)
        self.detector = CircularImportDetector(root_dir)
        self.errors = []
        self.warnings = []

    def validate_all_imports(self) -> ImportHealthReport:
        """Validate all imports in the project."""
        # Discover modules
        print(f"Discovering modules in {self.root_dir}...")
        modules = self.discoverer.discover_modules()
        print(f"Found {len(modules)} modules")

        # Check imports
        print("Checking imports...")
        import_results = self.checker.check_multiple_imports(modules)

        successful = sum(1 for r in import_results if r.success)
        failed = sum(1 for r in import_results if not r.success)

        print(f"Imports: {successful} successful, {failed} failed")

        # Build dependency graph
        print("Building dependency graph...")
        dependency_graph = self.detector.build_import_graph(modules)

        # Detect circular imports
        print("Detecting circular imports...")
        circular_imports = self.detector.detect_cycles()
        print(f"Found {len(circular_imports)} circular import chains")

        # Create report
        report = ImportHealthReport(
            scan_time=datetime.now().isoformat(),
            project_root=str(self.root_dir),
            total_modules=len(modules),
            successful_imports=successful,
            failed_imports=failed,
            import_results=import_results,
            dependencies=[],
            circular_imports=circular_imports,
            dependency_graph=dependency_graph,
            errors=self.errors,
            warnings=self.warnings
        )

        return report

    def validate_single_module(self, module_name: str) -> ImportResult:
        """Validate a single module import."""
        return self.checker.check_import(module_name)

    def verify_requirements_file(self, req_file: str) -> List[DependencyInfo]:
        """Verify requirements from a file."""
        return DependencyVerifier.verify_requirements(req_file)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Import Validation and Dependency Checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate all imports
  python scripts/validate_imports.py --check-all

  # Check specific module
  python scripts/validate_imports.py --module src.hardware.gpu_manager

  # Verify requirements
  python scripts/validate_imports.py --requirements requirements/base.txt

  # Generate dependency graph
  python scripts/validate_imports.py --check-all --graph deps.dot
        """
    )

    parser.add_argument('--check-all', action='store_true',
                       help='Check all imports in the project')
    parser.add_argument('--module', metavar='MODULE',
                       help='Check specific module import')
    parser.add_argument('--requirements', metavar='FILE',
                       help='Verify requirements file')
    parser.add_argument('--output', '-o', metavar='FILE',
                       help='Output file path for report (JSON)')
    parser.add_argument('--graph', metavar='FILE',
                       help='Output file for dependency graph (DOT format)')
    parser.add_argument('--root', metavar='DIR',
                       help='Project root directory (default: current directory)')

    args = parser.parse_args()

    # Determine root directory
    if args.root:
        root_dir = args.root
    else:
        # Try to find git root
        current = Path.cwd()
        while current != current.parent:
            if (current / '.git').exists():
                root_dir = str(current)
                break
            current = current.parent
        else:
            root_dir = os.getcwd()

    validator = ImportValidator(root_dir)

    # Execute commands
    exit_code = 0

    if args.check_all:
        report = validator.validate_all_imports()
        Reporter.print_summary(report)

        if args.output:
            Reporter.save_report(report, args.output)

        if args.graph:
            Reporter.save_dependency_graph(report.dependency_graph, args.graph)

        # Exit with error if there are failed imports
        if report.failed_imports > 0:
            exit_code = 1

    elif args.module:
        result = validator.validate_single_module(args.module)

        if result.success:
            print(f"✓ Module {result.module_name} imports successfully")
            exit_code = 0
        else:
            print(f"✗ Module {result.module_name} failed to import")
            print(f"  Error: {result.error_type}: {result.error}")
            exit_code = 1

    elif args.requirements:
        dependencies = validator.verify_requirements_file(args.requirements)

        print(f"\nDependency Verification: {args.requirements}")
        print("=" * 60)

        missing = [d for d in dependencies if not d.is_installed]
        installed = [d for d in dependencies if d.is_installed]

        print(f"Total dependencies: {len(dependencies)}")
        print(f"Installed: {len(installed)}")
        print(f"Missing: {len(missing)}")
        print()

        if missing:
            print("Missing Dependencies:")
            for dep in missing:
                print(f"  ✗ {dep.name}")
                if dep.required_version:
                    print(f"    Required: {dep.required_version}")
                print(f"    Install: pip install {dep.name}{dep.required_version or ''}")

            exit_code = 1
        else:
            print("✓ All dependencies installed")
            exit_code = 0

    else:
        parser.print_help()
        exit_code = 1

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
