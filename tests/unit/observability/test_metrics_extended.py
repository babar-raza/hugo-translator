"""Unit tests for extended metrics (BM-08)."""


from src.observability.metrics import MetricsCollector


def test_bm08_model_load_duration_metric_exists():
    """Test that model_load_duration_seconds metric is registered."""
    collector = MetricsCollector(worker_id="test")

    # Verify metric exists
    assert "model_load_duration_seconds" in [h.name for h in collector._histograms.values()]


def test_bm08_tokenization_duration_metric_exists():
    """Test that tokenization_duration_seconds metric is registered."""
    collector = MetricsCollector(worker_id="test")

    assert "tokenization_duration_seconds" in [h.name for h in collector._histograms.values()]


def test_bm08_l3_encoding_duration_metric_exists():
    """Test that l3_encoding_duration_seconds metric is registered."""
    collector = MetricsCollector(worker_id="test")

    assert "l3_encoding_duration_seconds" in [h.name for h in collector._histograms.values()]


def test_bm08_l3_lookup_duration_metric_exists():
    """Test that l3_lookup_duration_seconds metric is registered."""
    collector = MetricsCollector(worker_id="test")

    assert "l3_lookup_duration_seconds" in [h.name for h in collector._histograms.values()]


def test_bm08_retry_duration_metric_exists():
    """Test that retry_duration_seconds metric is registered."""
    collector = MetricsCollector(worker_id="test")

    assert "retry_duration_seconds" in [h.name for h in collector._histograms.values()]


def test_bm08_batch_preparation_duration_metric_exists():
    """Test that batch_preparation_duration_seconds metric is registered."""
    collector = MetricsCollector(worker_id="test")

    assert "batch_preparation_duration_seconds" in [
        h.name for h in collector._histograms.values()
    ]


def test_bm08_retry_count_metric_exists():
    """Test that retry_count_total metric is registered."""
    collector = MetricsCollector(worker_id="test")

    assert "retry_count_total" in [c.name for c in collector._counters.values()]


def test_bm08_warmup_iterations_metric_exists():
    """Test that warmup_iterations metric is registered."""
    collector = MetricsCollector(worker_id="test")

    assert "warmup_iterations" in [g.name for g in collector._gauges.values()]


def test_bm08_actual_iterations_metric_exists():
    """Test that actual_iterations metric is registered."""
    collector = MetricsCollector(worker_id="test")

    assert "actual_iterations" in [g.name for g in collector._gauges.values()]


def test_bm08_observe_model_load_duration():
    """Test observing model load duration."""
    collector = MetricsCollector(worker_id="test")

    # Observe a value
    collector.observe("model_load_duration_seconds", 1.5)

    # Verify it was recorded
    hist = collector.get_histogram("model_load_duration_seconds", {"worker_id": "test"})
    assert hist is not None
    assert hist.count == 1
    assert hist.sum == 1.5


def test_bm08_observe_tokenization_duration():
    """Test observing tokenization duration."""
    collector = MetricsCollector(worker_id="test")

    collector.observe("tokenization_duration_seconds", 0.05)

    hist = collector.get_histogram("tokenization_duration_seconds", {"worker_id": "test"})
    assert hist is not None
    assert hist.count == 1
    assert hist.sum == 0.05


def test_bm08_increment_retry_count():
    """Test incrementing retry count."""
    collector = MetricsCollector(worker_id="test")

    collector.increment("retry_count_total", 1)
    collector.increment("retry_count_total", 2)

    counter = collector.get_counter("retry_count_total", {"worker_id": "test"})
    assert counter is not None
    assert counter.value == 3


def test_bm08_set_warmup_iterations():
    """Test setting warmup iterations gauge."""
    collector = MetricsCollector(worker_id="test")

    collector.set("warmup_iterations", 3)

    gauge = collector.get_gauge("warmup_iterations", {"worker_id": "test"})
    assert gauge is not None
    assert gauge.value == 3


def test_bm08_all_new_metrics_initialized():
    """Test that all 9 new metrics are initialized."""
    collector = MetricsCollector(worker_id="test")

    # Expected new metrics from BM-08
    expected_histograms = [
        "model_load_duration_seconds",
        "tokenization_duration_seconds",
        "l3_encoding_duration_seconds",
        "l3_lookup_duration_seconds",
        "retry_duration_seconds",
        "batch_preparation_duration_seconds",
    ]

    expected_counters = ["retry_count_total"]

    expected_gauges = ["warmup_iterations", "actual_iterations"]

    # Check histograms
    histogram_names = [h.name for h in collector._histograms.values()]
    for metric in expected_histograms:
        assert metric in histogram_names, f"Missing histogram: {metric}"

    # Check counters
    counter_names = [c.name for c in collector._counters.values()]
    for metric in expected_counters:
        assert metric in counter_names, f"Missing counter: {metric}"

    # Check gauges
    gauge_names = [g.name for g in collector._gauges.values()]
    for metric in expected_gauges:
        assert metric in gauge_names, f"Missing gauge: {metric}"
