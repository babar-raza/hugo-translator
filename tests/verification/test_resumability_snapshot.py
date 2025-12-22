"""Tests for resumability snapshot artifacts."""
import json
from pathlib import Path

STATE_PATH = Path("plans/user-guide/state.json")
README_PATH = Path("plans/user-guide/README.md")


def validate_state(data: dict) -> list[str]:
    errors: list[str] = []
    open_issues = data.get("open_issues", [])
    if "docs/user-guide pending" not in open_issues:
        errors.append("Missing docs/user-guide pending in open_issues")
    return errors


def validate_readme(text: str) -> list[str]:
    errors: list[str] = []
    if "Docs status: docs/user-guide pages are pending." not in text:
        errors.append("Missing docs pending status in README")
    return errors


def test_state_json_contains_docs_pending():
    assert STATE_PATH.exists(), f"Missing {STATE_PATH}"
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    errors = validate_state(data)
    assert not errors, f"State validation errors: {errors}"


def test_readme_contains_docs_pending():
    assert README_PATH.exists(), f"Missing {README_PATH}"
    text = README_PATH.read_text(encoding="utf-8")
    errors = validate_readme(text)
    assert not errors, f"README validation errors: {errors}"


def test_validators_catch_missing_fields():
    bad_state = {"open_issues": []}
    assert validate_state(bad_state), "Expected state errors"

    bad_readme = "# User Guide Plan"
    assert validate_readme(bad_readme), "Expected README errors"
