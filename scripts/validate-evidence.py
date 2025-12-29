#!/usr/bin/env python3
"""
Evidence citation validator for Hugo Translation System specs.

Validates that evidence citations in specs reference actual code locations
that still exist and are within file bounds.

Usage:
    python scripts/validate-evidence.py --all
    python scripts/validate-evidence.py specs/features/cli-001-main-translate.md
    python scripts/validate-evidence.py --report reports/driftless/evidence_validation_report.md
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class EvidenceCitation:
    """Represents an evidence citation from a spec."""
    spec_file: Path
    file_path: str
    line_start: Optional[int]
    line_end: Optional[int]
    context: str  # The line of text containing the citation
    valid: bool = True
    reason: Optional[str] = None


class EvidenceValidator:
    """Validates evidence citations in specs."""

    def __init__(self):
        self.citations: List[EvidenceCitation] = []
        self.valid_count = 0
        self.invalid_count = 0

    def extract_citations(self, spec_path: Path) -> List[EvidenceCitation]:
        """Extract evidence citations from a spec file."""
        citations = []

        try:
            content = spec_path.read_text(encoding='utf-8')
        except Exception as e:
            print(f"Warning: Failed to read {spec_path}: {e}")
            return citations

        # Look for Evidence section (include subsections with ###)
        evidence_match = re.search(r'^## Evidence\s*$(.*?)(?=^## [^#]|\Z)', content, re.MULTILINE | re.DOTALL)
        if not evidence_match:
            return citations

        evidence_section = evidence_match.group(1)

        # Parse markdown tables in evidence section FIRST
        # Table format: | Component | File | Lines | Symbol |
        table_row_pattern = r'^\|([^|]*)\|([^|]*)\|([^|]*)\|'

        for line in evidence_section.split('\n'):
            # Skip table headers and separators
            if '----' in line or 'Component' in line or 'Purpose' in line:
                continue

            match = re.search(table_row_pattern, line)
            if match and len(match.groups()) >= 3:
                file_path = match.group(2).strip()
                lines_str = match.group(3).strip()

                # Skip if file path is empty or looks like a header
                if not file_path or file_path in ['File', '']:
                    continue

                # Parse line numbers (format: "100-200" or "100")
                lines_match = re.match(r'(\d+)(?:-(\d+))?', lines_str)
                if lines_match:
                    line_start = int(lines_match.group(1))
                    line_end = int(lines_match.group(2)) if lines_match.group(2) else line_start
                    citations.append(EvidenceCitation(
                        spec_file=spec_path,
                        file_path=file_path,
                        line_start=line_start,
                        line_end=line_end,
                        context=line.strip()
                    ))

        # ALSO parse "**File:**" / "**Lines:**" format (alternative format)
        file_pattern = r'\*\*File:\*\*\s+([^\s\n]+)'
        lines_pattern = r'\*\*Lines:\*\*\s+(\d+)(?:-(\d+))?'

        lines = evidence_section.split('\n')
        current_file = None

        for line in lines:
            file_match = re.search(file_pattern, line)
            if file_match:
                current_file = file_match.group(1)
                # Some citations have both File and Lines on same line
                lines_match = re.search(lines_pattern, line)
                if lines_match:
                    line_start = int(lines_match.group(1))
                    line_end = int(lines_match.group(2)) if lines_match.group(2) else line_start
                    citations.append(EvidenceCitation(
                        spec_file=spec_path,
                        file_path=current_file,
                        line_start=line_start,
                        line_end=line_end,
                        context=line.strip()
                    ))
                    current_file = None  # Reset
                continue

            if current_file:
                lines_match = re.search(lines_pattern, line)
                if lines_match:
                    line_start = int(lines_match.group(1))
                    line_end = int(lines_match.group(2)) if lines_match.group(2) else line_start
                    citations.append(EvidenceCitation(
                        spec_file=spec_path,
                        file_path=current_file,
                        line_start=line_start,
                        line_end=line_end,
                        context=line.strip()
                    ))
                    current_file = None  # Reset after finding lines

        return citations

    def validate_citation(self, citation: EvidenceCitation) -> None:
        """Validate a single evidence citation."""
        # Check file exists
        file_path = Path(citation.file_path)
        if not file_path.exists():
            citation.valid = False
            citation.reason = f"File not found: {citation.file_path}"
            self.invalid_count += 1
            return

        # If no line numbers specified, just check file exists
        if citation.line_start is None:
            citation.valid = True
            self.valid_count += 1
            return

        # Check line numbers are within bounds
        try:
            lines = file_path.read_text(encoding='utf-8').splitlines()
            total_lines = len(lines)

            if citation.line_start < 1 or citation.line_start > total_lines:
                citation.valid = False
                citation.reason = f"Line {citation.line_start} out of bounds (file has {total_lines} lines)"
                self.invalid_count += 1
                return

            if citation.line_end and (citation.line_end < 1 or citation.line_end > total_lines):
                citation.valid = False
                citation.reason = f"Line {citation.line_end} out of bounds (file has {total_lines} lines)"
                self.invalid_count += 1
                return

            if citation.line_end and citation.line_end < citation.line_start:
                citation.valid = False
                citation.reason = f"Invalid range: {citation.line_start}-{citation.line_end} (end < start)"
                self.invalid_count += 1
                return

            citation.valid = True
            self.valid_count += 1

        except Exception as e:
            citation.valid = False
            citation.reason = f"Error reading file: {e}"
            self.invalid_count += 1

    def validate_spec(self, spec_path: Path) -> None:
        """Validate all evidence citations in a spec."""
        citations = self.extract_citations(spec_path)
        for citation in citations:
            self.validate_citation(citation)
            self.citations.append(citation)

    def generate_report(self, output_path: Optional[Path] = None) -> str:
        """Generate validation report."""
        report = f"""# Evidence Citation Validation Report

**Generated:** {Path.cwd()}
**Total Citations:** {len(self.citations)}
**Valid:** {self.valid_count}
**Invalid:** {self.invalid_count}

---

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Valid | {self.valid_count} | {100 * self.valid_count / len(self.citations) if self.citations else 0:.1f}% |
| ❌ Invalid | {self.invalid_count} | {100 * self.invalid_count / len(self.citations) if self.citations else 0:.1f}% |

---

## Invalid Citations

"""

        invalid_citations = [c for c in self.citations if not c.valid]
        if invalid_citations:
            for citation in invalid_citations:
                report += f"""
### {citation.spec_file.name}

**File:** {citation.file_path}
**Lines:** {citation.line_start}-{citation.line_end if citation.line_end else citation.line_start}
**Reason:** {citation.reason}
**Context:** {citation.context}

---
"""
        else:
            report += "\n✅ No invalid citations found.\n"

        report += """
## Valid Citations by Spec

"""

        # Group valid citations by spec
        valid_by_spec: Dict[Path, List[EvidenceCitation]] = {}
        for citation in self.citations:
            if citation.valid:
                if citation.spec_file not in valid_by_spec:
                    valid_by_spec[citation.spec_file] = []
                valid_by_spec[citation.spec_file].append(citation)

        for spec_path, citations in sorted(valid_by_spec.items()):
            report += f"\n### {spec_path.name} ({len(citations)} citations)\n\n"
            for citation in citations:
                lines_str = f"{citation.line_start}-{citation.line_end}" if citation.line_end else str(citation.line_start)
                report += f"- ✅ {citation.file_path}:{lines_str}\n"

        report += """
---

## Recommendations

"""

        if invalid_citations:
            report += """
**Action Required:**
1. Review invalid citations above
2. Update evidence sections with correct file paths and line numbers
3. If code was refactored, update specs to reference new locations
4. Re-run validator after fixes
"""
        else:
            report += """
**Status:** ✅ All evidence citations are valid.

**Maintenance:**
- Re-run validator after code refactoring
- Include in CI pipeline to detect stale citations
- Update citations when files are renamed or restructured
"""

        # Write to file if output path provided
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding='utf-8')
            print(f"Report written to: {output_path}")

        return report


def main():
    parser = argparse.ArgumentParser(
        description='Validate evidence citations in specs',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('files', nargs='*', help='Spec files to validate')
    parser.add_argument('--all', action='store_true', help='Validate all specs')
    parser.add_argument('--report', help='Output report path (default: stdout)')

    args = parser.parse_args()

    # Determine files to validate
    if args.all:
        specs_dir = Path('specs/features')
        if not specs_dir.exists():
            print(f"Error: specs/features not found", file=sys.stderr)
            return 2
        spec_files = sorted(specs_dir.glob('*.md'))

        # Also check core_invariants.md
        core_inv = Path('specs/core_invariants.md')
        if core_inv.exists():
            spec_files.append(core_inv)

    elif args.files:
        spec_files = [Path(f) for f in args.files]
    else:
        parser.print_help()
        return 2

    # Validate
    validator = EvidenceValidator()
    print(f"Validating {len(spec_files)} spec file(s)...")

    for spec_file in spec_files:
        if not spec_file.exists():
            print(f"Warning: File not found: {spec_file}")
            continue
        validator.validate_spec(spec_file)

    # Generate report
    output_path = Path(args.report) if args.report else None
    report = validator.generate_report(output_path)

    if not output_path:
        print(report)

    # Summary
    print(f"\n{'='*60}")
    print(f"Validation complete: {validator.valid_count} valid, {validator.invalid_count} invalid")
    print(f"{'='*60}\n")

    return 0 if validator.invalid_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
