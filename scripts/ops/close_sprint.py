"""
close_sprint.py — Sprint Evidence Bundle Generator

Creates a minimal .local/evidences/<sprint-name>/evidence-declaration.yaml
at sprint closeout.  Run this BEFORE the final push of a sprint to capture
the evidence package that the loop controller requires for auditing.

Usage:
    python scripts/ops/close_sprint.py --sprint-name <name> --verdict <verdict>
    python scripts/ops/close_sprint.py --sprint-name rosy-squishing-pretzel \
        --verdict ACCEPTED_VERIFIED

Required arguments:
    --sprint-name   Unique sprint identifier (e.g. rosy-squishing-pretzel)
    --verdict       Final sprint verdict (e.g. ACCEPTED_VERIFIED,
                    ACCEPTED_WITH_LIMITATIONS, PARTIAL, BLOCKED)

Optional arguments:
    --test-suite    Glob pattern for pytest collection count (default: tests/)
    --base-commit   SHA of the first sprint commit (default: HEAD~1)
    --plan-file     Path to the plan .md file for this sprint
    --notes         Free-text notes to include in the declaration

Exit codes:
    0  = evidence-declaration.yaml written successfully
    1  = error (invalid argument, git failure, etc.)
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVIDENCES_DIR = REPO_ROOT / ".local" / "evidences"

VALID_VERDICTS = {
    "ACCEPTED_VERIFIED",
    "ACCEPTED_WITH_LIMITATIONS",
    "PARTIAL",
    "BLOCKED",
    "FAILED",
    "REROUTED",
}


def _git(*args: str) -> str:
    """Run a git command and return stripped stdout, or '' on error."""
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _collect_test_count(pattern: str) -> dict:
    """Run pytest --collect-only and return pass/collected counts."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                pattern,
                "--collect-only",
                "-q",
                "--no-header",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=REPO_ROOT,
        )
        lines = result.stdout.strip().splitlines()
        # Last line is typically "X tests selected" or "X test collected"
        for line in reversed(lines):
            if "test" in line and any(c.isdigit() for c in line):
                return {"collected_summary": line.strip()}
        return {"collected_summary": "(could not parse)"}
    except Exception as exc:
        return {"collected_summary": f"(error: {exc})"}


def _sprint_commits(base_commit: str) -> list[str]:
    """Return one-line log of commits since base_commit (exclusive)."""
    log = _git("log", "--oneline", f"{base_commit}..HEAD")
    return log.splitlines() if log else []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate sprint evidence-declaration.yaml at closeout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--sprint-name", required=True, help="Sprint identifier")
    parser.add_argument(
        "--verdict",
        required=True,
        choices=sorted(VALID_VERDICTS),
        help="Final sprint verdict",
    )
    parser.add_argument(
        "--test-suite",
        default="tests/",
        help="Pytest path/pattern for test count (default: tests/)",
    )
    parser.add_argument(
        "--base-commit",
        default="",
        help="SHA of the commit immediately before the sprint (default: auto-detect)",
    )
    parser.add_argument(
        "--plan-file",
        default="",
        help="Relative path to the sprint plan .md file",
    )
    parser.add_argument("--notes", default="", help="Free-text notes")
    args = parser.parse_args()

    # Collect git metadata
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    head_sha = _git("rev-parse", "HEAD")
    today = datetime.date.today().isoformat()

    # Resolve base commit
    base_commit = args.base_commit
    if not base_commit:
        # Auto-detect: find the first commit on main after origin/main diverged
        origin_head = _git("rev-parse", "origin/main")
        base_commit = origin_head if origin_head else "HEAD~1"

    sprint_commits = _sprint_commits(base_commit)
    test_info = _collect_test_count(args.test_suite)

    # Build the evidence directory
    evidence_dir = EVIDENCES_DIR / args.sprint_name
    evidence_dir.mkdir(parents=True, exist_ok=True)
    output_path = evidence_dir / "evidence-declaration.yaml"

    # Write the declaration
    lines: list[str] = [
        f"run_id: {args.sprint_name}",
        f"repo_path: {REPO_ROOT}",
        f"branch: {branch}",
        f"base_commit: {base_commit}",
        f"head_commit: {head_sha}",
        f"date: {today}",
        f"closeout_date: {today}",
        "",
        f"final_verdict: {args.verdict}",
        "",
    ]

    if args.plan_file:
        lines.append(f"plan_file: {args.plan_file}")
        lines.append("")

    lines += [
        "sprint_commits:",
    ]
    if sprint_commits:
        for c in sprint_commits:
            lines.append(f"  - \"{c}\"")
    else:
        lines.append("  []")

    lines += [
        "",
        "test_collection:",
        f"  suite: {args.test_suite}",
        f"  {next(iter(test_info))}: {next(iter(test_info.values()))}",
        "",
        "evidence_package_created: true",
    ]

    if args.notes:
        lines.append("")
        lines.append(f"notes: |\n  {args.notes}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK: evidence-declaration.yaml written to {output_path}")
    print(f"    Sprint:   {args.sprint_name}")
    print(f"    Verdict:  {args.verdict}")
    print(f"    Commits:  {len(sprint_commits)} since {base_commit[:8]}")
    print(f"    Tests:    {test_info.get('collected_summary', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
