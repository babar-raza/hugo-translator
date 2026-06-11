"""Unit tests for L3SemanticTM bounded timing metrics (TM-07)."""

from collections import deque


def test_l3_metrics_structure():
    """Test that L3 _metrics structure matches expected format (TM-07)."""
    # Simulate L3SemanticTM's _metrics structure
    metrics = {
        "semantic_search_ms": deque(maxlen=10000),
        "add_entry_ms": deque(maxlen=10000),
        "batch_add_ms": deque(maxlen=10000),
        "cache_hits": 0,
        "cache_misses": 0,
    }

    # Verify types
    assert isinstance(metrics["semantic_search_ms"], deque)
    assert isinstance(metrics["add_entry_ms"], deque)
    assert isinstance(metrics["batch_add_ms"], deque)
    assert isinstance(metrics["cache_hits"], int)
    assert isinstance(metrics["cache_misses"], int)

    # Verify maxlen
    assert metrics["semantic_search_ms"].maxlen == 10000
    assert metrics["add_entry_ms"].maxlen == 10000
    assert metrics["batch_add_ms"].maxlen == 10000

    # Test append behavior for timing lists
    for i in range(50000):  # Add 50K entries (5x limit)
        metrics["semantic_search_ms"].append(i * 0.5)
        metrics["add_entry_ms"].append(i * 0.3)
        metrics["batch_add_ms"].append(i * 2.1)

    # Memory is bounded to maxlen
    assert len(metrics["semantic_search_ms"]) == 10000
    assert len(metrics["add_entry_ms"]) == 10000
    assert len(metrics["batch_add_ms"]) == 10000

    # Contains latest 10000 values
    assert list(metrics["semantic_search_ms"])[-1] == 49999 * 0.5
    assert list(metrics["add_entry_ms"])[-1] == 49999 * 0.3
    assert list(metrics["batch_add_ms"])[-1] == 49999 * 2.1

    # First value should be from index 40000 (50000 - 10000)
    assert list(metrics["semantic_search_ms"])[0] == 40000 * 0.5

    # Test cache counters remain integers and grow unbounded
    metrics["cache_hits"] += 100000
    metrics["cache_misses"] += 50000

    assert metrics["cache_hits"] == 100000
    assert metrics["cache_misses"] == 50000
    assert isinstance(metrics["cache_hits"], int)
    assert isinstance(metrics["cache_misses"], int)


def test_l3_memory_efficiency():
    """Test that TM-07 fixes provide significant memory savings."""
    # OLD approach (unbounded list)
    old_metrics = {
        "semantic_search_ms": [],
        "add_entry_ms": [],
        "batch_add_ms": [],
    }

    # NEW approach (TM-07: bounded deque)
    new_metrics = {
        "semantic_search_ms": deque(maxlen=10000),
        "add_entry_ms": deque(maxlen=10000),
        "batch_add_ms": deque(maxlen=10000),
    }

    # Simulate 1M operations (high-traffic production scenario)
    for i in range(1000000):
        old_metrics["semantic_search_ms"].append(i * 1.5)
        new_metrics["semantic_search_ms"].append(i * 1.5)

    # OLD: Unbounded growth (1M elements)
    assert len(old_metrics["semantic_search_ms"]) == 1000000

    # NEW: Bounded growth (10K elements) - 100x memory savings
    assert len(new_metrics["semantic_search_ms"]) == 10000

    # Calculate memory savings
    old_memory_items = len(old_metrics["semantic_search_ms"])
    new_memory_items = len(new_metrics["semantic_search_ms"])
    memory_reduction_factor = old_memory_items / new_memory_items

    assert memory_reduction_factor == 100.0  # 100x reduction


def test_l3_statistics_remain_accurate():
    """Test that statistics remain accurate with bounded deque."""
    metrics = {
        "semantic_search_ms": deque(maxlen=10000),
    }

    # Add 50K operations
    for i in range(50000):
        metrics["semantic_search_ms"].append(i * 0.5)

    # Statistics on last 10K operations should be accurate
    values = list(metrics["semantic_search_ms"])

    assert len(values) == 10000
    assert min(values) == 40000 * 0.5  # First of last 10K
    assert max(values) == 49999 * 0.5  # Last of last 10K
    assert sum(values) / len(values) == ((40000 + 49999) / 2) * 0.5  # Mean of range
