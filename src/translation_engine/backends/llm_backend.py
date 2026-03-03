"""
Large Language Model backend for ITranslationBackend interface.

Delegates to the unified LLMModelBackend in model_runtime, providing
backward compatibility with the ITranslationBackend abstraction.

Supports all providers: Ollama, OpenAI, Anthropic, OpenAI-compatible.
"""

import logging
import os
from typing import List, Dict, Any, Optional

from .interface import ITranslationBackend
from src.model_runtime.registry import ModelInfo
from src.model_runtime.llm_backend import LLMModelBackend

logger = logging.getLogger(__name__)


class LLMBackend(ITranslationBackend):
    """LLM translation backend using any supported provider.

    Wraps the unified LLMModelBackend to provide ITranslationBackend interface.
    Supports Ollama, OpenAI, Anthropic, and OpenAI-compatible endpoints.

    Args:
        model_id: Model identifier (e.g., "claude-sonnet-4", "gpt-4o", "qwen3:14b")
        provider: Provider name ("ollama", "openai", "anthropic", "openai_compatible")
        api_key: API key (or None to read from environment)
        base_url: API base URL (for local/custom endpoints)
        max_tokens: Maximum tokens per translation (default: 4096)
        temperature: Sampling temperature 0-2 (default: 0.1 for deterministic)
        api_key_env: Environment variable name for API key

    Example:
        # Anthropic Claude
        backend = LLMBackend(model_id="claude-sonnet-4", provider="anthropic")

        # Local Ollama
        backend = LLMBackend(
            model_id="qwen3:14b", provider="ollama",
            base_url="http://localhost:11434"
        )

        # OpenAI-compatible (vLLM, etc.)
        backend = LLMBackend(
            model_id="mistral-7b", provider="openai_compatible",
            base_url="http://localhost:8000/v1"
        )
    """

    def __init__(
        self,
        model_id: str = "claude-sonnet-4",
        provider: str = "anthropic",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        api_key_env: Optional[str] = None,
    ):
        # If api_key provided directly, set it in env for the provider to find
        if api_key and not api_key_env:
            if provider == "anthropic":
                api_key_env = "ANTHROPIC_API_KEY"
            elif provider == "openai":
                api_key_env = "OPENAI_API_KEY"
            if api_key_env and not os.environ.get(api_key_env):
                os.environ[api_key_env] = api_key

        model_info = ModelInfo(
            model_id=f"llm_{model_id}",
            name=f"LLM {model_id}",
            backend="llm",
            supported_pairs="all",
            model_size_mb=0,
            min_ram_gb=0,
            optimal_device="api",
            provider=provider,
            model_name=model_id,
            base_url=base_url,
            api_key_env=api_key_env,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        self._backend = LLMModelBackend(model_info, device="api")
        self._backend.load()
        self.model_id = model_id

        logger.info(
            "LLMBackend initialized: provider=%s model=%s",
            provider, model_id,
        )

    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any,
    ) -> str:
        results = self._backend.translate([text], src_lang, tgt_lang)
        return results[0] if results else ""

    def translate_batch(
        self,
        texts: List[str],
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any,
    ) -> List[str]:
        return self._backend.translate(texts, src_lang, tgt_lang)

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "backend_type": "llm",
            "model_id": self.model_id,
            "device": "api",
            "provider": self._backend.model_info.provider,
        }

    def supports_language_pair(self, src_lang: str, tgt_lang: str) -> bool:
        return True

    def warmup(self) -> None:
        pass  # Already loaded in __init__

    def shutdown(self) -> None:
        self._backend.unload()
