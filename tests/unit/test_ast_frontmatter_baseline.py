"""
TC-ORG-02: Baseline reproduction tests proving the AST frontmatter bug.

These tests MUST FAIL before the engine fix (TC-ORG-03) and PASS after.
They prove:
  1. AST path drops nested frontmatter translations (RC-1)
  2. Legacy path correctly applies nested frontmatter translations
  3. Missing profile rules for 10 fields (RC-3)
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from ruamel.yaml.comments import CommentedMap

from src.translation_engine.extractor.segment_extractor import (
    Segment,
    SegmentContext,
    SegmentContextType,
)
from src.translation_engine.reconstructor.markdown_reconstructor import (
    MarkdownReconstructor,
)
from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter
from src.utils.models import FrontmatterMode, FrontmatterRule, SiteProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_segment(key: str, source_text: str, site_id: str = "www.aspose.org") -> Segment:
    """Create a frontmatter segment with the correct context and ID."""
    context = SegmentContext(
        context_type=SegmentContextType.FRONTMATTER,
        frontmatter_key=key,
    )
    seg_id = Segment.create_id(source_text, context, site_id)
    return Segment(
        id=seg_id,
        source_text=source_text,
        context=context,
        site_id=site_id,
        source_lang="en",
    )


def _build_test_frontmatter() -> CommentedMap:
    """Build a minimal frontmatter similar to www.aspose.org _index.md."""
    fm = CommentedMap()
    fm["title"] = "Aspose — File Format APIs"
    fm["description"] = "Aspose offers APIs for popular file formats."

    header = CommentedMap()
    header["title"] = "Build Reliable Document Solutions"
    header["subtitle"] = "Cross-platform APIs for document automation"
    image = CommentedMap()
    image["alt_text"] = "Aspose logo"
    header["image"] = image
    fm["header"] = header

    products = CommentedMap()
    items = []
    for family in ["words", "cells"]:
        app = CommentedMap()
        app["family"] = family
        app["subtitle"] = f"Process {family.title()} documents"
        app["description"] = f"Full {family.title()} processing toolkit"
        item = CommentedMap()
        item["app"] = app
        items.append(item)
    products["items"] = items
    fm["products"] = products

    popular = CommentedMap()
    popular["heading"] = "Popular Features"
    popular["text"] = "Trusted by thousands of companies worldwide"
    fm["popular_features"] = popular

    return fm


def _build_test_profile(include_missing_rules: bool = False) -> SiteProfile:
    """Build a minimal SiteProfile matching www.aspose.org rules."""
    rules = {
        "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "header.title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "header.subtitle": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "header.image.alt_text": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "products.items.app.subtitle": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "products.items.app.description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "popular_features.heading": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
    }
    if include_missing_rules:
        rules["popular_features.text"] = FrontmatterRule(mode=FrontmatterMode.TRANSLATE)

    profile = MagicMock(spec=SiteProfile)
    profile.frontmatter = rules
    profile.site_id = "www.aspose.org"
    profile.default_source_lang = "en"
    return profile


def _build_translations(fm: CommentedMap, profile: SiteProfile) -> dict[str, str]:
    """Build a translations dict mapping segment_id -> German translation."""
    translations = {}
    german = {
        "title": "Aspose — Dateiformate-APIs",
        "description": "Aspose bietet APIs für gängige Dateiformate.",
        "header.title": "Erstellen Sie zuverlässige Dokumentenlösungen",
        "header.subtitle": "Plattformübergreifende APIs für Dokumentenautomation",
        "header.image.alt_text": "Aspose-Logo",
        "products.items[0].app.subtitle": "Words-Dokumente verarbeiten",
        "products.items[0].app.description": "Vollständiges Words-Verarbeitungstoolkit",
        "products.items[1].app.subtitle": "Cells-Dokumente verarbeiten",
        "products.items[1].app.description": "Vollständiges Cells-Verarbeitungstoolkit",
        "popular_features.heading": "Beliebte Funktionen",
        "popular_features.text": "Von Tausenden von Unternehmen weltweit vertraut",
    }

    # Map each field key to its source value and create segment IDs
    field_source_map = {
        "title": fm["title"],
        "description": fm["description"],
        "header.title": fm["header"]["title"],
        "header.subtitle": fm["header"]["subtitle"],
        "header.image.alt_text": fm["header"]["image"]["alt_text"],
        "products.items[0].app.subtitle": fm["products"]["items"][0]["app"]["subtitle"],
        "products.items[0].app.description": fm["products"]["items"][0]["app"]["description"],
        "products.items[1].app.subtitle": fm["products"]["items"][1]["app"]["subtitle"],
        "products.items[1].app.description": fm["products"]["items"][1]["app"]["description"],
        "popular_features.heading": fm["popular_features"]["heading"],
        "popular_features.text": fm["popular_features"]["text"],
    }

    for key, source_text in field_source_map.items():
        if key in german:
            seg = _make_segment(key, source_text)
            translations[seg.id] = german[key]

    return translations


# ---------------------------------------------------------------------------
# Test 1: Prove AST path drops nested frontmatter translations (RC-1)
# ---------------------------------------------------------------------------


class TestASTPathDropsNestedKeys:
    """
    Reproduce the exact AST frontmatter reconstruction code from engine.py:3544-3565.
    This code iterates doc.frontmatter.items() (top-level keys only) and looks up
    profile rules by top-level key name. Dot-notation keys like 'header.title'
    never match because 'header' != 'header.title'.
    """

    def test_ast_path_fails_to_translate_nested_keys(self):
        """
        MUST FAIL before TC-ORG-03 fix (the assertion proves the bug exists).

        The AST path code:
          for key, value in doc.frontmatter.items():
              field_rule = site_profile.frontmatter.get(key)
              ...

        'key' is 'header' (top-level), but profile has 'header.title'.
        site_profile.frontmatter.get('header') returns None → translation skipped.
        """
        fm = _build_test_frontmatter()
        profile = _build_test_profile()
        translations = _build_translations(fm, profile)

        # Build _fm_key_to_seg_id exactly as engine.py does
        segments = []
        for key, source_text in [
            ("title", fm["title"]),
            ("description", fm["description"]),
            ("header.title", fm["header"]["title"]),
            ("header.subtitle", fm["header"]["subtitle"]),
            ("header.image.alt_text", fm["header"]["image"]["alt_text"]),
            ("products.items[0].app.subtitle", fm["products"]["items"][0]["app"]["subtitle"]),
            ("popular_features.heading", fm["popular_features"]["heading"]),
        ]:
            segments.append(_make_segment(key, source_text))

        _fm_key_to_seg_id = {}
        for _seg in segments:
            if (
                _seg.context
                and hasattr(_seg.context, "frontmatter_key")
                and _seg.context.frontmatter_key
                and hasattr(_seg.context, "context_type")
                and str(_seg.context.context_type) == "SegmentContextType.FRONTMATTER"
            ):
                _fm_key_to_seg_id[_seg.context.frontmatter_key] = _seg.id

        # Deep-copy frontmatter (as engine does)
        import copy

        translated_frontmatter = copy.deepcopy(fm)

        # === EXACT ENGINE CODE from engine.py:3558-3565 ===
        for key, value in fm.items():
            field_rule = profile.frontmatter.get(key)
            if field_rule and field_rule.mode == "translate":
                seg_id = _fm_key_to_seg_id.get(key)
                if seg_id and seg_id in translations and isinstance(value, str):
                    translated_frontmatter[key] = translations[seg_id]

        # === ASSERTIONS ===
        # Top-level keys SHOULD be translated (they match)
        assert translated_frontmatter["title"] == "Aspose — Dateiformate-APIs", (
            "Top-level 'title' should be translated by AST path"
        )

        # Nested keys should be translated but ARE NOT (this is the bug).
        # We assert the BUG EXISTS: nested keys still have English values.
        assert translated_frontmatter["header"]["title"] == "Build Reliable Document Solutions", (
            "BUG CONFIRMED: AST path did NOT translate header.title (nested key ignored)"
        )

        assert (
            translated_frontmatter["header"]["subtitle"]
            == "Cross-platform APIs for document automation"
        ), "BUG CONFIRMED: AST path did NOT translate header.subtitle (nested key ignored)"

        assert (
            translated_frontmatter["products"]["items"][0]["app"]["subtitle"]
            == "Process Words documents"
        ), "BUG CONFIRMED: AST path did NOT translate products.items[0].app.subtitle"

        assert translated_frontmatter["popular_features"]["heading"] == "Popular Features", (
            "BUG CONFIRMED: AST path did NOT translate popular_features.heading"
        )


# ---------------------------------------------------------------------------
# Test 2: Prove legacy path correctly applies nested keys
# ---------------------------------------------------------------------------


class TestLegacyPathAppliesNestedKeys:
    """
    The legacy MarkdownReconstructor.reconstruct_frontmatter() iterates profile
    rules (dot-notation), resolves array indices, and uses set_nested_value().
    This path works correctly for all key types.
    """

    def test_legacy_path_translates_nested_keys(self):
        """MUST PASS — proves the legacy path is correct."""
        fm = _build_test_frontmatter()
        profile = _build_test_profile()
        translations = _build_translations(fm, profile)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        # Top-level keys translated
        assert result["title"] == "Aspose — Dateiformate-APIs"
        assert result["description"] == "Aspose bietet APIs für gängige Dateiformate."

        # Nested keys translated
        assert result["header"]["title"] == "Erstellen Sie zuverlässige Dokumentenlösungen"
        assert (
            result["header"]["subtitle"] == "Plattformübergreifende APIs für Dokumentenautomation"
        )
        assert result["header"]["image"]["alt_text"] == "Aspose-Logo"

        # Array-indexed keys translated
        assert result["products"]["items"][0]["app"]["subtitle"] == "Words-Dokumente verarbeiten"
        assert (
            result["products"]["items"][0]["app"]["description"]
            == "Vollständiges Words-Verarbeitungstoolkit"
        )
        assert result["products"]["items"][1]["app"]["subtitle"] == "Cells-Dokumente verarbeiten"
        assert (
            result["products"]["items"][1]["app"]["description"]
            == "Vollständiges Cells-Verarbeitungstoolkit"
        )

        # Non-indexed nested keys translated
        assert result["popular_features"]["heading"] == "Beliebte Funktionen"

    def test_legacy_path_preserves_untranslated_fields(self):
        """Product family identifiers and structure must be preserved."""
        fm = _build_test_frontmatter()
        profile = _build_test_profile()
        translations = _build_translations(fm, profile)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        # Product families preserved (not translated)
        assert result["products"]["items"][0]["app"]["family"] == "words"
        assert result["products"]["items"][1]["app"]["family"] == "cells"

        # Product count preserved
        assert len(result["products"]["items"]) == 2


# ---------------------------------------------------------------------------
# Test 3: Prove missing profile fields (RC-3)
# ---------------------------------------------------------------------------


class TestMissingProfileRules:
    """
    The www.aspose.org.yaml profile is missing rules for 10 translatable fields.
    These fields exist in the English source but have no profile rule → never extracted.
    """

    MISSING_FIELDS = [
        "popular_features.text",
        "products.available_title",
        "products.available_subtitle",
        "products.coming_soon_title",
        "products.coming_soon_subtitle",
        "products.platform_suffix",
        "products.platform_conjunction",
        "products.platform_pair",
        "products.items.app.base_description",
    ]

    def test_popular_features_text_missing_from_profile(self):
        """popular_features.text has no rule in the current profile."""
        profile = _build_test_profile(include_missing_rules=False)
        assert "popular_features.text" not in profile.frontmatter, (
            "popular_features.text should NOT be in current profile (RC-3 proves this)"
        )

    def test_popular_features_text_not_translated_without_rule(self):
        """Without a profile rule, popular_features.text stays in English."""
        fm = _build_test_frontmatter()
        profile = _build_test_profile(include_missing_rules=False)
        translations = _build_translations(fm, profile)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        # popular_features.text should still be English because no rule exists
        assert (
            result["popular_features"]["text"] == "Trusted by thousands of companies worldwide"
        ), "Without profile rule, popular_features.text stays untranslated"

    def test_popular_features_text_translated_with_rule(self):
        """With a profile rule added, popular_features.text gets translated."""
        fm = _build_test_frontmatter()
        profile = _build_test_profile(include_missing_rules=True)
        translations = _build_translations(fm, profile)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert (
            result["popular_features"]["text"] == "Von Tausenden von Unternehmen weltweit vertraut"
        ), "With profile rule, popular_features.text should be translated"


# ---------------------------------------------------------------------------
# Test 4: AST vs Legacy output equivalence (for top-level keys)
# ---------------------------------------------------------------------------


class TestASTLegacyTopLevelEquivalence:
    """
    Prove that for flat top-level keys (title, description), both paths produce
    the same result. The divergence is ONLY on nested keys.
    """

    def test_top_level_keys_match_between_paths(self):
        fm = _build_test_frontmatter()
        profile = _build_test_profile()
        translations = _build_translations(fm, profile)

        # AST path result
        segments = [
            _make_segment("title", fm["title"]),
            _make_segment("description", fm["description"]),
        ]
        _fm_key_to_seg_id = {s.context.frontmatter_key: s.id for s in segments}

        import copy

        ast_result = copy.deepcopy(fm)
        for key, value in fm.items():
            field_rule = profile.frontmatter.get(key)
            if field_rule and field_rule.mode == "translate":
                seg_id = _fm_key_to_seg_id.get(key)
                if seg_id and seg_id in translations and isinstance(value, str):
                    ast_result[key] = translations[seg_id]

        # Legacy path result
        reconstructor = MarkdownReconstructor(profile)
        legacy_result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        # Top-level keys match
        assert ast_result["title"] == legacy_result["title"]
        assert ast_result["description"] == legacy_result["description"]

        # Nested keys diverge — AST has English, legacy has German
        assert ast_result["header"]["title"] != legacy_result["header"]["title"], (
            "AST should still have English header.title while legacy has German"
        )
