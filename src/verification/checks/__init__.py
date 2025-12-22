"""
Verification checks package.

Provides pluggable verification checks for post-translation validation.
"""
from .base import (
    IssueSeverity,
    VerificationCheck,
    VerificationIssue,
    VerificationResult,
)
from .language_check import LanguageDetectionCheck

__all__ = [
    "IssueSeverity",
    "VerificationCheck",
    "VerificationIssue",
    "VerificationResult",
    "LanguageDetectionCheck",
]
