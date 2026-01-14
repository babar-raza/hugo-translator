"""
ProfileEngine - Unified site profile and configuration resolution.

Wraps existing ConfigService to provide consistent interface for accessing
site profiles, global config, validation/terminology config across execution modes.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from src.utils.config_loader import ConfigService
from src.utils.models import SiteProfile, GlobalConfig, ValidationConfig, TerminologyConfig

logger = logging.getLogger(__name__)


class ProfileEngine:
    """
    Unified profile and configuration engine.

    Wraps ConfigService to provide consistent interface for:
    - Site profile resolution
    - Global configuration access
    - Validation/terminology config merging
    - Configuration caching

    Args:
        config_root: Path to configuration root directory (default: "config/")

    Example:
        # Initialize engine
        profile_engine = ProfileEngine(config_root="config/")

        # Get site profile
        profile = profile_engine.get_profile("products.aspose.com")
        print(f"Target languages: {profile.target_langs}")

        # List all sites
        sites = profile_engine.list_sites()
        print(f"Configured sites: {', '.join(sites)}")

        # Get merged validation config for site
        validation_config = profile_engine.resolve_config(
            site_id="products.aspose.com",
            config_type="validation"
        )
    """

    def __init__(self, config_root: Optional[str | Path] = None):
        """Initialize profile engine."""
        # Default to config/ directory
        if config_root is None:
            config_root = Path(__file__).parent.parent.parent / "config"

        self.config_root = Path(config_root)

        # Initialize underlying ConfigService
        self.config_service = ConfigService(config_root=self.config_root)

        logger.info(f"ProfileEngine initialized: config_root={self.config_root}")

    def get_profile(self, site_id: str, use_cache: bool = True) -> SiteProfile:
        """
        Get site profile by ID.

        Args:
            site_id: Site identifier (e.g., "products.aspose.com")
            use_cache: Use cached profile if available (default: True)

        Returns:
            SiteProfile instance

        Raises:
            ConfigLoadError: If profile not found or invalid

        Example:
            profile = engine.get_profile("products.aspose.com")
            print(f"Default model: {profile.default_model}")
            print(f"Target languages: {profile.target_langs}")
        """
        profile = self.config_service.get_site_profile(
            site_id=site_id,
            use_cache=use_cache
        )
        # Safe logging (attributes may not exist in mocked profiles)
        model = getattr(profile, 'default_model', 'unknown')
        num_langs = len(getattr(profile, 'target_langs', []))
        logger.debug(
            f"Retrieved profile for {site_id}: "
            f"model={model}, langs={num_langs}"
        )
        return profile

    def list_sites(self) -> List[str]:
        """
        List all configured site IDs.

        Returns:
            List of site identifiers (sorted)

        Example:
            sites = engine.list_sites()
            for site_id in sites:
                print(f"Site: {site_id}")
        """
        sites = self.config_service.list_sites()
        logger.debug(f"Listed {len(sites)} configured sites")
        return sites

    def resolve_config(
        self,
        site_id: str,
        config_type: str,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Resolve merged configuration for a site.

        Merges global configuration with site-specific overrides.

        Args:
            site_id: Site identifier
            config_type: Configuration type ("validation", "terminology", "metrics", "global")
            use_cache: Use cached config if available (default: True)

        Returns:
            Merged configuration dictionary

        Raises:
            ValueError: If config_type is invalid
            ConfigLoadError: If configuration cannot be loaded

        Example:
            # Get merged validation config for site
            validation = engine.resolve_config(
                site_id="products.aspose.com",
                config_type="validation"
            )
            print(f"Validation enabled: {validation['enabled']}")
            print(f"Validators: {list(validation['validators'].keys())}")

            # Get merged terminology config for site
            terminology = engine.resolve_config(
                site_id="docs.aspose.net",
                config_type="terminology"
            )
            print(f"Preserve mode: {terminology['preserve_mode']}")
        """
        # Get site profile
        profile = self.get_profile(site_id, use_cache=use_cache)

        # Resolve configuration based on type
        if config_type == "validation":
            config = self.config_service.get_merged_validation_config(profile)
            logger.debug(f"Resolved validation config for {site_id}")
        elif config_type == "terminology":
            config = self.config_service.get_merged_terminology_config(profile)
            logger.debug(f"Resolved terminology config for {site_id}")
        elif config_type == "metrics":
            config = self.config_service.get_metrics_config(use_cache=use_cache)
            logger.debug("Resolved metrics config (global)")
        elif config_type == "global":
            config = self.config_service.get_config()
            logger.debug("Resolved global config")
        else:
            raise ValueError(
                f"Invalid config_type: {config_type}. "
                f"Use 'validation', 'terminology', 'metrics', or 'global'."
            )

        return config

    def get_global_config(self) -> GlobalConfig:
        """
        Get global configuration.

        Returns:
            GlobalConfig instance

        Example:
            global_config = engine.get_global_config()
            print(f"Auto-commit: {global_config.git.auto_commit_enabled}")
        """
        config = self.config_service.global_config
        logger.debug("Retrieved global config")
        return config

    def get_raw_config(self) -> Dict[str, Any]:
        """
        Get raw global configuration dictionary.

        Returns:
            Raw configuration dictionary

        Example:
            raw_config = engine.get_raw_config()
            hash_algo = raw_config.get("content_hash_tracking", {}).get("hash_algorithm")
        """
        config = self.config_service.get_config()
        logger.debug("Retrieved raw global config")
        return config

    def reload_profile(self, site_id: str) -> SiteProfile:
        """
        Reload site profile from disk (bypass cache).

        Args:
            site_id: Site identifier

        Returns:
            Freshly loaded SiteProfile instance

        Example:
            # Reload profile after config file change
            profile = engine.reload_profile("products.aspose.com")
        """
        profile = self.config_service.reload_profile(site_id)
        logger.debug(f"Reloaded profile for {site_id}")
        return profile

    def clear_cache(self) -> None:
        """
        Clear all cached profiles and configs.

        Useful when configuration files have been modified.

        Example:
            # Clear cache after bulk config updates
            engine.clear_cache()
        """
        self.config_service.clear_cache()
        logger.debug("Cleared profile cache")

    def validate_all_profiles(self) -> Dict[str, List[str]]:
        """
        Validate all site profiles.

        Returns:
            Dictionary mapping site IDs to error messages (empty dict if all valid)

        Example:
            errors = engine.validate_all_profiles()
            if errors:
                for site_id, error_list in errors.items():
                    print(f"Site {site_id} has errors:")
                    for error in error_list:
                        print(f"  - {error}")
            else:
                print("All profiles are valid")
        """
        errors = self.config_service.validate_all_profiles()
        if errors:
            logger.warning(f"Found errors in {len(errors)} profiles")
        else:
            logger.debug(f"Validated all profiles successfully")
        return errors

    def get_validation_config(
        self,
        use_cache: bool = True
    ) -> ValidationConfig:
        """
        Get global validation configuration.

        Args:
            use_cache: Use cached config if available (default: True)

        Returns:
            ValidationConfig instance

        Example:
            validation_config = engine.get_validation_config()
            print(f"Decision rules: {validation_config.decision_rules}")
        """
        config = self.config_service.get_validation_config(use_cache=use_cache)
        logger.debug("Retrieved global validation config")
        return config

    def get_terminology_config(
        self,
        use_cache: bool = True
    ) -> TerminologyConfig:
        """
        Get global terminology configuration.

        Args:
            use_cache: Use cached config if available (default: True)

        Returns:
            TerminologyConfig instance

        Example:
            terminology_config = engine.get_terminology_config()
            print(f"Global terms: {len(terminology_config.global_.exact_matches)}")
        """
        config = self.config_service.get_terminology_config(use_cache=use_cache)
        logger.debug("Retrieved global terminology config")
        return config

    def get_metrics_config(
        self,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Get metrics configuration.

        Args:
            use_cache: Use cached config if available (default: True)

        Returns:
            Dictionary with metrics configuration

        Example:
            metrics_config = engine.get_metrics_config()
            percentiles = metrics_config["metrics"]["statistics"]["percentiles"]
            print(f"Percentiles: {percentiles}")
        """
        config = self.config_service.get_metrics_config(use_cache=use_cache)
        logger.debug("Retrieved metrics config")
        return config

    def get_config_root(self) -> Path:
        """
        Get configuration root directory.

        Returns:
            Path to config root

        Example:
            config_root = engine.get_config_root()
            print(f"Config directory: {config_root}")
        """
        return self.config_root
