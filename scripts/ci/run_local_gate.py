#!/usr/bin/env python3
"""
Local quality gate - runs lint and critical tests before commit/push.

Usage:
    python scripts/ci/run_local_gate.py          # Quick gate (lint + core tests)
    python scripts/ci/run_local_gate.py --full    # Full gate (lint + all unit tests)

Exit codes:
    0: All gates pass
    1: One or more gates failed
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path


def run_cmd(label: str, cmd: list[str], cwd: Path) -> bool:
    """Run a command and return True if it passed."""
    print(f"\n{'=' * 60}")
    print(f"  GATE: {label}")
    print(f"  CMD:  {' '.join(cmd)}")
    print(f"{'=' * 60}")
    start = time.monotonic()
    result = subprocess.run(cmd, cwd=cwd, capture_output=False)
    elapsed = time.monotonic() - start
    status = "PASS" if result.returncode == 0 else "FAIL"
    print(f"  [{status}] {label} ({elapsed:.1f}s)")
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Local quality gate")
    parser.add_argument("--full", action="store_true", help="Run full test suite")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        print("ERROR: .venv not found. Create it first.")
        return 1

    py = str(venv_python)
    results: list[tuple[str, bool]] = []

    # Gate 1: Ruff lint
    results.append(
        (
            "Ruff lint (src/)",
            run_cmd(
                "Ruff lint (src/)",
                [py, "-m", "ruff", "check", "src/", "--output-format=concise"],
                project_root,
            ),
        )
    )

    # Gate 2: Core unit tests (fast)
    if args.full:
        test_paths = ["tests/unit/"]
    else:
        test_paths = [
            "tests/unit/phase-0/",
            "tests/unit/phase-1/",
            "tests/unit/validation/",
            "tests/unit/translation_engine/",
        ]
    results.append(
        (
            "Unit tests",
            run_cmd(
                "Unit tests",
                [py, "-m", "pytest", *test_paths, "-q", "--tb=short", "--timeout=300"],
                project_root,
            ),
        )
    )

    # Gate 3: Contract tests
    results.append(
        (
            "Contract tests",
            run_cmd(
                "Contract tests",
                [py, "-m", "pytest", "tests/contract/", "-q", "--tb=short", "--timeout=300"],
                project_root,
            ),
        )
    )

    # Summary
    print(f"\n{'=' * 60}")
    print("  LOCAL GATE SUMMARY")
    print(f"{'=' * 60}")
    all_pass = True
    for label, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}")
        if not passed:
            all_pass = False

    if all_pass:
        print("\n  LOCAL GATE: ALL PASS")
        return 0
    else:
        print("\n  LOCAL GATE: FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
