"""HT-INLINE-CODE-001 TC-ICR-002: shared global preserve_patterns baseline.

Proves the merge mechanism SegmentExtractor.__init__ now uses --
config/global.yaml's body.preserve_patterns unioned with each site
profile's own list -- resolves correctly in all three shapes: global-only,
site-only, and both combined. This is the fix for the drift class where a
protection pattern gets added to one site profile and silently forgotten on
the other four (see TC-ICR-003's kb.aspose.org / reference.aspose.org case).
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.translation_engine.extractor import segment_extractor as se_module
from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.utils.models import BodyRules

_THROWAWAY_GLOBAL_PATTERN = r"__THROWAWAY_GLOBAL_TEST_PATTERN__"
_THROWAWAY_SITE_PATTERN = r"__THROWAWAY_SITE_TEST_PATTERN__"
_INLINE_CODE_BACKTICK_PATTERN = r"`[^`\n]+`"
_CONFIG_ROOT = Path(__file__).resolve().parents[4] / "config"


def _make_site_profile(preserve_patterns=None):
    profile = MagicMock()
    profile.site_id = "test.example.com"
    profile.body = BodyRules(translate_markdown=True)
    profile.body.preserve_patterns = preserve_patterns or []
    profile.body.preserve_blocks = []
    profile.body.placeholder_syntax = None
    return profile


class TestGlobalPreservePatternsBaseline:
    def test_global_only_pattern_is_honored_by_a_site_with_no_patterns_of_its_own(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            se_module,
            "_get_global_body_preserve_patterns",
            lambda: [_THROWAWAY_GLOBAL_PATTERN],
        )
        profile = _make_site_profile(preserve_patterns=[])
        extractor = SegmentExtractor(profile)
        assert _THROWAWAY_GLOBAL_PATTERN in extractor.preserve_patterns

    def test_site_only_pattern_still_applies_on_top_of_an_empty_global_baseline(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            se_module, "_get_global_body_preserve_patterns", lambda: []
        )
        profile = _make_site_profile(preserve_patterns=[_THROWAWAY_SITE_PATTERN])
        extractor = SegmentExtractor(profile)
        assert _THROWAWAY_SITE_PATTERN in extractor.preserve_patterns

    def test_global_and_site_patterns_both_present_simultaneously(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            se_module,
            "_get_global_body_preserve_patterns",
            lambda: [_THROWAWAY_GLOBAL_PATTERN],
        )
        profile = _make_site_profile(preserve_patterns=[_THROWAWAY_SITE_PATTERN])
        extractor = SegmentExtractor(profile)
        assert _THROWAWAY_GLOBAL_PATTERN in extractor.preserve_patterns
        assert _THROWAWAY_SITE_PATTERN in extractor.preserve_patterns

    def test_real_config_global_yaml_resolves_without_error(self) -> None:
        """No monkeypatch -- proves _get_global_body_preserve_patterns()
        actually loads the real config/global.yaml body.preserve_patterns
        key (added by TC-ICR-002/003) without raising, and returns a list."""
        patterns = se_module._get_global_body_preserve_patterns()
        assert isinstance(patterns, list)


class TestInlineCodePatternResolvesOnAllFiveSites:
    """TC-ICR-003 acceptance criterion: all 5 site profiles resolve the
    inline-code preserve pattern via the shared baseline, not a per-site
    copy. Regression guard against the exact drift found in the working
    tree (staged on kb.aspose.org.yaml only, missing on the other 4)."""

    @pytest.mark.parametrize(
        "site_id",
        [
            "reference.aspose.org",
            "docs.aspose.org",
            "kb.aspose.org",
            "products.aspose.org",
            "blog.aspose.org",
        ],
    )
    def test_site_resolves_inline_code_preserve_pattern(self, site_id) -> None:
        from src.utils.config_loader import ConfigService

        config = ConfigService(config_root=_CONFIG_ROOT)
        profile = config.get_site_profile(site_id)
        extractor = SegmentExtractor(profile)
        assert _INLINE_CODE_BACKTICK_PATTERN in extractor.preserve_patterns, (
            f"{site_id} did not resolve the shared inline-code preserve "
            f"pattern -- got: {extractor.preserve_patterns}"
        )

    def test_kb_no_longer_carries_a_duplicated_per_site_copy(self) -> None:
        """The retired per-site pattern (no newline exclusion) must be gone
        from kb.aspose.org.yaml's own list -- only the shared, tightened
        baseline copy should be in effect."""
        from src.utils.config_loader import ConfigService

        config = ConfigService(config_root=_CONFIG_ROOT)
        profile = config.get_site_profile("kb.aspose.org")
        assert r"`[^`]+`" not in (profile.body.preserve_patterns or [])
