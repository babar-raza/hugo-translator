"""Test that all scripts can be imported and executed."""

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"


class TestScriptImports:
    """Test script import compatibility."""

    def test_validate_ast_translation_help(self):
        """Test that validate_ast_translation.py shows help."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "validate_ast_translation.py"), "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "usage" in result.stdout.lower()

    def test_analyze_ast_corpus_help(self):
        """Test that analyze_ast_corpus.py shows help."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "analyze_ast_corpus.py"), "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "usage" in result.stdout.lower()

    def test_no_import_errors(self):
        """Test that scripts can show help without ImportError."""
        # Test validate_ast_translation.py
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "validate_ast_translation.py"), "--help"],
            capture_output=True,
            text=True
        )
        # Should not have ImportError in output
        assert "ImportError" not in result.stderr, f"Import error in validate_ast_translation.py: {result.stderr}"

        # Test analyze_ast_corpus.py
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "analyze_ast_corpus.py"), "--help"],
            capture_output=True,
            text=True
        )
        # Should not have ImportError in output
        assert "ImportError" not in result.stderr, f"Import error in analyze_ast_corpus.py: {result.stderr}"
