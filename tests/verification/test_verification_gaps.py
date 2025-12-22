"""Tests for verification gaps backlog."""
import json
from pathlib import Path

INVENTORY_PATH = Path("reports/user-guide/entrypoints_inventory.md")
BACKLOG_PATH = Path("reports/user-guide/verification_gaps.md")
STATE_PATH = Path("plans/user-guide/state.json")


def parse_inventory_unverified() -> set[str]:
    lines = INVENTORY_PATH.read_text(encoding="utf-8").splitlines()
    names = set()
    for line in lines:
        if not line.startswith("|"):
            continue
        if line.strip().startswith("| ---"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 6:
            continue
        name = cols[0]
        verified = cols[5]
        if name.lower() == "name":
            continue
        if verified.upper() == "N":
            names.add(name)
    return names


def parse_backlog_unverified() -> set[str]:
    text = BACKLOG_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    names = set()
    in_section = False
    for line in lines:
        if line.strip() == "## All unverified entrypoints":
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                names.add(line[2:].strip())
    return names


def validate_backlog(text: str, expected: set[str]) -> list[str]:
    errors: list[str] = []
    if "## All unverified entrypoints" not in text:
        errors.append("Missing all-unverified section")
        return errors
    actual = parse_backlog_unverified()
    missing = sorted(expected - actual)
    if missing:
        errors.append(f"Missing entries: {missing[:5]}")
    return errors


def test_backlog_contains_all_unverified_entrypoints():
    assert INVENTORY_PATH.exists(), f"Missing {INVENTORY_PATH}"
    assert BACKLOG_PATH.exists(), f"Missing {BACKLOG_PATH}"
    expected = parse_inventory_unverified()
    actual = parse_backlog_unverified()
    missing = expected - actual
    extra = actual - expected
    assert not missing, f"Backlog missing {len(missing)} entries"
    assert not extra, f"Backlog has extra {len(extra)} entries"


def test_backlog_validator_catches_missing_entries():
    expected = {"a", "b"}
    bad_text = "# Verification Gaps Backlog\n\n## All unverified entrypoints\n- a\n"
    errors = validate_backlog(bad_text, expected)
    assert errors, "Expected errors for missing entries"


def test_state_json_includes_backlog_action():
    assert STATE_PATH.exists(), f"Missing {STATE_PATH}"
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    actions = data.get("next_actions", [])
    assert any("verification_gaps" in action for action in actions), "Missing backlog action in next_actions"
