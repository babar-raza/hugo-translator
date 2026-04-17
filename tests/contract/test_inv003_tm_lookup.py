"""
CONTRACT: specs/core_invariants.md

Verifies Translation Memory lookup follows L1 -> L2 -> L3 cascade order,
stopping at first hit and promoting results up the hierarchy.

INV-003 Core Invariant: TM Lookup Order

Key Guarantees:
1. L1 (in-memory cache) checked first (fastest, < 1us)
2. L2 (LMDB persistent) checked only if L1 miss
3. L3 (FAISS semantic) checked only if L1 and L2 miss
4. First match wins - no unnecessary lookups
5. Cache warming: hits promoted up the hierarchy
"""

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest

# ==============================================================================
# Mock Classes for Testing
# ==============================================================================


@dataclass
class MockSemanticMatch:
    """Mock for L3 semantic search result."""
    translation: str
    similarity: float
    metadata: dict[str, Any] | None = None


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def mock_l1_cache():
    """
    Mock L1Cache with configurable hit/miss behavior.

    Default: Returns None (cache miss)
    """
    l1 = Mock()
    l1.get.return_value = None  # Default: miss
    l1.put = Mock()
    l1.stats.return_value = {
        "hits": 0, "misses": 0, "evictions": 0,
        "size": 0, "max_size": 10000, "hit_rate": 0.0
    }
    return l1


@pytest.fixture
def mock_l2_persistent():
    """
    Mock L2PersistentTM with configurable hit/miss behavior.

    Default: Returns None (cache miss)
    """
    l2 = Mock()
    l2.exact_lookup.return_value = None  # Default: miss
    l2.__len__ = Mock(return_value=0)
    return l2


@pytest.fixture
def mock_l3_semantic():
    """
    Mock L3SemanticTM with configurable hit/miss behavior.

    Default: Returns empty list (no matches)
    """
    l3 = Mock()
    l3.semantic_search.return_value = []  # Default: no matches
    l3.__len__ = Mock(return_value=0)
    return l3


@pytest.fixture
def mock_override_controller():
    """
    Mock OverrideController with NORMAL mode (no bypass).
    """
    controller = Mock()
    controller.should_bypass_lookup.return_value = False
    controller.should_update_cache.return_value = True
    controller.get_stats.return_value = {"mode": "NORMAL"}
    return controller


@pytest.fixture
def translation_memory(mock_l1_cache, mock_l2_persistent, mock_l3_semantic, mock_override_controller):
    """
    TranslationMemory instance with all mocked layers.
    """
    from src.tm.translation_memory import TranslationMemory

    return TranslationMemory(
        l1_cache=mock_l1_cache,
        l2_persistent=mock_l2_persistent,
        l3_semantic=mock_l3_semantic,
        override_controller=mock_override_controller,
    )


@pytest.fixture
def sample_lookup_params():
    """Standard lookup parameters for tests."""
    return {
        "site_id": "test.example.com",
        "src_lang": "en",
        "tgt_lang": "de",
        "text": "Hello world",
    }


# ==============================================================================
# INV-003: L1 Hit Skips L2 and L3 Tests
# ==============================================================================


@pytest.mark.contract
def test_l1_hit_skips_l2_and_l3_lookup(
    translation_memory,
    mock_l1_cache,
    mock_l2_persistent,
    mock_l3_semantic,
    sample_lookup_params,
):
    """
    Verify L1 cache hit prevents L2 and L3 lookups.

    CONTRACT: INV-003 - L1 hit skips downstream layers
    Evidence: src/tm/translation_memory.py lines 101-110
    """
    # Arrange - L1 returns a cached translation
    cached_translation = "Hallo Welt"
    mock_l1_cache.get.return_value = cached_translation

    # Act
    result = translation_memory.lookup(**sample_lookup_params)

    # Assert - L1 was called
    mock_l1_cache.get.assert_called_once_with(
        sample_lookup_params["site_id"],
        sample_lookup_params["src_lang"],
        sample_lookup_params["tgt_lang"],
        sample_lookup_params["text"],
    )

    # Assert - L2 and L3 were NOT called
    mock_l2_persistent.exact_lookup.assert_not_called()
    mock_l3_semantic.semantic_search.assert_not_called()

    # Assert - Result indicates L1 cache hit
    assert result.hit is True
    assert result.source == "l1_cache"
    assert result.translation == cached_translation
    assert result.confidence == 1.0


@pytest.mark.contract
def test_l1_hit_does_not_update_cache(
    translation_memory,
    mock_l1_cache,
    sample_lookup_params,
):
    """
    Verify L1 hit does not trigger cache promotion (already in L1).

    CONTRACT: INV-003 - No unnecessary cache updates
    Evidence: src/tm/translation_memory.py lines 101-110
    """
    # Arrange - L1 returns a cached translation
    mock_l1_cache.get.return_value = "Hallo Welt"

    # Act
    translation_memory.lookup(**sample_lookup_params)

    # Assert - L1.put not called (already in cache)
    mock_l1_cache.put.assert_not_called()


# ==============================================================================
# INV-003: L2 Hit Skips L3 and Promotes to L1 Tests
# ==============================================================================


@pytest.mark.contract
def test_l2_hit_skips_l3_and_promotes_to_l1(
    translation_memory,
    mock_l1_cache,
    mock_l2_persistent,
    mock_l3_semantic,
    sample_lookup_params,
):
    """
    Verify L2 persistent hit prevents L3 lookup and promotes to L1.

    CONTRACT: INV-003 - L2 hit skips L3, promotes to L1
    Evidence: src/tm/translation_memory.py lines 112-124
    """
    # Arrange - L1 miss, L2 returns entry
    mock_l1_cache.get.return_value = None

    l2_entry = Mock()
    l2_entry.translation = "Hallo Welt"
    l2_entry.metadata = {"source": "l2_test"}
    mock_l2_persistent.exact_lookup.return_value = l2_entry

    # Act
    result = translation_memory.lookup(**sample_lookup_params)

    # Assert - L1 and L2 were called
    mock_l1_cache.get.assert_called_once()
    mock_l2_persistent.exact_lookup.assert_called_once()

    # Assert - L3 was NOT called
    mock_l3_semantic.semantic_search.assert_not_called()

    # Assert - L1 cache was populated (cache warming)
    mock_l1_cache.put.assert_called_once_with(
        sample_lookup_params["site_id"],
        sample_lookup_params["src_lang"],
        sample_lookup_params["tgt_lang"],
        sample_lookup_params["text"],
        l2_entry.translation,
    )

    # Assert - Result indicates L2 exact hit
    assert result.hit is True
    assert result.source == "l2_exact"
    assert result.translation == "Hallo Welt"
    assert result.confidence == 1.0


# ==============================================================================
# INV-003: L3 Hit Promotes to L1 Tests
# ==============================================================================


@pytest.mark.contract
def test_l3_hit_promotes_to_l1_cache(
    translation_memory,
    mock_l1_cache,
    mock_l2_persistent,
    mock_l3_semantic,
    sample_lookup_params,
):
    """
    Verify L3 semantic hit promotes result to L1 cache.

    CONTRACT: INV-003 - L3 hit promotes to L1
    Evidence: src/tm/translation_memory.py lines 126-153
    """
    # Arrange - L1 miss, L2 miss, L3 returns semantic match
    mock_l1_cache.get.return_value = None
    mock_l2_persistent.exact_lookup.return_value = None

    l3_match = MockSemanticMatch(
        translation="Hallo Welt",
        similarity=0.92,
        metadata={"semantic_source": "l3_test"},
    )
    mock_l3_semantic.semantic_search.return_value = [l3_match]

    # Act
    result = translation_memory.lookup(**sample_lookup_params)

    # Assert - All three layers were called in order
    mock_l1_cache.get.assert_called_once()
    mock_l2_persistent.exact_lookup.assert_called_once()
    mock_l3_semantic.semantic_search.assert_called_once()

    # Assert - L1 cache was populated (cache warming from L3)
    mock_l1_cache.put.assert_called_once_with(
        sample_lookup_params["site_id"],
        sample_lookup_params["src_lang"],
        sample_lookup_params["tgt_lang"],
        sample_lookup_params["text"],
        l3_match.translation,
    )

    # Assert - Result indicates L3 semantic hit
    assert result.hit is True
    assert result.source == "l3_semantic"
    assert result.translation == "Hallo Welt"
    assert result.confidence == 0.92


# ==============================================================================
# INV-003: Complete Miss Tests
# ==============================================================================


@pytest.mark.contract
def test_complete_miss_checks_all_layers(
    translation_memory,
    mock_l1_cache,
    mock_l2_persistent,
    mock_l3_semantic,
    sample_lookup_params,
):
    """
    Verify all three layers are checked on complete miss.

    CONTRACT: INV-003 - Complete cascade on miss
    Evidence: src/tm/translation_memory.py lines 155-160
    """
    # Arrange - All layers return miss/empty
    mock_l1_cache.get.return_value = None
    mock_l2_persistent.exact_lookup.return_value = None
    mock_l3_semantic.semantic_search.return_value = []

    # Act
    result = translation_memory.lookup(**sample_lookup_params)

    # Assert - All three layers were called
    mock_l1_cache.get.assert_called_once()
    mock_l2_persistent.exact_lookup.assert_called_once()
    mock_l3_semantic.semantic_search.assert_called_once()

    # Assert - No cache update on miss
    mock_l1_cache.put.assert_not_called()

    # Assert - Result indicates miss
    assert result.hit is False
    assert result.source == "none"
    assert result.translation is None
    assert result.confidence == 0.0


@pytest.mark.contract
def test_l3_disabled_skips_semantic_search(
    translation_memory,
    mock_l1_cache,
    mock_l2_persistent,
    mock_l3_semantic,
    sample_lookup_params,
):
    """
    Verify L3 is not called when use_semantic=False.

    CONTRACT: INV-003 Exception - L3 can be disabled
    Evidence: src/tm/translation_memory.py line 127 (if use_semantic)
    """
    # Arrange - All layers miss, but disable semantic
    mock_l1_cache.get.return_value = None
    mock_l2_persistent.exact_lookup.return_value = None

    # Act - Disable semantic search
    result = translation_memory.lookup(**sample_lookup_params, use_semantic=False)

    # Assert - L3 was NOT called
    mock_l3_semantic.semantic_search.assert_not_called()

    # Assert - L1 and L2 were called
    mock_l1_cache.get.assert_called_once()
    mock_l2_persistent.exact_lookup.assert_called_once()

    # Assert - Result indicates miss (L3 skipped)
    assert result.hit is False


# ==============================================================================
# INV-003: Performance Contract Tests
# ==============================================================================


@pytest.mark.contract
def test_l3_not_called_on_l1_hit_performance(
    translation_memory,
    mock_l1_cache,
    mock_l2_persistent,
    mock_l3_semantic,
    sample_lookup_params,
):
    """
    Verify L3 semantic search (slow) is not called when L1 (fast) hits.

    CONTRACT: INV-003 Performance Contract - L3 MUST NOT be called if L1 hit
    Evidence: src/tm/translation_memory.py structure
    """
    # Arrange - L1 hit
    mock_l1_cache.get.return_value = "Cached Translation"

    # Act
    translation_memory.lookup(**sample_lookup_params)

    # Assert - L3 (expensive semantic search) not called
    mock_l3_semantic.semantic_search.assert_not_called()


@pytest.mark.contract
def test_l3_not_called_on_l2_hit_performance(
    translation_memory,
    mock_l1_cache,
    mock_l2_persistent,
    mock_l3_semantic,
    sample_lookup_params,
):
    """
    Verify L3 semantic search (slow) is not called when L2 (fast) hits.

    CONTRACT: INV-003 Performance Contract - L3 MUST NOT be called if L2 hit
    Evidence: src/tm/translation_memory.py structure
    """
    # Arrange - L1 miss, L2 hit
    mock_l1_cache.get.return_value = None
    l2_entry = Mock()
    l2_entry.translation = "L2 Translation"
    l2_entry.metadata = {}
    mock_l2_persistent.exact_lookup.return_value = l2_entry

    # Act
    translation_memory.lookup(**sample_lookup_params)

    # Assert - L3 (expensive semantic search) not called
    mock_l3_semantic.semantic_search.assert_not_called()


# ==============================================================================
# INV-003: Override Bypass Tests
# ==============================================================================


@pytest.mark.contract
def test_override_bypass_skips_all_layers(
    translation_memory,
    mock_l1_cache,
    mock_l2_persistent,
    mock_l3_semantic,
    mock_override_controller,
    sample_lookup_params,
):
    """
    Verify override bypass skips all cache layers.

    CONTRACT: INV-003 Override - BYPASS mode skips all layers
    Evidence: src/tm/translation_memory.py lines 92-99
    """
    # Arrange - Override says bypass
    mock_override_controller.should_bypass_lookup.return_value = True

    # Act
    result = translation_memory.lookup(**sample_lookup_params)

    # Assert - No layers called
    mock_l1_cache.get.assert_not_called()
    mock_l2_persistent.exact_lookup.assert_not_called()
    mock_l3_semantic.semantic_search.assert_not_called()

    # Assert - Result indicates bypass
    assert result.hit is False
    assert result.source == "override_bypass"
