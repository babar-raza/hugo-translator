"""
Production quality gates for translation validation.

Provides automated quality checks to detect translation issues before production.
"""
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class GateStatus(str, Enum):
    """Status of a quality gate check."""

    PASS = "pass"
    """Gate check passed - no issues detected."""

    WARN = "warn"
    """Gate check found potential issues - review recommended."""

    FAIL = "fail"
    """Gate check failed - translation should not proceed."""


@dataclass
class GateResult:
    """Result of a single quality gate check."""

    gate_name: str
    """Name of the gate that produced this result."""

    status: GateStatus
    """Pass/warn/fail status."""

    message: str
    """Human-readable description of the result."""

    details: Dict[str, Any] = field(default_factory=dict)
    """Additional details about the check (metrics, thresholds, etc.)."""

    def __str__(self) -> str:
        """Format result as string."""
        status_symbol = {
            GateStatus.PASS: "[PASS]",
            GateStatus.WARN: "[WARN]",
            GateStatus.FAIL: "[FAIL]"
        }
        return f"{status_symbol[self.status]} {self.gate_name}: {self.message}"


@dataclass
class GateReport:
    """Collection of quality gate results."""

    results: List[GateResult]
    """Individual gate results."""

    file_path: Optional[str] = None
    """File that was checked."""

    target_lang: Optional[str] = None
    """Target language code."""

    def has_failures(self) -> bool:
        """Check if any gates failed."""
        return any(r.status == GateStatus.FAIL for r in self.results)

    def has_warnings(self) -> bool:
        """Check if any gates warned."""
        return any(r.status == GateStatus.WARN for r in self.results)

    def get_summary(self) -> Dict[str, int]:
        """Get count of each status."""
        return {
            "pass": sum(1 for r in self.results if r.status == GateStatus.PASS),
            "warn": sum(1 for r in self.results if r.status == GateStatus.WARN),
            "fail": sum(1 for r in self.results if r.status == GateStatus.FAIL),
        }

    def get_overall_status(self) -> GateStatus:
        """Get overall status (worst status wins)."""
        if self.has_failures():
            return GateStatus.FAIL
        if self.has_warnings():
            return GateStatus.WARN
        return GateStatus.PASS

    def format_console(self) -> str:
        """Format report for console output."""
        lines = []
        lines.append("=" * 80)
        lines.append("QUALITY GATES REPORT")
        lines.append("=" * 80)

        if self.file_path:
            lines.append(f"File: {self.file_path}")
        if self.target_lang:
            lines.append(f"Target Language: {self.target_lang}")
        if self.file_path or self.target_lang:
            lines.append("")

        # Add results
        for result in self.results:
            lines.append(str(result))
            if result.details:
                for key, value in result.details.items():
                    lines.append(f"  {key}: {value}")

        # Add summary
        lines.append("")
        summary = self.get_summary()
        lines.append(f"Summary: {summary['pass']} PASS, {summary['warn']} WARN, {summary['fail']} FAIL")

        overall = self.get_overall_status()
        if overall == GateStatus.FAIL:
            lines.append("Recommendation: TRANSLATION REJECTED - Fix issues before committing")
        elif overall == GateStatus.WARN:
            lines.append("Recommendation: REVIEW REQUIRED - Manual inspection recommended")
        else:
            lines.append("Recommendation: APPROVED - Translation quality acceptable")

        lines.append("=" * 80)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary (for JSON serialization)."""
        return {
            "file_path": self.file_path,
            "target_lang": self.target_lang,
            "gates": [
                {
                    "name": r.gate_name,
                    "status": r.status.value,
                    "message": r.message,
                    "details": r.details
                }
                for r in self.results
            ],
            "summary": self.get_summary(),
            "overall_status": self.get_overall_status().value
        }


class QualityGate:
    """Base class for quality gates."""

    def __init__(self, name: str, enabled: bool = True):
        """
        Initialize quality gate.

        Args:
            name: Gate name
            enabled: Whether gate is enabled
        """
        self.name = name
        self.enabled = enabled

    def check(
        self,
        source_content: str,
        target_content: str,
        source_doc: Optional[Any] = None,
        target_doc: Optional[Any] = None,
        **kwargs
    ) -> GateResult:
        """
        Check translation quality.

        Args:
            source_content: Source markdown content
            target_content: Target (translated) markdown content
            source_doc: Optional parsed source document
            target_doc: Optional parsed target document
            **kwargs: Additional context

        Returns:
            GateResult with pass/warn/fail status
        """
        raise NotImplementedError


class LineCountGate(QualityGate):
    """
    Detects excessive line count changes.

    Line count changes indicate content concatenation, omission, or expansion.
    The nested list bug caused 23% line loss (79 → 61 lines).
    """

    def __init__(
        self,
        warn_threshold: float = 0.2,
        fail_threshold: float = 0.4,
        enabled: bool = True
    ):
        """
        Initialize line count gate.

        Args:
            warn_threshold: Warn if line change exceeds this ratio (0.2 = 20%)
            fail_threshold: Fail if line change exceeds this ratio (0.4 = 40%)
            enabled: Whether gate is enabled
        """
        super().__init__("LineCount", enabled)
        self.warn_threshold = warn_threshold
        self.fail_threshold = fail_threshold

    def check(
        self,
        source_content: str,
        target_content: str,
        source_doc: Optional[Any] = None,
        target_doc: Optional[Any] = None,
        **kwargs
    ) -> GateResult:
        """Check line count ratio."""
        # Handle empty source
        if not source_content.strip():
            return GateResult(
                gate_name=self.name,
                status=GateStatus.PASS,
                message="Source is empty (no validation needed)",
                details={"source_lines": 0, "target_lines": len(target_content.strip().split('\n')) if target_content.strip() else 0}
            )

        source_lines = len(source_content.strip().split('\n'))
        target_lines = len(target_content.strip().split('\n'))

        line_ratio = target_lines / source_lines
        change_ratio = abs(1.0 - line_ratio)

        # Add small epsilon to handle floating point precision issues
        # (e.g., 0.19999999999999996 should be treated as 0.2)
        EPSILON = 1e-9

        details = {
            "source_lines": source_lines,
            "target_lines": target_lines,
            "ratio": round(line_ratio, 3),
            "change_pct": round(change_ratio * 100, 1),
            "warn_threshold_pct": round(self.warn_threshold * 100, 1),
            "fail_threshold_pct": round(self.fail_threshold * 100, 1)
        }

        if change_ratio + EPSILON >= self.fail_threshold:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.FAIL,
                message=(
                    f"Excessive line count change: {details['change_pct']}% "
                    f"({source_lines} → {target_lines} lines). "
                    f"This may indicate content concatenation or corruption."
                ),
                details=details
            )
        elif change_ratio + EPSILON >= self.warn_threshold:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.WARN,
                message=(
                    f"Significant line count change: {details['change_pct']}% "
                    f"({source_lines} → {target_lines} lines). "
                    f"Review recommended."
                ),
                details=details
            )
        else:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.PASS,
                message=f"Line count acceptable ({source_lines} → {target_lines} lines, {details['change_pct']}% change)",
                details=details
            )


class ListStructureGate(QualityGate):
    """
    Detects list structure degradation (flattening, concatenation).

    Checks:
    - List item count (should be ±10% of source)
    - List container count (should be ±30% of source)
    - Nested indentation present (at least 1 indented list if source has nesting)
    """

    def __init__(
        self,
        item_warn_threshold: float = 0.1,
        item_fail_threshold: float = 0.2,
        container_warn_threshold: float = 0.2,
        container_fail_threshold: float = 0.3,
        enabled: bool = True
    ):
        """
        Initialize list structure gate.

        Args:
            item_warn_threshold: Warn if list item loss exceeds this ratio
            item_fail_threshold: Fail if list item loss exceeds this ratio
            container_warn_threshold: Warn if container loss exceeds this ratio
            container_fail_threshold: Fail if container loss exceeds this ratio
            enabled: Whether gate is enabled
        """
        super().__init__("ListStructure", enabled)
        self.item_warn_threshold = item_warn_threshold
        self.item_fail_threshold = item_fail_threshold
        self.container_warn_threshold = container_warn_threshold
        self.container_fail_threshold = container_fail_threshold

    def _count_list_items(self, content: str) -> int:
        """Count markdown list items (lines starting with -, *, or digit)."""
        count = 0
        lines = content.split('\n')
        for line in lines:
            stripped = line.lstrip()
            # Check for unordered list (-, *, +)
            if stripped.startswith(('-', '*', '+')):
                # Make sure it's not a horizontal rule (---, ***)
                if len(stripped) >= 2 and stripped[1] not in ('-', '*', '+'):
                    count += 1
            # Check for ordered list (1., 2., etc.)
            elif re.match(r'^\d+\.', stripped):
                count += 1
        return count

    def _count_list_containers(self, content: str) -> int:
        """
        Count separate list containers (groups of consecutive list items).

        A list container is a group of consecutive list items separated by blank lines.
        """
        count = 0
        lines = content.split('\n')
        in_list = False

        for line in lines:
            stripped = line.lstrip()
            is_list_line = False

            # Check if line is a list item
            if stripped.startswith(('-', '*', '+')):
                if len(stripped) >= 2 and stripped[1] not in ('-', '*', '+'):
                    is_list_line = True
            elif re.match(r'^\d+\.', stripped):
                is_list_line = True

            if is_list_line:
                if not in_list:
                    count += 1
                    in_list = True
            elif not stripped:  # Blank line
                in_list = False
            # Non-blank, non-list line doesn't end list (could be continuation)

        return count

    def _has_nested_lists(self, content: str) -> bool:
        """Check if content has nested lists (indented list items)."""
        lines = content.split('\n')
        for line in lines:
            # Check for indented list items (at least 2 spaces)
            if line.startswith(('  -', '  *', '  +', '    -', '    *', '    +')):
                return True
            # Check for indented ordered lists
            if re.match(r'^\s{2,}\d+\.', line):
                return True
        return False

    def check(
        self,
        source_content: str,
        target_content: str,
        source_doc: Optional[Any] = None,
        target_doc: Optional[Any] = None,
        **kwargs
    ) -> GateResult:
        """Check list structure preservation."""
        source_items = self._count_list_items(source_content)
        target_items = self._count_list_items(target_content)

        source_containers = self._count_list_containers(source_content)
        target_containers = self._count_list_containers(target_content)

        source_has_nesting = self._has_nested_lists(source_content)
        target_has_nesting = self._has_nested_lists(target_content)

        # If source has no lists, skip validation
        if source_items == 0:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.PASS,
                message="No lists in source (validation skipped)",
                details={
                    "source_items": 0,
                    "target_items": target_items
                }
            )

        # Calculate retention ratios
        item_retention = target_items / source_items
        item_loss = 1.0 - item_retention

        container_retention = target_containers / source_containers if source_containers > 0 else 1.0
        container_loss = 1.0 - container_retention

        # Add small epsilon to handle floating point precision issues
        EPSILON = 1e-9

        details = {
            "source_items": source_items,
            "target_items": target_items,
            "item_retention": round(item_retention, 3),
            "item_loss_pct": round(item_loss * 100, 1),
            "source_containers": source_containers,
            "target_containers": target_containers,
            "container_retention": round(container_retention, 3),
            "container_loss_pct": round(container_loss * 100, 1),
            "source_has_nesting": source_has_nesting,
            "target_has_nesting": target_has_nesting
        }

        # Check for nesting loss
        nesting_lost = source_has_nesting and not target_has_nesting

        # Determine status based on thresholds
        # Check nesting loss FIRST as it's a specific structural failure
        if nesting_lost:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.FAIL,
                message=(
                    "Nested list structure lost. "
                    "Source has nested lists but target does not."
                ),
                details=details
            )
        elif item_loss + EPSILON >= self.item_fail_threshold:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.FAIL,
                message=(
                    f"Excessive list item loss: {details['item_loss_pct']}% "
                    f"({source_items} → {target_items} items). "
                    f"Lists may be concatenated or corrupted."
                ),
                details=details
            )
        elif container_loss + EPSILON >= self.container_fail_threshold:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.FAIL,
                message=(
                    f"Excessive list container loss: {details['container_loss_pct']}% "
                    f"({source_containers} → {target_containers} containers). "
                    f"List structure may be flattened."
                ),
                details=details
            )
        elif item_loss + EPSILON >= self.item_warn_threshold:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.WARN,
                message=(
                    f"Moderate list item loss: {details['item_loss_pct']}% "
                    f"({source_items} → {target_items} items). "
                    f"Review recommended."
                ),
                details=details
            )
        elif container_loss + EPSILON >= self.container_warn_threshold:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.WARN,
                message=(
                    f"Moderate list container loss: {details['container_loss_pct']}% "
                    f"({source_containers} → {target_containers} containers). "
                    f"Review recommended."
                ),
                details=details
            )
        else:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.PASS,
                message=(
                    f"List structure preserved "
                    f"({source_items} → {target_items} items, "
                    f"{source_containers} → {target_containers} containers)"
                ),
                details=details
            )


class MarkdownSyntaxGate(QualityGate):
    """
    Validates markdown syntax correctness.

    Checks:
    - Markdown parses without errors
    - Frontmatter YAML is valid
    - No unclosed code blocks
    """

    def __init__(self, enabled: bool = True):
        """Initialize markdown syntax gate."""
        super().__init__("MarkdownSyntax", enabled)

    def check(
        self,
        source_content: str,
        target_content: str,
        source_doc: Optional[Any] = None,
        target_doc: Optional[Any] = None,
        **kwargs
    ) -> GateResult:
        """Check markdown syntax validity."""
        errors = []

        # Check for unclosed code blocks
        code_fence_pattern = r'^```'
        code_fences = re.findall(code_fence_pattern, target_content, re.MULTILINE)
        if len(code_fences) % 2 != 0:
            errors.append("Unclosed code fence (odd number of ``` markers)")

        # Check frontmatter if present
        if target_content.startswith('---'):
            try:
                # Extract frontmatter
                parts = target_content.split('---', 2)
                if len(parts) >= 3:
                    fm_yaml = parts[1]
                    yaml.safe_load(fm_yaml)
            except yaml.YAMLError as e:
                errors.append(f"Invalid frontmatter YAML: {e}")

        # Try to parse with HugoParser if available (optional check)
        if target_doc is None:
            try:
                from ...parser.hugo_parser import HugoParser
                parser = HugoParser()
                parser.parse_string(target_content)
            except ImportError:
                # HugoParser not available, skip parsing check
                pass
            except Exception as e:
                # Actual parsing error
                errors.append(f"Markdown parsing failed: {e}")

        details = {
            "errors": errors,
            "code_fence_count": len(code_fences)
        }

        if errors:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.FAIL,
                message=f"Markdown syntax errors detected: {'; '.join(errors)}",
                details=details
            )
        else:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.PASS,
                message="Markdown syntax valid",
                details=details
            )


class GateRunner:
    """Runs multiple quality gates and generates a report."""

    def __init__(self, gates: List[QualityGate]):
        """
        Initialize gate runner.

        Args:
            gates: List of quality gates to run
        """
        self.gates = [g for g in gates if g.enabled]

    def run_all(
        self,
        source_content: str,
        target_content: str,
        file_path: Optional[str] = None,
        target_lang: Optional[str] = None,
        **kwargs
    ) -> GateReport:
        """
        Run all enabled gates.

        Args:
            source_content: Source markdown content
            target_content: Target (translated) markdown content
            file_path: Optional file path for reporting
            target_lang: Optional target language for reporting
            **kwargs: Additional context passed to gates

        Returns:
            GateReport with all results
        """
        results = []

        for gate in self.gates:
            try:
                result = gate.check(source_content, target_content, **kwargs)
                results.append(result)

                # Log result
                if result.status == GateStatus.FAIL:
                    logger.error(f"Quality gate FAILED: {result}")
                elif result.status == GateStatus.WARN:
                    logger.warning(f"Quality gate WARNING: {result}")
                else:
                    logger.debug(f"Quality gate passed: {result}")

            except Exception as e:
                logger.exception(f"Quality gate {gate.name} crashed: {e}")
                results.append(GateResult(
                    gate_name=gate.name,
                    status=GateStatus.FAIL,
                    message=f"Gate crashed: {e}",
                    details={"exception": str(e)}
                ))

        return GateReport(
            results=results,
            file_path=file_path,
            target_lang=target_lang
        )


def get_default_gates() -> List[QualityGate]:
    """
    Get default quality gates with standard thresholds.

    Returns:
        List of quality gates ready to use
    """
    return [
        LineCountGate(
            warn_threshold=0.2,  # 20% change
            fail_threshold=0.4   # 40% change
        ),
        ListStructureGate(
            item_warn_threshold=0.1,     # 10% item loss
            item_fail_threshold=0.2,     # 20% item loss
            container_warn_threshold=0.2, # 20% container loss
            container_fail_threshold=0.3  # 30% container loss
        ),
        MarkdownSyntaxGate()
    ]
