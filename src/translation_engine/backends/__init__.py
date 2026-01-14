"""
Translation backends for pluggable translation engines.

Provides an abstract interface (ITranslationBackend) and concrete implementations:
- MTBackend: Machine Translation using M2M100, NLLB models
- LLMBackend: Large Language Model translation via Anthropic API

Usage:
    from translation_engine.backends import MTBackend, LLMBackend

    # MT backend for local GPU translation
    mt_backend = MTBackend(model_id="m2m100_418m", device="cuda")
    result = mt_backend.translate("Hello", src_lang="en", tgt_lang="es")

    # LLM backend for API-based translation
    llm_backend = LLMBackend(model_id="claude-sonnet-4", api_key=os.getenv("ANTHROPIC_API_KEY"))
    result = llm_backend.translate("Hello", src_lang="en", tgt_lang="es")
"""

from .interface import ITranslationBackend
from .mt_backend import MTBackend
from .llm_backend import LLMBackend

__all__ = [
    "ITranslationBackend",
    "MTBackend",
    "LLMBackend",
]
