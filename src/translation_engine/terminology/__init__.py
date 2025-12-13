"""Terminology preservation and validation module.

This module provides data models and functionality for:
- Protecting terminology during translation
- Validating terminology preservation after translation
- Managing term rules and configurations
"""

from .models import (
    PreserveMode,
    TermSeverity,
    TermRule,
    DetectedTerm,
    ProtectedSegment,
    TerminologyConfig,
)
from .terminology_detector import TerminologyDetector
from .terminology_protector import TerminologyProtector
from .terminology_manager import TerminologyManager

__all__ = [
    "PreserveMode",
    "TermSeverity",
    "TermRule",
    "DetectedTerm",
    "ProtectedSegment",
    "TerminologyConfig",
    "TerminologyDetector",
    "TerminologyProtector",
    "TerminologyManager",
]
