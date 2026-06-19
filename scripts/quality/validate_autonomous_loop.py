"""
Autonomous Green Loop — Structural Validator

Checks that all loop prompt files exist, cross-references are intact,
AUTONOMOUS LOOP OPERATION sections are present in the 4 enhanced prompts,
and that the loop contracts contain the required key terms.

Optionally validates the structure of a run directory.

Usage:
    python scripts/quality/validate_autonomous_loop.py
    python scripts/quality/validate_autonomous_loop.py --run-dir <path>

Exit codes:
    0 = all checks pass
    1 = one or more checks failed (first failure printed to stdout)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repository root relative to this script
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROMPTS_DIR = REPO_ROOT / "prompts" / "autonomous"

# --- Check 1: All 8 new prompt files exist ---
NEW_PROMPT_FILES = [
    "autonomous-green-loop.md",
    "loop-state-machine.md",
    "loop-runbook.md",
    "loop-audit-contract.md",
    "loop-idempotency-contract.md",
    "loop-taskcard-contract.md",
    "loop-evidence-contract.md",
    "loop-swarm-contract.md",
]

# --- Check 2: All 4 enhanced prompts have AUTONOMOUS LOOP OPERATION section ---
ENHANCED_PROMPT_FILES = [
    "harden-plan.md",
    "execute-plan.md",
    "sprint-audit.md",
    "expand-plan.md",
]

LOOP_OPERATION_MARKER = "AUTONOMOUS LOOP OPERATION"

# --- Check 3: autonomous-green-loop.md references all 4 stage prompts ---
ORCHESTRATOR_FILE = "autonomous-green-loop.md"
REQUIRED_STAGE_PROMPT_REFS = [
    "harden-plan.md",
    "execute-plan.md",
    "sprint-audit.md",
    "expand-plan.md",
]

# --- Check 4-5: autonomous-green-loop.md references key state files ---
REQUIRED_ORCHESTRATOR_REFS = [
    "loop-signal.yaml",
    "taskcard-registry.yaml",
]

# --- Check 6: loop-state-machine.md defines all required states ---
STATE_MACHINE_FILE = "loop-state-machine.md"
REQUIRED_STATES = [
    "INITIATED",
    "HARDENING",
    "HARDENED",
    "EXECUTING",
    "EXECUTED",
    "AUDITING",
    "AUDIT_COMPLETE",
    "EXPANDING",
    "EXPANDED",
    "GREEN",
    "BLOCKED_EXTERNAL",
    "MAX_ITER_REACHED",
]

# --- Check 7: loop-audit-contract.md contains key terms ---
AUDIT_CONTRACT_FILE = "loop-audit-contract.md"
AUDIT_CONTRACT_REQUIRED_TERMS = ["blocking_gaps", "GREEN_STOP", "BLOCKING_GAP"]

# --- Check 8: loop-idempotency-contract.md contains key terms ---
IDEMPOTENCY_CONTRACT_FILE = "loop-idempotency-contract.md"
IDEMPOTENCY_REQUIRED_TERMS = ["MAX_ITER", "CLOSED"]

# --- Check 9: expand-plan.md AUTONOMOUS section has file-based input ---
EXPAND_REQUIRED_TERM = "audit-report-iter"

# --- Check 10: sprint-audit.md AUTONOMOUS section writes loop-signal.yaml ---
AUDIT_REQUIRED_TERM = "loop-signal.yaml"

# --- Check 11: loop-taskcard-contract.md references the registry schema ---
TASKCARD_CONTRACT_FILE = "loop-taskcard-contract.md"
TASKCARD_REQUIRED_TERM = "taskcard-registry.yaml"

# --- Check 12: loop-swarm-contract.md contains COORDINATOR key term ---
SWARM_CONTRACT_FILE = "loop-swarm-contract.md"
SWARM_REQUIRED_TERM = "COORDINATOR"

# --- Check 13: loop-runbook.md references loop-signal ---
RUNBOOK_FILE = "loop-runbook.md"
RUNBOOK_REQUIRED_TERM = "loop-signal"

# --- Check 14: loop-evidence-contract.md contains evidence_level term ---
EVIDENCE_CONTRACT_FILE = "loop-evidence-contract.md"
EVIDENCE_REQUIRED_TERM = "Evidence Level"

# --- Check 15 (optional): run directory structure ---
RUN_DIR_REQUIRED_FILES = [
    "loop-signal.yaml",
    "loop-state.yaml",
    "taskcard-registry.yaml",
]

LOOP_SIGNAL_REQUIRED_FIELDS = ["run_id", "next_action", "blocking_gaps", "iteration"]
REGISTRY_REQUIRED_FIELDS = ["run_id", "taskcards"]


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _check_file_contains(file_path: Path, term: str) -> bool:
    """Return True if file contains the given string."""
    try:
        content = file_path.read_text(encoding="utf-8")
        return term in content
    except OSError:
        return False


def _check_run_dir(run_dir: Path) -> int:
    """Validate run directory structure. Returns 0 on pass, 1 on failure."""
    for fname in RUN_DIR_REQUIRED_FILES:
        fpath = run_dir / fname
        if not fpath.exists():
            return _fail(f"Run dir missing required file: {fpath}")

    # Validate loop-signal.yaml has required fields
    signal_path = run_dir / "loop-signal.yaml"
    signal_content = signal_path.read_text(encoding="utf-8")
    for field in LOOP_SIGNAL_REQUIRED_FIELDS:
        if field not in signal_content:
            return _fail(f"loop-signal.yaml missing required field: {field} (in {signal_path})")

    # Validate taskcard-registry.yaml has required fields
    registry_path = run_dir / "taskcard-registry.yaml"
    registry_content = registry_path.read_text(encoding="utf-8")
    for field in REGISTRY_REQUIRED_FIELDS:
        if field not in registry_content:
            return _fail(
                f"taskcard-registry.yaml missing required field: {field} (in {registry_path})"
            )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate autonomous green loop prompt files and cross-references.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Optional: path to a loop run directory to validate its structure",
    )
    args = parser.parse_args()

    failures: list[str] = []

    def fail(msg: str) -> None:
        failures.append(msg)

    # Check 1: All 8 new prompt files exist
    for fname in NEW_PROMPT_FILES:
        fpath = PROMPTS_DIR / fname
        if not fpath.exists():
            fail(f"New prompt file missing: {fpath}")

    # Check 2: All 4 enhanced prompts have AUTONOMOUS LOOP OPERATION section
    for fname in ENHANCED_PROMPT_FILES:
        fpath = PROMPTS_DIR / fname
        if not fpath.exists():
            fail(f"Enhanced prompt file missing: {fpath}")
        elif not _check_file_contains(fpath, LOOP_OPERATION_MARKER):
            fail(f"Enhanced prompt missing '{LOOP_OPERATION_MARKER}' section: {fpath}")

    # Check 3: autonomous-green-loop.md references all 4 stage prompts
    orchestrator_path = PROMPTS_DIR / ORCHESTRATOR_FILE
    if orchestrator_path.exists():
        for ref in REQUIRED_STAGE_PROMPT_REFS:
            if not _check_file_contains(orchestrator_path, ref):
                fail(f"{ORCHESTRATOR_FILE} does not reference stage prompt: {ref}")
    else:
        fail(f"Orchestrator file missing: {orchestrator_path}")

    # Checks 4-5: autonomous-green-loop.md references key state files
    if orchestrator_path.exists():
        for ref in REQUIRED_ORCHESTRATOR_REFS:
            if not _check_file_contains(orchestrator_path, ref):
                fail(f"{ORCHESTRATOR_FILE} does not reference required file: {ref}")

    # Check 6: loop-state-machine.md defines all required states
    state_machine_path = PROMPTS_DIR / STATE_MACHINE_FILE
    if state_machine_path.exists():
        for state in REQUIRED_STATES:
            if not _check_file_contains(state_machine_path, state):
                fail(f"{STATE_MACHINE_FILE} does not define required state: {state}")
    else:
        fail(f"State machine file missing: {state_machine_path}")

    # Check 7: loop-audit-contract.md required terms
    audit_contract_path = PROMPTS_DIR / AUDIT_CONTRACT_FILE
    if audit_contract_path.exists():
        for term in AUDIT_CONTRACT_REQUIRED_TERMS:
            if not _check_file_contains(audit_contract_path, term):
                fail(f"{AUDIT_CONTRACT_FILE} missing required term: '{term}'")
    else:
        fail(f"Audit contract file missing: {audit_contract_path}")

    # Check 8: loop-idempotency-contract.md required terms
    idempotency_path = PROMPTS_DIR / IDEMPOTENCY_CONTRACT_FILE
    if idempotency_path.exists():
        for term in IDEMPOTENCY_REQUIRED_TERMS:
            if not _check_file_contains(idempotency_path, term):
                fail(f"{IDEMPOTENCY_CONTRACT_FILE} missing required term: '{term}'")
    else:
        fail(f"Idempotency contract file missing: {idempotency_path}")

    # Check 9: expand-plan.md AUTONOMOUS section has file-based input term
    expand_path = PROMPTS_DIR / "expand-plan.md"
    if expand_path.exists():
        if not _check_file_contains(expand_path, EXPAND_REQUIRED_TERM):
            fail(
                f"expand-plan.md AUTONOMOUS LOOP OPERATION section does not "
                f"reference '{EXPAND_REQUIRED_TERM}' (file-based input fallback missing)"
            )
    else:
        fail(f"expand-plan.md missing: {expand_path}")

    # Check 10: sprint-audit.md AUTONOMOUS section writes loop-signal.yaml
    audit_path = PROMPTS_DIR / "sprint-audit.md"
    if audit_path.exists():
        if not _check_file_contains(audit_path, AUDIT_REQUIRED_TERM):
            fail(
                f"sprint-audit.md AUTONOMOUS LOOP OPERATION section does not "
                f"reference '{AUDIT_REQUIRED_TERM}' (machine-readable output missing)"
            )
    else:
        fail(f"sprint-audit.md missing: {audit_path}")

    # Check 11: loop-taskcard-contract.md references taskcard-registry.yaml
    taskcard_contract_path = PROMPTS_DIR / TASKCARD_CONTRACT_FILE
    if taskcard_contract_path.exists():
        if not _check_file_contains(taskcard_contract_path, TASKCARD_REQUIRED_TERM):
            fail(f"{TASKCARD_CONTRACT_FILE} missing required term: '{TASKCARD_REQUIRED_TERM}'")
    else:
        fail(f"Taskcard contract file missing: {taskcard_contract_path}")

    # Check 12: loop-swarm-contract.md contains COORDINATOR key term
    swarm_contract_path = PROMPTS_DIR / SWARM_CONTRACT_FILE
    if swarm_contract_path.exists():
        if not _check_file_contains(swarm_contract_path, SWARM_REQUIRED_TERM):
            fail(
                f"{SWARM_CONTRACT_FILE} does not contain '{SWARM_REQUIRED_TERM}' "
                f"(swarm contract must define coordinator role)"
            )
    else:
        fail(f"Swarm contract file missing: {swarm_contract_path}")

    # Check 13: loop-runbook.md references loop-signal
    runbook_path = PROMPTS_DIR / RUNBOOK_FILE
    if runbook_path.exists():
        if not _check_file_contains(runbook_path, RUNBOOK_REQUIRED_TERM):
            fail(
                f"{RUNBOOK_FILE} does not reference '{RUNBOOK_REQUIRED_TERM}' "
                f"(runbook must describe loop-signal.yaml outputs)"
            )
    else:
        fail(f"Runbook file missing: {runbook_path}")

    # Check 14: loop-evidence-contract.md defines evidence levels
    evidence_contract_path = PROMPTS_DIR / EVIDENCE_CONTRACT_FILE
    if evidence_contract_path.exists():
        if not _check_file_contains(evidence_contract_path, EVIDENCE_REQUIRED_TERM):
            fail(
                f"{EVIDENCE_CONTRACT_FILE} does not contain '{EVIDENCE_REQUIRED_TERM}' "
                f"(evidence contract must define evidence levels)"
            )
    else:
        fail(f"Evidence contract file missing: {evidence_contract_path}")

    # Check 15 (optional): run directory structure
    if args.run_dir is not None:
        if not args.run_dir.is_dir():
            fail(f"Run directory does not exist: {args.run_dir}")
        else:
            rc = _check_run_dir(args.run_dir)
            if rc != 0:
                failures.append(f"Run directory validation failed: {args.run_dir}")

    # Report results
    if failures:
        print(f"VALIDATION FAILED ({len(failures)} issue(s)):")
        for i, f in enumerate(failures, 1):
            print(f"  {i}. {f}")
        return 1

    print("ALL CHECKS PASSED")
    if args.run_dir:
        print(f"  Run directory structure valid: {args.run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
