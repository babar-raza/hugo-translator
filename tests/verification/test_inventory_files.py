"""
Tests for File Inventory and Verification Tool

Tests cover:
- File scanning and categorization
- Line counting (code, comments, blank)
- Inventory creation and loading
- Inventory comparison and diff
- Edge cases (empty files, binary files, symlinks)
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Import the modules we're testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'scripts'))
from inventory_files import (
    FileInfo,
    FileScanner,
    Inventory,
    InventoryManager,
    InventoryStats,
    LineCounter,
    Reporter,
)


class TestFileScanner:
    """Test FileScanner class."""

    def test_should_exclude_pycache(self, tmp_path):
        """Test that __pycache__ directories are excluded."""
        scanner = FileScanner(tmp_path)
        pycache_path = tmp_path / '__pycache__' / 'test.pyc'
        assert scanner.should_exclude(pycache_path)

    def test_should_exclude_git(self, tmp_path):
        """Test that .git directories are excluded."""
        scanner = FileScanner(tmp_path)
        git_path = tmp_path / '.git' / 'config'
        assert scanner.should_exclude(git_path)

    def test_should_not_exclude_normal_files(self, tmp_path):
        """Test that normal files are not excluded."""
        scanner = FileScanner(tmp_path)
        normal_path = tmp_path / 'src' / 'test.py'
        assert not scanner.should_exclude(normal_path)

    def test_categorize_scripts(self, tmp_path):
        """Test that files in scripts/ are categorized correctly."""
        scanner = FileScanner(tmp_path)
        script_path = tmp_path / 'scripts' / 'test.py'
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.touch()
        category = scanner.categorize_file(script_path)
        assert category == 'scripts'

    def test_categorize_tests(self, tmp_path):
        """Test that files in tests/ are categorized correctly."""
        scanner = FileScanner(tmp_path)
        test_path = tmp_path / 'tests' / 'test_something.py'
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.touch()
        category = scanner.categorize_file(test_path)
        assert category == 'tests'

    def test_categorize_src(self, tmp_path):
        """Test that files in src/ are categorized correctly."""
        scanner = FileScanner(tmp_path)
        src_path = tmp_path / 'src' / 'module.py'
        src_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.touch()
        category = scanner.categorize_file(src_path)
        assert category == 'src'

    def test_categorize_docs(self, tmp_path):
        """Test that files in docs/ are categorized correctly."""
        scanner = FileScanner(tmp_path)
        doc_path = tmp_path / 'docs' / 'README.md'
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.touch()
        category = scanner.categorize_file(doc_path)
        assert category == 'docs'

    def test_categorize_root(self, tmp_path):
        """Test that root files are categorized as root."""
        scanner = FileScanner(tmp_path)
        root_path = tmp_path / 'README.md'
        root_path.touch()
        category = scanner.categorize_file(root_path)
        assert category == 'root'

    def test_scan_finds_files(self, tmp_path):
        """Test that scan finds files in directory tree."""
        scanner = FileScanner(tmp_path)

        # Create some test files
        (tmp_path / 'scripts').mkdir()
        (tmp_path / 'scripts' / 'test.py').write_text('print("test")')
        (tmp_path / 'src').mkdir()
        (tmp_path / 'src' / 'module.py').write_text('def foo(): pass')

        files = scanner.scan()
        assert len(files) >= 2
        paths = [str(f[0].name) for f in files]
        assert 'test.py' in paths
        assert 'module.py' in paths


class TestLineCounter:
    """Test LineCounter class."""

    def test_count_empty_file(self, tmp_path):
        """Test counting lines in an empty file."""
        counter = LineCounter()
        empty_file = tmp_path / 'empty.py'
        empty_file.write_text('')

        total, code, comments, blank = counter.count_lines(empty_file)
        assert total == 0
        assert code == 0
        assert comments == 0
        assert blank == 0

    def test_count_python_code(self, tmp_path):
        """Test counting Python code lines."""
        counter = LineCounter()
        py_file = tmp_path / 'test.py'
        py_file.write_text("""# This is a comment
def foo():
    return 42

# Another comment
print("hello")
""")

        total, code, comments, blank = counter.count_lines(py_file)
        assert total == 6
        assert code == 3  # def foo, return 42, print("hello")
        assert comments == 2  # Two comment lines
        assert blank == 1  # One blank line

    def test_count_python_with_docstring(self, tmp_path):
        \"\"\"Test counting Python with docstrings.\"\"\"
        counter = LineCounter()
        py_file = tmp_path / 'test.py'
        py_file.write_text('''"""
This is a docstring.
"""
def foo():
    pass
''')

        total, code, comments, blank = counter.count_lines(py_file)
        assert total == 5
        assert comments >= 1  # At least the docstring start

    def test_count_blank_lines(self, tmp_path):
        """Test counting blank lines."""
        counter = LineCounter()
        py_file = tmp_path / 'test.py'
        py_file.write_text("""

def foo():

    pass

""")

        total, code, comments, blank = counter.count_lines(py_file)
        assert total == 7
        assert blank >= 3  # At least 3 blank lines

    def test_count_yaml_comments(self, tmp_path):
        """Test counting YAML comments."""
        counter = LineCounter()
        yaml_file = tmp_path / 'test.yaml'
        yaml_file.write_text("""# Comment
key: value
# Another comment
nested:
  key2: value2
""")

        total, code, comments, blank = counter.count_lines(yaml_file)
        assert total == 5
        assert comments == 2  # Two comment lines
        assert code == 3  # Three YAML lines

    def test_count_javascript_comments(self, tmp_path):
        """Test counting JavaScript comments."""
        counter = LineCounter()
        js_file = tmp_path / 'test.js'
        js_file.write_text("""// Single line comment
function foo() {
  return 42;
}
/* Multi-line
   comment */
const x = 10;
""")

        total, code, comments, blank = counter.count_lines(js_file)
        assert total == 7
        assert comments >= 2  # At least single-line and multi-line start

    def test_count_binary_file(self, tmp_path):
        """Test that binary files return zero counts."""
        counter = LineCounter()
        bin_file = tmp_path / 'test.bin'
        bin_file.write_bytes(b'\x00\x01\x02\x03')

        total, code, comments, blank = counter.count_lines(bin_file)
        assert total == 0
        assert code == 0


class TestInventoryManager:
    """Test InventoryManager class."""

    def test_create_inventory(self, tmp_path):
        """Test creating an inventory."""
        # Create some test files
        (tmp_path / 'scripts').mkdir()
        (tmp_path / 'scripts' / 'test.py').write_text('print("test")\n')
        (tmp_path / 'README.md').write_text('# Test\n')

        manager = InventoryManager(tmp_path)
        inventory = manager.create_inventory()

        assert inventory.project_root == str(tmp_path)
        assert inventory.stats.total_files >= 2
        assert inventory.stats.total_lines >= 2
        assert len(inventory.files) >= 2

    def test_save_and_load_inventory(self, tmp_path):
        """Test saving and loading inventory."""
        # Create inventory
        (tmp_path / 'src').mkdir()
        (tmp_path / 'src' / 'test.py').write_text('def foo(): pass\n')

        manager = InventoryManager(tmp_path)
        inventory = manager.create_inventory()

        # Save
        output_file = tmp_path / 'inventory.json'
        manager.save_inventory(inventory, str(output_file))

        assert output_file.exists()

        # Load
        loaded = manager.load_inventory(str(output_file))

        assert loaded.project_root == inventory.project_root
        assert loaded.stats.total_files == inventory.stats.total_files
        assert loaded.stats.total_lines == inventory.stats.total_lines

    def test_verify_inventory_success(self, tmp_path):
        """Test verifying inventory when all files exist."""
        # Create test files
        (tmp_path / 'test.py').write_text('print("test")\n')

        manager = InventoryManager(tmp_path)
        inventory = manager.create_inventory()

        # Save inventory
        inv_file = tmp_path / 'inventory.json'
        manager.save_inventory(inventory, str(inv_file))

        # Verify
        result = manager.verify_inventory(str(inv_file))
        assert result is True

    def test_verify_inventory_missing_file(self, tmp_path):
        """Test verifying inventory when files are missing."""
        # Create test file
        test_file = tmp_path / 'test.py'
        test_file.write_text('print("test")\n')

        manager = InventoryManager(tmp_path)
        inventory = manager.create_inventory()

        # Save inventory
        inv_file = tmp_path / 'inventory.json'
        manager.save_inventory(inventory, str(inv_file))

        # Delete the test file
        test_file.unlink()

        # Verify - should fail
        result = manager.verify_inventory(str(inv_file))
        assert result is False

    def test_compare_inventories_added(self, tmp_path):
        """Test comparing inventories with added files."""
        # Create baseline
        (tmp_path / 'test1.py').write_text('print("test1")\n')
        manager = InventoryManager(tmp_path)
        baseline = manager.create_inventory()
        baseline_file = tmp_path / 'baseline.json'
        manager.save_inventory(baseline, str(baseline_file))

        # Add a file
        (tmp_path / 'test2.py').write_text('print("test2")\n')
        current = manager.create_inventory()
        current_file = tmp_path / 'current.json'
        manager.save_inventory(current, str(current_file))

        # Compare
        diff = manager.compare_inventories(str(baseline_file), str(current_file))

        assert diff['changes']['added_files'] >= 1
        assert 'test2.py' in diff['added']

    def test_compare_inventories_removed(self, tmp_path):
        """Test comparing inventories with removed files."""
        # Create baseline
        test_file = tmp_path / 'test.py'
        test_file.write_text('print("test")\n')
        manager = InventoryManager(tmp_path)
        baseline = manager.create_inventory()
        baseline_file = tmp_path / 'baseline.json'
        manager.save_inventory(baseline, str(baseline_file))

        # Remove the file
        test_file.unlink()
        current = manager.create_inventory()
        current_file = tmp_path / 'current.json'
        manager.save_inventory(current, str(current_file))

        # Compare
        diff = manager.compare_inventories(str(baseline_file), str(current_file))

        assert diff['changes']['removed_files'] >= 1
        assert 'test.py' in diff['removed']

    def test_compare_inventories_modified(self, tmp_path):
        """Test comparing inventories with modified files."""
        # Create baseline
        test_file = tmp_path / 'test.py'
        test_file.write_text('print("test")\n')
        manager = InventoryManager(tmp_path)
        baseline = manager.create_inventory()
        baseline_file = tmp_path / 'baseline.json'
        manager.save_inventory(baseline, str(baseline_file))

        # Modify the file
        test_file.write_text('print("test")\nprint("more")\n')
        current = manager.create_inventory()
        current_file = tmp_path / 'current.json'
        manager.save_inventory(current, str(current_file))

        # Compare
        diff = manager.compare_inventories(str(baseline_file), str(current_file))

        assert diff['changes']['modified_files'] >= 1
        assert 'test.py' in diff['modified']

    def test_format_size(self):
        """Test size formatting."""
        manager = InventoryManager('.')

        assert manager._format_size(500) == '500.0 B'
        assert manager._format_size(1024) == '1.0 KB'
        assert manager._format_size(1024 * 1024) == '1.0 MB'
        assert manager._format_size(1024 * 1024 * 1024) == '1.0 GB'


class TestReporter:
    """Test Reporter class."""

    def test_generate_summary(self, tmp_path):
        """Test generating a summary report."""
        # Create a simple inventory
        files = [
            FileInfo(
                path='test.py',
                category='tests',
                size_bytes=100,
                size_human='100 B',
                total_lines=10,
                code_lines=7,
                comment_lines=2,
                blank_lines=1,
                modified_time='2024-01-01T12:00:00'
            )
        ]
        stats = InventoryStats(
            total_files=1,
            total_size_bytes=100,
            total_size_human='100 B',
            total_lines=10,
            total_code_lines=7,
            total_comment_lines=2,
            total_blank_lines=1,
            files_by_category={'tests': 1},
            lines_by_category={'tests': 10},
            scan_time='2024-01-01T12:00:00'
        )
        inventory = Inventory(
            project_root=str(tmp_path),
            files=files,
            stats=stats
        )

        summary = Reporter.generate_summary(inventory)

        assert 'File Inventory Summary' in summary
        assert 'Total files: 1' in summary
        assert 'Total lines: 10' in summary
        assert 'tests' in summary

    def test_generate_markdown(self, tmp_path):
        """Test generating a Markdown report."""
        files = [
            FileInfo(
                path='test.py',
                category='tests',
                size_bytes=100,
                size_human='100 B',
                total_lines=10,
                code_lines=7,
                comment_lines=2,
                blank_lines=1,
                modified_time='2024-01-01T12:00:00'
            )
        ]
        stats = InventoryStats(
            total_files=1,
            total_size_bytes=100,
            total_size_human='100 B',
            total_lines=10,
            total_code_lines=7,
            total_comment_lines=2,
            total_blank_lines=1,
            files_by_category={'tests': 1},
            lines_by_category={'tests': 10},
            scan_time='2024-01-01T12:00:00'
        )
        inventory = Inventory(
            project_root=str(tmp_path),
            files=files,
            stats=stats
        )

        markdown = Reporter.generate_markdown(inventory)

        assert '# File Inventory Report' in markdown
        assert '**Total files:**' in markdown
        assert '| Category | Files | Lines |' in markdown
        assert '| tests |' in markdown

    def test_print_diff(self, tmp_path, capsys):
        """Test printing a diff report."""
        diff = {
            'baseline': {
                'path': 'baseline.json',
                'total_files': 10,
                'total_lines': 100,
                'scan_time': '2024-01-01T12:00:00'
            },
            'current': {
                'path': 'current.json',
                'total_files': 12,
                'total_lines': 120,
                'scan_time': '2024-01-02T12:00:00'
            },
            'changes': {
                'added_files': 2,
                'removed_files': 0,
                'modified_files': 1,
                'unchanged_files': 9
            },
            'added': ['file1.py', 'file2.py'],
            'removed': [],
            'modified': ['file3.py']
        }

        Reporter.print_diff(diff)

        captured = capsys.readouterr()
        assert 'Inventory Comparison' in captured.out
        assert 'Added files: 2' in captured.out
        assert 'file1.py' in captured.out


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_scan_empty_directory(self, tmp_path):
        """Test scanning an empty directory."""
        empty_dir = tmp_path / 'empty'
        empty_dir.mkdir()

        scanner = FileScanner(empty_dir)
        files = scanner.scan()

        assert len(files) == 0

    def test_count_file_with_unicode(self, tmp_path):
        """Test counting file with unicode characters."""
        counter = LineCounter()
        unicode_file = tmp_path / 'unicode.py'
        unicode_file.write_text('# 日本語コメント\nprint("Hello 世界")\n', encoding='utf-8')

        total, code, comments, blank = counter.count_lines(unicode_file)
        assert total == 2
        assert code == 1
        assert comments == 1

    def test_inventory_with_no_files(self, tmp_path):
        """Test creating inventory with no files."""
        empty_dir = tmp_path / 'empty'
        empty_dir.mkdir()

        manager = InventoryManager(empty_dir)
        inventory = manager.create_inventory()

        assert inventory.stats.total_files == 0
        assert inventory.stats.total_lines == 0
        assert len(inventory.files) == 0

    def test_match_pattern_wildcard(self):
        """Test pattern matching with wildcards."""
        scanner = FileScanner('.')

        assert scanner._match_pattern('test.pyc', '*.pyc')
        assert scanner._match_pattern('file.pyc', '*.pyc')
        assert not scanner._match_pattern('test.py', '*.pyc')

        assert scanner._match_pattern('prefix_test', 'prefix_*')
        assert not scanner._match_pattern('test_prefix', 'prefix_*')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
