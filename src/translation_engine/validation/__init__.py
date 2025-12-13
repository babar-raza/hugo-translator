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

from .base import Validator, ValidationIssue, ValidationResult, ValidationSeverity
from .yaml_validator import YAMLValidator
from .placeholder_validator import PlaceholderValidator
from .structure_validator import (
    StructureValidator,
    YAMLStructureValidator,
    YAMLStructureIssue,
    YAMLStructureValidationResult,
)
from .link_validator import LinkValidator
from .validation_suite import ValidationSuite
from .post_translation_validator import (
    ValidationDecision,
    DecisionResult,
    PostTranslationValidator,
)
from .decision_engine import ValidationDecisionEngine
from .completeness_validator import CompletenessValidator
from .shortcode_preservation_validator import ShortcodePreservationValidator
from .terminology_preservation_validator import TerminologyPreservationValidator
from .language_consistency_validator import LanguageConsistencyValidator
from .file_placement_validator import FilePlacementValidator
from .frontmatter_protection_validator import FrontmatterProtectionValidator

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
