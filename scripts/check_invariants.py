#!/usr/bin/env python3
"""
Invariant Checker CLI - Validates context protection invariants after translation.

Usage:
    python scripts/check_invariants.py --source doc.md --translated doc_trans.md
    python scripts/check_invariants.py --source doc.md --translated doc_trans.md --strict
    python scripts/check_invariants.py --source doc.md --translated doc_trans.md --output results.json
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path


class InvariantCheckResult:
    """Result of a single invariant check"""
    def __init__(self, name: str, passed: bool, message: str, details: dict = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details or {}

    def to_dict(self):
        return {
            'name': self.name,
            'passed': self.passed,
            'message': self.message,
            'details': self.details
        }


class PlaceholderInvariantChecker:
    """Validates placeholder preservation through translation"""

    PLACEHOLDER_PATTERN = re.compile(r'⟦([A-Z0-9_]+)⟧')

    def check_exact_count(self, source: str, translated: str) -> InvariantCheckResult:
        """Invariant 1: Placeholder count must match exactly"""
        source_phs = self.PLACEHOLDER_PATTERN.findall(source)
        translated_phs = self.PLACEHOLDER_PATTERN.findall(translated)

        passed = len(source_phs) == len(translated_phs)
        message = f"Expected {len(source_phs)} placeholders, found {len(translated_phs)}"

        return InvariantCheckResult(
            name="placeholder_exact_count",
            passed=passed,
            message=message,
            details={
                'expected_count': len(source_phs),
                'actual_count': len(translated_phs),
                'missing': list(set(source_phs) - set(translated_phs)),
                'extra': list(set(translated_phs) - set(source_phs))
            }
        )

    def check_set_equality(self, source: str, translated: str) -> InvariantCheckResult:
        """Invariant 2: Set of placeholder IDs must be identical"""
        source_phs = set(self.PLACEHOLDER_PATTERN.findall(source))
        translated_phs = set(self.PLACEHOLDER_PATTERN.findall(translated))

        passed = source_phs == translated_phs
        missing = source_phs - translated_phs
        extra = translated_phs - source_phs

        if passed:
            message = f"All {len(source_phs)} placeholder IDs preserved"
        else:
            message = f"Placeholder mismatch: {len(missing)} missing, {len(extra)} extra"

        return InvariantCheckResult(
            name="placeholder_set_equality",
            passed=passed,
            message=message,
            details={'missing': list(missing), 'extra': list(extra)}
        )

    def check_no_duplicates(self, text: str, label: str = "text") -> InvariantCheckResult:
        """Invariant 4: No duplicate placeholder IDs (collision detection)"""
        phs = self.PLACEHOLDER_PATTERN.findall(text)
        unique_phs = set(phs)

        passed = len(phs) == len(unique_phs)

        if passed:
            message = f"No duplicates among {len(phs)} placeholders in {label}"
        else:
            from collections import Counter
            dupes = {k: v for k, v in Counter(phs).items() if v > 1}
            message = f"Found {len(dupes)} duplicated placeholders in {label}"
            return InvariantCheckResult(
                name=f"placeholder_no_duplicates_{label}",
                passed=False,
                message=message,
                details={'duplicates': dupes}
            )

        return InvariantCheckResult(
            name=f"placeholder_no_duplicates_{label}",
            passed=True,
            message=message
        )

    def check_checksum(self, source: str, translated: str) -> InvariantCheckResult:
        """Invariant 5: SHA256 checksum of sorted placeholders must match"""
        source_phs = sorted(self.PLACEHOLDER_PATTERN.findall(source))
        translated_phs = sorted(self.PLACEHOLDER_PATTERN.findall(translated))

        source_checksum = hashlib.sha256(','.join(source_phs).encode()).hexdigest()
        translated_checksum = hashlib.sha256(','.join(translated_phs).encode()).hexdigest()

        passed = source_checksum == translated_checksum

        return InvariantCheckResult(
            name="placeholder_checksum",
            passed=passed,
            message=f"Checksum {'match' if passed else 'mismatch'}",
            details={
                'expected_checksum': source_checksum[:16],  # First 16 chars for brevity
                'actual_checksum': translated_checksum[:16]
            }
        )

    def run_all(self, source: str, translated: str) -> list[InvariantCheckResult]:
        """Run all placeholder invariant checks"""
        return [
            self.check_exact_count(source, translated),
            self.check_set_equality(source, translated),
            self.check_no_duplicates(source, "source"),
            self.check_no_duplicates(translated, "translated"),
            self.check_checksum(source, translated)
        ]


class BoundaryInvariantChecker:
    """Validates placeholder boundary rules"""

    PLACEHOLDER_WITH_CONTEXT = re.compile(r'(.)⟦([A-Z0-9_]+)⟧(.)')

    def _is_word_char(self, char: str) -> bool:
        """Check if character is alphanumeric or underscore (Unicode-aware)"""
        if not char:
            return False
        return char.isalnum() or char == '_' or unicodedata.category(char).startswith('L')

    def check_left_boundary(self, text: str) -> InvariantCheckResult:
        """Invariant: Left boundary must not be alphanumeric"""
        matches = self.PLACEHOLDER_WITH_CONTEXT.findall(text)

        violations = []
        for left, ph_id, right in matches:
            if self._is_word_char(left):
                violations.append(f"⟦{ph_id}⟧ has invalid left boundary: '{left}'")

        passed = len(violations) == 0
        message = f"Checked {len(matches)} placeholders, {len(violations)} left boundary violations"

        return InvariantCheckResult(
            name="boundary_left",
            passed=passed,
            message=message,
            details={'violations': violations[:10]}  # Limit to first 10
        )

    def check_right_boundary(self, text: str) -> InvariantCheckResult:
        """Invariant: Right boundary must not be alphanumeric"""
        matches = self.PLACEHOLDER_WITH_CONTEXT.findall(text)

        violations = []
        for left, ph_id, right in matches:
            if self._is_word_char(right):
                violations.append(f"⟦{ph_id}⟧ has invalid right boundary: '{right}'")

        passed = len(violations) == 0
        message = f"Checked {len(matches)} placeholders, {len(violations)} right boundary violations"

        return InvariantCheckResult(
            name="boundary_right",
            passed=passed,
            message=message,
            details={'violations': violations[:10]}  # Limit to first 10
        )

    def run_all(self, text: str) -> list[InvariantCheckResult]:
        """Run all boundary checks"""
        return [
            self.check_left_boundary(text),
            self.check_right_boundary(text)
        ]


class CodeBlockPolicyChecker:
    """Validates code block handling policies"""

    CODE_BLOCK_PATTERN = re.compile(r'```(\w+)?\n(.*?)```', re.DOTALL)

    FULL_BYPASS_LANGUAGES = {'python', 'java', 'csharp', 'c', 'cpp', 'go', 'rust', 'javascript', 'typescript'}

    def check_full_bypass_unchanged(self, source: str, translated: str) -> InvariantCheckResult:
        """Invariant: Python/Java/C# code blocks must be byte-for-byte identical"""
        source_blocks = self.CODE_BLOCK_PATTERN.findall(source)
        translated_blocks = self.CODE_BLOCK_PATTERN.findall(translated)

        violations = []

        # Match blocks by index (assume same order)
        for idx, ((src_lang, src_code), (trans_lang, trans_code)) in enumerate(
            zip(source_blocks, translated_blocks, strict=False)
        ):
            if src_lang and src_lang.lower() in self.FULL_BYPASS_LANGUAGES:
                if src_code != trans_code:
                    violations.append(
                        f"Block {idx} ({src_lang}): {len(src_code)} → {len(trans_code)} bytes"
                    )

        passed = len(violations) == 0
        checked_blocks = sum(
            1 for lang, _ in source_blocks
            if lang and lang.lower() in self.FULL_BYPASS_LANGUAGES
        )
        message = f"Checked {checked_blocks} bypass-language blocks, {len(violations)} violations"

        return InvariantCheckResult(
            name="codeblock_full_bypass",
            passed=passed,
            message=message,
            details={'violations': violations[:10]}  # Limit to first 10
        )

    def run_all(self, source: str, translated: str) -> list[InvariantCheckResult]:
        """Run all code block policy checks"""
        return [
            self.check_full_bypass_unchanged(source, translated)
        ]


class StructuralIntegrityChecker:
    """Validates document structure preservation"""

    def check_frontmatter_keys(self, source: str, translated: str) -> InvariantCheckResult:
        """Invariant: Frontmatter keys must be identical"""
        def extract_frontmatter_keys(text: str) -> list[str]:
            if not text.startswith('---\n'):
                return []
            end = text.find('\n---\n', 4)
            if end == -1:
                return []
            frontmatter = text[4:end]
            # Simple key extraction (handles most cases)
            return re.findall(r'^(\w+):', frontmatter, re.MULTILINE)

        source_keys = extract_frontmatter_keys(source)
        translated_keys = extract_frontmatter_keys(translated)

        passed = source_keys == translated_keys

        return InvariantCheckResult(
            name="frontmatter_keys_preserved",
            passed=passed,
            message=f"Frontmatter keys {'preserved' if passed else 'modified'}",
            details={
                'expected_keys': source_keys,
                'actual_keys': translated_keys
            }
        )

    def check_shortcode_syntax(self, translated: str) -> InvariantCheckResult:
        """Invariant: Shortcode syntax must be valid"""
        # Check for broken shortcodes
        broken_patterns = [
            r'{{<[^>]*$',  # Unclosed {{<
            r'{{%[^%]*$',  # Unclosed {{%
            r'⟦[^⟧]*$',    # Unclosed placeholder
        ]

        violations = []
        for pattern in broken_patterns:
            matches = re.findall(pattern, translated, re.MULTILINE)
            if matches:
                violations.extend(matches[:5])  # Limit to 5 per pattern

        passed = len(violations) == 0

        return InvariantCheckResult(
            name="shortcode_syntax_valid",
            passed=passed,
            message=f"{'No' if passed else len(violations)} broken shortcodes found",
            details={'violations': violations[:10]}
        )

    def run_all(self, source: str, translated: str) -> list[InvariantCheckResult]:
        """Run all structural checks"""
        return [
            self.check_frontmatter_keys(source, translated),
            self.check_shortcode_syntax(translated)
        ]


class BasicTerminologyChecker:
    """Basic terminology preservation checker with common technical terms"""

    # Hardcoded common technical terms that must never be translated
    DEFAULT_TERMS = {
        # Programming general
        'API', 'REST', 'JSON', 'XML', 'HTTP', 'HTTPS', 'URL', 'URI',
        'callback', 'middleware', 'endpoint', 'async', 'await', 'Promise',
        'closure', 'boolean', 'null', 'undefined',

        # Python specific
        'DataFrame', 'Series', 'numpy', 'pandas', 'dict', 'list',
        'lambda', 'yield', 'import', 'class', 'def',

        # Data structures
        'array', 'vector', 'matrix', 'tuple', 'set', 'map',
        'queue', 'stack', 'tree', 'graph'
    }

    def check_common_terms(self, source: str, translated: str) -> InvariantCheckResult:
        """Check that common technical terms are preserved"""
        violations = []

        for term in self.DEFAULT_TERMS:
            # Case-sensitive exact match
            source_count = source.count(term)
            if source_count > 0:
                translated_count = translated.count(term)
                if translated_count != source_count:
                    violations.append(f"{term}: {source_count} → {translated_count}")

        passed = len(violations) == 0
        checked = len([t for t in self.DEFAULT_TERMS if t in source])

        return InvariantCheckResult(
            name="common_technical_terms_preserved",
            passed=passed,
            message=f"Checked {checked} common technical terms, {len(violations)} violations",
            details={'violations': violations[:10]}  # Limit to first 10
        )

    def run_all(self, source: str, translated: str) -> list[InvariantCheckResult]:
        """Run all terminology checks"""
        return [self.check_common_terms(source, translated)]


def run_invariant_checks(source_file: Path, translated_file: Path) -> dict:
    """Run all invariant checks on a source/translated pair"""
    source = source_file.read_text(encoding='utf-8')
    translated = translated_file.read_text(encoding='utf-8')

    results = []

    # Run all checker categories
    results.extend(PlaceholderInvariantChecker().run_all(source, translated))
    results.extend(BoundaryInvariantChecker().run_all(translated))
    results.extend(CodeBlockPolicyChecker().run_all(source, translated))
    results.extend(StructuralIntegrityChecker().run_all(source, translated))
    results.extend(BasicTerminologyChecker().run_all(source, translated))

    # Aggregate results
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    return {
        'summary': {
            'total_checks': total,
            'passed': passed,
            'failed': failed,
            'pass_rate': passed / total if total > 0 else 0
        },
        'results': [r.to_dict() for r in results],
        'overall_pass': failed == 0
    }


def main():
    parser = argparse.ArgumentParser(description='Invariant checker for context protection')
    parser.add_argument('--source', type=Path, required=True, help='Source document')
    parser.add_argument('--translated', type=Path, required=True, help='Translated document')
    parser.add_argument('--output', type=Path, help='JSON output file (optional)')
    parser.add_argument('--strict', action='store_true', help='Exit 1 if any check fails')
    parser.add_argument('--quiet', action='store_true', help='Only show failures')

    args = parser.parse_args()

    # Validate files exist
    if not args.source.exists():
        print(f"[ERROR] Source file not found: {args.source}")
        return 1
    if not args.translated.exists():
        print(f"[ERROR] Translated file not found: {args.translated}")
        return 1

    # Run checks
    result = run_invariant_checks(args.source, args.translated)

    # Output JSON if requested
    if args.output:
        args.output.write_text(json.dumps(result, indent=2))

    # Print human-readable summary
    if not args.quiet:
        print(f"\n{'='*60}")
        print("INVARIANT CHECK RESULTS")
        print(f"{'='*60}")
        print(f"Total Checks: {result['summary']['total_checks']}")
        print(f"Passed: {result['summary']['passed']} [OK]")
        print(f"Failed: {result['summary']['failed']} [FAIL]")
        print(f"Pass Rate: {result['summary']['pass_rate']*100:.1f}%")
        print(f"{'='*60}\n")

        for check in result['results']:
            if args.quiet and check['passed']:
                continue

            status = "[OK]  PASS" if check['passed'] else "[FAIL] FAIL"
            print(f"{status} | {check['name']}")
            print(f"       {check['message']}")
            if check['details'] and not check['passed']:
                # Pretty print details (use json.dumps to handle Unicode safely)
                for key, value in check['details'].items():
                    if value:  # Only show non-empty details
                        value_str = json.dumps(value, ensure_ascii=True)
                        print(f"       {key}: {value_str}")
            print()

    # Exit code
    if args.strict and not result['overall_pass']:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
