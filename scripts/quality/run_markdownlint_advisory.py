"""run_markdownlint_advisory.py — Advisory markdownlint runner.

Runs npx markdownlint-cli2 on docs/**/*.md and prints results.
Always exits 0 — this is an advisory pre-commit hook.

To promote to blocking (TC-DOC-M-01): change sys.exit(0) to sys.exit(result).
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> None:
    # Require Node.js; skip silently if not available
    if not shutil.which("npx"):
        print("markdownlint-advisory: npx not found — skipping (install Node.js to enable)")
        sys.exit(0)

    try:
        result = subprocess.run(
            [
                "npx",
                "--yes",
                "markdownlint-cli2",
                "--config",
                ".markdownlintrc.json",
                "docs/**/*.md",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr)
            print(
                f"\nmarkdownlint-advisory: {result.returncode} violation(s) found "
                "(advisory — commit not blocked)"
            )
        else:
            print("markdownlint-advisory: all docs pass")
    except subprocess.TimeoutExpired:
        print("markdownlint-advisory: timed out — skipping")
    except Exception as e:
        print(f"markdownlint-advisory: error running markdownlint — {e}")

    sys.exit(0)  # Always advisory — never block commit


if __name__ == "__main__":
    main()
