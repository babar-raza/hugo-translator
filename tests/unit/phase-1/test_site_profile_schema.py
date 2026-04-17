"""
Unit tests for Site Profile Schema and Pydantic models.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from utils.models import (
    BodyRules,
    SiteProfile,
)


class TestSiteProfile:
    """Test SiteProfile model."""

    def test_minimal_site_profile(self) -> None:
        """Test minimal valid site profile."""
        profile = SiteProfile(
            site_id="test.example.com",
            content_roots=["/content/test"],
            default_source_lang="en",
            target_langs=["es"],
            frontmatter={},
            body=BodyRules(translate_markdown=True),
        )
        assert profile.site_id == "test.example.com"
        assert len(profile.content_roots) == 1
        assert profile.default_source_lang == "en"
        assert profile.target_langs == ["es"]
