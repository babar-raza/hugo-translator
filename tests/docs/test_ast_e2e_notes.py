"""Tests for AST E2E warning interpretation notes."""

from pathlib import Path

NOTES_PATH = Path("reports/user-guide/ast_e2e_notes.md")
TROUBLE_PATH = Path("docs/user-guide/troubleshooting.md")


def validate_notes(text: str) -> list[str]:
    errors: list[str] = []
    required = [
        "AST E2E Warning Interpretation",
        "Language purity",
        "Mitigation",
        "Reproduction",
    ]
    for item in required:
        if item not in text:
            errors.append(f"Missing '{item}' in notes")
    return errors


def validate_troubleshooting(text: str) -> list[str]:
    errors: list[str] = []
    required = [
        "AST E2E language purity fallback warnings",
        "Symptoms",
        "Cause",
        "Mitigation",
    ]
    for item in required:
        if item not in text:
            errors.append(f"Missing '{item}' in troubleshooting")
    return errors


def test_notes_file_present_and_valid():
    assert NOTES_PATH.exists(), f"Missing {NOTES_PATH}"
    text = NOTES_PATH.read_text(encoding="utf-8")
    errors = validate_notes(text)
    assert not errors, f"Notes validation errors: {errors}"


def test_troubleshooting_file_present_and_valid():
    assert TROUBLE_PATH.exists(), f"Missing {TROUBLE_PATH}"
    text = TROUBLE_PATH.read_text(encoding="utf-8")
    errors = validate_troubleshooting(text)
    assert not errors, f"Troubleshooting validation errors: {errors}"


def test_validators_catch_missing_sections():
    assert validate_notes("# Notes"), "Expected notes validation errors"
    assert validate_troubleshooting("# Troubleshooting"), "Expected troubleshooting errors"
