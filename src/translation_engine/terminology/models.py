"""Terminology data models for terminology protection system.

This module defines the core data models for terminology detection and protection:
- TermRule: Configuration for a terminology rule (exact match or pattern)
- DetectedTerm: A detected occurrence of terminology in text
- ProtectedSegment: Text with terminology replaced by placeholders
- PreserveMode: How to handle terminology preservation
- TermSeverity: Severity level for terminology violations
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PreserveMode(str, Enum):
    """How to preserve terminology.

    PROTECT: Replace with placeholder before translation
    VALIDATE: Check preservation after translation
    BOTH: Both protect and validate
    NONE: No preservation
    """
    PROTECT = "protect"
    VALIDATE = "validate"
    BOTH = "both"
    NONE = "none"


class TermSeverity(str, Enum):
    """Severity of terminology violation.

    ERROR: Critical violation, reject translation
    WARNING: Non-critical issue, accept with warning
    INFO: Informational only
    """
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class TermRule:
    """Rule for protecting/validating terminology.

    Attributes:
        term: Exact term to match (if exact matching)
        pattern: Regex pattern to match (if pattern matching)
        category: Term category (company_name, platform, product_family, etc.)
        preserve_mode: How to preserve (protect, validate, both, none)
        severity: Violation severity (error, warning, info)
        case_sensitive: Whether matching is case-sensitive
        description: Human-readable description
    """
    category: str
    preserve_mode: PreserveMode
    severity: TermSeverity
    term: str | None = None
    pattern: str | None = None
    case_sensitive: bool = True
    description: str | None = None

    def __post_init__(self):
        """Validate that either term or pattern is specified."""
        if not self.term and not self.pattern:
            raise ValueError("Either 'term' or 'pattern' must be specified")
        if self.term and self.pattern:
            raise ValueError("Cannot specify both 'term' and 'pattern'")


@dataclass
class DetectedTerm:
    """A detected terminology occurrence in text.

    Attributes:
        term_text: The actual text matched
        rule: The rule that matched this term
        start_pos: Start position in source text
        end_pos: End position in source text
        confidence: Detection confidence (0.0-1.0)
    """
    term_text: str
    rule: TermRule
    start_pos: int
    end_pos: int
    confidence: float = 1.0


@dataclass
class ProtectedSegment:
    """A text segment with terminology protected.

    Attributes:
        original_text: Original text before protection
        protected_text: Text with terms replaced by placeholders
        term_mapping: Mapping of placeholder IDs to detected terms
                      e.g., {0: DetectedTerm("Aspose", ...), 1: DetectedTerm(".NET", ...)}
    """
    original_text: str
    protected_text: str
    term_mapping: dict[int, DetectedTerm] = field(default_factory=dict)


@dataclass
class TerminologyConfig:
    """Complete terminology configuration.

    Attributes:
        version: Config version
        global_rules: Global term rules (apply to all sites)
        site_overrides: Site-specific rule overrides
        auto_discovery: Auto-discovery settings
    """
    version: str
    global_rules: list[TermRule] = field(default_factory=list)
    site_overrides: dict[str, list[TermRule]] = field(default_factory=dict)
    auto_discovery: dict[str, Any] = field(default_factory=dict)
