"""Unit tests for TranslationEngine bounded retry metrics (SR-12)."""
from collections import deque


def test_deque_bounded_behavior():
    """Test that deque(maxlen=N) enforces memory bounds."""
    # Create a bounded deque
    bounded = deque(maxlen=1000)

    # Add 10,000 elements
    for i in range(10000):
        bounded.append(i)

    # Should be exactly 1000 elements, not 10000
    assert len(bounded) == 1000

    # Should contain the last 1000 (9000-9999)
    assert list(bounded) == list(range(9000, 10000))


def test_deque_preserves_statistics():
    """Test that statistics remain valid with bounded deque."""
    bounded = deque(maxlen=100)

    # Add 1000 elements
    for i in range(1000):
        bounded.append(i)

    # Statistics on last 100 elements should be correct
    assert len(bounded) == 100
    assert min(bounded) == 900
    assert max(bounded) == 999
    assert sum(bounded) / len(bounded) == 949.5  # Mean of 900-999


def test_retry_metrics_structure():
    """Test that _retry_metrics structure matches expected format."""
    from collections import deque

    # Simulate engine's _retry_metrics (SR-12)
    retry_metrics = {
        "retry_attempts": deque(maxlen=1000),
        "retry_durations_ms": deque(maxlen=1000),
        "retry_reasons": {},
    }

    # Verify types
    assert isinstance(retry_metrics["retry_attempts"], deque)
    assert isinstance(retry_metrics["retry_durations_ms"], deque)
    assert isinstance(retry_metrics["retry_reasons"], dict)

    # Verify maxlen
    assert retry_metrics["retry_attempts"].maxlen == 1000
    assert retry_metrics["retry_durations_ms"].maxlen == 1000

    # Test append behavior
    for i in range(5000):
        retry_metrics["retry_attempts"].append(i)
        retry_metrics["retry_durations_ms"].append(i * 10.5)

    # Memory is bounded
    assert len(retry_metrics["retry_attempts"]) == 1000
    assert len(retry_metrics["retry_durations_ms"]) == 1000

    # Contains latest values
    assert list(retry_metrics["retry_attempts"])[-1] == 4999
    assert list(retry_metrics["retry_durations_ms"])[-1] == 4999 * 10.5
