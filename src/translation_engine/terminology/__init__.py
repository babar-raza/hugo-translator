"""Terminology preservation and validation module.

This module provides data models and functionality for:
- Protecting terminology during translation
- Validating terminology preservation after translation
- Managing term rules and configurations
- Auto-discovering new terminology from source corpus
"""

from .discovery import DiscoveredTerm, TerminologyDiscovery
from .models import (
    DetectedTerm,
    PreserveMode,
    ProtectedSegment,
    TerminologyConfig,
    TermRule,
    TermSeverity,
)
from .terminology_detector import TerminologyDetector
from .terminology_manager import TerminologyManager
from .terminology_protector import TerminologyProtector

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
    "TerminologyDiscovery",
    "DiscoveredTerm",
]
