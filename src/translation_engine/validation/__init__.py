"""
Translation validation subsystem.

This module provides validators for ensuring translation quality and integrity:
- YAML syntax validation
- Placeholder integrity checks
- Markdown structure preservation
- Link validity checks
- Post-translation validation framework
- Validation decision engine
- Language consistency validation
- Frontmatter protection validation
"""

from .base import ValidationIssue, ValidationResult, ValidationSeverity, Validator
from .completeness_validator import CompletenessValidator
from .decision_engine import ValidationDecisionEngine
from .file_placement_validator import FilePlacementValidator
from .frontmatter_protection_validator import FrontmatterProtectionValidator
from .language_consistency_validator import LanguageConsistencyValidator
from .link_validator import LinkValidator
from .placeholder_validator import PlaceholderValidator
from .post_translation_validator import (
    DecisionResult,
    PostTranslationValidator,
    ValidationDecision,
)
from .shortcode_preservation_validator import ShortcodePreservationValidator
from .structure_validator import (
    StructureValidator,
    YAMLStructureIssue,
    YAMLStructureValidationResult,
    YAMLStructureValidator,
)
from .terminology_preservation_validator import TerminologyPreservationValidator
from .validation_suite import ValidationSuite
from .yaml_validator import YAMLValidator

__all__ = [
    "Validator",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "YAMLValidator",
    "PlaceholderValidator",
    "StructureValidator",
    "YAMLStructureValidator",
    "YAMLStructureIssue",
    "YAMLStructureValidationResult",
    "LinkValidator",
    "ValidationSuite",
    "ValidationDecision",
    "DecisionResult",
    "PostTranslationValidator",
    "ValidationDecisionEngine",
    "CompletenessValidator",
    "ShortcodePreservationValidator",
    "TerminologyPreservationValidator",
    "LanguageConsistencyValidator",
    "FilePlacementValidator",
    "FrontmatterProtectionValidator",
]
