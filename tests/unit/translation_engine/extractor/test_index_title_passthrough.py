"""Regression test: family/platform _index.md titles must stay pinned to EN.

docs.aspose.org, kb.aspose.org, and products.aspose.org set `title: {mode:
translate}` site-wide, which is correct for leaf content pages (e.g.
"Installation" -> "Pemasangan") but wrong for family/platform index pages
(e.g. slides/cpp/_index.md's "Aspose.Slides FOSS for C++"), which must stay
byte-identical to English across every locale -- confirmed live via
docs.aspose.org/ms/slides/cpp/_index.md and kb.aspose.org equivalents.

is_family_platform_index() + TextUnitExtractor(force_protected_fields=...)
let the extractor override the site profile's per-field mode for just this
page shape, without a site-wide passthrough that would break leaf-page title
translation.
"""
from types import SimpleNamespace

from src.translation_engine.extractor.text_unit_extractor import (
    TextUnitExtractor,
    is_family_platform_index,
)


class TestIsFamilyPlatformIndex:
    def test_platform_index_is_detected(self):
        assert is_family_platform_index(
            "D:/content/docs.aspose.org/en/slides/cpp/_index.md"
        ) is True

    def test_family_only_index_is_not_platform_index(self):
        assert is_family_platform_index(
            "D:/content/docs.aspose.org/en/slides/_index.md"
        ) is False

    def test_leaf_page_is_not_platform_index(self):
        assert is_family_platform_index(
            "D:/content/docs.aspose.org/en/slides/cpp/getting-started/installation.md"
        ) is False

    def test_nested_index_is_not_platform_index(self):
        assert is_family_platform_index(
            "D:/content/docs.aspose.org/en/slides/cpp/getting-started/_index.md"
        ) is False

    def test_missing_source_lang_segment_returns_false(self):
        assert is_family_platform_index(
            "D:/content/docs.aspose.org/slides/cpp/_index.md"
        ) is False

    def test_none_path_returns_false(self):
        assert is_family_platform_index(None) is False

    def test_respects_custom_source_lang(self):
        assert is_family_platform_index(
            "D:/content/docs.aspose.org/de/slides/cpp/_index.md", source_lang="de"
        ) is True

    def test_family_only_index_matches_with_include_family_root(self):
        """HT-QUALITY-GATES-001: opt-in broadening for products.aspose.org,
        where family-root pages (e.g. psd/_index.md, a root-only family with
        no platform sub-pages) have the same byte-identical-title
        requirement as platform pages. Default (False) behavior is
        unchanged -- see test_family_only_index_is_not_platform_index above."""
        assert is_family_platform_index(
            "D:/content/products.aspose.org/en/psd/_index.md",
            include_family_root=True,
        ) is True

    def test_leaf_page_not_matched_even_with_include_family_root(self):
        assert is_family_platform_index(
            "D:/content/products.aspose.org/en/psd/getting-started/installation.md",
            include_family_root=True,
        ) is False

    def test_nested_index_not_matched_even_with_include_family_root(self):
        assert is_family_platform_index(
            "D:/content/products.aspose.org/en/cells/net/getting-started/_index.md",
            include_family_root=True,
        ) is False


class TestForceProtectedFieldsOverridesSiteProfile:
    def _translate_mode_site_profile(self):
        return SimpleNamespace(frontmatter={"title": {"mode": "translate"}})

    def test_title_is_skipped_when_forced_protected(self):
        extractor = TextUnitExtractor(
            site_profile=self._translate_mode_site_profile(),
            force_protected_fields={"title"},
        )
        units = extractor._extract_frontmatter_units(
            {"title": "Aspose.Slides FOSS for C++"}
        )
        assert units == []

    def test_title_still_translatable_without_force(self):
        """Regression guard: leaf-page titles on the same site must keep
        extracting normally when the platform-index override doesn't apply."""
        extractor = TextUnitExtractor(
            site_profile=self._translate_mode_site_profile(),
        )
        units = extractor._extract_frontmatter_units(
            {"title": "Aspose.Slides FOSS for C++"}
        )
        assert len(units) == 1
        assert units[0].metadata["field_name"] == "title"
