"""
TextUnit extractor for AST-based translation: AST-based translation with node addressing.

This module extracts translatable TextUnits from AST nodes for deterministic,
structure-preserving translation. Implements smart segmentation, product name
detection, and native list-based batch translation.
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .text_unit import BodyTranslationPlan, TextUnit, TextUnitKind
from ..parser.ast_nodes import ASTNode, NodeType

logger = logging.getLogger(__name__)


# Batch translation tuning constants
LANGUAGE_PURITY_MIN_LENGTH = 15   # Minimum text length for reliable language detection
LANGUAGE_PURITY_MIN_SCRIPT_RATIO = 0.4  # Minimum target-script ratio to accept mixed-script text
FALLBACK_RATE_THRESHOLD = 0.05    # Alert threshold for fallback rate (5%)
TOKEN_PER_WORD_ESTIMATE = 1.3     # Average tokens per word for M2M100 estimation

# Script-similar languages that may be confused by langdetect
# Languages that share the same script often get misdetected
SCRIPT_SIMILAR_LANGUAGES = {
    'ar': {'fa', 'it', 'es', 'fr', 'pt'},  # Arabic <-> Farsi (same script) + Romance languages (Latin script terms trigger false positives)
    'fa': {'ar'},  # Farsi/Persian <-> Arabic
    # Add more script-similar pairs as needed:
    # 'hi': {'ne', 'mr'},  # Hindi, Nepali, Marathi all use Devanagari
    # 'sr': {'ru', 'uk', 'bg'},  # Serbian, Russian, Ukrainian, Bulgarian use Cyrillic
}

# Script ranges for target-language ratio checks
ARABIC_SCRIPT_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')
TARGET_SCRIPT_REGEX = {
    'ar': ARABIC_SCRIPT_RE,
    'fa': ARABIC_SCRIPT_RE,
    'ur': ARABIC_SCRIPT_RE,
    'ps': ARABIC_SCRIPT_RE,
}

# Frontmatter translation configuration (FIX-BT-03)
TRANSLATABLE_FRONTMATTER_FIELDS = {
    'title', 'description', 'keywords',
    'step1', 'step2', 'step3', 'step4', 'step5'
}

NON_TRANSLATABLE_FRONTMATTER_FIELDS = {
    'slug', 'productname', 'productkey', 'platformkey', 'productplatform',
    'date', 'lastmod', 'weight', 'draft', 'type'
}

# Validate constants at module load time (VLD-04, PH-01)
# Use ValueError instead of assert to ensure validation works with -O flag
if not (5 <= LANGUAGE_PURITY_MIN_LENGTH <= 100):
    raise ValueError(
        f"Invalid configuration: LANGUAGE_PURITY_MIN_LENGTH must be "
        f"between 5 and 100, got {LANGUAGE_PURITY_MIN_LENGTH}"
    )

if not (0.0 <= LANGUAGE_PURITY_MIN_SCRIPT_RATIO <= 1.0):
    raise ValueError(
        f"Invalid configuration: LANGUAGE_PURITY_MIN_SCRIPT_RATIO must be "
        f"between 0.0 and 1.0, got {LANGUAGE_PURITY_MIN_SCRIPT_RATIO}"
    )

if not (0.01 <= FALLBACK_RATE_THRESHOLD <= 0.5):
    raise ValueError(
        f"Invalid configuration: FALLBACK_RATE_THRESHOLD must be "
        f"between 0.01 and 0.5, got {FALLBACK_RATE_THRESHOLD}"
    )

if not (0.5 <= TOKEN_PER_WORD_ESTIMATE <= 3.0):
    raise ValueError(
        f"Invalid configuration: TOKEN_PER_WORD_ESTIMATE must be "
        f"between 0.5 and 3.0, got {TOKEN_PER_WORD_ESTIMATE}"
    )


class TextUnitExtractor:
    """
    Extracts TextUnits from AST for node-addressed translation.

    Features:
    - Smart segmentation (adaptive/leaf_only/sentence_only)
    - Product name detection (NER + heuristics + terminology dict)
    - Native list-based batch translation with automatic fallback
    - Whitespace preservation
    - Deterministic extraction
    """

    def __init__(
        self,
        segmentation_strategy: str = "adaptive",
        terminology_file: Optional[Path] = None,
        mt_model: Optional[Any] = None,
        preserve_patterns: Optional[List[str]] = None,
        site_profile: Optional[Any] = None
    ):
        """
        Initialize extractor for native batch translation.

        Args:
            segmentation_strategy: "adaptive", "leaf_only", or "sentence_only"
            terminology_file: Path to terminology dictionary (one term per line)
            mt_model: M2M100 model instance (optional, not used for native batching)
            preserve_patterns: Regex patterns for content to preserve (e.g., brand names)
            site_profile: Site profile configuration for frontmatter field handling (optional)
        """
        self.segmentation_strategy = segmentation_strategy
        self.site_profile = site_profile

        # Load extraction config from site profile (with fallback to defaults)
        extraction_config = self._load_extraction_config()

        # Language purity configuration
        self.language_purity_min_length = extraction_config.get('language_purity', {}).get(
            'min_length', LANGUAGE_PURITY_MIN_LENGTH
        )
        self.language_purity_min_script_ratio = extraction_config.get('language_purity', {}).get(
            'min_script_ratio', LANGUAGE_PURITY_MIN_SCRIPT_RATIO
        )
        self.script_similar_languages = extraction_config.get('language_purity', {}).get(
            'script_similar_languages', SCRIPT_SIMILAR_LANGUAGES
        )

        # Batch translation tuning
        self.fallback_rate_threshold = extraction_config.get('batch_translation', {}).get(
            'fallback_rate_threshold', FALLBACK_RATE_THRESHOLD
        )
        self.token_per_word_estimate = extraction_config.get('batch_translation', {}).get(
            'token_per_word_estimate', TOKEN_PER_WORD_ESTIMATE
        )

        # Validate extraction config values
        self._validate_extraction_config()

        # Initialize preserve_patterns protection (if provided)
        self.preserve_patterns = preserve_patterns or []
        self.placeholder_manager = None
        if self.preserve_patterns:
            from .placeholder_manager import PlaceholderManager
            self.placeholder_manager = PlaceholderManager()
            logger.info(f"[DEBUG] PlaceholderManager initialized with {len(self.preserve_patterns)} preserve patterns")
            for i, pattern in enumerate(self.preserve_patterns):
                logger.debug(f"[DEBUG]   Pattern {i}: {pattern}")

        # Load terminology dictionary (product names, etc.)
        self.terminology_dict = set()
        if terminology_file and terminology_file.exists():
            with open(terminology_file, 'r', encoding='utf-8') as f:
                for line in f:
                    term = line.strip()
                    if term:
                        self.terminology_dict.add(term)

        # Default Aspose-specific terms
        self.terminology_dict.update({
            "Aspose.Slides", "Aspose.Cells", "Aspose.Words",
            "Aspose.PDF", "Aspose.Email", "Aspose.Imaging",
            "PowerPoint", "Excel", "Word",
            "API", "SDK", "JSON", "XML", "HTTP", "HTTPS",
            "SaveFormat.Pptx", "SaveFormat.Pdf",
            "LowCode", "C#", "Java", "Python",
        })

        # Initialize NLP model for NER (optional, lazy loaded)
        self._nlp = None

        # Batch statistics tracking
        self.batch_stats = {
            'total_batches': 0,
            'successful_batches': 0,
            'fallback_batches': 0,
            'mapping_failures': 0,
            'translation_errors': 0,
            'individual_translations': 0,
            'individual_translation_errors': 0,
            'empty_translations': 0,
        }

        # Load technical terms whitelist for language purity bypass (PO-01)
        self.technical_terms = self._load_technical_terms()

    def _load_extraction_config(self) -> dict:
        """
        Load extraction config from site profile with fallback to defaults.

        Returns:
            Dictionary with extraction configuration, or empty dict if not available.
        """
        def _normalize_section(section: Any, seen: Optional[set[int]] = None) -> Any:
            if seen is None:
                seen = set()

            obj_id = id(section)
            if obj_id in seen:
                return {}
            seen.add(obj_id)

            if isinstance(section, dict):
                return {k: _normalize_section(v, seen) for k, v in section.items()}
            if isinstance(section, (list, tuple)):
                return [_normalize_section(v, seen) for v in section]
            if hasattr(section, "model_dump") and callable(section.model_dump):
                try:
                    return _normalize_section(section.model_dump(), seen)
                except Exception:
                    pass
            if hasattr(section, "dict") and callable(section.dict):
                try:
                    return _normalize_section(section.dict(), seen)
                except Exception:
                    pass
            if hasattr(section, '__dict__'):
                module_name = section.__class__.__module__
                if module_name.startswith("unittest.mock"):
                    return {}
                return {k: _normalize_section(v, seen) for k, v in vars(section).items()}
            return section

        if self.site_profile:
            # Handle both dict and object attribute access
            if hasattr(self.site_profile, 'extraction'):
                extraction = self.site_profile.extraction
                return _normalize_section(extraction)
            elif isinstance(self.site_profile, dict):
                return _normalize_section(self.site_profile.get('extraction', {}))
        return {}

    def _validate_extraction_config(self):
        """
        Validate extraction configuration values.

        Raises:
            ValueError: If any configuration value is outside acceptable range.
        """
        # Validate language_purity_min_length
        if not (5 <= self.language_purity_min_length <= 100):
            raise ValueError(
                f"Invalid extraction config: language_purity.min_length must be "
                f"between 5 and 100, got {self.language_purity_min_length}"
            )

        if not (0.0 <= self.language_purity_min_script_ratio <= 1.0):
            raise ValueError(
                f"Invalid extraction config: language_purity.min_script_ratio must be "
                f"between 0.0 and 1.0, got {self.language_purity_min_script_ratio}"
            )

        # Validate fallback_rate_threshold
        if not (0.01 <= self.fallback_rate_threshold <= 0.5):
            raise ValueError(
                f"Invalid extraction config: batch_translation.fallback_rate_threshold must be "
                f"between 0.01 and 0.5, got {self.fallback_rate_threshold}"
            )

        # Validate token_per_word_estimate
        if not (0.5 <= self.token_per_word_estimate <= 3.0):
            raise ValueError(
                f"Invalid extraction config: batch_translation.token_per_word_estimate must be "
                f"between 0.5 and 3.0, got {self.token_per_word_estimate}"
            )

        # Validate script_similar_languages structure
        if not isinstance(self.script_similar_languages, dict):
            raise ValueError(
                f"Invalid extraction config: language_purity.script_similar_languages must be "
                f"a dictionary, got {type(self.script_similar_languages).__name__}"
            )

    def _load_technical_terms(self) -> set:
        """
        Load technical term whitelist from config.

        Technical terms often trigger false positive language detections
        (e.g., German text with "Aspose.Cells" detected as Dutch). Units
        with high technical term density (>30%) bypass language purity checks.

        Returns:
            Set of technical terms (case-sensitive)
        """
        from pathlib import Path
        import yaml

        config_path = Path("config/terminology/technical_terms.yaml")
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    terms = set(data.get('terms', []))
                    logger.info(f"Loaded {len(terms)} technical terms from {config_path}")
                    return terms
            except Exception as e:
                logger.warning(f"Failed to load technical terms from {config_path}: {e}")

        # Fallback to hardcoded defaults
        default_terms = {
            'C#', 'Aspose', 'Excel', 'HTML', 'PDF', '.NET',
            'NuGet', 'API', 'SDK', 'BarCode', 'PowerPoint'
        }
        logger.debug(f"Using {len(default_terms)} default technical terms")
        return default_terms

    def _calculate_technical_density(self, text: str) -> float:
        """
        Calculate proportion of technical terms in text.

        Supports multi-word technical terms (e.g., "Visual Studio", "Aspose.Cells").
        Uses greedy longest-match algorithm to handle overlapping terms correctly.

        Args:
            text: Translated text to analyze

        Returns:
            Float between 0.0 and 1.0 representing technical term density

        Example:
            text = "Visual Studio 2019 أو أحدث"
            terms = ["Visual Studio", "C#", "API"]
            → "Visual Studio" matches (2 words)
            → density = 2/5 = 0.40 (meets 25% threshold for bypass)
        """
        if not text:
            return 0.0

        words = text.split()
        if not words:
            return 0.0

        # Sort terms by word count (longest first) to handle overlaps correctly
        # Example: ["Visual Studio Code", "Visual Studio"] → match "Visual Studio Code" first
        sorted_terms = sorted(self.technical_terms, key=lambda t: len(t.split()), reverse=True)

        matched_word_count = 0
        text_lower = text.lower()  # Case-insensitive matching for better coverage

        for term in sorted_terms:
            term_word_count = len(term.split())
            # Count occurrences of this term in text
            occurrences = text_lower.count(term.lower())
            matched_word_count += occurrences * term_word_count

        # Calculate density, cap at 1.0 to handle overlapping matches
        density = min(matched_word_count / len(words), 1.0)

        # Debug logging for transparency
        if density > 0:
            logger.debug(
                f"Technical density: {density:.2f} ({matched_word_count}/{len(words)} words) "
                f"for text: {text[:50]}..."
            )

        return density

    def _get_translatable_frontmatter_fields(self):
        """Get translatable frontmatter fields from config or defaults."""
        if self.site_profile and hasattr(self.site_profile, 'frontmatter'):
            # Extract fields with mode='translate' or mode='translate_list'
            translatable = set()
            for field_name, field_rule in self.site_profile.frontmatter.items():
                # Handle both dict access and object attribute access
                if hasattr(field_rule, 'mode'):
                    mode = field_rule.mode
                elif isinstance(field_rule, dict):
                    mode = field_rule.get('mode', '')
                else:
                    continue

                if mode in ('translate', 'translate_list'):
                    translatable.add(field_name)

            if translatable:  # Only use if non-empty
                return translatable

        # Fallback to defaults
        return TRANSLATABLE_FRONTMATTER_FIELDS

    def _get_protected_frontmatter_fields(self):
        """Get protected frontmatter fields from config or defaults."""
        if self.site_profile and hasattr(self.site_profile, 'frontmatter'):
            # Extract fields with mode='passthrough'
            protected = set()
            for field_name, field_rule in self.site_profile.frontmatter.items():
                # Handle both dict access and object attribute access
                if hasattr(field_rule, 'mode'):
                    mode = field_rule.mode
                elif isinstance(field_rule, dict):
                    mode = field_rule.get('mode', '')
                else:
                    continue

                if mode == 'passthrough':
                    protected.add(field_name)

            if protected:  # Only use if non-empty
                return protected

        # Fallback to defaults
        return NON_TRANSLATABLE_FRONTMATTER_FIELDS

    def _extract_frontmatter_units(self, frontmatter_dict):
        """
        Extract translatable text units from frontmatter (FIX-BT-03).

        Extracts fields marked as translatable in configuration.
        Skips protected fields and non-string values.

        Args:
            frontmatter_dict: Dictionary containing YAML frontmatter

        Returns:
            List of TextUnit objects for translatable frontmatter fields
        """
        units = []

        if not frontmatter_dict:
            return units

        # Load configuration (site-specific)
        translatable = self._get_translatable_frontmatter_fields()
        protected = self._get_protected_frontmatter_fields()

        for field_name, field_value in frontmatter_dict.items():
            # Skip protected fields
            if field_name in protected:
                logger.debug(f"Skipping protected frontmatter field: {field_name}")
                continue

            # Skip if not in whitelist
            if translatable and field_name not in translatable:
                logger.debug(f"Skipping frontmatter field not in whitelist: {field_name}")
                continue

            # Handle string fields
            if isinstance(field_value, str) and field_value.strip():
                unit = TextUnit(
                    unit_id=TextUnit.create_id(f"frontmatter.{field_name}", field_value, TextUnitKind.TEXT),
                    node_addr=f"frontmatter.{field_name}",
                    kind=TextUnitKind.TEXT,
                    source_text=field_value,
                    metadata={'field_name': field_name, 'field_type': 'string'}
                )
                units.append(unit)
                logger.debug(f"Extracted frontmatter field '{field_name}': {field_value[:50]}")

            # Handle array fields (e.g., keywords)
            elif isinstance(field_value, list):
                for i, item in enumerate(field_value):
                    if isinstance(item, str) and item.strip():
                        unit = TextUnit(
                            unit_id=TextUnit.create_id(f"frontmatter.{field_name}[{i}]", item, TextUnitKind.TEXT),
                            node_addr=f"frontmatter.{field_name}[{i}]",
                            kind=TextUnitKind.TEXT,
                            source_text=item,
                            metadata={'field_name': field_name, 'field_type': 'array', 'index': i}
                        )
                        units.append(unit)
                        logger.debug(f"Extracted frontmatter array '{field_name}[{i}]': {item[:50]}")

        logger.info(f"Extracted {len(units)} frontmatter text units")
        return units

    def _apply_frontmatter_translations(self, frontmatter_dict, text_units):
        """
        Apply translations to frontmatter fields (FIX-BT-03).

        Args:
            frontmatter_dict: Dictionary frontmatter data
            text_units: List of translated TextUnit objects
        """
        if not frontmatter_dict:
            return

        applied_count = 0
        for unit in text_units:
            if not unit.translated_text:
                logger.warning(f"Frontmatter unit has no translation: {unit.metadata}")
                continue

            field_name = unit.metadata.get('field_name')
            field_type = unit.metadata.get('field_type')

            if field_type == 'string':
                # Simple string field
                frontmatter_dict[field_name] = unit.translated_text
                logger.debug(f"Applied translation to frontmatter field '{field_name}'")
                applied_count += 1

            elif field_type == 'array':
                # Array item
                index = unit.metadata.get('index')
                if field_name in frontmatter_dict:
                    if isinstance(frontmatter_dict[field_name], list):
                        if index < len(frontmatter_dict[field_name]):
                            frontmatter_dict[field_name][index] = unit.translated_text
                            logger.debug(f"Applied translation to frontmatter array '{field_name}[{index}]'")
                            applied_count += 1

        logger.info(f"Applied {applied_count} frontmatter translations")

    def _estimate_token_count(self, text: str) -> int:
        """
        Estimate token count for text.

        Uses simple heuristic: ~1.3 tokens per word for English/European languages.
        This is conservative for M2M100.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        word_count = len(text.split())
        # M2M100 tokenization ratio: typically 1.2-1.5 tokens per word
        # Use configured estimate (default: 1.3)
        return int(word_count * self.token_per_word_estimate)

    def _yield_safe_batches(
        self,
        units: List[TextUnit],
        max_units: int,
        max_tokens: int
    ) -> List[List[TextUnit]]:
        """
        Split units into batches respecting both unit count and token limits.

        This prevents context window overflow by ensuring batches stay within
        model capacity limits.

        Args:
            units: TextUnits to batch
            max_units: Maximum units per batch (hard limit)
            max_tokens: Maximum estimated tokens per batch

        Returns:
            List of batches, each batch is List[TextUnit]

        Example:
            units = [unit1, unit2, ...]  # 91 units total
            batches = _yield_safe_batches(units, max_units=20, max_tokens=512)
            # Result: ~5 batches of 18-20 units each, all under 512 tokens
        """
        batches = []
        current_batch = []
        current_token_estimate = 0

        for unit in units:
            # Estimate tokens for this unit
            unit_tokens = self._estimate_token_count(unit.source_text)

            # Check if adding this unit would exceed limits
            would_exceed_tokens = (current_token_estimate + unit_tokens > max_tokens)
            would_exceed_units = (len(current_batch) >= max_units)

            if current_batch and (would_exceed_tokens or would_exceed_units):
                # Save current batch and start new one
                batches.append(current_batch)
                logger.debug(
                    f"Batch {len(batches)} complete: "
                    f"{len(current_batch)} units, ~{current_token_estimate} tokens"
                )
                current_batch = [unit]
                current_token_estimate = unit_tokens
            else:
                # Add to current batch
                current_batch.append(unit)
                current_token_estimate += unit_tokens

        # Add final batch
        if current_batch:
            batches.append(current_batch)
            logger.debug(
                f"Batch {len(batches)} complete: "
                f"{len(current_batch)} units, ~{current_token_estimate} tokens"
            )

        # Log summary
        if batches:
            total_units = sum(len(b) for b in batches)
            avg_units = total_units / len(batches)
            logger.info(
                f"Split {total_units} units into {len(batches)} batches "
                f"(avg {avg_units:.1f} units/batch, "
                f"max {max_units} units or {max_tokens} tokens per batch)"
            )

        return batches

    def _fallback_to_individual(
        self,
        batch: List[TextUnit],
        mt_model: Any,
        src_lang: str,
        tgt_lang: str
    ):
        """
        Fallback: translate each unit individually.

        This is slower but guaranteed to work correctly.
        Called when batch translation fails validation.

        Args:
            batch: TextUnits to translate
            mt_model: Translation model
            src_lang: Source language code
            tgt_lang: Target language code
        """
        logger.info(f"Translating {len(batch)} units individually (fallback mode)")

        for unit in batch:
            try:
                results = mt_model.translate([unit.source_text], src_lang, tgt_lang)
                if results and results[0]:
                    unit.translated_text = results[0].strip()
                    if unit.translated_text == "":
                        self.batch_stats['individual_translation_errors'] += 1
                else:
                    self.batch_stats['individual_translation_errors'] += 1
                    unit.translated_text = ""
            except Exception as e:
                logger.error(f"Individual translation failed for unit: {e}")
                self.batch_stats['individual_translation_errors'] += 1
                unit.translated_text = ""

        self.batch_stats['individual_translations'] = \
            self.batch_stats.get('individual_translations', 0) + len(batch)

    def _translate_single_batch(
        self,
        batch: List[TextUnit],
        mt_model: Any,
        src_lang: str,
        tgt_lang: str
    ) -> bool:
        """
        Translate a single batch using native list-based batching.

        Returns True if batch translation succeeded, False if fell back to individual.

        This uses the model's native batching capability by sending a list of texts
        and receiving a list of translations, ensuring 1:1 mapping is preserved
        automatically without any delimiter manipulation.

        Args:
            batch: TextUnits to translate in this batch
            mt_model: Translation model
            src_lang: Source language code
            tgt_lang: Target language code

        Returns:
            True if batch translation succeeded, False if fell back to individual
        """
        batch_count = len(batch)

        # Build list of source texts (native batching - no delimiters!)
        batch_texts = [u.source_text for u in batch]

        # TRANSLATION: Send list to model (model handles batching internally)
        try:
            translations = mt_model.translate(batch_texts, src_lang, tgt_lang)

            if not translations:
                logger.warning("Translation returned empty result. Falling back.")
                self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)
                return False

            # VALIDATION: Verify 1:1 mapping preserved
            if len(translations) != batch_count:
                logger.warning(
                    f"MAPPING VALIDATION FAILED: Expected {batch_count} translations, "
                    f"got {len(translations)}. Falling back to individual translation."
                )
                self.batch_stats['mapping_failures'] += 1
                self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)
                return False

        except Exception as e:
            logger.error(f"TRANSLATION ERROR: {e}. Falling back to individual translation.")
            self.batch_stats['translation_errors'] = self.batch_stats.get('translation_errors', 0) + 1
            self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)
            return False

        # SUCCESS: Apply translations (perfect 1:1 mapping)
        for unit, translation in zip(batch, translations):
            unit.translated_text = translation.strip()

        # LANGUAGE PURITY CHECK: Verify all translations are in target language
        if not self._verify_translation_language_purity(batch, tgt_lang):
            logger.warning(
                f"LANGUAGE PURITY CHECK FAILED: Batch produced mixed-language output. "
                f"Re-translating {batch_count} units individually to ensure language purity."
            )
            self.batch_stats['language_purity_failures'] = self.batch_stats.get('language_purity_failures', 0) + 1
            self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)
            return False

        self.batch_stats['successful_batches'] += 1
        logger.debug(f"Batch translation successful ({batch_count} units)")

        return True

    def _log_batch_statistics(self):
        """Log comprehensive batch translation statistics."""
        stats = self.batch_stats
        total = stats['total_batches']

        if total == 0:
            return

        success_rate = (stats['successful_batches'] / total) * 100
        fallback_rate = (stats['fallback_batches'] / total) * 100

        logger.info(
            f"\n"
            f"=== Batch Translation Statistics ===\n"
            f"Total batches:             {total}\n"
            f"Successful:                {stats['successful_batches']} ({success_rate:.1f}%)\n"
            f"Fallback:                  {stats['fallback_batches']} ({fallback_rate:.1f}%)\n"
            f"  - Mapping failures:      {stats.get('mapping_failures', 0)}\n"
            f"  - Language purity:       {stats.get('language_purity_failures', 0)}\n"
            f"  - Translation errors:    {stats.get('translation_errors', 0)}\n"
            f"Individual translations:   {stats.get('individual_translations', 0)}\n"
            f"Fallback rate:             {fallback_rate:.1f}%\n"
            f"===================================="
        )

    def _verify_translation_language_purity(
        self, units: List[TextUnit], target_lang: str
    ) -> bool:
        """
        Verify all translated units are in target language.

        Uses langdetect to check each translated unit. Skips very short texts
        as they may not have enough content for reliable detection.

        PO-01: Units with high technical term density (>30%) bypass this check
        to prevent false positives from technical content.

        Args:
            units: List of TextUnits with translated_text populated
            target_lang: Expected target language code (e.g., 'de', 'fr')

        Returns:
            True if all units pass language check, False if any fail
        """
        try:
            import langdetect
            from langdetect import DetectorFactory

            # Set seed for reproducible detection
            DetectorFactory.seed = 0
        except ImportError:
            logger.warning(
                "langdetect not available, skipping language purity check. "
                "Install with: pip install langdetect"
            )
            return True

        failed_units = []
        bypassed_count = 0
        script_override_count = 0

        for unit in units:
            if unit.do_not_translate:
                continue

            translated = unit.translated_text
            if not translated or len(translated.strip()) < self.language_purity_min_length:
                # Skip very short texts (unreliable for language detection)
                continue

            # PO-01: Bypass purity check for high-density technical content
            density = self._calculate_technical_density(translated)
            if density >= 0.25:  # 25% threshold (tuned for Aspose technical docs)
                logger.debug(
                    f"Bypassing purity check (technical density={density:.2f}): "
                    f"{translated[:50]}..."
                )
                bypassed_count += 1
                continue

            try:
                detected = langdetect.detect(translated)
                # Check if detected language matches target or is script-similar
                script_similar = self.script_similar_languages.get(target_lang, set())
                if detected != target_lang and detected not in script_similar:
                    script_ratio = self._target_script_ratio(translated, target_lang)
                    if script_ratio >= self.language_purity_min_script_ratio:
                        logger.debug(
                            f"Accepting target-script ratio override (ratio={script_ratio:.2f}): "
                            f"detected={detected}, target={target_lang}, text={translated[:50]}..."
                        )
                        script_override_count += 1
                        continue
                    failed_units.append({
                        'text': translated[:60] + "..." if len(translated) > 60 else translated,
                        'expected': target_lang,
                        'detected': detected
                    })
                elif detected in script_similar:
                    # Log script-similar detection for monitoring
                    logger.debug(
                        f"Accepting script-similar language: detected={detected}, "
                        f"target={target_lang}, text={translated[:50]}..."
                    )
            except langdetect.lang_detect_exception.LangDetectException:
                # Skip texts that can't be detected (often technical content)
                pass

        if bypassed_count > 0:
            logger.info(
                f"Bypassed purity check for {bypassed_count} high-density technical units "
                f"(>=25% technical terms)"
            )

        if script_override_count > 0:
            logger.debug(
                f"Accepted {script_override_count} units based on target-script ratio "
                f"(>= {self.language_purity_min_script_ratio:.2f})"
            )

        if failed_units:
            logger.error(
                f"Language purity check FAILED: {len(failed_units)} units have wrong language. "
                f"Examples: {failed_units[:3]}"
            )
            return False

        logger.info(f"Language purity check passed for {len(units)} units")
        return True

    def _target_script_ratio(self, text: str, target_lang: str) -> float:
        """Compute ratio of target-script letters among all letters in text."""
        if not text:
            return 0.0

        pattern = TARGET_SCRIPT_REGEX.get(target_lang)
        if not pattern:
            return 0.0

        letter_count = sum(1 for ch in text if ch.isalpha())
        if letter_count == 0:
            return 0.0

        script_count = len(pattern.findall(text))
        return script_count / letter_count

    def extract_from_ast(self, ast: List[ASTNode], frontmatter: Optional[Dict[str, Any]] = None) -> BodyTranslationPlan:
        """
        Extract all translatable TextUnits from AST and frontmatter.

        Args:
            ast: List of root ASTNode objects (document body)
            frontmatter: Optional frontmatter dictionary (FIX-BT-03)

        Returns:
            BodyTranslationPlan with units and AST reference
        """
        units: List[TextUnit] = []

        # Extract frontmatter fields (FIX-BT-03)
        if frontmatter:
            frontmatter_units = self._extract_frontmatter_units(frontmatter)
            units.extend(frontmatter_units)
            logger.info(f"Extracted {len(frontmatter_units)} frontmatter units")

        # Traverse each root node
        for node in ast:
            self._traverse_node(node, units)

        # Calculate AST fingerprint for sanity checks
        ast_fingerprint = self._calculate_ast_fingerprint(ast)

        return BodyTranslationPlan(
            ast=ast,
            units=units,
            ast_fingerprint=ast_fingerprint,
            metadata={
                'segmentation_strategy': self.segmentation_strategy,
                'total_units': len(units),
                'translatable_units': len([u for u in units if not u.do_not_translate]),
                'frontmatter_units': len([u for u in units if u.node_addr and u.node_addr.startswith('frontmatter.')])
            }
        )

    def _traverse_node(self, node: ASTNode, units: List[TextUnit]) -> None:
        """
        Recursively traverse node and emit TextUnits.

        Args:
            node: ASTNode to traverse
            units: List to append TextUnits to (mutated in place)
        """
        # Handle different node types
        if node.type == NodeType.TEXT:
            # Extract text with whitespace separation
            self._extract_text_node(node, units)

        elif node.type == NodeType.CODE_SPAN:
            # Code spans are not translated (protected)
            self._extract_code_span(node, units)

        elif node.type == NodeType.CODE_BLOCK:
            # Code blocks are not translated (protected)
            self._extract_code_block(node, units)

        elif node.type == NodeType.LINK:
            # Extract link text but preserve URL
            self._extract_link(node, units)

        elif node.type == NodeType.IMAGE:
            # Extract alt text but preserve src
            self._extract_image(node, units)

        elif node.type in (NodeType.HEADING, NodeType.PARAGRAPH, NodeType.LIST_ITEM,
                          NodeType.BLOCKQUOTE, NodeType.TABLE_CELL):
            # Container nodes: check segmentation strategy
            if self._should_extract_full_sentence(node):
                # Extract full content as single unit
                self._extract_full_sentence(node, units)
            else:
                # Extract children individually (leaf-level)
                for child in node.children:
                    self._traverse_node(child, units)

        else:
            # Other containers: traverse children
            for child in node.children:
                self._traverse_node(child, units)

    def _extract_text_node(self, node: ASTNode, units: List[TextUnit]) -> None:
        """Extract text node with whitespace preservation."""
        if not node.raw:
            return

        # Skip nodes without addresses - they cannot be reliably tracked
        if not node.node_addr:
            logger.debug(
                "Skipping text node without address: type=%s, raw_preview=%s",
                node.type.value if node.type else "unknown",
                (node.raw[:50] + "...") if node.raw and len(node.raw) > 50 else node.raw
            )
            return

        text = node.raw

        # Separate whitespace
        prefix_ws = ""
        suffix_ws = ""
        stripped_text = text.strip()

        if stripped_text:
            # Find prefix whitespace
            prefix_match = re.match(r'^(\s*)', text)
            if prefix_match:
                prefix_ws = prefix_match.group(1)

            # Find suffix whitespace
            suffix_match = re.search(r'(\s*)$', text)
            if suffix_match:
                suffix_ws = suffix_match.group(1)
        else:
            # Empty or whitespace-only text
            prefix_ws = text

        # Check if non-translatable FIRST (before applying placeholders)
        # This ensures heuristic patterns can match original text like "Aspose.Words"
        do_not_translate = self._is_non_translatable(stripped_text)

        # Apply preserve_patterns protection (if configured and not already protected)
        placeholder_map = {}
        protected_text = stripped_text
        if self.placeholder_manager and stripped_text and not do_not_translate:
            logger.debug(f"[DEBUG] Applying protection to: '{stripped_text[:60]}...'")
            protected_text, placeholder_map = self.placeholder_manager.protect(
                stripped_text, self.preserve_patterns
            )
            if placeholder_map:
                logger.info(f"[DEBUG] Protected {len(placeholder_map)} instances in '{stripped_text[:40]}...'")
                for placeholder, original in placeholder_map.items():
                    logger.debug(f"[DEBUG]   {placeholder} -> '{original}'")

        # Create TextUnit with protected text and placeholder map
        unit = TextUnit(
            unit_id=TextUnit.create_id(node.node_addr, protected_text, TextUnitKind.TEXT),
            node_addr=node.node_addr,
            kind=TextUnitKind.TEXT,
            source_text=protected_text,
            prefix_ws=prefix_ws,
            suffix_ws=suffix_ws,
            do_not_translate=do_not_translate,
            metadata={'placeholder_map': placeholder_map} if placeholder_map else {}
        )
        logger.debug(f"[DEBUG] Created TextUnit: do_not_translate={do_not_translate}, source='{protected_text[:50]}...'")
        units.append(unit)

    def _extract_code_span(self, node: ASTNode, units: List[TextUnit]) -> None:
        """Extract code span as non-translatable."""
        if not node.raw:
            return

        # Skip nodes without addresses - they cannot be reliably tracked
        if not node.node_addr:
            logger.debug(
                "Skipping code span without address: raw_preview=%s",
                (node.raw[:30] + "...") if len(node.raw) > 30 else node.raw
            )
            return

        unit = TextUnit(
            unit_id=TextUnit.create_id(node.node_addr, node.raw, TextUnitKind.CODE_SPAN),
            node_addr=node.node_addr,
            kind=TextUnitKind.CODE_SPAN,
            source_text=node.raw,
            do_not_translate=True  # Code is NEVER translated
        )
        units.append(unit)

    def _extract_code_block(self, node: ASTNode, units: List[TextUnit]) -> None:
        """Extract code block as non-translatable."""
        if not node.raw:
            return

        # Skip nodes without addresses - they cannot be reliably tracked
        if not node.node_addr:
            logger.debug(
                "Skipping code block without address: lang=%s, lines=%d",
                node.attrs.get("language", "none") if node.attrs else "none",
                node.raw.count("\n") + 1
            )
            return

        # Note: Using CODE_SPAN kind for now (could add CODE_BLOCK to TextUnitKind if needed)
        unit = TextUnit(
            unit_id=TextUnit.create_id(node.node_addr, node.raw, TextUnitKind.CODE_SPAN),
            node_addr=node.node_addr,
            kind=TextUnitKind.CODE_SPAN,
            source_text=node.raw,
            do_not_translate=True  # Code is NEVER translated
        )
        units.append(unit)

    def _extract_link(self, node: ASTNode, units: List[TextUnit]) -> None:
        """Extract link text content (not URL)."""
        # Traverse children for link text
        for child in node.children:
            if child.type == NodeType.TEXT:
                # Extract as LINK_TEXT
                text = child.raw.strip() if child.raw else ""
                if text:
                    unit = TextUnit(
                        unit_id=TextUnit.create_id(child.node_addr, text, TextUnitKind.LINK_TEXT),
                        node_addr=child.node_addr,
                        kind=TextUnitKind.LINK_TEXT,
                        source_text=text,
                        do_not_translate=self._is_non_translatable(text)
                    )
                    units.append(unit)
            else:
                # Nested formatting in link (e.g., bold in link)
                self._traverse_node(child, units)

        # URL is stored in node.attrs['url'] - preserved, not extracted

    def _extract_image(self, node: ASTNode, units: List[TextUnit]) -> None:
        """Extract image alt text (not src)."""
        alt_text = node.attrs.get('alt', '').strip()
        if alt_text:
            unit = TextUnit(
                unit_id=TextUnit.create_id(node.node_addr, alt_text, TextUnitKind.IMAGE_ALT),
                node_addr=node.node_addr,
                kind=TextUnitKind.IMAGE_ALT,
                source_text=alt_text,
                do_not_translate=self._is_non_translatable(alt_text)
            )
            units.append(unit)

        # src is stored in node.attrs['src'] - preserved, not extracted

    def _extract_full_sentence(self, node: ASTNode, units: List[TextUnit]) -> None:
        """Extract entire node content as single translatable unit."""
        # Collect all text from children
        full_text = self._collect_text_from_node(node)

        if not full_text.strip():
            return

        # Determine kind based on node type
        kind_map = {
            NodeType.HEADING: TextUnitKind.HEADING_TEXT,
            NodeType.BLOCKQUOTE: TextUnitKind.BLOCKQUOTE_TEXT,
            NodeType.LIST_ITEM: TextUnitKind.LIST_ITEM_TEXT,
            NodeType.TABLE_CELL: TextUnitKind.TABLE_CELL_TEXT,
            NodeType.PARAGRAPH: TextUnitKind.TEXT,
        }
        kind = kind_map.get(node.type, TextUnitKind.TEXT)

        # Separate whitespace
        prefix_ws = ""
        suffix_ws = ""
        stripped_text = full_text.strip()

        if stripped_text:
            prefix_match = re.match(r'^(\s*)', full_text)
            if prefix_match:
                prefix_ws = prefix_match.group(1)

            suffix_match = re.search(r'(\s*)$', full_text)
            if suffix_match:
                suffix_ws = suffix_match.group(1)

        # Check if non-translatable FIRST (before applying placeholders)
        do_not_translate = self._is_non_translatable(stripped_text)

        # Apply preserve_patterns protection (if configured and not already protected)
        placeholder_map = {}
        protected_text = stripped_text
        if self.placeholder_manager and stripped_text and not do_not_translate:
            logger.debug(f"[DEBUG] Applying protection to full sentence: '{stripped_text[:60]}...'")
            protected_text, placeholder_map = self.placeholder_manager.protect(
                stripped_text, self.preserve_patterns
            )
            if placeholder_map:
                logger.info(f"[DEBUG] Protected {len(placeholder_map)} instances in full sentence '{stripped_text[:40]}...'")
                for placeholder, original in placeholder_map.items():
                    logger.debug(f"[DEBUG]   {placeholder} -> '{original}'")

        unit = TextUnit(
            unit_id=TextUnit.create_id(node.node_addr, protected_text, kind),
            node_addr=node.node_addr,
            kind=kind,
            source_text=protected_text,
            prefix_ws=prefix_ws,
            suffix_ws=suffix_ws,
            do_not_translate=do_not_translate,
            metadata={'placeholder_map': placeholder_map} if placeholder_map else {}
        )
        logger.debug(f"[DEBUG] Created full sentence TextUnit: do_not_translate={do_not_translate}, source='{protected_text[:50]}...'")
        units.append(unit)

    def _collect_text_from_node(self, node: ASTNode) -> str:
        """Recursively collect all text from node and children."""
        if node.type == NodeType.TEXT:
            return node.raw or ""

        text_parts = []
        for child in node.children:
            text_parts.append(self._collect_text_from_node(child))

        return "".join(text_parts)

    def _should_extract_full_sentence(self, node: ASTNode) -> bool:
        """
        Determine if node should be extracted as full sentence (adaptive mode).

        Returns True for plain text paragraphs without inline formatting.
        """
        if self.segmentation_strategy == "leaf_only":
            return False
        elif self.segmentation_strategy == "sentence_only":
            return True
        elif self.segmentation_strategy == "adaptive":
            # Extract full sentence if:
            # 1. No inline formatting (bold, italic, links, etc.)
            # 2. No technical content (code, URLs)
            # Otherwise, use leaf-level extraction for safety
            has_formatting = self._has_inline_formatting(node)
            has_technical = self._has_technical_content(node)

            return not has_formatting and not has_technical
        else:
            # Default to leaf_only for unknown strategies
            logger.warning(f"Unknown segmentation strategy: {self.segmentation_strategy}, using leaf_only")
            return False

    def _has_inline_formatting(self, node: ASTNode) -> bool:
        """Check if node contains inline formatting (strong/em/link/etc.)."""
        formatting_types = {
            NodeType.STRONG, NodeType.EMPHASIS, NodeType.CODE_SPAN,
            NodeType.LINK, NodeType.IMAGE
        }

        # Check children
        for child in node.children:
            if child.type in formatting_types:
                return True
            # Recursively check nested children
            if self._has_inline_formatting(child):
                return True

        return False

    def _has_technical_content(self, node: ASTNode) -> bool:
        """Check if node contains code, URLs, or technical identifiers."""
        # Check for code nodes
        for child in node.children:
            if child.type in (NodeType.CODE_SPAN, NodeType.CODE_BLOCK):
                return True

            # Check for links (URLs are technical)
            if child.type == NodeType.LINK:
                return True

            # Check text for technical patterns
            if child.type == NodeType.TEXT and child.raw:
                text = child.raw.strip()
                if self._is_technical_identifier(text):
                    return True

            # Recursively check nested children
            if self._has_technical_content(child):
                return True

        return False

    def _is_non_translatable(self, text: str) -> bool:
        """
        Detect non-translatable content using multiple strategies.

        Returns True if text should NOT be translated (product names, technical IDs, etc.)

        Strategies:
        0. Hugo shortcodes ({{< >}}, {{% %}})
        1. NER-based detection (requires spaCy)
        2. Heuristic-based detection (CamelCase, snake_case, etc.)
        3. Terminology dictionary
        """
        text_stripped = text.strip()
        if not text_stripped:
            return False

        # Strategy 0: Hugo shortcodes - NEVER translate
        # Patterns: {{% steps %}}, {{< ref >}}, {{% /steps %}}, etc.
        if re.match(r'^\{\{[%<].*?[%>]\}\}$', text_stripped):
            logger.debug(f"Hugo shortcode detected (protected): {text_stripped}")
            return True

        # Strategy 1: NER-based detection (requires spaCy)
        try:
            import spacy
            if self._nlp is None:
                try:
                    self._nlp = spacy.load("en_core_web_sm")
                except OSError:
                    # Model not available, disable NER
                    self._nlp = False
                    logger.info("spaCy model not available, disabling NER detection")

            if self._nlp:
                doc = self._nlp(text_stripped)
                for ent in doc.ents:
                    if ent.label_ in ["PRODUCT", "ORG"]:
                        # Detected product name or organization
                        logger.debug(f"NER detected {ent.label_}: {text_stripped}")
                        return True
        except ImportError:
            # spaCy not available, skip NER detection
            pass

        # Strategy 2: Heuristic-based detection
        if self._is_technical_identifier(text_stripped):
            return True

        # Strategy 3: Terminology dictionary
        if text_stripped in self.terminology_dict:
            logger.debug(f"Terminology match: {text_stripped}")
            return True

        return False

    def _is_technical_identifier(self, text: str) -> bool:
        """
        Check if text matches technical identifier patterns.

        Patterns:
        - CamelCase: AsposeSlidesLowCode
        - PascalCase.With.Dots: Aspose.Slides.LowCode
        - snake_case: aspose_slides_low_code
        - ALL_CAPS: API, SDK, URL
        - Version numbers: v1.2.3, 2.0.1, 1.0+
        """
        # CamelCase: Starts with capital, has lowercase, then capital
        if re.match(r'^[A-Z][a-z]+(?:[A-Z][a-z]+)+$', text):
            return True

        # PascalCase.With.Dots
        if re.match(r'^[A-Z][a-z]+\.[A-Z]', text):
            return True

        # snake_case (lowercase with underscores)
        if '_' in text and text.islower():
            return True

        # ALL_CAPS (2+ characters)
        if text.isupper() and len(text) > 1:
            return True

        # Version numbers: v1.2, 1.2.3, 2.0+
        if re.match(r'^v?\d+\.?\d*[\.\+\-]?', text):
            return True

        return False

    def batch_translate_units(
        self,
        units: List[TextUnit],
        mt_model: Any,
        src_lang: str,
        tgt_lang: str,
        batch_size: int = 20,
        max_tokens_per_batch: int = 512
    ) -> List[TextUnit]:
        """
        Batch translate multiple TextUnits using native list-based batching.

        This implementation uses the model's native batch translation capability:
        - Send list of texts, receive list of translations
        - Perfect 1:1 mapping preserved automatically
        - No delimiters needed (eliminates corruption issues)
        - Dynamic batch sizing based on token count
        - Automatic fallback to individual translation if issues occur

        Args:
            units: List of TextUnits to translate
            mt_model: M2M100 model instance
            src_lang: Source language code
            tgt_lang: Target language code
            batch_size: Maximum units per batch (hard limit, default: 20)
            max_tokens_per_batch: Maximum estimated tokens per batch (default: 512)

        Returns:
            Units with translated_text populated
        """
        # Separate translatable from non-translatable
        translatable = [u for u in units if not u.do_not_translate]
        non_translatable = [u for u in units if u.do_not_translate]

        # Non-translatable: copy source to translated (NEVER sent to MT)
        for unit in non_translatable:
            unit.translated_text = unit.source_text

        if not translatable:
            return units

        # Dynamic batch sizing
        batches = self._yield_safe_batches(
            translatable,
            max_units=batch_size,
            max_tokens=max_tokens_per_batch
        )

        # Translate each batch
        for batch_num, batch in enumerate(batches, 1):
            logger.info(
                f"Translating batch {batch_num}/{len(batches)}: "
                f"{len(batch)} units, "
                f"~{sum(self._estimate_token_count(u.source_text) for u in batch)} tokens"
            )

            # Use native batch translation (no delimiters!)
            if batch:
                self.batch_stats['total_batches'] += 1

                # Translate using native list-based batching
                try:
                    success = self._translate_single_batch(
                        batch, mt_model, src_lang, tgt_lang
                    )
                    if not success:
                        # Fallback occurred, counted internally
                        self.batch_stats['fallback_batches'] += 1
                except Exception as e:
                    # EXCEPTION: Any error during batch processing
                    logger.error(f"Batch translation error in batch {batch_num}: {e}")
                    self.batch_stats['fallback_batches'] += 1
                    self.batch_stats['translation_errors'] += 1
                    # Fallback to individual translation
                    self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)

        # Log comprehensive statistics
        self._log_batch_statistics()

        empty_units = [
            u for u in translatable
            if not u.translated_text or u.translated_text.strip() == ""
        ]
        if empty_units:
            self.batch_stats['empty_translations'] = len(empty_units)
            samples = [u.node_addr or u.unit_id for u in empty_units[:3]]
            logger.error(
                f"Empty translations detected for {len(empty_units)} units. "
                f"Samples: {samples}"
            )

        # Alert if fallback rate exceeds threshold
        fallback_rate = self.batch_stats['fallback_batches'] / max(self.batch_stats['total_batches'], 1)
        if fallback_rate > self.fallback_rate_threshold:
            self._alert_high_fallback_rate(fallback_rate)

        return units

    def _calculate_ast_fingerprint(self, ast: List[ASTNode]) -> str:
        """Calculate fingerprint of AST structure for sanity checks."""
        def node_signature(node: ASTNode) -> str:
            """Get structural signature of node (type + children count)."""
            child_sigs = [node_signature(child) for child in node.children]
            return f"{node.type.value}({len(node.children)})[{','.join(child_sigs)}]"

        ast_sig = ",".join([node_signature(node) for node in ast])
        return hashlib.sha256(ast_sig.encode('utf-8')).hexdigest()[:16]

    def _alert_high_fallback_rate(self, fallback_rate: float):
        """Alert if fallback rate exceeds acceptable threshold."""
        logger.warning(
            f"HIGH FALLBACK RATE DETECTED: {fallback_rate:.1%} of batches falling back to individual translation. "
            f"Stats: {self.batch_stats}. Consider reducing batch_size or investigating mapping/purity issues."
        )
