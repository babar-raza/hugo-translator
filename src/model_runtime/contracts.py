"""
Pydantic contracts for LLM provider interactions.

Defines strict JSON-serializable contracts for:
- LLM provider configuration
- Translation request/response
- Token usage tracking

These contracts enforce type safety at runtime and can export
JSON Schema for documentation and external tooling.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token usage metrics from an LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0


class LLMProviderConfig(BaseModel):
    """Strict configuration contract for an LLM provider endpoint.

    Validated at initialization time to catch misconfigurations early.
    """

    provider: Literal["ollama", "openai", "anthropic", "openai_compatible"] = Field(
        description="LLM provider type"
    )
    model_name: str = Field(
        description="Provider-specific model name (e.g., 'qwen3:14b', 'gpt-4o')"
    )
    base_url: str | None = Field(
        default=None,
        description="API base URL. Required for ollama and openai_compatible providers.",
    )
    api_key_env: str | None = Field(
        default=None,
        description="Environment variable name holding the API key (e.g., 'OPENAI_API_KEY')",
    )
    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. Low values (0.0-0.2) for deterministic translation.",
    )
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum tokens per translation response",
    )
    timeout_seconds: int = Field(
        default=120,
        gt=0,
        description="Request timeout in seconds",
    )
    system_prompt_template: str | None = Field(
        default=None,
        description=(
            "Custom system prompt template. Use {src_lang_name} and {tgt_lang_name} "
            "as placeholders. If None, uses built-in default."
        ),
    )

    @classmethod
    def from_model_info(cls, model_info) -> LLMProviderConfig:
        """Construct from a ModelInfo dataclass.

        Args:
            model_info: ModelInfo instance with LLM-specific fields populated.

        Returns:
            Validated LLMProviderConfig.
        """
        return cls(
            provider=model_info.provider or "ollama",
            model_name=model_info.model_name or model_info.hf_model_id or model_info.model_id,
            base_url=model_info.base_url,
            api_key_env=model_info.api_key_env,
            temperature=model_info.temperature if model_info.temperature is not None else 0.1,
            max_tokens=model_info.max_tokens if model_info.max_tokens is not None else 4096,
            timeout_seconds=model_info.timeout_seconds if model_info.timeout_seconds is not None else 120,
            system_prompt_template=model_info.system_prompt_template,
        )


class TranslationRequest(BaseModel):
    """Strict input contract for a translation call."""

    texts: list[str] = Field(description="Source texts to translate")
    src_lang: str = Field(description="Source language code (ISO 639-1, e.g., 'en')")
    tgt_lang: str = Field(description="Target language code (ISO 639-1, e.g., 'fr')")
    max_tokens: int | None = Field(
        default=None, description="Override max tokens per response"
    )
    temperature: float | None = Field(
        default=None, description="Override sampling temperature"
    )


class TranslationResponse(BaseModel):
    """Strict output contract for a translation call."""

    translations: list[str] = Field(description="Translated texts (same order as input)")
    model_id: str = Field(description="Model identifier used for translation")
    backend_type: Literal["mt", "llm"] = Field(description="Backend type")
    provider: str | None = Field(
        default=None, description="LLM provider name (None for MT backends)"
    )
    token_usage: TokenUsage = Field(
        default_factory=TokenUsage, description="Token usage metrics"
    )
