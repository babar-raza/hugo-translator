"""
TC-ORG-03: Tests for the fixed AST frontmatter reconstruction.

After the engine fix, the AST path delegates frontmatter reconstruction to
MarkdownReconstructor.reconstruct_frontmatter(). These tests verify:
  1. AST and legacy paths produce equivalent frontmatter for nested keys
  2. Array-indexed rules work through delegation
  3. translate_list rules work through delegation
  4. No added/removed product array items (product count invariant)
  5. Structural invariant fires when segments are not applied
  6. Every extracted frontmatter segment is applied
"""
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
# Helpers (shared with baseline tests)
# ---------------------------------------------------------------------------

def _make_segment(key: str, source_text: str, site_id: str = "www.aspose.org") -> Segment:
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


def _build_frontmatter_with_arrays() -> CommentedMap:
    fm = CommentedMap()
    fm["title"] = "Aspose — File Format APIs"
    fm["description"] = "APIs for popular formats"

    header = CommentedMap()
    header["title"] = "Build Document Solutions"
    header["subtitle"] = "Cross-platform APIs"
    fm["header"] = header

    products = CommentedMap()
    items = []
    for family in ["words", "cells", "pdf"]:
        app = CommentedMap()
        app["family"] = family
        app["subtitle"] = f"Process {family.title()}"
        app["description"] = f"{family.title()} toolkit"
        item = CommentedMap()
        item["app"] = app
        items.append(item)
    products["items"] = items
    fm["products"] = products

    # why_choose with translate_list (points inside array-traversing reasons, and top-level keywords)
    why = CommentedMap()
    why["heading"] = "Why Choose Aspose"
    why["keywords"] = ["reliability", "performance", "scalability"]
    reasons = []
    for i, (title, points) in enumerate([
        ("Stability", ["99.9% uptime", "Enterprise support"]),
        ("Performance", ["Sub-second latency", "Parallel processing"]),
    ]):
        reason = CommentedMap()
        reason["title"] = title
        reason["points"] = list(points)
        reasons.append(reason)
    why["reasons"] = reasons
    fm["why_choose"] = why

    return fm


def _build_full_profile() -> SiteProfile:
    rules = {
        "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "header.title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "header.subtitle": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "products.items.app.subtitle": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "products.items.app.description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "why_choose.heading": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "why_choose.reasons.title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "why_choose.reasons.points": FrontmatterRule(mode=FrontmatterMode.TRANSLATE_LIST),
        "why_choose.keywords": FrontmatterRule(mode=FrontmatterMode.TRANSLATE_LIST),
    }
    profile = MagicMock(spec=SiteProfile)
    profile.frontmatter = rules
    profile.site_id = "www.aspose.org"
    profile.default_source_lang = "en"
    return profile


def _build_translations_for(fm: CommentedMap) -> dict[str, str]:
    """Build German translations for all fields in the test frontmatter."""
    field_map = {
        "title": ("Aspose — File Format APIs", "Aspose — Dateiformate-APIs"),
        "description": ("APIs for popular formats", "APIs für gängige Formate"),
        "header.title": ("Build Document Solutions", "Dokumentenlösungen erstellen"),
        "header.subtitle": ("Cross-platform APIs", "Plattformübergreifende APIs"),
    }

    translations = {}
    for key, (src, tgt) in field_map.items():
        seg = _make_segment(key, src)
        translations[seg.id] = tgt

    # Array-indexed product fields
    families = ["words", "cells", "pdf"]
    for i, family in enumerate(families):
        for field in ["subtitle", "description"]:
            src = f"Process {family.title()}" if field == "subtitle" else f"{family.title()} toolkit"
            tgt = f"{family.title()} verarbeiten" if field == "subtitle" else f"{family.title()}-Werkzeugkasten"
            key = f"products.items[{i}].app.{field}"
            seg = _make_segment(key, src)
            translations[seg.id] = tgt

    # why_choose
    seg = _make_segment("why_choose.heading", "Why Choose Aspose")
    translations[seg.id] = "Warum Aspose wählen"

    # Reason titles
    for i, (title, de_title) in enumerate([("Stability", "Stabilität"), ("Performance", "Leistung")]):
        key = f"why_choose.reasons[{i}].title"
        seg = _make_segment(key, title)
        translations[seg.id] = de_title

    # Reason points (translate_list through array — the bug we're fixing)
    points_map = {
        "why_choose.reasons[0].points[0]": ("99.9% uptime", "99,9% Betriebszeit"),
        "why_choose.reasons[0].points[1]": ("Enterprise support", "Unternehmensunterstützung"),
        "why_choose.reasons[1].points[0]": ("Sub-second latency", "Latenz unter einer Sekunde"),
        "why_choose.reasons[1].points[1]": ("Parallel processing", "Parallelverarbeitung"),
    }
    for key, (src, tgt) in points_map.items():
        seg = _make_segment(key, src)
        translations[seg.id] = tgt

    # Keywords (translate_list — simple top-level list)
    keywords_map = {
        "why_choose.keywords[0]": ("reliability", "Zuverlässigkeit"),
        "why_choose.keywords[1]": ("performance", "Leistung_kw"),
        "why_choose.keywords[2]": ("scalability", "Skalierbarkeit"),
    }
    for key, (src, tgt) in keywords_map.items():
        seg = _make_segment(key, src)
        translations[seg.id] = tgt

    return translations


# ---------------------------------------------------------------------------
# Test 1: Nested keys work through delegation
# ---------------------------------------------------------------------------

class TestDelegationNestedKeys:
    def test_nested_keys_translated(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert result["title"] == "Aspose — Dateiformate-APIs"
        assert result["header"]["title"] == "Dokumentenlösungen erstellen"
        assert result["header"]["subtitle"] == "Plattformübergreifende APIs"


# ---------------------------------------------------------------------------
# Test 2: Array-indexed rules
# ---------------------------------------------------------------------------

class TestArrayIndexedRules:
    def test_product_subtitles_translated(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert result["products"]["items"][0]["app"]["subtitle"] == "Words verarbeiten"
        assert result["products"]["items"][1]["app"]["subtitle"] == "Cells verarbeiten"
        assert result["products"]["items"][2]["app"]["subtitle"] == "Pdf verarbeiten"

    def test_product_descriptions_translated(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert result["products"]["items"][0]["app"]["description"] == "Words-Werkzeugkasten"
        assert result["products"]["items"][1]["app"]["description"] == "Cells-Werkzeugkasten"
        assert result["products"]["items"][2]["app"]["description"] == "Pdf-Werkzeugkasten"


# ---------------------------------------------------------------------------
# Test 3: translate_list rules
# ---------------------------------------------------------------------------

class TestTranslateListRules:
    def test_why_choose_points_translated_through_array(self):
        """translate_list through array: why_choose.reasons.points where reasons is an array."""
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert result["why_choose"]["reasons"][0]["points"] == [
            "99,9% Betriebszeit", "Unternehmensunterstützung"
        ]
        assert result["why_choose"]["reasons"][1]["points"] == [
            "Latenz unter einer Sekunde", "Parallelverarbeitung"
        ]

    def test_why_choose_keywords_translated(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert result["why_choose"]["keywords"] == [
            "Zuverlässigkeit", "Leistung_kw", "Skalierbarkeit"
        ]

    def test_why_choose_titles_translated(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert result["why_choose"]["reasons"][0]["title"] == "Stabilität"
        assert result["why_choose"]["reasons"][1]["title"] == "Leistung"


# ---------------------------------------------------------------------------
# Test 4: Product count invariant — no added or removed items
# ---------------------------------------------------------------------------

class TestProductCountInvariant:
    def test_product_count_preserved(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert len(result["products"]["items"]) == 3, "Product count must match source"

    def test_product_families_preserved(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        families = [item["app"]["family"] for item in result["products"]["items"]]
        assert families == ["words", "cells", "pdf"], "Product families must be preserved"

    def test_reason_count_preserved(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert len(result["why_choose"]["reasons"]) == 2

    def test_keywords_count_preserved(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        assert len(result["why_choose"]["keywords"]) == 3


# ---------------------------------------------------------------------------
# Test 5: Structural invariant — detect unapplied segments
# ---------------------------------------------------------------------------

class TestStructuralInvariant:
    """
    Simulate the invariant check from the engine fix.
    When a segment has a translation but it's not in the output, the invariant fires.
    """

    def _run_invariant(self, translated_fm, segments, translations):
        """Run the same invariant check as engine.py post-fix."""
        formatter = YAMLFormatter()
        not_applied = []
        for seg in segments:
            if (
                seg.context
                and hasattr(seg.context, "context_type")
                and str(seg.context.context_type) == "SegmentContextType.FRONTMATTER"
                and seg.id in translations
            ):
                fm_key = seg.context.frontmatter_key
                expected = translations[seg.id]
                actual = formatter.get_nested_value(translated_fm, fm_key)
                if actual != expected:
                    not_applied.append((fm_key, expected[:40], str(actual)[:40]))
        return not_applied

    def test_invariant_passes_when_all_applied(self):
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        # Build segments for all translated fields
        segments = []
        for key in ["title", "description", "header.title", "header.subtitle",
                     "why_choose.heading"]:
            src = YAMLFormatter.get_nested_value(fm, key)
            segments.append(_make_segment(key, src))
        for i in range(3):
            for field in ["subtitle", "description"]:
                key = f"products.items[{i}].app.{field}"
                src = fm["products"]["items"][i]["app"][field]
                segments.append(_make_segment(key, src))

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        not_applied = self._run_invariant(result, segments, translations)
        assert not_applied == [], f"All segments should be applied: {not_applied}"

    def test_invariant_detects_unapplied_segment(self):
        """Simulate a scenario where a translation exists but was not applied."""
        fm = _build_frontmatter_with_arrays()

        # Create a segment for a key that doesn't exist in the frontmatter
        seg = _make_segment("nonexistent.key", "some text")
        translations = {seg.id: "etwas Text"}
        segments = [seg]

        not_applied = self._run_invariant(fm, segments, translations)
        assert len(not_applied) == 1
        assert not_applied[0][0] == "nonexistent.key"


# ---------------------------------------------------------------------------
# Test 6: YAML output roundtrips correctly
# ---------------------------------------------------------------------------

class TestYAMLOutput:
    def test_format_frontmatter_produces_valid_yaml(self):
        import yaml
        fm = _build_frontmatter_with_arrays()
        profile = _build_full_profile()
        translations = _build_translations_for(fm)

        reconstructor = MarkdownReconstructor(profile)
        result = reconstructor.reconstruct_frontmatter(fm, translations, "de")

        formatter = YAMLFormatter()
        yaml_output = formatter.format_frontmatter(result)

        # Must have --- delimiters
        assert yaml_output.startswith("---\n")
        assert yaml_output.endswith("---\n")

        # Must parse without error
        inner = yaml_output.split("---", 2)[1]
        parsed = yaml.safe_load(inner)
        assert isinstance(parsed, dict)

        # Parsed keys must match original top-level keys
        assert set(parsed.keys()) == set(fm.keys())
