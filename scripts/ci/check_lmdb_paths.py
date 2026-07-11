#!/usr/bin/env python3
"""
CI scan: detect hardcoded or unapproved LMDB paths in source code.

Fails (exit 1) if any file in src/, scripts/, or .local/ contains a literal
reference to a known legacy/wrong LMDB path, or opens lmdb/L2PersistentTM
with a hardcoded string that is not the canonical l2.lmdb.

Exit 0 = no violations found.
Exit 1 = violations found (printed to stdout).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

# Regex patterns that identify actual LMDB path constructs (not metric names or comments).
# Each pattern is compiled and matched against non-comment lines.

BANNED_PATTERNS = [
    # Path concatenation with wrong LMDB name: / "l2_lmdb"  or / 'l2_lmdb'
    re.compile(r"""[/\\]\s*["']l2_lmdb["']"""),
    # Direct path string in call: Path("...l2_lmdb...") or str ending in l2_lmdb
    re.compile(r"""Path\(['"]\S*l2_lmdb\S*['"]\)"""),
    # L2PersistentTM opened with tm_cache path
    re.compile(r"""L2PersistentTM\s*\(\s*(?:db_path\s*=\s*)?[A-Z_a-z.]+\s*/\s*["']tm_cache["']"""),
    re.compile(r"""L2PersistentTM\s*\(\s*Path\s*\(\s*["'][./\\]*tm_cache["']"""),
    # Path concatenation: / "tm_cache" as filesystem path (not metric string)
    re.compile(r"""[/\\]\s*["']tm_cache["']"""),
]

# Files that are explicitly allowed to reference legacy paths
# (migration scripts, CI script itself, dry-run classifier, legacy helpers)
ALLOWLIST = {
    "scripts/tm/consolidate_dry_run.py",
    "scripts/tm/merge_legacy_lmdb.py",
    "scripts/tm/verify_canonical_post_merge.py",
    "scripts/ci/check_lmdb_paths.py",         # this file
    ".local/consolidate_lmdb.py",             # superseded but kept for reference
    "scripts/tm/migrate_l2_lmdb.py",          # old migration script, references old name intentionally
    # Archived historical scripts (not run in production)
    "scripts/archived/root_cleanup_2026/test_logging.py",
    "scripts/archived/root_cleanup_2026/test_telemetry_docker_integration.py",
    "scripts/archived/root_cleanup_2026/validate_ast_e2e.py",
    "scripts/archived/root_cleanup_2026/validate_ast_translation.py",
    "scripts/archived/root_cleanup_2026/verify_docker_telemetry.py",
    "scripts/archived/root_cleanup_2026/verify_hp_e2e.py",
    # Diagnostic/e2e scripts that reference old path for checking legacy state
    "scripts/diag/verify_telemetry.py",
    "scripts/e2e/e2e_dry_run.py",
    "scripts/e2e/e2e_full_run.py",
    "scripts/e2e/e2e_slides_with_telemetry.py",
    "scripts/content/translate_bg_test.py",   # test/dev script, not production
}

SCAN_DIRS = [
    ROOT / "src",
    ROOT / "scripts",
    ROOT / ".local",
]

VIOLATIONS: list[tuple[str, int, str]] = []


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def scan_file(path: Path) -> None:
    r = rel(path)
    if r in ALLOWLIST:
        return
    # Skip archived directories entirely
    if "archived" in r:
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return
    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Track triple-quoted docstrings (skip content inside them)
        if '"""' in stripped or "'''" in stripped:
            count = stripped.count('"""') + stripped.count("'''")
            if count % 2 != 0:
                in_docstring = not in_docstring
        if in_docstring:
            continue
        if stripped.startswith("#"):
            continue
        for pattern in BANNED_PATTERNS:
            if pattern.search(line):
                VIOLATIONS.append((r, i, line.rstrip()))
                break


def main() -> int:
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for path in scan_dir.rglob("*.py"):
            scan_file(path)

    if not VIOLATIONS:
        print("check_lmdb_paths: OK — no banned LMDB path literals found.")
        return 0

    print(f"check_lmdb_paths: FAIL — {len(VIOLATIONS)} violation(s):")
    for file_path, lineno, text in VIOLATIONS:
        print(f"  {file_path}:{lineno}  {text[:120]}")
    print()
    print("Fix: use get_canonical_l2_path() or L2_DB_NAME from src.tm.l2_persistent.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
