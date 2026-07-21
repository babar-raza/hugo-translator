"""
HT-QUALITY-GATES-001 RC1/RC3 (second, real location): SegmentExtractor must
honor force_protected_fields for title on family/platform index pages.

This is the ACTUAL bug location for the real retranslation defect — found
only after fixing segment_translator.py's AST-path mechanism (RC1/RC3) and
running a real canary retranslation that STILL produced wrong titles (e.g.
"Aspose.PDF FOSS for .NET" -> "FOSS per a .NET", "Aspose.Email FOSS" ->
"Aspose.Email Σκατάληψη"). Traced to: `engine.py`'s `translate_file()` calls
`SegmentExtractor.extract_all()` ONCE per file, before any per-target-
language translation, to build the `segments` list passed into
`SegmentTranslator.translate_to_language()`. This extractor is a completely
separate code path from `TextUnitExtractor` (used only by the AST-body path,
`_translate_body_ast()`) and had ZERO `is_family_platform_index()` awareness
at all — the RC1/RC3 fix to `segment_translator.py` never had any effect on
title, because title was already being extracted as a translatable segment
by SegmentExtractor before `_translate_body_ast` even runs.

Uses the REAL products.aspose.org site profile (via ConfigService, not a
hand-built mock) — its `title: {mode: translate}` config is exactly what
made this defect possible, and is exactly what a mocked site_profile would
have papered over (see test_index_title_passthrough.py's own
TestForceProtectedFieldsOverridesSiteProfile class, which already predicted
titles needed forcing — but never wired that force through to THIS
extractor's real construction call sites in engine.py).
"""
from pathlib import Path

import pytest

from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.translation_engine.parser.hugo_parser import HugoDocument
from src.translation_engine.segment_translator import compute_force_protected_fields
from src.utils.config_loader import ConfigService

_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def products_site_profile():
    config = ConfigService(str(_REPO_ROOT / "config"))
    return config.get_site_profile("products.aspose.org")


def _doc(source_path: Path, title: str = "Aspose.3D FOSS") -> HugoDocument:
    return HugoDocument(frontmatter={"title": title}, ast=[], source_path=source_path)


class TestSegmentExtractorTitleProtection:
    def test_family_root_title_not_extracted_when_protected(self, products_site_profile):
        """The real regression: without force_protected_fields, products.aspose.org's
        real `title: {mode: translate}` config means title WOULD be extracted
        (confirmed by the sibling test below) -- with it wired correctly via
        compute_force_protected_fields(), it must not be."""
        doc = _doc(Path("D:/content/products.aspose.org/en/psd/_index.md"))
        force_protected = compute_force_protected_fields(doc, products_site_profile)
        assert force_protected == {"title"}

        extractor = SegmentExtractor(
            products_site_profile, force_protected_fields=force_protected
        )
        segments = extractor.extract_from_frontmatter(doc.frontmatter, "en")

        title_segments = [s for s in segments if s.context.frontmatter_key == "title"]
        assert title_segments == [], (
            "title must NOT be extracted as a translatable segment on a "
            "family/platform index page — this is the exact real-pipeline "
            "bug that let 'Aspose.PDF FOSS for .NET' become 'FOSS per a "
            ".NET' even after the AST-path fix."
        )

    def test_without_the_fix_title_would_have_been_extracted(self, products_site_profile):
        """Proves the site profile's real config is genuinely translate-mode
        for title (i.e. this isn't a vacuously-passing test) -- confirms
        the defect this fixes was real and reachable, not hypothetical.
        Title text arrives brand/terminology-placeholder-protected (e.g.
        "Aspose.3D" -> "{PLACEHOLDER_0}") -- that's an orthogonal mechanism,
        not this fix, so this assertion only checks a segment was extracted
        at all, not its exact protected text."""
        extractor = SegmentExtractor(products_site_profile)  # no force_protected_fields
        segments = extractor.extract_from_frontmatter({"title": "Aspose.3D FOSS"}, "en")

        title_segments = [s for s in segments if s.context.frontmatter_key == "title"]
        assert len(title_segments) == 1
        assert title_segments[0].source_text.endswith("FOSS")

    def test_leaf_page_title_still_extracted(self, products_site_profile):
        """Leaf pages must keep translating their title -- this fix must not
        become a site-wide passthrough."""
        doc = _doc(
            Path("D:/content/products.aspose.org/en/cells/net/getting-started/installation.md"),
            title="How to Read a Workbook",
        )
        force_protected = compute_force_protected_fields(doc, products_site_profile)
        assert force_protected == set()

        extractor = SegmentExtractor(
            products_site_profile, force_protected_fields=force_protected
        )
        segments = extractor.extract_from_frontmatter(doc.frontmatter, "en")

        title_segments = [s for s in segments if s.context.frontmatter_key == "title"]
        assert len(title_segments) == 1

    def test_platform_subpage_title_not_extracted_when_protected(self, products_site_profile):
        doc = _doc(
            Path("D:/content/products.aspose.org/en/cells/net/_index.md"),
            title="Aspose.Cells FOSS for .NET",
        )
        force_protected = compute_force_protected_fields(doc, products_site_profile)
        extractor = SegmentExtractor(
            products_site_profile, force_protected_fields=force_protected
        )
        segments = extractor.extract_from_frontmatter(doc.frontmatter, "en")

        title_segments = [s for s in segments if s.context.frontmatter_key == "title"]
        assert title_segments == []
