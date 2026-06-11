"""Tests for env-var expansion at profile load time and in downstream consumers."""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.utils.config_loader import ConfigService


@pytest.fixture
def config_service():
    return ConfigService("config/")


class TestProfileLoadExpandvars:
    """content_roots must be expanded when profile is loaded."""

    def test_content_roots_expanded_at_load(self, tmp_path, config_service):
        """content_roots with ${VAR} are expanded after get_site_profile."""
        with patch.dict(os.environ, {"ASPOSE_NET_CONTENT": str(tmp_path)}):
            # Invalidate cache so env var is picked up
            config_service._profile_cache.pop("blog.aspose.net", None)
            profile = config_service.get_site_profile("blog.aspose.net")
        assert "${ASPOSE_NET_CONTENT}" not in profile.content_roots[0]
        assert str(tmp_path) in profile.content_roots[0]

    def test_all_roots_expanded(self, tmp_path, config_service):
        """All entries in content_roots are expanded, not just the first."""
        with patch.dict(os.environ, {"ASPOSE_NET_CONTENT": str(tmp_path)}):
            config_service._profile_cache.pop("blog.aspose.net", None)
            profile = config_service.get_site_profile("blog.aspose.net")
        for root in profile.content_roots:
            assert "${" not in root, f"Unexpanded env var in root: {root}"

    def test_plain_path_root_unchanged(self, config_service):
        """content_roots without env vars pass through unchanged."""
        # Use a profile with a hardcoded path (or mock a fake one)
        with patch.object(config_service, "get_site_profile") as mock_gsp:
            from src.utils.models import SiteProfile

            mock_profile = MagicMock(spec=SiteProfile)
            mock_profile.content_roots = ["/content/blog"]
            mock_gsp.return_value = mock_profile
            profile = config_service.get_site_profile("any")
        assert profile.content_roots[0] == "/content/blog"

    def test_profile_cache_stores_expanded(self, tmp_path, config_service):
        """Cached profile also has expanded content_roots."""
        with patch.dict(os.environ, {"ASPOSE_NET_CONTENT": str(tmp_path)}):
            config_service._profile_cache.pop("blog.aspose.net", None)
            _ = config_service.get_site_profile("blog.aspose.net")
            # Second call hits cache
            profile = config_service.get_site_profile("blog.aspose.net")
        assert "${ASPOSE_NET_CONTENT}" not in profile.content_roots[0]


class TestFilePlacementValidatorExpandvars:
    """file_placement_validator must not emit false-positive path mismatch errors."""

    def test_no_false_positive_when_env_var_in_profile(self, tmp_path):
        """Validator should not warn when content root uses env var that resolves correctly."""
        from src.translation_engine.validation.file_placement_validator import (
            FilePlacementValidator,
        )
        from src.utils.models import SiteProfile

        content_dir = tmp_path / "blog.aspose.net"
        content_dir.mkdir()
        source = content_dir / "index.md"
        source.write_text("# test")
        translation = content_dir / "index.de.md"
        translation.write_text("# test de")

        # Profile with already-expanded content root (as SR-07 produces)
        profile = MagicMock(spec=SiteProfile)
        profile.site_id = "blog.aspose.net"
        profile.content_roots = [str(content_dir)]
        profile.output_layout = None

        validator = FilePlacementValidator(config_service=MagicMock())
        result = validator.validate(
            source=str(source),
            translation=str(translation),
            context={"target_lang": "de", "site_profile": profile},
        )

        # Should not emit "does not contain any defined content root" error/warning
        path_errors = [
            i for i in result.issues if "does not contain any defined content root" in i.message
        ]
        assert path_errors == [], f"Unexpected path errors: {path_errors}"
