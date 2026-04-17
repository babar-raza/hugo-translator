"""
L4 LLM-Based Translation Adaptation Layer.

Optional layer that uses local LLM to adapt fuzzy matches from L3
to better fit the specific context.
"""

import logging
import time
from dataclasses import dataclass

from ..intelligence.llm_client import LLMClient, LLMConfig
from .models import TMResult

logger = logging.getLogger(__name__)


@dataclass
class L4Config:
    """Configuration for L4 LLM layer."""

    enabled: bool = False
    provider: str = "ollama"
    model: str = "llama2"
    api_key: str | None = None
    base_url: str | None = None
    min_similarity: float = 0.75  # Only adapt matches above this threshold
    max_similarity: float = 0.95  # Don't adapt matches above this (already good)
    timeout_seconds: int = 30
    cache_adaptations: bool = True
    max_latency_ms: int = 500  # Maximum acceptable latency


class L4LLMLayer:
    """
    L4 layer using LLM for fuzzy match adaptation.

    Takes fuzzy matches from L3 and adapts them to the specific context
    using a local LLM. This is optional and can be disabled.
    """

    def __init__(self, config: L4Config):
        """
        Initialize L4 LLM layer.

        Args:
            config: L4 configuration
        """
        self.config = config
        self._llm_client: LLMClient | None = None
        self._available = False

        # Initialize LLM client if enabled
        if config.enabled:
            try:
                llm_config = LLMConfig(
                    provider=config.provider,
                    model=config.model,
                    api_key=config.api_key,
                    base_url=config.base_url,
                    timeout_seconds=config.timeout_seconds,
                )

                self._llm_client = LLMClient(llm_config)
                self._available = self._llm_client.is_available()

                if self._available:
                    logger.info(f"L4 LLM layer initialized: {config.provider}/{config.model}")
                else:
                    logger.warning("L4 LLM layer enabled but LLM not available")

            except Exception as e:
                logger.warning(f"L4 LLM initialization failed: {e}")
                self._available = False
        else:
            logger.info("L4 LLM layer disabled")

    def is_available(self) -> bool:
        """
        Check if L4 is available.

        Returns:
            True if L4 can be used, False otherwise
        """
        return self._available

    def adapt_match(
        self,
        source_text: str,
        tm_result: TMResult,
        source_lang: str,
        target_lang: str,
        context: str | None = None,
    ) -> TMResult | None:
        """
        Adapt a fuzzy TM match using LLM.

        Args:
            source_text: Original source text to translate
            tm_result: TM result with fuzzy match
            source_lang: Source language code
            target_lang: Target language code
            context: Optional context information

        Returns:
            New TMResult with adapted translation, or None if adaptation fails/skipped
        """
        # Check if L4 is available
        if not self._available or not self._llm_client:
            logger.debug("L4 not available - skipping adaptation")
            return None

        # Check if this is a candidate for adaptation
        if not tm_result.hit:
            logger.debug("No TM hit - skipping L4 adaptation")
            return None

        # Only adapt fuzzy matches in the sweet spot
        similarity = tm_result.similarity_score

        if similarity < self.config.min_similarity:
            logger.debug(f"Similarity {similarity:.2%} below threshold {self.config.min_similarity:.2%} - skipping L4")
            return None

        if similarity > self.config.max_similarity:
            logger.debug(f"Similarity {similarity:.2%} too high - match already good, skipping L4")
            return None

        # Attempt adaptation
        try:
            start_time = time.time()

            logger.info(
                f"L4 adapting fuzzy match (similarity: {similarity:.2%})"
            )

            adapted_translation = self._llm_client.adapt_translation(
                source_text=source_text,
                fuzzy_translation=tm_result.translation,
                source_lang=source_lang,
                target_lang=target_lang,
                context=context,
                similarity_score=similarity,
            )

            latency_ms = (time.time() - start_time) * 1000

            # Check latency constraint
            if latency_ms > self.config.max_latency_ms:
                logger.warning(
                    f"L4 adaptation too slow ({latency_ms:.0f}ms > {self.config.max_latency_ms}ms) - discarding"
                )
                return None

            if not adapted_translation:
                logger.warning("L4 adaptation returned empty result")
                return None

            # Create new TMResult with adapted translation
            adapted_result = TMResult(
                hit=True,
                translation=adapted_translation,
                source="l4_llm_adapted",
                similarity_score=1.0,  # Adapted translation is now exact
                metadata={
                    "original_source": tm_result.source,
                    "original_similarity": similarity,
                    "llm_provider": self.config.provider,
                    "llm_model": self.config.model,
                    "latency_ms": latency_ms,
                },
            )

            logger.info(
                f"L4 adaptation completed in {latency_ms:.0f}ms"
            )

            return adapted_result

        except Exception as e:
            logger.error(f"L4 adaptation failed: {e}")
            return None

    def test_connection(self) -> dict:
        """
        Test LLM connection.

        Returns:
            Test results dictionary
        """
        if not self._llm_client:
            return {
                "available": False,
                "error": "LLM client not initialized"
            }

        return self._llm_client.test_connection()


def create_l4_layer(
    enabled: bool = False,
    provider: str = "ollama",
    model: str = "llama2",
    **kwargs
) -> L4LLMLayer:
    """
    Factory function to create L4 layer.

    Args:
        enabled: Whether L4 is enabled
        provider: LLM provider
        model: Model name
        **kwargs: Additional config parameters

    Returns:
        Configured L4 layer
    """
    config = L4Config(
        enabled=enabled,
        provider=provider,
        model=model,
        **kwargs
    )

    return L4LLMLayer(config)


# CLI for testing
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Test L4 LLM layer")
    parser.add_argument("--provider", default="ollama", help="LLM provider")
    parser.add_argument("--model", default="llama2", help="Model name")
    parser.add_argument("--test-query", required=True, help="Source text to test")
    parser.add_argument("--fuzzy-match", default="Similar translation", help="Fuzzy match")
    parser.add_argument("--similarity", type=float, default=0.85, help="Similarity score")

    args = parser.parse_args()

    # Create L4 layer
    l4 = create_l4_layer(
        enabled=True,
        provider=args.provider,
        model=args.model,
    )

    # Test connection
    print("Testing L4 connection...")
    test_result = l4.test_connection()

    print(f"Available: {test_result['available']}")
    if not test_result['available']:
        print(f"Error: {test_result.get('error')}")
        sys.exit(1)

    print("✓ L4 layer available")

    # Test adaptation
    print("\nTesting adaptation:")
    print(f"  Source: {args.test_query}")
    print(f"  Fuzzy Match: {args.fuzzy_match}")
    print(f"  Similarity: {args.similarity:.0%}")

    # Create mock TM result
    tm_result = TMResult(
        hit=True,
        translation=args.fuzzy_match,
        source="l3_semantic",
        similarity_score=args.similarity,
    )

    # Adapt
    adapted = l4.adapt_match(
        source_text=args.test_query,
        tm_result=tm_result,
        source_lang="en",
        target_lang="es",
    )

    if adapted:
        print("\n✓ Adaptation successful:")
        print(f"  Adapted: {adapted.translation}")
        print(f"  Latency: {adapted.metadata.get('latency_ms', 0):.0f}ms")
    else:
        print("\n✗ Adaptation failed or skipped")
        sys.exit(1)
