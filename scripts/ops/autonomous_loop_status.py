"""
Autonomous Green Loop — Session Recovery Status Reader

Read-only tool for checking the current state of an autonomous green loop run.
Useful for session recovery after context exhaustion.

Usage:
    python scripts/ops/autonomous_loop_status.py --run-dir <path>

Exit codes:
    0 = GREEN_STOP reached (loop is complete)
    1 = loop is in progress, blocked, or incomplete
    2 = run directory or required files not found
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import]

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, falling back to JSON if yaml not available."""
    content = path.read_text(encoding="utf-8")
    if _YAML_AVAILABLE:
        return yaml.safe_load(content) or {}
    # Minimal fallback: try JSON (loop-signal.yaml uses simple scalar values)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Parse only key: value lines (no nested structures needed for status)
        result: dict = {}
        for line in content.splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#") and not line.startswith("-"):
                k, _, v = line.partition(":")
                result[k.strip()] = v.strip()
        return result


def _count_registry_statuses(registry: dict) -> dict[str, int]:
    """Count taskcards by status."""
    counts: dict[str, int] = {"OPEN": 0, "IN_PROGRESS": 0, "CLOSED": 0, "BLOCKED": 0}
    for tc in registry.get("taskcards", []):
        status = tc.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _check_evidence_artifacts(run_dir: Path, iteration: int) -> list[str]:
    """Return list of expected artifacts that are missing for given iteration."""
    expected = [
        run_dir / "loop-state.yaml",
        run_dir / "loop-signal.yaml",
        run_dir / "taskcard-registry.yaml",
        run_dir / f"audit-report-iter{iteration}.md",
    ]
    missing = [str(p.relative_to(run_dir)) for p in expected if not p.exists()]
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check autonomous green loop run status (read-only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--version",
        action="version",
        version="1.0",
    )
    parser.add_argument(
        "--run-dir",
        required=False,
        type=Path,
        help="Path to the loop run directory (contains loop-signal.yaml)",
    )
    args = parser.parse_args()

    if args.run_dir is None:
        parser.error("--run-dir is required (unless using --version or --help)")

    run_dir: Path = args.run_dir
    if not run_dir.is_dir():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        return 2

    signal_path = run_dir / "loop-signal.yaml"
    state_path = run_dir / "loop-state.yaml"
    registry_path = run_dir / "taskcard-registry.yaml"

    # Load available files
    signal: dict = {}
    state: dict = {}
    registry: dict = {}

    if signal_path.exists():
        signal = _load_yaml(signal_path)
    if state_path.exists():
        state = _load_yaml(state_path)
    if registry_path.exists():
        registry = _load_yaml(registry_path)

    if not signal and not state:
        print(f"ERROR: No loop state files found in {run_dir}", file=sys.stderr)
        print("This may be a new run that has not yet started.", file=sys.stderr)
        return 2

    # Extract key fields
    run_id = signal.get("run_id") or state.get("run_id") or run_dir.name
    plan_path = signal.get("plan_path") or state.get("plan_path") or "unknown"
    iteration = int(signal.get("iteration") or state.get("iteration") or 0)
    max_iterations = int(signal.get("max_iterations") or state.get("max_iterations") or 5)
    iterations_remaining = int(
        signal.get("iterations_remaining") or state.get("iterations_remaining") or 0
    )
    current_state = state.get("current_state") or signal.get("state") or "UNKNOWN"
    next_action = signal.get("next_action") or "UNKNOWN"
    audit_verdict = signal.get("audit_verdict") or "not yet run"
    blocking_gaps = signal.get("blocking_gaps", "unknown")
    blocker_desc = signal.get("blocker_description") or ""

    # Count taskcards
    tc_counts = _count_registry_statuses(registry)
    total_tc = sum(tc_counts.values())

    # Missing artifacts check
    missing = _check_evidence_artifacts(run_dir, iteration) if iteration > 0 else []

    # Print status
    print("=" * 60)
    print("AUTONOMOUS GREEN LOOP — STATUS")
    print("=" * 60)
    print(f"Run ID       : {run_id}")
    print(f"Plan         : {plan_path}")
    print(f"State        : {current_state}")
    print(f"Iteration    : {iteration}/{max_iterations}  ({iterations_remaining} remaining)")
    print(f"Next action  : {next_action}")
    print(f"Audit verdict: {audit_verdict}")
    print(f"Blocking gaps: {blocking_gaps}")
    print()
    print("Taskcards:")
    for status, count in tc_counts.items():
        if count > 0:
            print(f"  {status:12s}: {count}")
    if total_tc == 0:
        print("  (none registered yet)")
    print()

    if blocker_desc:
        print(f"BLOCKER: {blocker_desc}")
        print()

    if missing:
        print("Missing expected artifacts:")
        for m in missing:
            print(f"  - {m}")
        print()

    # Resume instruction
    if next_action == "GREEN_STOP":
        print("STATUS: COMPLETE — GREEN_STOP reached.")
        print(f"Evidence bundle: .local/autonomous-loop/evidence/{run_id}/")
        return 0

    elif next_action == "BLOCKED_EXTERNAL":
        print("STATUS: BLOCKED — External blocker requires human decision.")
        print("After resolving the blocker:")
        print("  1. Edit loop-signal.yaml — change next_action to EXPAND or GREEN_STOP")
        print("  2. Resume: Read prompts/autonomous/autonomous-green-loop.md")
        print(f"     Then read the plan at {plan_path}")
        print(f"     The loop will resume from run dir: {run_dir}")
        return 1

    elif next_action in ("EXPAND", "AUDIT_COMPLETE") or current_state in (
        "AUDIT_COMPLETE",
        "EXPANDING",
        "EXPANDED",
    ):
        print("STATUS: IN PROGRESS — loop needs to continue.")
        print()
        print("To resume in a new session:")
        print("  Read: prompts/autonomous/autonomous-green-loop.md")
        print(f"  Then read the plan at: {plan_path}")
        print(f"  The run directory {run_dir} contains loop-signal.yaml")
        print(f"  with next_action: {next_action}.")
        print("  The loop will resume from the correct state.")
        return 1

    elif current_state in ("EXECUTING", "AUDITING", "HARDENING"):
        print(f"STATUS: IN PROGRESS — currently in {current_state} stage.")
        print("If the agent session is still running, wait for it to complete.")
        print("If the session was interrupted, resume:")
        print("  Read: prompts/autonomous/autonomous-green-loop.md")
        print(f"  Then read the plan at: {plan_path}")
        return 1

    else:
        print(f"STATUS: {current_state} — review loop-state.yaml for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
