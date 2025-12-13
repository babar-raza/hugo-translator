"""Terminology protection via placeholder replacement.

This module provides the TerminologyProtector class which:
- Replaces detected terminology with placeholders before translation
- Restores original terms from placeholders after translation
- Handles nested and adjacent terms correctly
"""

from typing import List
from src.translation_engine.terminology.models import DetectedTerm, ProtectedSegment


class TerminologyProtector:
    """Protects terminology by replacing with placeholders.

    This class handles the protection and restoration of terminology in text:
    1. Protection: Replaces detected terms with {TERM_N} placeholders
    2. Restoration: Replaces placeholders back with original terms

    The placeholder format is {TERM_N} where N is a sequential integer.

    Example:
        protector = TerminologyProtector()
        protected = protector.protect("Aspose.Words for .NET", detected_terms)
        # Returns ProtectedSegment with protected_text="{TERM_0} for {TERM_1}"
        restored = protector.restore(protected)
        # Returns "Aspose.Words for .NET"
    """

    def __init__(self):
        """Initialize the terminology protector."""
        pass

    def protect(self, text: str, detected_terms: List[DetectedTerm]) -> ProtectedSegment:
        """Replace detected terms with placeholders.

        Args:
            text: Original text containing terminology
            detected_terms: List of detected terms to protect (must be sorted by position)

        Returns:
            ProtectedSegment with placeholders and term mapping
        """
        if not detected_terms:
            return ProtectedSegment(
                original_text=text,
                protected_text=text,
                term_mapping={}
            )

        # Sort terms by position (reverse order to replace from end to start)
        # This prevents position shifts when replacing
        sorted_terms = sorted(detected_terms, key=lambda t: t.start_pos, reverse=True)

        protected_text = text
        term_mapping = {}

        # Replace from end to start to maintain position accuracy
        for idx, term in enumerate(sorted_terms):
            # Create placeholder
            placeholder = f"{{TERM_{len(sorted_terms) - 1 - idx}}}"

            # Replace term with placeholder
            protected_text = (
                protected_text[:term.start_pos] +
                placeholder +
                protected_text[term.end_pos:]
            )

            # Store mapping (use forward index for mapping)
            term_mapping[len(sorted_terms) - 1 - idx] = term

        return ProtectedSegment(
            original_text=text,
            protected_text=protected_text,
            term_mapping=term_mapping
        )

    def restore(self, protected_segment: ProtectedSegment) -> str:
        """Restore original terms from placeholders.

        Args:
            protected_segment: Protected segment with placeholders and term mapping

        Returns:
            Text with placeholders replaced by original terms
        """
        restored_text = protected_segment.protected_text

        # Replace placeholders with original terms
        # Sort by term ID in reverse order to handle nested placeholders correctly
        for term_id in sorted(protected_segment.term_mapping.keys(), reverse=True):
            term = protected_segment.term_mapping[term_id]
            placeholder = f"{{TERM_{term_id}}}"
            restored_text = restored_text.replace(placeholder, term.term_text)

        return restored_text
