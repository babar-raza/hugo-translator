"""
Tests for L4 LLM-based translation adaptation layer.
"""

from unittest.mock import Mock, patch

import pytest

from src.intelligence.llm_client import LLMClient
from src.tm.l4_llm import L4Config, L4LLMLayer, create_l4_layer
from src.tm.models import TMResult


@pytest.fixture
def l4_config():
    """Create test L4 configuration."""
    return L4Config(
        enabled=True,
        provider="ollama",
        model="llama2",
        min_similarity=0.75,
        max_similarity=0.95,
        timeout_seconds=30,
        max_latency_ms=500,
    )


@pytest.fixture
def mock_llm_client():
    """Create mock LLM client."""
    client = Mock(spec=LLMClient)
    client.is_available.return_value = True
    client.adapt_translation.return_value = "Adapted translation"
    client.test_connection.return_value = {
        "available": True,
        "provider": "ollama",
        "model": "llama2",
        "test_successful": True,
    }
    return client


def test_l4_initialization_when_enabled(l4_config):
    """Test L4 layer initialization when enabled."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_llm.return_value = mock_instance

        l4 = L4LLMLayer(l4_config)

        assert l4.config.enabled is True
        assert l4.is_available() is True


def test_l4_initialization_when_disabled():
    """Test L4 layer initialization when disabled."""
    config = L4Config(enabled=False)

    l4 = L4LLMLayer(config)

    assert l4.config.enabled is False
    assert l4.is_available() is False
    assert l4._llm_client is None


def test_l4_graceful_degradation_when_llm_unavailable(l4_config):
    """Test L4 gracefully handles unavailable LLM."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = False
        mock_llm.return_value = mock_instance

        l4 = L4LLMLayer(l4_config)

        assert l4.is_available() is False

        # Should return None when LLM unavailable
        tm_result = TMResult(
            hit=True,
            translation="Test translation",
            source="l3_semantic",
            similarity_score=0.85,
        )

        adapted = l4.adapt_match(
            source_text="Test source",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        assert adapted is None


def test_l4_skips_non_hits():
    """Test L4 skips TM misses."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True)
        l4 = L4LLMLayer(config)

        # TM miss
        tm_result = TMResult(hit=False)

        adapted = l4.adapt_match(
            source_text="Test source",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        assert adapted is None
        mock_instance.adapt_translation.assert_not_called()


def test_l4_skips_low_similarity_matches():
    """Test L4 skips matches below similarity threshold."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True, min_similarity=0.75)
        l4 = L4LLMLayer(config)

        # Low similarity match
        tm_result = TMResult(
            hit=True,
            translation="Test translation",
            source="l3_semantic",
            similarity_score=0.70,  # Below threshold
        )

        adapted = l4.adapt_match(
            source_text="Test source",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        assert adapted is None
        mock_instance.adapt_translation.assert_not_called()


def test_l4_skips_high_similarity_matches():
    """Test L4 skips matches above similarity threshold (already good)."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True, max_similarity=0.95)
        l4 = L4LLMLayer(config)

        # Very high similarity match
        tm_result = TMResult(
            hit=True,
            translation="Test translation",
            source="l3_semantic",
            similarity_score=0.98,  # Above threshold
        )

        adapted = l4.adapt_match(
            source_text="Test source",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        assert adapted is None
        mock_instance.adapt_translation.assert_not_called()


def test_l4_adapts_sweet_spot_matches():
    """Test L4 adapts matches in the sweet spot (0.75-0.95)."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_instance.adapt_translation.return_value = "Adapted translation"
        mock_llm.return_value = mock_instance

        config = L4Config(
            enabled=True,
            min_similarity=0.75,
            max_similarity=0.95,
        )
        l4 = L4LLMLayer(config)

        # Sweet spot match
        tm_result = TMResult(
            hit=True,
            translation="Original translation",
            source="l3_semantic",
            similarity_score=0.85,
        )

        adapted = l4.adapt_match(
            source_text="Test source",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        # Should call LLM
        mock_instance.adapt_translation.assert_called_once()

        # Should return adapted result
        assert adapted is not None
        assert adapted.hit is True
        assert adapted.translation == "Adapted translation"
        assert adapted.source == "l4_llm_adapted"
        assert adapted.similarity_score == 1.0  # Adapted is now "exact"


def test_l4_includes_metadata():
    """Test L4 includes metadata in adapted result."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_instance.adapt_translation.return_value = "Adapted translation"
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True, provider="ollama", model="llama2")
        l4 = L4LLMLayer(config)

        tm_result = TMResult(
            hit=True,
            translation="Original",
            source="l3_semantic",
            similarity_score=0.85,
        )

        adapted = l4.adapt_match(
            source_text="Test",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        assert adapted is not None
        assert "original_source" in adapted.metadata
        assert adapted.metadata["original_source"] == "l3_semantic"
        assert "original_similarity" in adapted.metadata
        assert adapted.metadata["original_similarity"] == 0.85
        assert "llm_provider" in adapted.metadata
        assert adapted.metadata["llm_provider"] == "ollama"
        assert "latency_ms" in adapted.metadata


def test_l4_rejects_slow_adaptations():
    """Test L4 rejects adaptations that exceed latency limit."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True

        # Simulate slow adaptation
        def slow_adapt(*args, **kwargs):
            import time
            time.sleep(0.6)  # 600ms
            return "Adapted translation"

        mock_instance.adapt_translation.side_effect = slow_adapt
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True, max_latency_ms=500)
        l4 = L4LLMLayer(config)

        tm_result = TMResult(
            hit=True,
            translation="Original",
            source="l3_semantic",
            similarity_score=0.85,
        )

        adapted = l4.adapt_match(
            source_text="Test",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        # Should reject slow adaptation
        assert adapted is None


def test_l4_handles_llm_errors():
    """Test L4 handles LLM errors gracefully."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_instance.adapt_translation.side_effect = Exception("LLM error")
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True)
        l4 = L4LLMLayer(config)

        tm_result = TMResult(
            hit=True,
            translation="Original",
            source="l3_semantic",
            similarity_score=0.85,
        )

        # Should not raise exception
        adapted = l4.adapt_match(
            source_text="Test",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        # Should return None on error
        assert adapted is None


def test_l4_handles_empty_llm_response():
    """Test L4 handles empty LLM responses."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_instance.adapt_translation.return_value = ""  # Empty response
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True)
        l4 = L4LLMLayer(config)

        tm_result = TMResult(
            hit=True,
            translation="Original",
            source="l3_semantic",
            similarity_score=0.85,
        )

        adapted = l4.adapt_match(
            source_text="Test",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
        )

        # Should return None for empty response
        assert adapted is None


def test_l4_factory_function():
    """Test create_l4_layer factory function."""
    with patch('src.tm.l4_llm.LLMClient'):
        l4 = create_l4_layer(
            enabled=True,
            provider="ollama",
            model="llama2",
            min_similarity=0.80,
        )

        assert isinstance(l4, L4LLMLayer)
        assert l4.config.enabled is True
        assert l4.config.provider == "ollama"
        assert l4.config.model == "llama2"
        assert l4.config.min_similarity == 0.80


def test_l4_test_connection():
    """Test L4 test_connection method."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_instance.test_connection.return_value = {
            "available": True,
            "test_successful": True,
        }
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True)
        l4 = L4LLMLayer(config)

        result = l4.test_connection()

        assert result["available"] is True
        assert result["test_successful"] is True


def test_l4_passes_context_to_llm():
    """Test L4 passes context to LLM for adaptation."""
    with patch('src.tm.l4_llm.LLMClient') as mock_llm:
        mock_instance = Mock()
        mock_instance.is_available.return_value = True
        mock_instance.adapt_translation.return_value = "Adapted"
        mock_llm.return_value = mock_instance

        config = L4Config(enabled=True)
        l4 = L4LLMLayer(config)

        tm_result = TMResult(
            hit=True,
            translation="Original",
            source="l3_semantic",
            similarity_score=0.85,
        )

        adapted = l4.adapt_match(
            source_text="Test source",
            tm_result=tm_result,
            source_lang="en",
            target_lang="es",
            context="This is important context",
        )

        # Verify context was passed to LLM
        call_args = mock_instance.adapt_translation.call_args
        assert call_args[1]["context"] == "This is important context"


@pytest.mark.integration
@pytest.mark.skipif(
    True,  # Skip by default - requires actual LLM
    reason="Integration test requires running Ollama/LLM"
)
def test_l4_with_real_llm():
    """Integration test with real LLM (requires Ollama running)."""
    config = L4Config(
        enabled=True,
        provider="ollama",
        model="llama2",
        min_similarity=0.75,
        max_similarity=0.95,
    )

    l4 = L4LLMLayer(config)

    if not l4.is_available():
        pytest.skip("LLM not available")

    # Test with real adaptation
    tm_result = TMResult(
        hit=True,
        translation="Hola mundo",  # Fuzzy match
        source="l3_semantic",
        similarity_score=0.85,
    )

    adapted = l4.adapt_match(
        source_text="Hello there",  # Actual source
        tm_result=tm_result,
        source_lang="en",
        target_lang="es",
    )

    assert adapted is not None
    assert adapted.translation != ""
    assert adapted.source == "l4_llm_adapted"
    assert "latency_ms" in adapted.metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
