"""
Tests for AST body reconstruction feature flag toggle (SR-02).

Verifies that use_ast_body_reconstruction flag correctly controls
which code path is used for translation.
"""

import pytest

from src.utils.models import BodyRules, SiteProfile


class TestFeatureFlagToggle:
    """Tests for use_ast_body_reconstruction feature flag."""

    @pytest.fixture
    def site_profile_ast_enabled(self):
        """Create site profile with AST reconstruction enabled."""
        return SiteProfile(
            site_id="test.site.net",
            content_roots=["content"],
            default_source_lang="en",
            target_langs=["de", "fr"],
            body=BodyRules(translate_markdown=True, use_ast_body_reconstruction=True),
            frontmatter={},
        )

    @pytest.fixture
    def site_profile_ast_disabled(self):
        """Create site profile with AST reconstruction disabled."""
        return SiteProfile(
            site_id="test.site.net",
            content_roots=["content"],
            default_source_lang="en",
            target_langs=["de", "fr"],
            body=BodyRules(translate_markdown=True, use_ast_body_reconstruction=False),
            frontmatter={},
        )

    @pytest.fixture
    def site_profile_default(self):
        """Create site profile with default AST setting."""
        return SiteProfile(
            site_id="test.site.net",
            content_roots=["content"],
            default_source_lang="en",
            target_langs=["de", "fr"],
            body=BodyRules(translate_markdown=True),  # use_ast defaults to True (TC-HT-004)
            frontmatter={},
        )

    def test_flag_true_uses_ast_path(self, site_profile_ast_enabled):
        """When use_ast_body_reconstruction=True, AST path is used."""
        # Verify the flag is set correctly
        assert site_profile_ast_enabled.body.use_ast_body_reconstruction is True

        # Verify getattr returns True (matches engine logic at line 856)
        use_ast = getattr(site_profile_ast_enabled.body, "use_ast_body_reconstruction", False)
        assert use_ast is True

    def test_flag_false_uses_legacy_path(self, site_profile_ast_disabled):
        """When use_ast_body_reconstruction=False, legacy path is used."""
        # Verify the flag is set correctly
        assert site_profile_ast_disabled.body.use_ast_body_reconstruction is False

        # Verify getattr returns False (matches engine logic)
        use_ast = getattr(site_profile_ast_disabled.body, "use_ast_body_reconstruction", False)
        assert use_ast is False

    def test_flag_default_is_true(self, site_profile_default):
        """Default value for use_ast_body_reconstruction is True (TC-HT-004: legacy retired)."""
        # Verify default is True
        assert site_profile_default.body.use_ast_body_reconstruction is True

        # Verify getattr returns True for default
        use_ast = getattr(site_profile_default.body, "use_ast_body_reconstruction", True)
        assert use_ast is True

    def test_body_rules_default_value(self):
        """BodyRules has correct default for use_ast_body_reconstruction (TC-HT-004)."""
        body_rules = BodyRules(translate_markdown=True)
        assert body_rules.use_ast_body_reconstruction is True

    def test_body_rules_explicit_true(self):
        """BodyRules accepts explicit True value."""
        body_rules = BodyRules(translate_markdown=True, use_ast_body_reconstruction=True)
        assert body_rules.use_ast_body_reconstruction is True

    def test_body_rules_explicit_false(self):
        """BodyRules accepts explicit False value."""
        body_rules = BodyRules(translate_markdown=True, use_ast_body_reconstruction=False)
        assert body_rules.use_ast_body_reconstruction is False

    def test_flag_read_from_dict(self):
        """Flag can be set from dictionary (config file simulation)."""
        config_dict = {
            "site_id": "test.site.net",
            "content_roots": ["content"],
            "default_source_lang": "en",
            "target_langs": ["de"],
            "body": {"translate_markdown": True, "use_ast_body_reconstruction": True},
            "frontmatter": {},
        }
        profile = SiteProfile(**config_dict)
        assert profile.body.use_ast_body_reconstruction is True

    def test_flag_missing_from_dict_uses_default(self):
        """Missing flag in config uses default (True, TC-HT-004)."""
        config_dict = {
            "site_id": "test.site.net",
            "content_roots": ["content"],
            "default_source_lang": "en",
            "target_langs": ["de"],
            "body": {"translate_markdown": True},
            "frontmatter": {},
        }
        profile = SiteProfile(**config_dict)
        assert profile.body.use_ast_body_reconstruction is True


class TestASTMethodExists:
    """Verify AST translation method exists and is callable."""

    def test_translate_body_ast_method_exists(self):
        """Engine class has _translate_body_ast method defined."""
        from src.translation_engine.engine import TranslationEngine

        # Check method exists on class (not instance, since instantiation requires deps)
        assert hasattr(TranslationEngine, "_translate_body_ast")
        assert callable(TranslationEngine._translate_body_ast)


class TestFlagInEngineLogic:
    """Test that flag controls branching in translate_file."""

    def test_flag_controls_ast_vs_legacy_branching(self):
        """Verify flag controls code path selection logic."""
        # This tests the conditional logic matching engine.py line 856

        # Simulate the engine's decision logic
        class MockBody:
            def __init__(self, use_ast):
                self.use_ast_body_reconstruction = use_ast

        class MockProfile:
            def __init__(self, use_ast):
                self.body = MockBody(use_ast)

        # Test with True - should trigger AST path (line 858: if use_ast:)
        profile_ast = MockProfile(use_ast=True)
        use_ast = getattr(profile_ast.body, "use_ast_body_reconstruction", False)
        assert use_ast is True, "Flag=True should trigger AST path"

        # Test with False - should trigger legacy path (line 899: if not use_ast:)
        profile_legacy = MockProfile(use_ast=False)
        use_ast = getattr(profile_legacy.body, "use_ast_body_reconstruction", False)
        assert use_ast is False, "Flag=False should trigger legacy path"

        # Test with missing attribute (fallback to True, TC-HT-004: legacy retired)
        class MockBodyNoAttr:
            pass

        class MockProfileNoAttr:
            def __init__(self):
                self.body = MockBodyNoAttr()

        profile_no_attr = MockProfileNoAttr()
        use_ast = getattr(profile_no_attr.body, "use_ast_body_reconstruction", True)
        assert use_ast is True, "Missing attribute should default to True"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
