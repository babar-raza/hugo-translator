"""
Configuration loader service for site profiles and global settings.

Provides centralized access to site profiles with validation and caching.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from .models import (
    GlobalConfig,
    SiteProfile,
    ValidationConfig,
    TerminologyConfig,
)


class ConfigLoadError(Exception):
    """Exception raised when configuration loading fails."""
    pass


class ConfigValidationError(ConfigLoadError):
    """Exception raised when configuration validation fails."""
    pass


class ConfigService:
    """Service for loading and managing site profiles and global configuration."""

    def __init__(self, config_root: str | Path):
        """Initialize the configuration service."""
        self.config_root = Path(config_root)
        if not self.config_root.exists():
            raise ConfigLoadError(f"Config root does not exist: {self.config_root}")

        self.site_profiles_dir = self.config_root / "site_profiles"
        self.global_config_path = self.config_root / "global.yaml"
        self.validation_config_path = self.config_root / "validation.yaml"
        self.terminology_config_path = self.config_root / "terminology.yaml"

        self._profile_cache: Dict[str, SiteProfile] = {}
        self._global_config: Optional[GlobalConfig] = None
        self._validation_config: Optional[ValidationConfig] = None
        self._terminology_config: Optional[TerminologyConfig] = None
        self._raw_global_config: Dict[str, Any] = {}
        self._load_global_config()

    def _load_global_config(self) -> None:
        """Load global configuration with defaults."""
        if self.global_config_path.exists():
            try:
                with open(self.global_config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    self._raw_global_config = data or {}
                    self._global_config = GlobalConfig(**data) if data else GlobalConfig()
            except Exception as e:
                raise ConfigLoadError(f"Failed to load global config: {e}")
        else:
            self._global_config = GlobalConfig()
            self._raw_global_config = {}

    @property
    def global_config(self) -> GlobalConfig:
        """Get global configuration."""
        if self._global_config is None:
            self._load_global_config()
        return self._global_config

    def get_config(self) -> Dict[str, Any]:
        """
        Return raw global configuration dictionary.

        Used by components that expect dictionary access (e.g., validation defaults).
        """
        return dict(self._raw_global_config)

    def get_site_profile(self, site_id: str, use_cache: bool = True) -> SiteProfile:
        """Retrieve validated site profile by ID."""
        if use_cache and site_id in self._profile_cache:
            return self._profile_cache[site_id]

        profile_path = self.site_profiles_dir / f"{site_id}.yaml"
        if not profile_path.exists():
            raise ConfigLoadError(f"Profile not found: {site_id}")

        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            data = self._apply_env_overrides(site_id, data)
            profile = SiteProfile(**data)
            self._profile_cache[site_id] = profile
            return profile
        except Exception as e:
            raise ConfigLoadError(f"Failed to load profile {site_id}: {e}")

    def _apply_env_overrides(self, site_id: str, data: dict) -> dict:
        """Apply environment variable overrides to profile data."""
        env_prefix = f"SITE_{site_id.upper().replace('.', '_').replace('-', '_')}_"
        
        if f"{env_prefix}DEFAULT_SOURCE_LANG" in os.environ:
            data["default_source_lang"] = os.environ[f"{env_prefix}DEFAULT_SOURCE_LANG"]
        
        if f"{env_prefix}TARGET_LANGS" in os.environ:
            data["target_langs"] = [
                lang.strip() for lang in os.environ[f"{env_prefix}TARGET_LANGS"].split(",")
            ]
        
        return data

    def list_sites(self) -> List[str]:
        """List all configured site IDs."""
        if not self.site_profiles_dir.exists():
            return []
        return sorted([f.stem for f in self.site_profiles_dir.glob("*.yaml")])

    def validate_all_profiles(self) -> Dict[str, List[str]]:
        """Validate all profiles and return errors per site."""
        errors: Dict[str, List[str]] = {}
        for site_id in self.list_sites():
            try:
                self.get_site_profile(site_id, use_cache=False)
            except ConfigLoadError as e:
                errors[site_id] = [str(e)]
        return errors

    def reload_profile(self, site_id: str) -> SiteProfile:
        """Reload a profile from disk, bypassing cache."""
        if site_id in self._profile_cache:
            del self._profile_cache[site_id]
        return self.get_site_profile(site_id, use_cache=False)

    def clear_cache(self) -> None:
        """Clear all cached profiles."""
        self._profile_cache.clear()

    def get_validation_config(self, use_cache: bool = True) -> ValidationConfig:
        """Load and validate the validation configuration."""
        if use_cache and self._validation_config is not None:
            return self._validation_config

        if not self.validation_config_path.exists():
            raise ConfigLoadError(
                f"Validation config not found: {self.validation_config_path}"
            )

        try:
            with open(self.validation_config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                raise ConfigValidationError("Validation config is empty")

            self._validation_config = ValidationConfig(**data)
            return self._validation_config
        except yaml.YAMLError as e:
            raise ConfigValidationError(
                f"Invalid YAML in validation config: {e}"
            )
        except ValidationError as e:
            raise ConfigValidationError(
                f"Validation config schema validation failed: {e}"
            )
        except Exception as e:
            raise ConfigLoadError(f"Failed to load validation config: {e}")

    def get_terminology_config(self, use_cache: bool = True) -> TerminologyConfig:
        """Load and validate the terminology configuration."""
        if use_cache and self._terminology_config is not None:
            return self._terminology_config

        if not self.terminology_config_path.exists():
            raise ConfigLoadError(
                f"Terminology config not found: {self.terminology_config_path}"
            )

        try:
            with open(self.terminology_config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                raise ConfigValidationError("Terminology config is empty")

            self._terminology_config = TerminologyConfig(**data)
            return self._terminology_config
        except yaml.YAMLError as e:
            raise ConfigValidationError(
                f"Invalid YAML in terminology config: {e}"
            )
        except ValidationError as e:
            raise ConfigValidationError(
                f"Terminology config schema validation failed: {e}"
            )
        except Exception as e:
            raise ConfigLoadError(f"Failed to load terminology config: {e}")

    def reload_validation_config(self) -> ValidationConfig:
        """Reload validation config from disk, bypassing cache."""
        self._validation_config = None
        return self.get_validation_config(use_cache=False)

    def reload_terminology_config(self) -> TerminologyConfig:
        """Reload terminology config from disk, bypassing cache."""
        self._terminology_config = None
        return self.get_terminology_config(use_cache=False)

    def get_merged_validation_config(
        self, site_profile: "SiteProfile"
    ) -> Dict[str, any]:
        """
        Merge global validation config with site-specific overrides.

        Args:
            site_profile: Site profile containing potential overrides

        Returns:
            Merged validation configuration dictionary
        """
        # Start with global validation config
        global_validation = self.get_validation_config()
        merged = {
            "enabled": self.global_config.validation.enabled
            if self.global_config.validation
            else True,
            "mode": self.global_config.validation.mode
            if self.global_config.validation
            else "normal",
            "decision_rules": global_validation.decision_rules.model_dump(),
            "retry_strategy": global_validation.retry_strategy.model_dump(),
            "validators": {
                name: config.model_dump()
                for name, config in self.global_config.validation_defaults.validators.items()
            }
            if self.global_config.validation_defaults
            else {},
        }

        # Apply site-specific overrides if present
        if site_profile.validation:
            if site_profile.validation.enabled is not None:
                merged["enabled"] = site_profile.validation.enabled

            if site_profile.validation.validation_mode:
                merged["mode"] = site_profile.validation.validation_mode

            if site_profile.validation.validators:
                # Merge validator configs (site overrides global)
                for name, config in site_profile.validation.validators.items():
                    merged["validators"][name] = config.model_dump()

        return merged

    def get_merged_terminology_config(
        self, site_profile: "SiteProfile"
    ) -> Dict[str, any]:
        """
        Merge global terminology config with site-specific overrides.

        Args:
            site_profile: Site profile containing potential overrides

        Returns:
            Merged terminology configuration dictionary
        """
        # Start with global terminology config
        global_terminology = self.get_terminology_config()
        merged = {
            "enabled": self.global_config.terminology.enabled
            if self.global_config.terminology
            else True,
            "preserve_mode": self.global_config.terminology.preserve_mode
            if self.global_config.terminology
            else "BOTH",
            "global_terms": {
                "exact_matches": [
                    term.model_dump() for term in global_terminology.global_.exact_matches
                ],
                "patterns": [
                    pattern.model_dump() for pattern in global_terminology.global_.patterns
                ],
            },
            "site_specific_terms": [],
        }

        # Apply site-specific configuration if present
        if site_profile.terminology:
            if site_profile.terminology.enabled is not None:
                merged["enabled"] = site_profile.terminology.enabled

            if site_profile.terminology.preserve_mode:
                merged["preserve_mode"] = site_profile.terminology.preserve_mode

            # Add site-specific custom terms
            if site_profile.terminology.custom_terms:
                merged["site_specific_terms"] = [
                    term.model_dump() for term in site_profile.terminology.custom_terms
                ]

            # Handle inheritance
            if not site_profile.terminology.inherit_global:
                # If not inheriting, clear global terms
                merged["global_terms"] = {"exact_matches": [], "patterns": []}

        return merged
