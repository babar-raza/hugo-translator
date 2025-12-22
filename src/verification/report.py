"""
Verification reporting module.

Generates human-readable and machine-readable reports from verification results.
Supports JSON and Markdown output formats.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .checks.base import VerificationResult


class VerificationReporter:
    """
    Generates verification reports in multiple formats.

    Supports:
    - JSON: Machine-readable format for automation
    - Markdown: Human-readable format for documentation
    """

    def __init__(self, include_timestamps: bool = True):
        """
        Initialize reporter.

        Args:
            include_timestamps: Whether to include timestamps in reports
        """
        self.include_timestamps = include_timestamps

    def to_json(
        self,
        results: List[Tuple[Path, VerificationResult]],
        include_issues: bool = True,
    ) -> str:
        """
        Generate JSON report from verification results.

        Args:
            results: List of (file_path, VerificationResult) tuples
            include_issues: Whether to include detailed issue information

        Returns:
            JSON-formatted string

        Example:
            {
              "timestamp": "2025-12-15T10:30:00Z",
              "summary": {
                "total_files": 10,
                "passed": 8,
                "failed": 2,
                "total_errors": 5,
                "total_warnings": 3,
                "total_info": 1
              },
              "files": [
                {
                  "path": "slides/de/presentation-merger/_index.md",
                  "passed": false,
                  "error_count": 2,
                  "warning_count": 1,
                  "info_count": 0,
                  "issues": [...]
                }
              ]
            }
        """
        report: Dict[str, Any] = {}

        # Add timestamp
        if self.include_timestamps:
            report["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Calculate summary statistics
        total_files = len(results)
        passed_files = sum(1 for _, result in results if result.passed)
        failed_files = total_files - passed_files
        total_errors = sum(result.error_count for _, result in results)
        total_warnings = sum(result.warning_count for _, result in results)
        total_info = sum(result.info_count for _, result in results)

        report["summary"] = {
            "total_files": total_files,
            "passed": passed_files,
            "failed": failed_files,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "total_info": total_info,
        }

        # Add per-file results
        files_data = []
        for file_path, result in results:
            file_data = {
                "path": str(file_path),
                "passed": result.passed,
                "error_count": result.error_count,
                "warning_count": result.warning_count,
                "info_count": result.info_count,
            }

            # Include check results
            if result.check_results:
                file_data["check_results"] = result.check_results

            # Include detailed issues if requested
            if include_issues and result.issues:
                file_data["issues"] = [issue.to_dict() for issue in result.issues]

            # Include metadata
            if result.metadata:
                file_data["metadata"] = result.metadata

            files_data.append(file_data)

        report["files"] = files_data

        return json.dumps(report, indent=2, ensure_ascii=False)

    def to_markdown(
        self,
        results: List[Tuple[Path, VerificationResult]],
        include_issues: bool = True,
    ) -> str:
        """
        Generate Markdown report from verification results.

        Args:
            results: List of (file_path, VerificationResult) tuples
            include_issues: Whether to include detailed issue information

        Returns:
            Markdown-formatted string

        Example:
            # Verification Report

            **Generated**: 2025-12-15T10:30:00Z

            ## Summary

            - **Total Files**: 10
            - **Passed**: 8 (80.0%)
            - **Failed**: 2 (20.0%)
            - **Total Errors**: 5
            - **Total Warnings**: 3

            ## Files

            ### slides/de/presentation-merger/_index.md

            **Status**: FAILED
            - Errors: 2
            - Warnings: 1

            #### Issues

            1. **ERROR** [language_detection] `body.block[0].title_left`
               Expected de, detected en
        """
        lines = []

        # Header
        lines.append("# Verification Report")
        lines.append("")

        # Timestamp
        if self.include_timestamps:
            timestamp = datetime.utcnow().isoformat() + "Z"
            lines.append(f"**Generated**: {timestamp}")
            lines.append("")

        # Summary section
        total_files = len(results)
        passed_files = sum(1 for _, result in results if result.passed)
        failed_files = total_files - passed_files
        total_errors = sum(result.error_count for _, result in results)
        total_warnings = sum(result.warning_count for _, result in results)
        total_info = sum(result.info_count for _, result in results)

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Total Files**: {total_files}")
        if total_files > 0:
            pass_rate = (passed_files / total_files) * 100
            fail_rate = (failed_files / total_files) * 100
            lines.append(f"- **Passed**: {passed_files} ({pass_rate:.1f}%)")
            lines.append(f"- **Failed**: {failed_files} ({fail_rate:.1f}%)")
        else:
            lines.append("- **Passed**: 0")
            lines.append("- **Failed**: 0")

        lines.append(f"- **Total Errors**: {total_errors}")
        lines.append(f"- **Total Warnings**: {total_warnings}")
        lines.append(f"- **Total Info**: {total_info}")
        lines.append("")

        # Files section
        if results:
            lines.append("## Files")
            lines.append("")

            for file_path, result in results:
                # File header
                lines.append(f"### {file_path}")
                lines.append("")

                # Status
                status = "PASSED" if result.passed else "FAILED"
                status_emoji = "✓" if result.passed else "✗"
                lines.append(f"**Status**: {status_emoji} {status}")

                # Counts
                if result.error_count > 0 or result.warning_count > 0 or result.info_count > 0:
                    lines.append("")
                    if result.error_count > 0:
                        lines.append(f"- **Errors**: {result.error_count}")
                    if result.warning_count > 0:
                        lines.append(f"- **Warnings**: {result.warning_count}")
                    if result.info_count > 0:
                        lines.append(f"- **Info**: {result.info_count}")

                # Check results summary
                if result.check_results:
                    lines.append("")
                    lines.append("**Checks Run**:")
                    for check_name, check_result in result.check_results.items():
                        passed = check_result.get("passed", False)
                        check_emoji = "✓" if passed else "✗"
                        lines.append(f"- {check_emoji} {check_name}")

                # Detailed issues
                if include_issues and result.issues:
                    lines.append("")
                    lines.append("#### Issues")
                    lines.append("")

                    for i, issue in enumerate(result.issues, 1):
                        severity_upper = issue.severity.upper()
                        lines.append(
                            f"{i}. **{severity_upper}** [{issue.check_name}] `{issue.location}`"
                        )
                        lines.append(f"   {issue.message}")

                        if issue.source_text:
                            truncated_source = issue.source_text[:100]
                            if len(issue.source_text) > 100:
                                truncated_source += "..."
                            lines.append(f"   - Source: `{truncated_source}`")

                        if issue.translated_text:
                            truncated_translated = issue.translated_text[:100]
                            if len(issue.translated_text) > 100:
                                truncated_translated += "..."
                            lines.append(f"   - Translated: `{truncated_translated}`")

                        lines.append("")

                lines.append("")

        return "\n".join(lines)

    def to_console_summary(
        self,
        results: List[Tuple[Path, VerificationResult]],
    ) -> str:
        """
        Generate concise console summary.

        Args:
            results: List of (file_path, VerificationResult) tuples

        Returns:
            Console-formatted summary string

        Example:
            Verification Summary:
              Files: 10 (8 passed, 2 failed)
              Issues: 5 errors, 3 warnings, 1 info
        """
        total_files = len(results)
        passed_files = sum(1 for _, result in results if result.passed)
        failed_files = total_files - passed_files
        total_errors = sum(result.error_count for _, result in results)
        total_warnings = sum(result.warning_count for _, result in results)
        total_info = sum(result.info_count for _, result in results)

        lines = [
            "Verification Summary:",
            f"  Files: {total_files} ({passed_files} passed, {failed_files} failed)",
            f"  Issues: {total_errors} errors, {total_warnings} warnings, {total_info} info",
        ]

        return "\n".join(lines)


def write_report(
    report_path: Path,
    results: List[Tuple[Path, VerificationResult]],
    format_type: str = "auto",
    include_issues: bool = True,
) -> None:
    """
    Write verification report to file.

    Args:
        report_path: Path to output file
        results: List of (file_path, VerificationResult) tuples
        format_type: Output format ("json", "markdown", or "auto" to detect from extension)
        include_issues: Whether to include detailed issue information

    Raises:
        ValueError: If format_type is invalid or cannot be auto-detected
    """
    # Auto-detect format from extension
    if format_type == "auto":
        suffix = report_path.suffix.lower()
        if suffix == ".json":
            format_type = "json"
        elif suffix in [".md", ".markdown"]:
            format_type = "markdown"
        else:
            raise ValueError(
                f"Cannot auto-detect format from extension '{suffix}'. "
                "Use .json or .md extension, or specify format_type explicitly."
            )

    # Generate report
    reporter = VerificationReporter()

    if format_type == "json":
        content = reporter.to_json(results, include_issues=include_issues)
    elif format_type == "markdown":
        content = reporter.to_markdown(results, include_issues=include_issues)
    else:
        raise ValueError(f"Invalid format_type: {format_type}. Use 'json' or 'markdown'.")

    # Write to file
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
