"""
End-to-end integration tests for TM layer integration (L1, L2, L3).

Tests cover:
- L1 → L2 → L3 fallback chain
- Cache population on hits
- Thread-safe concurrent access
- All language pairs
- Statistics accuracy
- Real data from migration
"""

import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tm import TranslationMemory, L1Cache, L2PersistentTM, L3SemanticTM, TranslationEntry


class TestTMLayerIntegration:
    """Test integration between all TM layers."""

    @pytest.fixture
    def temp_tm_dir(self, tmp_path):
        """Create temporary TM directory."""
        tm_dir = tmp_path / "tm"
        tm_dir.mkdir()
        return tm_dir

    def test_tm_initialization_all_layers(self, temp_tm_dir):
        """Test TM initializes with all 3 layers."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)
        l3 = L3SemanticTM(temp_tm_dir / "l3.faiss", use_gpu=False)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

        assert tm.l1 is l1
        assert tm.l2 is l2
        assert tm.l3 is l3

        tm.close()

    def test_tm_initialization_without_l3(self, temp_tm_dir):
        """Test TM initializes without L3 (optional)."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=None)

        assert tm.l1 is l1
        assert tm.l2 is l2
        assert tm.l3 is None

        tm.close()

    def test_lookup_l1_hit(self, temp_tm_dir):
        """Test lookup hits L1 cache (fastest path)."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Pre-populate L1
        l1.put("site1", "en", "de", "Hello", "Hallo")

        # Lookup should hit L1
        result = tm.lookup("site1", "en", "de", "Hello")

        assert result.hit is True
        assert result.translation == "Hallo"
        assert result.source == "l1_cache"
        assert result.confidence == 1.0

        tm.close()

    def test_lookup_l2_hit_populates_l1(self, temp_tm_dir):
        """Test lookup hits L2 and populates L1."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Store in L2 only
        l2.store("site1", "en", "de", "Hello", "Hallo")

        # First lookup should hit L2
        result = tm.lookup("site1", "en", "de", "Hello")

        assert result.hit is True
        assert result.translation == "Hallo"
        assert result.source == "l2_exact"
        assert result.confidence == 1.0

        # L1 should now be populated
        cached = l1.get("site1", "en", "de", "Hello")
        assert cached == "Hallo"

        # Second lookup should hit L1
        result2 = tm.lookup("site1", "en", "de", "Hello")
        assert result2.source == "l1_cache"

        tm.close()

    def test_lookup_l3_hit_populates_l1(self, temp_tm_dir):
        """Test lookup hits L3 and populates L1."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)
        l3 = L3SemanticTM(temp_tm_dir / "l3.faiss", use_gpu=False)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

        # Store entry (goes to all layers via TM)
        tm.store("site1", "en", "de", "Hello world", "Hallo Welt")

        # Clear L1 to force L3 lookup
        l1.clear()

        # Lookup similar text (should hit L3)
        result = tm.lookup("site1", "en", "de", "Hello world!", use_semantic=True, semantic_threshold=0.75)

        assert result.hit is True
        assert result.source == "l3_semantic"
        assert result.confidence >= 0.75

        # L1 should now be populated
        cached = l1.get("site1", "en", "de", "Hello world!")
        assert cached is not None

        tm.close()

    def test_lookup_miss_all_layers(self, temp_tm_dir):
        """Test lookup misses all layers."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)
        l3 = L3SemanticTM(temp_tm_dir / "l3.faiss", use_gpu=False)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

        # Lookup non-existent entry
        result = tm.lookup("site1", "en", "de", "NonExistentText")

        assert result.hit is False
        assert result.source == "none"
        assert result.confidence == 0.0

        tm.close()

    def test_store_writes_all_layers(self, temp_tm_dir):
        """Test store writes to all layers."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)
        l3 = L3SemanticTM(temp_tm_dir / "l3.faiss", use_gpu=False)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

        # Store entry
        entry_id = tm.store("site1", "en", "de", "Test", "Test DE")

        assert entry_id is not None

        # Verify in L1
        assert l1.get("site1", "en", "de", "Test") == "Test DE"

        # Verify in L2
        entry = l2.exact_lookup("site1", "en", "de", "Test")
        assert entry is not None
        assert entry.translation == "Test DE"

        # Verify in L3
        assert len(l3) > 0

        tm.close()

    def test_batch_store(self, temp_tm_dir):
        """Test batch store functionality."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)
        l3 = L3SemanticTM(temp_tm_dir / "l3.faiss", use_gpu=False)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

        # Create batch entries
        entries = [
            TranslationEntry(
                source_text=f"Test {i}",
                translation=f"Test DE {i}",
                site_id="site1",
                src_lang="en",
                tgt_lang="de"
            )
            for i in range(10)
        ]

        # Batch store
        count = tm.batch_store(entries)

        assert count == 10

        # Verify entries are in L2
        assert len(l2) >= 10

        # Verify entries are in L3
        assert len(l3) >= 10

        tm.close()

    def test_statistics_accuracy(self, temp_tm_dir):
        """Test TM statistics are accurate."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)
        l3 = L3SemanticTM(temp_tm_dir / "l3.faiss", use_gpu=False)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

        # Store some entries
        for i in range(5):
            tm.store("site1", "en", "de", f"Test {i}", f"Test DE {i}")

        # Do some lookups
        for i in range(5):
            tm.lookup("site1", "en", "de", f"Test {i}")  # Hits
        tm.lookup("site1", "en", "de", "NonExistent")  # Miss

        # Check statistics
        stats = tm.stats()

        assert stats.total_lookups == 6
        assert stats.total_hits == 5
        assert stats.overall_hit_rate == pytest.approx(5/6, abs=0.01)
        assert stats.l1_hits > 0
        assert stats.l2_size >= 5
        assert stats.l3_size >= 5

        tm.close()

    def test_concurrent_lookups(self, temp_tm_dir):
        """Test thread-safe concurrent lookups."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Store test data
        for i in range(10):
            tm.store("site1", "en", "de", f"Test {i}", f"Test DE {i}")

        results = []
        errors = []

        def lookup_worker(text_id):
            """Worker function for concurrent lookups."""
            try:
                result = tm.lookup("site1", "en", "de", f"Test {text_id}")
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Create threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=lookup_worker, args=(i % 10,))
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout=5)

        # Verify no errors
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 10

        # Verify all lookups succeeded
        for result in results:
            assert result.hit is True

        tm.close()

    def test_concurrent_stores(self, temp_tm_dir):
        """Test thread-safe concurrent stores."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        errors = []

        def store_worker(entry_id):
            """Worker function for concurrent stores."""
            try:
                tm.store("site1", "en", "de", f"Test {entry_id}", f"Test DE {entry_id}")
            except Exception as e:
                errors.append(e)

        # Create threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=store_worker, args=(i,))
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout=5)

        # Verify no errors
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Verify all entries stored
        assert len(l2) >= 10

        tm.close()

    def test_multiple_language_pairs(self, temp_tm_dir):
        """Test TM with multiple language pairs."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Store entries for multiple language pairs
        language_pairs = [
            ("en", "de"),
            ("en", "fr"),
            ("en", "es"),
            ("en", "ja"),
        ]

        for src_lang, tgt_lang in language_pairs:
            tm.store("site1", src_lang, tgt_lang, "Hello", f"Hello in {tgt_lang}")

        # Verify each language pair
        for src_lang, tgt_lang in language_pairs:
            result = tm.lookup("site1", src_lang, tgt_lang, "Hello")
            assert result.hit is True
            assert f"Hello in {tgt_lang}" in result.translation

        tm.close()

    def test_fallback_chain_order(self, temp_tm_dir):
        """Test that fallback chain respects L1 → L2 → L3 order."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)
        l3 = L3SemanticTM(temp_tm_dir / "l3.faiss", use_gpu=False)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

        # Store in L2 and L3
        tm.store("site1", "en", "de", "Hello", "Hallo")

        # Clear L1 to force L2 lookup
        l1.clear()

        # Lookup should hit L2 (not L3)
        result = tm.lookup("site1", "en", "de", "Hello")
        assert result.source == "l2_exact"

        # Now lookup again - should hit L1 (populated from L2 hit)
        result2 = tm.lookup("site1", "en", "de", "Hello")
        assert result2.source == "l1_cache"

        tm.close()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_tm_with_zero_l1_size(self, temp_tm_dir):
        """Test TM with L1 cache size of 0."""
        l1 = L1Cache(max_size=0)  # Effectively disabled
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Store and lookup
        tm.store("site1", "en", "de", "Test", "Test DE")
        result = tm.lookup("site1", "en", "de", "Test")

        # Should still work via L2
        assert result.hit is True
        assert result.source == "l2_exact"

        tm.close()

    def test_empty_text_handling(self, temp_tm_dir):
        """Test handling of empty text."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Lookup with empty text
        result = tm.lookup("site1", "en", "de", "")

        assert result.hit is False

        tm.close()

    def test_special_characters(self, temp_tm_dir):
        """Test handling of special characters."""
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(temp_tm_dir / "l2.lmdb", max_size_mb=100)

        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Store with special characters
        text = "Hello 世界 🌍 <tag> & \"quotes\""
        translation = "Hallo 世界 🌍 <tag> & \"Anführungszeichen\""

        tm.store("site1", "en", "de", text, translation)
        result = tm.lookup("site1", "en", "de", text)

        assert result.hit is True
        assert result.translation == translation

        tm.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
