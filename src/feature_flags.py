"""
Centralized Feature Flag System

Provides a unified API for checking feature flags across the translation system.
Feature flags enable gradual rollout, A/B testing, and quick rollback of features.

Usage:
    from src.feature_flags import get_feature_flags

    flags = get_feature_flags()
    if flags.is_enabled('use_ast_translation'):
        # Use AST-based translation
        ...
    else:
        # Use legacy translation
        ...

Configuration:
    Feature flags are loaded from config/global.yaml under the 'features' section.
    Flags can be overridden via environment variables (prefix: FEATURE_FLAG_).

Example config/global.yaml:
    features:
      enable_parallel_processing: true
      enable_semantic_tm: true
      enable_model_benchmarking: false
      enable_auto_model_selection: true
      enable_quality_scoring: false
      use_ast_translation: true  # Per-site flag override

Environment variable override:
    export FEATURE_FLAG_ENABLE_MODEL_BENCHMARKING=true
    # Overrides config/global.yaml value

Related:
    - config/global.yaml (feature flags configuration)
    - docs/ast_translation_rollout.md (AST feature rollout guide)
    - scripts/ops/toggle_ast_translation.py (per-site AST toggle)
"""

import os
from pathlib import Path

import yaml


class FeatureFlags:
    """
    Feature flag manager for the translation system.

    Loads feature flags from config/global.yaml and supports environment
    variable overrides for deployment-time configuration changes.
    """

    def __init__(self, config_path: str | None = None):
        """
        Initialize feature flag system.

        Args:
            config_path: Path to global.yaml config file.
                        Defaults to config/global.yaml relative to project root.
        """
        self._flags: dict[str, bool] = {}
        self._config_path = config_path or "config/global.yaml"
        self._load_flags()

    def _load_flags(self) -> None:
        """Load feature flags from config file and environment variables."""
        # Load from config file
        config_file = Path(self._config_path)
        if config_file.exists():
            with open(config_file, encoding="utf-8") as f:
                try:
                    config = yaml.safe_load(f)
                    self._flags = config.get("features", {})
                except yaml.YAMLError:
                    # Fall back to defaults if config is invalid
                    self._flags = self._default_flags()
        else:
            # No config file, use defaults
            self._flags = self._default_flags()

        # Apply environment variable overrides
        self._apply_env_overrides()

    def _default_flags(self) -> dict[str, bool]:
        """
        Default feature flag values (used when config file is missing).

        Returns:
            Dictionary of default flag values (conservative defaults).
        """
        return {
            # Core system features
            "enable_parallel_processing": True,
            "enable_semantic_tm": True,
            "enable_auto_model_selection": True,
            # Experimental features (default off)
            "enable_model_benchmarking": False,
            "enable_quality_scoring": False,
            # Gradual rollout features (default off for safety)
            "use_ast_translation": False,
            "protect_hugo_shortcodes": True,  # Safety feature
            "enable_batch_optimization": True,
        }

    def _apply_env_overrides(self) -> None:
        """
        Apply environment variable overrides to feature flags.

        Environment variables:
            FEATURE_FLAG_<FLAG_NAME>=true|false

        Example:
            FEATURE_FLAG_ENABLE_MODEL_BENCHMARKING=true
            FEATURE_FLAG_USE_AST_TRANSLATION=false
        """
        env_prefix = "FEATURE_FLAG_"

        for env_var, value in os.environ.items():
            if env_var.startswith(env_prefix):
                # Extract flag name (convert ENABLE_MODEL_BENCHMARKING to enable_model_benchmarking)
                flag_name = env_var[len(env_prefix) :].lower()

                # Parse boolean value
                bool_value = value.lower() in ("true", "1", "yes", "on")

                # Override config value
                self._flags[flag_name] = bool_value

    def is_enabled(self, flag_name: str, default: bool = False) -> bool:
        """
        Check if a feature flag is enabled.

        Args:
            flag_name: Name of the feature flag (e.g., 'enable_parallel_processing')
            default: Default value if flag is not defined (defaults to False for safety)

        Returns:
            True if feature is enabled, False otherwise

        Example:
            >>> flags = get_feature_flags()
            >>> if flags.is_enabled('use_ast_translation'):
            ...     print("AST translation enabled")
        """
        return self._flags.get(flag_name, default)

    def is_disabled(self, flag_name: str, default: bool = False) -> bool:
        """
        Check if a feature flag is disabled (inverse of is_enabled).

        Args:
            flag_name: Name of the feature flag
            default: Default value if flag is not defined (defaults to False)

        Returns:
            True if feature is disabled, False otherwise

        Example:
            >>> flags = get_feature_flags()
            >>> if flags.is_disabled('enable_model_benchmarking'):
            ...     print("Model benchmarking is off")
        """
        return not self.is_enabled(flag_name, default)

    def get(self, flag_name: str, default: bool = False) -> bool:
        """
        Get feature flag value (alias for is_enabled for dict-like access).

        Args:
            flag_name: Name of the feature flag
            default: Default value if flag is not defined

        Returns:
            Feature flag value (bool)
        """
        return self.is_enabled(flag_name, default)

    def get_all(self) -> dict[str, bool]:
        """
        Get all feature flags as a dictionary.

        Returns:
            Dictionary of all feature flags and their values

        Example:
            >>> flags = get_feature_flags()
            >>> all_flags = flags.get_all()
            >>> print(f"Total flags: {len(all_flags)}")
        """
        return self._flags.copy()

    def reload(self) -> None:
        """
        Reload feature flags from config file.

        Useful for picking up configuration changes without restarting the application.
        """
        self._load_flags()


# Global singleton instance
_feature_flags: FeatureFlags | None = None


def get_feature_flags(config_path: str | None = None) -> FeatureFlags:
    """
    Get the global FeatureFlags instance (singleton pattern).

    Args:
        config_path: Optional path to config file (only used on first call)

    Returns:
        Global FeatureFlags instance

    Example:
        >>> from src.feature_flags import get_feature_flags
        >>>
        >>> flags = get_feature_flags()
        >>> if flags.is_enabled('use_ast_translation'):
        ...     # Use AST translation
        ...     pass
    """
    global _feature_flags

    if _feature_flags is None:
        _feature_flags = FeatureFlags(config_path)

    return _feature_flags


def reset_feature_flags() -> None:
    """
    Reset the global FeatureFlags instance (for testing).

    This forces the next call to get_feature_flags() to create a new instance,
    which is useful for testing with different configurations.
    """
    global _feature_flags
    _feature_flags = None


# Convenience function for common pattern
def feature_enabled(flag_name: str, default: bool = False) -> bool:
    """
    Quick check if a feature is enabled (convenience function).

    Args:
        flag_name: Name of the feature flag
        default: Default value if flag is not defined

    Returns:
        True if feature is enabled, False otherwise

    Example:
        >>> from src.feature_flags import feature_enabled
        >>>
        >>> if feature_enabled('use_ast_translation'):
        ...     print("AST enabled")
    """
    return get_feature_flags().is_enabled(flag_name, default)
