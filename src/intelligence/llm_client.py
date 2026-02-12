"""
LLM Client for Translation Adaptation.

Provides interface to local LLM services (Ollama, OpenAI) for
context-aware translation adaptation.
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


@dataclass
class LLMConfig:
    """LLM client configuration."""

    provider: str = "ollama"
    model: str = "qwen3:14b"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout_seconds: int = 30
    max_retries: int = 2
    temperature: float = 0.3


class LLMClient:
    """
    Client for LLM-based translation adaptation.

    Supports multiple LLM providers for fuzzy match refinement.
    """

    def __init__(self, config: LLMConfig):
        """
        Initialize LLM client.

        Args:
            config: LLM configuration
        """
        self.config = config
        self._client = None
        self._available = False

        # Try to initialize client
        try:
            self._initialize_client()
            self._available = True
            logger.info(f"LLM client initialized: {config.provider}/{config.model}")
        except Exception as e:
            logger.warning(f"LLM client unavailable: {e}")
            self._available = False

    def _initialize_client(self):
        """Initialize the LLM provider client."""
        if self.config.provider == LLMProvider.OLLAMA.value:
            self._initialize_ollama()
        elif self.config.provider == LLMProvider.OPENAI.value:
            self._initialize_openai()
        elif self.config.provider == LLMProvider.ANTHROPIC.value:
            self._initialize_anthropic()
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")

    def _initialize_ollama(self):
        """Initialize Ollama client."""
        try:
            import requests

            # Check if Ollama is running
            base_url = self.config.base_url or "http://localhost:11434"
            response = requests.get(f"{base_url}/api/tags", timeout=5)
            response.raise_for_status()

            # Store client info
            self._client = {
                "type": "ollama",
                "base_url": base_url,
            }

            logger.info(f"Ollama available at {base_url}")

        except Exception as e:
            raise RuntimeError(f"Ollama initialization failed: {e}")

    def _initialize_openai(self):
        """Initialize OpenAI client."""
        try:
            import openai

            if not self.config.api_key:
                raise ValueError("OpenAI API key required")

            # Create client
            client = openai.OpenAI(api_key=self.config.api_key)

            # Test connection
            client.models.list()

            self._client = {
                "type": "openai",
                "client": client,
            }

            logger.info("OpenAI client initialized")

        except ImportError:
            raise RuntimeError("OpenAI library not installed: pip install openai")
        except Exception as e:
            raise RuntimeError(f"OpenAI initialization failed: {e}")

    def _initialize_anthropic(self):
        """Initialize Anthropic client."""
        try:
            import anthropic

            if not self.config.api_key:
                raise ValueError("Anthropic API key required")

            # Create client
            client = anthropic.Anthropic(api_key=self.config.api_key)

            self._client = {
                "type": "anthropic",
                "client": client,
            }

            logger.info("Anthropic client initialized")

        except ImportError:
            raise RuntimeError("Anthropic library not installed: pip install anthropic")
        except Exception as e:
            raise RuntimeError(f"Anthropic initialization failed: {e}")

    def is_available(self) -> bool:
        """
        Check if LLM is available.

        Returns:
            True if LLM can be used, False otherwise
        """
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

        # Build prompt
        prompt = self._build_adaptation_prompt(
            source_text=source_text,
            fuzzy_translation=fuzzy_translation,
            source_lang=source_lang,
            target_lang=target_lang,
            context=context,
            similarity_score=similarity_score,
        )

        # Call LLM
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
        """
        Build prompt for translation adaptation.

        Args:
            source_text: Source text
            fuzzy_translation: Fuzzy match translation
            source_lang: Source language
            target_lang: Target language
            context: Optional context
            similarity_score: Match similarity

        Returns:
            Formatted prompt
        """
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
        """
        Call the LLM with a prompt.

        Args:
            prompt: Prompt text

        Returns:
            LLM response text

        Raises:
            RuntimeError: If LLM call fails
        """
        if not self._client:
            raise RuntimeError("LLM client not initialized")

        client_type = self._client["type"]

        if client_type == "ollama":
            return self._call_ollama(prompt)
        elif client_type == "openai":
            return self._call_openai(prompt)
        elif client_type == "anthropic":
            return self._call_anthropic(prompt)
        else:
            raise RuntimeError(f"Unknown client type: {client_type}")

    def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API."""
        import requests

        base_url = self._client["base_url"]
        url = f"{base_url}/api/generate"

        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
            }
        }

        response = requests.post(
            url,
            json=payload,
            timeout=self.config.timeout_seconds
        )
        response.raise_for_status()

        result = response.json()
        return result.get("response", "").strip()

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API."""
        client = self._client["client"]

        response = client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": "You are a professional translator."},
                {"role": "user", "content": prompt}
            ],
            temperature=self.config.temperature,
            timeout=self.config.timeout_seconds,
        )

        return response.choices[0].message.content.strip()

    def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic API."""
        client = self._client["client"]

        message = client.messages.create(
            model=self.config.model,
            max_tokens=1024,
            temperature=self.config.temperature,
            messages=[
                {"role": "user", "content": prompt}
            ],
            timeout=self.config.timeout_seconds,
        )

        return message.content[0].text.strip()

    def test_connection(self) -> Dict[str, Any]:
        """
        Test LLM connection.

        Returns:
            Dictionary with connection test results
        """
        result = {
            "available": self._available,
            "provider": self.config.provider,
            "model": self.config.model,
        }

        if not self._available:
            result["error"] = "LLM client not available"
            return result

        try:
            # Test with simple prompt
            start_time = time.time()
            response = self._call_llm("Translate 'Hello' to Spanish:")
            latency = time.time() - start_time

            result["test_successful"] = True
            result["test_response"] = response[:50]  # First 50 chars
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
    **kwargs
) -> LLMClient:
    """
    Factory function to create LLM client.

    Args:
        provider: LLM provider (ollama, openai, anthropic)
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
        **kwargs
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

    # Create client
    client = create_llm_client(
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
    )

    # Test connection
    print("Testing LLM connection...")
    test_result = client.test_connection()

    print(f"\nProvider: {test_result['provider']}")
    print(f"Model: {test_result['model']}")
    print(f"Available: {test_result['available']}")

    if test_result.get("test_successful"):
        print(f"✓ Connection successful")
        print(f"  Latency: {test_result['test_latency_seconds']:.3f}s")
        print(f"  Response: {test_result['test_response']}")
    else:
        print(f"✗ Connection failed: {test_result.get('error')}")
        sys.exit(1)

    # Run test query if provided
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
