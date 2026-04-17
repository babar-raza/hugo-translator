"""
Placeholder management for protecting non-translatable content.
"""
import re


class PlaceholderManager:
    """Manages placeholder replacement and restoration for protected content."""

    def __init__(self):
        """Initialize placeholder manager."""
        self.placeholder_map: dict[str, str] = {}
        self.counter = 0

    def protect(self, text: str, patterns: list[str]) -> tuple[str, dict[str, str]]:
        """
        Replace protected content with placeholders.

        Args:
            text: Original text
            patterns: List of regex patterns to protect

        Returns:
            Tuple of (protected_text, placeholder_map)
        """
        self.placeholder_map = {}
        self.counter = 0
        protected_text = text

        for pattern in patterns:
            protected_text = self._apply_pattern(protected_text, pattern)

        return protected_text, dict(self.placeholder_map)

    def _apply_pattern(self, text: str, pattern: str) -> str:
        """Apply a single protection pattern."""

        def replace_match(match: re.Match) -> str:
            placeholder = f"{{PLACEHOLDER_{self.counter}}}"
            self.placeholder_map[placeholder] = match.group(0)
            self.counter += 1
            return placeholder

        try:
            return re.sub(pattern, replace_match, text)
        except re.error:
            # If pattern is invalid, return text unchanged
            return text

    def restore(self, text: str, placeholder_map: dict[str, str]) -> str:
        """
        Restore placeholders to original content.

        Args:
            text: Text with placeholders
            placeholder_map: Mapping of placeholders to original content

        Returns:
            Text with placeholders restored
        """
        restored = text

        # Exact replacements first
        for placeholder, original in placeholder_map.items():
            restored = restored.replace(placeholder, original)

        # Fuzzy replacement: handle translator-modified tokens like {Platch_1}
        def fuzzy_replace(match: re.Match) -> str:
            token = match.group(0)
            number = match.group(1)
            key = f"{{PLACEHOLDER_{number}}}"
            return placeholder_map.get(key, token)

        restored = re.sub(r"\{[^{}]*?(\d+)\}", fuzzy_replace, restored)
        return restored

    def extract_placeholders(self, text: str) -> list[str]:
        """
        Extract all placeholder tokens from text.

        Args:
            text: Text potentially containing placeholders

        Returns:
            List of placeholder tokens found
        """
        return re.findall(r"\{PLACEHOLDER_\d+\}", text)
