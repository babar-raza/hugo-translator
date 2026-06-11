"""Tests for audit script."""

import tempfile
from pathlib import Path

from scripts.audit_codebase import CodebaseAuditor


def test_detects_stub_function():
    # Create temp file with stub
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("""
def my_stub():
    pass
""")
        f.flush()
        temp_path = Path(f.name)

    try:
        auditor = CodebaseAuditor(temp_path.parent)
        auditor._audit_python_file(temp_path)

        stubs = [i for i in auditor.issues if i.category == "stub"]
        assert len(stubs) == 1
        assert "my_stub" in stubs[0].context
    finally:
        temp_path.unlink()


def test_detects_todo_comment():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("# TODO: implement this\n")
        f.flush()
        temp_path = Path(f.name)

    try:
        auditor = CodebaseAuditor(temp_path.parent)
        auditor._audit_python_file(temp_path)

        todos = [i for i in auditor.issues if i.category == "todo"]
        assert len(todos) == 1
    finally:
        temp_path.unlink()


def test_detects_not_implemented_error():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("""
def incomplete():
    raise NotImplementedError()
""")
        f.flush()
        temp_path = Path(f.name)

    try:
        auditor = CodebaseAuditor(temp_path.parent)
        auditor._audit_python_file(temp_path)

        not_impl = [i for i in auditor.issues if i.category == "not_implemented"]
        assert len(not_impl) == 1
    finally:
        temp_path.unlink()


def test_excludes_test_functions():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("""
def test_something():
    pass  # Test stubs are ok
""")
        f.flush()
        temp_path = Path(f.name)

    try:
        auditor = CodebaseAuditor(temp_path.parent)
        auditor._audit_python_file(temp_path)

        stubs = [i for i in auditor.issues if i.category == "stub"]
        assert len(stubs) == 0  # Test functions excluded
    finally:
        temp_path.unlink()
