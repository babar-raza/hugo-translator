"""
Unit tests for SegmentExtractor terminology integration (TRM-05).

Tests the integration of TerminologyManager with SegmentExtractor:
- Terminology protection during segment extraction
- Terminology restoration after translation
- Metadata preservation
- Backward compatibility when manager is None
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from translation_engine.extractor import (
    SegmentExtractor,
)
from translation_engine.parser import HugoParser
from translation_engine.terminology.models import (
    DetectedTerm,
    PreserveMode,
    ProtectedSegment,
    TermRule,
    TermSeverity,
)
from utils.models import BodyRules, FrontmatterMode, FrontmatterRule, SiteProfile


# Mock TerminologyManager for testing
class MockTerminologyManager:
    """Mock manager that protects specific test terms."""

    def __init__(self, terms_to_protect: list[str] | None = None):
        """Initialize with optional list of terms to protect."""
        self.terms_to_protect = terms_to_protect or ["Aspose", ".NET", "Aspose.Words"]

    def protect(self, text: str, site: str | None = None) -> ProtectedSegment:
        """Mock protect that replaces known terms with placeholders."""
        protected_text = text
        term_mapping = {}
        term_index = 0

        # Sort terms by length (longest first) to handle overlaps
        sorted_terms = sorted(self.terms_to_protect, key=len, reverse=True)

        for term in sorted_terms:
            if term in protected_text:
                # Create mock DetectedTerm
                start_pos = protected_text.find(term)
                detected_term = DetectedTerm(
                    term_text=term,
                    rule=TermRule(
                        term=term,
                        category="test_category",
                        preserve_mode=PreserveMode.BOTH,
                        severity=TermSeverity.WARNING,
                    ),
                    start_pos=start_pos,
                    end_pos=start_pos + len(term),
                )

                # Replace with placeholder
                placeholder = f"{{TERM_{term_index}}}"
                protected_text = protected_text.replace(term, placeholder, 1)
                term_mapping[term_index] = detected_term
                term_index += 1

        return ProtectedSegment(
            original_text=text,
            protected_text=protected_text,
            term_mapping=term_mapping,
        )

    def restore(self, protected_segment: ProtectedSegment) -> str:
        """Mock restore that replaces placeholders with original terms."""
        restored_text = protected_segment.protected_text

        # Restore in reverse order (highest index first) to avoid conflicts
        for term_idx in sorted(protected_segment.term_mapping.keys(), reverse=True):
            detected_term = protected_segment.term_mapping[term_idx]
            placeholder = f"{{TERM_{term_idx}}}"
            restored_text = restored_text.replace(placeholder, detected_term.term_text)

        return restored_text


@pytest.fixture
def simple_profile() -> SiteProfile:
    """Create a simple test profile."""
    return SiteProfile(
        site_id="test-site",
        content_roots=["/content/test"],
        default_source_lang="en",
        target_langs=["es", "fr"],
        frontmatter={
            "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        },
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=["block_code"],
            preserve_patterns=[],
            placeholder_syntax=[r"\{\{<.*?>\}\}", r"\{\{%.*?%\}\}"],
        ),
    )


@pytest.fixture
def mock_terminology_manager() -> MockTerminologyManager:
    """Create a mock terminology manager."""
    return MockTerminologyManager()


class TestSegmentExtractorTerminologyProtection:
    """Test terminology protection during segment extraction."""

    def test_protect_terms_in_frontmatter_segments(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test that terms are protected in frontmatter segments."""
        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)

        frontmatter = {
            "title": "Aspose.Words for .NET Documentation",
            "description": "Learn about Aspose products",
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Find the title segment
        title_seg = next(s for s in segments if "title" in s.context.frontmatter_key)

        # Verify terms were protected
        assert "{TERM_" in title_seg.source_text
        assert "Aspose.Words" not in title_seg.source_text
        assert ".NET" not in title_seg.source_text

        # Verify protected_terms is populated
        assert len(title_seg.protected_terms) > 0

        # Verify metadata is stored
        assert "original_text" in title_seg.protection_metadata
        assert title_seg.protection_metadata["original_text"] == "Aspose.Words for .NET Documentation"
        assert title_seg.protection_metadata["terms_protected"] > 0

    def test_protect_terms_in_body_segments(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test that terms are protected in body segments."""
        parser = HugoParser()
        content = "# Using Aspose\n\nAspose.Words for .NET is a powerful library."
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)
        segments = extractor.extract_from_body(doc.ast, "en")

        # Find segment with Aspose.Words
        aspose_seg = next(s for s in segments if "powerful library" in s.source_text)

        # Verify terms were protected
        assert "{TERM_" in aspose_seg.source_text
        assert "Aspose.Words" not in aspose_seg.source_text

        # Verify protected_terms is populated
        assert len(aspose_seg.protected_terms) > 0

    def test_protection_metadata_preserved(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test that protection metadata is correctly preserved."""
        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)

        frontmatter = {"title": "Aspose.Words Documentation"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        title_seg = segments[0]

        # Verify metadata structure
        assert "original_text" in title_seg.protection_metadata
        assert "terms_protected" in title_seg.protection_metadata
        assert "term_categories" in title_seg.protection_metadata

        # Verify metadata content
        assert title_seg.protection_metadata["terms_protected"] > 0
        assert isinstance(title_seg.protection_metadata["term_categories"], list)

    def test_no_protection_when_manager_none(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test that no protection occurs when manager is None (backward compatible)."""
        # Create extractor without terminology manager
        extractor = SegmentExtractor(simple_profile, terminology_manager=None)

        frontmatter = {"title": "Aspose.Words for .NET Documentation"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        title_seg = segments[0]

        # Verify no protection occurred
        assert "Aspose.Words" in title_seg.source_text
        assert ".NET" in title_seg.source_text
        assert "{TERM_" not in title_seg.source_text

        # Verify protected_terms is empty
        assert len(title_seg.protected_terms) == 0

        # Verify protection_metadata is empty
        assert len(title_seg.protection_metadata) == 0

    def test_no_protection_when_no_terms_detected(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test that segments without protected terms are not modified."""
        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)

        frontmatter = {"title": "Simple Title Without Terms"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        title_seg = segments[0]

        # Verify no protection occurred
        assert title_seg.source_text == "Simple Title Without Terms"
        assert len(title_seg.protected_terms) == 0
        assert len(title_seg.protection_metadata) == 0


class TestSegmentExtractorTerminologyRestoration:
    """Test terminology restoration after translation."""

    def test_restore_terms_in_translated_segment(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test that terms are restored in translated segments."""
        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)

        # Extract with protection
        frontmatter = {"title": "Aspose.Words for .NET Documentation"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")
        title_seg = segments[0]

        # Simulate translation (placeholders remain)
        translated_text = title_seg.source_text.replace("Documentation", "Documentación")

        # Restore terminology
        restored_text = extractor.restore_terminology(translated_text, title_seg)

        # Verify terms were restored
        assert "Aspose.Words" in restored_text
        assert ".NET" in restored_text
        assert "{TERM_" not in restored_text
        assert "Documentación" in restored_text

    def test_restore_preserves_translation(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test that restoration preserves the translated text."""
        parser = HugoParser()
        content = "Aspose.Words is a library"
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)
        segments = extractor.extract_from_body(doc.ast, "en")
        seg = segments[0]

        # Simulate translation
        translated_text = seg.source_text.replace("is a library", "es una biblioteca")

        # Restore terminology
        restored_text = extractor.restore_terminology(translated_text, seg)

        # Verify both restoration and translation
        assert "Aspose.Words" in restored_text
        assert "es una biblioteca" in restored_text

    def test_restore_without_manager_returns_text(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test that restore without manager returns text unchanged."""
        extractor = SegmentExtractor(simple_profile, terminology_manager=None)

        frontmatter = {"title": "Test Title"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")
        seg = segments[0]

        translated_text = "Título de Prueba"
        restored_text = extractor.restore_terminology(translated_text, seg)

        # Should return unchanged
        assert restored_text == translated_text

    def test_restore_without_protected_terms_returns_text(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test that restore without protected terms returns text unchanged."""
        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)

        # Create segment without protected terms
        frontmatter = {"title": "Simple Title"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")
        seg = segments[0]

        translated_text = "Título Simple"
        restored_text = extractor.restore_terminology(translated_text, seg)

        # Should return unchanged
        assert restored_text == translated_text


class TestSegmentExtractorTerminologyEndToEnd:
    """End-to-end tests for terminology protection workflow."""

    def test_full_protection_and_restoration_cycle(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test complete protection and restoration cycle."""
        parser = HugoParser()
        content = """---
title: "Aspose.Words for .NET Guide"
---

# Introduction

Aspose.Words for .NET is a powerful library for document processing.
"""
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)
        segments = extractor.extract_all(doc, source_lang="en")

        # Verify protection occurred
        protected_segments = [s for s in segments if s.protected_terms]
        assert len(protected_segments) > 0

        # Simulate translation and restoration for each segment
        for seg in protected_segments:
            # Simulate translation (replace some text but keep placeholders)
            if "powerful library" in seg.source_text:
                translated = seg.source_text.replace("powerful library", "biblioteca poderosa")
            elif "Guide" in seg.source_text:
                translated = seg.source_text.replace("Guide", "Guía")
            else:
                translated = seg.source_text

            # Restore terminology
            restored = extractor.restore_terminology(translated, seg)

            # Verify restoration
            if "biblioteca poderosa" in translated:
                assert "Aspose.Words" in restored
                assert ".NET" in restored
                assert "biblioteca poderosa" in restored
            elif "Guía" in translated:
                assert "Aspose.Words" in restored or "Aspose" in restored
                assert "Guía" in restored

    def test_multiple_terms_in_single_segment(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test handling of multiple terms in a single segment."""
        manager = MockTerminologyManager(["Aspose", ".NET", "Python", "Java"])
        extractor = SegmentExtractor(simple_profile, manager)

        frontmatter = {"title": "Aspose for .NET, Python, and Java"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")
        seg = segments[0]

        # Verify multiple terms protected
        assert seg.protection_metadata.get("terms_protected", 0) > 1

        # Simulate translation
        translated = seg.source_text.replace("and", "y")

        # Restore
        restored = extractor.restore_terminology(translated, seg)

        # Verify all terms restored
        assert "Aspose" in restored
        assert ".NET" in restored
        assert "Python" in restored
        assert "Java" in restored
        assert "y" in restored

    def test_backward_compatibility_with_existing_code(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test that existing code without terminology manager still works."""
        # This simulates existing code that doesn't use terminology manager
        extractor = SegmentExtractor(simple_profile)

        parser = HugoParser()
        content = """---
title: "Test Document"
---

# Test

This is a test paragraph.
"""
        doc = parser.parse_string(content)

        # Should work without errors
        segments = extractor.extract_all(doc)

        # Verify normal extraction occurred
        assert len(segments) > 0

        # Verify no protection occurred
        for seg in segments:
            assert len(seg.protected_terms) == 0
            assert len(seg.protection_metadata) == 0


class TestSegmentExtractorTerminologyEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_text_protection(
        self, simple_profile: SiteProfile, mock_terminology_manager: MockTerminologyManager
    ) -> None:
        """Test protecting empty text."""
        extractor = SegmentExtractor(simple_profile, mock_terminology_manager)

        frontmatter = {"title": ""}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Should not create segments for empty strings
        assert len(segments) == 0

    def test_protection_with_special_characters(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test protection with special characters in terms."""
        # Create manager with terms containing special regex characters
        manager = MockTerminologyManager(["C++", ".NET", "F#"])
        extractor = SegmentExtractor(simple_profile, manager)

        frontmatter = {"title": "Programming with C++, .NET, and F#"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")
        seg = segments[0]

        # Verify protection occurred
        assert len(seg.protected_terms) > 0

        # Restore and verify
        restored = extractor.restore_terminology(seg.source_text, seg)
        assert "C++" in restored
        assert ".NET" in restored
        assert "F#" in restored

    def test_overlapping_terms(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test handling of overlapping terms."""
        # Create manager with overlapping terms
        manager = MockTerminologyManager(["Aspose", "Aspose.Words", "Words"])
        extractor = SegmentExtractor(simple_profile, manager)

        frontmatter = {"title": "Aspose.Words Documentation"}
        segments = extractor.extract_from_frontmatter(frontmatter, "en")
        seg = segments[0]

        # Should protect longest match first
        assert len(seg.protected_terms) > 0

        # Restore
        restored = extractor.restore_terminology(seg.source_text, seg)

        # Should restore correctly (longest match takes precedence)
        assert "Aspose.Words" in restored or ("Aspose" in restored and "Words" in restored)
