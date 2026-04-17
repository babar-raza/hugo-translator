"""
Translation Memory Override Controller.

Manages cache bypass logic for selective retranslation.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from re import Pattern
from typing import Any


class OverrideMode(str, Enum):
    """Override mode for TM operations."""
    NORMAL = "normal"      # Default: use cache, update on miss
    BYPASS = "bypass"      # Skip cache entirely, don't update
    REFRESH = "refresh"    # Skip cache, force update with new translation
    VALIDATE = "validate"  # Use cache but also translate for comparison


@dataclass
class OverrideFilter:
    """Filters to selectively apply override."""
    source_patterns: list[str] = field(default_factory=list)
    frontmatter_keys: list[str] = field(default_factory=list)
    target_langs: list[str] = field(default_factory=list)
    modified_after: datetime | None = None

    # Compiled patterns (internal)
    _compiled_patterns: list[Pattern] = field(default_factory=list, repr=False)

    def __post_init__(self):
        """Compile regex patterns."""
        self._compiled_patterns = []
        for pattern in self.source_patterns:
            try:
                self._compiled_patterns.append(re.compile(pattern))
            except re.error:
                pass  # Skip invalid patterns


@dataclass
class OverrideConfig:
    """Configuration for override behavior."""
    mode: OverrideMode = OverrideMode.NORMAL
    filters: OverrideFilter = field(default_factory=OverrideFilter)

    # Statistics tracking
    segments_bypassed: int = 0
    segments_refreshed: int = 0
    segments_normal: int = 0


class OverrideController:
    """
    Controls Translation Memory override behavior.

    Determines whether to bypass cache lookup for specific segments
    based on configured mode and filters.
    """

    def __init__(self, config: OverrideConfig | None = None):
        """
        Initialize override controller.

        Args:
            config: Override configuration. Defaults to normal mode.
        """
        self.config = config or OverrideConfig()
        self._stats = {
            "total_checked": 0,
            "bypassed": 0,
            "refreshed": 0,
            "normal": 0,
        }

    @property
    def mode(self) -> OverrideMode:
        """Get current override mode."""
        return self.config.mode

    @property
    def stats(self) -> dict[str, int]:
        """Get override statistics."""
        return dict(self._stats)

    def get_stats(self) -> dict[str, Any]:
        """Return stats with configuration details for reporting."""
        filters = self.config.filters
        return {
            "mode": self.config.mode.value,
            "total_checked": self._stats["total_checked"],
            "bypassed": self._stats["bypassed"],
            "refreshed": self._stats["refreshed"],
            "normal": self._stats["normal"],
            "filters": {
                "source_patterns": list(filters.source_patterns),
                "frontmatter_keys": list(filters.frontmatter_keys),
                "target_langs": list(filters.target_langs),
            },
        }

    def should_bypass_lookup(
        self,
        source_text: str,
        target_lang: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """
        Determine if TM lookup should be bypassed for this segment.

        Args:
            source_text: Source text to translate
            target_lang: Target language code
            context: Optional context (frontmatter_key, etc.)

        Returns:
            True if TM lookup should be skipped
        """
        self._stats["total_checked"] += 1

        # Normal mode never bypasses
        if self.config.mode == OverrideMode.NORMAL:
            self._stats["normal"] += 1
            return False

        # Bypass and Refresh modes always bypass (unless filtered)
        if self.config.mode in (OverrideMode.BYPASS, OverrideMode.REFRESH):
            # Check filters
            if self._matches_filters(source_text, target_lang, context):
                if self.config.mode == OverrideMode.BYPASS:
                    self._stats["bypassed"] += 1
                else:
                    self._stats["refreshed"] += 1
                return True
            else:
                self._stats["normal"] += 1
                return False

        # Validate mode doesn't bypass lookup but still translates
        if self.config.mode == OverrideMode.VALIDATE:
            self._stats["normal"] += 1
            return False

        return False

    def should_update_cache(
        self,
        source_text: str,
        target_lang: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """
        Determine if TM cache should be updated with new translation.

        Args:
            source_text: Source text
            target_lang: Target language
            context: Optional context

        Returns:
            True if cache should be updated
        """
        # Normal mode always updates on miss (handled by TM)
        if self.config.mode == OverrideMode.NORMAL:
            return True

        # Bypass mode never updates
        if self.config.mode == OverrideMode.BYPASS:
            return False

        # Refresh mode always updates (overwrites)
        if self.config.mode == OverrideMode.REFRESH:
            return self._matches_filters(source_text, target_lang, context)

        # Validate mode doesn't update
        if self.config.mode == OverrideMode.VALIDATE:
            return False

        return True

    def should_force_translate(
        self,
        source_text: str,
        target_lang: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """
        Determine if fresh translation should be forced regardless of cache.

        Used in VALIDATE mode to compare cache vs model.

        Args:
            source_text: Source text
            target_lang: Target language
            context: Optional context

        Returns:
            True if fresh translation should be performed
        """
        if self.config.mode == OverrideMode.VALIDATE:
            return self._matches_filters(source_text, target_lang, context)

        # For BYPASS and REFRESH, this is implied by should_bypass_lookup
        return False

    def _matches_filters(
        self,
        source_text: str,
        target_lang: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """
        Check if segment matches override filters.

        If no filters configured, matches everything.
        If filters configured, must match at least one.
        """
        filters = self.config.filters

        # No filters = match all
        if not any([
            filters.source_patterns,
            filters.frontmatter_keys,
            filters.target_langs,
        ]):
            return True

        # Check source patterns
        if filters._compiled_patterns:
            for pattern in filters._compiled_patterns:
                if pattern.search(source_text):
                    return True

        # Check target language
        if filters.target_langs:
            if target_lang in filters.target_langs:
                return True

        # Check frontmatter key
        if filters.frontmatter_keys and context:
            fm_key = context.get("frontmatter_key", "")
            for key_pattern in filters.frontmatter_keys:
                if fm_key.startswith(key_pattern) or fm_key == key_pattern:
                    return True

        # No filter matched
        return False

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._stats = {
            "total_checked": 0,
            "bypassed": 0,
            "refreshed": 0,
            "normal": 0,
        }

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "OverrideController":
        """
        Create controller from configuration dictionary.

        Args:
            config_dict: Dictionary with mode and filters

        Returns:
            Configured OverrideController
        """
        mode = OverrideMode(config_dict.get("mode", "normal"))

        filter_dict = config_dict.get("filters", {})
        filters = OverrideFilter(
            source_patterns=filter_dict.get("source_patterns", []),
            frontmatter_keys=filter_dict.get("frontmatter_keys", []),
            target_langs=filter_dict.get("target_langs", []),
            modified_after=None,  # Parse if needed
        )

        config = OverrideConfig(mode=mode, filters=filters)
        return cls(config)
