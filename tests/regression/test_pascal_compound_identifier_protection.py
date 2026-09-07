"""TC-APT-103: protect bare PascalCase compound identifiers outside backticks.

Reproduced directly on pdf-annotations-in-cpp: the heading "### Annotation and
AnnotationCollection" has no backticks (a heading, not a code span), so the
existing backtick-only preserve_pattern never reaches it. hi mistranslated
"AnnotationCollection" into a garbled phonetic mash "एनोटेशनकलेक्शन" across TWO
independent retries -- first via the frontmatter summary field, then again at
this exact heading once the summary instance was fixed -- and ar's first
attempt separately translated both class names into generic Arabic nouns.

The new global preserve_pattern (`\\b[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+\\b`)
protects a bare run of 2+ camel-case humps (an API/class/brand identifier in
practice) while deliberately leaving a single capitalized word untouched --
that's ordinary English text a language may legitimately translate
(RB-006's own carve-out).
"""

from src.translation_engine.extractor.placeholder_manager import PlaceholderManager
from src.utils.config_loader import get_global_config


def _protect(text: str) -> tuple[str, dict[str, str]]:
    patterns = get_global_config()["body"]["preserve_patterns"]
    pm = PlaceholderManager()
    return pm.protect(text, patterns)


class TestPascalCompoundIdentifiersAreProtected:
    def test_reproduces_the_exact_failing_heading(self):
        protected, placeholder_map = _protect("Annotation and AnnotationCollection")
        assert protected == "Annotation and {PLACEHOLDER_0}"
        assert placeholder_map == {"{PLACEHOLDER_0}": "AnnotationCollection"}

    def test_multiple_compounds_in_one_sentence(self):
        protected, placeholder_map = _protect(
            "through classes such as TextAnnotation, LinkAnnotation, "
            "HighlightAnnotation, and StampAnnotation"
        )
        for name in (
            "TextAnnotation",
            "LinkAnnotation",
            "HighlightAnnotation",
            "StampAnnotation",
        ):
            assert name not in protected
            assert name in placeholder_map.values()

    def test_three_hump_compound(self):
        protected, placeholder_map = _protect("PageLabelCollection numbers pages")
        assert "PageLabelCollection" not in protected
        assert "PageLabelCollection" in placeholder_map.values()

    def test_subsumes_the_narrower_typescript_fix(self):
        # eca736e added a site-specific \bTypeScript\b pattern after m2m100
        # mistranslated it into Romanian; this general rule covers the same
        # case (and JavaScript/PowerShell/etc.) without a per-term entry.
        protected, placeholder_map = _protect("Aspose.PDF FOSS for TypeScript")
        assert "TypeScript" not in protected
        assert "TypeScript" in placeholder_map.values()


class TestSingleCapitalizedWordsAreNotProtected:
    """A single hump is ordinary English text some languages legitimately
    translate (RB-006's carve-out) -- only true 2+-hump compounds are the
    protect target."""

    def test_bare_class_name_alone_stays_translatable(self):
        protected, placeholder_map = _protect("Annotation and Document")
        assert protected == "Annotation and Document"
        assert placeholder_map == {}

    def test_all_caps_acronyms_stay_translatable(self):
        protected, placeholder_map = _protect("PDF and XMP metadata")
        assert protected == "PDF and XMP metadata"
        assert placeholder_map == {}

    def test_brand_single_word_stays_translatable(self):
        protected, placeholder_map = _protect("Aspose and CMake")
        assert protected == "Aspose and CMake"
        assert placeholder_map == {}


class TestNoFalsePositivesAcrossRealPortfolioHeadings:
    """788 real English headings sampled from the content repo produced
    exactly 65 unique matches, all of them genuine API/library/brand
    identifiers (AcroForm, DocumentBuilder, NuGet, OneNote, PostScript,
    TypeScript, ReportLab, ...), zero false positives on ordinary prose --
    this test locks in a representative slice of that finding."""

    def test_ordinary_prose_headings_untouched(self):
        for heading in (
            "Getting Started",
            "Quick Start",
            "Introduction",
            "Supported Formats",
            "Open Source & Licensing",
            "Related Resources",
        ):
            protected, placeholder_map = _protect(heading)
            assert protected == heading
            assert placeholder_map == {}

    def test_real_api_identifiers_from_other_pages_are_protected(self):
        for heading, identifier in (
            ("AcroForm Field Processing", "AcroForm"),
            ("Building Documents with DocumentBuilder", "DocumentBuilder"),
            ("The Shape and ShapeBase Object Model", "ShapeBase"),
            ("PdfExtractor: Text and Image Extraction", "PdfExtractor"),
        ):
            protected, placeholder_map = _protect(heading)
            assert identifier not in protected
            assert identifier in placeholder_map.values()
