"""Tests for progress summary artifact."""
from pathlib import Path

SUMMARY_PATH = Path("reports/user-guide/progress_summary.md")

REQUIRED_HEADERS = [
    "## Verified Commands",
    "## Health Check Outcome",
]

REQUIRED_SNIPPETS = [
    "translate-hugo.exe",
    "-m src.cli",
    "run_translation.py",
    "scripts\\batch_translate.py",
    "scripts\\validate_ast_translation.py",
    "scripts\\validate_ast_e2e.py",
    "toggle_ast_translation.py",
    "diagnose_nllb_tokenizer.py",
    "scripts\\health_check.py",
]


def validate_summary(text: str) -> list[str]:
    errors: list[str] = []

    for header in REQUIRED_HEADERS:
        if header not in text:
            errors.append(f"Missing header: {header}")

    for snippet in REQUIRED_SNIPPETS:
        if snippet not in text:
            errors.append(f"Missing snippet: {snippet}")

    if "Status: healthy" not in text:
        errors.append("Missing health status")

    return errors


def test_progress_summary_exists_and_valid():
    assert SUMMARY_PATH.exists(), f"Missing {SUMMARY_PATH}"
    text = SUMMARY_PATH.read_text(encoding="utf-8")
    errors = validate_summary(text)
    assert not errors, f"Progress summary validation errors: {errors}"


def test_progress_summary_validator_catches_missing_sections():
    bad_text = "# Progress Summary\n\n## Verified Commands\n"
    errors = validate_summary(bad_text)
    assert errors, "Expected errors for missing sections/snippets"
