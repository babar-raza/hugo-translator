"""
Enhanced failure classification with multi-failure detection.

This module provides classification logic that detects ALL failures in a verification
result, not just the first match. This addresses the Phase 6 issue where 70% of
failures were classified as FAIL_OTHER due to incomplete classification.
"""
from typing import Dict, List, Optional, Tuple


# Failure category severity ranking (highest to lowest priority)
SEVERITY_RANK = {
    "FAIL_UNTRANSLATED_PROSE": 1,        # Most critical: content not translated
    "FAIL_MARKDOWN_FIDELITY": 2,         # Critical: structure broken
    "FAIL_CODE_SPAN_CHANGED": 3,         # Critical: code altered
    "FAIL_LIST_CONCAT": 4,               # Critical: list corruption
    "FAIL_ENCODING_OR_FRONTMATTER": 5,   # Important: metadata issues
    "FAIL_LINE_COUNT": 6,                # Warning: possible content loss
    "FAIL_OTHER": 7,                     # Lowest: unclassified
}


class FailureInfo:
    """Information about a detected failure."""

    def __init__(self, category: str, reason: str, details: Optional[Dict] = None):
        """
        Initialize failure info.

        Args:
            category: Failure category (e.g., "FAIL_MARKDOWN_FIDELITY")
            reason: Human-readable reason for failure
            details: Additional structured details (optional)
        """
        self.category = category
        self.reason = reason
        self.details = details or {}
        self.severity = SEVERITY_RANK.get(category, 99)

    def __repr__(self):
        return f"FailureInfo(category={self.category}, reason={self.reason})"

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "category": self.category,
            "reason": self.reason,
            "details": self.details,
        }


def classify_all_failures(verify_data: Optional[Dict]) -> Tuple[str, str, List[FailureInfo]]:
    """
    Classify ALL failures in verification data.

    This is an enhanced version that detects multiple failure types, not just the first one.

    Args:
        verify_data: Verification result dictionary from e2e_verify_single_file.py

    Returns:
        Tuple of:
        - primary_category (str): Highest severity failure category
        - primary_reason (str): Human-readable reason for primary failure
        - all_failures (List[FailureInfo]): All detected failures, sorted by severity

    Example:
        >>> verify_data = {"checks": {"markdown_fidelity": {"passed": False}, ...}}
        >>> category, reason, failures = classify_all_failures(verify_data)
        >>> print(category)
        "FAIL_MARKDOWN_FIDELITY"
        >>> print(len(failures))
        3  # Could have multiple failures
    """
    all_failures = []

    if not verify_data:
        failure = FailureInfo("FAIL_OTHER", "No verification data")
        return failure.category, failure.reason, [failure]

    checks = verify_data.get("checks", {})

    # Check for untranslated prose (HIGHEST PRIORITY)
    untranslated_check = checks.get("untranslated", {})
    if not untranslated_check.get("passed", True):
        ratio = untranslated_check.get("ratio", 0)
        threshold = untranslated_check.get("threshold", 0)
        reason = f"Untranslated ratio: {ratio:.2%} (threshold: {threshold:.0%})"
        details = {
            "ratio": ratio,
            "threshold": threshold,
        }
        all_failures.append(FailureInfo("FAIL_UNTRANSLATED_PROSE", reason, details))

    # Check for markdown fidelity issues
    md_fidelity = checks.get("markdown_fidelity", {})
    if not md_fidelity.get("passed", True):
        errors = md_fidelity.get("errors", [])
        reason = "Bold/italic/heading/list structure mismatch"
        if errors:
            reason = "; ".join(errors[:3])  # Show first 3 errors
        details = {
            "errors": errors,
            "source_counts": md_fidelity.get("source_counts", {}),
            "target_counts": md_fidelity.get("target_counts", {}),
        }
        all_failures.append(FailureInfo("FAIL_MARKDOWN_FIDELITY", reason, details))

    # Check for code preservation
    if not checks.get("code_preservation", {}).get("passed", True):
        reason = "Code blocks or inline code altered"
        all_failures.append(FailureInfo("FAIL_CODE_SPAN_CHANGED", reason))

    # Check for token leakage
    token_leak = checks.get("token_leakage", {})
    if not token_leak.get("passed", True):
        leaks = token_leak.get("leaks", [])
        reason = f"Token leakage detected: {len(leaks)} instances"
        details = {
            "leak_count": len(leaks),
            "leaks": leaks[:5],  # Show first 5
        }
        all_failures.append(FailureInfo("FAIL_CODE_SPAN_CHANGED", reason, details))

    # Check for list concatenation
    if checks.get("list_concatenation", False):
        reason = "List items concatenated"
        all_failures.append(FailureInfo("FAIL_LIST_CONCAT", reason))

    # Check for frontmatter issues
    frontmatter_check = checks.get("frontmatter", {})
    if not frontmatter_check.get("passed", True):
        reason = "Frontmatter invalid or encoding issue"
        details = {
            "source_keys": frontmatter_check.get("source_keys", []),
            "target_keys": frontmatter_check.get("target_keys", []),
        }
        all_failures.append(FailureInfo("FAIL_ENCODING_OR_FRONTMATTER", reason, details))

    # Check for line count issues
    line_count_check = checks.get("line_count", {})
    if not line_count_check.get("passed", True):
        src_lines = line_count_check.get("source", 0)
        tgt_lines = line_count_check.get("target", 0)
        threshold = line_count_check.get("threshold", 0)
        reason = f"Line count too low: target={tgt_lines}, threshold={threshold:.1f} (source={src_lines})"
        details = {
            "source": src_lines,
            "target": tgt_lines,
            "threshold": threshold,
        }
        all_failures.append(FailureInfo("FAIL_LINE_COUNT", reason, details))

    # If no specific failures found but verification failed
    if not all_failures:
        # Check if overall verification passed
        if not verify_data.get("passed", True):
            # Look for error messages
            errors = verify_data.get("errors", [])
            reason = "Verification failed"
            if errors:
                reason = "; ".join(errors[:3])
            details = {"errors": errors}
            all_failures.append(FailureInfo("FAIL_OTHER", reason, details))

    # If still no failures found, this shouldn't happen for failed verifications
    if not all_failures:
        all_failures.append(FailureInfo("FAIL_OTHER", "Verification failed (no specific error detected)"))

    # Sort by severity (highest priority first)
    all_failures.sort(key=lambda f: f.severity)

    # Primary failure is the highest severity one
    primary = all_failures[0]
    return primary.category, primary.reason, all_failures


def classify_failure_legacy(verify_data: Optional[Dict]) -> Tuple[str, str]:
    """
    Legacy classification function (single failure detection).

    This is the old behavior that only returns the first failure found.
    Kept for backward compatibility.

    Args:
        verify_data: Verification result dictionary

    Returns:
        Tuple of (category, reason)
    """
    category, reason, _ = classify_all_failures(verify_data)
    return category, reason


# Backward compatibility alias
classify_failure = classify_failure_legacy


if __name__ == "__main__":
    # Example usage
    sample_verify_data = {
        "passed": False,
        "checks": {
            "markdown_fidelity": {
                "passed": False,
                "errors": ["Bold span count mismatch: source=13, target=14"],
                "source_counts": {"bold": 13, "links": 4},
                "target_counts": {"bold": 14, "links": 5},
            },
            "line_count": {
                "source": 48,
                "target": 30,
                "threshold": 45.6,
                "passed": False,
            },
            "untranslated": {
                "ratio": 0.0,
                "threshold": 0.35,
                "passed": True,
            },
        },
        "errors": [
            "Line count too low: target=30, threshold=45.6 (95% of 48)",
            "Bold span count mismatch: source=13, target=14",
        ],
    }

    category, reason, all_failures = classify_all_failures(sample_verify_data)
    print(f"Primary: {category} - {reason}")
    print(f"\nAll failures ({len(all_failures)}):")
    for f in all_failures:
        print(f"  - {f.category}: {f.reason}")
