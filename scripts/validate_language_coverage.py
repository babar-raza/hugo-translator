#!/usr/bin/env python3
"""Validate that all 36 target languages have model coverage."""
import json
import sys
from pathlib import Path
import importlib.util

# Load language_coverage module directly without triggering __init__.py
module_path = Path(__file__).parent.parent / "src" / "benchmarking" / "language_coverage.py"
spec = importlib.util.spec_from_file_location("language_coverage", module_path)
language_coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(language_coverage)

check_language_coverage = language_coverage.check_language_coverage


def main():
    report = check_language_coverage(
        "config/model_registry.yaml",
        "config/target_languages.yaml"
    )

    print(f"Language Coverage Report")
    print(f"=" * 60)
    print(f"Total languages: {report.total_languages}")
    print(f"Covered: {len(report.covered_languages)} ({report.coverage_percentage:.1f}%)")
    print(f"Missing: {len(report.missing_languages)}")
    print()

    if report.missing_languages:
        print("Missing languages:")
        for lang in sorted(report.missing_languages):
            print(f"  - {lang}")
        print()

    # Show models per language
    print("Models per language:")
    for lang in sorted(report.models_per_language.keys()):
        models = report.models_per_language[lang]
        if models:
            print(f"  {lang}: {len(models)} model(s) - {', '.join(models[:3])}")
        else:
            print(f"  {lang}: NO MODELS ❌")

    # Exit code based on coverage
    if report.coverage_percentage >= 90:
        print(f"\n✓ Coverage check passed ({report.coverage_percentage:.1f}%)")
        return 0
    else:
        print(f"\n✗ Coverage check failed ({report.coverage_percentage:.1f}% < 90%)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
