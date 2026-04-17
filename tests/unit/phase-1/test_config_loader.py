"""
Unit tests for ConfigService - Configuration loading and validation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from utils.config_loader import ConfigLoadError, ConfigService
from utils.models import GlobalConfig, SiteProfile


class TestConfigService:
    """Test ConfigService initialization and basic functionality."""

    def test_init_with_valid_config_dir(self, temp_config_dir: Path) -> None:
        """Test initializing ConfigService with valid config directory."""
        service = ConfigService(temp_config_dir)
        assert service.config_root == temp_config_dir
        assert service.site_profiles_dir == temp_config_dir / "site_profiles"

    def test_init_with_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test that initializing with nonexistent directory raises error."""
        with pytest.raises(ConfigLoadError, match="does not exist"):
            ConfigService(tmp_path / "nonexistent")

    def test_global_config_defaults(self, temp_config_dir: Path) -> None:
        """Test that global config uses defaults when file missing."""
        service = ConfigService(temp_config_dir)
        assert isinstance(service.global_config, GlobalConfig)
        assert service.global_config.model_cache_dir == "./data/models"


class TestSiteProfileLoading:
    """Test loading site profiles."""

    def test_list_sites_empty(self, temp_config_dir: Path) -> None:
        """Test listing sites when none exist."""
        service = ConfigService(temp_config_dir)
        sites = service.list_sites()
        assert sites == []

    def test_list_sites_with_profiles(self, test_data_dir: Path) -> None:
        """Test listing sites when profiles exist."""
        service = ConfigService(test_data_dir / "config")
        sites = service.list_sites()
        assert isinstance(sites, list)
        assert "test.example.com" in sites

    def test_load_valid_profile(self, test_data_dir: Path) -> None:
        """Test loading a valid site profile."""
        service = ConfigService(test_data_dir / "config")
        profile = service.get_site_profile("test.example.com")

        assert isinstance(profile, SiteProfile)
        assert profile.site_id == "test.example.com"
        assert profile.default_source_lang == "en"
        assert "es" in profile.target_langs

    def test_load_nonexistent_profile(self, temp_config_dir: Path) -> None:
        """Test loading nonexistent profile raises error."""
        service = ConfigService(temp_config_dir)
        with pytest.raises(ConfigLoadError, match="not found"):
            service.get_site_profile("nonexistent.site")

    def test_profile_caching(self, test_data_dir: Path) -> None:
        """Test that profiles are cached after first load."""
        service = ConfigService(test_data_dir / "config")

        # Load twice
        profile1 = service.get_site_profile("test.example.com")
        profile2 = service.get_site_profile("test.example.com")

        # Should be same instance (cached)
        assert profile1 is profile2

    def test_reload_profile_bypasses_cache(self, test_data_dir: Path) -> None:
        """Test that reload_profile bypasses cache."""
        service = ConfigService(test_data_dir / "config")

        profile1 = service.get_site_profile("test.example.com")
        profile2 = service.reload_profile("test.example.com")

        # Should be different instances
        assert profile1 is not profile2
        # But same content
        assert profile1.site_id == profile2.site_id


class TestEnvironmentOverrides:
    """Test environment variable overrides."""

    def test_source_lang_override(
        self, test_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test overriding source language via environment variable."""
        monkeypatch.setenv("SITE_TEST_EXAMPLE_COM_DEFAULT_SOURCE_LANG", "de")

        service = ConfigService(test_data_dir / "config")
        profile = service.get_site_profile("test.example.com", use_cache=False)

        assert profile.default_source_lang == "de"

    def test_target_langs_override(
        self, test_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test overriding target languages via environment variable."""
        monkeypatch.setenv("SITE_TEST_EXAMPLE_COM_TARGET_LANGS", "ja,ko,zh")

        service = ConfigService(test_data_dir / "config")
        profile = service.get_site_profile("test.example.com", use_cache=False)

        assert profile.target_langs == ["ja", "ko", "zh"]


class TestValidation:
    """Test profile validation."""

    def test_validate_all_profiles_success(self, test_data_dir: Path) -> None:
        """Test validating all profiles when all are valid."""
        service = ConfigService(test_data_dir / "config")
        errors = service.validate_all_profiles()

        assert errors == {}

    def test_clear_cache(self, test_data_dir: Path) -> None:
        """Test clearing the profile cache."""
        service = ConfigService(test_data_dir / "config")

        # Load profile (caches it)
        service.get_site_profile("test.example.com")
        assert len(service._profile_cache) > 0

        # Clear cache
        service.clear_cache()
        assert len(service._profile_cache) == 0
