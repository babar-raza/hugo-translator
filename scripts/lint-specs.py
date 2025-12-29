#!/usr/bin/env python3
"""
Automated spec-lint checker for Hugo Translation System specs.

Usage:
    python scripts/lint-specs.py --all                 # Check all specs
    python scripts/lint-specs.py specs/features/*.md   # Check specific files
    python scripts/lint-specs.py --fix --all           # Auto-fix violations

Exit codes:
    0 - All checks passed
    1 - Violations found
    2 - Error (file not found, invalid YAML, etc.)
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional
import yaml


class Violation:
    """Represents a spec-lint violation."""

    def __init__(self, rule: str, file: Path, line: Optional[int], message: str, fixable: bool = False):
        self.rule = rule
        self.file = file
        self.line = line
        self.message = message
        self.fixable = fixable

    def __str__(self):
        location = f"{self.file}:{self.line}" if self.line else str(self.file)
        fix_mark = " [FIXABLE]" if self.fixable else ""
        return f"{location} - {self.rule}: {self.message}{fix_mark}"


class SpecLinter:
    """Automated spec linter."""

    def __init__(self):
        self.violations: List[Violation] = []

    def check_naming(self, spec_path: Path) -> None:
        """RULE-S1: Check filename follows {category}-{number}-{slug}.md"""
        pattern = r'^[a-z]+-\d{3}-[a-z0-9-]+\.md$'
        if not re.match(pattern, spec_path.name):
            self.violations.append(Violation(
                rule="RULE-S1",
                file=spec_path,
                line=None,
                message=f"Invalid filename '{spec_path.name}'. Expected pattern: {{category}}-{{number}}-{{slug}}.md (e.g., cli-001-main-translate.md)",
                fixable=False
            ))

    def check_frontmatter(self, spec_path: Path) -> None:
        """RULE-S2: Check required frontmatter fields."""
        required_fields = ['spec_id', 'title', 'category', 'status', 'priority', 'risk_if_unspecified', 'last_updated']

        try:
            content = spec_path.read_text(encoding='utf-8')
        except Exception as e:
            self.violations.append(Violation(
                rule="RULE-S2",
                file=spec_path,
                line=None,
                message=f"Failed to read file: {e}",
                fixable=False
            ))
            return

        # Extract frontmatter
        if not content.startswith('---\n'):
            self.violations.append(Violation(
                rule="RULE-S2",
                file=spec_path,
                line=1,
                message="Missing frontmatter (must start with '---')",
                fixable=False
            ))
            return

        # Find end of frontmatter
        end_match = re.search(r'\n---\n', content[4:])
        if not end_match:
            self.violations.append(Violation(
                rule="RULE-S2",
                file=spec_path,
                line=1,
                message="Frontmatter not closed (missing closing '---')",
                fixable=False
            ))
            return

        frontmatter_text = content[4:4 + end_match.start()]

        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as e:
            self.violations.append(Violation(
                rule="RULE-S2",
                file=spec_path,
                line=1,
                message=f"Invalid YAML in frontmatter: {e}",
                fixable=False
            ))
            return

        if not isinstance(frontmatter, dict):
            self.violations.append(Violation(
                rule="RULE-S2",
                file=spec_path,
                line=1,
                message="Frontmatter is not a YAML dictionary",
                fixable=False
            ))
            return

        # Check required fields
        for field in required_fields:
            if field not in frontmatter:
                self.violations.append(Violation(
                    rule="RULE-S2",
                    file=spec_path,
                    line=1,
                    message=f"Missing required frontmatter field: {field}",
                    fixable=False
                ))

    def check_spec_id_in_inventory(self, spec_path: Path, inventory_path: Path) -> None:
        """RULE-T1: Check spec_id exists in inventory."""
        try:
            content = spec_path.read_text(encoding='utf-8')
            frontmatter_match = re.search(r'^---\n(.*?)\n---\n', content, re.DOTALL)
            if not frontmatter_match:
                return  # Already reported by check_frontmatter

            frontmatter = yaml.safe_load(frontmatter_match.group(1))
            if not isinstance(frontmatter, dict):
                return  # Already reported by check_frontmatter

            spec_id = frontmatter.get('spec_id')
            if not spec_id:
                return  # Already reported by check_frontmatter

            # Check inventory
            if not inventory_path.exists():
                self.violations.append(Violation(
                    rule="RULE-T1",
                    file=spec_path,
                    line=None,
                    message=f"Inventory file not found: {inventory_path}",
                    fixable=False
                ))
                return

            inventory = yaml.safe_load(inventory_path.read_text(encoding='utf-8'))
            surface_ids = [surface['id'] for surface in inventory.get('surfaces', [])]

            if spec_id not in surface_ids:
                self.violations.append(Violation(
                    rule="RULE-T1",
                    file=spec_path,
                    line=None,
                    message=f"spec_id '{spec_id}' not found in inventory (valid IDs: {', '.join(surface_ids[:5])}...)",
                    fixable=False
                ))

        except Exception as e:
            self.violations.append(Violation(
                rule="RULE-T1",
                file=spec_path,
                line=None,
                message=f"Error checking spec_id: {e}",
                fixable=False
            ))

    def check_valid_status(self, spec_path: Path) -> None:
        """RULE-ST1: Check status field has valid value."""
        valid_statuses = ['EVIDENCE_ONLY', 'VERIFIED', 'INFERRED', 'DEPRECATED']

        try:
            content = spec_path.read_text(encoding='utf-8')
            frontmatter_match = re.search(r'^---\n(.*?)\n---\n', content, re.DOTALL)
            if not frontmatter_match:
                return  # Already reported by check_frontmatter

            frontmatter = yaml.safe_load(frontmatter_match.group(1))
            if not isinstance(frontmatter, dict):
                return  # Already reported by check_frontmatter

            status = frontmatter.get('status')
            if not status:
                return  # Already reported by check_frontmatter

            if status not in valid_statuses:
                self.violations.append(Violation(
                    rule="RULE-ST1",
                    file=spec_path,
                    line=None,
                    message=f"Invalid status '{status}'. Valid values: {', '.join(valid_statuses)}",
                    fixable=False
                ))

        except Exception as e:
            self.violations.append(Violation(
                rule="RULE-ST1",
                file=spec_path,
                line=None,
                message=f"Error checking status: {e}",
                fixable=False
            ))

    def lint_file(self, spec_path: Path, inventory_path: Optional[Path] = None) -> None:
        """Run all lint checks on a single spec file."""
        self.check_naming(spec_path)
        self.check_frontmatter(spec_path)
        self.check_valid_status(spec_path)
        if inventory_path:
            self.check_spec_id_in_inventory(spec_path, inventory_path)

    def report(self) -> int:
        """Print violations and return exit code."""
        if not self.violations:
            print("OK - All spec-lint checks passed")
            return 0

        print(f"\n{len(self.violations)} spec-lint violation(s) found:\n")
        for v in sorted(self.violations, key=lambda x: (str(x.file), x.line or 0)):
            print(f"  {v}")

        fixable_count = sum(1 for v in self.violations if v.fixable)
        if fixable_count > 0:
            print(f"\n{fixable_count} violation(s) are auto-fixable. Run with --fix to correct them.")

        return 1


def main():
    parser = argparse.ArgumentParser(
        description='Automated spec-lint checker',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python scripts/lint-specs.py --all
  python scripts/lint-specs.py specs/features/cli-001-main-translate.md
  python scripts/lint-specs.py --fix --all
        '''
    )
    parser.add_argument('files', nargs='*', help='Spec files to check')
    parser.add_argument('--all', action='store_true', help='Check all specs in specs/features/')
    parser.add_argument('--fix', action='store_true', help='Auto-fix violations where possible')
    parser.add_argument('--inventory', default='reports/driftless/15_traceability_matrix.yml',
                        help='Path to inventory file (default: reports/driftless/15_traceability_matrix.yml)')

    args = parser.parse_args()

    # Determine files to check
    if args.all:
        specs_dir = Path('specs/features')
        if not specs_dir.exists():
            print(f"Error: specs/features directory not found", file=sys.stderr)
            return 2
        spec_files = sorted(specs_dir.glob('*.md'))
    elif args.files:
        spec_files = [Path(f) for f in args.files]
    else:
        parser.print_help()
        return 2

    # Validate files exist
    for f in spec_files:
        if not f.exists():
            print(f"Error: File not found: {f}", file=sys.stderr)
            return 2

    # Run linter
    linter = SpecLinter()
    inventory_path = Path(args.inventory) if args.inventory else None

    print(f"Checking {len(spec_files)} spec file(s)...")
    for spec_file in spec_files:
        linter.lint_file(spec_file, inventory_path)

    # Report results
    return linter.report()


if __name__ == '__main__':
    sys.exit(main())
