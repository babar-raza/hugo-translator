#!/usr/bin/env python3
"""
SD-05: Post-Regeneration Structure Validation Script.

Run this script after regenerating BG translations to verify
that the structure preservation improvements are working.

Usage:
    python scripts/validate_bg_structure.py

Expected Results:
    - Average drift < 20% (down from 47%)
    - Comments preserved (# Static, # Head, etc.)
    - Literal block scalars preserved (|)
"""
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class StructureIssue:
    """A single structural issue."""
    issue_type: str
    description: str
    severity: str  # 'warning' or 'error'


@dataclass
class StructureValidationResult:
    """Result of structure validation."""
    source_lines: int
    target_lines: int
    line_drift_percent: float
    issues: List[StructureIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.line_drift_percent < 20.0 and not any(
            i.severity == 'error' for i in self.issues
        )


class StructureValidator:
    """Validates structural parity between source and target files."""

    def __init__(self, warn_threshold: float = 10.0, error_threshold: float = 20.0):
        self.warn_threshold = warn_threshold
        self.error_threshold = error_threshold

    def validate(
        self,
        source_content: str,
        target_content: str,
    ) -> StructureValidationResult:
        """Compare source and target structure."""
        source_lines = len(source_content.strip().split('\n'))
        target_lines = len(target_content.strip().split('\n'))

        drift = abs(source_lines - target_lines) / source_lines * 100

        issues = []

        # Check line count drift
        if drift > self.error_threshold:
            issues.append(StructureIssue(
                issue_type='line_count_drift',
                description=f'Line count drift {drift:.1f}% exceeds error threshold {self.error_threshold}%',
                severity='error'
            ))
        elif drift > self.warn_threshold:
            issues.append(StructureIssue(
                issue_type='line_count_drift',
                description=f'Line count drift {drift:.1f}% exceeds warning threshold {self.warn_threshold}%',
                severity='warning'
            ))

        # Check for comment preservation
        source_comments = re.findall(r'^#\s*\w+', source_content, re.MULTILINE)
        target_comments = re.findall(r'^#\s*\w+', target_content, re.MULTILINE)

        missing_comments = set(source_comments) - set(target_comments)
        for comment in missing_comments:
            issues.append(StructureIssue(
                issue_type='missing_comment',
                description=f'Comment "{comment}" from source not found in target',
                severity='warning'
            ))

        # Check for literal block usage
        source_literals = source_content.count(': |')
        target_literals = target_content.count(': |')

        if source_literals > 0 and target_literals < source_literals:
            issues.append(StructureIssue(
                issue_type='literal_block_loss',
                description=f'Source has {source_literals} literal blocks, target has {target_literals}',
                severity='warning'
            ))

        return StructureValidationResult(
            source_lines=source_lines,
            target_lines=target_lines,
            line_drift_percent=drift,
            issues=issues,
        )


def main():
    """Run validation on all BG translation files."""

    # Paths
    en_dir = Path('D:/onedrive/Documents/GitHub/aspose.net/content/products.aspose.net/slides/en')
    bg_dir = Path('D:/onedrive/Documents/GitHub/aspose.net/content/products.aspose.net/slides/bg')

    if not en_dir.exists():
        print(f"Error: EN directory not found: {en_dir}")
        sys.exit(1)

    if not bg_dir.exists():
        print(f"Error: BG directory not found: {bg_dir}")
        sys.exit(1)

    print("=" * 70)
    print("SD-05: Post-Regeneration Structure Validation")
    print("=" * 70)
    print()

    validator = StructureValidator()

    results = []
    total_drift = 0
    total_issues = 0

    for en_file in sorted(en_dir.glob('**/_index.md')):
        relative = en_file.relative_to(en_dir)
        bg_file = bg_dir / relative

        if not bg_file.exists():
            print(f"  MISSING: {relative}")
            continue

        en_content = en_file.read_text(encoding='utf-8')
        bg_content = bg_file.read_text(encoding='utf-8')

        result = validator.validate(en_content, bg_content)
        results.append((relative, result))
        total_drift += result.line_drift_percent
        total_issues += len(result.issues)

        status = 'PASS' if result.is_valid else 'FAIL'
        print(f"{status} {relative}: {result.line_drift_percent:.1f}% drift, {len(result.issues)} issues")

        # Show issues if any
        for issue in result.issues:
            print(f"     [{issue.severity}] {issue.issue_type}: {issue.description}")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if results:
        avg_drift = total_drift / len(results)
        pass_count = sum(1 for _, r in results if r.is_valid)

        print(f"Files checked: {len(results)}")
        print(f"Files passing: {pass_count}/{len(results)} ({pass_count/len(results)*100:.0f}%)")
        print(f"Average drift: {avg_drift:.1f}%")
        print(f"Total issues: {total_issues}")
        print()

        if avg_drift < 20:
            print("SUCCESS: Average drift is within acceptable range (<20%)")
            print("         Structure preservation improvements are working!")
        else:
            print("WARNING: Average drift is still high (>20%)")
            print("         Review the implementation or regenerate translations")
    else:
        print("No files found to validate.")

    print()


if __name__ == "__main__":
    main()
