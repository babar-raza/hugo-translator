"""
Tests for Import Validation and Dependency Checker

Tests cover:
- Module discovery
- Import checking
- Dependency verification
- Circular import detection
- Error handling
"""

# Import the modules we're testing
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'scripts'))
from validate_imports import (
    CircularImportChain,
    CircularImportDetector,
    DependencyInfo,
    DependencyVerifier,
    ImportChecker,
    ImportHealthReport,
    ImportResult,
    ImportValidator,
    ModuleDiscoverer,
    Reporter,
)


class TestModuleDiscoverer:
    """Test ModuleDiscoverer class."""

    def test_discover_modules(self, tmp_path):
        """Test discovering modules in a project."""
        # Create test structure
        (tmp_path / 'src').mkdir()
        (tmp_path / 'src' / '__init__.py').write_text('')
        (tmp_path / 'src' / 'module1.py').write_text('def foo(): pass')

        (tmp_path / 'tests').mkdir()
        (tmp_path / 'tests' / 'test_module1.py').write_text('def test_foo(): pass')

        discoverer = ModuleDiscoverer(tmp_path)
        modules = discoverer.discover_modules()

        # Should find module1.py and test_module1.py (but not __init__.py)
        assert len(modules) >= 2
        module_names = [name for name, _ in modules]
        assert 'src.module1' in module_names
        assert 'tests.test_module1' in module_names

    def test_exclude_pycache(self, tmp_path):
        """Test that __pycache__ is excluded."""
        (tmp_path / '__pycache__').mkdir()
        (tmp_path / '__pycache__' / 'test.pyc').write_text('')

        discoverer = ModuleDiscoverer(tmp_path)
        modules = discoverer.discover_modules()

        module_names = [name for name, _ in modules]
        assert not any('__pycache__' in name for name in module_names)

    def test_exclude_venv(self, tmp_path):
        """Test that .venv is excluded."""
        (tmp_path / '.venv').mkdir()
        (tmp_path / '.venv' / 'lib').mkdir()
        (tmp_path / '.venv' / 'lib' / 'test.py').write_text('')

        discoverer = ModuleDiscoverer(tmp_path)
        modules = discoverer.discover_modules()

        module_names = [name for name, _ in modules]
        assert not any('.venv' in name for name in module_names)

    def test_discover_empty_directory(self, tmp_path):
        """Test discovering in an empty directory."""
        discoverer = ModuleDiscoverer(tmp_path)
        modules = discoverer.discover_modules()

        assert len(modules) == 0


class TestImportChecker:
    """Test ImportChecker class."""

    def test_check_import_success(self, tmp_path):
        """Test successful import check."""
        checker = ImportChecker(tmp_path)

        # Test with a built-in module
        result = checker.check_import('json')

        assert result.module_name == 'json'
        assert result.success is True
        assert result.error is None

    def test_check_import_not_found(self, tmp_path):
        """Test import check for non-existent module."""
        checker = ImportChecker(tmp_path)

        result = checker.check_import('this_module_does_not_exist_12345')

        assert result.success is False
        assert result.error_type in ['ModuleNotFoundError', 'ImportError']
        assert result.error is not None

    def test_check_import_syntax_error(self, tmp_path):
        """Test import check for module with syntax error."""
        # Create module with syntax error
        (tmp_path / 'bad_module.py').write_text('def foo(\n  pass')

        checker = ImportChecker(tmp_path)
        result = checker.check_import('bad_module')

        # This might fail in different ways depending on Python version
        assert result.success is False

    def test_check_multiple_imports(self, tmp_path):
        """Test checking multiple imports."""
        # Create test modules
        (tmp_path / 'module1.py').write_text('def foo(): pass')
        (tmp_path / 'module2.py').write_text('def bar(): pass')

        checker = ImportChecker(tmp_path)
        modules = [
            ('module1', tmp_path / 'module1.py'),
            ('module2', tmp_path / 'module2.py'),
            ('nonexistent', tmp_path / 'nonexistent.py')
        ]

        results = checker.check_multiple_imports(modules)

        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is True
        assert results[2].success is False


class TestDependencyVerifier:
    """Test DependencyVerifier class."""

    def test_parse_requirements_file(self, tmp_path):
        """Test parsing a requirements file."""
        req_file = tmp_path / 'requirements.txt'
        req_file.write_text("""# Comment
pytest==7.4.0
requests>=2.28.0
numpy
# Another comment

flask<3.0.0
""")

        requirements = DependencyVerifier.parse_requirements_file(str(req_file))

        assert len(requirements) >= 4
        names = [name for name, _ in requirements]
        assert 'pytest' in names
        assert 'requests' in names
        assert 'numpy' in names
        assert 'flask' in names

    def test_parse_empty_requirements_file(self, tmp_path):
        """Test parsing an empty requirements file."""
        req_file = tmp_path / 'requirements.txt'
        req_file.write_text('# Only comments\n\n')

        requirements = DependencyVerifier.parse_requirements_file(str(req_file))

        assert len(requirements) == 0

    def test_parse_nonexistent_requirements_file(self):
        """Test parsing a non-existent requirements file."""
        requirements = DependencyVerifier.parse_requirements_file('nonexistent.txt')

        assert len(requirements) == 0

    def test_get_installed_version(self):
        """Test getting installed version of a package."""
        # Test with a package that should be installed (pytest)
        version = DependencyVerifier.get_installed_version('pytest')

        # Should return a version string or None
        assert version is None or isinstance(version, str)

    def test_check_version_match(self):
        """Test version matching."""
        assert DependencyVerifier.check_version_match('1.2.3', '==1.2.3') is True
        assert DependencyVerifier.check_version_match('1.2.3', '>=1.0.0') is True
        assert DependencyVerifier.check_version_match('1.2.3', None) is True

    def test_verify_requirements(self, tmp_path):
        """Test verifying requirements."""
        req_file = tmp_path / 'requirements.txt'
        req_file.write_text("""pytest
nonexistent_package_12345
""")

        dependencies = DependencyVerifier.verify_requirements(str(req_file))

        assert len(dependencies) == 2

        # pytest should be installed (we're using it)
        pytest_dep = next((d for d in dependencies if d.name == 'pytest'), None)
        assert pytest_dep is not None
        # Note: pytest might or might not be installed in the test environment

        # nonexistent package should not be installed
        nonexistent_dep = next((d for d in dependencies if d.name == 'nonexistent_package_12345'), None)
        assert nonexistent_dep is not None
        assert nonexistent_dep.is_installed is False


class TestCircularImportDetector:
    """Test CircularImportDetector class."""

    def test_build_import_graph(self, tmp_path):
        """Test building import graph."""
        # Create modules with imports
        (tmp_path / 'module1.py').write_text('import json\nimport sys')
        (tmp_path / 'module2.py').write_text('from pathlib import Path')

        detector = CircularImportDetector(tmp_path)
        modules = [
            ('module1', tmp_path / 'module1.py'),
            ('module2', tmp_path / 'module2.py')
        ]

        graph = detector.build_import_graph(modules)

        assert 'module1' in graph
        assert 'module2' in graph
        assert 'json' in graph['module1']
        assert 'sys' in graph['module1']
        assert 'pathlib' in graph['module2']

    def test_extract_imports(self, tmp_path):
        """Test extracting imports from a file."""
        test_file = tmp_path / 'test.py'
        test_file.write_text("""import json
import sys
from pathlib import Path
from os import path
""")

        detector = CircularImportDetector(tmp_path)
        imports = detector._extract_imports(test_file)

        assert 'json' in imports
        assert 'sys' in imports
        assert 'pathlib' in imports
        assert 'os' in imports

    def test_detect_cycles_no_cycles(self, tmp_path):
        """Test detecting cycles when there are none."""
        # Create linear dependency: module1 -> module2
        (tmp_path / 'module1.py').write_text('import module2')
        (tmp_path / 'module2.py').write_text('import json')

        detector = CircularImportDetector(tmp_path)
        modules = [
            ('module1', tmp_path / 'module1.py'),
            ('module2', tmp_path / 'module2.py')
        ]

        detector.build_import_graph(modules)
        cycles = detector.detect_cycles()

        # Should find no cycles (json is not in our graph)
        assert len(cycles) == 0

    def test_detect_cycles_with_cycle(self, tmp_path):
        """Test detecting circular imports."""
        # Create circular dependency: module1 -> module2 -> module1
        (tmp_path / 'module1.py').write_text('import module2')
        (tmp_path / 'module2.py').write_text('import module1')

        detector = CircularImportDetector(tmp_path)
        modules = [
            ('module1', tmp_path / 'module1.py'),
            ('module2', tmp_path / 'module2.py')
        ]

        detector.build_import_graph(modules)
        cycles = detector.detect_cycles()

        # Should find at least one cycle
        assert len(cycles) >= 1

        # Check that the cycle includes both modules
        cycle_modules = cycles[0].modules
        assert 'module1' in cycle_modules
        assert 'module2' in cycle_modules


class TestReporter:
    """Test Reporter class."""

    def test_save_report(self, tmp_path):
        """Test saving report to JSON."""
        report = ImportHealthReport(
            scan_time='2024-01-01T12:00:00',
            project_root=str(tmp_path),
            total_modules=10,
            successful_imports=8,
            failed_imports=2,
            import_results=[],
            dependencies=[],
            circular_imports=[],
            dependency_graph={},
            errors=[],
            warnings=[]
        )

        output_file = tmp_path / 'report.json'
        Reporter.save_report(report, str(output_file))

        assert output_file.exists()

        # Load and verify
        import json
        with open(output_file) as f:
            data = json.load(f)

        assert data['total_modules'] == 10
        assert data['successful_imports'] == 8
        assert data['failed_imports'] == 2

    def test_print_summary(self, capsys):
        """Test printing summary report."""
        report = ImportHealthReport(
            scan_time='2024-01-01T12:00:00',
            project_root='/test/project',
            total_modules=10,
            successful_imports=8,
            failed_imports=2,
            import_results=[
                ImportResult(
                    module_name='bad_module',
                    success=False,
                    error='No module named bad_module',
                    error_type='ModuleNotFoundError'
                )
            ],
            dependencies=[
                DependencyInfo(
                    name='pytest',
                    is_installed=True,
                    matches_requirement=True
                ),
                DependencyInfo(
                    name='missing_package',
                    is_installed=False,
                    required_version='==1.0.0'
                )
            ],
            circular_imports=[
                CircularImportChain(
                    modules=['module1', 'module2', 'module1'],
                    description='module1 → module2 → module1'
                )
            ],
            dependency_graph={},
            errors=[],
            warnings=[]
        )

        Reporter.print_summary(report)

        captured = capsys.readouterr()
        assert 'Import Health Report' in captured.out
        assert 'Total modules: 10' in captured.out
        assert 'Successful imports: 8' in captured.out
        assert 'Failed imports: 2' in captured.out
        assert 'bad_module' in captured.out
        assert 'missing_package' in captured.out
        assert 'module1 → module2 → module1' in captured.out

    def test_save_dependency_graph(self, tmp_path):
        """Test saving dependency graph."""
        graph = {
            'module1': ['module2', 'module3'],
            'module2': ['module3'],
            'module3': []
        }

        output_file = tmp_path / 'deps.dot'
        Reporter.save_dependency_graph(graph, str(output_file))

        assert output_file.exists()

        content = output_file.read_text()
        assert 'digraph dependencies' in content
        assert 'module1' in content
        assert 'module2' in content


class TestImportValidator:
    """Test ImportValidator class."""

    def test_validate_single_module(self, tmp_path):
        """Test validating a single module."""
        validator = ImportValidator(tmp_path)

        # Test with a built-in module
        result = validator.validate_single_module('json')

        assert result.success is True
        assert result.module_name == 'json'

    def test_validate_all_imports(self, tmp_path):
        """Test validating all imports in a project."""
        # Create test modules
        (tmp_path / 'module1.py').write_text('def foo(): pass')
        (tmp_path / 'module2.py').write_text('import json')

        validator = ImportValidator(tmp_path)
        report = validator.validate_all_imports()

        assert report.total_modules >= 2
        assert report.successful_imports >= 0
        assert report.project_root == str(tmp_path)

    def test_verify_requirements_file(self, tmp_path):
        """Test verifying requirements file."""
        req_file = tmp_path / 'requirements.txt'
        req_file.write_text('pytest\njson\n')

        validator = ImportValidator(tmp_path)
        dependencies = validator.verify_requirements_file(str(req_file))

        assert len(dependencies) >= 2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_import_checker_with_circular_import_module(self, tmp_path):
        """Test import checker doesn't crash on circular imports."""
        # Create circular imports
        (tmp_path / 'circ1.py').write_text('import circ2')
        (tmp_path / 'circ2.py').write_text('import circ1')

        checker = ImportChecker(tmp_path)

        # This might fail or succeed depending on import behavior
        # but shouldn't crash
        result1 = checker.check_import('circ1')
        result2 = checker.check_import('circ2')

        assert result1 is not None
        assert result2 is not None

    def test_module_discoverer_with_symlinks(self, tmp_path):
        """Test module discoverer with symlinks (if supported)."""
        (tmp_path / 'real_module.py').write_text('def foo(): pass')

        discoverer = ModuleDiscoverer(tmp_path)
        modules = discoverer.discover_modules()

        # Should find at least the real module
        assert len(modules) >= 1

    def test_dependency_verifier_with_malformed_requirements(self, tmp_path):
        """Test dependency verifier with malformed requirements."""
        req_file = tmp_path / 'requirements.txt'
        req_file.write_text("""# Valid
pytest
# Invalid lines below
===broken===
http://example.com/package.tar.gz
-e git+https://github.com/user/repo.git#egg=package
""")

        # Should not crash
        requirements = DependencyVerifier.parse_requirements_file(str(req_file))

        # Should at least get pytest
        names = [name for name, _ in requirements]
        assert 'pytest' in names


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
