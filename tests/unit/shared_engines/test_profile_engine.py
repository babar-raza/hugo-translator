"""
Unit tests for ProfileEngine.

Tests profile and configuration wrapper with mocked ConfigService.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from src.shared_engines.profile_engine import ProfileEngine
from src.utils.models import GlobalConfig, SiteProfile, TerminologyConfig, ValidationConfig


class TestProfileEngine(unittest.TestCase):
    """Test ProfileEngine wrapper."""

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_initialization_default_config_root(self, mock_config_service):
        """Test ProfileEngine initializes with default config root."""
        mock_service_instance = Mock()
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()

        # Config root should default to config/ directory
        self.assertIsNotNone(engine.config_root)
        self.assertTrue(str(engine.config_root).endswith("config"))
        mock_config_service.assert_called_once()

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_initialization_custom_config_root(self, mock_config_service):
        """Test ProfileEngine initializes with custom config root."""
        mock_service_instance = Mock()
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine(config_root="/custom/config")

        self.assertEqual(engine.config_root, Path("/custom/config"))
        mock_config_service.assert_called_once_with(config_root=Path("/custom/config"))

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_profile(self, mock_config_service):
        """Test get_profile() retrieves site profile."""
        mock_service_instance = Mock()
        mock_profile = Mock(spec=SiteProfile)
        mock_profile.default_model = "m2m100_418m"
        mock_profile.target_langs = ["es", "fr", "de"]
        mock_service_instance.get_site_profile.return_value = mock_profile
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        profile = engine.get_profile("products.aspose.com")

        self.assertEqual(profile, mock_profile)
        self.assertEqual(profile.default_model, "m2m100_418m")
        mock_service_instance.get_site_profile.assert_called_once_with(
            site_id="products.aspose.com",
            use_cache=True
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_profile_no_cache(self, mock_config_service):
        """Test get_profile() with cache disabled."""
        mock_service_instance = Mock()
        mock_profile = Mock(spec=SiteProfile)
        mock_service_instance.get_site_profile.return_value = mock_profile
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        profile = engine.get_profile("docs.aspose.net", use_cache=False)

        mock_service_instance.get_site_profile.assert_called_once_with(
            site_id="docs.aspose.net",
            use_cache=False
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_list_sites(self, mock_config_service):
        """Test list_sites() returns all configured sites."""
        mock_service_instance = Mock()
        mock_service_instance.list_sites.return_value = [
            "products.aspose.com",
            "docs.aspose.net",
            "blog.aspose.net"
        ]
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        sites = engine.list_sites()

        self.assertEqual(len(sites), 3)
        self.assertIn("products.aspose.com", sites)
        self.assertIn("docs.aspose.net", sites)
        mock_service_instance.list_sites.assert_called_once()

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_resolve_config_validation(self, mock_config_service):
        """Test resolve_config() for validation configuration."""
        mock_service_instance = Mock()
        mock_profile = Mock(spec=SiteProfile)
        mock_service_instance.get_site_profile.return_value = mock_profile

        mock_validation_config = {
            "enabled": True,
            "mode": "strict",
            "validators": {"terminology": {"enabled": True}}
        }
        mock_service_instance.get_merged_validation_config.return_value = mock_validation_config
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.resolve_config(
            site_id="products.aspose.com",
            config_type="validation"
        )

        self.assertEqual(config["enabled"], True)
        self.assertEqual(config["mode"], "strict")
        mock_service_instance.get_merged_validation_config.assert_called_once_with(
            mock_profile
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_resolve_config_terminology(self, mock_config_service):
        """Test resolve_config() for terminology configuration."""
        mock_service_instance = Mock()
        mock_profile = Mock(spec=SiteProfile)
        mock_service_instance.get_site_profile.return_value = mock_profile

        mock_terminology_config = {
            "enabled": True,
            "preserve_mode": "BOTH",
            "global_terms": {"exact_matches": [], "patterns": []}
        }
        mock_service_instance.get_merged_terminology_config.return_value = mock_terminology_config
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.resolve_config(
            site_id="docs.aspose.net",
            config_type="terminology"
        )

        self.assertEqual(config["preserve_mode"], "BOTH")
        mock_service_instance.get_merged_terminology_config.assert_called_once_with(
            mock_profile
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_resolve_config_metrics(self, mock_config_service):
        """Test resolve_config() for metrics configuration."""
        mock_service_instance = Mock()
        mock_profile = Mock(spec=SiteProfile)
        mock_service_instance.get_site_profile.return_value = mock_profile

        mock_metrics_config = {
            "metrics": {
                "storage": {"translation_engine": {"retry_metrics_maxlen": 1000}},
                "statistics": {"percentiles": [0.50, 0.95, 0.99]}
            }
        }
        mock_service_instance.get_metrics_config.return_value = mock_metrics_config
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.resolve_config(
            site_id="products.aspose.com",
            config_type="metrics"
        )

        self.assertIn("metrics", config)
        mock_service_instance.get_metrics_config.assert_called_once_with(use_cache=True)

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_resolve_config_global(self, mock_config_service):
        """Test resolve_config() for global configuration."""
        mock_service_instance = Mock()
        mock_profile = Mock(spec=SiteProfile)
        mock_service_instance.get_site_profile.return_value = mock_profile

        mock_global_config = {
            "content_hash_tracking": {"hash_algorithm": "md5"}
        }
        mock_service_instance.get_config.return_value = mock_global_config
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.resolve_config(
            site_id="products.aspose.com",
            config_type="global"
        )

        self.assertIn("content_hash_tracking", config)
        mock_service_instance.get_config.assert_called_once()

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_resolve_config_invalid_type(self, mock_config_service):
        """Test resolve_config() raises error for invalid config type."""
        mock_service_instance = Mock()
        mock_profile = Mock(spec=SiteProfile)
        mock_service_instance.get_site_profile.return_value = mock_profile
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()

        with self.assertRaises(ValueError) as ctx:
            engine.resolve_config(
                site_id="products.aspose.com",
                config_type="invalid_type"
            )

        self.assertIn("Invalid config_type", str(ctx.exception))
        self.assertIn("invalid_type", str(ctx.exception))

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_global_config(self, mock_config_service):
        """Test get_global_config() returns GlobalConfig."""
        mock_service_instance = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_service_instance.global_config = mock_global_config
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.get_global_config()

        self.assertEqual(config, mock_global_config)

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_raw_config(self, mock_config_service):
        """Test get_raw_config() returns raw config dictionary."""
        mock_service_instance = Mock()
        mock_raw_config = {"content_hash_tracking": {"hash_algorithm": "md5"}}
        mock_service_instance.get_config.return_value = mock_raw_config
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.get_raw_config()

        self.assertEqual(config, mock_raw_config)
        mock_service_instance.get_config.assert_called_once()

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_reload_profile(self, mock_config_service):
        """Test reload_profile() bypasses cache."""
        mock_service_instance = Mock()
        mock_profile = Mock(spec=SiteProfile)
        mock_service_instance.reload_profile.return_value = mock_profile
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        profile = engine.reload_profile("products.aspose.com")

        self.assertEqual(profile, mock_profile)
        mock_service_instance.reload_profile.assert_called_once_with(
            "products.aspose.com"
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_clear_cache(self, mock_config_service):
        """Test clear_cache() clears profile cache."""
        mock_service_instance = Mock()
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        engine.clear_cache()

        mock_service_instance.clear_cache.assert_called_once()

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_validate_all_profiles_success(self, mock_config_service):
        """Test validate_all_profiles() with no errors."""
        mock_service_instance = Mock()
        mock_service_instance.validate_all_profiles.return_value = {}
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        errors = engine.validate_all_profiles()

        self.assertEqual(errors, {})
        mock_service_instance.validate_all_profiles.assert_called_once()

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_validate_all_profiles_with_errors(self, mock_config_service):
        """Test validate_all_profiles() with validation errors."""
        mock_service_instance = Mock()
        mock_errors = {
            "invalid-site": ["Missing required field: default_model"],
            "broken-site": ["Invalid YAML syntax"]
        }
        mock_service_instance.validate_all_profiles.return_value = mock_errors
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        errors = engine.validate_all_profiles()

        self.assertEqual(len(errors), 2)
        self.assertIn("invalid-site", errors)
        self.assertIn("broken-site", errors)

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_validation_config(self, mock_config_service):
        """Test get_validation_config() returns ValidationConfig."""
        mock_service_instance = Mock()
        mock_validation = Mock(spec=ValidationConfig)
        mock_service_instance.get_validation_config.return_value = mock_validation
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.get_validation_config()

        self.assertEqual(config, mock_validation)
        mock_service_instance.get_validation_config.assert_called_once_with(
            use_cache=True
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_terminology_config(self, mock_config_service):
        """Test get_terminology_config() returns TerminologyConfig."""
        mock_service_instance = Mock()
        mock_terminology = Mock(spec=TerminologyConfig)
        mock_service_instance.get_terminology_config.return_value = mock_terminology
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.get_terminology_config()

        self.assertEqual(config, mock_terminology)
        mock_service_instance.get_terminology_config.assert_called_once_with(
            use_cache=True
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_metrics_config(self, mock_config_service):
        """Test get_metrics_config() returns metrics dict."""
        mock_service_instance = Mock()
        mock_metrics = {
            "metrics": {
                "storage": {"translation_engine": {"retry_metrics_maxlen": 1000}}
            }
        }
        mock_service_instance.get_metrics_config.return_value = mock_metrics
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.get_metrics_config()

        self.assertEqual(config, mock_metrics)
        mock_service_instance.get_metrics_config.assert_called_once_with(
            use_cache=True
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_metrics_config_no_cache(self, mock_config_service):
        """Test get_metrics_config() with cache disabled."""
        mock_service_instance = Mock()
        mock_metrics = {"metrics": {}}
        mock_service_instance.get_metrics_config.return_value = mock_metrics
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine()
        config = engine.get_metrics_config(use_cache=False)

        mock_service_instance.get_metrics_config.assert_called_once_with(
            use_cache=False
        )

    @patch('src.shared_engines.profile_engine.ConfigService')
    def test_get_config_root(self, mock_config_service):
        """Test get_config_root() returns config root path."""
        mock_service_instance = Mock()
        mock_config_service.return_value = mock_service_instance

        engine = ProfileEngine(config_root="/test/config")
        config_root = engine.get_config_root()

        self.assertEqual(config_root, Path("/test/config"))


if __name__ == "__main__":
    unittest.main()
