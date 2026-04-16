"""
Glossary-based post-translation correction.

Applies deterministic term corrections to improve translation quality
for known vocabulary errors.
"""
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

logger = logging.getLogger(__name__)


class GlossaryCorrector:
    """
    Post-process translations using glossary-based corrections.

    Loads a YAML glossary file with term mappings and applies corrections
    to translated text using word-boundary-aware regex matching.
    """

    def __init__(self, glossary_path: Path | str):
        """
        Initialize glossary corrector.

        Args:
            glossary_path: Path to YAML glossary file

        Raises:
            FileNotFoundError: If glossary file doesn't exist
            ValueError: If glossary format is invalid
        """
        self.glossary_path = Path(glossary_path)

        if not self.glossary_path.exists():
            raise FileNotFoundError(
                f"Glossary file not found: {self.glossary_path}"
            )

        self.glossary = self._load_glossary()
        self.corrections = self.glossary.get("corrections", {})
        self.language_pair = tuple(self.glossary.get("language_pair", ["unknown", "unknown"]))

        logger.info(
            f"Loaded glossary for {self.language_pair[0]} -> {self.language_pair[1]} "
            f"with {len(self.corrections)} correction rules"
        )

    def _load_glossary(self) -> Dict:
        """Load and validate glossary from YAML file."""
        try:
            with open(self.glossary_path, "r", encoding="utf-8") as f:
                glossary = yaml.safe_load(f)

            if not isinstance(glossary, dict):
                raise ValueError("Glossary must be a YAML dictionary")

            if "corrections" not in glossary:
                logger.warning(
                    f"Glossary {self.glossary_path} has no 'corrections' section"
                )
                glossary["corrections"] = {}

            return glossary

        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in glossary file: {e}")

    def apply_corrections(
        self,
        text: str,
        src_lang: str | None = None,
        tgt_lang: str | None = None
    ) -> Tuple[str, List[str]]:
        """
        Apply glossary corrections to translated text.

        Uses word-boundary matching to avoid replacing partial words.
        For example, "métrage" will be replaced but "estimation" won't be.

        Args:
            text: Translated text to correct
            src_lang: Source language code (for validation)
            tgt_lang: Target language code (for validation)

        Returns:
            Tuple of (corrected_text, list_of_corrections_applied)

        Example:
            >>> corrector = GlossaryCorrector("config/glossaries/en-fr.yaml")
            >>> text = "Métrage plusieurs fichiers"
            >>> corrected, changes = corrector.apply_corrections(text, "en", "fr")
            >>> print(corrected)
            "Fusion plusieurs fichiers"
            >>> print(changes)
            ["métrage -> fusion"]
        """
        # Validate language pair if provided
        if src_lang and tgt_lang:
            expected = (src_lang, tgt_lang)
            if self.language_pair != expected:
                logger.warning(
                    f"Language pair mismatch: glossary is for {self.language_pair}, "
                    f"but translation is {expected}"
                )

        if not self.corrections:
            return text, []

        corrections_applied = []
        corrected = text

        for incorrect, correct in self.corrections.items():
            # Use word boundary matching to avoid partial replacements
            # Case-insensitive matching
            pattern = r'\b' + re.escape(incorrect) + r'\b'

            # Find all matches (case-insensitive)
            matches = re.finditer(pattern, corrected, flags=re.IGNORECASE)
            match_found = False

            for match in matches:
                match_found = True
                # Preserve original case if first letter was uppercase
                matched_text = match.group(0)
                if matched_text and matched_text[0].isupper():
                    # Capitalize replacement
                    replacement = correct.capitalize()
                else:
                    replacement = correct

                # Replace this occurrence
                corrected = (
                    corrected[:match.start()] +
                    replacement +
                    corrected[match.end():]
                )

            if match_found:
                corrections_applied.append(f"{incorrect} -> {correct}")

        if corrections_applied:
            logger.debug(
                f"Applied {len(corrections_applied)} corrections: {corrections_applied}"
            )

        return corrected, corrections_applied

    def get_correction_count(self) -> int:
        """Get number of correction rules in glossary."""
        return len(self.corrections)

    def get_language_pair(self) -> Tuple[str, str]:
        """Get source and target language codes."""
        return self.language_pair


# Singleton-style glossary cache to avoid reloading files
_glossary_cache: Dict[str, GlossaryCorrector] = {}


def get_glossary_corrector(
    src_lang: str, tgt_lang: str, config_root: Path | str = "config"
) -> GlossaryCorrector | None:
    """
    Get or create a glossary corrector for a language pair.

    Uses a cache to avoid reloading glossary files.

    Args:
        src_lang: Source language code (e.g., "en")
        tgt_lang: Target language code (e.g., "fr")
        config_root: Root directory for config files

    Returns:
        GlossaryCorrector instance, or None if glossary file doesn't exist
    """
    cache_key = f"{src_lang}-{tgt_lang}"

    if cache_key in _glossary_cache:
        return _glossary_cache[cache_key]

    glossary_path = Path(config_root) / "glossaries" / f"{src_lang}-{tgt_lang}.yaml"

    if not glossary_path.exists():
        logger.debug(f"No glossary found for {src_lang} -> {tgt_lang}")
        return None

    try:
        corrector = GlossaryCorrector(glossary_path)
        _glossary_cache[cache_key] = corrector
        return corrector
    except (FileNotFoundError, ValueError) as e:
        logger.warning(f"Failed to load glossary {glossary_path}: {e}")
        return None
