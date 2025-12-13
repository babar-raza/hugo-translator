#!/usr/bin/env python3
"""
Translation Quality Validation Script

Validates translated Hugo files for quality issues including:
- Malformed frontmatter YAML
- Missing or extra placeholders
- Unbalanced code blocks
- Broken link structure
- Heading/list structure mismatches

Usage:
    python scripts/validate_translation_quality.py --input translated/ --output reports/quality.json
    python scripts/validate_translation_quality.py --source samples/ --translation output/ --lang es
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.validation.quality_validator import QualityValidator
from src.translation_engine.validation import ValidationSeverity


def format_console_output(results: Dict[str, any], verbose: bool = False) -> str:
    """
    Format validation results for console output.

    Args:
        results: Validation results dictionary
        verbose: Whether to show all details

    Returns:
        Formatted string for console
    """
    output = []
    output.append("=" * 80)
    output.append("TRANSLATION QUALITY VALIDATION REPORT")
    output.append("=" * 80)

    summary = results.get("summary", {})
    output.append(f"\nTotal Files: {summary.get('total_files', 0)}")
    output.append(f"Files with Errors: {summary.get('files_with_errors', 0)}")
    output.append(f"Files with Warnings: {summary.get('files_with_warnings', 0)}")
    output.append(f"Clean Files: {summary.get('clean_files', 0)}")
    output.append(f"\nTotal Issues: {summary.get('total_issues', 0)}")
    output.append(f"  Errors: {summary.get('total_errors', 0)}")
    output.append(f"  Warnings: {summary.get('total_warnings', 0)}")
    output.append(f"  Info: {summary.get('total_info', 0)}")

    # Show files with errors
    if results.get("files_with_issues"):
        output.append(f"\n{'-' * 80}")
        output.append("FILES WITH ISSUES")
        output.append(f"{'-' * 80}")

        for file_path, file_result in results["files_with_issues"].items():
            error_count = file_result.get("error_count", 0)
            warning_count = file_result.get("warning_count", 0)
            info_count = file_result.get("info_count", 0)

            output.append(f"\n{file_path}")
            output.append(f"  Errors: {error_count}, Warnings: {warning_count}, Info: {info_count}")

            if verbose or error_count > 0:
                for issue in file_result.get("issues", []):
                    severity_marker = {
                        "ERROR": "❌",
                        "WARNING": "⚠️",
                        "INFO": "ℹ️"
                    }.get(issue["severity"], "•")

                    output.append(f"  {severity_marker} [{issue['severity']}] {issue['message']}")
                    if issue.get("location"):
                        output.append(f"      Location: {issue['location']}")

    # Quality score
    quality_score = results.get("quality_score", 0)
    output.append(f"\n{'-' * 80}")
    output.append(f"QUALITY SCORE: {quality_score:.1f}%")

    if quality_score >= 90:
        output.append("Status: ✓ EXCELLENT")
    elif quality_score >= 75:
        output.append("Status: ✓ GOOD")
    elif quality_score >= 50:
        output.append("Status: ⚠ NEEDS IMPROVEMENT")
    else:
        output.append("Status: ❌ POOR")

    output.append("=" * 80)

    return "\n".join(output)


def calculate_quality_score(summary: Dict) -> float:
    """
    Calculate overall quality score (0-100).

    Args:
        summary: Summary statistics

    Returns:
        Quality score percentage
    """
    total_files = summary.get("total_files", 0)
    if total_files == 0:
        return 100.0

    clean_files = summary.get("clean_files", 0)
    files_with_errors = summary.get("files_with_errors", 0)
    files_with_warnings = summary.get("files_with_warnings", 0)

    # Calculate score: clean files get 100%, files with warnings get 50%, files with errors get 0%
    score = (
        (clean_files * 100.0) +
        ((files_with_warnings - files_with_errors) * 50.0)
    ) / total_files

    return max(0.0, min(100.0, score))


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description="Validate translation quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--source",
        type=Path,
        help="Source directory containing original files",
    )

    parser.add_argument(
        "--translation",
        type=Path,
        help="Translation directory containing translated files",
    )

    parser.add_argument(
        "--input",
        type=Path,
        help="Input directory (if source/translation dirs have matching structure)",
    )

    parser.add_argument(
        "--lang",
        type=str,
        default="",
        help="Target language code (for context)",
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output file for JSON report",
    )

    parser.add_argument(
        "--recursive",
        action="store_true",
        default=True,
        help="Recursively process subdirectories (default: True)",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show all issues including warnings and info",
    )

    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with non-zero code if any errors found",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.input:
        # Single directory mode - assume it contains translations
        source_dir = args.input
        translation_dir = args.input
    elif args.source and args.translation:
        source_dir = args.source
        translation_dir = args.translation
    else:
        print("Error: Either --input or both --source and --translation must be specified")
        return 1

    if not translation_dir.exists():
        print(f"Error: Translation directory not found: {translation_dir}")
        return 1

    print("=" * 80)
    print("TRANSLATION QUALITY VALIDATION")
    print("=" * 80)
    print(f"Translation directory: {translation_dir}")
    if source_dir != translation_dir:
        print(f"Source directory: {source_dir}")
    if args.lang:
        print(f"Target language: {args.lang}")
    print(f"Output: {args.output}")
    print()

    # Initialize validator
    validator = QualityValidator(base_dir=translation_dir)

    # Validate files
    print("Validating files...")
    start_time = time.time()

    if source_dir == translation_dir:
        # Single directory - validate all markdown files
        validation_results = {}
        for md_file in translation_dir.glob("**/*.md" if args.recursive else "*.md"):
            # Validate against itself (only structural checks)
            result = validator.validate_content(
                md_file.read_text(encoding='utf-8'),
                md_file.read_text(encoding='utf-8'),
                context={"file": str(md_file), "target_lang": args.lang}
            )
            validation_results[str(md_file)] = result
    else:
        # Two directories - validate translations against sources
        validation_results = validator.validate_directory(
            source_dir,
            translation_dir,
            args.lang or "unknown",
            recursive=args.recursive,
        )

    elapsed_time = time.time() - start_time
    print(f"Validated {len(validation_results)} files in {elapsed_time:.2f}s")

    # Process results
    summary = {
        "total_files": len(validation_results),
        "files_with_errors": 0,
        "files_with_warnings": 0,
        "clean_files": 0,
        "total_issues": 0,
        "total_errors": 0,
        "total_warnings": 0,
        "total_info": 0,
    }

    files_with_issues = {}

    for file_path, result in validation_results.items():
        error_count = result.error_count
        warning_count = result.warning_count
        info_count = result.info_count

        summary["total_issues"] += len(result.issues)
        summary["total_errors"] += error_count
        summary["total_warnings"] += warning_count
        summary["total_info"] += info_count

        if error_count > 0:
            summary["files_with_errors"] += 1
        if warning_count > 0:
            summary["files_with_warnings"] += 1
        if error_count == 0 and warning_count == 0:
            summary["clean_files"] += 1

        if len(result.issues) > 0:
            files_with_issues[file_path] = {
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "issues": [
                    {
                        "severity": issue.severity.value.upper(),
                        "validator": issue.validator,
                        "message": issue.message,
                        "location": issue.location,
                        "details": issue.details,
                    }
                    for issue in result.issues
                ]
            }

    # Calculate quality score
    quality_score = calculate_quality_score(summary)

    # Build final report
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_dir": str(source_dir) if source_dir != translation_dir else None,
        "translation_dir": str(translation_dir),
        "target_lang": args.lang,
        "validation_time_seconds": elapsed_time,
        "summary": summary,
        "quality_score": quality_score,
        "files_with_issues": files_with_issues,
    }

    # Write JSON report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nJSON report saved to: {args.output}")

    # Print console summary
    print()
    print(format_console_output(report, verbose=args.verbose))

    # Return appropriate exit code
    if args.fail_on_error and summary["total_errors"] > 0:
        print(f"\n❌ Validation failed: {summary['total_errors']} errors found")
        return 1

    if summary["total_errors"] == 0:
        print("\n✓ Validation passed: No critical errors found")
        return 0
    else:
        print(f"\n⚠ Validation completed with {summary['total_errors']} errors")
        return 0 if not args.fail_on_error else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nValidation interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
