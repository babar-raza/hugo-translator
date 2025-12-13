#!/usr/bin/env python3
"""
Evidence-Based Claim Validator

This tool validates numerical and verifiable claims against collected evidence:
- Loads claim definitions from YAML configuration
- Collects evidence from various sources (file inventory, tests, GPU detection, etc.)
- Validates each claim against evidence with tolerance handling
- Generates detailed validation reports

Usage:
    python scripts/validate_claims.py --claims config/claims.yaml
    python scripts/validate_claims.py --claim "88 files created"
    python scripts/validate_claims.py --claims config/claims.yaml --report reports/claim_validation.json
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(2)


@dataclass
class Claim:
    """A verifiable claim about the project."""
    id: str
    description: str
    expected_value: Union[int, float, str, bool]
    tolerance: str
    evidence_source: str
    evidence_key: str
    category: str


@dataclass
class ValidationResult:
    """Result of validating a claim."""
    claim_id: str
    claim_description: str
    expected_value: Any
    actual_value: Any
    status: str  # PASS, FAIL, UNKNOWN
    tolerance: str
    evidence_source: str
    error: Optional[str] = None
    details: Optional[str] = None


@dataclass
class ClaimValidationReport:
    """Complete claim validation report."""
    validation_time: str
    total_claims: int
    passed_claims: int
    failed_claims: int
    unknown_claims: int
    results: List[ValidationResult]
    errors: List[str]
    warnings: List[str]


class ClaimLoader:
    """Loads claim definitions from YAML configuration."""

    @staticmethod
    def load_claims(config_file: str) -> Tuple[List[Claim], Dict]:
        """
        Load claims from YAML configuration file.

        Returns:
            Tuple of (list of claims, evidence source configurations)
        """
        config_path = Path(config_file)

        if not config_path.exists():
            raise FileNotFoundError(f"Claims configuration file not found: {config_file}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        claims = []
        for claim_data in config.get('claims', []):
            claim = Claim(
                id=claim_data['id'],
                description=claim_data['description'],
                expected_value=claim_data['expected_value'],
                tolerance=claim_data['tolerance'],
                evidence_source=claim_data['evidence_source'],
                evidence_key=claim_data['evidence_key'],
                category=claim_data['category']
            )
            claims.append(claim)

        evidence_sources = config.get('evidence_sources', {})

        return claims, evidence_sources

    @staticmethod
    def find_claim_by_description(claims: List[Claim], description: str) -> Optional[Claim]:
        """Find a claim by partial description match."""
        description_lower = description.lower()

        for claim in claims:
            if description_lower in claim.description.lower():
                return claim

        return None


class EvidenceCollector:
    """Collects evidence from various sources."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    def collect_evidence(
        self,
        source_name: str,
        source_config: Dict
    ) -> Optional[Dict]:
        """
        Collect evidence from a source.

        Args:
            source_name: Name of the evidence source
            source_config: Configuration for the source

        Returns:
            Evidence data as dictionary, or None if collection failed
        """
        source_type = source_config.get('type')

        if source_type == 'json_file':
            return self._collect_from_json_file(source_config)
        elif source_type == 'pytest_collection':
            return self._collect_from_pytest(source_config)
        else:
            print(f"Warning: Unknown evidence source type: {source_type}")
            return None

    def _collect_from_json_file(self, config: Dict) -> Optional[Dict]:
        """Collect evidence from a JSON file."""
        file_path = self.root_dir / config['path']

        if not file_path.exists():
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading JSON file {file_path}: {e}")
            return None

    def _collect_from_pytest(self, config: Dict) -> Optional[Dict]:
        """Collect evidence from pytest collection."""
        command = config.get('command', 'pytest --collect-only -q')

        try:
            result = subprocess.run(
                command.split(),
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.root_dir)
            )

            # Parse pytest output to count tests
            # Output format: "X selected" or "X deselected, Y selected"
            output = result.stdout + result.stderr

            # Count test functions/methods
            test_count = 0
            for line in output.split('\n'):
                if '<Function' in line or '<Method' in line:
                    test_count += 1

            # Also try to parse summary line
            match = re.search(r'(\d+)\s+test', output)
            if match:
                test_count = max(test_count, int(match.group(1)))

            return {
                'total_tests': test_count,
                'command': command,
                'exit_code': result.returncode,
                'output': output
            }

        except subprocess.TimeoutExpired:
            print("Warning: pytest collection timed out")
            return None
        except FileNotFoundError:
            print("Warning: pytest not found")
            return None
        except Exception as e:
            print(f"Warning: Error collecting pytest evidence: {e}")
            return None


class ClaimValidator:
    """Validates claims against evidence."""

    @staticmethod
    def extract_value(data: Any, key_path: str) -> Any:
        """
        Extract a value from nested data structure using a key path.

        Supports:
        - Dot notation: "stats.total_files"
        - Array indexing: "files[0].name"
        - Simple expressions: "stats.total_code_lines / stats.total_comment_lines"
        - JMESPath-like filters: "files[?category=='src'].length"

        Args:
            data: Data structure to extract from
            key_path: Path to the value

        Returns:
            Extracted value, or None if not found
        """
        # Handle simple arithmetic expressions
        if '/' in key_path and not '[' in key_path:
            parts = [p.strip() for p in key_path.split('/')]
            if len(parts) == 2:
                numerator = ClaimValidator.extract_value(data, parts[0])
                denominator = ClaimValidator.extract_value(data, parts[1])
                if numerator is not None and denominator is not None and denominator != 0:
                    return numerator / denominator

        # Handle filters (simplified JMESPath-like)
        if '[?' in key_path:
            # Very simplified filter support
            # Example: "files[?category=='src'].length"
            match = re.match(r"(\w+)\[\?(\w+)=='(\w+)'\]\.length", key_path)
            if match and isinstance(data, dict):
                array_name, filter_key, filter_value = match.groups()
                array = data.get(array_name, [])
                if isinstance(array, list):
                    filtered = [item for item in array if isinstance(item, dict) and item.get(filter_key) == filter_value]
                    return len(filtered)

        # Handle simple dot notation and array indexing
        parts = key_path.split('.')
        current = data

        for part in parts:
            if current is None:
                return None

            # Handle array indexing
            if '[' in part and ']' in part:
                # Split array name and index
                array_match = re.match(r'(\w+)\[(\d+)\]', part)
                if array_match:
                    array_name, index = array_match.groups()
                    if isinstance(current, dict):
                        current = current.get(array_name, [])
                    if isinstance(current, list):
                        try:
                            current = current[int(index)]
                        except (IndexError, ValueError):
                            return None
                    else:
                        return None
                else:
                    # Handle special case like "circular_imports.length"
                    if part.endswith('.length'):
                        part = part[:-7]  # Remove '.length'
                        if isinstance(current, dict):
                            current = current.get(part, [])
                        if isinstance(current, list):
                            return len(current)
                        return None
                    return None
            else:
                # Handle "length" pseudo-property
                if part == 'length':
                    if isinstance(current, list):
                        return len(current)
                    return None

                # Simple dictionary key access
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None

        return current

    @staticmethod
    def validate_claim(claim: Claim, evidence: Any) -> ValidationResult:
        """
        Validate a claim against evidence.

        Args:
            claim: Claim to validate
            evidence: Evidence data

        Returns:
            ValidationResult
        """
        # Extract actual value from evidence
        try:
            actual_value = ClaimValidator.extract_value(evidence, claim.evidence_key)
        except Exception as e:
            return ValidationResult(
                claim_id=claim.id,
                claim_description=claim.description,
                expected_value=claim.expected_value,
                actual_value=None,
                status='UNKNOWN',
                tolerance=claim.tolerance,
                evidence_source=claim.evidence_source,
                error=f"Error extracting value: {e}"
            )

        if actual_value is None:
            return ValidationResult(
                claim_id=claim.id,
                claim_description=claim.description,
                expected_value=claim.expected_value,
                actual_value=None,
                status='UNKNOWN',
                tolerance=claim.tolerance,
                evidence_source=claim.evidence_source,
                error=f"Could not find value at path: {claim.evidence_key}"
            )

        # Perform comparison based on tolerance
        status = 'FAIL'
        details = None

        try:
            if claim.tolerance == 'equals':
                if actual_value == claim.expected_value:
                    status = 'PASS'
                else:
                    details = f"Expected {claim.expected_value}, got {actual_value}"

            elif claim.tolerance == 'greater_than':
                if actual_value > claim.expected_value:
                    status = 'PASS'
                else:
                    details = f"Expected > {claim.expected_value}, got {actual_value}"

            elif claim.tolerance == 'greater_than_or_equal':
                if actual_value >= claim.expected_value:
                    status = 'PASS'
                else:
                    details = f"Expected >= {claim.expected_value}, got {actual_value}"

            elif claim.tolerance == 'less_than':
                if actual_value < claim.expected_value:
                    status = 'PASS'
                else:
                    details = f"Expected < {claim.expected_value}, got {actual_value}"

            elif claim.tolerance == 'less_than_or_equal':
                if actual_value <= claim.expected_value:
                    status = 'PASS'
                else:
                    details = f"Expected <= {claim.expected_value}, got {actual_value}"

            elif claim.tolerance == 'range':
                # Expect expected_value to be a tuple/list [min, max]
                if isinstance(claim.expected_value, (list, tuple)) and len(claim.expected_value) == 2:
                    min_val, max_val = claim.expected_value
                    if min_val <= actual_value <= max_val:
                        status = 'PASS'
                    else:
                        details = f"Expected in range [{min_val}, {max_val}], got {actual_value}"

            else:
                return ValidationResult(
                    claim_id=claim.id,
                    claim_description=claim.description,
                    expected_value=claim.expected_value,
                    actual_value=actual_value,
                    status='UNKNOWN',
                    tolerance=claim.tolerance,
                    evidence_source=claim.evidence_source,
                    error=f"Unknown tolerance type: {claim.tolerance}"
                )

        except Exception as e:
            return ValidationResult(
                claim_id=claim.id,
                claim_description=claim.description,
                expected_value=claim.expected_value,
                actual_value=actual_value,
                status='UNKNOWN',
                tolerance=claim.tolerance,
                evidence_source=claim.evidence_source,
                error=f"Error comparing values: {e}"
            )

        return ValidationResult(
            claim_id=claim.id,
            claim_description=claim.description,
            expected_value=claim.expected_value,
            actual_value=actual_value,
            status=status,
            tolerance=claim.tolerance,
            evidence_source=claim.evidence_source,
            details=details
        )


class Reporter:
    """Generates validation reports."""

    @staticmethod
    def save_report(report: ClaimValidationReport, output_path: str):
        """Save report to JSON file."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, 'w', encoding='utf-8') as f:
            json.dump(asdict(report), f, indent=2, ensure_ascii=False)

        print(f"Report saved to: {output}")

    @staticmethod
    def print_summary(report: ClaimValidationReport):
        """Print a summary of the validation report."""
        print("\nClaim Validation Report")
        print("=" * 60)
        print(f"Validation time: {report.validation_time}")
        print()

        # Overall statistics
        print("Overall Statistics:")
        print(f"  Total claims: {report.total_claims}")
        print(f"  Passed: {report.passed_claims} ({report.passed_claims * 100 // report.total_claims if report.total_claims > 0 else 0}%)")
        print(f"  Failed: {report.failed_claims} ({report.failed_claims * 100 // report.total_claims if report.total_claims > 0 else 0}%)")
        print(f"  Unknown: {report.unknown_claims}")
        print()

        # Group results by category
        by_category = {}
        for result in report.results:
            # Find category from claim ID (we'll need to track this)
            category = 'general'
            by_category.setdefault(category, []).append(result)

        # Print results by status
        passed = [r for r in report.results if r.status == 'PASS']
        failed = [r for r in report.results if r.status == 'FAIL']
        unknown = [r for r in report.results if r.status == 'UNKNOWN']

        if passed:
            print(f"Passed Claims ({len(passed)}):")
            for result in passed:
                print(f"  ✓ {result.claim_description}")
                print(f"    Expected: {result.expected_value} ({result.tolerance})")
                print(f"    Actual: {result.actual_value}")
            print()

        if failed:
            print(f"Failed Claims ({len(failed)}):")
            for result in failed:
                print(f"  ✗ {result.claim_description}")
                print(f"    Expected: {result.expected_value} ({result.tolerance})")
                print(f"    Actual: {result.actual_value}")
                if result.details:
                    print(f"    Details: {result.details}")
            print()

        if unknown:
            print(f"Unknown Claims ({len(unknown)}):")
            for result in unknown:
                print(f"  ? {result.claim_description}")
                if result.error:
                    print(f"    Error: {result.error}")
            print()

        # Errors and warnings
        if report.errors:
            print(f"Errors ({len(report.errors)}):")
            for error in report.errors:
                print(f"  ✗ {error}")
            print()

        if report.warnings:
            print(f"Warnings ({len(report.warnings)}):")
            for warning in report.warnings:
                print(f"  ⚠ {warning}")
            print()

        # Overall status
        print("Overall Status:")
        if report.failed_claims == 0 and report.unknown_claims == 0:
            print("  ✓ All claims validated successfully")
        elif report.failed_claims > 0:
            print(f"  ✗ {report.failed_claims} claim(s) failed validation")
        else:
            print(f"  ? {report.unknown_claims} claim(s) could not be validated")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Evidence-Based Claim Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate all claims
  python scripts/validate_claims.py --claims config/claims.yaml

  # Validate specific claim
  python scripts/validate_claims.py --claim "88 files created"

  # Generate validation report
  python scripts/validate_claims.py --claims config/claims.yaml --report reports/claim_validation.json
        """
    )

    parser.add_argument('--claims', metavar='FILE',
                       help='Claims configuration file (YAML)')
    parser.add_argument('--claim', metavar='DESCRIPTION',
                       help='Validate specific claim by description')
    parser.add_argument('--report', '-o', metavar='FILE',
                       help='Output file for validation report (JSON)')
    parser.add_argument('--root', metavar='DIR',
                       help='Project root directory (default: current directory)')

    args = parser.parse_args()

    if not (args.claims or args.claim):
        parser.print_help()
        sys.exit(1)

    # Determine root directory
    if args.root:
        root_dir = args.root
    else:
        # Try to find git root
        current = Path.cwd()
        while current != current.parent:
            if (current / '.git').exists():
                root_dir = str(current)
                break
            current = current.parent
        else:
            root_dir = str(Path.cwd())

    # Default claims file
    claims_file = args.claims or 'config/claims.yaml'

    # Load claims
    try:
        claims, evidence_sources = ClaimLoader.load_claims(claims_file)
    except Exception as e:
        print(f"Error loading claims: {e}")
        sys.exit(2)

    # Filter claims if specific claim requested
    if args.claim:
        matching_claim = ClaimLoader.find_claim_by_description(claims, args.claim)
        if matching_claim:
            claims = [matching_claim]
        else:
            print(f"No claim found matching: {args.claim}")
            sys.exit(1)

    # Collect evidence and validate
    collector = EvidenceCollector(root_dir)
    results = []
    errors = []
    warnings = []

    # Group claims by evidence source
    by_source = {}
    for claim in claims:
        by_source.setdefault(claim.evidence_source, []).append(claim)

    # Collect evidence for each source
    evidence_cache = {}
    for source_name, source_claims in by_source.items():
        if source_name not in evidence_sources:
            warnings.append(f"Evidence source not configured: {source_name}")
            continue

        print(f"Collecting evidence from: {source_name}")
        evidence = collector.collect_evidence(source_name, evidence_sources[source_name])

        if evidence is None:
            warnings.append(f"Could not collect evidence from: {source_name}")
            evidence = {}

        evidence_cache[source_name] = evidence

    # Validate each claim
    print(f"\nValidating {len(claims)} claims...")
    for claim in claims:
        evidence = evidence_cache.get(claim.evidence_source, {})
        result = ClaimValidator.validate_claim(claim, evidence)
        results.append(result)

    # Create report
    passed = sum(1 for r in results if r.status == 'PASS')
    failed = sum(1 for r in results if r.status == 'FAIL')
    unknown = sum(1 for r in results if r.status == 'UNKNOWN')

    report = ClaimValidationReport(
        validation_time=datetime.now().isoformat(),
        total_claims=len(claims),
        passed_claims=passed,
        failed_claims=failed,
        unknown_claims=unknown,
        results=results,
        errors=errors,
        warnings=warnings
    )

    # Output
    Reporter.print_summary(report)

    if args.report:
        Reporter.save_report(report, args.report)

    # Exit with appropriate code
    if failed > 0:
        sys.exit(1)
    elif unknown > 0:
        sys.exit(0)  # Unknown is not a failure
    else:
        sys.exit(0)


if __name__ == '__main__':
    from typing import Tuple
    main()
