"""
Regression tests for CLI import chain without torch (TEST-006, TEST-011, TEST-012 fix).

Ensures that --help and --dry-run work in minimal environments without torch installed.
This prevents regression of the import chain failures fixed in Phase 1.
"""

import subprocess
import sys
from pathlib import Path

import pytest


def test_help_works_without_torch():
    """
    Test that --help works even if torch import is blocked.

    This simulates a minimal CI environment where torch is not available.
    The CLI should be able to show help without importing heavy ML dependencies.
    """
    # Use a subprocess to avoid polluting the current interpreter
    # We'll intercept torch imports to simulate it being unavailable
    test_script = """
import builtins
import sys

# Block torch imports
_orig_import = builtins.__import__

def _mock_import(name, *args, **kwargs):
    if name == 'torch' or name.startswith('torch.'):
        raise ModuleNotFoundError(f"No module named '{name}'")
    return _orig_import(name, *args, **kwargs)

builtins.__import__ = _mock_import

# Now try to run CLI --help
import runpy
sys.argv = ['src.cli', '--help']
try:
    runpy.run_module('src.cli', run_name='__main__')
except SystemExit as e:
    sys.exit(e.code)
"""

    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Should succeed (exit code 0)
    assert result.returncode == 0, (
        f"--help failed with torch blocked:\\nSTDOUT:\\n{result.stdout}\\nSTDERR:\\n{result.stderr}"
    )

    # Should display usage
    assert "usage:" in result.stdout.lower() or "Usage:" in result.stdout, "Help text not displayed"


def test_version_works_without_torch():
    """
    Test that --version works even if torch import is blocked.

    Version information should be available without loading ML dependencies.
    """
    test_script = """
import builtins
import sys

# Block torch imports
_orig_import = builtins.__import__

def _mock_import(name, *args, **kwargs):
    if name == 'torch' or name.startswith('torch.'):
        raise ModuleNotFoundError(f"No module named '{name}'")
    return _orig_import(name, *args, **kwargs)

builtins.__import__ = _mock_import

# Now try to run CLI --version
import runpy
sys.argv = ['src.cli', '--version']
try:
    runpy.run_module('src.cli', run_name='__main__')
except SystemExit as e:
    sys.exit(e.code)
"""

    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Should succeed (exit code 0)
    assert result.returncode == 0, (
        f"--version failed with torch blocked:\\n"
        f"STDOUT:\\n{result.stdout}\\n"
        f"STDERR:\\n{result.stderr}"
    )

    # Should display version
    assert "translate-hugo" in result.stdout or "version" in result.stdout.lower(), (
        "Version info not displayed"
    )


def test_argument_parsing_without_torch():
    """
    Test that argument parsing (validation) works without torch.

    Tests the specific case from TEST-011: invalid --cache-write-mode value
    should be rejected at argument parsing level without needing torch.
    """
    test_script = """
import builtins
import sys

# Block torch imports
_orig_import = builtins.__import__

def _mock_import(name, *args, **kwargs):
    if name == 'torch' or name.startswith('torch.'):
        raise ModuleNotFoundError(f"No module named '{name}'")
    return _orig_import(name, *args, **kwargs)

builtins.__import__ = _mock_import

# Test invalid cache-write-mode value
import runpy
sys.argv = ['src.cli', '--site', 'test', '--cache-write-mode', 'invalid_value']
try:
    runpy.run_module('src.cli', run_name='__main__')
except SystemExit as e:
    sys.exit(e.code)
"""

    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Should fail with exit code 2 (argument error)
    assert result.returncode == 2, (
        f"Expected exit code 2 for invalid argument, got {result.returncode}"
    )

    # Should show invalid choice error
    assert "invalid choice" in result.stderr.lower(), "Expected 'invalid choice' error in stderr"


@pytest.mark.slow
def test_dry_run_imports_work_without_torch():
    """
    Test that --dry-run can at least start without torch (TEST-006, TEST-012).

    This is a more permissive test - we allow the command to fail later
    (e.g., missing site config), but it should NOT fail with ImportError
    or ModuleNotFoundError related to torch.

    This test is marked as @pytest.mark.slow because it imports the full CLI.
    """
    test_script = """
import builtins
import sys

# Block torch imports
_orig_import = builtins.__import__

def _mock_import(name, *args, **kwargs):
    if name == 'torch' or name.startswith('torch.'):
        raise ModuleNotFoundError(f"No module named '{name}'")
    return _orig_import(name, *args, **kwargs)

builtins.__import__ = _mock_import

# Test dry-run
import runpy
sys.argv = ['src.cli', '--site', 'example', '--dry-run']
try:
    runpy.run_module('src.cli', run_name='__main__')
except SystemExit as e:
    sys.exit(e.code)
"""

    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Check that NO torch-related import errors occurred
    stderr_lower = result.stderr.lower()

    # These are the forbidden error patterns
    forbidden_patterns = [
        "importerror.*torch",
        "modulenotfounderror.*torch",
        "no module named.*torch",
    ]

    import re

    for pattern in forbidden_patterns:
        assert not re.search(pattern, stderr_lower, re.IGNORECASE), (
            f"Found torch import error in stderr (pattern: {pattern}):\\nSTDERR:\\n{result.stderr}"
        )

    # The command may fail for other reasons (missing site config, missing other deps)
    # but it should NOT fail with torch import errors
    # Exit codes other than 0 are acceptable as long as no torch import error
