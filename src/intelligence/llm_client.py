"""
LLM Client for Translation Adaptation.

Provides interface to LLM services for context-aware translation adaptation.
Delegates to the unified provider layer in model_runtime.llm_providers.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers."""
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass
class LLMConfig:
    """LLM client configuration."""

    provider: str = "ollama"
    model: str = "qwen3:14b"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout_seconds: int = 30
    max_retries: int = 2
    temperature: float = 0.3


class LLMClient:
    """
    Client for LLM-based translation adaptation.

    Supports multiple LLM providers for fuzzy match refinement.
    Uses the unified provider layer from model_runtime.llm_providers.
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self._provider = None
        self._available = False

        try:
            self._initialize_provider()
            self._available = True
            logger.info(f"LLM client initialized: {config.provider}/{config.model}")
        except Exception as e:
            logger.warning(f"LLM client unavailable: {e}")
            self._available = False

    def _initialize_provider(self):
        """Initialize the unified LLM provider."""
        import os
        from src.model_runtime.contracts import LLMProviderConfig
        from src.model_runtime.llm_providers import create_provider

        # If api_key provided directly, set it in env for the provider
        api_key_env = self.config.api_key_env
        if self.config.api_key and not api_key_env:
            if self.config.provider == LLMProvider.ANTHROPIC.value:
                api_key_env = "ANTHROPIC_API_KEY"
            elif self.config.provider == LLMProvider.OPENAI.value:
                api_key_env = "OPENAI_API_KEY"
            if api_key_env and self.config.api_key:
                os.environ.setdefault(api_key_env, self.config.api_key)

        provider_config = LLMProviderConfig(
            provider=self.config.provider,
            model_name=self.config.model,
            base_url=self.config.base_url,
            api_key_env=api_key_env,
            temperature=self.config.temperature,
            max_tokens=6000,
            timeout_seconds=self.config.timeout_seconds,
        )

        self._provider = create_provider(provider_config)

    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._available

    def adapt_translation(
        self,
        source_text: str,
        fuzzy_translation: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
        similarity_score: float = 0.0,
    ) -> Optional[str]:
        """
        Adapt a fuzzy translation match to better fit the context.

        Uses LLM to refine a translation from TM that doesn't exactly match.

        Args:
            source_text: Original source text
            fuzzy_translation: Translation from fuzzy match
            source_lang: Source language code
            target_lang: Target language code
            context: Optional context information
            similarity_score: Similarity score of fuzzy match (0-1)

        Returns:
            Adapted translation, or None if adaptation fails
        """
        if not self._available:
            logger.debug("LLM not available - skipping adaptation")
            return None

        prompt = self._build_adaptation_prompt(
            source_text=source_text,
            fuzzy_translation=fuzzy_translation,
            source_lang=source_lang,
            target_lang=target_lang,
            context=context,
            similarity_score=similarity_score,
        )

        try:
            start_time = time.time()
            adapted = self._call_llm(prompt)
            latency = time.time() - start_time
            logger.debug(f"LLM adaptation completed in {latency:.3f}s")
            return adapted

        except Exception as e:
            logger.error(f"LLM adaptation failed: {e}")
            return None

    def _build_adaptation_prompt(
        self,
        source_text: str,
        fuzzy_translation: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str],
        similarity_score: float,
    ) -> str:
        """Build prompt for translation adaptation."""
        prompt = f"""You are a professional translator. You have a fuzzy translation match that needs adaptation.

Source Language: {source_lang}
Target Language: {target_lang}
Similarity Score: {similarity_score:.0%}

Source Text:
{source_text}

Fuzzy Translation (from similar source):
{fuzzy_translation}
"""

        if context:
            prompt += f"""
Context:
{context}
"""

        prompt += """
Task: Adapt the fuzzy translation to accurately translate the source text. Maintain the style and terminology of the fuzzy translation, but ensure accuracy for the actual source text.

Important:
- Return ONLY the adapted translation
- Do NOT include explanations or metadata
- Preserve formatting (markdown, HTML, etc.)
- Maintain consistent terminology

Adapted Translation:"""

        return prompt

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM provider with a prompt."""
        if not self._provider:
            raise RuntimeError("LLM provider not initialized")

        result, _, _ = self._provider.generate(
            system_prompt="You are a professional translator.",
            user_text=prompt,
        )
        return result

    def unload_from_server(self) -> None:
        """Signal the LLM server to evict the model from VRAM."""
        if self._provider:
            self._provider.shutdown()

    def reconnect(self) -> bool:
        """Reinitialize the provider after a transient connectivity failure."""
        try:
            self._initialize_provider()
        except Exception as e:
            logger.warning(f"LLM reconnect failed: {e}")
            self._available = False
            return False

        self._available = True
        return True

    def test_connection(self) -> Dict[str, Any]:
        """Test LLM connection."""
        result = {
            "available": self._available,
            "provider": self.config.provider,
            "model": self.config.model,
        }

        if not self._available:
            result["error"] = "LLM client not available"
            return result

        try:
            start_time = time.time()
            response = self._call_llm("Translate 'Hello' to Spanish:")
            latency = time.time() - start_time

            result["test_successful"] = True
            result["test_response"] = response[:50]
            result["test_latency_seconds"] = latency

        except Exception as e:
            result["test_successful"] = False
            result["error"] = str(e)

        return result


def create_llm_client(
    provider: str = "ollama",
    model: str = "qwen3:14b",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    **kwargs,
) -> LLMClient:
    """
    Factory function to create LLM client.

    Args:
        provider: LLM provider (ollama, openai, anthropic, openai_compatible)
        model: Model name
        api_key: API key (for cloud providers)
        base_url: Base URL (for local providers)
        **kwargs: Additional config parameters

    Returns:
        Configured LLM client
    """
    config = LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )

    return LLMClient(config)


# CLI for testing
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Test LLM client")
    parser.add_argument("--provider", default="ollama", help="LLM provider")
    parser.add_argument("--model", default="qwen3:14b", help="Model name")
    parser.add_argument("--test-query", help="Test query to run")
    parser.add_argument("--api-key", help="API key (for cloud providers)")

    args = parser.parse_args()

    client = create_llm_client(
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
    )

    print("Testing LLM connection...")
    test_result = client.test_connection()

    print(f"\nProvider: {test_result['provider']}")
    print(f"Model: {test_result['model']}")
    print(f"Available: {test_result['available']}")

    if test_result.get("test_successful"):
        print("Connection successful")
        print(f"  Latency: {test_result['test_latency_seconds']:.3f}s")
        print(f"  Response: {test_result['test_response']}")
    else:
        print(f"Connection failed: {test_result.get('error')}")
        sys.exit(1)

    if args.test_query:
        print(f"\nRunning test query: {args.test_query}")
        adapted = client.adapt_translation(
            source_text=args.test_query,
            fuzzy_translation="[fuzzy match placeholder]",
            source_lang="en",
            target_lang="es",
        )

        if adapted:
            print(f"Result: {adapted}")
        else:
            print("Adaptation failed")
