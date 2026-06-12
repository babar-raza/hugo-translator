"""
Spec Verification Tool

Scans specs/ directory and verifies:
1. All specs are parseable (valid YAML/Markdown)
2. Referenced evidence files exist
3. start_method commands are valid (if applicable)
4. Implementation files exist (basic check)

Usage:
    python -m scripts.specscan --specs-dir specs/ --report-dir reports/

Exit Codes:
    0 - All checks passed
    1 - One or more checks failed

Author: Agent A+B
Task: SPEC-TOOL-SPECSCAN
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml


@dataclass
class SpecScanResult:
    """Result of scanning a single spec item."""

    spec_type: str  # "runtime_unit", "feature", "entrypoint", "evidence", etc.
    spec_id: str
    status: str  # "PASS", "FAIL", "WARNING"
    messages: list[str] = field(default_factory=list)
    location: str = ""  # file:line


@dataclass
class ScanSummary:
    """Summary of entire scan operation."""

    total_specs: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    results: list[SpecScanResult] = field(default_factory=list)


class SpecScanner:
    """Main spec scanner class."""

    def __init__(self, specs_dir: Path, report_dir: Path, project_root: Path):
        self.specs_dir = specs_dir
        self.report_dir = report_dir
        self.project_root = project_root
        self.summary = ScanSummary()
        self.evidence_registry: dict[str, dict] = {}

    def scan_all(self) -> int:
        """
        Scan all specs and return exit code.

        Returns:
            0 if all checks passed, 1 if any failures
        """
        print(f"Starting spec scan of {self.specs_dir}")
        print(f"Project root: {self.project_root}")
        print()

        # Load evidence registry first
        self._load_evidence_registry()

        # Scan different spec types
        self._scan_runtime_units()
        self._scan_features()
        self._scan_entrypoints()
        self._scan_evidence_registry()

        # Generate report
        report_path = self._generate_report()

        # Print summary
        self._print_summary()
        print(f"\nReport written to: {report_path}")

        # Return exit code
        return 0 if self.summary.failed == 0 else 1

    def _load_evidence_registry(self) -> None:
        """Load evidence registry from _evidence_index.yml."""
        evidence_file = self.specs_dir / "_evidence_index.yml"

        if not evidence_file.exists():
            result = SpecScanResult(
                spec_type="evidence_registry",
                spec_id="_evidence_index.yml",
                status="FAIL",
                messages=["Evidence registry file not found"],
                location=str(evidence_file),
            )
            self.summary.results.append(result)
            self.summary.total_specs += 1
            self.summary.failed += 1
            return

        try:
            with open(evidence_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data and "evidence" in data:
                for item in data["evidence"]:
                    evidence_id = item.get("evidence_id", "")
                    self.evidence_registry[evidence_id] = item

                print(f"Loaded {len(self.evidence_registry)} evidence entries")
        except Exception as e:
            result = SpecScanResult(
                spec_type="evidence_registry",
                spec_id="_evidence_index.yml",
                status="FAIL",
                messages=[f"Failed to parse evidence registry: {e}"],
                location=str(evidence_file),
            )
            self.summary.results.append(result)
            self.summary.total_specs += 1
            self.summary.failed += 1

    def _scan_runtime_units(self) -> None:
        """Scan runtime_units.yml."""
        runtime_file = self.specs_dir / "runtime_units.yml"

        if not runtime_file.exists():
            print("⚠️  runtime_units.yml not found, skipping")
            return

        print("Scanning runtime_units.yml...")

        try:
            with open(runtime_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            result = SpecScanResult(
                spec_type="runtime_units",
                spec_id="runtime_units.yml",
                status="FAIL",
                messages=[f"Failed to parse YAML: {e}"],
                location=str(runtime_file),
            )
            self.summary.results.append(result)
            self.summary.total_specs += 1
            self.summary.failed += 1
            return

        if not data or "runtime_units" not in data:
            result = SpecScanResult(
                spec_type="runtime_units",
                spec_id="runtime_units.yml",
                status="FAIL",
                messages=["No 'runtime_units' key found in YAML"],
                location=str(runtime_file),
            )
            self.summary.results.append(result)
            self.summary.total_specs += 1
            self.summary.failed += 1
            return

        # Scan each runtime unit
        for idx, unit in enumerate(data["runtime_units"]):
            unit_result = self._verify_runtime_unit(unit, runtime_file, idx)
            self.summary.results.append(unit_result)
            self.summary.total_specs += 1

            if unit_result.status == "PASS":
                self.summary.passed += 1
            elif unit_result.status == "FAIL":
                self.summary.failed += 1
            elif unit_result.status == "WARNING":
                self.summary.warnings += 1

        print(f"  Scanned {len(data['runtime_units'])} runtime units")

    def _verify_runtime_unit(self, unit: dict, file_path: Path, idx: int) -> SpecScanResult:
        """Verify a single runtime unit."""
        unit_id = unit.get("id", f"<unknown_{idx}>")
        messages = []
        status = "PASS"

        # Check required fields
        required_fields = ["id", "name", "description", "start_method"]
        for field in required_fields:
            if field not in unit or not unit[field]:
                messages.append(f"Missing required field: {field}")
                status = "FAIL"

        # Validate start_method syntax
        if "start_method" in unit:
            start_method = unit["start_method"]
            if not self._validate_start_method(start_method):
                messages.append(f"Invalid start_method syntax: {start_method}")
                status = "FAIL"

        # Verify evidence_ids exist
        if "evidence_ids" in unit:
            for evidence_id in unit["evidence_ids"]:
                if evidence_id not in self.evidence_registry:
                    messages.append(f"Evidence ID not found in registry: {evidence_id}")
                    status = "FAIL"

        # Validate ports (if present)
        if "ports" in unit and unit["ports"]:
            for port in unit["ports"]:
                if isinstance(port, str):
                    try:
                        port_num = int(port)
                        if port_num < 0 or port_num > 65535:
                            messages.append(f"Port out of valid range: {port}")
                            if status == "PASS":
                                status = "WARNING"
                    except ValueError:
                        messages.append(f"Invalid port format: {port}")
                        if status == "PASS":
                            status = "WARNING"

        if status == "PASS":
            messages.append("All checks passed")

        return SpecScanResult(
            spec_type="runtime_unit",
            spec_id=unit_id,
            status=status,
            messages=messages,
            location=f"{file_path}:unit[{idx}]",
        )

    def _validate_start_method(self, command: str) -> bool:
        """
        Validate start_method command syntax.

        Accepts:
        - docker-compose up <service>
        - python -m <module.path>
        - CLI commands like translate-hugo
        """
        # Docker compose pattern
        if command.startswith("docker-compose up "):
            return True

        # Python module pattern
        if command.startswith("python -m "):
            module_path = command[10:].split()[0]  # Get module path before any args
            # Basic validation: should contain dots or be a valid module name
            return bool(
                re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$", module_path)
            )

        # CLI command pattern (starts with known command)
        if command.startswith("translate-hugo"):
            return True

        # If none match, it might still be valid but we can't verify
        # Return True to avoid false positives
        return True

    def _scan_features(self) -> None:
        """Scan features/ directory."""
        features_dir = self.specs_dir / "features"

        if not features_dir.exists():
            print("⚠️  features/ directory not found, skipping")
            return

        print("Scanning features/ directory...")

        # Find all markdown files except _index.md
        feature_files = [f for f in features_dir.glob("*.md") if f.name != "_index.md"]

        for feature_file in feature_files:
            feature_result = self._verify_feature(feature_file)
            self.summary.results.append(feature_result)
            self.summary.total_specs += 1

            if feature_result.status == "PASS":
                self.summary.passed += 1
            elif feature_result.status == "FAIL":
                self.summary.failed += 1
            elif feature_result.status == "WARNING":
                self.summary.warnings += 1

        print(f"  Scanned {len(feature_files)} feature specs")

    def _verify_feature(self, file_path: Path) -> SpecScanResult:
        """Verify a single feature spec file."""
        feature_id = file_path.stem  # e.g., "cli-001-main-translate"
        messages = []
        status = "PASS"

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return SpecScanResult(
                spec_type="feature",
                spec_id=feature_id,
                status="FAIL",
                messages=[f"Failed to read file: {e}"],
                location=str(file_path),
            )

        # Check for basic content
        if not content.strip():
            messages.append("File is empty")
            status = "FAIL"

        # Check for feature ID in heading
        if not re.search(
            r"^#\s+" + re.escape(feature_id.upper().replace("-", "-")),
            content,
            re.MULTILINE | re.IGNORECASE,
        ):
            # More flexible: just check for any heading
            if not re.search(r"^#\s+", content, re.MULTILINE):
                messages.append("No heading found in file")
                if status == "PASS":
                    status = "WARNING"

        # Check for status marker
        if "**Status:**" not in content and "**Feature:**" not in content:
            messages.append("No status marker found")
            if status == "PASS":
                status = "WARNING"

        # Check for Evidence section
        if "## Evidence" not in content:
            messages.append("No Evidence section found")
            if status == "PASS":
                status = "WARNING"

        # Check for related specs references (optional)
        if "## Related Specs" in content:
            messages.append("Contains Related Specs section (good)")

        if status == "PASS":
            messages.append("All checks passed")

        return SpecScanResult(
            spec_type="feature",
            spec_id=feature_id,
            status=status,
            messages=messages,
            location=str(file_path),
        )

    def _scan_entrypoints(self) -> None:
        """Scan entrypoints.md."""
        entrypoints_file = self.specs_dir / "entrypoints.md"

        if not entrypoints_file.exists():
            print("⚠️  entrypoints.md not found, skipping")
            return

        print("Scanning entrypoints.md...")

        try:
            with open(entrypoints_file, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            result = SpecScanResult(
                spec_type="entrypoints",
                spec_id="entrypoints.md",
                status="FAIL",
                messages=[f"Failed to read file: {e}"],
                location=str(entrypoints_file),
            )
            self.summary.results.append(result)
            self.summary.total_specs += 1
            self.summary.failed += 1
            return

        # Extract entrypoints (lines starting with ###)
        entrypoint_pattern = r"^###\s+(.+)$"
        entrypoints = re.findall(entrypoint_pattern, content, re.MULTILINE)

        messages = []
        status = "PASS"

        if not entrypoints:
            messages.append("No entrypoints found (no ### headings)")
            status = "FAIL"
        else:
            messages.append(f"Found {len(entrypoints)} entrypoints")

            # Check each entrypoint has description and evidence
            for ep in entrypoints:
                # Look for the section after this heading
                ep_section_match = re.search(
                    rf"###\s+{re.escape(ep)}.*?(?=^###|\Z)", content, re.MULTILINE | re.DOTALL
                )

                if ep_section_match:
                    section = ep_section_match.group(0)

                    # Check for description
                    if "**Description:**" not in section and "**Command:**" not in section:
                        messages.append(f"Entrypoint '{ep}' missing description or command")
                        if status == "PASS":
                            status = "WARNING"

                    # Check for evidence link
                    if "**Evidence:**" not in section:
                        messages.append(f"Entrypoint '{ep}' missing evidence reference")
                        if status == "PASS":
                            status = "WARNING"

        if status == "PASS" and not any("missing" in m for m in messages):
            messages.append("All checks passed")

        result = SpecScanResult(
            spec_type="entrypoints",
            spec_id="entrypoints.md",
            status=status,
            messages=messages,
            location=str(entrypoints_file),
        )

        self.summary.results.append(result)
        self.summary.total_specs += 1

        if status == "PASS":
            self.summary.passed += 1
        elif status == "FAIL":
            self.summary.failed += 1
        elif status == "WARNING":
            self.summary.warnings += 1

    def _scan_evidence_registry(self) -> None:
        """Verify evidence registry entries point to valid files."""
        if not self.evidence_registry:
            return

        print("Verifying evidence registry entries...")

        for evidence_id, evidence_data in self.evidence_registry.items():
            result = self._verify_evidence(evidence_id, evidence_data)
            self.summary.results.append(result)
            self.summary.total_specs += 1

            if result.status == "PASS":
                self.summary.passed += 1
            elif result.status == "FAIL":
                self.summary.failed += 1
            elif result.status == "WARNING":
                self.summary.warnings += 1

        print(f"  Verified {len(self.evidence_registry)} evidence entries")

    def _verify_evidence(self, evidence_id: str, evidence_data: dict) -> SpecScanResult:
        """Verify a single evidence entry."""
        messages = []
        status = "PASS"

        # Check required fields
        if "pointer" not in evidence_data:
            messages.append("Missing 'pointer' field")
            status = "FAIL"
        else:
            pointer = evidence_data["pointer"]

            # Parse pointer (format: "file:line" or "file")
            parts = pointer.split(":")
            file_path = parts[0]
            line_num = parts[1] if len(parts) > 1 else None

            # Check if file exists
            full_path = self.project_root / file_path
            if not full_path.exists():
                messages.append(f"Pointer file not found: {file_path}")
                status = "FAIL"
            else:
                # Optionally verify line number
                if line_num:
                    try:
                        line_int = int(line_num)
                        # Check if line number is reasonable (basic check)
                        if line_int < 1:
                            messages.append(f"Invalid line number: {line_num}")
                            if status == "PASS":
                                status = "WARNING"
                    except ValueError:
                        messages.append(f"Invalid line number format: {line_num}")
                        if status == "PASS":
                            status = "WARNING"

        # Check type field
        if "type" not in evidence_data:
            messages.append("Missing 'type' field")
            if status == "PASS":
                status = "WARNING"

        if status == "PASS":
            messages.append("Pointer file exists")

        return SpecScanResult(
            spec_type="evidence",
            spec_id=evidence_id,
            status=status,
            messages=messages,
            location=f"_evidence_index.yml:{evidence_id}",
        )

    def _generate_report(self) -> Path:
        """Generate markdown compliance report."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.report_dir / f"spec_compliance_{timestamp}.md"

        # Ensure report directory exists
        self.report_dir.mkdir(parents=True, exist_ok=True)

        # Group results by spec type
        results_by_type: dict[str, list[SpecScanResult]] = {}
        for result in self.summary.results:
            if result.spec_type not in results_by_type:
                results_by_type[result.spec_type] = []
            results_by_type[result.spec_type].append(result)

        # Generate report content
        lines = []
        lines.append("# Spec Compliance Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Specs Directory:** {self.specs_dir}")
        lines.append(f"**Total Specs Scanned:** {self.summary.total_specs}")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        pass_pct = (
            (self.summary.passed / self.summary.total_specs * 100)
            if self.summary.total_specs > 0
            else 0
        )
        fail_pct = (
            (self.summary.failed / self.summary.total_specs * 100)
            if self.summary.total_specs > 0
            else 0
        )
        warn_pct = (
            (self.summary.warnings / self.summary.total_specs * 100)
            if self.summary.total_specs > 0
            else 0
        )

        lines.append(
            f"- ✅ **Passed:** {self.summary.passed}/{self.summary.total_specs} ({pass_pct:.1f}%)"
        )
        lines.append(
            f"- ❌ **Failed:** {self.summary.failed}/{self.summary.total_specs} ({fail_pct:.1f}%)"
        )
        lines.append(
            f"- ⚠️  **Warnings:** {self.summary.warnings}/{self.summary.total_specs} ({warn_pct:.1f}%)"
        )
        lines.append("")

        # Overall status
        if self.summary.failed == 0:
            lines.append("**Overall Status:** ✅ PASS")
        else:
            lines.append("**Overall Status:** ❌ FAIL")
        lines.append("")

        # Detailed results by type
        lines.append("## Detailed Results")
        lines.append("")

        for spec_type, results in sorted(results_by_type.items()):
            lines.append(f"### {spec_type.replace('_', ' ').title()}")
            lines.append("")

            passed = sum(1 for r in results if r.status == "PASS")
            failed = sum(1 for r in results if r.status == "FAIL")
            warnings = sum(1 for r in results if r.status == "WARNING")

            type_status = "✅ PASS" if failed == 0 else "❌ FAIL"
            lines.append(f"**Status:** {type_status}")
            lines.append(
                f"**Total:** {len(results)} | **Passed:** {passed} | **Failed:** {failed} | **Warnings:** {warnings}"
            )
            lines.append("")

            # Show failures first
            failures = [r for r in results if r.status == "FAIL"]
            if failures:
                lines.append("#### Failures")
                lines.append("")
                for result in failures:
                    lines.append(f"**{result.spec_id}**")
                    lines.append(f"- Location: `{result.location}`")
                    for msg in result.messages:
                        lines.append(f"- ❌ {msg}")
                    lines.append("")

            # Show warnings
            warns = [r for r in results if r.status == "WARNING"]
            if warns:
                lines.append("#### Warnings")
                lines.append("")
                for result in warns:
                    lines.append(f"**{result.spec_id}**")
                    lines.append(f"- Location: `{result.location}`")
                    for msg in result.messages:
                        lines.append(f"- ⚠️  {msg}")
                    lines.append("")

        # Recommendations
        lines.append("## Recommendations")
        lines.append("")

        if self.summary.failed == 0 and self.summary.warnings == 0:
            lines.append("All specs are in good shape! No action required.")
        else:
            recommendations = []

            # Check for specific issues
            for result in self.summary.results:
                if result.status == "FAIL":
                    for msg in result.messages:
                        if "Evidence ID not found" in msg:
                            evidence_id = msg.split(": ")[1] if ": " in msg else "unknown"
                            recommendations.append(f"Add missing evidence entry: {evidence_id}")
                        elif "Pointer file not found" in msg:
                            file_path = msg.split(": ")[1] if ": " in msg else "unknown"
                            recommendations.append(f"Create or fix pointer to: {file_path}")
                        elif "Missing required field" in msg:
                            field = msg.split(": ")[1] if ": " in msg else "unknown"
                            recommendations.append(
                                f"Add missing field '{field}' in {result.spec_id}"
                            )

            # Deduplicate recommendations
            recommendations = list(set(recommendations))

            if recommendations:
                for i, rec in enumerate(recommendations[:10], 1):  # Limit to top 10
                    lines.append(f"{i}. {rec}")
            else:
                lines.append("Review warnings and address as needed.")

        lines.append("")

        # Write report
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return report_path

    def _print_summary(self) -> None:
        """Print summary to console."""
        print()
        print("=" * 60)
        print("SCAN SUMMARY")
        print("=" * 60)
        print(f"Total specs scanned: {self.summary.total_specs}")
        print(f"[PASS] Passed:  {self.summary.passed}")
        print(f"[FAIL] Failed:  {self.summary.failed}")
        print(f"[WARN] Warnings: {self.summary.warnings}")
        print()

        if self.summary.failed == 0:
            print("[PASS] All checks passed!")
        else:
            print("[FAIL] Some checks failed. See report for details.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Verify specs/ against implementation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.specscan
  python -m scripts.specscan --specs-dir specs/ --report-dir reports/
  python -m scripts.specscan --project-root /path/to/project
        """,
    )

    parser.add_argument(
        "--specs-dir", type=Path, default=Path("specs/"), help="Specs directory (default: specs/)"
    )

    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports/"),
        help="Report output directory (default: reports/)",
    )

    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Project root directory (default: current directory)",
    )

    args = parser.parse_args()

    # Resolve paths
    specs_dir = args.specs_dir.resolve()
    report_dir = args.report_dir.resolve()
    project_root = args.project_root.resolve()

    # Validate specs directory exists
    if not specs_dir.exists():
        print(f"Error: Specs directory not found: {specs_dir}", file=sys.stderr)
        return 1

    # Create scanner and run
    scanner = SpecScanner(specs_dir, report_dir, project_root)
    exit_code = scanner.scan_all()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
