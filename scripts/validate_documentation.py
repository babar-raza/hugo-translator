#!/usr/bin/env python3
"""
Documentation Validation Tool

Validates documentation against DOCUMENTATION_STANDARDS.md to ensure:
- Claims are properly categorized (verified/reported/projected)
- Evidence exists for verified claims
- Absolute language is not used without qualification
- Status markers are used consistently
"""

import re
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


class ClaimType(Enum):
    """Types of claims in documentation"""
    VERIFIED = "verified"
    REPORTED = "reported"
    PROJECTED = "projected"
    UNQUALIFIED = "unqualified"


class Severity(Enum):
    """Severity levels for validation issues"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Claim:
    """Represents a claim found in documentation"""
    text: str
    line_number: int
    claim_type: ClaimType
    pattern: str
    context: str = ""

    def __str__(self):
        return f"Line {self.line_number}: {self.text[:80]}..."


@dataclass
class ValidationIssue:
    """Represents a validation issue"""
    severity: Severity
    message: str
    line_number: int
    claim: Optional[Claim] = None
    suggestion: str = ""

    def __str__(self):
        result = f"[{self.severity.value.upper()}] Line {self.line_number}: {self.message}"
        if self.suggestion:
            result += f"\n  Suggestion: {self.suggestion}"
        return result


@dataclass
class ValidationReport:
    """Complete validation report for a document"""
    file_path: str
    claims_found: List[Claim] = field(default_factory=list)
    issues: List[ValidationIssue] = field(default_factory=list)
    evidence_links: List[Tuple[int, str]] = field(default_factory=list)
    status_markers: Dict[str, int] = field(default_factory=dict)

    @property
    def verified_claims(self) -> List[Claim]:
        return [c for c in self.claims_found if c.claim_type == ClaimType.VERIFIED]

    @property
    def reported_claims(self) -> List[Claim]:
        return [c for c in self.claims_found if c.claim_type == ClaimType.REPORTED]

    @property
    def projected_claims(self) -> List[Claim]:
        return [c for c in self.claims_found if c.claim_type == ClaimType.PROJECTED]

    @property
    def unqualified_claims(self) -> List[Claim]:
        return [c for c in self.claims_found if c.claim_type == ClaimType.UNQUALIFIED]

    @property
    def error_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.ERROR])

    @property
    def warning_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.WARNING])

    def to_dict(self) -> dict:
        """Convert report to dictionary for JSON serialization"""
        return {
            "file_path": self.file_path,
            "summary": {
                "total_claims": len(self.claims_found),
                "verified_claims": len(self.verified_claims),
                "reported_claims": len(self.reported_claims),
                "projected_claims": len(self.projected_claims),
                "unqualified_claims": len(self.unqualified_claims),
                "evidence_links": len(self.evidence_links),
                "errors": self.error_count,
                "warnings": self.warning_count,
            },
            "issues": [
                {
                    "severity": i.severity.value,
                    "line": i.line_number,
                    "message": i.message,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
            "claims": [
                {
                    "type": c.claim_type.value,
                    "line": c.line_number,
                    "text": c.text[:100],
                    "pattern": c.pattern,
                }
                for c in self.claims_found
            ],
            "status_markers": self.status_markers,
        }


class ClaimDetector:
    """Detects claims in documentation"""

    # Patterns for absolute language that requires evidence
    ABSOLUTE_PATTERNS = [
        # Quantitative claims
        (r'\b100%\b', "100% claim requires evidence"),
        (r'\ball\s+(?:tests?|files?|features?|components?)\s+(?:pass|work|complete)', "Absolute 'all X' claim requires evidence"),
        (r'\bevery\s+\w+', "Absolute 'every' claim requires evidence"),
        (r'\b\d+\+?\s+(?:tests?|files?|features?)\s+(?:pass|created?|implemented?)', "Numeric claim requires evidence"),
        (r'\bzero\s+(?:errors?|bugs?|failures?)', "Zero errors claim requires evidence"),
        (r'\bno\s+(?:errors?|bugs?|failures?|issues?)', "No errors claim requires evidence"),

        # Status claims
        (r'\bproduction\s+ready\b', "Production ready claim requires evidence"),
        (r'\bfully\s+(?:implemented?|functional?|working?)', "Fully X claim requires evidence"),
        (r'\bcomplete(?:ly)?\s+(?:implemented?|working?|functional?)', "Complete claim requires evidence"),

        # Capability claims
        (r'\b(?:supports?|handles?|processes?)\s+(?!.*(?:designed|intended|expected))', "Capability claim requires evidence"),
        (r'\bdetects?\s+\w+\s+(?:correctly|successfully)', "Detection claim requires evidence"),
    ]

    # Patterns for qualified language (acceptable)
    QUALIFIED_PATTERNS = [
        # Reported
        (r'(?:agent|tool|script)\s+reports?', ClaimType.REPORTED),
        (r'according\s+to', ClaimType.REPORTED),
        (r'logs?\s+(?:indicate|show|suggest)', ClaimType.REPORTED),
        (r'tool\s+output\s+(?:shows?|indicates?)', ClaimType.REPORTED),

        # Projected
        (r'(?:expected|designed|intended)\s+(?:to|for)', ClaimType.PROJECTED),
        (r'(?:should|may|might|could)\s+', ClaimType.PROJECTED),
        (r'estimated?\s+', ClaimType.PROJECTED),
        (r'projected?\s+', ClaimType.PROJECTED),
    ]

    # Status markers
    STATUS_MARKERS = {
        '✅': 'verified',
        '📋': 'reported',
        '🎯': 'projected',
        '⏳': 'pending',
        '⚠️': 'partial',
        '❌': 'not_verified',
    }

    def detect_claims(self, content: str) -> Tuple[List[Claim], Dict[str, int]]:
        """
        Detect all claims in content

        Returns:
            Tuple of (claims list, status markers count)
        """
        lines = content.split('\n')
        claims = []
        status_markers = {marker: 0 for marker in self.STATUS_MARKERS.keys()}

        for line_num, line in enumerate(lines, start=1):
            # Count status markers
            for marker in self.STATUS_MARKERS.keys():
                if marker in line:
                    status_markers[marker] += 1

            # Detect qualified claims first
            claim_type = self._detect_qualified_claim(line)
            if claim_type:
                claims.append(Claim(
                    text=line.strip(),
                    line_number=line_num,
                    claim_type=claim_type,
                    pattern="qualified",
                    context=self._get_context(lines, line_num)
                ))
                continue

            # Check for verified markers
            if '✅' in line:
                claims.append(Claim(
                    text=line.strip(),
                    line_number=line_num,
                    claim_type=ClaimType.VERIFIED,
                    pattern="status_marker",
                    context=self._get_context(lines, line_num)
                ))
                continue

            # Detect unqualified absolute claims
            for pattern, description in self.ABSOLUTE_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    claims.append(Claim(
                        text=line.strip(),
                        line_number=line_num,
                        claim_type=ClaimType.UNQUALIFIED,
                        pattern=description,
                        context=self._get_context(lines, line_num)
                    ))
                    break

        return claims, status_markers

    def _detect_qualified_claim(self, line: str) -> Optional[ClaimType]:
        """Detect if line contains qualified claim language"""
        for pattern, claim_type in self.QUALIFIED_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                return claim_type
        return None

    def _get_context(self, lines: List[str], line_num: int, context_lines: int = 2) -> str:
        """Get surrounding context for a line"""
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        return '\n'.join(lines[start:end])


class EvidenceChecker:
    """Checks for evidence links in documentation"""

    # Patterns for evidence links
    EVIDENCE_PATTERNS = [
        r'Evidence:\s*(.+)',
        r'See:\s*(.+)',
        r'Verification:\s*`([^`]+)`',
        r'Command:\s*`([^`]+)`',
        r'Output:\s*(.+)',
        r'Result:\s*(.+)',
        r'Source:\s*(.+)',
    ]

    # File reference patterns
    FILE_PATTERNS = [
        r'`([^`]+\.py)`',
        r'`([^`]+\.md)`',
        r'`([^`]+\.json)`',
        r'`([^`]+\.txt)`',
        r'`([^`]+\.log)`',
    ]

    def check_evidence(self, content: str, claims: List[Claim]) -> List[Tuple[int, str]]:
        """
        Check for evidence links in content

        Returns:
            List of (line_number, evidence_text) tuples
        """
        lines = content.split('\n')
        evidence_links = []

        for line_num, line in enumerate(lines, start=1):
            # Check for evidence patterns
            for pattern in self.EVIDENCE_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    evidence_links.append((line_num, match.group(1).strip()))

            # Check for file references
            for pattern in self.FILE_PATTERNS:
                matches = re.finditer(pattern, line)
                for match in matches:
                    evidence_links.append((line_num, f"File reference: {match.group(1)}"))

        return evidence_links

    def validate_evidence_for_claims(self, claims: List[Claim], evidence_links: List[Tuple[int, str]]) -> List[ValidationIssue]:
        """Validate that verified claims have nearby evidence"""
        issues = []

        for claim in claims:
            if claim.claim_type == ClaimType.VERIFIED:
                # Check if there's evidence within 5 lines
                has_evidence = any(
                    abs(evidence_line - claim.line_number) <= 5
                    for evidence_line, _ in evidence_links
                )

                if not has_evidence:
                    issues.append(ValidationIssue(
                        severity=Severity.ERROR,
                        message=f"Verified claim lacks evidence link",
                        line_number=claim.line_number,
                        claim=claim,
                        suggestion="Add 'Evidence:', 'Verification:', or 'See:' link within 5 lines"
                    ))

        return issues


class LanguageValidator:
    """Validates language usage in documentation"""

    def validate_language(self, claims: List[Claim]) -> List[ValidationIssue]:
        """Validate language usage in claims"""
        issues = []

        for claim in claims:
            if claim.claim_type == ClaimType.UNQUALIFIED:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Unqualified absolute claim: {claim.pattern}",
                    line_number=claim.line_number,
                    claim=claim,
                    suggestion=self._get_qualification_suggestion(claim)
                ))

        return issues

    def _get_qualification_suggestion(self, claim: Claim) -> str:
        """Get suggestion for qualifying a claim"""
        if "production ready" in claim.text.lower():
            return "Use: 'Implementation complete, verification pending' or '📋 Agents report production ready'"
        elif "all tests pass" in claim.text.lower():
            return "Use: '📋 Agent reports all tests pass. ⏳ Run pytest to verify.'"
        elif re.search(r'\d+\+?\s+tests?', claim.text.lower()):
            return "Use: '📋 Agent reports X tests created. ⏳ Verification pending.'"
        elif "fully implemented" in claim.text.lower():
            return "Use: '✅ Implementation complete (code written). ⏳ Testing pending.'"
        else:
            return "Add status marker (✅/📋/🎯) and qualification ('reported as', 'verified by', 'designed for')"


class Reporter:
    """Generates validation reports"""

    def print_report(self, report: ValidationReport, verbose: bool = False):
        """Print human-readable report"""
        print(f"\n{'='*70}")
        print(f"Validation Report: {report.file_path}")
        print(f"{'='*70}")

        # Summary
        print(f"\n📊 Summary:")
        print(f"  Total claims: {len(report.claims_found)}")
        print(f"    ✅ Verified: {len(report.verified_claims)}")
        print(f"    📋 Reported: {len(report.reported_claims)}")
        print(f"    🎯 Projected: {len(report.projected_claims)}")
        print(f"    ⚠️  Unqualified: {len(report.unqualified_claims)}")
        print(f"  Evidence links: {len(report.evidence_links)}")
        print(f"  Issues: {report.error_count} errors, {report.warning_count} warnings")

        # Status markers
        if report.status_markers:
            print(f"\n🏷️  Status Markers:")
            for marker, count in report.status_markers.items():
                if count > 0:
                    print(f"    {marker}: {count}")

        # Issues
        if report.issues:
            print(f"\n❌ Issues Found:")
            for issue in report.issues:
                print(f"  {issue}")
        else:
            print(f"\n✅ No issues found!")

        # Verbose details
        if verbose and report.claims_found:
            print(f"\n📋 All Claims:")
            for claim in report.claims_found:
                print(f"  [{claim.claim_type.value}] {claim}")

        if verbose and report.evidence_links:
            print(f"\n🔗 Evidence Links:")
            for line_num, evidence in report.evidence_links:
                print(f"  Line {line_num}: {evidence[:80]}...")

        print(f"\n{'='*70}")

    def save_json_report(self, report: ValidationReport, output_path: str):
        """Save report as JSON"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\n💾 Report saved to: {output_path}")


class DocumentationValidator:
    """Main documentation validator"""

    def __init__(self):
        self.claim_detector = ClaimDetector()
        self.evidence_checker = EvidenceChecker()
        self.language_validator = LanguageValidator()
        self.reporter = Reporter()

    def validate_file(self, file_path: str) -> ValidationReport:
        """Validate a single documentation file"""
        # Read file
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            report = ValidationReport(file_path=file_path)
            report.issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Failed to read file: {e}",
                line_number=0
            ))
            return report

        # Create report
        report = ValidationReport(file_path=file_path)

        # Detect claims
        report.claims_found, report.status_markers = self.claim_detector.detect_claims(content)

        # Check evidence
        report.evidence_links = self.evidence_checker.check_evidence(content, report.claims_found)

        # Validate evidence for verified claims
        evidence_issues = self.evidence_checker.validate_evidence_for_claims(
            report.claims_found,
            report.evidence_links
        )
        report.issues.extend(evidence_issues)

        # Validate language
        language_issues = self.language_validator.validate_language(report.claims_found)
        report.issues.extend(language_issues)

        return report

    def validate_directory(self, directory: str, pattern: str = "*.md") -> List[ValidationReport]:
        """Validate all documentation files in a directory"""
        path = Path(directory)
        reports = []

        for file_path in path.rglob(pattern):
            if file_path.is_file():
                report = self.validate_file(str(file_path))
                reports.append(report)

        return reports


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Validate documentation against DOCUMENTATION_STANDARDS.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate all documentation
  %(prog)s --check-all

  # Validate specific file
  %(prog)s --file IMPLEMENTATION_COMPLETE.md

  # Generate JSON report
  %(prog)s --check-all --report reports/doc_validation.json

  # Verbose output
  %(prog)s --file README.md --verbose
        """
    )

    parser.add_argument(
        '--file',
        type=str,
        help='Validate specific file'
    )

    parser.add_argument(
        '--check-all',
        action='store_true',
        help='Validate all documentation files'
    )

    parser.add_argument(
        '--directory',
        type=str,
        default='.',
        help='Directory to search for documentation (default: current directory)'
    )

    parser.add_argument(
        '--pattern',
        type=str,
        default='*.md',
        help='File pattern to match (default: *.md)'
    )

    parser.add_argument(
        '--report',
        type=str,
        help='Save JSON report to file'
    )

    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.file and not args.check_all:
        parser.error("Must specify either --file or --check-all")

    # Create validator
    validator = DocumentationValidator()

    # Validate
    if args.file:
        # Single file
        report = validator.validate_file(args.file)
        validator.reporter.print_report(report, verbose=args.verbose)

        if args.report:
            validator.reporter.save_json_report(report, args.report)

        # Exit with error code if issues found
        sys.exit(1 if report.error_count > 0 else 0)

    elif args.check_all:
        # All files
        reports = validator.validate_directory(args.directory, args.pattern)

        if not reports:
            print(f"No documentation files found matching pattern: {args.pattern}")
            sys.exit(1)

        # Print individual reports
        for report in reports:
            validator.reporter.print_report(report, verbose=args.verbose)

        # Print summary
        total_errors = sum(r.error_count for r in reports)
        total_warnings = sum(r.warning_count for r in reports)
        total_claims = sum(len(r.claims_found) for r in reports)
        total_verified = sum(len(r.verified_claims) for r in reports)

        print(f"\n{'='*70}")
        print(f"Overall Summary: {len(reports)} files validated")
        print(f"{'='*70}")
        print(f"  Total claims: {total_claims}")
        print(f"  Verified claims: {total_verified}")
        print(f"  Total errors: {total_errors}")
        print(f"  Total warnings: {total_warnings}")
        print(f"{'='*70}\n")

        # Save combined report
        if args.report:
            combined_report = {
                "summary": {
                    "files_validated": len(reports),
                    "total_claims": total_claims,
                    "total_verified": total_verified,
                    "total_errors": total_errors,
                    "total_warnings": total_warnings,
                },
                "reports": [r.to_dict() for r in reports]
            }
            with open(args.report, 'w', encoding='utf-8') as f:
                json.dump(combined_report, f, indent=2, ensure_ascii=False)
            print(f"💾 Combined report saved to: {args.report}\n")

        # Exit with error code if issues found
        sys.exit(1 if total_errors > 0 else 0)


if __name__ == '__main__':
    main()
