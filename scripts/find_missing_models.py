#!/usr/bin/env python3
"""Find models needed to cover all 36 languages."""
import importlib.util
import json
import sys
from pathlib import Path


def load_module_directly(module_name, module_path):
    """Load a module directly from file path."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    # Load modules directly
    project_root = Path(__file__).parent.parent

    coverage_path = project_root / "src" / "benchmarking" / "language_coverage.py"
    coverage_mod = load_module_directly("language_coverage", coverage_path)
    check_language_coverage = coverage_mod.check_language_coverage

    gap_analysis_path = project_root / "src" / "benchmarking" / "model_gap_analysis.py"
    gap_mod = load_module_directly("model_gap_analysis", gap_analysis_path)
    analyze_gaps = gap_mod.analyze_gaps

    # Get current coverage
    report = check_language_coverage(
        "config/model_registry.yaml",
        "config/target_languages.yaml"
    )

    if report.is_complete():
        print("✓ All languages already covered!")
        return 0

    print(f"Found {len(report.missing_languages)} missing languages:")
    for lang in sorted(report.missing_languages):
        print(f"  - {lang}")
    print()

    # Analyze gaps
    recommendations = analyze_gaps(
        report.models_per_language,
        report.missing_languages
    )

    # Output recommendations
    print("Recommended model downloads:")
    print("=" * 60)

    total_size = 0
    for rec in recommendations:
        print(f"\nPriority {rec.priority}: {rec.model_id}")
        print(f"  HuggingFace: {rec.hf_model_id}")
        print(f"  Size: {rec.size_mb} MB")
        print(f"  Languages: {len(rec.languages_covered)}")
        print(f"  License: {rec.license}")
        print(f"  Device: {rec.optimal_device}")
        total_size += rec.size_mb

    print(f"\nTotal download size: {total_size} MB ({total_size/1024:.1f} GB)")

    # Ensure data directory exists
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    # JSON output
    output_file = data_dir / "model_download_plan.json"
    with open(output_file, "w") as f:
        json.dump([{
            "model_id": r.model_id,
            "hf_model_id": r.hf_model_id,
            "size_mb": r.size_mb,
            "languages": r.languages_covered,
            "priority": r.priority,
            "backend": r.backend,
            "optimal_device": r.optimal_device,
            "license": r.license
        } for r in recommendations], f, indent=2)

    print(f"\n✓ Download plan saved to {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
