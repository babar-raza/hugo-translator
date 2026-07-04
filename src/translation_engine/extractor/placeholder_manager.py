"""
Placeholder management for protecting non-translatable content.
"""
import difflib
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

        # Fuzzy replacement: handle translator-modified tokens like {Platch_1} or
        # { PLACHEHOLODER _1 } (NLLB adds spaces and misspells the keyword).
        # Pattern: any {…N…} where N is the digit sequence, with optional trailing
        # whitespace/garbage before the closing brace.
        def fuzzy_replace(match: re.Match) -> str:
            token = match.group(0)
            number = match.group(1)
            key = f"{{PLACEHOLDER_{number}}}"
            return placeholder_map.get(key, token)

        restored = re.sub(r"\{[^{}]*?(\d+)[^{}]*?\}", fuzzy_replace, restored)

        # Inter-pass cleanup: remove corrupted placeholder tokens where M2M100 dropped the
        # digit entirely (e.g. {PLACEHOLDER_1} → {PROLEXHOODERS}}).
        # Pattern: { followed by ALL-CAPS/underscore only (no digit) followed by one or more }
        # This can only be a corrupted placeholder — valid translated content never looks like this.
        if placeholder_map:
            restored = re.sub(r'\{[A-Z][A-Z_]*[A-Z]\}+', '', restored)

        # Third pass: handle cases where NLLB completely replaced the placeholder token
        # with a "guessed" variant of the original (e.g. PropertyCollection →
        # PropertiesCollection). If the original term is absent but a close variant
        # exists in the text, replace the variant with the original.
        _PASCAL_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+\b")
        for placeholder, original in placeholder_map.items():
            if original not in restored and re.match(r"^[A-Z]", original):
                # Find all PascalCase-ish words in restored text
                candidates = _PASCAL_RE.findall(restored)
                # cutoff=0.92: strict enough to avoid substituting real translated words
                # that happen to resemble the original (e.g. PropertiesCollection ≈ PropertyCollection)
                matches = difflib.get_close_matches(original, candidates, n=1, cutoff=0.92)
                if matches and matches[0] != original:
                    restored = restored.replace(matches[0], original, 1)

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
