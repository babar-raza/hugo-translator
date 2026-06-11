"""
Tests for metrics collection system.
"""

from src.observability.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsCollector,
    get_metrics,
    init_metrics,
)


class TestCounter:
    """Test Counter metric."""

    def test_counter_creation(self):
        """Test creating a counter."""
        counter = Counter(name="test_counter", help_text="Test counter")
        assert counter.name == "test_counter"
        assert counter.value == 0.0

    def test_counter_increment(self):
        """Test incrementing counter."""
        counter = Counter(name="test", help_text="Test")
        counter.increment()
        assert counter.get() == 1.0

        counter.increment(5.0)
        assert counter.get() == 6.0

    def test_counter_with_labels(self):
        """Test counter with labels."""
        counter = Counter(
            name="requests_total",
            help_text="Total requests",
            labels={"method": "GET", "path": "/api"},
        )
        assert counter.labels == {"method": "GET", "path": "/api"}


class TestGauge:
    """Test Gauge metric."""

    def test_gauge_creation(self):
        """Test creating a gauge."""
        gauge = Gauge(name="test_gauge", help_text="Test gauge")
        assert gauge.name == "test_gauge"
        assert gauge.value == 0.0

    def test_gauge_set(self):
        """Test setting gauge value."""
        gauge = Gauge(name="test", help_text="Test")
        gauge.set(42.5)
        assert gauge.get() == 42.5

    def test_gauge_increment_decrement(self):
        """Test incrementing and decrementing gauge."""
        gauge = Gauge(name="test", help_text="Test")
        gauge.increment(10.0)
        assert gauge.get() == 10.0

        gauge.decrement(3.0)
        assert gauge.get() == 7.0


class TestHistogram:
    """Test Histogram metric."""

    def test_histogram_creation(self):
        """Test creating a histogram."""
        hist = Histogram(name="test_histogram", help_text="Test histogram")
        assert hist.name == "test_histogram"
        assert hist.count == 0
        assert hist.sum == 0.0

    def test_histogram_observe(self):
        """Test recording observations."""
        hist = Histogram(name="test", help_text="Test")
        hist.observe(1.5)
        hist.observe(2.5)
        hist.observe(3.0)

        assert hist.count == 3
        assert hist.sum == 7.0

    def test_histogram_stats(self):
        """Test histogram statistics."""
        hist = Histogram(name="test", help_text="Test")
        hist.observe(1.0)
        hist.observe(2.0)
        hist.observe(3.0)

        stats = hist.get_stats()
        assert stats["count"] == 3
        assert stats["sum"] == 6.0
        assert stats["mean"] == 2.0
        assert stats["min"] == 1.0
        assert stats["max"] == 3.0

    def test_histogram_buckets(self):
        """Test histogram buckets."""
        hist = Histogram(name="test", help_text="Test")
        hist.observe(0.05)  # Should be in 0.1 bucket
        hist.observe(0.5)  # Should be in 0.5 bucket
        hist.observe(2.0)  # Should be in multiple buckets

        assert hist.bucket_counts[0.1] == 1
        assert hist.bucket_counts[0.5] == 2
        assert hist.bucket_counts[1.0] == 2
        assert hist.bucket_counts[5.0] == 3


class TestMetricsCollector:
    """Test MetricsCollector."""

    def test_collector_creation(self):
        """Test creating metrics collector."""
        collector = MetricsCollector(worker_id="test-worker")
        assert collector.worker_id == "test-worker"

    def test_register_counter(self):
        """Test registering a counter."""
        collector = MetricsCollector()
        counter = collector.register_counter("test_counter", "Test counter")

        assert isinstance(counter, Counter)
        assert counter.name == "test_counter"

    def test_register_gauge(self):
        """Test registering a gauge."""
        collector = MetricsCollector()
        gauge = collector.register_gauge("test_gauge", "Test gauge")

        assert isinstance(gauge, Gauge)
        assert gauge.name == "test_gauge"

    def test_register_histogram(self):
        """Test registering a histogram."""
        collector = MetricsCollector()
        hist = collector.register_histogram("test_histogram", "Test histogram")

        assert isinstance(hist, Histogram)
        assert hist.name == "test_histogram"

    def test_increment_counter(self):
        """Test incrementing counter via collector."""
        collector = MetricsCollector(worker_id="test")
        collector.register_counter("requests", "Requests", labels={"worker_id": "test"})

        collector.increment("requests", 5.0)
        metrics = collector.get_all()

        # Find the counter metric
        counter_key = [k for k in metrics.keys() if "requests" in k][0]
        assert metrics[counter_key]["value"] == 5.0

    def test_set_gauge(self):
        """Test setting gauge via collector."""
        collector = MetricsCollector(worker_id="test")
        collector.register_gauge("queue_depth", "Queue depth", labels={"worker_id": "test"})

        collector.set_gauge("queue_depth", 42.0)
        metrics = collector.get_all()

        gauge_key = [k for k in metrics.keys() if "queue_depth" in k and "test" in k][0]
        assert metrics[gauge_key]["value"] == 42.0

    def test_observe_histogram(self):
        """Test observing histogram via collector."""
        collector = MetricsCollector(worker_id="test")
        collector.register_histogram("duration", "Duration", labels={"worker_id": "test"})

        collector.observe("duration", 1.5)
        collector.observe("duration", 2.5)

        metrics = collector.get_all()
        # Find the histogram we just registered (not the core metrics ones)
        hist_key = [k for k in metrics.keys() if k.startswith("duration{")][0]

        assert metrics[hist_key]["stats"]["count"] == 2
        assert metrics[hist_key]["stats"]["sum"] == 4.0

    def test_get_all_metrics(self):
        """Test getting all metrics."""
        collector = MetricsCollector(worker_id="test")
        collector.register_counter("counter1", "Counter 1")
        collector.register_gauge("gauge1", "Gauge 1")
        collector.register_histogram("hist1", "Histogram 1")

        metrics = collector.get_all()

        assert len(metrics) >= 3
        assert any("counter1" in k for k in metrics.keys())
        assert any("gauge1" in k for k in metrics.keys())
        assert any("hist1" in k for k in metrics.keys())

    def test_export_prometheus(self):
        """Test Prometheus export format."""
        collector = MetricsCollector(worker_id="test")
        counter = collector.register_counter("requests_total", "Total requests")
        counter.increment(10.0)

        output = collector.export_prometheus()

        assert "# HELP requests_total Total requests" in output
        assert "# TYPE requests_total counter" in output
        assert "requests_total" in output

    def test_core_metrics_initialized(self):
        """Test that core metrics are initialized."""
        collector = MetricsCollector(worker_id="test-worker")
        metrics = collector.get_all()

        # Check for core translation metrics
        metric_names = [m["name"] for m in metrics.values()]

        assert "translations_total" in metric_names
        assert "tm_lookups_total" in metric_names
        assert "queue_depth" in metric_names


class TestGlobalMetrics:
    """Test global metrics functions."""

    def test_get_metrics(self):
        """Test getting global metrics instance."""
        metrics = get_metrics()
        assert isinstance(metrics, MetricsCollector)

    def test_init_metrics(self):
        """Test initializing global metrics."""
        metrics = init_metrics(
            worker_id="custom-worker",
            push_interval=30,
            enable_push=False,
        )

        assert metrics.worker_id == "custom-worker"
        assert metrics.push_interval == 30
