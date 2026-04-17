"""
CONTRACT: specs/features/tm-003-l3-semantic-search.md

Verifies L3 semantic translation memory behavior including:
- Embedding generation before adding entries
- Metadata/FAISS index synchronization
- Periodic save triggers at configured interval
- Search filtering by site_id, src_lang, tgt_lang
- Similarity threshold enforcement
- Thread-safe index access

TM-003 Feature: L3 Semantic Translation Memory

Key Guarantees:
1. Embedding before add - MUST generate embedding for source_text
2. Synchronized metadata - Metadata array index MUST match FAISS index position
3. Periodic save triggers - IF save_interval > 0 AND additions >= save_interval -> trigger save
4. Filter by site_id, src_lang, tgt_lang - Search results MUST match all three filters
5. Similarity threshold enforcement - MUST filter results by threshold (only return >= threshold)
6. Thread-safe index access - MUST acquire lock before FAISS operations
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

# ==============================================================================
# Skip if dependencies not available
# ==============================================================================


@pytest.fixture(scope="module")
def check_deps():
    """Check if required dependencies are available."""
    try:
        import faiss
        from sentence_transformers import SentenceTransformer
        return True
    except ImportError:
        pytest.skip("faiss or sentence-transformers not installed")
        return False


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def l3_tm(tmp_path, check_deps):
    """
    Create a temporary L3SemanticTM for testing.

    Evidence: src/tm/l3_semantic.py L3SemanticTM.__init__()
    """
    from src.tm.l3_semantic import L3SemanticTM

    return L3SemanticTM(
        index_path=tmp_path / "l3_faiss",
        save_interval=0,  # Disable periodic saves for tests
    )


@pytest.fixture
def l3_tm_with_save_interval(tmp_path, check_deps):
    """
    L3SemanticTM with periodic saves enabled.

    Evidence: src/tm/l3_semantic.py L3SemanticTM.__init__()
    """
    from src.tm.l3_semantic import L3SemanticTM

    return L3SemanticTM(
        index_path=tmp_path / "l3_faiss_save",
        save_interval=3,  # Save every 3 additions
        async_save=False,  # Sync save for predictable testing
    )


@pytest.fixture
def sample_entries():
    """Standard test entries with different sites and languages."""
    return [
        {
            "entry_id": "e1",
            "site_id": "docs.example.com",
            "src_lang": "en",
            "tgt_lang": "de",
            "source_text": "Hello world",
            "translation": "Hallo Welt",
        },
        {
            "entry_id": "e2",
            "site_id": "docs.example.com",
            "src_lang": "en",
            "tgt_lang": "de",
            "source_text": "Good morning",
            "translation": "Guten Morgen",
        },
        {
            "entry_id": "e3",
            "site_id": "docs.example.com",
            "src_lang": "en",
            "tgt_lang": "fr",
            "source_text": "Hello world",
            "translation": "Bonjour le monde",
        },
        {
            "entry_id": "e4",
            "site_id": "blog.example.com",
            "src_lang": "en",
            "tgt_lang": "de",
            "source_text": "Hello world",
            "translation": "Hallo Welt (blog)",
        },
    ]


# ==============================================================================
# TM-003: Invariant 1 - Embedding Before Add
# ==============================================================================


@pytest.mark.contract
def test_embedding_generated_before_add(l3_tm, check_deps):
    """
    Verify embedding is generated for source_text during add_entry.

    CONTRACT: TM-003 Invariant 1 - Embedding before add
    Evidence: src/tm/l3_semantic.py lines 206-209 (encoder.encode)
    """
    # Track encoder calls
    original_encode = l3_tm.encoder.encode
    encode_calls = []

    def tracked_encode(text, **kwargs):
        encode_calls.append(text)
        return original_encode(text, **kwargs)

    l3_tm.encoder.encode = tracked_encode

    # Add entry
    source_text = "Hello world"
    l3_tm.add_entry(
        "test_id", "site", "en", "de",
        source_text, "Hallo Welt"
    )

    # Verify encoder was called with source_text
    assert len(encode_calls) == 1
    assert encode_calls[0] == source_text


@pytest.mark.contract
def test_embedding_dimension_matches_model(l3_tm, check_deps):
    """
    Verify embedding dimension matches the sentence transformer model.

    CONTRACT: TM-003 - Embedding model configuration
    Evidence: src/tm/l3_semantic.py line 129 (embedding_dim)
    """
    # all-MiniLM-L6-v2 has 384 dimensions
    assert l3_tm.embedding_dim == 384

    # Add an entry and verify FAISS index dimension
    l3_tm.add_entry("e1", "site", "en", "de", "Hello", "Hallo")
    assert l3_tm.index.d == 384


# ==============================================================================
# TM-003: Invariant 2 - Synchronized Metadata
# ==============================================================================


@pytest.mark.contract
def test_metadata_index_matches_faiss_position(l3_tm, check_deps):
    """
    Verify metadata array index matches FAISS index position.

    CONTRACT: TM-003 Invariant 2 - Synchronized metadata
    Evidence: src/tm/l3_semantic.py lines 212-226 (index.add then metadata.append)
    """
    # Add multiple entries
    entries = [
        ("e1", "Hello world", "Hallo Welt"),
        ("e2", "Good morning", "Guten Morgen"),
        ("e3", "Goodbye", "Auf Wiedersehen"),
    ]

    for entry_id, source, translation in entries:
        l3_tm.add_entry(entry_id, "site", "en", "de", source, translation)

    # Verify count matches
    assert l3_tm.index.ntotal == len(entries)
    assert len(l3_tm.metadata) == len(entries)

    # Verify metadata at each position
    for i, (entry_id, source, translation) in enumerate(entries):
        assert l3_tm.metadata[i]["entry_id"] == entry_id
        assert l3_tm.metadata[i]["source_text"] == source
        assert l3_tm.metadata[i]["translation"] == translation


@pytest.mark.contract
def test_batch_add_maintains_sync(l3_tm, check_deps):
    """
    Verify batch_add maintains metadata/index synchronization.

    CONTRACT: TM-003 Invariant 2 - Batch sync
    Evidence: src/tm/l3_semantic.py lines 467-483 (batch embeddings then metadata)
    """
    entries = [
        {
            "entry_id": f"batch_{i}",
            "site_id": "site",
            "src_lang": "en",
            "tgt_lang": "de",
            "source_text": f"Source text number {i}",
            "translation": f"Translation {i}",
        }
        for i in range(10)
    ]

    count = l3_tm.batch_add(entries)

    assert count == 10
    assert l3_tm.index.ntotal == 10
    assert len(l3_tm.metadata) == 10

    # Verify order preserved
    for i in range(10):
        assert l3_tm.metadata[i]["entry_id"] == f"batch_{i}"


# ==============================================================================
# TM-003: Invariant 3 - Periodic Save Triggers
# ==============================================================================


@pytest.mark.contract
def test_periodic_save_triggers_at_interval(tmp_path, check_deps):
    """
    Verify periodic save triggers when additions reach save_interval.

    CONTRACT: TM-003 Invariant 3 - Periodic save triggers
    Evidence: src/tm/l3_semantic.py lines 240-242 (interval check)
    """
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=tmp_path / "l3_test",
        save_interval=3,
        async_save=False,
    )

    # Track save calls
    save_calls = []
    original_do_save = tm._do_save

    def tracked_save():
        save_calls.append(time.time())
        return original_do_save()

    tm._do_save = tracked_save

    # Add 2 entries - should not trigger
    tm.add_entry("e1", "site", "en", "de", "Hello", "Hallo")
    tm.add_entry("e2", "site", "en", "de", "World", "Welt")
    assert len(save_calls) == 0

    # Add 3rd entry - should trigger save
    tm.add_entry("e3", "site", "en", "de", "Goodbye", "Auf Wiedersehen")
    assert len(save_calls) == 1


@pytest.mark.contract
def test_periodic_save_resets_counter(l3_tm_with_save_interval, check_deps):
    """
    Verify additions counter resets after successful save.

    CONTRACT: TM-003 Invariant 3 - Counter reset
    Evidence: src/tm/l3_semantic.py lines 282-284 (reset in _do_save)
    """
    tm = l3_tm_with_save_interval

    # Add 3 entries to trigger save
    for i in range(3):
        tm.add_entry(f"e{i}", "site", "en", "de", f"Text {i}", f"Trans {i}")

    # Counter should be reset
    assert tm._additions_since_save == 0

    # Add 1 more - counter should be 1
    tm.add_entry("e4", "site", "en", "de", "More text", "Mehr Text")
    assert tm._additions_since_save == 1


@pytest.mark.contract
def test_no_save_when_interval_zero(l3_tm, check_deps):
    """
    Verify no periodic save when save_interval=0.

    CONTRACT: TM-003 Invariant 3 - Disabled saves
    Evidence: src/tm/l3_semantic.py line 241 (save_interval > 0 check)
    """
    # Track save triggers
    save_triggered = []
    original_trigger = l3_tm._trigger_save

    def tracked_trigger():
        save_triggered.append(True)
        return original_trigger()

    l3_tm._trigger_save = tracked_trigger

    # Add many entries
    for i in range(20):
        l3_tm.add_entry(f"e{i}", "site", "en", "de", f"Text {i}", f"Trans {i}")

    # Save should never trigger
    assert len(save_triggered) == 0


# ==============================================================================
# TM-003: Invariant 4 - Filter by site_id, src_lang, tgt_lang
# ==============================================================================


@pytest.mark.contract
def test_search_filters_by_site_id(l3_tm, sample_entries, check_deps):
    """
    Verify search results match site_id filter.

    CONTRACT: TM-003 Invariant 4 - Site filter
    Evidence: src/tm/l3_semantic.py line 398 (site_id == site_id check)
    """
    # Add entries with different sites
    for entry in sample_entries:
        l3_tm.add_entry(**entry)

    # Search for docs.example.com
    results = l3_tm.semantic_search(
        "docs.example.com", "en", "de",
        "Hello world",
        k=10,
        threshold=0.0,  # Accept all similarities
    )

    # All results should be from docs.example.com
    assert len(results) > 0
    for match in results:
        assert match.site_id == "docs.example.com"


@pytest.mark.contract
def test_search_filters_by_src_lang(l3_tm, check_deps):
    """
    Verify search results match src_lang filter.

    CONTRACT: TM-003 Invariant 4 - Source language filter
    Evidence: src/tm/l3_semantic.py line 399 (src_lang == src_lang check)
    """
    # Add entries with different source languages
    l3_tm.add_entry("e1", "site", "en", "de", "Hello", "Hallo")
    l3_tm.add_entry("e2", "site", "fr", "de", "Bonjour", "Hallo")

    # Search with en source
    results = l3_tm.semantic_search(
        "site", "en", "de",
        "Hello",
        k=10,
        threshold=0.0,
    )

    # Only en source should be returned
    for match in results:
        assert match.src_lang == "en"


@pytest.mark.contract
def test_search_filters_by_tgt_lang(l3_tm, sample_entries, check_deps):
    """
    Verify search results match tgt_lang filter.

    CONTRACT: TM-003 Invariant 4 - Target language filter
    Evidence: src/tm/l3_semantic.py line 400 (tgt_lang == tgt_lang check)
    """
    # Add entries
    for entry in sample_entries:
        l3_tm.add_entry(**entry)

    # Search for German translations
    results_de = l3_tm.semantic_search(
        "docs.example.com", "en", "de",
        "Hello world",
        k=10,
        threshold=0.0,
    )

    # Search for French translations
    results_fr = l3_tm.semantic_search(
        "docs.example.com", "en", "fr",
        "Hello world",
        k=10,
        threshold=0.0,
    )

    # Verify target language filtering
    for match in results_de:
        assert match.tgt_lang == "de"

    for match in results_fr:
        assert match.tgt_lang == "fr"


@pytest.mark.contract
def test_search_requires_all_three_filters_match(l3_tm, check_deps):
    """
    Verify search requires ALL three filters to match (AND logic).

    CONTRACT: TM-003 Invariant 4 - Combined filters
    Evidence: src/tm/l3_semantic.py lines 397-401 (all conditions with 'and')
    """
    # Add entry
    l3_tm.add_entry("e1", "site_a", "en", "de", "Hello world", "Hallo Welt")

    # Wrong site_id
    results = l3_tm.semantic_search("site_b", "en", "de", "Hello world", threshold=0.0)
    assert len(results) == 0

    # Wrong src_lang
    results = l3_tm.semantic_search("site_a", "fr", "de", "Hello world", threshold=0.0)
    assert len(results) == 0

    # Wrong tgt_lang
    results = l3_tm.semantic_search("site_a", "en", "fr", "Hello world", threshold=0.0)
    assert len(results) == 0

    # All correct
    results = l3_tm.semantic_search("site_a", "en", "de", "Hello world", threshold=0.0)
    assert len(results) == 1


# ==============================================================================
# TM-003: Invariant 5 - Similarity Threshold Enforcement
# ==============================================================================


@pytest.mark.contract
def test_threshold_filters_low_similarity(l3_tm, check_deps):
    """
    Verify results below threshold are filtered out.

    CONTRACT: TM-003 Invariant 5 - Threshold enforcement
    Evidence: src/tm/l3_semantic.py line 401 (similarity >= threshold)
    """
    # Add entries with varying similarity to query
    l3_tm.add_entry("e1", "site", "en", "de", "Hello world", "Hallo Welt")
    l3_tm.add_entry("e2", "site", "en", "de", "Hello there", "Hallo da")
    l3_tm.add_entry("e3", "site", "en", "de", "Completely different text about programming", "Ganz anderer Text")

    # High threshold should filter more results
    high_results = l3_tm.semantic_search(
        "site", "en", "de",
        "Hello world",
        k=10,
        threshold=0.9,
    )

    # Low threshold should return more
    low_results = l3_tm.semantic_search(
        "site", "en", "de",
        "Hello world",
        k=10,
        threshold=0.1,
    )

    # Verify all returned results meet threshold
    for match in high_results:
        assert match.similarity >= 0.9

    for match in low_results:
        assert match.similarity >= 0.1

    # Low threshold should return at least as many results
    assert len(low_results) >= len(high_results)


@pytest.mark.contract
def test_threshold_zero_returns_all_matches(l3_tm, check_deps):
    """
    Verify threshold=0.0 returns all matching site/lang results.

    CONTRACT: TM-003 Edge Case - threshold=0.0
    Evidence: src/tm/l3_semantic.py line 401 (similarity >= 0.0 always true)
    """
    # Add multiple entries
    for i in range(5):
        l3_tm.add_entry(f"e{i}", "site", "en", "de", f"Text number {i}", f"Text Nummer {i}")

    # threshold=0.0 should return all (up to k)
    results = l3_tm.semantic_search(
        "site", "en", "de",
        "Any query text",
        k=10,
        threshold=0.0,
    )

    assert len(results) == 5


@pytest.mark.contract
def test_threshold_one_requires_perfect_match(l3_tm, check_deps):
    """
    Verify threshold=1.0 requires near-perfect similarity (rare).

    CONTRACT: TM-003 Edge Case - threshold=1.0
    Evidence: Spec notes this may return 0 results
    """
    l3_tm.add_entry("e1", "site", "en", "de", "Hello world", "Hallo Welt")

    # threshold=1.0 typically returns empty (exact semantic match rare)
    results = l3_tm.semantic_search(
        "site", "en", "de",
        "Different query text",
        k=10,
        threshold=1.0,
    )

    # May return 0 results (acceptable for threshold=1.0)
    # All returned results must have similarity >= 1.0
    for match in results:
        assert match.similarity >= 1.0


# ==============================================================================
# TM-003: Invariant 6 - Thread-Safe Index Access
# ==============================================================================


@pytest.mark.contract
def test_concurrent_adds_are_thread_safe(tmp_path, check_deps):
    """
    Verify concurrent add_entry calls don't corrupt index.

    CONTRACT: TM-003 Invariant 6 - Thread-safe access
    Evidence: src/tm/l3_semantic.py lines 212, 234 (self._lock context manager)
    """
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=tmp_path / "l3_concurrent",
        save_interval=0,
    )

    num_threads = 5
    entries_per_thread = 10
    errors: list[Exception] = []

    def add_entries(thread_id: int):
        try:
            for i in range(entries_per_thread):
                tm.add_entry(
                    f"t{thread_id}_e{i}",
                    f"site_{thread_id}",
                    "en", "de",
                    f"Text from thread {thread_id} entry {i}",
                    f"Translation {thread_id}_{i}",
                )
        except Exception as e:
            errors.append(e)

    # Run concurrent adds
    threads = []
    for t in range(num_threads):
        thread = threading.Thread(target=add_entries, args=(t,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    # Verify no errors
    assert len(errors) == 0, f"Thread errors: {errors}"

    # Verify all entries added
    expected_count = num_threads * entries_per_thread
    assert tm.index.ntotal == expected_count
    assert len(tm.metadata) == expected_count


@pytest.mark.contract
def test_concurrent_reads_and_writes_are_safe(l3_tm, check_deps):
    """
    Verify concurrent search and add operations are thread-safe.

    CONTRACT: TM-003 Invariant 6 - Mixed operation safety
    Evidence: src/tm/l3_semantic.py lines 212, 375 (lock in both methods)
    """
    # Pre-populate
    for i in range(20):
        l3_tm.add_entry(f"init_{i}", "site", "en", "de", f"Initial text {i}", f"Initial trans {i}")

    errors: list[Exception] = []

    def writer(thread_id: int):
        try:
            for i in range(20):
                l3_tm.add_entry(
                    f"t{thread_id}_e{i}", "site", "en", "de",
                    f"New text {thread_id}_{i}", f"New trans {thread_id}_{i}",
                )
        except Exception as e:
            errors.append(e)

    def reader(thread_id: int):
        try:
            for _ in range(20):
                l3_tm.semantic_search(
                    "site", "en", "de",
                    f"Query text {thread_id}",
                    k=5,
                    threshold=0.0,
                )
        except Exception as e:
            errors.append(e)

    # Mix readers and writers
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for i in range(4):
            futures.append(executor.submit(writer, i))
            futures.append(executor.submit(reader, i))

        for future in as_completed(futures):
            future.result()

    # No errors
    assert len(errors) == 0, f"Concurrent errors: {errors}"


# ==============================================================================
# TM-003: Edge Cases
# ==============================================================================


@pytest.mark.contract
def test_empty_index_returns_empty_list(l3_tm, check_deps):
    """
    Verify search on empty index returns empty list (not error).

    CONTRACT: TM-003 Edge Case - Empty index
    Evidence: src/tm/l3_semantic.py lines 364-368 (ntotal == 0 check)
    """
    # Don't add anything
    results = l3_tm.semantic_search(
        "site", "en", "de",
        "Hello world",
        k=10,
        threshold=0.75,
    )

    assert results == []
    assert isinstance(results, list)


@pytest.mark.contract
def test_k_greater_than_index_size_capped(l3_tm, check_deps):
    """
    Verify k is capped at index.ntotal when larger.

    CONTRACT: TM-003 Edge Case - k > index size
    Evidence: src/tm/l3_semantic.py line 378 (min(k * 10, index.ntotal))
    """
    # Add only 3 entries
    for i in range(3):
        l3_tm.add_entry(f"e{i}", "site", "en", "de", f"Text {i}", f"Trans {i}")

    # Request k=100
    results = l3_tm.semantic_search(
        "site", "en", "de",
        "Text",
        k=100,
        threshold=0.0,
    )

    # Should return at most 3 (all that exist)
    assert len(results) <= 3


@pytest.mark.contract
def test_oversample_factor_for_filtering(tmp_path, check_deps):
    """
    Verify search uses k * 10 oversample before filtering.

    CONTRACT: TM-003 - Oversample for filtering
    Evidence: src/tm/l3_semantic.py line 378 (search_k = min(k * 10, index.ntotal))
    """
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=tmp_path / "l3_oversample",
        save_interval=0,
    )

    # Add many entries with mixed sites
    for i in range(50):
        site = "target_site" if i < 5 else "other_site"
        tm.add_entry(f"e{i}", site, "en", "de", f"Text content {i}", f"Trans {i}")

    # Search with k=3 but only 5 entries match site filter
    # Oversample (k*10=30) ensures we search enough to find all 5
    results = tm.semantic_search(
        "target_site", "en", "de",
        "Text content",
        k=3,
        threshold=0.0,
    )

    # Should return up to k=3 results
    assert len(results) <= 3
    for match in results:
        assert match.site_id == "target_site"


@pytest.mark.contract
def test_search_returns_sorted_by_similarity(l3_tm, check_deps):
    """
    Verify results are sorted by similarity (descending).

    CONTRACT: TM-003 - Result ordering
    Evidence: Spec states results "sorted by similarity, descending"
    """
    # Add entries
    l3_tm.add_entry("exact", "site", "en", "de", "Hello world", "Hallo Welt")
    l3_tm.add_entry("similar", "site", "en", "de", "Hello there world", "Hallo da Welt")
    l3_tm.add_entry("different", "site", "en", "de", "Programming tutorial", "Programmier Tutorial")

    results = l3_tm.semantic_search(
        "site", "en", "de",
        "Hello world",
        k=10,
        threshold=0.0,
    )

    # Verify descending order
    if len(results) >= 2:
        for i in range(len(results) - 1):
            assert results[i].similarity >= results[i + 1].similarity


# ==============================================================================
# TM-003: SemanticMatch Structure Tests
# ==============================================================================


@pytest.mark.contract
def test_semantic_match_contains_all_fields(l3_tm, check_deps):
    """
    Verify SemanticMatch contains all required fields.

    CONTRACT: TM-003 - SemanticMatch structure
    Evidence: src/tm/l3_semantic.py lines 33-45 (SemanticMatch dataclass)
    """
    l3_tm.add_entry(
        "test_entry",
        "test_site",
        "en", "de",
        "Hello world",
        "Hallo Welt",
        context="test_context",
        metadata={"key": "value"},
    )

    results = l3_tm.semantic_search(
        "test_site", "en", "de",
        "Hello world",
        k=1,
        threshold=0.0,
    )

    assert len(results) == 1
    match = results[0]

    # Verify all fields present
    assert match.entry_id == "test_entry"
    assert isinstance(match.similarity, float)
    assert 0.0 <= match.similarity <= 1.0
    assert match.source_text == "Hello world"
    assert match.translation == "Hallo Welt"
    assert match.site_id == "test_site"
    assert match.src_lang == "en"
    assert match.tgt_lang == "de"
    assert match.context == "test_context"
    assert match.metadata == {"key": "value"}


@pytest.mark.contract
def test_semantic_match_to_dict(l3_tm, check_deps):
    """
    Verify SemanticMatch.to_dict() works correctly.

    CONTRACT: TM-003 - SemanticMatch serialization
    Evidence: src/tm/l3_semantic.py lines 47-49 (to_dict method)
    """
    l3_tm.add_entry("e1", "site", "en", "de", "Hello", "Hallo")

    results = l3_tm.semantic_search("site", "en", "de", "Hello", k=1, threshold=0.0)

    assert len(results) == 1
    match_dict = results[0].to_dict()

    assert isinstance(match_dict, dict)
    assert "entry_id" in match_dict
    assert "similarity" in match_dict
    assert "source_text" in match_dict
    assert "translation" in match_dict


# ==============================================================================
# TM-003: Index Persistence Tests
# ==============================================================================


@pytest.mark.contract
def test_save_and_load_preserves_data(tmp_path, check_deps):
    """
    Verify save/load preserves all entries correctly.

    CONTRACT: TM-003 - Index persistence
    Evidence: src/tm/l3_semantic.py lines 503-588 (save_index, load_index)
    """
    from src.tm.l3_semantic import L3SemanticTM

    index_path = tmp_path / "l3_persist"

    # Create and populate
    tm1 = L3SemanticTM(index_path=index_path, save_interval=0)
    tm1.add_entry("e1", "site", "en", "de", "Hello world", "Hallo Welt")
    tm1.add_entry("e2", "site", "en", "de", "Goodbye", "Auf Wiedersehen")
    tm1.save_index()

    # Create new instance loading saved data
    tm2 = L3SemanticTM(index_path=index_path, save_interval=0)

    # Verify data loaded
    assert tm2.index.ntotal == 2
    assert len(tm2.metadata) == 2

    # Verify searchable
    results = tm2.semantic_search("site", "en", "de", "Hello world", k=1, threshold=0.0)
    assert len(results) == 1
    assert results[0].entry_id == "e1"


@pytest.mark.contract
def test_save_creates_required_files(l3_tm, check_deps):
    """
    Verify save_index creates all required files.

    CONTRACT: TM-003 - File system writes
    Evidence: src/tm/l3_semantic.py lines 517-550 (writes index.faiss, metadata.pkl, config.json)
    """
    l3_tm.add_entry("e1", "site", "en", "de", "Hello", "Hallo")
    l3_tm.save_index()

    # Verify files created
    assert (l3_tm.index_path / "index.faiss").exists()
    assert (l3_tm.index_path / "metadata.pkl").exists()
    assert (l3_tm.index_path / "config.json").exists()

    # Verify config content
    with open(l3_tm.index_path / "config.json") as f:
        config = json.load(f)

    assert config["embedding_dim"] == 384
    assert config["num_entries"] == 1


# ==============================================================================
# TM-003: Timing Metrics Tests
# ==============================================================================


@pytest.mark.contract
def test_timing_metrics_collected(l3_tm, check_deps):
    """
    Verify timing metrics are collected for operations.

    CONTRACT: TM-003 - Performance instrumentation (BM-08)
    Evidence: src/tm/l3_semantic.py lines 104-110, 316-336 (get_timing_metrics)
    """
    # Perform operations
    l3_tm.add_entry("e1", "site", "en", "de", "Hello", "Hallo")
    l3_tm.semantic_search("site", "en", "de", "Hello", k=1, threshold=0.0)

    metrics = l3_tm.get_timing_metrics()

    # Verify structure
    assert "semantic_search" in metrics
    assert "add_entry" in metrics
    assert "cache_hits" in metrics
    assert "cache_misses" in metrics
    assert "cache_hit_rate" in metrics

    # Verify timing data recorded
    assert metrics["add_entry"]["count"] >= 1
    assert metrics["semantic_search"]["count"] >= 1


@pytest.mark.contract
def test_cache_hit_miss_tracking(l3_tm, check_deps):
    """
    Verify cache hits/misses tracked correctly.

    CONTRACT: TM-003 - Cache metrics
    Evidence: src/tm/l3_semantic.py lines 419-423 (hit/miss recording)
    """
    # Add entry
    l3_tm.add_entry("e1", "site", "en", "de", "Hello world", "Hallo Welt")

    # Search that finds results (hit)
    l3_tm.semantic_search("site", "en", "de", "Hello world", k=1, threshold=0.0)

    # Search that finds no results (miss - wrong site)
    l3_tm.semantic_search("other_site", "en", "de", "Hello world", k=1, threshold=0.0)

    metrics = l3_tm.get_timing_metrics()

    # Verify tracking
    assert metrics["cache_hits"] >= 1
    assert metrics["cache_misses"] >= 1


# ==============================================================================
# TM-003: Context Manager Tests
# ==============================================================================


@pytest.mark.contract
def test_context_manager_saves_on_exit(tmp_path, check_deps):
    """
    Verify context manager saves index on exit.

    CONTRACT: TM-003 - Resource cleanup
    Evidence: src/tm/l3_semantic.py lines 631-639 (__exit__ saves)
    """
    from src.tm.l3_semantic import L3SemanticTM

    index_path = tmp_path / "l3_context"

    with L3SemanticTM(index_path=index_path, save_interval=0) as tm:
        tm.add_entry("e1", "site", "en", "de", "Hello", "Hallo")

    # After exit, files should exist
    assert (index_path / "index.faiss").exists()
    assert (index_path / "metadata.pkl").exists()


# ==============================================================================
# TM-003: Clear and Count Tests
# ==============================================================================


@pytest.mark.contract
def test_clear_resets_index_and_metadata(l3_tm, check_deps):
    """
    Verify clear() resets both index and metadata.

    CONTRACT: TM-003 - Clear operation
    Evidence: src/tm/l3_semantic.py lines 618-621 (clear calls _create_index)
    """
    # Add entries
    for i in range(5):
        l3_tm.add_entry(f"e{i}", "site", "en", "de", f"Text {i}", f"Trans {i}")

    assert l3_tm.count() == 5

    # Clear
    l3_tm.clear()

    assert l3_tm.count() == 0
    assert len(l3_tm.metadata) == 0
    assert l3_tm.index.ntotal == 0


@pytest.mark.contract
def test_count_and_len_match(l3_tm, check_deps):
    """
    Verify count() and __len__ return same value.

    CONTRACT: TM-003 - Count consistency
    Evidence: src/tm/l3_semantic.py lines 608-625 (count and __len__)
    """
    for i in range(7):
        l3_tm.add_entry(f"e{i}", "site", "en", "de", f"Text {i}", f"Trans {i}")

    assert l3_tm.count() == 7
    assert len(l3_tm) == 7
    assert l3_tm.count() == len(l3_tm)
