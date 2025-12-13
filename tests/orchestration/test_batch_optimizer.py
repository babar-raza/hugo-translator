"""
Tests for batch optimizer.
"""

import pytest
from src.orchestration.batch_optimizer import (
    BatchOptimizer,
    BatchConfig,
    create_batch_optimizer,
)


@pytest.fixture
def optimizer():
    """Create test batch optimizer."""
    config = BatchConfig(
        initial_batch_size=32,
        min_batch_size=4,
        max_batch_size=128,
        dynamic_batch_size=True,
        sort_by_length=True,
    )
    return BatchOptimizer(config)


def test_optimizer_initialization(optimizer):
    """Test optimizer initializes correctly."""
    assert optimizer.config.initial_batch_size == 32
    assert optimizer.get_optimal_batch_size() == 32


def test_prepare_batches_without_sorting(optimizer):
    """Test batch preparation without sorting."""
    items = [f"item{i}" for i in range(100)]

    batches = optimizer.prepare_batches(items, sort_by_length=False)

    assert len(batches) > 0
    total_items = sum(len(b) for b in batches)
    assert total_items == len(items)


def test_prepare_batches_with_sorting(optimizer):
    """Test batch preparation with sorting."""
    items = ["short", "medium text", "x", "very long text here"]

    batches = optimizer.prepare_batches(items, sort_by_length=True)

    # Verify items are sorted by length
    all_items = []
    for batch in batches:
        all_items.extend(batch)

    for i in range(len(all_items) - 1):
        assert len(all_items[i]) <= len(all_items[i + 1])


def test_get_optimal_batch_size(optimizer):
    """Test getting optimal batch size."""
    size = optimizer.get_optimal_batch_size()
    assert size >= optimizer.config.min_batch_size
    assert size <= optimizer.config.max_batch_size


def test_process_batch_with_monitoring(optimizer):
    """Test batch processing with monitoring."""
    batch = ["item1", "item2", "item3"]

    def mock_process(items):
        return [item.upper() for item in items]

    result, success = optimizer.process_batch_with_monitoring(
        batch, mock_process
    )

    assert success is True
    assert result == ["ITEM1", "ITEM2", "ITEM3"]


def test_oom_handling_disabled():
    """Test OOM handling when disabled."""
    config = BatchConfig(oom_retry_enabled=False)
    optimizer = BatchOptimizer(config)

    def mock_process_oom(items):
        raise RuntimeError("CUDA out of memory")

    batch = ["item1", "item2"]

    with pytest.raises(RuntimeError, match="out of memory"):
        optimizer.process_batch_with_monitoring(batch, mock_process_oom)


def test_factory_function():
    """Test create_batch_optimizer factory."""
    optimizer = create_batch_optimizer(
        initial_batch_size=64,
        enable_optimization=True,
    )

    assert isinstance(optimizer, BatchOptimizer)
    assert optimizer.get_optimal_batch_size() == 64


def test_stats_collection(optimizer):
    """Test statistics collection."""
    batch = ["item1", "item2", "item3"]

    def mock_process(items):
        return [item.upper() for item in items]

    optimizer.process_batch_with_monitoring(batch, mock_process)

    stats = optimizer.get_stats()

    assert stats.batches_processed == 1
    assert stats.total_segments == 3
    assert stats.avg_batch_size == 3.0


def test_batch_size_bounds(optimizer):
    """Test batch size stays within bounds."""
    size = optimizer.get_optimal_batch_size()

    assert size >= optimizer.config.min_batch_size
    assert size <= optimizer.config.max_batch_size


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
