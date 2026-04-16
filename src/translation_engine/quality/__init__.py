"""
Translation quality enhancement modules.

Includes glossary-based correction, quality validation, and failure classification.
"""

from .glossary_corrector import GlossaryCorrector, get_glossary_corrector
from .quality_gates import (
    GateResult,
    GateReport,
    GateRunner,
    GateStatus,
    LineCountGate,
    ListStructureGate,
    MarkdownSyntaxGate,
    QualityGate,
    get_default_gates,
)
from .failure_classifier import (
    FailureInfo,
    classify_all_failures,
    classify_failure,
    classify_failure_legacy,
    SEVERITY_RANK,
)

__all__ = [
    "GlossaryCorrector",
    "get_glossary_corrector",
    "GateResult",
    "GateReport",
    "GateRunner",
    "GateStatus",
    "LineCountGate",
    "ListStructureGate",
    "MarkdownSyntaxGate",
    "QualityGate",
    "get_default_gates",
    "FailureInfo",
    "classify_all_failures",
    "classify_failure",
    "classify_failure_legacy",
    "SEVERITY_RANK",
]
