"""
Comprehensive tests for metrics collection system.

Tests all metric types, derived metrics, and Prometheus export format.
"""

import pytest
import threading
import time

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
        assert counter.help_text == "Test counter"
        assert counter.value == 0.0

    def test_counter_increment(self):
        """Test incrementing counter."""
        counter = Counter(name="test", help_text="Test")
        counter.increment()
        assert counter.get() == 1.0

        counter.increment(5.0)
        assert counter.get() == 6.0

    def test_counter_increment_float(self):
        """Test incrementing counter with floats."""
        counter = Counter(name="test", help_text="Test")
        counter.increment(1.5)
        counter.increment(2.3)
        assert counter.get() == 3.8

    def test_counter_with_labels(self):
        """Test counter with labels."""
        counter = Counter(
            name="requests_total",
            help_text="Total requests",
            labels={"method": "GET", "path": "/api"},
        )
        assert counter.labels == {"method": "GET", "path": "/api"}

    def test_counter_only_increases(self):
        """Test that counter only increases."""
        counter = Counter(name="test", help_text="Test")
        counter.increment(5.0)
        assert counter.get() == 5.0
        counter.increment(3.0)
        assert counter.get() == 8.0


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
        gauge.set(10.0)
        assert gauge.get() == 10.0

    def test_gauge_increment_decrement(self):
        """Test incrementing and decrementing gauge."""
        gauge = Gauge(name="test", help_text="Test")
        gauge.increment(10.0)
        assert gauge.get() == 10.0

        gauge.decrement(3.0)
        assert gauge.get() == 7.0

        gauge.decrement(10.0)
        assert gauge.get() == -3.0

    def test_gauge_can_be_negative(self):
        """Test that gauge can be negative."""
        gauge = Gauge(name="test", help_text="Test")
        gauge.set(-5.0)
        assert gauge.get() == -5.0


class TestHistogram:
    """Test Histogram metric."""

    def test_histogram_creation(self):
        """Test creating a histogram."""
        hist = Histogram(name="test_histogram", help_text="Test histogram")
        assert hist.name == "test_histogram"
        assert hist.count == 0
        assert hist.sum == 0.0
        assert len(hist.buckets) > 0

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
        hist.observe(4.0)
        hist.observe(5.0)

        stats = hist.get_stats()
        assert stats["count"] == 5
        assert stats["sum"] == 15.0
        assert stats["mean"] == 3.0
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0

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

    def test_histogram_empty_stats(self):
        """Test histogram statistics when empty."""
        hist = Histogram(name="test", help_text="Test")
        stats = hist.get_stats()

        assert stats["count"] == 0
        assert stats["sum"] == 0.0
        assert stats["mean"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0

    def test_histogram_custom_buckets(self):
        """Test histogram with custom buckets."""
        hist = Histogram(
            name="test",
            help_text="Test",
            buckets=[1.0, 5.0, 10.0]
        )
        hist.__post_init__()

        hist.observe(0.5)
        hist.observe(3.0)
        hist.observe(7.0)

        assert hist.bucket_counts[1.0] == 1
        assert hist.bucket_counts[5.0] == 2
        assert hist.bucket_counts[10.0] == 3


class TestMetricsCollector:
    """Test MetricsCollector."""

    def test_collector_creation(self):
        """Test creating metrics collector."""
        collector = MetricsCollector(worker_id="test-worker")
        assert collector.worker_id == "test-worker"
        assert collector.push_interval == 60
        assert collector.enable_push is False

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

    def test_prometheus_export_with_labels(self):
        """Test Prometheus export with labels."""
        collector = MetricsCollector(worker_id="test")
        counter = collector.register_counter(
            "requests_total",
            "Total requests",
            labels={"method": "GET", "status": "200"}
        )
        counter.increment(5.0)

        output = collector.export_prometheus()

        assert 'method="GET"' in output
        assert 'status="200"' in output

    def test_core_metrics_initialized(self):
        """Test that core metrics are initialized."""
        collector = MetricsCollector(worker_id="test-worker")
        metrics = collector.get_all()

        # Check for core translation metrics
        metric_names = [m["name"] for m in metrics.values()]

        assert "translations_total" in metric_names
        assert "translations_success" in metric_names
        assert "translations_failed" in metric_names
        assert "translation_errors_total" in metric_names
        assert "tm_lookups_total" in metric_names
        assert "tm_hits_l1" in metric_names
        assert "tm_hits_l2" in metric_names
        assert "tm_hits_l3" in metric_names
        assert "queue_depth" in metric_names
        assert "translation_duration_seconds" in metric_names

    def test_tm_hit_rate_calculation(self):
        """Test TM hit rate calculation."""
        collector = MetricsCollector(worker_id="test")

        # Simulate TM lookups
        collector.increment("tm_lookups_total", 100)
        collector.increment("tm_hits_l1", 30)
        collector.increment("tm_hits_l2", 20)
        collector.increment("tm_hits_l3", 10)

        hit_rate = collector.get_tm_hit_rate()
        assert hit_rate == 0.6  # 60% hit rate

    def test_tm_hit_rate_no_lookups(self):
        """Test TM hit rate when no lookups."""
        collector = MetricsCollector(worker_id="test")
        hit_rate = collector.get_tm_hit_rate()
        assert hit_rate == 0.0

    def test_error_rate_calculation(self):
        """Test error rate calculation."""
        collector = MetricsCollector(worker_id="test")

        collector.increment("translations_total", 100)
        collector.increment("translations_failed", 5)

        error_rate = collector.get_error_rate()
        assert error_rate == 0.05  # 5% error rate

    def test_error_rate_no_translations(self):
        """Test error rate when no translations."""
        collector = MetricsCollector(worker_id="test")
        error_rate = collector.get_error_rate()
        assert error_rate == 0.0

    def test_stats_summary(self):
        """Test getting stats summary."""
        collector = MetricsCollector(worker_id="test")

        # Simulate some activity
        collector.increment("translations_total", 100)
        collector.increment("translations_success", 95)
        collector.increment("translations_failed", 5)
        collector.increment("tm_lookups_total", 200)
        collector.increment("tm_hits_l1", 80)
        collector.increment("tm_hits_l2", 60)
        collector.increment("tm_hits_l3", 20)
        collector.set_gauge("queue_depth", 15)
        collector.observe("translation_duration_seconds", 1.5)
        collector.observe("translation_duration_seconds", 2.5)

        stats = collector.get_stats_summary()

        assert stats["worker_id"] == "test"
        assert stats["translations"]["total"] == 100
        assert stats["translations"]["success"] == 95
        assert stats["translations"]["failed"] == 5
        assert stats["translations"]["success_rate"] == 0.95
        assert stats["tm"]["lookups"] == 200
        assert stats["tm"]["hit_rate"] == 0.8  # 160/200
        assert stats["queue"]["depth"] == 15
        assert stats["performance"]["translation_duration"]["count"] == 2

    def test_thread_safety(self):
        """Test that metrics collection is thread-safe."""
        collector = MetricsCollector(worker_id="test")

        def increment_counter():
            for _ in range(100):
                collector.increment("translations_total", 1)

        threads = [threading.Thread(target=increment_counter) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        metrics = collector.get_all()
        total_key = [k for k in metrics.keys() if "translations_total" in k][0]
        assert metrics[total_key]["value"] == 1000  # 10 threads * 100 increments

    def test_histogram_prometheus_export(self):
        """Test histogram export in Prometheus format."""
        collector = MetricsCollector(worker_id="test")
        hist = collector.register_histogram(
            "request_duration",
            "Request duration",
            labels={"worker_id": "test"}
        )

        hist.observe(0.05)
        hist.observe(0.5)
        hist.observe(2.0)

        output = collector.export_prometheus()

        assert "# TYPE request_duration histogram" in output
        assert "request_duration_bucket" in output
        assert "request_duration_sum" in output
        assert "request_duration_count" in output
        assert 'le=' in output  # Bucket labels


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
        assert metrics.enable_push is False

    def test_get_metrics_singleton(self):
        """Test that get_metrics returns singleton."""
        metrics1 = get_metrics()
        metrics2 = get_metrics()
        assert metrics1 is metrics2


class TestMetricsWithLabels:
    """Test metrics with various label combinations."""

    def test_counter_with_multiple_labels(self):
        """Test counter with multiple labels."""
        collector = MetricsCollector(worker_id="test")
        collector.register_counter(
            "http_requests_total",
            "Total HTTP requests",
            labels={"worker_id": "test", "method": "GET", "endpoint": "/api", "status": "200"}
        )

        collector.increment("http_requests_total", 5, {"method": "GET", "endpoint": "/api", "status": "200"})

        metrics = collector.get_all()
        assert any("http_requests_total" in k for k in metrics.keys())

    def test_histogram_percentiles(self):
        """Test histogram bucket distribution."""
        collector = MetricsCollector(worker_id="test")
        hist = collector.register_histogram("latency", "Latency", labels={"worker_id": "test"})

        # Add values in different ranges
        for _ in range(10):
            hist.observe(0.05)  # Fast
        for _ in range(5):
            hist.observe(0.5)   # Medium
        for _ in range(2):
            hist.observe(5.0)   # Slow

        stats = hist.get_stats()
        assert stats["count"] == 17
        assert hist.bucket_counts[0.1] == 10  # Fast requests
        assert hist.bucket_counts[1.0] == 15  # Fast + medium
        assert hist.bucket_counts[10.0] == 17  # All requests


class TestMetricsFailureCases:
    """Test metrics behavior in failure scenarios."""

    def test_increment_nonexistent_counter(self):
        """Test incrementing non-existent counter logs warning but doesn't crash."""
        collector = MetricsCollector(worker_id="test")
        # Should not raise exception
        collector.increment("nonexistent_counter", 5)

    def test_set_nonexistent_gauge(self):
        """Test setting non-existent gauge logs warning but doesn't crash."""
        collector = MetricsCollector(worker_id="test")
        # Should not raise exception
        collector.set_gauge("nonexistent_gauge", 42)

    def test_observe_nonexistent_histogram(self):
        """Test observing non-existent histogram logs warning but doesn't crash."""
        collector = MetricsCollector(worker_id="test")
        # Should not raise exception
        collector.observe("nonexistent_histogram", 1.5)

    def test_empty_collector_export(self):
        """Test exporting metrics from empty collector."""
        collector = MetricsCollector(worker_id="test")
        # Clear core metrics for this test
        collector._counters.clear()
        collector._gauges.clear()
        collector._histograms.clear()

        output = collector.export_prometheus()
        # Should return empty or minimal output without crashing
        assert isinstance(output, str)


class TestMetricsPerformance:
    """Test metrics collection performance."""

    def test_metrics_collection_overhead(self):
        """Test that metrics collection has minimal overhead."""
        collector = MetricsCollector(worker_id="test")

        start = time.time()
        for _ in range(10000):
            collector.increment("translations_total", 1)
            collector.observe("translation_duration_seconds", 1.5)
        duration = time.time() - start

        # Should complete 10,000 operations in under 1 second
        assert duration < 1.0

    def test_prometheus_export_performance(self):
        """Test that Prometheus export is fast."""
        collector = MetricsCollector(worker_id="test")

        # Add lots of metrics
        for i in range(100):
            collector.register_counter(f"counter_{i}", f"Counter {i}")
            collector.increment(f"counter_{i}", i)

        start = time.time()
        output = collector.export_prometheus()
        duration = time.time() - start

        # Should export in under 0.1 seconds
        assert duration < 0.1
        assert len(output) > 0
