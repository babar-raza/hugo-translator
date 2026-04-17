"""
Unit tests for TM improvement queue.

Tests:
- append_candidate() with deduplication
- pop_candidates() with limit
- count() and stats()
- clear()
"""


import pytest

from src.tm.improvement_queue import ImprovementCandidate, ImprovementQueue


@pytest.fixture
def temp_queue(tmp_path):
    """Create temporary improvement queue for testing."""
    queue = ImprovementQueue(tmp_path, queue_filename="test_queue.jsonl")
    yield queue
    # Cleanup
    queue.clear()


def test_append_candidate(temp_queue):
    """Test appending a candidate to the queue."""
    result = temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Hello world",
        translation="Hallo Welt",
        context="greeting",
        metadata={"similarity_score": 0.75},
    )

    assert result is True
    assert temp_queue.count() == 1


def test_append_candidate_deduplication(temp_queue):
    """Test that duplicate candidates are not added."""
    # Add first candidate
    result1 = temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Hello world",
        translation="Hallo Welt",
    )
    assert result1 is True
    assert temp_queue.count() == 1

    # Try to add duplicate (same site_id, src_lang, tgt_lang, text)
    result2 = temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Hello world",
        translation="Hallo Welt v2",  # Different translation, but same key
    )
    assert result2 is False
    assert temp_queue.count() == 1  # Still only 1 candidate


def test_append_different_candidates(temp_queue):
    """Test appending multiple different candidates."""
    # Add first candidate
    temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Hello world",
        translation="Hallo Welt",
    )

    # Add second candidate (different text)
    temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Goodbye world",
        translation="Auf Wiedersehen Welt",
    )

    # Add third candidate (different target language)
    temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="fr",
        text="Hello world",
        translation="Bonjour le monde",
    )

    assert temp_queue.count() == 3


def test_pop_candidates_with_limit(temp_queue):
    """Test popping candidates with limit."""
    # Add 5 candidates
    for i in range(5):
        temp_queue.append_candidate(
            site_id="docs.aspose.net",
            src_lang="en",
            tgt_lang="de",
            text=f"Text {i}",
            translation=f"Translation {i}",
        )

    assert temp_queue.count() == 5

    # Pop 3 candidates
    candidates = temp_queue.pop_candidates(limit=3)
    assert len(candidates) == 3
    assert temp_queue.count() == 2  # 2 remaining

    # Pop remaining
    candidates = temp_queue.pop_candidates(limit=10)
    assert len(candidates) == 2
    assert temp_queue.count() == 0  # All popped


def test_pop_candidates_fifo_order(temp_queue):
    """Test that candidates are popped in FIFO order."""
    # Add candidates with identifiable texts
    texts = ["First", "Second", "Third"]
    for text in texts:
        temp_queue.append_candidate(
            site_id="docs.aspose.net",
            src_lang="en",
            tgt_lang="de",
            text=text,
            translation=f"Translation of {text}",
        )

    # Pop candidates
    candidates = temp_queue.pop_candidates(limit=3)

    # Check order (FIFO)
    assert candidates[0].text == "First"
    assert candidates[1].text == "Second"
    assert candidates[2].text == "Third"


def test_pop_candidates_empty_queue(temp_queue):
    """Test popping from empty queue returns empty list."""
    candidates = temp_queue.pop_candidates(limit=10)
    assert len(candidates) == 0
    assert temp_queue.count() == 0


def test_candidate_hash_computation():
    """Test that candidate hashes are computed correctly."""
    candidate1 = ImprovementCandidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Hello world",
        translation="Hallo Welt",
    )

    candidate2 = ImprovementCandidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Hello world",
        translation="Different translation",  # Different translation
    )

    # Hashes should be the same (based on key, not translation)
    assert candidate1.candidate_hash == candidate2.candidate_hash

    candidate3 = ImprovementCandidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="fr",  # Different target language
        text="Hello world",
        translation="Bonjour le monde",
    )

    # Hashes should be different
    assert candidate1.candidate_hash != candidate3.candidate_hash


def test_queue_stats(temp_queue):
    """Test queue statistics."""
    # Add some candidates
    for i in range(3):
        temp_queue.append_candidate(
            site_id="docs.aspose.net",
            src_lang="en",
            tgt_lang="de",
            text=f"Text {i}",
            translation=f"Translation {i}",
        )

    stats = temp_queue.stats()

    assert stats["queue_size"] == 3
    assert stats["seen_hashes"] == 3
    assert "queue_file" in stats
    assert "seen_file" in stats


def test_queue_clear(temp_queue):
    """Test clearing the queue."""
    # Add candidates
    for i in range(5):
        temp_queue.append_candidate(
            site_id="docs.aspose.net",
            src_lang="en",
            tgt_lang="de",
            text=f"Text {i}",
            translation=f"Translation {i}",
        )

    assert temp_queue.count() == 5

    # Clear
    temp_queue.clear()

    assert temp_queue.count() == 0
    assert len(temp_queue._seen_hashes) == 0


def test_queue_persistence(tmp_path):
    """Test that queue persists across instances."""
    # Create first queue and add candidates
    queue1 = ImprovementQueue(tmp_path, queue_filename="persist_test.jsonl")
    queue1.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Persistent text",
        translation="Persistente Übersetzung",
    )
    assert queue1.count() == 1

    # Create second queue (same path)
    queue2 = ImprovementQueue(tmp_path, queue_filename="persist_test.jsonl")

    # Should see the same candidate
    assert queue2.count() == 1

    # Pop candidate
    candidates = queue2.pop_candidates(limit=1)
    assert len(candidates) == 1
    assert candidates[0].text == "Persistent text"

    # Cleanup
    queue2.clear()


def test_append_with_context_and_metadata(temp_queue):
    """Test appending candidate with context and metadata."""
    result = temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Technical term",
        translation="Technischer Begriff",
        context="documentation/api",
        metadata={
            "similarity_score": 0.85,
            "hit_count": 42,
            "source": "l3_semantic",
        },
    )

    assert result is True

    # Pop and verify
    candidates = temp_queue.pop_candidates(limit=1)
    assert len(candidates) == 1

    candidate = candidates[0]
    assert candidate.context == "documentation/api"
    assert candidate.metadata["similarity_score"] == 0.85
    assert candidate.metadata["hit_count"] == 42
    assert candidate.metadata["source"] == "l3_semantic"


def test_malformed_line_handling(tmp_path):
    """Test that malformed lines in queue file are handled gracefully."""
    queue = ImprovementQueue(tmp_path, queue_filename="malformed_test.jsonl")

    # Add valid candidate
    queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Valid text",
        translation="Gültige Übersetzung",
    )

    # Manually corrupt the queue file
    queue_file = tmp_path / "malformed_test.jsonl"
    with open(queue_file, "a", encoding="utf-8") as f:
        f.write("THIS IS NOT VALID JSON\n")
        f.write('{"incomplete": "json"\n')

    # Add another valid candidate
    queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Another valid text",
        translation="Noch eine gültige Übersetzung",
    )

    # Should still be able to read valid candidates
    # (malformed lines should be kept in remaining to avoid data loss)
    candidates = queue.pop_candidates(limit=10)

    # Should get the valid candidates (malformed lines kept in file)
    assert len(candidates) >= 2

    # Cleanup
    queue.clear()


def test_candidate_timestamp():
    """Test that candidates have timestamps."""
    candidate = ImprovementCandidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Hello",
        translation="Hallo",
    )

    assert candidate.added_at is not None
    # Should be ISO format timestamp
    from datetime import datetime

    datetime.fromisoformat(candidate.added_at)  # Should not raise


def test_empty_text_handling(temp_queue):
    """Test handling of empty text (should still work)."""
    result = temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="",
        translation="",
    )

    assert result is True
    assert temp_queue.count() == 1


def test_unicode_handling(temp_queue):
    """Test handling of Unicode text."""
    result = temp_queue.append_candidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="zh",
        text="Hello 世界",
        translation="你好 world",
        context="测试",
    )

    assert result is True

    candidates = temp_queue.pop_candidates(limit=1)
    assert len(candidates) == 1
    assert candidates[0].text == "Hello 世界"
    assert candidates[0].translation == "你好 world"
    assert candidates[0].context == "测试"
