"""Test that all scripts can be imported and executed."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"

_VALIDATE_AST_SCRIPT = SCRIPTS_DIR / "validate_ast_translation.py"
_ANALYZE_CORPUS_SCRIPT = SCRIPTS_DIR / "analyze_ast_corpus.py"


class TestScriptImports:
    """Test script import compatibility."""

    def test_validate_ast_translation_help(self):
        """Test that validate_ast_translation.py shows help."""
        if not _VALIDATE_AST_SCRIPT.exists():
            pytest.skip(f"Script not found: {_VALIDATE_AST_SCRIPT}")
        result = subprocess.run(
            [sys.executable, str(_VALIDATE_AST_SCRIPT), "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "usage" in result.stdout.lower()

    def test_analyze_ast_corpus_help(self):
        """Test that analyze_ast_corpus.py shows help."""
        if not _ANALYZE_CORPUS_SCRIPT.exists():
            pytest.skip(f"Script not found: {_ANALYZE_CORPUS_SCRIPT}")
        result = subprocess.run(
            [sys.executable, str(_ANALYZE_CORPUS_SCRIPT), "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "usage" in result.stdout.lower()

    def test_no_import_errors(self):
        """Test that scripts can show help without ImportError."""
        # Test validate_ast_translation.py
        if _VALIDATE_AST_SCRIPT.exists():
            result = subprocess.run(
                [sys.executable, str(_VALIDATE_AST_SCRIPT), "--help"],
                capture_output=True,
                text=True
            )
            assert "ImportError" not in result.stderr, f"Import error in validate_ast_translation.py: {result.stderr}"

        # Test analyze_ast_corpus.py
        if _ANALYZE_CORPUS_SCRIPT.exists():
            result = subprocess.run(
                [sys.executable, str(_ANALYZE_CORPUS_SCRIPT), "--help"],
                capture_output=True,
                text=True
            )
            assert "ImportError" not in result.stderr, f"Import error in analyze_ast_corpus.py: {result.stderr}"
