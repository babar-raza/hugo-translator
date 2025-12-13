"""Terminology management and orchestration.

This module provides the TerminologyManager class which:
- Loads terminology configuration from YAML
- Merges global rules with site-specific overrides
- Orchestrates terminology detection and protection
- Provides end-to-end protection/restoration workflow
"""

import yaml
from pathlib import Path
from typing import List, Optional
from src.translation_engine.terminology.models import (
    TermRule,
    PreserveMode,
    TermSeverity,
    ProtectedSegment,
)
from src.translation_engine.terminology.terminology_detector import TerminologyDetector
from src.translation_engine.terminology.terminology_protector import TerminologyProtector


class TerminologyManager:
    """Manages terminology detection and protection.

    This class provides the main interface for terminology management:
    1. Loads configuration from terminology.yaml
    2. Merges global rules with site-specific overrides
    3. Detects terminology in text
    4. Protects terminology with placeholders
    5. Restores original terms after processing

    Example:
        manager = TerminologyManager("config/terminology.yaml")
        rules = manager.get_rules("reference.aspose.net")
        protected = manager.protect("Aspose.Words for .NET", "reference.aspose.net")
        restored = manager.restore(protected)
    """

    def __init__(self, config_path: str):
        """Initialize terminology manager with configuration.

        Args:
            config_path: Path to terminology.yaml configuration file

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        # Load configuration
        self._load_config()

        # Initialize protector (stateless, can be reused)
        self.protector = TerminologyProtector()

    def _load_config(self):
        """Load and parse terminology configuration from YAML."""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)

        if not config_data:
            raise ValueError("Empty configuration file")

        # Store version
        self.version = config_data.get('version', '1.0')

        # Parse global rules
        self.global_rules = self._parse_rules(config_data.get('global', {}))

        # Parse site overrides
        self.site_overrides = {}
        site_overrides_data = config_data.get('site_overrides', {})
        for site, site_config in site_overrides_data.items():
            self.site_overrides[site] = {
                'inherit_global': site_config.get('inherit_global', True),
                'rules': self._parse_rules(site_config)
            }

        # Store auto-discovery settings (not used yet)
        self.auto_discovery = config_data.get('auto_discovery', {})

    def _parse_rules(self, config_section: dict) -> List[TermRule]:
        """Parse term rules from configuration section.

        Args:
            config_section: Configuration section containing exact_matches and/or patterns

        Returns:
            List of parsed TermRule objects
        """
        rules = []

        # Parse exact matches
        exact_matches = config_section.get('exact_matches', [])
        for match_config in exact_matches:
            rules.append(TermRule(
                term=match_config.get('term'),
                category=match_config.get('category', 'unknown'),
                preserve_mode=PreserveMode(match_config.get('preserve_mode', 'both')),
                severity=TermSeverity(match_config.get('severity', 'warning')),
                case_sensitive=match_config.get('case_sensitive', True),
                description=match_config.get('description')
            ))

        # Parse patterns
        patterns = config_section.get('patterns', [])
        for pattern_config in patterns:
            rules.append(TermRule(
                pattern=pattern_config.get('pattern'),
                category=pattern_config.get('category', 'unknown'),
                preserve_mode=PreserveMode(pattern_config.get('preserve_mode', 'protect')),
                severity=TermSeverity(pattern_config.get('severity', 'warning')),
                case_sensitive=pattern_config.get('case_sensitive', True),
                description=pattern_config.get('description')
            ))

        return rules

    def get_rules(self, site: Optional[str] = None) -> List[TermRule]:
        """Get applicable terminology rules for a site.

        Merges global rules with site-specific overrides.

        Args:
            site: Site identifier (e.g., "reference.aspose.net")
                  If None, returns only global rules

        Returns:
            List of applicable TermRule objects
        """
        if site is None or site not in self.site_overrides:
            # No site or site not found - return global rules only
            return self.global_rules.copy()

        site_config = self.site_overrides[site]

        # Check if site inherits global rules
        if site_config['inherit_global']:
            # Merge global + site-specific rules
            # Site rules come after global rules (allows overriding if needed)
            return self.global_rules + site_config['rules']
        else:
            # Site-only rules (don't inherit global)
            return site_config['rules']

    def protect(self, text: str, site: Optional[str] = None) -> ProtectedSegment:
        """Detect and protect terminology in text.

        This is the main entry point for terminology protection.
        It combines detection and protection in one step.

        Args:
            text: Source text to protect
            site: Site identifier for site-specific rules

        Returns:
            ProtectedSegment with placeholders and term mapping
        """
        # Get applicable rules
        rules = self.get_rules(site)

        # Detect terminology
        detector = TerminologyDetector(rules)
        detected_terms = detector.detect(text)

        # Protect with placeholders
        protected_segment = self.protector.protect(text, detected_terms)

        return protected_segment

    def restore(self, protected_segment: ProtectedSegment) -> str:
        """Restore original terms from protected segment.

        Args:
            protected_segment: Protected segment with placeholders

        Returns:
            Text with placeholders replaced by original terms
        """
        return self.protector.restore(protected_segment)
