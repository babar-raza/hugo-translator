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
from typing import Any

from src.utils.log_sanitizer import sanitize_for_log

from ..parser.ast_nodes import ASTNode, NodeType
from ..terminology.classification import (
    VERDICT_TABLE,
    categories_for_kind,
    classify,
    get_default_protected_terms,
    get_default_registry,
    is_translate_eligible,
)
from .text_unit import BodyTranslationPlan, TextUnit, TextUnitKind

logger = logging.getLogger(__name__)


def _normalize_lang_code(code: str) -> str:
    """Normalize language codes to base ISO 639-1 for skip-list matching."""
    code = code.lower().strip()
    _VARIANTS = {
        "nb": "no",
        "nn": "no",
        "zh-cn": "zh",
        "zh-tw": "zh",
        "zh-hk": "zh",
        "pt-br": "pt",
        "pt-pt": "pt",
        "en-us": "en",
        "en-gb": "en",
    }
    if code in _VARIANTS:
        return _VARIANTS[code]
    if "-" in code:
        return code.split("-")[0]
    return code


# Batch translation tuning constants
LANGUAGE_PURITY_MIN_LENGTH = 15  # Minimum text length for reliable language detection
LANGUAGE_PURITY_MIN_SCRIPT_RATIO = 0.4  # Minimum target-script ratio to accept mixed-script text
FALLBACK_RATE_THRESHOLD = 0.05  # Alert threshold for fallback rate (5%)
TOKEN_PER_WORD_ESTIMATE = 1.3  # Average tokens per word for M2M100 estimation

# Circuit breaker constants (TC-03, plan: validated-mixing-biscuit)
# Fires when run-level purity failure rate exceeds threshold after min batches.
# Threshold ≤ 67.7% to catch Serbian (the lower of the two known-failing languages).
# 50 min_batches provides statistical stability before aborting.
CIRCUIT_BREAKER_MIN_BATCHES = 50
CIRCUIT_BREAKER_THRESHOLD = 0.50


class LanguagePurityCircuitBreakerError(RuntimeError):
    """Raised when run-level purity failure rate is catastrophic.

    Aborts the language run to stop wasted compute. Use
    translation_engine.language_routing_overrides in global.yaml to route
    the affected language to a capable model.
    """


# DEPRECATED: Use SimilarityTracker baseline_groups in global.yaml instead.
# This is kept for backward compatibility with older site profiles.
# Script-similar languages that may be confused by langdetect
# Languages that share the same script often get misdetected
SCRIPT_SIMILAR_LANGUAGES = {
    "ar": {
        "fa",
        "it",
        "es",
        "fr",
        "pt",
    },  # Arabic <-> Farsi (same script) + Romance languages (Latin script terms trigger false positives)
    "fa": {"ar"},  # Farsi/Persian <-> Arabic
    "sr": {
        "hr",
        "bs",
    },  # Serbian Latin ≈ Croatian/Bosnian: LLM produces Latin-script Serbian; FastText classifies it as 'hr'. Linguistically identical at text level (TC-06, plan: validated-mixing-biscuit).
    # Add more script-similar pairs as needed:
    # 'hi': {'ne', 'mr'},  # Hindi, Nepali, Marathi all use Devanagari
}

# Script ranges for target-language ratio checks
ARABIC_SCRIPT_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)
TARGET_SCRIPT_REGEX = {
    "ar": ARABIC_SCRIPT_RE,
    "fa": ARABIC_SCRIPT_RE,
    "ur": ARABIC_SCRIPT_RE,
    "ps": ARABIC_SCRIPT_RE,
}

# Frontmatter translation configuration (FIX-BT-03)
TRANSLATABLE_FRONTMATTER_FIELDS = {
    "title",
    "description",
    "keywords",
    "step1",
    "step2",
    "step3",
    "step4",
    "step5",
}

NON_TRANSLATABLE_FRONTMATTER_FIELDS = {
    "slug",
    "productname",
    "productkey",
    "platformkey",
    "productplatform",
    "date",
    "lastmod",
    "weight",
    "draft",
    "type",
}


def is_family_platform_index(
    file_path: Any, source_lang: str = "en", include_family_root: bool = False
) -> bool:
    """True for {source_lang}/{family}/{platform}/_index.md paths.

    These are product/platform index pages (e.g. docs.aspose.org's
    slides/cpp/_index.md) whose title must stay identical to the English
    source across every locale, unlike leaf content pages under the same
    family/platform which legitimately translate their titles.

    HT-QUALITY-GATES-001: `include_family_root=True` ALSO matches
    {source_lang}/{family}/_index.md (2-level, no platform segment) — e.g.
    products.aspose.org's `psd/_index.md`, one of the 15 root-only families
    with no platform sub-pages at all. Confirmed by direct audit that these
    family-root titles have the exact same byte-identical-to-EN requirement
    (the audit's most severe single finding, a Serbian title corrupted to
    "Смрт"/"Death", was on exactly this page shape). Defaults to False
    (the original, narrower behavior) because this function is shared
    across sites (docs.aspose.org, kb.aspose.org, ...) this session has not
    audited — callers that have confirmed the broader requirement for their
    site must opt in explicitly rather than this changing silently
    everywhere.
    """
    if not file_path:
        return False
    parts = Path(file_path).parts
    if source_lang not in parts:
        return False
    idx = len(parts) - 1 - parts[::-1].index(source_lang)
    remainder = parts[idx + 1 :]
    if remainder and remainder[-1] != "_index.md":
        return False
    if len(remainder) == 3:
        return True
    if len(remainder) == 2 and include_family_root:
        return True
    return False

# reference-i18n-hardening-20260725: the hardcoded _API_HEADING_TERMS /
# _ALWAYS_TRANSLATE_WORDS frozensets that lived here were retired — the
# always-translate override in _is_non_translatable now reads the i18n
# template-string registry via classification.is_translate_eligible(), with
# kind-scoped categories so table Access-column values (Read/Write/Execute/
# Create/Delete/Update — all real method names too) are only eligible in
# table-cell context, never as headings.

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


def analyze_segment_variance(segments: list[str]) -> dict[str, Any]:
    """
    Analyze segment length distribution for batch optimization.

    Calculates variance and standard deviation to determine if batch size
    should be reduced for segments with high length variability.

    Args:
        segments: List of text segments to analyze

    Returns:
        Dictionary containing:
            - variance: Variance of segment lengths
            - std_dev: Standard deviation of segment lengths
            - recommendation: "reduce_batch" or "default"
            - suggested_factor: Batch size multiplier (0.6 for reduce, 1.0 for default)

    Example:
        >>> result = analyze_segment_variance(["short", "medium text", "very long text here"])
        >>> if result["recommendation"] == "reduce_batch":
        >>>     batch_size = int(batch_size * result["suggested_factor"])
    """
    if not segments:
        return {
            "variance": 0,
            "std_dev": 0,
            "recommendation": "default",
            "suggested_factor": 1.0,
        }

    lengths = [len(s) for s in segments]
    avg = sum(lengths) / len(lengths)
    variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
    std_dev = variance**0.5

    # High variance = use smaller batches
    # Coefficient of variation > 0.5 indicates high variability
    coefficient_of_variation = std_dev / avg if avg > 0 else 0

    if coefficient_of_variation > 0.5:
        return {
            "variance": variance,
            "std_dev": std_dev,
            "coefficient_of_variation": coefficient_of_variation,
            "recommendation": "reduce_batch",
            "suggested_factor": 0.6,
        }
    else:
        return {
            "variance": variance,
            "std_dev": std_dev,
            "coefficient_of_variation": coefficient_of_variation,
            "recommendation": "default",
            "suggested_factor": 1.0,
        }


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

    # Run-level purity failure tracking (class-level, shared across instances per process).
    # Each language runs in its own subprocess (--_single-lang-mode), so these accumulators
    # provide true run-level circuit breaking without cross-language contamination.
    _run_purity_failures: dict = {}  # tgt_lang → cumulative purity failure count
    _run_total_batches: dict = {}  # tgt_lang → cumulative batch count
    _circuit_breaker_enabled: bool = True  # class-level toggle (for testing)

    def __init__(
        self,
        segmentation_strategy: str = "sentence_only",
        terminology_file: Path | None = None,
        mt_model: Any | None = None,
        preserve_patterns: list[str] | None = None,
        site_profile: Any | None = None,
        batch_stats_tracker: Any | None = None,
        fasttext_detector: Any | None = None,
        similarity_tracker: Any | None = None,
        script_validation_thresholds: dict | None = None,
        batch_purity_skip_langs: list[str] | None = None,
        force_protected_fields: frozenset[str] | set[str] = frozenset(),
        target_lang: str | None = None,
    ):
        """
        Initialize extractor for native batch translation.

        Args:
            segmentation_strategy: "adaptive", "leaf_only", or "sentence_only"
            terminology_file: Path to terminology dictionary (one term per line)
            mt_model: M2M100 model instance (optional, not used for native batching)
            preserve_patterns: Regex patterns for content to preserve (e.g., brand names)
            site_profile: Site profile configuration for frontmatter field handling (optional)
            batch_stats_tracker: BatchStatsTracker for adaptive batch sizing (optional)
            fasttext_detector: FastTextDetector for language detection (optional, replaces langdetect)
            similarity_tracker: SimilarityTracker for adaptive similarity learning (optional)
            script_validation_thresholds: Script validation thresholds for fallback (optional)
            force_protected_fields: Frontmatter field names to always treat as protected
                (passthrough), overriding the site profile's per-field mode. Used for
                path-dependent exceptions (e.g. family/platform index page titles) that
                can't be expressed in the site-wide frontmatter config.
            target_lang: Target locale code (e.g. "ja"). Used to resolve headings/table
                cells against the i18n template-string table (mission
                heading-i18n-governance-20260723, TC-HT-I18N-004) before falling back to
                MT — None disables the table lookup entirely (e.g. legacy callers that
                don't pass it), preserving prior behavior.
        """
        self.segmentation_strategy = segmentation_strategy
        self.site_profile = site_profile
        self.force_protected_fields = frozenset(force_protected_fields)
        self.target_lang = target_lang
        # Process-cached (reference-i18n-hardening-20260725): one extractor is
        # built per file-translation call, so per-instance loading still
        # re-parsed all template-string YAML files once per file per language.
        self._template_registry = get_default_registry()
        self._protected_terms = get_default_protected_terms()

        # Load extraction config from site profile (with fallback to defaults)
        extraction_config = self._load_extraction_config()

        # Language purity configuration
        self.language_purity_min_length = extraction_config.get("language_purity", {}).get(
            "min_length", LANGUAGE_PURITY_MIN_LENGTH
        )
        self.language_purity_min_script_ratio = extraction_config.get("language_purity", {}).get(
            "min_script_ratio", LANGUAGE_PURITY_MIN_SCRIPT_RATIO
        )
        self.script_similar_languages = extraction_config.get("language_purity", {}).get(
            "script_similar_languages", SCRIPT_SIMILAR_LANGUAGES
        )

        # Batch translation tuning
        self.fallback_rate_threshold = extraction_config.get("batch_translation", {}).get(
            "fallback_rate_threshold", FALLBACK_RATE_THRESHOLD
        )
        self.token_per_word_estimate = extraction_config.get("batch_translation", {}).get(
            "token_per_word_estimate", TOKEN_PER_WORD_ESTIMATE
        )

        # Validate extraction config values
        self._validate_extraction_config()

        # Initialize preserve_patterns protection (if provided)
        self.preserve_patterns = preserve_patterns or []
        self.placeholder_manager = None
        if self.preserve_patterns:
            from .placeholder_manager import PlaceholderManager

            self.placeholder_manager = PlaceholderManager()
            logger.info(
                f"[DEBUG] PlaceholderManager initialized with {len(self.preserve_patterns)} preserve patterns"
            )
            for i, pattern in enumerate(self.preserve_patterns):
                logger.debug(f"[DEBUG]   Pattern {i}: {pattern}")

        # Load terminology dictionary (product names, etc.)
        self.terminology_dict = set()
        if terminology_file and terminology_file.exists():
            with open(terminology_file, encoding="utf-8") as f:
                for line in f:
                    term = line.strip()
                    if term:
                        self.terminology_dict.add(term)

        # Default Aspose-specific terms
        self.terminology_dict.update(
            {
                "Aspose.Slides",
                "Aspose.Cells",
                "Aspose.Words",
                "Aspose.PDF",
                "Aspose.Email",
                "Aspose.Imaging",
                "PowerPoint",
                "Excel",
                "Word",
                "API",
                "SDK",
                "JSON",
                "XML",
                "HTTP",
                "HTTPS",
                "SaveFormat.Pptx",
                "SaveFormat.Pdf",
                "LowCode",
                "C#",
                "Java",
                "Python",
            }
        )
        # Canonical exact protected terms live in config/terminology.yaml.
        # Keep AST do_not_translate classification aligned with the governed
        # terminology validator; otherwise a correctly preserved multi-word
        # phrase (for example "API Reference") is mislabeled as same-as-source
        # leakage by TC-SAS-01 in zero-defect campaigns.
        self.terminology_dict.update(self._protected_terms.terms)

        # Initialize NLP model for NER (optional, lazy loaded)
        self._nlp = None

        # Batch statistics tracking
        self.batch_stats = {
            "total_batches": 0,
            "total_outer_batches": 0,    # incremented once per outer loop iteration
            "failed_outer_batches": 0,   # outer batches where all sub-retries failed
            "successful_batches": 0,
            "fallback_batches": 0,
            "mapping_failures": 0,
            "translation_errors": 0,
            "individual_translations": 0,
            "individual_translation_errors": 0,
            "empty_translations": 0,
        }

        # Load technical terms whitelist for language purity bypass (PO-01)
        self.technical_terms = self._load_technical_terms()

        # Adaptive batch sizing tracker (optional)
        self.batch_stats_tracker = batch_stats_tracker

        # Language detection (FastText + adaptive similarity learning)
        self.fasttext_detector = fasttext_detector
        self.similarity_tracker = similarity_tracker
        self.script_validation_thresholds = script_validation_thresholds or {}
        self.batch_purity_skip_langs = batch_purity_skip_langs or []

    def _load_extraction_config(self) -> dict:
        """
        Load extraction config from site profile with fallback to defaults.

        Returns:
            Dictionary with extraction configuration, or empty dict if not available.
        """

        def _normalize_section(section: Any, seen: set[int] | None = None) -> Any:
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
            if hasattr(section, "__dict__"):
                module_name = section.__class__.__module__
                if module_name.startswith("unittest.mock"):
                    return {}
                return {k: _normalize_section(v, seen) for k, v in vars(section).items()}
            return section

        if self.site_profile:
            # Handle both dict and object attribute access
            if hasattr(self.site_profile, "extraction"):
                extraction = self.site_profile.extraction
                return _normalize_section(extraction)
            elif isinstance(self.site_profile, dict):
                return _normalize_section(self.site_profile.get("extraction", {}))
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
                with open(config_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    terms = set(data.get("terms", []))
                    logger.info(f"Loaded {len(terms)} technical terms from {config_path}")
                    return terms
            except Exception as e:
                logger.warning(f"Failed to load technical terms from {config_path}: {e}")

        # Fallback to hardcoded defaults
        default_terms = {
            "C#",
            "Aspose",
            "Excel",
            "HTML",
            "PDF",
            ".NET",
            "NuGet",
            "API",
            "SDK",
            "BarCode",
            "PowerPoint",
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
                f"Technical density: {density:.2f} ({matched_word_count}/{len(words)} words)",
                extra={"text": sanitize_for_log(text, 200)},
            )

        return density

    def _get_translatable_frontmatter_fields(self):
        """Get translatable frontmatter fields from config or defaults."""
        if self.site_profile and hasattr(self.site_profile, "frontmatter"):
            # Extract fields with mode='translate' or mode='translate_list'
            translatable = set()
            for field_name, field_rule in self.site_profile.frontmatter.items():
                # Handle both dict access and object attribute access
                if hasattr(field_rule, "mode"):
                    mode = field_rule.mode
                elif isinstance(field_rule, dict):
                    mode = field_rule.get("mode", "")
                else:
                    continue

                if mode in ("translate", "translate_list"):
                    translatable.add(field_name)

            if translatable:  # Only use if non-empty
                return translatable

        # Fallback to defaults
        return TRANSLATABLE_FRONTMATTER_FIELDS

    def _get_protected_frontmatter_fields(self):
        """Get protected frontmatter fields from config or defaults."""
        if self.site_profile and hasattr(self.site_profile, "frontmatter"):
            # Extract fields with mode='passthrough'
            protected = set()
            for field_name, field_rule in self.site_profile.frontmatter.items():
                # Handle both dict access and object attribute access
                if hasattr(field_rule, "mode"):
                    mode = field_rule.mode
                elif isinstance(field_rule, dict):
                    mode = field_rule.get("mode", "")
                else:
                    continue

                if mode == "passthrough":
                    protected.add(field_name)

            if protected:  # Only use if non-empty
                return protected | self.force_protected_fields

        # Fallback to defaults
        return NON_TRANSLATABLE_FRONTMATTER_FIELDS | self.force_protected_fields

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
                stripped = field_value.strip()
                do_not_translate = self._is_non_translatable(stripped)
                protected_text = field_value
                placeholder_map = {}
                if not do_not_translate and self.placeholder_manager:
                    protected_text, placeholder_map = self.placeholder_manager.protect(
                        field_value, self.preserve_patterns
                    )
                unit = TextUnit(
                    unit_id=TextUnit.create_id(
                        f"frontmatter.{field_name}", protected_text, TextUnitKind.TEXT
                    ),
                    node_addr=f"frontmatter.{field_name}",
                    kind=TextUnitKind.TEXT,
                    source_text=protected_text,
                    do_not_translate=do_not_translate,
                    metadata={
                        "field_name": field_name,
                        "field_type": "string",
                        "placeholder_map": placeholder_map,
                        "original_text": field_value,
                    },
                )
                units.append(unit)
                logger.debug(
                    f"Extracted frontmatter field '{field_name}' do_not_translate={do_not_translate}",
                    extra={"field_value": sanitize_for_log(field_value, 200)},
                )

            # Handle array fields (e.g., keywords)
            elif isinstance(field_value, list):
                for i, item in enumerate(field_value):
                    if isinstance(item, str) and item.strip():
                        item_stripped = item.strip()
                        do_not_translate = self._is_non_translatable(item_stripped)
                        protected_item = item
                        placeholder_map = {}
                        if not do_not_translate and self.placeholder_manager:
                            protected_item, placeholder_map = self.placeholder_manager.protect(
                                item, self.preserve_patterns
                            )
                        unit = TextUnit(
                            unit_id=TextUnit.create_id(
                                f"frontmatter.{field_name}[{i}]", protected_item, TextUnitKind.TEXT
                            ),
                            node_addr=f"frontmatter.{field_name}[{i}]",
                            kind=TextUnitKind.TEXT,
                            source_text=protected_item,
                            do_not_translate=do_not_translate,
                            metadata={
                                "field_name": field_name,
                                "field_type": "array",
                                "index": i,
                                "placeholder_map": placeholder_map,
                                "original_text": item,
                            },
                        )
                        units.append(unit)
                        logger.debug(
                            f"Extracted frontmatter array '{field_name}[{i}]' do_not_translate={do_not_translate}",
                            extra={"item": sanitize_for_log(item, 200)},
                        )

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

            field_name = unit.metadata.get("field_name")
            field_type = unit.metadata.get("field_type")

            if field_type == "string":
                # Simple string field — restore placeholders if any
                translated = unit.translated_text
                placeholder_map = unit.metadata.get("placeholder_map")
                if placeholder_map and self.placeholder_manager:
                    translated = self.placeholder_manager.restore(translated, placeholder_map)
                frontmatter_dict[field_name] = translated
                logger.debug(f"Applied translation to frontmatter field '{field_name}'")
                applied_count += 1

            elif field_type == "array":
                # Array item — restore placeholders if any
                index = unit.metadata.get("index")
                if field_name in frontmatter_dict:
                    if isinstance(frontmatter_dict[field_name], list):
                        if index < len(frontmatter_dict[field_name]):
                            translated = unit.translated_text
                            placeholder_map = unit.metadata.get("placeholder_map")
                            if placeholder_map and self.placeholder_manager:
                                translated = self.placeholder_manager.restore(
                                    translated, placeholder_map
                                )
                            frontmatter_dict[field_name][index] = translated
                            logger.debug(
                                f"Applied translation to frontmatter array '{field_name}[{index}]'"
                            )
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
        self, units: list[TextUnit], max_units: int, max_tokens: int
    ) -> list[list[TextUnit]]:
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
            would_exceed_tokens = current_token_estimate + unit_tokens > max_tokens
            would_exceed_units = len(current_batch) >= max_units

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
        self, batch: list[TextUnit], mt_model: Any, src_lang: str, tgt_lang: str
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
                    translated = results[0].strip()

                    # NEW: Validate individual translation language purity
                    if self.fasttext_detector and self.fasttext_detector.is_available:
                        try:
                            detected, conf = self.fasttext_detector.detect(translated)

                            # If wrong language with high confidence, mark as failed
                            if detected != tgt_lang and conf > 0.70:
                                is_similar = False
                                if self.similarity_tracker:
                                    is_similar = self.similarity_tracker.are_similar(
                                        tgt_lang, detected
                                    )

                                if not is_similar:
                                    logger.warning(
                                        f"Individual fallback failed purity: Expected {tgt_lang}, "
                                        f"got {detected} ({conf:.2%}). Marking as untranslated."
                                    )
                                    # Set None (not "") so get_final_text() returns source_text,
                                    # making the failure visible to the file-level purity gate
                                    # rather than silently writing a blank paragraph.
                                    unit.translated_text = (
                                        None  # Mark as failed — purity gate will catch
                                    )
                                    self.batch_stats["individual_purity_failures"] = (
                                        self.batch_stats.get("individual_purity_failures", 0) + 1
                                    )
                                    continue
                        except Exception as e:
                            logger.debug(f"Could not validate individual translation: {e}")

                    unit.translated_text = translated
                    if unit.translated_text == "":
                        self.batch_stats["individual_translation_errors"] += 1
                else:
                    self.batch_stats["individual_translation_errors"] += 1
                    # Set None so get_final_text() surfaces source_text to purity gate
                    unit.translated_text = None
            except Exception as e:
                logger.error(f"Individual translation failed for unit: {e}")
                self.batch_stats["individual_translation_errors"] += 1
                # Set None so get_final_text() surfaces source_text to purity gate
                unit.translated_text = None

        self.batch_stats["individual_translations"] = self.batch_stats.get(
            "individual_translations", 0
        ) + len(batch)

    def _translate_single_batch(
        self,
        batch: list[TextUnit],
        mt_model: Any,
        src_lang: str,
        tgt_lang: str,
        generation_params: dict[str, Any] | None = None,
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
            generation_params: Optional generation parameters for adaptive behavior
                (e.g., stronger repetition penalties)

        Returns:
            True if batch translation succeeded, False if fell back to individual
        """
        batch_count = len(batch)

        # Build list of source texts (native batching - no delimiters!)
        batch_texts = [u.source_text for u in batch]

        # TRANSLATION: Send list to model (model handles batching internally)
        try:
            # DEBUG: Log translation attempt
            if batch_count <= 3:  # Only log details for small batches
                logger.debug(
                    f"Translating batch of {batch_count} segments ({src_lang}→{tgt_lang}): "
                    f"[{', '.join([repr(t[:30]) for t in batch_texts[:3]])}...]"
                )

            translations = mt_model.translate(
                batch_texts, src_lang, tgt_lang, generation_params=generation_params
            )

            # DEBUG: Log translation results
            if batch_count <= 3 and translations:
                logger.debug(
                    f"Translation results: "
                    f"[{', '.join([repr(t[:30]) for t in translations[:3]])}...]"
                )

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
                self.batch_stats["mapping_failures"] += 1
                self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)
                return False

        except Exception as e:
            logger.error(f"TRANSLATION ERROR: {e}. Falling back to individual translation.")
            self.batch_stats["translation_errors"] = (
                self.batch_stats.get("translation_errors", 0) + 1
            )
            self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)
            return False

        # SUCCESS: Apply translations (perfect 1:1 mapping)
        # strict=True: the length check above guarantees equality before reaching here;
        # if it ever fires unexpectedly, the except at the caller catches it and falls
        # back to individual translation rather than silently dropping units.
        for unit, translation in zip(batch, translations, strict=True):
            unit.translated_text = translation.strip()

        # LANGUAGE PURITY CHECK: Verify all translations are in target language
        # LLM-WASTE-FIX-2b: Skip purity check for languages with known FastText false-positive rates
        if _normalize_lang_code(tgt_lang) in self.batch_purity_skip_langs:
            logger.debug(f"Skipping batch purity check for {tgt_lang} (in batch_purity_skip_langs)")
            self.batch_stats["successful_batches"] += 1
            return True

        if not self._verify_translation_language_purity(batch, tgt_lang):
            logger.warning(
                f"LANGUAGE PURITY CHECK FAILED: Batch produced mixed-language output. "
                f"Attempting reactive batch splitting (batch_size={batch_count})."
            )
            self.batch_stats["language_purity_failures"] = (
                self.batch_stats.get("language_purity_failures", 0) + 1
            )
            # Update run-level counter for circuit breaker (TC-03)
            TextUnitExtractor._run_purity_failures[tgt_lang] = (
                TextUnitExtractor._run_purity_failures.get(tgt_lang, 0) + 1
            )

            # REACTIVE SPLITTING: Try smaller batches before individual fallback
            if batch_count > 1 and self.batch_stats_tracker:
                reduced_size = self.batch_stats_tracker.react_to_failure(tgt_lang, batch_count)

                # Split batch in half and retry
                mid = batch_count // 2
                logger.info(
                    f"Reactive split: {batch_count} → [{mid} + {batch_count - mid}] "
                    f"(target={tgt_lang})"
                )

                success_1 = self._translate_single_batch(batch[:mid], mt_model, src_lang, tgt_lang)
                success_2 = self._translate_single_batch(batch[mid:], mt_model, src_lang, tgt_lang)

                # Return combined success status
                return success_1 and success_2

            # Fallback to individual if already at size 1 or no tracker
            logger.warning(
                f"Re-translating {batch_count} units individually to ensure language purity."
            )
            self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)
            return False

        self.batch_stats["successful_batches"] += 1
        logger.debug(f"Batch translation successful ({batch_count} units)")

        return True

    def _log_batch_statistics(self):
        """Log comprehensive batch translation statistics."""
        stats = self.batch_stats
        total = stats["total_batches"]

        if total == 0:
            return

        success_rate = (stats["successful_batches"] / total) * 100
        fallback_rate = (stats["fallback_batches"] / total) * 100

        logger.info(
            f"\n"
            f"=== Batch Translation Statistics ===\n"
            f"Total batches:             {total}\n"
            f"Successful:                {stats['successful_batches']} ({success_rate:.1f}%)\n"
            f"Fallback:                  {stats['fallback_batches']} ({fallback_rate:.1f}%)\n"
            f"  - Mapping failures:      {stats.get('mapping_failures', 0)}\n"
            f"  - Language purity:       {stats.get('language_purity_failures', 0)}\n"
            f"  - Translation errors:    {stats.get('translation_errors', 0)}\n"
            f"Repetition detection:      \n"
            f"  - Detected:              {stats.get('repetition_detected_count', 0)}\n"
            f"  - Retry attempts:        {stats.get('repetition_retry_count', 0)}\n"
            f"  - Retry success:         {stats.get('repetition_retry_success', 0)}\n"
            f"  - Batch splits:          {stats.get('repetition_split_count', 0)}\n"
            f"  - Final fallback:        {stats.get('repetition_fallback_count', 0)}\n"
            f"Individual translations:   {stats.get('individual_translations', 0)}\n"
            f"Fallback rate:             {fallback_rate:.1f}%\n"
            f"===================================="
        )

    def _verify_translation_language_purity(self, units: list[TextUnit], target_lang: str) -> bool:
        """
        Verify all translated units are in target language.

        Uses FastText (preferred) or langdetect (fallback) for language detection.
        Integrates with adaptive similarity tracker to learn which language pairs
        cause false positives and automatically accept them.

        Multi-tier validation:
        1. Technical density bypass (>25% technical terms)
        2. FastText/langdetect detection with confidence threshold
        3. Adaptive similarity groups (learned + baseline)
        4. Script-based validation fallback

        PO-01: Units with high technical term density (>=25%) bypass this check
        to prevent false positives from technical content.

        Args:
            units: List of TextUnits with translated_text populated
            target_lang: Expected target language code (e.g., 'de', 'fr')

        Returns:
            True if all units pass language check, False if any fail
        """
        # Check if detection is available
        has_fasttext = self.fasttext_detector and self.fasttext_detector.is_available
        has_langdetect = False

        if not has_fasttext:
            # Try langdetect fallback
            try:
                import langdetect
                from langdetect import DetectorFactory

                DetectorFactory.seed = 0  # Reproducible results
                has_langdetect = True
            except ImportError:
                pass

        if not has_fasttext and not has_langdetect:
            logger.error(
                "CRITICAL: No language detector available. Cannot validate translation purity. "
                "Install fasttext or langdetect before running translations."
            )
            raise RuntimeError("Language detector required for translation quality assurance")

        failed_units = []
        bypassed_count = 0
        similarity_accepted_count = 0
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
                    f"Bypassing purity check (technical density={density:.2f})",
                    extra={"translation": sanitize_for_log(translated, 200)},
                )
                bypassed_count += 1
                continue

            # Use FastText if available, otherwise langdetect
            if has_fasttext:
                # FastText with integrated verification
                is_valid = self.fasttext_detector.verify_language(
                    text=translated,
                    expected_lang=target_lang,
                    similarity_tracker=self.similarity_tracker,
                    script_validation_thresholds=self.script_validation_thresholds,
                )

                if is_valid:
                    # Check if accepted due to similarity (for statistics)
                    detected_lang, confidence = self.fasttext_detector.detect(translated)
                    if detected_lang != target_lang and detected_lang != "unknown":
                        similarity_accepted_count += 1
                        logger.debug(
                            f"Language purity: Accepted due to similarity "
                            f"(detected={detected_lang}, expected={target_lang}): "
                            f"{sanitize_for_log(translated[:50], 50)}"
                        )
                else:
                    # Detection failed
                    detected_lang, confidence = self.fasttext_detector.detect(translated)
                    logger.debug(
                        f"Language purity FAILED: detected={detected_lang} "
                        f"(confidence={confidence:.2f}), expected={target_lang}: "
                        f"{sanitize_for_log(translated[:50], 50)}"
                    )
                    failed_units.append(
                        {
                            "text": translated[:60] + "..." if len(translated) > 60 else translated,
                            "expected": target_lang,
                            "detected": detected_lang,
                            "confidence": f"{confidence:.2f}",
                            "method": "fasttext",
                        }
                    )

            else:
                # Langdetect fallback (legacy behavior)
                try:
                    detected = langdetect.detect(translated)

                    # Check exact match
                    if detected == target_lang:
                        continue

                    # Check old script_similar_languages config (backward compatibility)
                    script_similar = self.script_similar_languages.get(target_lang, set())
                    if detected in script_similar:
                        logger.debug(
                            f"Accepting script-similar language (legacy): detected={detected}, "
                            f"target={target_lang}"
                        )
                        similarity_accepted_count += 1
                        continue

                    # Check adaptive similarity tracker
                    if self.similarity_tracker and self.similarity_tracker.are_similar(
                        target_lang, detected
                    ):
                        logger.debug(
                            f"Accepting similar language (adaptive): detected={detected}, "
                            f"target={target_lang}"
                        )
                        similarity_accepted_count += 1

                        # Record for learning
                        self.similarity_tracker.record_detection(
                            expected_lang=target_lang,
                            detected_lang=detected,
                            confidence=0.80,  # langdetect assumed confidence
                            success=True,
                        )
                        continue

                    # Script validation fallback
                    script_ratio = self._target_script_ratio(translated, target_lang)
                    if script_ratio >= self.language_purity_min_script_ratio:
                        logger.debug(
                            f"Accepting target-script ratio override (ratio={script_ratio:.2f}): "
                            f"detected={detected}, target={target_lang}"
                        )
                        script_override_count += 1
                        continue

                    # Failed all checks
                    failed_units.append(
                        {
                            "text": translated[:60] + "..." if len(translated) > 60 else translated,
                            "expected": target_lang,
                            "detected": detected,
                            "method": "langdetect",
                        }
                    )

                    # Record failed detection for adaptive learning
                    if self.similarity_tracker:
                        self.similarity_tracker.record_detection(
                            expected_lang=target_lang,
                            detected_lang=detected,
                            confidence=0.80,  # langdetect assumed confidence
                            success=False,
                        )

                except Exception as e:
                    # Skip texts that can't be detected (often technical content)
                    logger.debug(f"Language detection failed (skipping): {e}")
                    pass

        # Calculate truly detected count
        total_validated = len(units)
        truly_detected_count = (
            total_validated
            - bypassed_count
            - similarity_accepted_count
            - script_override_count
            - len(failed_units)
        )

        # Determine detection method
        detection_method = "FastText" if has_fasttext else "langdetect"

        # Log comprehensive summary with breakdown
        if failed_units:
            # FAILURE case
            logger.error(
                f"Language purity check FAILED for batch (method={detection_method}):\n"
                f"  Total units: {total_validated}\n"
                f"  - Failed (wrong language): {len(failed_units)} ({len(failed_units) / total_validated * 100:.1f}%)\n"
                f"  - Detected correctly: {truly_detected_count} ({truly_detected_count / total_validated * 100:.1f}%)\n"
                f"  - Bypassed (technical): {bypassed_count} ({bypassed_count / total_validated * 100:.1f}%)\n"
                f"  - Accepted (similarity): {similarity_accepted_count} ({similarity_accepted_count / total_validated * 100:.1f}%)\n"
                f"  - Accepted (script): {script_override_count} ({script_override_count / total_validated * 100:.1f}%)"
            )
            return False
        else:
            # SUCCESS case - show detailed breakdown
            logger.info(
                f"Language purity check PASSED (method={detection_method}):\n"
                f"  Total units: {total_validated}\n"
                f"  - Detected as {target_lang}: {truly_detected_count} ({truly_detected_count / total_validated * 100:.1f}%)\n"
                f"  - Bypassed (technical ≥25%): {bypassed_count} ({bypassed_count / total_validated * 100:.1f}%)\n"
                f"  - Accepted (similarity): {similarity_accepted_count} ({similarity_accepted_count / total_validated * 100:.1f}%)\n"
                f"  - Accepted (script): {script_override_count} ({script_override_count / total_validated * 100:.1f}%)"
            )
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

    def _build_cell_header_map(self, ast: list[ASTNode]) -> dict[str, str]:
        """Pre-pass: map each TABLE_CELL node_id → column header text.

        Used by _extract_full_sentence to populate column_header metadata on
        TABLE_CELL_TEXT units so LLM backend has column context.
        """
        result: dict[str, str] = {}

        def _scan(node: ASTNode) -> None:
            if node.type == NodeType.TABLE:
                # Find first header row
                header_texts: list[str] = []
                for row in node.children:
                    if row.type == NodeType.TABLE_ROW and row.attrs.get("is_header"):
                        for cell in row.children:
                            if cell.type == NodeType.TABLE_CELL:
                                header_texts.append(
                                    self._collect_text_from_node(cell).strip()
                                )
                        break
                # Map body cells: cell.node_id → header_texts[col_idx]
                for row in node.children:
                    if row.type == NodeType.TABLE_ROW and not row.attrs.get("is_header"):
                        for col_idx, cell in enumerate(row.children):
                            if (
                                cell.type == NodeType.TABLE_CELL
                                and cell.node_id
                                and col_idx < len(header_texts)
                            ):
                                result[cell.node_id] = header_texts[col_idx]
            for child in node.children:
                _scan(child)

        for root in ast:
            _scan(root)
        return result

    def extract_from_ast(
        self, ast: list[ASTNode], frontmatter: dict[str, Any] | None = None
    ) -> BodyTranslationPlan:
        """
        Extract all translatable TextUnits from AST and frontmatter.

        Args:
            ast: List of root ASTNode objects (document body)
            frontmatter: Optional frontmatter dictionary (FIX-BT-03)

        Returns:
            BodyTranslationPlan with units and AST reference
        """
        units: list[TextUnit] = []

        # TC-EXT-001: pre-compute column headers for all table cells
        self._cell_column_header: dict[str, str] = self._build_cell_header_map(ast)

        # Extract frontmatter fields (FIX-BT-03)
        if frontmatter:
            frontmatter_units = self._extract_frontmatter_units(frontmatter)
            units.extend(frontmatter_units)
            logger.info(f"Extracted {len(frontmatter_units)} frontmatter units")

        # Traverse each root node
        for node in ast:
            self._traverse_node(node, units)

        self._cell_column_header = {}  # clear after use

        # Calculate AST fingerprint for sanity checks
        ast_fingerprint = self._calculate_ast_fingerprint(ast)

        return BodyTranslationPlan(
            ast=ast,
            units=units,
            ast_fingerprint=ast_fingerprint,
            metadata={
                "segmentation_strategy": self.segmentation_strategy,
                "total_units": len(units),
                "translatable_units": len([u for u in units if not u.do_not_translate]),
                "frontmatter_units": len(
                    [u for u in units if u.node_addr and u.node_addr.startswith("frontmatter.")]
                ),
            },
        )

    def _traverse_node(self, node: ASTNode, units: list[TextUnit]) -> None:
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

        elif node.type in (
            NodeType.HEADING,
            NodeType.PARAGRAPH,
            NodeType.LIST_ITEM,
            NodeType.BLOCKQUOTE,
            NodeType.TABLE_CELL,
        ):
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

    def _extract_text_node(self, node: ASTNode, units: list[TextUnit]) -> None:
        """Extract text node with whitespace preservation."""
        if not node.raw:
            return

        # Skip nodes without addresses - they cannot be reliably tracked
        if not node.node_addr:
            logger.debug(
                "Skipping text node without address: type=%s, raw_preview=%s",
                node.type.value if node.type else "unknown",
                (node.raw[:50] + "...") if node.raw and len(node.raw) > 50 else node.raw,
            )
            return

        text = node.raw

        # Separate whitespace
        prefix_ws = ""
        suffix_ws = ""
        stripped_text = text.strip()

        if stripped_text:
            # Find prefix whitespace
            prefix_match = re.match(r"^(\s*)", text)
            if prefix_match:
                prefix_ws = prefix_match.group(1)

            # Find suffix whitespace
            suffix_match = re.search(r"(\s*)$", text)
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
            logger.debug(
                "[DEBUG] Applying protection",
                extra={"source_text": sanitize_for_log(stripped_text, 200)},
            )
            protected_text, placeholder_map = self.placeholder_manager.protect(
                stripped_text, self.preserve_patterns
            )
            if placeholder_map:
                logger.info(
                    f"[DEBUG] Protected {len(placeholder_map)} instances",
                    extra={"source_text": sanitize_for_log(stripped_text, 200)},
                )
                for placeholder, original in placeholder_map.items():
                    logger.debug(
                        f"[DEBUG]   {placeholder}",
                        extra={"original": sanitize_for_log(original, 200)},
                    )

        # Create TextUnit with protected text and placeholder map
        unit = TextUnit(
            unit_id=TextUnit.create_id(node.node_addr, protected_text, TextUnitKind.TEXT),
            node_addr=node.node_addr,
            kind=TextUnitKind.TEXT,
            source_text=protected_text,
            prefix_ws=prefix_ws,
            suffix_ws=suffix_ws,
            do_not_translate=do_not_translate,
            metadata={"placeholder_map": placeholder_map} if placeholder_map else {},
        )
        # i18n table short-circuit (TC-HT-I18N-004): pre-setting translated_text
        # here makes segment_translator.py's existing "already translated" skip
        # (the same one used for LLM-prefilled units) apply automatically — no
        # MT call, no TM read/write, for this unit.
        table_value = self._i18n_table_value(
            protected_text, node_addr=node.node_addr, kind=TextUnitKind.TEXT
        )
        if table_value is not None:
            unit.do_not_translate = True
            unit.translated_text = table_value
        logger.debug(
            f"[DEBUG] Created TextUnit: do_not_translate={unit.do_not_translate}",
            extra={"source_text": sanitize_for_log(protected_text, 200)},
        )
        units.append(unit)

    def _extract_code_span(self, node: ASTNode, units: list[TextUnit]) -> None:
        """Extract code span as non-translatable."""
        if not node.raw:
            return

        # Skip nodes without addresses - they cannot be reliably tracked
        if not node.node_addr:
            logger.debug(
                "Skipping code span without address: raw_preview=%s",
                (node.raw[:30] + "...") if len(node.raw) > 30 else node.raw,
            )
            return

        unit = TextUnit(
            unit_id=TextUnit.create_id(node.node_addr, node.raw, TextUnitKind.CODE_SPAN),
            node_addr=node.node_addr,
            kind=TextUnitKind.CODE_SPAN,
            source_text=node.raw,
            do_not_translate=True,  # Code is NEVER translated
        )
        units.append(unit)

    def _extract_code_block(self, node: ASTNode, units: list[TextUnit]) -> None:
        """Extract code block as non-translatable."""
        if not node.raw:
            return

        # Skip nodes without addresses - they cannot be reliably tracked
        if not node.node_addr:
            logger.debug(
                "Skipping code block without address: lang=%s, lines=%d",
                node.attrs.get("language", "none") if node.attrs else "none",
                node.raw.count("\n") + 1,
            )
            return

        # Note: Using CODE_SPAN kind for now (could add CODE_BLOCK to TextUnitKind if needed)
        unit = TextUnit(
            unit_id=TextUnit.create_id(node.node_addr, node.raw, TextUnitKind.CODE_SPAN),
            node_addr=node.node_addr,
            kind=TextUnitKind.CODE_SPAN,
            source_text=node.raw,
            do_not_translate=True,  # Code is NEVER translated
        )
        units.append(unit)

    def _extract_link(self, node: ASTNode, units: list[TextUnit]) -> None:
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
                        do_not_translate=self._is_non_translatable(text),
                    )
                    units.append(unit)
            else:
                # Nested formatting in link (e.g., bold in link)
                self._traverse_node(child, units)

        # URL is stored in node.attrs['url'] - preserved, not extracted

    def _extract_image(self, node: ASTNode, units: list[TextUnit]) -> None:
        """Extract image alt text (not src)."""
        alt_text = node.attrs.get("alt", "").strip()
        if alt_text:
            unit = TextUnit(
                unit_id=TextUnit.create_id(node.node_addr, alt_text, TextUnitKind.IMAGE_ALT),
                node_addr=node.node_addr,
                kind=TextUnitKind.IMAGE_ALT,
                source_text=alt_text,
                do_not_translate=self._is_non_translatable(alt_text),
            )
            units.append(unit)

        # src is stored in node.attrs['src'] - preserved, not extracted

    def _extract_full_sentence(self, node: ASTNode, units: list[TextUnit]) -> None:
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
            prefix_match = re.match(r"^(\s*)", full_text)
            if prefix_match:
                prefix_ws = prefix_match.group(1)

            suffix_match = re.search(r"(\s*)$", full_text)
            if suffix_match:
                suffix_ws = suffix_match.group(1)

        # TC-EXT-001 column context, hoisted above the DNT check so the
        # kind-scoped registry override (and the i18n resolver below) can
        # gate Access-column enum values on it.
        _col_header = ""
        if kind is TextUnitKind.TABLE_CELL_TEXT and node.node_id:
            _col_header = getattr(self, "_cell_column_header", {}).get(node.node_id, "")

        # Check if non-translatable FIRST (before applying placeholders)
        do_not_translate = self._is_non_translatable(
            stripped_text, kind=kind, column_header=_col_header or None
        )

        # Apply preserve_patterns protection (if configured and not already protected)
        placeholder_map = {}
        protected_text = stripped_text
        if self.placeholder_manager and stripped_text and not do_not_translate:
            logger.debug(
                "[DEBUG] Applying protection to full sentence",
                extra={"source_text": sanitize_for_log(stripped_text, 200)},
            )
            protected_text, placeholder_map = self.placeholder_manager.protect(
                stripped_text, self.preserve_patterns
            )
            if placeholder_map:
                logger.info(
                    f"[DEBUG] Protected {len(placeholder_map)} instances in full sentence",
                    extra={"source_text": sanitize_for_log(stripped_text, 200)},
                )
                for placeholder, original in placeholder_map.items():
                    logger.debug(
                        f"[DEBUG]   {placeholder}",
                        extra={"original": sanitize_for_log(original, 200)},
                    )

        # TC-OPS-001: short API description cells (≤60 chars, "Gets/Sets/…" pattern) must
        # go to professionalize_llm, NOT to NLLB/m2m.  MT models hallucinate "psychiatrist"
        # for "Gets the shrink to fit." — the context is too sparse for MT.
        _unit_metadata: dict = {"placeholder_map": placeholder_map} if placeholder_map else {}

        # TC-EXT-001: add column_header for table cells so LLM has column context
        if _col_header:
            _unit_metadata["column_header"] = _col_header
        if (
            kind is TextUnitKind.TABLE_CELL_TEXT
            and not do_not_translate
            and len(stripped_text) <= 60
            and re.match(
                r"^(?:Gets?|Sets?|Indicates?|Enables?|Disables?|Represents?)\s",
                stripped_text,
            )
        ):
            _unit_metadata["preferred_model"] = "professionalize_llm"
            _unit_metadata["context_hint"] = "api_property_description"

        unit = TextUnit(
            unit_id=TextUnit.create_id(node.node_addr, protected_text, kind),
            node_addr=node.node_addr,
            kind=kind,
            source_text=protected_text,
            prefix_ws=prefix_ws,
            suffix_ws=suffix_ws,
            do_not_translate=do_not_translate,
            metadata=_unit_metadata,
        )
        # i18n table short-circuit (TC-HT-I18N-004): this is the primary path
        # for headings (kind=HEADING_TEXT) and table headers/enum cells
        # (kind=TABLE_CELL_TEXT) — the ~83% of the english_headings_nonlatin
        # backlog this mission's i18n table covers. See _extract_text_node's
        # matching comment for why pre-setting translated_text is sufficient.
        # reference-i18n-hardening-20260725: kind + column context scope the
        # lookup (enum values only serve under their required column header).
        if kind in (TextUnitKind.HEADING_TEXT, TextUnitKind.TABLE_CELL_TEXT):
            table_value = self._i18n_table_value(
                protected_text,
                node_addr=node.node_addr,
                kind=kind,
                column_header=_col_header or None,
            )
            if table_value is not None:
                unit.do_not_translate = True
                unit.translated_text = table_value
        logger.debug(
            f"[DEBUG] Created full sentence TextUnit: do_not_translate={unit.do_not_translate}",
            extra={"source_text": sanitize_for_log(protected_text, 200)},
        )
        units.append(unit)

    def _collect_text_from_node(self, node: ASTNode) -> str:
        """Recursively collect all text from node and children, preserving markdown formatting."""
        if node.type == NodeType.TEXT:
            return node.raw or ""

        elif node.type == NodeType.LINK:
            # Reconstruct link markdown: [text](url) or [text](url "title")
            url = node.attrs.get("url", "")
            title = node.attrs.get("title")
            text = "".join(self._collect_text_from_node(child) for child in node.children)
            if title:
                # Escape quotes in title
                escaped_title = title.replace('"', '\\"')
                return f'[{text}]({url} "{escaped_title}")'
            else:
                return f"[{text}]({url})"

        elif node.type == NodeType.STRONG:
            # Reconstruct bold: **text**
            text = "".join(self._collect_text_from_node(child) for child in node.children)
            return f"**{text}**"

        elif node.type == NodeType.EMPHASIS:
            # Reconstruct italic: *text*
            text = "".join(self._collect_text_from_node(child) for child in node.children)
            return f"*{text}*"

        elif node.type == NodeType.CODE_SPAN:
            # Preserve inline code: `code`
            return f"`{node.raw}`" if node.raw else ""

        elif node.type == NodeType.IMAGE:
            # Reconstruct image: ![alt](src) or ![alt](src "title")
            src = node.attrs.get("src", "")
            alt = node.attrs.get("alt", "")
            title = node.attrs.get("title")
            if title:
                escaped_title = title.replace('"', '\\"')
                return f'![{alt}]({src} "{escaped_title}")'
            else:
                return f"![{alt}]({src})"

        elif node.type == NodeType.SOFT_BREAK:
            return " "

        elif node.type == NodeType.LINE_BREAK:
            return "\n"

        elif node.type == NodeType.INLINE_HTML:
            return node.raw or ""

        elif node.type == NodeType.CODE_BLOCK:
            # Bug 2: CODE_BLOCK has no children — content is in node.raw.
            # Return fenced representation with trailing \n\n to match renderer output.
            lang = node.attrs.get("lang", "") if node.attrs else ""
            code = node.raw or ""
            # TC-HT-004: idempotent newline before the closing fence -- code
            # already ends with \n in the common case.
            if code and not code.endswith("\n"):
                code += "\n"
            return f"```{lang}\n{code}```\n\n"

        # Default: recurse through children
        text_parts = []
        for child in node.children:
            text_parts.append(self._collect_text_from_node(child))

        return "".join(text_parts)

    def _should_extract_full_sentence(self, node: ASTNode) -> bool:
        """
        Determine if node should be extracted as full sentence.

        FIX-B: Even in sentence_only mode, fallback to leaf extraction when
        inline formatting is present to prevent markdown loss.

        Returns True for plain text paragraphs without inline formatting.
        """
        if self.segmentation_strategy == "leaf_only":
            return False
        elif self.segmentation_strategy == "sentence_only":
            # FIX-B: Make sentence_only safe - check for inline formatting
            # If inline formatting is present, fall back to leaf extraction
            has_formatting = self._has_inline_formatting(node)
            # Bug 3: Also fall back when block-level content (CODE_BLOCK) is present —
            # full-sentence extraction cannot represent block children as plain text.
            has_block = self._has_block_content(node)
            if has_formatting or has_block:
                # Don't extract full sentence - content would be lost
                logger.debug(
                    f"FIX-B: Skipping full-sentence extraction for {node.node_addr} (has inline formatting or block content)"
                )
                return False
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
            logger.warning(
                f"Unknown segmentation strategy: {self.segmentation_strategy}, using leaf_only"
            )
            return False

    def _has_inline_formatting(self, node: ASTNode) -> bool:
        """Check if node contains inline formatting (strong/em/link/shortcodes/etc.)."""
        formatting_types = {
            NodeType.STRONG,
            NodeType.EMPHASIS,
            NodeType.CODE_SPAN,
            NodeType.LINK,
            NodeType.IMAGE,
            # INLINE_HTML intentionally excluded: shortcodes are self-contained leaf nodes
            # that _collect_text_from_node handles via node.raw. Excluding them allows
            # full-sentence extraction so placeholder_manager can protect inline shortcodes.
        }

        # Check children
        for child in node.children:
            if child.type in formatting_types:
                return True
            # Recursively check nested children
            if self._has_inline_formatting(child):
                return True

        return False

    def _i18n_table_value(
        self,
        text: str,
        *,
        node_addr: str = "",
        kind: TextUnitKind | str | None = None,
        column_header: str | None = None,
    ) -> str | None:
        """Resolve ``text`` against the i18n template-string table for
        ``self.target_lang`` (mission heading-i18n-governance-20260723,
        TC-HT-I18N-004). Returns the approved translation on a table hit, or
        None otherwise (including when ``target_lang`` was never set, e.g.
        a caller that predates this parameter). Never raises: a classifier
        error must not block ordinary extraction.

        reference-i18n-hardening-20260725: ``kind`` scopes the lookup to the
        unit's grammatical role (normalized, category-filtered matching via
        classification.resolve()); ``column_header`` satisfies context-gated
        enum_value entries (Read/Write under an Access column).

        A miss also drives the continuous discovery log (TC-HT-I18N-005) for
        single-hump words with neither a table nor protected-terms entry —
        this is what turns "found by a rare full-corpus audit" into
        "surfaced continuously, as it happens."
        """
        if not self.target_lang:
            return None
        try:
            result = classify(
                text,
                self.target_lang,
                registry=self._template_registry,
                protected_terms=self._protected_terms,
                # File path isn't plumbed into the extractor today (extract_from_ast
                # only receives the AST + frontmatter); node_addr is still useful
                # discovery-log context and doesn't require widening that signature.
                context=node_addr or None,
                categories=categories_for_kind(kind) if kind is not None else None,
                unit_context={"column_header": column_header} if column_header else None,
            )
        except Exception:
            logger.debug("i18n table classification failed for %r", text[:80], exc_info=True)
            return None
        return result.value if result.verdict == VERDICT_TABLE else None

    def _has_block_content(self, node: ASTNode) -> bool:
        """Check if node has block-level children that cannot be represented as
        plain text in full-sentence extraction mode. Nested LISTs are included:
        a list item containing a sub-list must use leaf extraction so each
        item's text is extracted separately rather than concatenated."""
        for child in node.children:
            if child.type in (NodeType.CODE_BLOCK, NodeType.LIST):
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

    def _is_non_translatable(
        self,
        text: str,
        kind: TextUnitKind | str | None = None,
        column_header: str | None = None,
    ) -> bool:
        """
        Detect non-translatable content using multiple strategies.

        Returns True if text should NOT be translated (product names, technical IDs, etc.)

        Strategies:
        0. Hugo shortcodes ({{< >}}, {{% %}})
        1. NER-based detection (requires spaCy)
        2. Heuristic-based detection (CamelCase, snake_case, etc.)
        3. Terminology dictionary

        ``kind`` scopes the registry always-translate override to the unit's
        grammatical role (heading vs table cell vs bare text); callers that
        don't pass it get the bare-text scope (labels yes, enum values no).
        ``column_header`` is accepted for parity with the i18n resolver but
        eligibility here is category-level; value serving stays context-gated
        in classification.resolve().
        """
        text_stripped = text.strip()
        if not text_stripped:
            return False

        # Strategy 0: Hugo shortcodes - NEVER translate
        # Patterns: {{% steps %}}, {{< ref >}}, {{% /steps %}}, etc.
        if re.match(r"^\{\{[%<].*?[%>]\}\}$", text_stripped):
            logger.debug(
                "Hugo shortcode detected (protected)",
                extra={"source_text": sanitize_for_log(text_stripped, 200)},
            )
            return True

        # Strategy 0.5: Punctuation-only or separator-only strings - NEVER translate
        # These cause corruption like ",et," when the model tries to "translate" commas
        # Detect: strings with no alphanumeric content after stripping
        if not any(c.isalnum() for c in text_stripped):
            # Pure punctuation/symbols/separators: , . : ; - — → ← ↔ | / \ etc.
            logger.debug(
                "Punctuation-only text detected (protected)",
                extra={"source_text": sanitize_for_log(text_stripped, 50)},
            )
            return True

        # Strategy 0.7: Method/type signatures - NEVER translate (FIX Concern #4)
        # Signatures like BarCodeReader(string) must be preserved exactly
        # as they represent API contracts
        if self._is_signature_like(text_stripped):
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

        # TC-AUDIT-001 / reference-i18n-hardening-20260725: registry-driven
        # always-translate override for template strings the PascalCase
        # heuristic (Strategy 2) would incorrectly block. Kind-scoped: a
        # section-heading term is eligible as a heading or bare text; an
        # Access-column enum value (Read/Write/Execute/…) only as a table
        # cell — as a heading those words are method names and correctly
        # fall through to Strategy 2 / classify()'s default-protect.
        if is_translate_eligible(
            text_stripped,
            categories_for_kind(kind if kind is not None else "text"),
            registry=self._template_registry,
        ):
            return False

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
        # PascalCase: Starts with capital + 3+ lowercase/digits, optional additional PascalCase segments.
        # Matches single-word API identifiers (Body, Cell, Camera) AND multi-word (VertexDeclaration).
        # Requires 4+ chars total to avoid false-positive on common 3-char words (Use, The, For, See).
        # Changed from r"^[A-Z][a-z]+(?:[A-Z][a-z]+)+$" which required 2+ components
        # and incorrectly allowed translation of single-word API class names.
        if re.match(r"^[A-Z][a-z0-9]{3,}(?:[A-Z][a-z0-9]*)*$", text):
            return True

        # PascalCase.With.Dots — full match required; no trailing words/spaces
        # Old pattern lacked $ anchor and incorrectly marked description sentences
        # like "Header.SectorSize represents the size..." as non-translatable.
        if re.match(r"^[A-Z][a-z]+(?:\.[A-Z][A-Za-z0-9]*)+$", text):
            return True

        # snake_case (lowercase with underscores)
        if "_" in text and text.islower():
            return True

        # ALL_CAPS (2+ characters)
        if text.isupper() and len(text) > 1:
            return True

        # Version numbers: v1.2, 1.2.3, 2.0+
        # Full-match required (trailing $): the old pattern had no end anchor,
        # so re.match only required the STRING TO START WITH a digit -- any
        # heading beginning with a number ("3D Model Inspection and
        # Validation", "2D Visual Effects") satisfied it on the leading
        # digit alone and was marked non-translatable, silently shipping the
        # English heading in every locale on every site using AST body
        # reconstruction (not something limited to one site's content).
        if re.match(r"^v?\d+(?:\.\d+)*[\+\-]?$", text):
            return True

        return False

    def _is_signature_like(self, text: str) -> bool:
        """
        Check if text looks like a method/type signature that should be preserved exactly.

        Method signatures contain parentheses with parameters and should never be translated
        as they represent API contracts. Examples:
        - BarCodeReader(string)
        - BarCodeReader\\(string\\)  # Escaped markdown
        - Foo(int, bool)
        - Aspose.BarCode.BarCodeReader(string)

        Also detects HTML anchors with signature-like IDs that should be preserved:
        - <a id="...__ctor_System_String_"></a> BarCodeReader(string)

        Args:
            text: Text to check

        Returns:
            True if text looks like a method/type signature that should be preserved
        """
        if not text:
            return False

        text_stripped = text.strip()

        # Pattern 1: Method signature with parentheses (possibly escaped)
        # Matches: BarCodeReader(string), BarCodeReader\(string\), Foo(int, bool)
        # Prefix: identifier or dotted.identifier
        # Inside parentheses: type names (letters, digits, underscore, space, comma, [], <>, etc.)
        signature_pattern = (
            r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*\\?\([\w\s,\[\]<>?&|*@.]*\\?\)$"
        )
        if re.match(signature_pattern, text_stripped):
            logger.debug(f"Method signature detected (protected): {text_stripped[:80]}")
            return True

        # Pattern 2: HTML anchor with method signature following
        # Matches: <a id="..."></a> BarCodeReader(string)
        # This catches headings with anchors that contain method signatures
        anchor_with_signature = r'^<a\s+id="[^"]*"[^>]*>\s*</a>\s*(?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*\\?\([\w\s,\[\]<>?&|*@.]*\\?\)$'
        if re.match(anchor_with_signature, text_stripped):
            logger.debug(f"Anchor + method signature detected (protected): {text_stripped[:80]}")
            return True

        # Pattern 3: Text ending with method signature (for mixed content)
        # Matches text that ends with: SomeMethod(params)
        ends_with_signature = (
            r"(?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*\\?\([\w\s,\[\]<>?&|*@.]*\\?\)$"
        )
        if re.search(ends_with_signature, text_stripped):
            # Only protect if the main content is the signature (not a sentence about methods)
            # Check if text starts with identifier or anchor
            if re.match(r"^(?:<a\s|[A-Za-z_])", text_stripped):
                # Check ratio of signature to total text - if signature is >50%, protect it
                match = re.search(ends_with_signature, text_stripped)
                if match:
                    signature_len = len(match.group())
                    if signature_len > len(text_stripped) * 0.5:
                        logger.debug(
                            f"Text dominated by method signature (protected): {text_stripped[:80]}"
                        )
                        return True

        # Pattern 4: Short segments that ARE a dotted API identifier (with no real prose).
        # e.g. "FileNode.file_node_id" alone → protect (identifier = the whole text).
        # TC-AUDIT-001 (RC-B): Long description sentences starting with a dotted identifier
        # (e.g. "FileNode.file_node_id is the integer identifier...") are now sent to the
        # model instead of being blocked.  The new preserve_pattern
        # \b[A-Z][A-Za-z0-9_]+\.[a-z][A-Za-z0-9_.]*\b in reference.aspose.org.yaml protects
        # the identifier as a placeholder, so the surrounding prose is translated correctly.
        # Threshold: protect whole text only when identifier occupies >80% of the chars.
        dotted_pascal_lead = r"^[A-Z][A-Za-z0-9_]+\.[A-Za-z][A-Za-z0-9_.]*(?:\s|$)"
        m4 = re.match(dotted_pascal_lead, text_stripped)
        if m4:
            identifier_len = len(m4.group().rstrip())
            if identifier_len > len(text_stripped) * 0.80:
                logger.debug(
                    f"API identifier-led segment (protected): {text_stripped[:80]}"
                )
                return True
            # Sentence is longer than identifier — fall through to let model translate it
            # with identifier protected via preserve_patterns.

        return False

    def _tokenize_for_repetition_check(self, text: str) -> list[str]:
        """
        Tokenize text into words for repetition detection.

        Reuses logic from RepetitionDetectorValidator for consistency.

        Args:
            text: Text to tokenize

        Returns:
            List of normalized words (lowercase)
        """
        # Remove punctuation and split on whitespace
        words = re.findall(r"\b[\w]+\b", text.lower())
        return words

    def _detect_batch_repetition(
        self, units: list[TextUnit], threshold: int = 3
    ) -> tuple[bool, list[TextUnit]]:
        """
        Quick repetition detection for batch translations.

        Checks for:
        1. N-gram repetition within single translations (3-grams appearing >=3 times)
        2. Cross-unit duplicate translations (different sources → same output)

        Args:
            units: TextUnits with translated_text populated
            threshold: N-gram occurrence threshold (default: 3)

        Returns:
            (has_repetition, problematic_units)
        """
        from collections import Counter

        problematic = []

        # Check 1: N-gram repetition within each unit
        for unit in units:
            if not unit.translated_text or len(unit.translated_text) < 20:
                continue

            # Tokenize and generate 3-grams
            words = self._tokenize_for_repetition_check(unit.translated_text)
            if len(words) < 3:
                continue

            ngrams = [tuple(words[i : i + 3]) for i in range(len(words) - 2)]
            ngram_counts = Counter(ngrams)

            # Check if any 3-gram exceeds threshold
            for ngram, count in ngram_counts.items():
                if count >= threshold:
                    logger.warning(
                        f"Repetition detected in unit {unit.unit_id}: "
                        f"3-gram '{' '.join(ngram)}' repeated {count} times"
                    )
                    problematic.append(unit)
                    break

        # Check 2: Cross-unit duplicate translations
        cross_unit_dups = self._detect_cross_unit_duplicates(units)
        for unit in cross_unit_dups:
            if unit not in problematic:
                problematic.append(unit)

        return len(problematic) > 0, problematic

    def _detect_cross_unit_duplicates(
        self, units: list[TextUnit], min_length: int = 5
    ) -> list[TextUnit]:
        """
        Detect when different source texts produce the same translation.

        This catches the "[Précédent]" bug where multiple different English
        headings like "Inheritance", "Derived", "Implements" all translate
        to the same French word.

        Args:
            units: TextUnits with source_text and translated_text populated
            min_length: Minimum translation length to consider (skip short strings)

        Returns:
            List of problematic TextUnits that have duplicate translations
        """
        from collections import defaultdict

        # Group units by their normalized translation
        translation_groups: dict[str, list[TextUnit]] = defaultdict(list)

        for unit in units:
            if not unit.translated_text or len(unit.translated_text.strip()) < min_length:
                continue

            # Normalize translation: lowercase, strip, collapse whitespace
            normalized = " ".join(unit.translated_text.strip().lower().split())
            translation_groups[normalized].append(unit)

        problematic = []

        for translation, group in translation_groups.items():
            if len(group) < 2:
                continue  # Not a duplicate

            # Check if the source texts are actually different
            source_texts = set(
                " ".join(u.source_text.strip().lower().split()) for u in group if u.source_text
            )

            if len(source_texts) >= 2:
                # Different source texts produced the same translation!
                logger.warning(
                    f"Cross-unit duplicate detected: {len(group)} different sources "
                    f"translated to '{translation[:50]}...'"
                )
                logger.debug(f"  Source texts: {[u.source_text[:30] for u in group[:3]]}...")
                problematic.extend(group)

        return problematic

    def _translate_single_batch_with_repetition_check(
        self,
        batch: list[TextUnit],
        mt_model: Any,
        src_lang: str,
        tgt_lang: str,
        retry_count: int = 0,
    ) -> bool:
        """
        Translate batch with real-time repetition detection and retry.

        Flow:
        1. Translate with normal parameters
        2. Check for repetition
        3. If detected -> retry with stronger anti-repetition params
        4. If still fails -> split batch and retry recursively

        Args:
            batch: TextUnits to translate
            mt_model: Translation model
            src_lang: Source language code
            tgt_lang: Target language code
            retry_count: Current retry attempt (for recursion limit)

        Returns:
            True if translation succeeded without repetition, False otherwise
        """
        # Step 1: Normal translation
        success = self._translate_single_batch(batch, mt_model, src_lang, tgt_lang)
        if not success:
            return False  # Already fell back to individual

        # Step 2: Quick repetition check
        has_repetition, problematic_units = self._detect_batch_repetition(batch)

        if not has_repetition:
            return True  # Success, no repetition

        # Step 3: Repetition detected, track stats
        self.batch_stats["repetition_detected_count"] = (
            self.batch_stats.get("repetition_detected_count", 0) + 1
        )

        logger.warning(
            f"Repetition detected in batch (size={len(batch)}). "
            f"Problematic units: {len(problematic_units)}"
        )

        # Step 4: Retry with adaptive parameters (first attempt only)
        if retry_count == 0:
            logger.info("Retrying batch with stronger anti-repetition parameters")
            self.batch_stats["repetition_retry_count"] = (
                self.batch_stats.get("repetition_retry_count", 0) + 1
            )

            # Retry with adaptive params
            adaptive_params = {
                "no_repeat_ngram_size": 4,  # Stronger (was 3)
                "repetition_penalty": 1.5,  # Stronger (was 1.2)
                "num_beams": 2,  # Add diversity
            }

            success = self._translate_single_batch(
                batch, mt_model, src_lang, tgt_lang, generation_params=adaptive_params
            )

            if not success:
                return False

            # Check again after retry
            has_repetition, _ = self._detect_batch_repetition(batch)
            if not has_repetition:
                self.batch_stats["repetition_retry_success"] = (
                    self.batch_stats.get("repetition_retry_success", 0) + 1
                )
                logger.info("Retry with adaptive params succeeded!")
                return True

        # Step 5: Still failing -> split batch and retry recursively
        if len(batch) > 1 and retry_count < 2:  # Max 2 recursive splits
            logger.warning(
                f"Repetition persists after retry. Splitting batch "
                f"(size={len(batch)} -> {len(batch) // 2} + {len(batch) - len(batch) // 2})"
            )
            self.batch_stats["repetition_split_count"] = (
                self.batch_stats.get("repetition_split_count", 0) + 1
            )

            mid = len(batch) // 2
            success_1 = self._translate_single_batch_with_repetition_check(
                batch[:mid], mt_model, src_lang, tgt_lang, retry_count + 1
            )
            success_2 = self._translate_single_batch_with_repetition_check(
                batch[mid:], mt_model, src_lang, tgt_lang, retry_count + 1
            )
            return success_1 and success_2

        # Step 6: Final fallback to individual translation
        logger.error("Repetition could not be resolved. Falling back to individual translation.")
        self.batch_stats["repetition_fallback_count"] = (
            self.batch_stats.get("repetition_fallback_count", 0) + 1
        )
        self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)
        return False

    def _is_tokenizer_available(self, model: Any) -> bool:
        """Check whether the model has a usable tokenizer attribute."""
        return getattr(model, "tokenizer", None) is not None

    def batch_translate_units(
        self,
        units: list[TextUnit],
        mt_model: Any,
        src_lang: str,
        tgt_lang: str,
        batch_size: int = 20,
        max_tokens_per_batch: int = 512,
        sort_by_length: bool = False,
    ) -> list[TextUnit]:
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
            sort_by_length: If True, sort translatable units by estimated token length
                before batching to improve batch homogeneity. Output order is always
                preserved because translations are applied in-place to unit objects.

        Returns:
            Units with translated_text populated
        """
        # Get adaptive batch size if tracker available
        if self.batch_stats_tracker:
            adaptive_size = self.batch_stats_tracker.get_batch_size(tgt_lang)
            logger.info(
                f"Adaptive batch sizing: {tgt_lang} batch_size={adaptive_size} "
                f"(baseline={batch_size})"
            )
            batch_size = adaptive_size

        # Separate translatable from non-translatable
        # E2E FIX: Also skip units that already have translations (reused from earlier phase)
        translatable = [u for u in units if not u.do_not_translate and not u.translated_text]
        non_translatable = [u for u in units if u.do_not_translate]
        already_translated = [u for u in units if not u.do_not_translate and u.translated_text]

        # TC-SCHED-001-C: optional length bucketing for batch homogeneity.
        # Sorting translatable by token length improves GPU efficiency without
        # affecting output order, because translations are applied in-place to
        # unit objects and the caller's `units` list is returned unchanged.
        if sort_by_length and translatable:
            translatable = sorted(translatable, key=lambda u: self._estimate_token_count(u.source_text))

        # Non-translatable: copy source to translated (NEVER sent to MT).
        # Fill-if-empty only: i18n-table-resolved units arrive here with
        # do_not_translate=True AND translated_text already holding the
        # approved locale value — overwriting unconditionally clobbered
        # that value back to English (P0, reference-i18n-hardening-20260725).
        for unit in non_translatable:
            if not unit.translated_text:
                unit.translated_text = unit.source_text

        # E2E FIX: Log reused translations
        if already_translated:
            logger.debug(f"Skipping {len(already_translated)} units with existing translations")

        if not translatable:
            return units

        # Dynamic batch sizing
        batches = self._yield_safe_batches(
            translatable, max_units=batch_size, max_tokens=max_tokens_per_batch
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
                self.batch_stats["total_batches"] += 1
                self.batch_stats["total_outer_batches"] += 1
                # Update run-level counter for circuit breaker (TC-03)
                TextUnitExtractor._run_total_batches[tgt_lang] = (
                    TextUnitExtractor._run_total_batches.get(tgt_lang, 0) + 1
                )

                # Translate using native list-based batching with repetition detection
                _purity_before = self.batch_stats.get("language_purity_failures", 0)
                try:
                    success = self._translate_single_batch_with_repetition_check(
                        batch, mt_model, src_lang, tgt_lang
                    )

                    # Record result to adaptive tracker
                    if self.batch_stats_tracker:
                        fallback_reason = None
                        if not success:
                            # Determine reason from batch_stats
                            if self.batch_stats.get("language_purity_failures", 0) > 0:
                                fallback_reason = "language_purity"
                            elif self.batch_stats.get("mapping_failures", 0) > 0:
                                fallback_reason = "mapping"
                            else:
                                fallback_reason = "translation_error"

                        self.batch_stats_tracker.record_batch_result(
                            language=tgt_lang,
                            batch_size=len(batch),
                            success=success,
                            fallback_reason=fallback_reason,
                        )

                    if not success:
                        # Fallback occurred, counted internally
                        self.batch_stats["fallback_batches"] += 1
                        # Count as a fully-failed outer batch if purity was the cause
                        _purity_now = self.batch_stats.get("language_purity_failures", 0)
                        if _purity_now > _purity_before:
                            self.batch_stats["failed_outer_batches"] += 1
                except Exception as e:
                    # EXCEPTION: Any error during batch processing
                    logger.error(f"Batch translation error in batch {batch_num}: {e}")
                    self.batch_stats["fallback_batches"] += 1
                    self.batch_stats["translation_errors"] += 1

                    # Record exception to adaptive tracker
                    if self.batch_stats_tracker:
                        self.batch_stats_tracker.record_batch_result(
                            language=tgt_lang,
                            batch_size=len(batch),
                            success=False,
                            fallback_reason="exception",
                        )

                    # Fallback to individual translation
                    self._fallback_to_individual(batch, mt_model, src_lang, tgt_lang)

            # Circuit breaker: check run-level purity failure rate after each batch (TC-03)
            # This check is OUTSIDE the try/except so it propagates up the call stack.
            _run_total = TextUnitExtractor._run_total_batches.get(tgt_lang, 0)
            _run_fails = TextUnitExtractor._run_purity_failures.get(tgt_lang, 0)
            if (
                TextUnitExtractor._circuit_breaker_enabled
                and _run_total >= CIRCUIT_BREAKER_MIN_BATCHES
                and _run_fails > 0
                and _run_fails / _run_total > CIRCUIT_BREAKER_THRESHOLD
            ):
                raise LanguagePurityCircuitBreakerError(
                    f"Language purity circuit breaker fired for '{tgt_lang}': "
                    f"{_run_fails / _run_total:.1%} of {_run_total} run-level batches "
                    f"produced wrong-language output. "
                    f"Use translation_engine.language_routing_overrides in global.yaml "
                    f"to route '{tgt_lang}' to a capable model (e.g., professionalize_llm)."
                )

        # Log comprehensive statistics
        self._log_batch_statistics()

        empty_units = [
            u for u in translatable if not u.translated_text or u.translated_text.strip() == ""
        ]
        if empty_units:
            self.batch_stats["empty_translations"] = len(empty_units)
            samples = [u.node_addr or u.unit_id for u in empty_units[:3]]
            logger.error(
                f"Empty translations detected for {len(empty_units)} units. Samples: {samples}"
            )

        # Alert if fallback rate exceeds threshold
        fallback_rate = self.batch_stats["fallback_batches"] / max(
            self.batch_stats["total_batches"], 1
        )
        if fallback_rate > self.fallback_rate_threshold:
            self._alert_high_fallback_rate(fallback_rate)

        # Update adaptive statistics for long-term adaptation
        if self.batch_stats_tracker:
            self.batch_stats_tracker.update_language_stats(tgt_lang)
            logger.info(
                f"Updated adaptive stats for {tgt_lang}: "
                f"current_batch_size={self.batch_stats_tracker.get_batch_size(tgt_lang)}"
            )

        return units

    def _calculate_ast_fingerprint(self, ast: list[ASTNode]) -> str:
        """Calculate fingerprint of AST structure for sanity checks."""

        def node_signature(node: ASTNode) -> str:
            """Get structural signature of node (type + children count)."""
            child_sigs = [node_signature(child) for child in node.children]
            return f"{node.type.value}({len(node.children)})[{','.join(child_sigs)}]"

        ast_sig = ",".join([node_signature(node) for node in ast])
        return hashlib.sha256(ast_sig.encode("utf-8")).hexdigest()[:16]

    def _alert_high_fallback_rate(self, fallback_rate: float):
        """Alert if fallback rate exceeds acceptable threshold."""
        logger.warning(
            f"HIGH FALLBACK RATE DETECTED: {fallback_rate:.1%} of batches falling back to individual translation. "
            f"Stats: {self.batch_stats}. Consider reducing batch_size or investigating mapping/purity issues."
        )
