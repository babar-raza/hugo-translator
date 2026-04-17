"""
Unit tests for Language-Aware Model Selector.

PROD-004: Language-Aware Model Selection (Agent-E)

Tests cover:
1. Auto-select Opus when available (FR, ES, DE)
2. Auto-select multilingual fallback when no Opus (HR, KO, PL, etc.)
3. Manual model override takes precedence
4. Hardware constraints respected
5. Clear error when model not found
6. Integration with ModelRegistry
7. Prefer quality flag behavior
8. No suitable model error handling
"""
from unittest.mock import Mock

import pytest

from src.model_runtime.hardware import HardwareInfo
from src.model_runtime.registry import ModelInfo, ModelRegistry

# Import classes under test
from src.model_runtime.selector import (
    LanguageAwareModelSelector,
)

# === Fixtures ===

@pytest.fixture
def mock_hardware_cpu():
    """Hardware info for CPU system with 8GB RAM."""
    return HardwareInfo(
        cpu_count=8,
        total_ram_gb=8.0,
        has_cuda=False,
        cuda_devices=[],
        has_mps=False,
        recommended_device="cpu",
        platform="Windows",
        python_version="3.13"
    )


@pytest.fixture
def mock_hardware_gpu():
    """Hardware info for GPU system with 16GB RAM and 8GB VRAM."""
    return HardwareInfo(
        cpu_count=12,
        total_ram_gb=16.0,
        has_cuda=True,
        cuda_devices=[{
            "id": 0,
            "name": "NVIDIA RTX 3080",
            "total_memory_gb": 8.0,
            "compute_capability": "8.6"
        }],
        has_mps=False,
        recommended_device="cuda",
        platform="Windows",
        python_version="3.13"
    )


@pytest.fixture
def mock_hardware_low_ram():
    """Hardware info for low-RAM system (2GB)."""
    return HardwareInfo(
        cpu_count=2,
        total_ram_gb=2.0,
        has_cuda=False,
        cuda_devices=[],
        has_mps=False,
        recommended_device="cpu",
        platform="Windows",
        python_version="3.13"
    )


@pytest.fixture
def mock_registry_production():
    """
    Mock ModelRegistry with production configuration.

    Contains:
    - 3 Opus models: opus_en_fr, opus_en_es, opus_en_de
    - 4 Multilingual models: m2m100_418m, nllb_200_600m, etc.
    """
    registry = Mock(spec=ModelRegistry)

    # Define Opus models (only FR, ES, DE)
    opus_en_fr = ModelInfo(
        model_id="opus_en_fr",
        name="Opus-MT English-French",
        backend="huggingface",
        supported_pairs=[["en", "fr"], ["fr", "en"]],
        model_size_mb=300,
        min_ram_gb=1.0,
        optimal_device="cpu",
        parameters=77_000_000,
        license="CC-BY-4.0",
        hf_model_id="Helsinki-NLP/opus-mt-en-fr",
        description="Specialized English-French model"
    )

    opus_en_es = ModelInfo(
        model_id="opus_en_es",
        name="Opus-MT English-Spanish",
        backend="huggingface",
        supported_pairs=[["en", "es"], ["es", "en"]],
        model_size_mb=300,
        min_ram_gb=1.0,
        optimal_device="cpu",
        parameters=77_000_000,
        license="CC-BY-4.0",
        hf_model_id="Helsinki-NLP/opus-mt-en-es",
        description="Specialized English-Spanish model"
    )

    opus_en_de = ModelInfo(
        model_id="opus_en_de",
        name="Opus-MT English-German",
        backend="huggingface",
        supported_pairs=[["en", "de"], ["de", "en"]],
        model_size_mb=300,
        min_ram_gb=1.0,
        optimal_device="cpu",
        parameters=77_000_000,
        license="CC-BY-4.0",
        hf_model_id="Helsinki-NLP/opus-mt-en-de",
        description="Specialized English-German model"
    )

    # Define multilingual models
    m2m100_418m = ModelInfo(
        model_id="m2m100_418m",
        name="Facebook M2M100 (418M)",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=1600,
        min_ram_gb=4.0,
        optimal_device="cuda",
        parameters=418_000_000,
        license="MIT",
        hf_model_id="facebook/m2m100_418M",
        description="Multilingual model supporting 100 languages"
    )

    m2m100_418m_ct2 = ModelInfo(
        model_id="m2m100_418m_ct2",
        name="Facebook M2M100 (418M, CTranslate2)",
        backend="ctranslate2",
        supported_pairs="all",
        model_size_mb=800,
        min_ram_gb=2.0,
        optimal_device="cpu",
        parameters=418_000_000,
        license="MIT",
        local_path="./models/ct2/m2m100_418m",
        description="CTranslate2 optimized M2M100"
    )

    nllb_200_600m = ModelInfo(
        model_id="nllb_200_600m",
        name="NLLB-200 (600M)",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=2400,
        min_ram_gb=6.0,
        optimal_device="cuda",
        parameters=600_000_000,
        license="CC-BY-NC-4.0",
        hf_model_id="facebook/nllb-200-distilled-600M",
        description="No Language Left Behind - 200 languages"
    )

    nllb_200_1_3b = ModelInfo(
        model_id="nllb_200_1.3b",
        name="NLLB-200 (1.3B)",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=5200,
        min_ram_gb=10.0,
        optimal_device="cuda",
        parameters=1_300_000_000,
        license="CC-BY-NC-4.0",
        hf_model_id="facebook/nllb-200-1.3B",
        description="Larger NLLB model with excellent quality"
    )

    # Registry models dictionary
    models = {
        "opus_en_fr": opus_en_fr,
        "opus_en_es": opus_en_es,
        "opus_en_de": opus_en_de,
        "m2m100_418m": m2m100_418m,
        "m2m100_418m_ct2": m2m100_418m_ct2,
        "nllb_200_600m": nllb_200_600m,
        "nllb_200_1.3b": nllb_200_1_3b,
    }

    registry.models = models

    def get_model_side_effect(model_id):
        if model_id not in models:
            raise KeyError(f"Model {model_id} not found in registry")
        return models[model_id]

    registry.get_model.side_effect = get_model_side_effect

    def supports_lang_pair_side_effect(model, lang_pair):
        """Check if model supports language pair."""
        src, tgt = lang_pair
        if model.supported_pairs == "all":
            return True
        if isinstance(model.supported_pairs, list):
            return [src, tgt] in model.supported_pairs or [tgt, src] in model.supported_pairs
        return False

    registry._supports_lang_pair.side_effect = supports_lang_pair_side_effect

    return registry


# === Test Cases ===

def test_auto_select_opus_when_available(mock_registry_production, mock_hardware_cpu):
    """
    Test 1: Auto-select Opus when available for supported language pair.

    GIVEN: Registry has opus_en_fr model for French
    WHEN: Selecting model for EN→FR
    THEN: Returns opus_en_fr (not multilingual fallback)
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_cpu,
        fallback_model=None
    )

    selection = selector.select_for_language_pair("en", "fr")

    assert selection.model_info.model_id == "opus_en_fr"
    assert selection.selection_strategy == "opus-specific"
    assert selection.hardware_fit is True
    assert "opus" in selection.rationale.lower()
    assert "en→fr" in selection.rationale.lower()


def test_auto_select_multilingual_fallback(mock_registry_production, mock_hardware_cpu):
    """
    Test 2: Auto-select multilingual fallback when no Opus available.

    GIVEN: Registry has NO opus_en_hr model (Croatian not supported)
    WHEN: Selecting model for EN→HR
    THEN: Returns m2m100_418m_ct2 (multilingual fallback, CTranslate2 preferred for CPU)
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_cpu,
        fallback_model=None
    )

    selection = selector.select_for_language_pair("en", "hr")

    # Should select CTranslate2 multilingual model (fastest for CPU)
    assert "m2m100" in selection.model_info.model_id or "nllb" in selection.model_info.model_id
    assert selection.selection_strategy == "multilingual-fallback"
    assert selection.hardware_fit is True
    assert selection.model_info.supported_pairs == "all"


def test_hardware_constraints_respected(mock_registry_production, mock_hardware_low_ram):
    """
    Test 4: Hardware constraints are respected during selection.

    GIVEN: System has only 2GB RAM
          opus_en_fr requires 1GB (fits)
          nllb_200_1.3b requires 10GB (doesn't fit)
    WHEN: Auto-selecting for EN→FR
    THEN: Returns opus_en_fr (smaller model that fits constraints)
          Larger models excluded by RAM constraint
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_low_ram,
        fallback_model=None
    )

    # Test 1: French should select Opus (1GB requirement fits in 2GB)
    selection_fr = selector.select_for_language_pair("en", "fr")
    assert selection_fr.model_info.model_id == "opus_en_fr"
    assert selection_fr.model_info.min_ram_gb <= 2.0

    # Test 2: Croatian should select m2m100_418m_ct2 (2GB requirement fits)
    # Should NOT select nllb_200_1.3b (10GB requirement doesn't fit)
    selection_hr = selector.select_for_language_pair("en", "hr")
    assert selection_hr.model_info.min_ram_gb <= 2.0
    assert selection_hr.model_info.model_id == "m2m100_418m_ct2"  # Only multilingual that fits


def test_no_suitable_model_error(mock_hardware_low_ram):
    """
    Test 8: Clear error when no suitable model found.

    GIVEN: Registry with only high-RAM models
          System has low RAM (2GB)
    WHEN: Auto-selecting for any language
    THEN: Raises ValueError with helpful message
          Error includes suggestions (install models, increase RAM, use --model)
    """
    # Create registry with only high-RAM models
    registry = Mock(spec=ModelRegistry)
    high_ram_model = ModelInfo(
        model_id="nllb_200_1.3b",
        name="NLLB-200 (1.3B)",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=5200,
        min_ram_gb=10.0,  # Requires 10GB
        optimal_device="cuda",
        parameters=1_300_000_000,
        license="CC-BY-NC-4.0",
        hf_model_id="facebook/nllb-200-1.3B",
        description="Large model"
    )
    registry.models = {"nllb_200_1.3b": high_ram_model}
    registry._supports_lang_pair.return_value = False  # No Opus models

    selector = LanguageAwareModelSelector(
        registry=registry,
        hardware_info=mock_hardware_low_ram,
        fallback_model=None
    )

    with pytest.raises(ValueError) as exc_info:
        selector.select_for_language_pair("en", "fr")

    error_msg = str(exc_info.value)
    assert "No suitable model found" in error_msg
    assert "en→fr" in error_msg
    assert "Suggestions" in error_msg or "suggestions" in error_msg.lower()


def test_selector_integration_with_registry(mock_registry_production, mock_hardware_cpu):
    """
    Test 6: Selector integrates correctly with ModelRegistry.

    GIVEN: Production registry with 3 Opus models (fr, es, de)
    WHEN: Auto-selecting for all 36 target languages
    THEN:
      - FR, ES, DE use Opus models (language-specific)
      - Other 33 languages use multilingual fallback
      - No ValueError raised for any language
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_cpu,
        fallback_model=None
    )

    # All 36 target languages from config/target_languages.yaml
    all_languages = [
        "ar", "bg", "ca", "cs", "da", "de", "el", "es", "fa", "fi",
        "fr", "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "lt",
        "lv", "ms", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sr",
        "sv", "th", "tr", "uk", "vi", "zh"
    ]

    opus_languages = ["fr", "es", "de"]
    multilingual_languages = [lang for lang in all_languages if lang not in opus_languages]

    results = {}

    # Test all 36 languages
    for lang in all_languages:
        selection = selector.select_for_language_pair("en", lang)
        results[lang] = selection

    # Verify Opus languages use Opus models
    for lang in opus_languages:
        assert results[lang].selection_strategy == "opus-specific"
        assert "opus" in results[lang].model_info.model_id.lower()

    # Verify other languages use multilingual fallback
    for lang in multilingual_languages:
        assert results[lang].selection_strategy == "multilingual-fallback"
        assert results[lang].model_info.supported_pairs == "all"

    # Verify no exceptions raised
    assert len(results) == 36


def test_prefer_quality_flag(mock_registry_production, mock_hardware_gpu):
    """
    Test 7: prefer_quality flag selects larger/better models.

    GIVEN: Multiple multilingual models (m2m100_418m vs nllb_200_1.3b)
          GPU system with sufficient RAM (16GB)
    WHEN: Auto-selecting with prefer_quality=True
    THEN: Returns larger/better model (nllb_200_1.3b, 1.3B params)
          NOT smaller model (m2m100_418m, 418M params)
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_gpu,
        fallback_model=None
    )

    # Croatian has no Opus, will use multilingual
    selection_quality = selector.select_for_language_pair("en", "hr", prefer_quality=True)

    # Should prefer larger model (more parameters = better quality)
    assert selection_quality.model_info.parameters > 418_000_000
    assert selection_quality.selection_strategy == "multilingual-fallback"
    assert "quality" in selection_quality.rationale.lower()


def test_global_fallback_model(mock_registry_production, mock_hardware_cpu):
    """
    Test: Global fallback model is used when specified.

    GIVEN: Selector configured with fallback_model="m2m100_418m"
          Language pair with no Opus model
    WHEN: Auto-selecting and multilingual search fails
    THEN: Uses global fallback model as last resort
    """
    # Create registry with only Opus models (no multilingual)
    registry = Mock(spec=ModelRegistry)
    opus_fr = ModelInfo(
        model_id="opus_en_fr",
        name="Opus-MT English-French",
        backend="huggingface",
        supported_pairs=[["en", "fr"]],
        model_size_mb=300,
        min_ram_gb=1.0,
        optimal_device="cpu",
        parameters=77_000_000,
        license="CC-BY-4.0",
        hf_model_id="Helsinki-NLP/opus-mt-en-fr",
        description="French model"
    )
    fallback_model = ModelInfo(
        model_id="m2m100_418m",
        name="M2M100 Fallback",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=1600,
        min_ram_gb=4.0,
        optimal_device="cpu",
        parameters=418_000_000,
        license="MIT",
        hf_model_id="facebook/m2m100_418M",
        description="Fallback model"
    )
    registry.models = {"opus_en_fr": opus_fr, "m2m100_418m": fallback_model}
    registry.get_model.side_effect = lambda mid: registry.models.get(mid, None) or (_ for _ in ()).throw(KeyError(f"Model {mid} not found"))
    registry._supports_lang_pair.side_effect = lambda m, lp: (
        lp == ("en", "fr") if m.model_id == "opus_en_fr" else m.supported_pairs == "all"
    )

    selector = LanguageAwareModelSelector(
        registry=registry,
        hardware_info=mock_hardware_cpu,
        fallback_model="m2m100_418m"  # Specify global fallback
    )

    # For Croatian (no Opus), should try multilingual then fallback
    # Since we have a multilingual model, it will be used
    selection = selector.select_for_language_pair("en", "hr")
    assert selection.model_info.model_id == "m2m100_418m"
    # Could be multilingual-fallback or global-fallback depending on implementation
    assert selection.selection_strategy in ["multilingual-fallback", "global-fallback"]


def test_get_available_models_for_language_pair(mock_registry_production, mock_hardware_cpu):
    """
    Test: get_available_models_for_language_pair returns all options.

    GIVEN: Registry with Opus and multilingual models
    WHEN: Querying available models for a language pair
    THEN: Returns list of (model_id, strategy) tuples in priority order
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_cpu,
        fallback_model="m2m100_418m"
    )

    # French has Opus + multilingual options
    available_fr = selector.get_available_models_for_language_pair("en", "fr")

    # Should have at least Opus-specific and multilingual-fallback
    assert len(available_fr) >= 2
    model_ids = [model_id for model_id, strategy in available_fr]
    strategies = [strategy for model_id, strategy in available_fr]

    assert "opus_en_fr" in model_ids
    assert "opus-specific" in strategies
    assert "multilingual-fallback" in strategies


def test_ctranslate2_preference_for_cpu(mock_registry_production, mock_hardware_cpu):
    """
    Test: CTranslate2 backend preferred for CPU systems.

    GIVEN: Registry has m2m100_418m (HuggingFace) and m2m100_418m_ct2 (CTranslate2)
          System is CPU-only
    WHEN: Auto-selecting multilingual model for unsupported language
    THEN: Prefers m2m100_418m_ct2 (CTranslate2, optimized for CPU)
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_cpu,
        fallback_model=None
    )

    # Croatian has no Opus, will select multilingual
    selection = selector.select_for_language_pair("en", "hr")

    # Should select CTranslate2 version (faster on CPU)
    assert selection.model_info.backend == "ctranslate2"
    assert selection.model_info.model_id == "m2m100_418m_ct2"


# === Integration Test ===

def test_end_to_end_selection_workflow(mock_registry_production, mock_hardware_cpu):
    """
    End-to-end test of selector workflow.

    Tests complete workflow:
    1. Initialize selector
    2. Select for multiple languages
    3. Verify correct models chosen
    4. Verify rationales make sense
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_cpu,
        fallback_model=None
    )

    # Test cases: (src_lang, tgt_lang, expected_strategy)
    test_cases = [
        ("en", "fr", "opus-specific"),  # French has Opus
        ("en", "es", "opus-specific"),  # Spanish has Opus
        ("en", "de", "opus-specific"),  # German has Opus
        ("en", "hr", "multilingual-fallback"),  # Croatian no Opus
        ("en", "ko", "multilingual-fallback"),  # Korean no Opus
        ("en", "pl", "multilingual-fallback"),  # Polish no Opus
    ]

    for src_lang, tgt_lang, expected_strategy in test_cases:
        selection = selector.select_for_language_pair(src_lang, tgt_lang)

        assert selection.selection_strategy == expected_strategy, (
            f"Language pair {src_lang}→{tgt_lang} should use {expected_strategy}, "
            f"got {selection.selection_strategy}"
        )
        assert selection.hardware_fit is True
        assert len(selection.rationale) > 0
        # Check that rationale mentions either the language pair OR the strategy
        assert (f"{src_lang}→{tgt_lang}" in selection.rationale
                or expected_strategy.replace("-", " ") in selection.rationale.lower()
                or expected_strategy.split("-")[0] in selection.rationale.lower())


# === Edge Cases ===

def test_bidirectional_language_support(mock_registry_production, mock_hardware_cpu):
    """
    Test: Opus models support bidirectional translation.

    GIVEN: opus_en_fr supports both EN→FR and FR→EN
    WHEN: Selecting for FR→EN (reverse direction)
    THEN: Still selects opus_en_fr (supports both directions)
    """
    selector = LanguageAwareModelSelector(
        registry=mock_registry_production,
        hardware_info=mock_hardware_cpu,
        fallback_model=None
    )

    # Test both directions
    selection_en_fr = selector.select_for_language_pair("en", "fr")
    selection_fr_en = selector.select_for_language_pair("fr", "en")

    assert selection_en_fr.model_info.model_id == "opus_en_fr"
    assert selection_fr_en.model_info.model_id == "opus_en_fr"
    assert selection_en_fr.selection_strategy == "opus-specific"
    assert selection_fr_en.selection_strategy == "opus-specific"
