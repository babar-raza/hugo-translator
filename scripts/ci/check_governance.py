#!/usr/bin/env python3
"""Governance file validator.

Checks that required project governance files exist and are non-empty.
Run as part of the release gate or locally:

    python scripts/ci/check_governance.py
    python scripts/ci/check_governance.py --strict   # exit 1 on any failure
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Required governance files with minimum byte size
REQUIRED_FILES: dict[str, int] = {
    "README.md": 500,
    "CONTRIBUTING.md": 200,
    "LICENSE": 100,
    "SECURITY.md": 200,
    "CODEOWNERS": 50,
    "AGENTS.md": 200,
    "CHANGELOG.md": 100,
    "pyproject.toml": 200,
    ".gitignore": 100,
}

# Required directories (must exist and contain at least one file)
REQUIRED_DIRS: list[str] = [
    "src",
    "tests",
    "config",
    "docs",
]


def check_governance(strict: bool = False) -> int:
    """Validate governance files and directories.

    Returns:
        0 if all checks pass, 1 if any check fails and strict mode is on.
    """
    failures: list[str] = []
    warnings: list[str] = []

    print("=" * 60)
    print("GOVERNANCE FILE CHECK")
    print("=" * 60)

    # Check required files
    for filename, min_size in REQUIRED_FILES.items():
        filepath = REPO_ROOT / filename
        if not filepath.exists():
            failures.append(f"MISSING: {filename}")
            print(f"  FAIL  {filename} — file not found")
        elif filepath.stat().st_size < min_size:
            failures.append(f"TOO_SMALL: {filename} ({filepath.stat().st_size} < {min_size} bytes)")
            print(
                f"  FAIL  {filename} — too small ({filepath.stat().st_size} bytes, need {min_size}+)"
            )
        else:
            print(f"  OK    {filename} ({filepath.stat().st_size} bytes)")

    # Check required directories
    for dirname in REQUIRED_DIRS:
        dirpath = REPO_ROOT / dirname
        if not dirpath.is_dir():
            failures.append(f"MISSING_DIR: {dirname}/")
            print(f"  FAIL  {dirname}/ — directory not found")
        elif not any(dirpath.iterdir()):
            warnings.append(f"EMPTY_DIR: {dirname}/")
            print(f"  WARN  {dirname}/ — directory is empty")
        else:
            count = (
                sum(1 for _ in dirpath.rglob("*.py"))
                if dirname in ("src", "tests")
                else sum(1 for _ in dirpath.iterdir())
            )
            print(f"  OK    {dirname}/ ({count} items)")

    # Check CI configuration
    ci_gitlab = REPO_ROOT / ".gitlab-ci.yml"
    ci_github = REPO_ROOT / ".github" / "workflows"
    if ci_gitlab.exists():
        print(f"  OK    .gitlab-ci.yml ({ci_gitlab.stat().st_size} bytes)")
    else:
        warnings.append("MISSING: .gitlab-ci.yml")
        print("  WARN  .gitlab-ci.yml — not found")

    if ci_github.is_dir() and any(ci_github.glob("*.yml")):
        wf_count = len(list(ci_github.glob("*.yml")))
        print(f"  OK    .github/workflows/ ({wf_count} workflows)")
    else:
        warnings.append("MISSING: .github/workflows/")
        print("  WARN  .github/workflows/ — not found or empty")

    # Summary
    print("=" * 60)
    if failures:
        print(f"GOVERNANCE CHECK: FAIL ({len(failures)} failure(s), {len(warnings)} warning(s))")
        for f in failures:
            print(f"  - {f}")
    elif warnings:
        print(f"GOVERNANCE CHECK: PASS with {len(warnings)} warning(s)")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("GOVERNANCE CHECK: PASS (all checks passed)")
    print("=" * 60)

    if failures and strict:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Check governance files")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any failure")
    args = parser.parse_args()
    sys.exit(check_governance(strict=args.strict))


if __name__ == "__main__":
    main()
