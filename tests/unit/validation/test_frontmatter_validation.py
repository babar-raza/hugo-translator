"""Tests for frontmatter validation extraction (RC1-FIX).

Verifies that _extract_translatable_frontmatter_text correctly extracts
frontmatter values for validation, and that frontmatter-only files are
no longer invisible to the purity check.
"""
import pytest
from unittest.mock import MagicMock

from src.translation_engine.engine import _extract_translatable_frontmatter_text


# ── _extract_translatable_frontmatter_text ──────────────────────────────


class TestExtractTranslatableFrontmatterText:
    """Tests for the frontmatter text extraction helper."""

    def test_no_frontmatter(self):
        """No frontmatter → empty string."""
        assert _extract_translatable_frontmatter_text("Hello world") == ""

    def test_empty_content(self):
        assert _extract_translatable_frontmatter_text("") == ""

    def test_invalid_yaml(self):
        content = "---\n: invalid: [yaml\n---\nbody"
        assert _extract_translatable_frontmatter_text(content) == ""

    def test_top_level_fallback(self):
        """Without site_profile, extracts known translatable keys."""
        content = "---\ntitle: This is a long title for testing\ndescription: A description that is long enough\nlayout: single\n---\nbody here"
        result = _extract_translatable_frontmatter_text(content)
        assert "This is a long title for testing" in result
        assert "A description that is long enough" in result
        assert "single" not in result  # layout is not translatable

    def test_short_values_excluded(self):
        """Values < 10 chars are excluded (dates, bools, etc.)."""
        content = "---\ntitle: Hi\ndescription: Short\n---\nbody"
        assert _extract_translatable_frontmatter_text(content) == ""

    def test_site_profile_translate_mode(self):
        """With site_profile, uses frontmatter rules."""
        profile = MagicMock()
        rule_translate = MagicMock()
        rule_translate.mode = "translate"
        rule_passthrough = MagicMock()
        rule_passthrough.mode = "passthrough"

        profile.frontmatter = {
            "title": rule_translate,
            "layout": rule_passthrough,
        }

        content = "---\ntitle: A long translatable title value\nlayout: single\n---\nbody"
        result = _extract_translatable_frontmatter_text(content, site_profile=profile)
        assert "A long translatable title value" in result
        assert "single" not in result

    def test_site_profile_translate_list_mode(self):
        """translate_list mode extracts list items."""
        profile = MagicMock()
        rule = MagicMock()
        rule.mode = "translate_list"
        profile.frontmatter = {"keywords": rule}

        content = "---\nkeywords:\n  - This is keyword one\n  - This is keyword two\n---\nbody"
        result = _extract_translatable_frontmatter_text(content, site_profile=profile)
        assert "This is keyword one" in result
        assert "This is keyword two" in result

    def test_nested_dot_path(self):
        """Handles nested dot-path keys like overview.content."""
        profile = MagicMock()
        rule = MagicMock()
        rule.mode = "translate"
        profile.frontmatter = {"overview.content": rule}

        content = "---\noverview:\n  content: This is the overview content text\n---\n"
        result = _extract_translatable_frontmatter_text(content, site_profile=profile)
        assert "This is the overview content text" in result

    def test_dict_rules(self):
        """Handles frontmatter rules as dicts (not objects)."""
        profile = MagicMock()
        profile.frontmatter = {
            "title": {"mode": "translate"},
            "layout": {"mode": "passthrough"},
        }

        content = "---\ntitle: A dictionary-style rule title\nlayout: page\n---\nbody"
        result = _extract_translatable_frontmatter_text(content, site_profile=profile)
        assert "A dictionary-style rule title" in result


# ── Purity check integration with frontmatter ───────────────────────────


class TestPurityCheckFrontmatterIntegration:
    """Verify that _verify_final_file_purity now sees frontmatter content."""

    def _make_engine(self):
        """Create a minimal engine mock for purity testing."""
        engine = MagicMock()
        engine._verify_final_file_purity = (
            __import__('src.translation_engine.engine', fromlist=['TranslationEngine'])
            .TranslationEngine._verify_final_file_purity
        )
        engine._get_purity_threshold = MagicMock(return_value=0.06)
        engine.similarity_tracker = None
        return engine

    def test_frontmatter_only_english_rejected(self):
        """A frontmatter-only file with English content should fail purity for non-English targets."""
        engine = self._make_engine()

        content = "---\ntitle: This is a long English title that should be detected\ndescription: Another English description value for testing\n---\n"

        # Mock detector that detects English
        detector = MagicMock()
        detector.detect.return_value = ("en", 0.95)

        profile = MagicMock()
        rule = MagicMock()
        rule.mode = "translate"
        profile.frontmatter = {"title": rule, "description": rule}

        result = engine._verify_final_file_purity(
            engine, content, "fr", detector, site_profile=profile,
        )
        assert not result["passed"], (
            "Frontmatter-only file with English content should fail purity for target=fr"
        )

    def test_frontmatter_only_no_profile_still_checked(self):
        """Without profile, fallback keys are used for extraction."""
        engine = self._make_engine()

        content = "---\ntitle: This is a long English title value here\ndescription: Another long English description text\n---\n"

        detector = MagicMock()
        detector.detect.return_value = ("en", 0.95)

        # No site_profile → falls back to _FALLBACK_TRANSLATABLE_FM_KEYS
        result = engine._verify_final_file_purity(
            engine, content, "de", detector, site_profile=None,
        )
        assert not result["passed"]

    def test_correctly_translated_frontmatter_passes(self):
        """Frontmatter-only file in correct language should pass."""
        engine = self._make_engine()

        content = "---\ntitle: Ceci est un titre en français assez long\ndescription: Une description française suffisamment longue\n---\n"

        detector = MagicMock()
        detector.detect.return_value = ("fr", 0.92)

        profile = MagicMock()
        rule = MagicMock()
        rule.mode = "translate"
        profile.frontmatter = {"title": rule, "description": rule}

        result = engine._verify_final_file_purity(
            engine, content, "fr", detector, site_profile=profile,
        )
        assert result["passed"]
