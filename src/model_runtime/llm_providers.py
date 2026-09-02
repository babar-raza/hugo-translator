"""
Unified LLM Provider Layer.

Provides a common interface for all LLM providers:
- OllamaProvider: Native Ollama API (http://localhost:11434/api)
- OpenAIProvider: OpenAI Chat Completions API
- AnthropicProvider: Anthropic Messages API
- OpenAICompatibleProvider: Any OpenAI-compatible endpoint (vLLM, LM Studio, llama.cpp)

All providers implement BaseLLMProvider and return (text, input_tokens, output_tokens).
"""

import logging
import os
import random
import time
from abc import ABC, abstractmethod

from .contracts import LLMProviderConfig

logger = logging.getLogger(__name__)


# Injection points for tests (TC-APT-004): real sleep/jitter/clock in production.
_sleep = time.sleep
_rand = random.random
_clock = time.perf_counter


class BaseLLMProvider(ABC):
    """Common interface for all LLM providers."""

    def __init__(self) -> None:
        self._config: LLMProviderConfig | None = None

    @abstractmethod
    def initialize(self, config: LLMProviderConfig) -> None:
        """Initialize the provider with configuration."""

    @abstractmethod
    def _generate_impl(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        """Subclass implementation of generation logic."""

    @property
    def breaker_key(self) -> str:
        cfg = self._config
        return (
            getattr(cfg, "model_id", None)
            or getattr(cfg, "model_name", None)
            or type(self).__name__
        )

    def generate(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        """Hardened generate (TC-APT-004 / LLM-HARDEN-001).

        * refuses immediately with ``LLMCircuitOpenError`` while the model's breaker is open;
        * classifies every transport/provider exception (``LLMTransientError`` /
          ``LLMFatalError``) and retries transient ones with bounded backoff (+/- jitter);
        * records each logical call's outcome on the breaker and in the redacted health log;
        * still tracks attempts/completions via ``LLMRunContext``.
        Never returns the source text on failure -- it raises.
        """
        from ..observability.llm_run_context import LLMRunContext
        from .circuit_breaker import breaker_for, health_log, retry_policy
        from .llm_errors import LLMCircuitOpenError, LLMFatalError, classify_exception

        key = self.breaker_key
        breaker = breaker_for(key)
        if breaker is not None and not breaker.allow_request():
            health_log(key, event="refused", ok=False, error_kind="LLMCircuitOpenError")
            raise LLMCircuitOpenError(f"circuit breaker open for {key!r}; call refused")

        ctx = LLMRunContext.get_current()
        policy = retry_policy()
        api_key_resolved = bool(self._resolve_api_key())
        last_error: Exception | None = None
        for attempt in range(1, policy.attempts + 1):
            if ctx:
                ctx.record_attempted()
            started = _clock()
            try:
                result = self._generate_impl(system_prompt, user_text)
            except Exception as exc:
                if ctx:
                    ctx.record_failed()
                error = classify_exception(exc)
                last_error = error
                health_log(
                    key,
                    event="call",
                    ok=False,
                    attempt=attempt,
                    seconds=round(_clock() - started, 3),
                    error_class=type(exc).__name__,
                    error_kind=type(error).__name__,
                    api_key_resolved=api_key_resolved,
                )
                if isinstance(error, LLMFatalError) or attempt >= policy.attempts:
                    if breaker is not None:
                        breaker.record_failure(f"{type(exc).__name__}: {exc}"[:200])
                    raise error from exc
                _sleep(policy.delay(attempt - 1, _rand()))
                continue
            if ctx:
                ctx.record_completed(result[1], result[2])
            if breaker is not None:
                breaker.record_success()
            health_log(
                key,
                event="call",
                ok=True,
                attempt=attempt,
                seconds=round(_clock() - started, 3),
                input_tokens=result[1],
                output_tokens=result[2],
                api_key_resolved=api_key_resolved,
            )
            return result
        raise last_error or RuntimeError("unreachable")  # pragma: no cover

    def health_check(self) -> bool:
        """Test provider connectivity.

        Returns:
            True if the provider is reachable and can generate, False otherwise.
        """
        try:
            text, _, _ = self.generate(
                system_prompt="Respond with exactly: OK",
                user_text="Health check",
            )
            return bool(text.strip())
        except Exception as e:
            logger.warning("Health check failed for %s: %s", type(self).__name__, e)
            return False

    def shutdown(self) -> None:
        """Release provider resources. No-op by default."""

    def _resolve_api_key(self) -> str | None:
        """Resolve API key from the configured environment variable."""
        if self._config and self._config.api_key_env:
            return os.environ.get(self._config.api_key_env)
        return None


class OllamaProvider(BaseLLMProvider):
    """Native Ollama API provider (http://localhost:11434/api).

    Uses the requests library directly — no extra SDK needed.
    Supports keep_alive management for VRAM control.
    """

    def __init__(self) -> None:
        super().__init__()
        self._base_url: str = ""

    def initialize(self, config: LLMProviderConfig) -> None:
        self._config = config
        self._base_url = config.base_url or "http://localhost:11434"
        logger.info("OllamaProvider initialized: %s model=%s", self._base_url, config.model_name)

    def _generate_impl(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        import requests

        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "stream": False,
            "options": {
                "temperature": self._config.temperature,
                "num_predict": self._config.max_tokens,
            },
        }

        response = requests.post(url, json=payload, timeout=self._config.timeout_seconds)
        response.raise_for_status()
        data = response.json()

        text = data.get("message", {}).get("content", "").strip()
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return text, input_tokens, output_tokens

    def shutdown(self) -> None:
        """Unload model from Ollama server VRAM."""
        try:
            import requests

            requests.post(
                f"{self._base_url}/api/generate",
                json={"model": self._config.model_name, "keep_alive": 0},
                timeout=10,
            )
        except Exception:
            pass  # Best-effort unload


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Chat Completions API provider."""

    def __init__(self) -> None:
        super().__init__()
        self._client = None

    def initialize(self, config: LLMProviderConfig) -> None:
        try:
            import openai
        except ImportError:
            raise RuntimeError("openai SDK not installed. Install with: pip install openai>=1.0")

        self._config = config
        api_key = self._resolve_api_key()
        if not api_key:
            raise ValueError(
                f"OpenAI API key required. Set {config.api_key_env or 'OPENAI_API_KEY'} "
                "environment variable."
            )

        self._client = openai.OpenAI(api_key=api_key, max_retries=0)
        logger.info("OpenAIProvider initialized: model=%s", config.model_name)

    def _generate_impl(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        response = self._client.chat.completions.create(
            model=self._config.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            timeout=self._config.timeout_seconds,
        )

        content = response.choices[0].message.content
        if content is None:
            finish = response.choices[0].finish_reason
            raise ValueError(
                f"API returned no content (finish_reason={finish!r}). "
                "Increase max_tokens to allow the model to generate output."
            )
        text = content.strip()
        input_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        output_tokens = getattr(response.usage, "completion_tokens", 0) if response.usage else 0

        return text, input_tokens, output_tokens


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Messages API provider."""

    def __init__(self) -> None:
        super().__init__()
        self._client = None

    def initialize(self, config: LLMProviderConfig) -> None:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic SDK not installed. Install with: pip install anthropic>=0.30"
            )

        self._config = config
        api_key = self._resolve_api_key()
        if not api_key:
            raise ValueError(
                f"Anthropic API key required. Set {config.api_key_env or 'ANTHROPIC_API_KEY'} "
                "environment variable."
            )

        self._client = anthropic.Anthropic(api_key=api_key)
        logger.info("AnthropicProvider initialized: model=%s", config.model_name)

    def _generate_impl(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        response = self._client.messages.create(
            model=self._config.model_name,
            system=system_prompt,
            messages=[{"role": "user", "content": user_text}],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            timeout=self._config.timeout_seconds,
        )

        text = response.content[0].text.strip()
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        return text, input_tokens, output_tokens


class OpenAICompatibleProvider(BaseLLMProvider):
    """Generic OpenAI-compatible endpoint provider.

    Works with vLLM, LM Studio, llama.cpp server, text-generation-inference,
    and any other server exposing the OpenAI Chat Completions API format.
    """

    def __init__(self) -> None:
        super().__init__()
        self._client = None

    def initialize(self, config: LLMProviderConfig) -> None:
        self._config = config

        if not config.base_url:
            raise ValueError(
                "base_url is required for openai_compatible provider "
                "(e.g., 'http://localhost:8000/v1')"
            )

        try:
            import openai
        except ImportError:
            raise RuntimeError("openai SDK not installed. Install with: pip install openai>=1.0")

        api_key = self._resolve_api_key() or "not-needed"

        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            max_retries=0,  # TC-APT-004: BaseLLMProvider.generate is the single retry authority
        )
        logger.info(
            "OpenAICompatibleProvider initialized: base_url=%s model=%s",
            config.base_url,
            config.model_name,
        )

    def _generate_impl(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        response = self._client.chat.completions.create(
            model=self._config.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            timeout=self._config.timeout_seconds,
        )

        content = response.choices[0].message.content
        if content is None:
            finish = response.choices[0].finish_reason
            raise ValueError(
                f"API returned no content (finish_reason={finish!r}). "
                "Increase max_tokens to allow the model to generate output."
            )
        text = content.strip()
        input_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        output_tokens = getattr(response.usage, "completion_tokens", 0) if response.usage else 0

        return text, input_tokens, output_tokens


_PROVIDER_REGISTRY = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "openai_compatible": OpenAICompatibleProvider,
}


def create_provider(config: LLMProviderConfig) -> BaseLLMProvider:
    """Factory: create and initialize the appropriate LLM provider.

    Args:
        config: Validated provider configuration.

    Returns:
        Initialized BaseLLMProvider instance.

    Raises:
        ValueError: If provider type is unknown.
    """
    cls = _PROVIDER_REGISTRY.get(config.provider)
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider: '{config.provider}'. "
            f"Supported: {list(_PROVIDER_REGISTRY.keys())}"
        )

    provider = cls()
    provider.initialize(config)
    return provider
