"""
scripts/ci/check_manifest.py

Validates scripts/MANIFEST.toml against the actual scripts/ root directory.

EXIT CODES:
  0 — all CI-critical scripts present; root is clean (strict) or warnings issued
  1 — unregistered script at scripts/ root (--strict mode only, or CI-critical missing)
  2 — MANIFEST entry has no corresponding file (stale reference)

MODES:
  Default: verify all ci_critical scripts exist; warn on unregistered root files.
           Used during the Phase 1-2 migration period.
  --strict: additionally fail if any root script exists without a MANIFEST entry.
            Used after Phase 2 migration is complete (all non-CI-critical scripts
            moved to subdirectories).

USAGE:
  python scripts/ci/check_manifest.py            # warn mode (migration period)
  python scripts/ci/check_manifest.py --strict   # strict mode (post-migration)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal TOML parser — avoids tomli/tomllib dependency.
# Parses the simple [[script]] blocks used in MANIFEST.toml.
# ---------------------------------------------------------------------------


def _parse_manifest(manifest_path: Path) -> list[dict]:
    """
    Parse [[script]] blocks from MANIFEST.toml.
    Returns a list of dicts, one per [[script]] block.
    Only extracts string and boolean fields.
    """
    text = manifest_path.read_text(encoding="utf-8")
    blocks: list[dict] = []
    current: dict | None = None

    for line in text.splitlines():
        line = line.strip()
        if line == "[[script]]":
            if current is not None:
                blocks.append(current)
            current = {}
            continue
        if current is None:
            continue
        # Skip comments and blank lines
        if not line or line.startswith("#"):
            continue
        # Match: key = "value"
        m = re.match(r'^(\w+)\s*=\s*"([^"]*)"$', line)
        if m:
            current[m.group(1)] = m.group(2)
            continue
        # Match: key = true / false
        m = re.match(r"^(\w+)\s*=\s*(true|false)$", line)
        if m:
            current[m.group(1)] = m.group(2) == "true"
            continue
        # Match: key = ["val1", "val2"] (list of strings)
        m = re.match(r"^(\w+)\s*=\s*\[([^\]]*)\]$", line)
        if m:
            vals = re.findall(r'"([^"]*)"', m.group(2))
            current[m.group(1)] = vals
            continue

    if current is not None:
        blocks.append(current)

    return blocks


# ---------------------------------------------------------------------------
# Extensions considered scripts at the root level
# ---------------------------------------------------------------------------
SCRIPT_EXTENSIONS = {".py", ".sh", ".ps1", ".bat", ".toml"}
# .toml is excluded from "script" checks — MANIFEST.toml itself is not a script
EXCLUDE_FILES = {"MANIFEST.toml"}
EXCLUDE_NAMES = {"README.md", "README_INVARIANT_CHECKER.md", "validation_output_de.md"}


def _get_root_scripts(scripts_root: Path) -> set[str]:
    """Return filenames of all script files directly in scripts/ root (not subdirs)."""
    result = set()
    for p in scripts_root.iterdir():
        if p.is_file() and p.suffix in SCRIPT_EXTENSIONS and p.name not in EXCLUDE_FILES:
            result.add(p.name)
    return result


def main(strict: bool = False) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    scripts_root = repo_root / "scripts"
    manifest_path = scripts_root / "MANIFEST.toml"

    if not manifest_path.exists():
        print(f"ERROR: MANIFEST.toml not found at {manifest_path}")
        return 1

    entries = _parse_manifest(manifest_path)
    if not entries:
        print("ERROR: MANIFEST.toml parsed 0 entries — check file format.")
        return 1

    registered_paths = {e["path"] for e in entries if "path" in e}
    ci_critical = {e["path"] for e in entries if e.get("ci_critical") is True}

    actual_root_scripts = _get_root_scripts(scripts_root)

    exit_code = 0
    errors: list[str] = []
    warnings: list[str] = []

    # --- Check 1: CI-critical scripts must exist on disk ---
    for path in sorted(ci_critical):
        if not (scripts_root / path).exists():
            errors.append(
                f"MISSING CI-CRITICAL: scripts/{path} is registered as ci_critical=true "
                f"but does not exist on disk. Do NOT remove or rename CI-critical scripts "
                f"without updating the CI workflow and CONTRIBUTING.md simultaneously."
            )

    # --- Check 2: MANIFEST entries must have corresponding files ---
    for path in sorted(registered_paths):
        if not (scripts_root / path).exists():
            errors.append(
                f"STALE MANIFEST ENTRY: scripts/{path} is in MANIFEST.toml but "
                f"does not exist. Remove the entry or restore the file."
            )

    # --- Check 3: Root scripts must be registered (strict mode) ---
    unregistered = actual_root_scripts - registered_paths
    for name in sorted(unregistered):
        msg = (
            f"UNREGISTERED ROOT SCRIPT: scripts/{name} has no MANIFEST.toml entry. "
            f"Add an entry to MANIFEST.toml before landing this script, OR move it "
            f"to an appropriate subdirectory (scripts/bench/, scripts/ops/, etc.)."
        )
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    # --- Report ---
    print("=" * 70)
    print("MANIFEST CHECK")
    print(f"  MANIFEST.toml entries : {len(entries)}")
    print(f"  CI-critical scripts   : {len(ci_critical)}")
    print(f"  Root scripts on disk  : {len(actual_root_scripts)}")
    print(f"  Unregistered at root  : {len(unregistered)}")
    print(f"  Mode                  : {'strict' if strict else 'warn (migration period)'}")
    print("=" * 70)

    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  [WARN] {w}")

    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  [FAIL] {e}")
        exit_code = 1
    else:
        if warnings:
            print(
                "\nNOTE: Warnings are non-blocking during migration (Phase 1-2).\n"
                "After subdirectory migration is complete, switch to --strict mode."
            )
        else:
            print("\nOK: All MANIFEST checks passed.")

    return exit_code


if __name__ == "__main__":
    strict_mode = "--strict" in sys.argv
    sys.exit(main(strict=strict_mode))
