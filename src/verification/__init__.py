"""
Verification package for post-translation quality checks.

Provides the VerificationAgent and pluggable verification checks
to detect quality issues in translated content.

Usage:
    from src.verification import VerificationAgent, VerificationResult
    from src.verification.checks import LanguageDetectionCheck

    agent = VerificationAgent([
        LanguageDetectionCheck(),
    ])

    result = agent.verify(source_doc, translated_doc, "de")
    if not result.passed:
        print(f"Found {result.error_count} errors")
"""
from .agent import VerificationAgent
from .checks.base import (
    IssueSeverity,
    VerificationCheck,
    VerificationIssue,
    VerificationResult,
)
from .report import VerificationReporter, write_report

__all__ = [
    "VerificationAgent",
    "VerificationCheck",
    "VerificationIssue",
    "VerificationResult",
    "IssueSeverity",
    "VerificationReporter",
    "write_report",
]
