"""Tests for OverrideController."""
from src.tm.override_controller import (
    OverrideConfig,
    OverrideController,
    OverrideFilter,
    OverrideMode,
)


class TestOverrideController:
    """Test OverrideController functionality."""

    def test_normal_mode_never_bypasses(self):
        """Normal mode should never bypass cache."""
        controller = OverrideController()

        assert controller.should_bypass_lookup("Hello world", "de") is False
        assert controller.should_update_cache("Hello world", "de") is True

    def test_bypass_mode_always_bypasses(self):
        """Bypass mode should always skip cache."""
        config = OverrideConfig(mode=OverrideMode.BYPASS)
        controller = OverrideController(config)

        assert controller.should_bypass_lookup("Hello world", "de") is True
        assert controller.should_update_cache("Hello world", "de") is False

    def test_refresh_mode_bypasses_and_updates(self):
        """Refresh mode should bypass and update cache."""
        config = OverrideConfig(mode=OverrideMode.REFRESH)
        controller = OverrideController(config)

        assert controller.should_bypass_lookup("Hello world", "de") is True
        assert controller.should_update_cache("Hello world", "de") is True

    def test_validate_mode_does_not_bypass(self):
        """Validate mode checks cache but also translates."""
        config = OverrideConfig(mode=OverrideMode.VALIDATE)
        controller = OverrideController(config)

        assert controller.should_bypass_lookup("Hello world", "de") is False
        assert controller.should_force_translate("Hello world", "de") is True
        assert controller.should_update_cache("Hello world", "de") is False

    def test_source_pattern_filter(self):
        """Filter by source text pattern."""
        filters = OverrideFilter(
            source_patterns=[r"\[.*\]\(.*\)"]  # Markdown links
        )
        config = OverrideConfig(mode=OverrideMode.REFRESH, filters=filters)
        controller = OverrideController(config)

        # Text with markdown link should match
        assert controller.should_bypass_lookup(
            "Get it from [NuGet](https://nuget.org)", "de"
        ) is True

        # Text without link should not match
        assert controller.should_bypass_lookup(
            "Hello world", "de"
        ) is False

    def test_target_lang_filter(self):
        """Filter by target language."""
        filters = OverrideFilter(target_langs=["ru", "bg"])
        config = OverrideConfig(mode=OverrideMode.REFRESH, filters=filters)
        controller = OverrideController(config)

        assert controller.should_bypass_lookup("Hello", "ru") is True
        assert controller.should_bypass_lookup("Hello", "bg") is True
        assert controller.should_bypass_lookup("Hello", "de") is False

    def test_frontmatter_key_filter(self):
        """Filter by frontmatter key."""
        filters = OverrideFilter(
            frontmatter_keys=["body.block.content_left"]
        )
        config = OverrideConfig(mode=OverrideMode.REFRESH, filters=filters)
        controller = OverrideController(config)

        context_match = {"frontmatter_key": "body.block[0].content_left"}
        context_nomatch = {"frontmatter_key": "title"}

        assert controller.should_bypass_lookup("Hello", "de", context_match) is True
        assert controller.should_bypass_lookup("Hello", "de", context_nomatch) is False

    def test_stats_tracking(self):
        """Statistics should be tracked correctly."""
        config = OverrideConfig(mode=OverrideMode.REFRESH)
        controller = OverrideController(config)

        controller.should_bypass_lookup("Text 1", "de")
        controller.should_bypass_lookup("Text 2", "de")
        controller.should_bypass_lookup("Text 3", "de")

        stats = controller.stats
        assert stats["total_checked"] == 3
        assert stats["refreshed"] == 3

    def test_from_dict(self):
        """Create controller from dictionary config."""
        config_dict = {
            "mode": "refresh",
            "filters": {
                "target_langs": ["ru"],
                "source_patterns": [r"\[.*\]"],
            }
        }

        controller = OverrideController.from_dict(config_dict)

        assert controller.mode == OverrideMode.REFRESH
        assert "ru" in controller.config.filters.target_langs

    def test_invalid_pattern_gracefully_handled(self):
        """Invalid regex patterns should be skipped."""
        filters = OverrideFilter(
            source_patterns=["[invalid(regex"]  # Invalid pattern
        )
        config = OverrideConfig(mode=OverrideMode.REFRESH, filters=filters)
        controller = OverrideController(config)

        # Should not raise, should not match (pattern skipped)
        # No filters effectively compiled = match all
        assert controller.should_bypass_lookup("test", "de") is True

    def test_reset_stats(self):
        """Reset stats should clear counters."""
        config = OverrideConfig(mode=OverrideMode.REFRESH)
        controller = OverrideController(config)

        controller.should_bypass_lookup("Text", "de")
        assert controller.stats["total_checked"] == 1

        controller.reset_stats()
        assert controller.stats["total_checked"] == 0
