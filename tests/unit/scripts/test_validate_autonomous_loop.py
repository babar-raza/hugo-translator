"""Unit tests for scripts/quality/validate_autonomous_loop.py.

Tests focus on Check 12 (loop-swarm-contract.md must contain COORDINATOR)
with two behavioural cases: pass (term present) and fail (file absent or
term missing).  A shared fixture builds a fully-valid prompts directory so
that only the aspect under test is varied.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import scripts.quality.validate_autonomous_loop as validator_module
from scripts.quality.validate_autonomous_loop import _check_file_contains, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORCHESTRATOR_CONTENT = (
    "# Autonomous Green Loop\n"
    "harden-plan.md execute-plan.md sprint-audit.md expand-plan.md\n"
    "loop-signal.yaml taskcard-registry.yaml\n"
)

_LOOP_SECTION = "## AUTONOMOUS LOOP OPERATION\nThis section is present.\n"

_STATE_MACHINE_CONTENT = (
    "INITIATED HARDENING HARDENED EXECUTING EXECUTED "
    "AUDITING AUDIT_COMPLETE EXPANDING EXPANDED GREEN "
    "BLOCKED_EXTERNAL MAX_ITER_REACHED\n"
)


def _build_valid_prompts_dir(base: Path) -> Path:
    """Create a prompts directory satisfying all checks 1-11 and 13-14."""
    d = base / "autonomous"
    d.mkdir(parents=True)

    # Check 1 — all 8 new prompt files
    (d / "autonomous-green-loop.md").write_text(_ORCHESTRATOR_CONTENT)
    (d / "loop-state-machine.md").write_text(_STATE_MACHINE_CONTENT)
    (d / "loop-runbook.md").write_text("# Runbook\nloop-signal here.\n")
    (d / "loop-audit-contract.md").write_text(
        "blocking_gaps GREEN_STOP BLOCKING_GAP\n"
    )
    (d / "loop-idempotency-contract.md").write_text("MAX_ITER CLOSED\n")
    (d / "loop-taskcard-contract.md").write_text("taskcard-registry.yaml\n")
    (d / "loop-evidence-contract.md").write_text("Evidence Level: 3\n")
    # loop-swarm-contract.md intentionally omitted — tests supply their own

    # Check 2 — 4 enhanced prompts with AUTONOMOUS LOOP OPERATION
    for fname in ("harden-plan.md", "execute-plan.md", "sprint-audit.md", "expand-plan.md"):
        (d / fname).write_text(
            f"# {fname}\n{_LOOP_SECTION}"
            + ("audit-report-iter\n" if fname == "expand-plan.md" else "")
            + ("loop-signal.yaml\n" if fname == "sprint-audit.md" else "")
        )

    return d


# ---------------------------------------------------------------------------
# Unit tests for _check_file_contains
# ---------------------------------------------------------------------------


def test_check_file_contains_present(tmp_path: Path) -> None:
    f = tmp_path / "contract.md"
    f.write_text("# Swarm Contract\nCOORDINATOR role is defined here.\n")
    assert _check_file_contains(f, "COORDINATOR") is True


def test_check_file_contains_absent(tmp_path: Path) -> None:
    f = tmp_path / "contract.md"
    f.write_text("# Swarm Contract\nNo key term here.\n")
    assert _check_file_contains(f, "COORDINATOR") is False


def test_check_file_contains_missing_file(tmp_path: Path) -> None:
    f = tmp_path / "nonexistent.md"
    assert _check_file_contains(f, "COORDINATOR") is False


# ---------------------------------------------------------------------------
# Check 12 behavioural tests
# ---------------------------------------------------------------------------


def test_check12_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Check 12 passes when loop-swarm-contract.md contains COORDINATOR."""
    prompts_dir = _build_valid_prompts_dir(tmp_path)
    (prompts_dir / "loop-swarm-contract.md").write_text(
        "# Swarm Contract\nCOORDINATOR is responsible for task dispatch.\n"
    )
    monkeypatch.setattr(validator_module, "PROMPTS_DIR", prompts_dir)
    monkeypatch.setattr(sys, "argv", ["validate_autonomous_loop.py"])

    result = main()

    assert result == 0


def test_check12_fail_term_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Check 12 fails when loop-swarm-contract.md exists but lacks COORDINATOR."""
    prompts_dir = _build_valid_prompts_dir(tmp_path)
    (prompts_dir / "loop-swarm-contract.md").write_text(
        "# Swarm Contract\nThis contract defines agent roles.\n"
    )
    monkeypatch.setattr(validator_module, "PROMPTS_DIR", prompts_dir)
    monkeypatch.setattr(sys, "argv", ["validate_autonomous_loop.py"])

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    assert "COORDINATOR" in captured.out
    assert "loop-swarm-contract.md" in captured.out


def test_check12_fail_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Check 12 fails when loop-swarm-contract.md is absent entirely."""
    prompts_dir = _build_valid_prompts_dir(tmp_path)
    # Do NOT create loop-swarm-contract.md
    monkeypatch.setattr(validator_module, "PROMPTS_DIR", prompts_dir)
    monkeypatch.setattr(sys, "argv", ["validate_autonomous_loop.py"])

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    assert "Swarm contract file missing" in captured.out
