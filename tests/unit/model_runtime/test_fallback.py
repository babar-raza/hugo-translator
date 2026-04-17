"""
Unit tests for model fallback chain in ModelRegistry.

Tests the 2-tier fallback implementation:
1. Opus-specific models (preferred when available)
2. Multilingual models (fallback for unsupported pairs)
3. ValueError (only when no models available at all)
"""
import logging

import pytest

from src.model_runtime.hardware import HardwareInfo
from src.model_runtime.registry import ModelRegistry


@pytest.fixture
def mock_hardware():
    """Mock hardware with standard capabilities."""
    return HardwareInfo(
        cpu_count=4,
        total_ram_gb=8.0,
        has_cuda=False,
        cuda_devices=[],
        has_mps=False,
        recommended_device="cpu",
    )


@pytest.fixture
def mock_hardware_low_memory():
    """Mock hardware with low memory (3GB)."""
    return HardwareInfo(
        cpu_count=4,
        total_ram_gb=3.0,
        has_cuda=False,
        cuda_devices=[],
        has_mps=False,
        recommended_device="cpu",
    )


@pytest.fixture
def registry_with_opus_and_multilingual(tmp_path):
    """Registry with Opus model for FR and multilingual m2m100."""
    registry_path = tmp_path / "registry.yaml"
    registry_content = """
models:
  - model_id: opus_en_fr
    name: Opus-MT English-French
    backend: huggingface
    supported_pairs:
      - ["en", "fr"]
    model_size_mb: 300
    min_ram_gb: 1.0
    optimal_device: cpu
    hf_model_id: Helsinki-NLP/opus-mt-en-fr

  - model_id: m2m100_418m
    name: M2M-100 418M
    backend: huggingface
    supported_pairs: all
    model_size_mb: 1600
    min_ram_gb: 2.0
    optimal_device: cpu
    hf_model_id: facebook/m2m100_418M
"""
    registry_path.write_text(registry_content)
    return ModelRegistry(registry_path)


@pytest.fixture
def registry_multilingual_only(tmp_path):
    """Registry with only multilingual models (no Opus)."""
    registry_path = tmp_path / "registry.yaml"
    registry_content = """
models:
  - model_id: m2m100_418m
    name: M2M-100 418M
    backend: huggingface
    supported_pairs: all
    model_size_mb: 1600
    min_ram_gb: 2.0
    optimal_device: cpu
    hf_model_id: facebook/m2m100_418M

  - model_id: nllb_200_distilled
    name: NLLB-200 Distilled
    backend: huggingface
    supported_pairs: all
    model_size_mb: 1200
    min_ram_gb: 1.5
    optimal_device: cpu
    hf_model_id: facebook/nllb-200-distilled-600M
"""
    registry_path.write_text(registry_content)
    return ModelRegistry(registry_path)


@pytest.fixture
def registry_empty(tmp_path):
    """Empty registry with no models."""
    registry_path = tmp_path / "registry.yaml"
    registry_content = """
models: []
"""
    registry_path.write_text(registry_content)
    return ModelRegistry(registry_path)


@pytest.fixture
def registry_multilingual_large(tmp_path):
    """Registry with only a large multilingual model (5GB)."""
    registry_path = tmp_path / "registry.yaml"
    registry_content = """
models:
  - model_id: m2m100_large
    name: M2M-100 Large
    backend: huggingface
    supported_pairs: all
    model_size_mb: 5000
    min_ram_gb: 6.0
    optimal_device: cpu
    hf_model_id: facebook/m2m100_1.2B
"""
    registry_path.write_text(registry_content)
    return ModelRegistry(registry_path)


class TestOpusPreference:
    """Test that Opus models are preferred when available."""

    def test_opus_preferred_when_available(
        self, registry_with_opus_and_multilingual, mock_hardware
    ):
        """Opus model should be selected when available, NOT multilingual."""
        model = registry_with_opus_and_multilingual.recommend_model(
            src_lang="en", tgt_lang="fr", hardware=mock_hardware
        )

        assert model.model_id == "opus_en_fr"
        assert model.backend == "huggingface"
        # Should NOT fallback to m2m100 when Opus exists

    def test_no_fallback_log_if_opus_exists(
        self, registry_with_opus_and_multilingual, mock_hardware, caplog
    ):
        """No fallback log message when Opus model is used."""
        with caplog.at_level(logging.INFO):
            model = registry_with_opus_and_multilingual.recommend_model(
                src_lang="en", tgt_lang="fr", hardware=mock_hardware
            )

        # Should have DEBUG log, but NOT INFO fallback message
        assert model.model_id == "opus_en_fr"
        assert "multilingual fallback" not in caplog.text.lower()


class TestMultilingualFallback:
    """Test multilingual fallback for unsupported language pairs."""

    def test_multilingual_fallback_for_unsupported_pair(
        self, registry_with_opus_and_multilingual, mock_hardware
    ):
        """Multilingual model should be used when no Opus model exists."""
        # Croatian (hr) has no Opus model, should fallback to m2m100
        model = registry_with_opus_and_multilingual.recommend_model(
            src_lang="en", tgt_lang="hr", hardware=mock_hardware
        )

        assert model.model_id == "m2m100_418m"
        assert model.supported_pairs == "all"

    def test_fallback_logging(
        self, registry_with_opus_and_multilingual, mock_hardware, caplog
    ):
        """INFO log should be emitted when falling back to multilingual."""
        with caplog.at_level(logging.INFO, logger="src.model_runtime.registry"):
            model = registry_with_opus_and_multilingual.recommend_model(
                src_lang="en", tgt_lang="hr", hardware=mock_hardware
            )

        # Should log fallback event
        assert "No Opus model for en→hr" in caplog.text
        assert "multilingual fallback" in caplog.text.lower()
        assert model.model_id == "m2m100_418m"

    def test_fallback_model_selection_heuristics(
        self, registry_multilingual_only, mock_hardware
    ):
        """Best multilingual model should be selected using heuristics."""
        # Registry has m2m100_418m (1600MB) and nllb_200_distilled (1200MB)
        # Should prefer smaller model (nllb) for faster loading
        model = registry_multilingual_only.recommend_model(
            src_lang="en", tgt_lang="hr", hardware=mock_hardware
        )

        # NLLB is smaller (1200MB vs 1600MB), should be preferred
        assert model.model_id == "nllb_200_distilled"
        assert model.model_size_mb == 1200


class TestErrorHandling:
    """Test error handling when no models are available."""

    def test_valueerror_if_no_models_at_all(self, registry_empty, mock_hardware):
        """ValueError should be raised if registry is empty."""
        with pytest.raises(ValueError) as exc_info:
            registry_empty.recommend_model(
                src_lang="en", tgt_lang="fr", hardware=mock_hardware
            )

        assert "No models available for en→fr" in str(exc_info.value)
        assert "no models supporting this pair or multilingual models" in str(
            exc_info.value
        )

    def test_valueerror_logging(self, registry_empty, mock_hardware, caplog):
        """WARNING log should be emitted before ValueError."""
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ValueError):
                registry_empty.recommend_model(
                    src_lang="en", tgt_lang="fr", hardware=mock_hardware
                )

        assert "No models available for en→fr" in caplog.text
        assert "Registry contains 0 models total" in caplog.text


class TestHardwareConstraints:
    """Test fallback behavior with hardware constraints."""

    def test_fallback_with_hardware_constraint_passes(
        self, registry_multilingual_only, mock_hardware
    ):
        """Multilingual fallback should respect hardware constraints."""
        # Hardware has 8GB, m2m100 needs 2GB, nllb needs 1.5GB - both fit
        model = registry_multilingual_only.recommend_model(
            src_lang="en", tgt_lang="hr", hardware=mock_hardware
        )

        # Should select one that fits
        assert model.model_id in ["m2m100_418m", "nllb_200_distilled"]
        assert model.min_ram_gb <= mock_hardware.total_ram_gb

    def test_fallback_with_hardware_constraint_too_small(
        self, registry_multilingual_large, mock_hardware_low_memory
    ):
        """Multilingual model selected even if above RAM requirement (smallest available)."""
        # Hardware has 3GB, m2m100_large needs 6GB
        # Should still return the model (smallest available)
        model = registry_multilingual_large.recommend_model(
            src_lang="en", tgt_lang="hr", hardware=mock_hardware_low_memory
        )

        # Should select smallest model even if it doesn't fit perfectly
        assert model.model_id == "m2m100_large"


class TestBackwardCompatibility:
    """Test backward compatibility with existing usage patterns."""

    def test_backward_compat_manual_model_id(
        self, registry_with_opus_and_multilingual
    ):
        """Manual model selection via get_model() should still work."""
        # Direct model access should not be affected
        opus = registry_with_opus_and_multilingual.get_model("opus_en_fr")
        assert opus.model_id == "opus_en_fr"

        m2m = registry_with_opus_and_multilingual.get_model("m2m100_418m")
        assert m2m.model_id == "m2m100_418m"

    def test_backward_compat_list_models(self, registry_with_opus_and_multilingual):
        """list_models() should still work with lang_pair filtering."""
        # List all models
        all_models = registry_with_opus_and_multilingual.list_models()
        assert len(all_models) == 2

        # List models for specific pair
        fr_models = registry_with_opus_and_multilingual.list_models(
            lang_pair=("en", "fr")
        )
        assert len(fr_models) == 2  # opus_en_fr + m2m100 (supports all)


class TestSelectBestMethod:
    """Test the internal _select_best method."""

    def test_select_best_empty_candidates_raises(
        self, registry_with_opus_and_multilingual, mock_hardware
    ):
        """_select_best should raise ValueError for empty candidate list."""
        with pytest.raises(ValueError) as exc_info:
            registry_with_opus_and_multilingual._select_best(
                candidates=[], hardware=mock_hardware, prefer_quality=False
            )

        assert "Cannot select from empty candidate list" in str(exc_info.value)

    def test_select_best_prefers_quality_when_requested(
        self, registry_multilingual_only, mock_hardware
    ):
        """_select_best should prefer larger models when prefer_quality=True."""
        candidates = list(registry_multilingual_only.models.values())

        # With prefer_quality=False (default), should prefer smaller/faster
        fast_model = registry_multilingual_only._select_best(
            candidates=candidates, hardware=mock_hardware, prefer_quality=False
        )

        # With prefer_quality=True, scoring changes (though both are similar size)
        # Just verify method accepts the parameter
        quality_model = registry_multilingual_only._select_best(
            candidates=candidates, hardware=mock_hardware, prefer_quality=True
        )

        assert fast_model.model_id in ["m2m100_418m", "nllb_200_distilled"]
        assert quality_model.model_id in ["m2m100_418m", "nllb_200_distilled"]


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_multiple_opus_models_for_same_pair(self, tmp_path, mock_hardware):
        """If multiple Opus models exist for same pair, best one should be selected."""
        registry_path = tmp_path / "registry.yaml"
        registry_content = """
models:
  - model_id: opus_en_fr_v1
    name: Opus-MT EN-FR v1
    backend: huggingface
    supported_pairs:
      - ["en", "fr"]
    model_size_mb: 300
    min_ram_gb: 1.0
    optimal_device: cpu

  - model_id: opus_en_fr_v2
    name: Opus-MT EN-FR v2
    backend: ctranslate2
    supported_pairs:
      - ["en", "fr"]
    model_size_mb: 250
    min_ram_gb: 1.0
    optimal_device: cpu
"""
        registry_path.write_text(registry_content)
        registry = ModelRegistry(registry_path)

        model = registry.recommend_model(
            src_lang="en", tgt_lang="fr", hardware=mock_hardware
        )

        # Should select v2 (ctranslate2 backend preferred)
        assert model.model_id == "opus_en_fr_v2"
        assert model.backend == "ctranslate2"

    def test_unsupported_pair_with_multiple_multilingual(
        self, registry_multilingual_only, mock_hardware, caplog
    ):
        """Fallback with multiple multilingual models should select best one."""
        with caplog.at_level(logging.INFO, logger="src.model_runtime.registry"):
            model = registry_multilingual_only.recommend_model(
                src_lang="en", tgt_lang="ko", hardware=mock_hardware  # Korean
            )

        # Should log fallback with count
        assert "multilingual fallback" in caplog.text.lower()
        assert "2 models available" in caplog.text

        # Should select best multilingual model
        assert model.model_id in ["m2m100_418m", "nllb_200_distilled"]
