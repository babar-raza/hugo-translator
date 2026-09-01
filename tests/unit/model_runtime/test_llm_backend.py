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

from unittest.mock import MagicMock

import pytest

from src.model_runtime.contracts import (
    LLMProviderConfig,
    TokenUsage,
    TranslationRequest,
    TranslationResponse,
)
from src.model_runtime.llm_backend import LANGUAGE_NAMES, LLMModelBackend
from src.model_runtime.llm_providers import (
    OllamaProvider,
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
        with pytest.raises((ValueError, KeyError)):
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
            provider="ollama",
            model_name="qwen3:14b",
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
        # Packed prompt returns <<<SEG_N>>> numbered output (single call)
        mock_provider.generate.return_value = (
            "<<<SEG_1>>> Bonjour\n<<<SEG_2>>> Au revoir",
            10,
            7,
        )
        backend._provider = mock_provider

        result = backend.translate(["Hello", "Goodbye"], "en", "fr")
        assert result == ["Bonjour", "Au revoir"]
        # Packed: 1 call instead of 2
        assert mock_provider.generate.call_count == 1

    def test_retry_feedback_is_system_context_not_source_text(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True
        mock_provider = MagicMock()
        mock_provider.generate.return_value = ("हिंदी लिंक", 10, 4)
        backend._provider = mock_provider

        result = backend.translate_with_retry_feedback(
            ["Aspose.Cells — Enterprise Blog"],
            "en",
            "hi",
            retry_feedback="Translate every link label fully into hi.",
        )

        assert result == ["हिंदी लिंक"]
        kwargs = mock_provider.generate.call_args.kwargs
        assert "Translate every link label fully into hi." not in kwargs["user_text"]
        assert kwargs["user_text"].endswith("— Enterprise Blog")
        assert "Translate every link label fully into hi." in kwargs["system_prompt"]

        mock_provider.reset_mock()
        mock_provider.generate.return_value = ("सामान्य", 8, 2)
        backend.translate(["Normal source"], "en", "hi")
        assert (
            "Translate every link label fully into hi."
            not in mock_provider.generate.call_args.kwargs["system_prompt"]
        )

    def test_context_hint_and_retry_feedback_compose(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True
        mock_provider = MagicMock()
        mock_provider.generate.return_value = ("हिंदी विवरण", 10, 4)
        backend._provider = mock_provider

        backend.translate_with_context(
            ["Technical description"],
            "en",
            "hi",
            context_hint="frontmatter_description",
            retry_feedback="Translate description fully into hi.",
        )

        prompt = mock_provider.generate.call_args.kwargs["system_prompt"]
        assert "technical documentation translator" in prompt
        assert "Translate description fully into hi." in prompt

    def test_packed_retry_feedback_does_not_modify_numbered_sources(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True
        mock_provider = MagicMock()
        mock_provider.generate.return_value = (
            "<<<SEG_1>>> पहला\n<<<SEG_2>>> दूसरा",
            20,
            6,
        )
        backend._provider = mock_provider

        result = backend.translate_with_retry_feedback(
            ["First source", "Second source"],
            "en",
            "hi",
            retry_feedback="Preserve every claim.",
        )

        assert result == ["पहला", "दूसरा"]
        kwargs = mock_provider.generate.call_args.kwargs
        assert "Preserve every claim." in kwargs["system_prompt"]
        assert "Preserve every claim." not in kwargs["user_text"]
        assert "<<<SEG_1>>> First source" in kwargs["user_text"]
        assert "<<<SEG_2>>> Second source" in kwargs["user_text"]

    def test_translate_with_token_counts(self, ollama_model_info):
        """LLM-WASTE-FIX-3: token counts from packed call."""
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        # Packed prompt returns <<<SEG_N>>> numbered output (single call)
        mock_provider.generate.return_value = (
            "<<<SEG_1>>> Bonjour\n<<<SEG_2>>> Au revoir",
            11,
            7,
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
        ollama_model_info.system_prompt_template = (
            "Translate from {src_lang_name} to {tgt_lang_name}. Only output translation."
        )
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


# ---------------------------------------------------------------------------
# TC-HT-003: Prompt-echo / refusal validation
# ---------------------------------------------------------------------------


class TestValidateLlmResponse:
    """Unit tests for LLMModelBackend._validate_llm_response()."""

    def _prompt(self):
        return LLMModelBackend(
            ModelInfo(
                model_id="x",
                name="x",
                backend="llm",
                supported_pairs="all",
                model_size_mb=0,
                min_ram_gb=0,
                optimal_device="api",
                provider="ollama",
                model_name="x",
                base_url="http://x",
            ),
            device="api",
        )._build_system_prompt("en", "es")

    def test_english_rule_echo_rejected(self):
        response = (
            "Rules:\n"
            "- Output ONLY the translation, nothing else\n"
            "- Preserve all formatting: markdown, HTML tags, links\n"
        )
        reason = LLMModelBackend._validate_llm_response(response, "Do", self._prompt())
        assert reason in ("rule_header_leak", "prompt_echo_en")

    def test_translated_rule_dump_rejected(self):
        response = (
            "- Salida SOLO la traduccion, nada mas\n"
            "- Preservar todo el formato: markdown, etiquetas HTML, enlaces\n"
        )
        reason = LLMModelBackend._validate_llm_response(response, "Do", self._prompt())
        assert reason == "list_marker_leak"

    def test_refusal_rejected(self):
        response = "I cannot translate this content."
        reason = LLMModelBackend._validate_llm_response(response, "Do", self._prompt())
        assert reason == "refusal"

    def test_empty_response_rejected_as_refusal(self):
        reason = LLMModelBackend._validate_llm_response("   ", "Do", self._prompt())
        assert reason == "refusal"

    def test_legitimate_short_translation_passes(self):
        reason = LLMModelBackend._validate_llm_response("Faire", "Do", self._prompt())
        assert reason is None

    def test_genuine_list_translation_passes(self):
        """Source itself has list markers — response having them too is fine."""
        source = "- Step one\n- Step two"
        response = "- Paso uno\n- Paso dos"
        reason = LLMModelBackend._validate_llm_response(response, source, self._prompt())
        assert reason is None

    def test_rule_header_leak_structural_translated(self):
        """Language-agnostic structural match: a short colon-terminated
        header line followed by list markers, regardless of the word used
        for 'Rules' in the target language."""
        response = "Reglas:\n- uno\n- dos\n"
        reason = LLMModelBackend._validate_llm_response(response, "Do", self._prompt())
        assert reason in ("rule_header_leak", "list_marker_leak")

    def test_mid_string_conversational_reply_not_anchored_at_start_is_rejected(self):
        """HT-QUALITY-GATES-001 Part 22 (1.6): _REFUSAL_RE only matches at
        the START of the response, so a conversational reply that doesn't
        happen to open with a refusal phrase used to pass every check here
        and ship as translated content. Real confirmed instance: this exact
        sentence shipped verbatim to docs.aspose.org/no/email/net/
        developer-guide/features.md, matching zero entries in either
        _REFUSAL_RE or the old REFUSAL_PHRASES list."""
        response = (
            "I'm sorry, but I can't access or read any attached files. If you "
            "paste the text you'd like translated directly into the chat, "
            "I'll be happy to translate it for you."
        )
        reason = LLMModelBackend._validate_llm_response(response, "Do", self._prompt())
        assert reason == "refusal"

    def test_keywords_entry_conversational_question_is_rejected(self):
        """Real confirmed instance: this exact string shipped as a raw
        frontmatter `keywords:` list entry on
        kb.aspose.org/uk/slides/cpp/how-to-create-presentations-cpp.md —
        short, question-shaped, first/second-person conversational register
        that never legitimately occurs in this corpus."""
        response = "Could you please provide the English text you'd like translated into Ukrainian?"
        reason = LLMModelBackend._validate_llm_response(response, "Do", self._prompt())
        assert reason == "refusal"

    def test_legitimate_translation_containing_a_question_mark_passes(self):
        """False-positive guard: a genuine translated FAQ-style question
        must not be rejected just because it ends in '?' — the shape
        patterns are scoped to specific first/second-person conversational
        markers ("could you provide", "i'm sorry", "let me know if"), not a
        blanket question-mark check."""
        response = "¿Cómo instalo la biblioteca?"
        reason = LLMModelBackend._validate_llm_response(
            response, "How do I install the library?", self._prompt()
        )
        assert reason is None


class TestLlmEchoRejectIntegration:
    """End-to-end: translate() must passthrough source on an echo/refusal
    response, and record the reject reason for provenance."""

    def test_translate_passes_through_on_rule_echo(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        mock_provider.generate.return_value = (
            "Rules:\n- Output ONLY the translation\n- Do not add commentary\n",
            10,
            8,
        )
        backend._provider = mock_provider

        result = backend.translate(["Do"], "en", "es")
        assert result == ["Do"]  # passthrough, not the echoed rules
        assert backend.last_reject_reasons.get(0) is not None

    def test_translate_passes_through_on_refusal(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        mock_provider.generate.return_value = ("I cannot translate this.", 5, 5)
        backend._provider = mock_provider

        result = backend.translate(["Hello"], "en", "es")
        assert result == ["Hello"]
        assert backend.last_reject_reasons.get(0) == "refusal"

    def test_translate_accepts_legitimate_translation(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        mock_provider.generate.return_value = ("Hola", 5, 3)
        backend._provider = mock_provider

        result = backend.translate(["Hello"], "en", "es")
        assert result == ["Hola"]
        assert 0 not in backend.last_reject_reasons

    def test_packed_batch_rejects_per_item_echo(self, ollama_model_info):
        """One segment in a packed batch refuses; the other is legit — only
        the refusing segment should be rejected/passed-through. (Packed
        output is one line per <<<SEG_N>>> marker, so the echo/refusal
        fixture here must be single-line to survive _parse_packed_output.)
        """
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        mock_provider.generate.return_value = (
            "<<<SEG_1>>> Hola\n<<<SEG_2>>> I cannot translate this content.",
            20,
            15,
        )
        backend._provider = mock_provider

        result = backend.translate(["Hello", "Goodbye"], "en", "es")
        assert result[0] == "Hola"
        assert result[1] == "Goodbye"  # rejected → passthrough source
        assert 1 in backend.last_reject_reasons
        assert 0 not in backend.last_reject_reasons

    def test_reject_reasons_reset_between_calls(self, ollama_model_info):
        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        mock_provider = MagicMock()
        mock_provider.generate.return_value = ("I cannot translate this.", 5, 5)
        backend._provider = mock_provider
        backend.translate(["Hello"], "en", "es")
        assert 0 in backend.last_reject_reasons

        mock_provider.generate.return_value = ("Hola", 5, 3)
        backend.translate(["Hello"], "en", "es")
        assert 0 not in backend.last_reject_reasons


class TestTranslateWithContextConcurrency:
    """HT-QUALITY-GATES-001 Part 22 (root cause B, LLM prompt-context race).

    ModelLoader caches ONE LLMModelBackend instance per model, shared across
    every concurrent worker thread. translate_with_context() used to stash
    context_hint/file_context as plain instance attributes on that shared
    backend, read back later inside prompt-building -- two threads
    translating different files concurrently could interleave, so file A's
    prompt got built with file B's class context. Fixed via
    contextvars.ContextVar, which gives each thread its own independent view.

    This test proves the fix with REAL thread interleaving (not hope): a
    barrier forces thread A to set its context, yield to thread B (which
    sets a DIFFERENT context and completes its own generate() call), and
    only then does thread A's own generate() call run and read the context
    back. Before the fix, thread A's prompt would contain thread B's class
    name.
    """

    def test_two_threads_do_not_leak_context_into_each_others_prompt(self, ollama_model_info):
        import threading

        backend = LLMModelBackend(ollama_model_info, device="api")
        backend.loaded = True

        thread_a_ready = threading.Event()
        thread_b_done = threading.Event()
        captured_prompts: dict[str, str] = {}

        # ONE shared generate() (matching production: both threads call
        # through the same real shared backend/provider instance) that
        # identifies which thread is calling via threading.current_thread()
        # -- not via reconfiguring the mock per thread, which would just add
        # a race in the test harness itself rather than exercising the
        # production ContextVar fix.
        def _generate(system_prompt, user_text):
            name = threading.current_thread().name
            if name == "A":
                # Yield control to thread B before reading/using context,
                # forcing the exact interleaving the original bug needed.
                thread_a_ready.set()
                thread_b_done.wait(timeout=5)
            captured_prompts[name] = system_prompt
            if name == "B":
                thread_b_done.set()
            return (f"translated-by-{name}", 5, 5)

        provider = MagicMock()
        provider.generate.side_effect = _generate
        backend._provider = provider

        results = {}

        def run_thread_a():
            results["A"] = backend.translate_with_context(
                ["desc text"], "en", "es",
                context_hint="api_property_description",
                file_context={"class_name": "ClassA", "product": "cells/net"},
            )

        def run_thread_b():
            thread_a_ready.wait(timeout=5)
            results["B"] = backend.translate_with_context(
                ["desc text"], "en", "fr",
                context_hint="api_property_description",
                file_context={"class_name": "ClassB", "product": "words/python"},
            )

        t_a = threading.Thread(target=run_thread_a, name="A")
        t_b = threading.Thread(target=run_thread_b, name="B")
        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

        assert "A" in captured_prompts and "B" in captured_prompts
        assert "ClassA" in captured_prompts["A"]
        assert "ClassB" not in captured_prompts["A"], (
            "Thread A's prompt was built with Thread B's class context -- "
            "the exact cross-file contamination this fix closes."
        )
        assert "ClassB" in captured_prompts["B"]
        assert "ClassA" not in captured_prompts["B"]
