"""
Unit tests for LLMModelBackend and unified LLM provider layer.

Tests cover:
- Contract validation (Pydantic models)
- ModelInfo LLM field parsing
- LLMModelBackend initialization and translation
- Provider factory and routing
- Token tracking compatibility
- Error handling and fallback behavior
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.model_runtime.contracts import (
    LLMProviderConfig,
    TokenUsage,
    TranslationRequest,
    TranslationResponse,
)
from src.model_runtime.llm_backend import LLMModelBackend, LANGUAGE_NAMES, DEFAULT_SYSTEM_PROMPT
from src.model_runtime.llm_providers import (
    BaseLLMProvider,
    OllamaProvider,
    OpenAIProvider,
    AnthropicProvider,
    OpenAICompatibleProvider,
    create_provider,
)
from src.model_runtime.registry import ModelInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ollama_model_info():
    """ModelInfo for a local Ollama LLM."""
    return ModelInfo(
        model_id="ollama_qwen3_14b",
        name="Qwen3 14B (Ollama)",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=16,
        optimal_device="api",
        provider="ollama",
        model_name="qwen3:14b",
        base_url="http://localhost:11434",
        temperature=0.1,
        max_tokens=4096,
    )


@pytest.fixture
def openai_model_info():
    """ModelInfo for an OpenAI LLM."""
    return ModelInfo(
        model_id="openai_gpt4o",
        name="GPT-4o (OpenAI)",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="api",
        provider="openai",
        model_name="gpt-4o",
        api_key_env="OPENAI_API_KEY",
        temperature=0.1,
        max_tokens=4096,
    )


@pytest.fixture
def anthropic_model_info():
    """ModelInfo for Anthropic Claude."""
    return ModelInfo(
        model_id="anthropic_claude_sonnet",
        name="Claude Sonnet",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="api",
        provider="anthropic",
        model_name="claude-sonnet-4-20250514",
        api_key_env="ANTHROPIC_API_KEY",
        temperature=0.1,
        max_tokens=4096,
    )


@pytest.fixture
def openai_compat_model_info():
    """ModelInfo for OpenAI-compatible endpoint."""
    return ModelInfo(
        model_id="local_vllm",
        name="Local vLLM",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="api",
        provider="openai_compatible",
        model_name="mistral-7b",
        base_url="http://localhost:8000/v1",
        temperature=0.1,
        max_tokens=4096,
    )


@pytest.fixture
def professionalize_model_info():
    """ModelInfo for the professionalize.com LLM."""
    return ModelInfo(
        model_id="professionalize_llm",
        name="Professionalize LLM",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="api",
        provider="openai_compatible",
        model_name="recommended",
        base_url="https://llm.professionalize.com/v1",
        api_key_env="litellm_key",
        temperature=0.0,
        max_tokens=6000,
        timeout_seconds=300,
    )


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------

class TestContracts:
    """Tests for Pydantic contract models."""

    def test_llm_provider_config_defaults(self):
        config = LLMProviderConfig(provider="ollama", model_name="qwen3:14b")
        assert config.temperature == 0.1
        assert config.max_tokens == 4096
        assert config.timeout_seconds == 120
        assert config.base_url is None

    def test_llm_provider_config_validation(self):
        with pytest.raises(Exception):
            LLMProviderConfig(provider="invalid_provider", model_name="test")

    def test_llm_provider_config_from_model_info(self, ollama_model_info):
        config = LLMProviderConfig.from_model_info(ollama_model_info)
        assert config.provider == "ollama"
        assert config.model_name == "qwen3:14b"
        assert config.base_url == "http://localhost:11434"
        assert config.temperature == 0.1

    def test_llm_provider_config_from_professionalize(self, professionalize_model_info):
        config = LLMProviderConfig.from_model_info(professionalize_model_info)
        assert config.provider == "openai_compatible"
        assert config.model_name == "recommended"
        assert config.base_url == "https://llm.professionalize.com/v1"
        assert config.api_key_env == "litellm_key"
        assert config.temperature == 0.0
        assert config.max_tokens == 6000
        assert config.timeout_seconds == 300

    def test_translation_request_model(self):
        req = TranslationRequest(
            texts=["Hello world"],
            src_lang="en",
            tgt_lang="fr",
        )
        assert len(req.texts) == 1
        assert req.src_lang == "en"

    def test_translation_response_model(self):
        resp = TranslationResponse(
            translations=["Bonjour le monde"],
            model_id="ollama_qwen3_14b",
            backend_type="llm",
            provider="ollama",
            token_usage=TokenUsage(input_tokens=10, output_tokens=8),
        )
        assert resp.backend_type == "llm"
        assert resp.token_usage.input_tokens == 10

    def test_json_schema_export(self):
        schema = LLMProviderConfig.model_json_schema()
        assert "properties" in schema
        assert "provider" in schema["properties"]

    def test_token_usage_defaults(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0


# ---------------------------------------------------------------------------
# ModelInfo LLM Field Tests
# ---------------------------------------------------------------------------

class TestModelInfoLLMFields:
    """Tests for ModelInfo with LLM-specific fields."""

    def test_to_dict_includes_llm_fields(self, ollama_model_info):
        d = ollama_model_info.to_dict()
        assert d["provider"] == "ollama"
        assert d["model_name"] == "qwen3:14b"
        assert d["base_url"] == "http://localhost:11434"
        assert d["temperature"] == 0.1

    def test_to_dict_omits_none_llm_fields(self):
        """MT models should not have LLM fields in their dict."""
        mt_info = ModelInfo(
            model_id="m2m100_418m",
            name="M2M100",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=1600,
            min_ram_gb=4,
            optimal_device="cuda",
        )
        d = mt_info.to_dict()
        assert "provider" not in d
        assert "model_name" not in d
        assert "base_url" not in d

    def test_from_dict_with_llm_fields(self):
        data = {
            "model_id": "ollama_test",
            "name": "Test Ollama",
            "backend": "llm",
            "supported_pairs": "all",
            "model_size_mb": 0,
            "min_ram_gb": 8,
            "optimal_device": "api",
            "provider": "ollama",
            "model_name": "qwen3:14b",
            "base_url": "http://localhost:11434",
            "temperature": 0.0,
            "max_tokens": 6000,
        }
        info = ModelInfo.from_dict(data)
        assert info.provider == "ollama"
        assert info.model_name == "qwen3:14b"
        assert info.temperature == 0.0
        assert info.max_tokens == 6000

    def test_from_dict_without_llm_fields(self):
        """Existing MT registry entries should still parse."""
        data = {
            "model_id": "m2m100_418m",
            "name": "M2M100",
            "backend": "huggingface",
            "supported_pairs": "all",
            "model_size_mb": 1600,
            "min_ram_gb": 4,
            "optimal_device": "cuda",
        }
        info = ModelInfo.from_dict(data)
        assert info.provider is None
        assert info.model_name is None
        assert info.base_url is None

    def test_roundtrip_llm_model_info(self, professionalize_model_info):
        d = professionalize_model_info.to_dict()
        restored = ModelInfo.from_dict(d)
        assert restored.provider == professionalize_model_info.provider
        assert restored.model_name == professionalize_model_info.model_name
        assert restored.base_url == professionalize_model_info.base_url
        assert restored.api_key_env == professionalize_model_info.api_key_env


# ---------------------------------------------------------------------------
# Provider Factory Tests
# ---------------------------------------------------------------------------

class TestProviderFactory:
    """Tests for create_provider factory."""

    def test_create_ollama_provider(self):
        config = LLMProviderConfig(
            provider="ollama", model_name="qwen3:14b",
            base_url="http://localhost:11434",
        )
        # OllamaProvider.initialize() stores config — no network call
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)

    def test_create_unknown_provider_raises(self):
        # Must bypass Pydantic validation to test factory with bad provider
        config = LLMProviderConfig.__new__(LLMProviderConfig)
        object.__setattr__(config, "provider", "nonexistent")
        object.__setattr__(config, "model_name", "test")

        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_provider(config)

    def test_openai_compatible_requires_base_url(self):
        config = LLMProviderConfig(
            provider="openai_compatible",
            model_name="test",
            base_url=None,
        )
        with pytest.raises(ValueError, match="base_url is required"):
            create_provider(config)


# ---------------------------------------------------------------------------
# LLMModelBackend Tests
# ---------------------------------------------------------------------------

class TestLLMModelBackend:
    """Tests for LLMModelBackend conforming to ModelBackend interface."""

    def test_init_sets_device_to_api(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="cuda")
        assert backend.device == "api"
        assert not backend.loaded

    def test_translate_before_load_raises(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        with pytest.raises(RuntimeError, match="not loaded"):
            backend.translate(["Hello"], "en", "fr")

    def test_translate_empty_list(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True
        backend._provider = MagicMock()

        result = backend.translate([], "en", "fr")
        assert result == []

    def test_translate_calls_provider(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        mock_provider.generate.return_value = ("Bonjour le monde", 10, 8)
        backend._provider = mock_provider

        result = backend.translate(["Hello world"], "en", "fr")
        assert result == ["Bonjour le monde"]
        mock_provider.generate.assert_called_once()

    def test_translate_batch_multiple(self, ollama_model_info):
        """LLM-WASTE-FIX-3: multi-segment batches use packed prompts."""
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        # Packed prompt returns <<<SEG_N>>> numbered output (single call) — LWF-01 delimiter
        mock_provider.generate.return_value = (
            "<<<SEG_1>>> Bonjour\n<<<SEG_2>>> Au revoir", 10, 7,
        )
        backend._provider = mock_provider

        result = backend.translate(["Hello", "Goodbye"], "en", "fr")
        assert result == ["Bonjour", "Au revoir"]
        # Packed: 1 call instead of 2
        assert mock_provider.generate.call_count == 1

    def test_translate_with_token_counts(self, ollama_model_info):
        """LLM-WASTE-FIX-3: token counts from packed call."""
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        # LWF-01: <<<SEG_N>>> delimiter
        mock_provider.generate.return_value = (
            "<<<SEG_1>>> Bonjour\n<<<SEG_2>>> Au revoir", 11, 7,
        )
        backend._provider = mock_provider

        translations, inp, out = backend.translate_with_token_counts(
            ["Hello", "Goodbye"], "en", "fr"
        )
        assert translations == ["Bonjour", "Au revoir"]
        assert inp == 11
        assert out == 7
        assert backend.last_input_tokens == 11
        assert backend.last_output_tokens == 7

    def test_translate_error_fallback_to_source(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = RuntimeError("API error")
        backend._provider = mock_provider

        result = backend.translate(["Hello"], "en", "fr")
        assert result == ["Hello"]  # Falls back to source text

    def test_translate_empty_text_passthrough(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        backend._provider = mock_provider

        result = backend.translate(["", "  "], "en", "fr")
        assert result == ["", "  "]
        mock_provider.generate.assert_not_called()

    def test_unload_calls_provider_shutdown(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True
        mock_provider = MagicMock()
        backend._provider = mock_provider

        backend.unload()
        assert not backend.loaded
        mock_provider.shutdown.assert_called_once()

    def test_get_token_count_heuristic(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        count = backend.get_token_count("Hello world this is a test")
        # 6 words * 1.3 ≈ 7
        assert count == 7

    def test_system_prompt_uses_language_names(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        prompt = backend._build_system_prompt("en", "fr")
        assert "English" in prompt
        assert "French" in prompt

    def test_system_prompt_custom_template(self, ollama_model_info):
        ollama_model_info.system_prompt_template = "Translate from {src_lang_name} to {tgt_lang_name}. Only output translation."
        backend = LLMModelBackend(ollama_model_info, device="api")
        prompt = backend._build_system_prompt("en", "de")
        assert prompt == "Translate from English to German. Only output translation."

    def test_is_loaded(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        assert not backend.is_loaded()
        backend.loaded = True
        assert backend.is_loaded()


# ---------------------------------------------------------------------------
# ModelLoader Integration Tests
# ---------------------------------------------------------------------------

class TestModelLoaderLLMIntegration:
    """Tests that ModelLoader correctly routes to LLMModelBackend."""

    def test_create_backend_routes_to_llm(self, ollama_model_info):
        """ModelLoader._create_backend should return LLMModelBackend for backend='llm'."""
        from src.model_runtime.loader import ModelLoader
        from src.model_runtime.registry import ModelRegistry

        registry = MagicMock(spec=ModelRegistry)
        loader = ModelLoader(registry=registry, device="cpu")

        backend = loader._create_backend(ollama_model_info, device="cpu")
        assert isinstance(backend, LLMModelBackend)
        assert backend.device == "api"

    def test_create_backend_routes_local_llm(self):
        """ModelLoader._create_backend should also handle 'local_llm' backend type."""
        from src.model_runtime.loader import ModelLoader
        from src.model_runtime.registry import ModelRegistry

        model_info = ModelInfo(
            model_id="test_local_llm",
            name="Test",
            backend="local_llm",
            supported_pairs="all",
            model_size_mb=0,
            min_ram_gb=0,
            optimal_device="api",
            provider="ollama",
            model_name="test:latest",
            base_url="http://localhost:11434",
        )

        registry = MagicMock(spec=ModelRegistry)
        loader = ModelLoader(registry=registry, device="cpu")

        backend = loader._create_backend(model_info, device="cpu")
        assert isinstance(backend, LLMModelBackend)


# ---------------------------------------------------------------------------
# Language Names Coverage
# ---------------------------------------------------------------------------

class TestLanguageNames:
    """Test language name mapping coverage."""

    def test_all_common_languages_covered(self):
        common = ["en", "fr", "de", "es", "it", "pt", "ru", "zh", "ja", "ko", "ar"]
        for lang in common:
            assert lang in LANGUAGE_NAMES, f"Missing language name for: {lang}"

    def test_unknown_language_uses_uppercase(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        prompt = backend._build_system_prompt("xx", "yy")
        assert "XX" in prompt
        assert "YY" in prompt
