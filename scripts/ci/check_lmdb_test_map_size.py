"""CI gate: detect L2PersistentTM calls in tests missing or oversized max_size_mb.

Usage:
    python scripts/ci/check_lmdb_test_map_size.py tests/
    python scripts/ci/check_lmdb_test_map_size.py tests/unit/test_foo.py

Exit codes:
    0 — all calls compliant
    1 — violations found
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import NamedTuple

MAX_ALLOWED_WITHOUT_JUSTIFICATION = 100
JUSTIFICATION_MARKER = "LMDB_MAX_SIZE_JUSTIFIED"


class Violation(NamedTuple):
    path: str
    line: int
    reason: str


def _is_l2_call(node: ast.Call) -> bool:
    """Return True if *node* is a call to L2PersistentTM."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == "L2PersistentTM":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "L2PersistentTM":
        return True
    return False


def _get_max_size_mb(node: ast.Call) -> int | None:
    """Extract the integer value of max_size_mb kwarg, or None if absent/dynamic."""
    for kw in node.keywords:
        if kw.arg == "max_size_mb":
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                return int(kw.value.value)
            if isinstance(kw.value, ast.UnaryOp):
                return None  # dynamic expression — treat as present but unresolvable
            return None  # present but not a literal — caller is responsible
    return None  # keyword absent


def _has_max_size_kwarg(node: ast.Call) -> bool:
    """Return True if max_size_mb keyword exists in the call (even if dynamic)."""
    return any(kw.arg == "max_size_mb" for kw in node.keywords)


def _has_justification(source_lines: list[str], call_lineno: int) -> bool:
    """Check 3 lines above the call for the justification marker comment."""
    # call_lineno is 1-indexed; source_lines is 0-indexed
    start = max(0, call_lineno - 4)  # 3 lines before (0-indexed)
    end = call_lineno  # up to and including the call line itself
    for i in range(start, end):
        if i < len(source_lines) and JUSTIFICATION_MARKER in source_lines[i]:
            return True
    return False


def check_file(filepath: Path) -> list[Violation]:
    """Return violations for a single Python file."""
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    source_lines = source.splitlines()

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    violations: list[Violation] = []
    relpath = str(filepath)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_l2_call(node):
            continue

        lineno = node.lineno

        if not _has_max_size_kwarg(node):
            violations.append(Violation(
                relpath, lineno,
                "missing max_size_mb (default 1536 MB pre-allocates 1.5 GB on Windows)",
            ))
            continue

        value = _get_max_size_mb(node)
        if value is not None and value > MAX_ALLOWED_WITHOUT_JUSTIFICATION:
            if not _has_justification(source_lines, lineno):
                violations.append(Violation(
                    relpath, lineno,
                    f"max_size_mb={value} exceeds {MAX_ALLOWED_WITHOUT_JUSTIFICATION} without "
                    f"{JUSTIFICATION_MARKER} comment",
                ))

    return violations


def scan_paths(paths: list[str]) -> list[Violation]:
    """Scan files or directories and return all violations."""
    all_violations: list[Violation] = []
    for path_str in paths:
        root = Path(path_str)
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for f in files:
            all_violations.extend(check_file(f))
    return all_violations


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: check_lmdb_test_map_size.py <path> [<path> ...]", file=sys.stderr)
        return 2

    violations = scan_paths(args)
    for v in sorted(violations, key=lambda x: (x.path, x.line)):
        print(f"{v.path}:{v.line}: {v.reason}")

    if violations:
        print(f"\n{len(violations)} violation(s) found.", file=sys.stderr)
        return 1

    print("All L2PersistentTM calls compliant.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
