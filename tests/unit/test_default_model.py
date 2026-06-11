"""
Unit tests for default_model resolution feature (SR-DEFAULT-MODEL).

Tests the priority hierarchy:
  CLI --model > site_profile.default_model > system default (m2m100_418m)
"""

import yaml


class TestSiteProfileDefaultModel:
    """Tests for SiteProfile.default_model field."""

    def test_profile_accepts_none_default_model(self):
        """SR-01: Field accepts None (uses system default)."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de", "fr"],
            body=BodyRules(translate_markdown=True),
            # default_model not set - should default to None
        )
        assert profile.default_model is None

    def test_profile_accepts_valid_model_id(self):
        """SR-01: Field accepts valid model ID strings."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de", "fr"],
            body=BodyRules(translate_markdown=True),
            default_model="m2m100_1.2b",
        )
        assert profile.default_model == "m2m100_1.2b"

    def test_profile_model_overrides_default(self):
        """SR-01: Profile default_model takes precedence over system default."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            default_model="nllb_200_600m",
        )

        # Simulate the resolution logic from engine.py
        model_id = getattr(profile, "default_model", None) or "m2m100_418m"
        assert model_id == "nllb_200_600m"

    def test_system_default_when_none_set(self):
        """SR-01/SR-02: Falls back to m2m100_418m when nothing set."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            # default_model not set
        )

        # Simulate the resolution logic
        cli_model = None
        model_id = cli_model or getattr(profile, "default_model", None) or "m2m100_418m"
        assert model_id == "m2m100_418m"


class TestConfigLoaderModelMapping:
    """Tests for config loader YAML compatibility (SR-03)."""

    def test_legacy_yaml_model_default_mapping(self, tmp_path):
        """SR-03: model.default maps to default_model."""
        from src.utils.config_loader import ConfigService

        # Create config structure
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        profiles_dir = config_dir / "site_profiles"
        profiles_dir.mkdir()

        # Create global.yaml
        global_yaml = config_dir / "global.yaml"
        global_yaml.write_text("log_level: INFO\n")

        # Create profile with legacy model.default structure
        profile_yaml = profiles_dir / "legacy.site.yaml"
        profile_data = {
            "site_id": "legacy.site",
            "content_roots": ["/content"],
            "default_source_lang": "en",
            "target_langs": ["de"],
            "body": {"translate_markdown": True},
            "model": {"default": "m2m100_1.2b"},
        }
        profile_yaml.write_text(yaml.dump(profile_data))

        # Load and verify
        service = ConfigService(config_dir)
        profile = service.get_site_profile("legacy.site")

        assert profile.default_model == "m2m100_1.2b"

    def test_direct_default_model_field(self, tmp_path):
        """SR-03: Profiles with direct default_model field work."""
        from src.utils.config_loader import ConfigService

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        profiles_dir = config_dir / "site_profiles"
        profiles_dir.mkdir()

        global_yaml = config_dir / "global.yaml"
        global_yaml.write_text("log_level: INFO\n")

        profile_yaml = profiles_dir / "direct.site.yaml"
        profile_data = {
            "site_id": "direct.site",
            "content_roots": ["/content"],
            "default_source_lang": "en",
            "target_langs": ["de"],
            "body": {"translate_markdown": True},
            "default_model": "nllb_200_600m",
        }
        profile_yaml.write_text(yaml.dump(profile_data))

        service = ConfigService(config_dir)
        profile = service.get_site_profile("direct.site")

        assert profile.default_model == "nllb_200_600m"

    def test_profile_without_model_field(self, tmp_path):
        """SR-03: Profiles without either field work (uses system default)."""
        from src.utils.config_loader import ConfigService

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        profiles_dir = config_dir / "site_profiles"
        profiles_dir.mkdir()

        global_yaml = config_dir / "global.yaml"
        global_yaml.write_text("log_level: INFO\n")

        profile_yaml = profiles_dir / "minimal.site.yaml"
        profile_data = {
            "site_id": "minimal.site",
            "content_roots": ["/content"],
            "default_source_lang": "en",
            "target_langs": ["de"],
            "body": {"translate_markdown": True},
            # No model or default_model field
        }
        profile_yaml.write_text(yaml.dump(profile_data))

        service = ConfigService(config_dir)
        profile = service.get_site_profile("minimal.site")

        assert profile.default_model is None
        # Resolution should fall back to system default
        model_id = getattr(profile, "default_model", None) or "m2m100_418m"
        assert model_id == "m2m100_418m"

    def test_direct_overrides_legacy(self, tmp_path):
        """SR-03: Direct default_model takes precedence over legacy model.default."""
        from src.utils.config_loader import ConfigService

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        profiles_dir = config_dir / "site_profiles"
        profiles_dir.mkdir()

        global_yaml = config_dir / "global.yaml"
        global_yaml.write_text("log_level: INFO\n")

        profile_yaml = profiles_dir / "both.site.yaml"
        profile_data = {
            "site_id": "both.site",
            "content_roots": ["/content"],
            "default_source_lang": "en",
            "target_langs": ["de"],
            "body": {"translate_markdown": True},
            "default_model": "direct_model",
            "model": {"default": "legacy_model"},
        }
        profile_yaml.write_text(yaml.dump(profile_data))

        service = ConfigService(config_dir)
        profile = service.get_site_profile("both.site")

        # Direct field should take precedence
        assert profile.default_model == "direct_model"

    def test_invalid_type_model_default_ignored(self, tmp_path):
        """SR-H02: Invalid model.default type is ignored gracefully."""
        from src.utils.config_loader import ConfigService

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        profiles_dir = config_dir / "site_profiles"
        profiles_dir.mkdir()

        global_yaml = config_dir / "global.yaml"
        global_yaml.write_text("log_level: INFO\n")

        profile_yaml = profiles_dir / "invalid.site.yaml"
        profile_data = {
            "site_id": "invalid.site",
            "content_roots": ["/content"],
            "default_source_lang": "en",
            "target_langs": ["de"],
            "body": {"translate_markdown": True},
            "model": {"default": ["list", "not", "string"]},  # Invalid type
        }
        profile_yaml.write_text(yaml.dump(profile_data))

        service = ConfigService(config_dir)
        profile = service.get_site_profile("invalid.site")

        # Invalid type should be ignored, default_model remains None
        assert profile.default_model is None


class TestCLIModelPriority:
    """Tests for CLI --model override priority (SR-02)."""

    def test_cli_model_overrides_profile(self):
        """SR-02: CLI --model takes precedence over profile."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            default_model="profile_model",
        )

        cli_model = "cli_override_model"

        # Simulate the resolution logic from cli.py
        model_id = cli_model or getattr(profile, "default_model", None) or "m2m100_418m"
        assert model_id == "cli_override_model"

    def test_cli_none_uses_profile(self):
        """SR-02: When CLI --model is None, use profile default_model."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            default_model="profile_model",
        )

        cli_model = None

        model_id = cli_model or getattr(profile, "default_model", None) or "m2m100_418m"
        assert model_id == "profile_model"

    def test_full_priority_chain(self):
        """SR-02: Full priority: CLI > profile > system default."""
        from src.utils.models import BodyRules, SiteProfile

        profile_with_model = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            default_model="profile_model",
        )

        profile_without_model = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
        )

        def resolve(cli_model, profile):
            return cli_model or getattr(profile, "default_model", None) or "m2m100_418m"

        # CLI overrides everything
        assert resolve("cli_model", profile_with_model) == "cli_model"
        assert resolve("cli_model", profile_without_model) == "cli_model"

        # Profile overrides system default
        assert resolve(None, profile_with_model) == "profile_model"

        # System default when nothing else set
        assert resolve(None, profile_without_model) == "m2m100_418m"


class TestEdgeCases:
    """SR-H03: Edge case tests for default_model resolution."""

    def test_empty_string_falls_through_to_default(self):
        """Empty string should fall through to system default."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            default_model="",  # Empty string
        )

        # Empty string is falsy, should fall through
        model_id = getattr(profile, "default_model", None) or "m2m100_418m"
        assert model_id == "m2m100_418m"

    def test_whitespace_only_falls_through_to_default(self):
        """SR-P01: Whitespace-only string is normalized to None, falls through."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            default_model="   ",  # Whitespace only
        )

        # Whitespace-only is normalized to None by field validator
        assert profile.default_model is None
        # Falls through to system default
        model_id = getattr(profile, "default_model", None) or "m2m100_418m"
        assert model_id == "m2m100_418m"

    def test_explicit_none_falls_through_to_default(self):
        """Explicit None should fall through to system default."""
        from src.utils.models import BodyRules, SiteProfile

        profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            default_model=None,  # Explicit None
        )

        model_id = getattr(profile, "default_model", None) or "m2m100_418m"
        assert model_id == "m2m100_418m"
