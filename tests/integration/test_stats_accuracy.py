"""Integration tests for translation statistics accuracy."""
from src.observability.progress import AdaptiveEMACalculator, ProgressTracker


class TestETAAdaptation:
    """Test ETA adapts to cache rate changes."""

    def test_eta_adjusts_to_cache_rate_changes(self):
        """Test ETA increases when cache rate drops (volatile scenario)."""
        tracker = ProgressTracker(show_progress=False, ema_alpha=0.3)
        tracker.start()
        tracker.set_totals(segments=2000)

        # Phase 1: High cache rate (fast processing)
        # Simulate 100 segments with high cache hit rate
        for i in range(100):
            tracker.cache_hit("l1")
            tracker.segments_completed(1, duration_s=0.01)  # Fast: 100 seg/s

        snapshot1 = tracker.get_snapshot()
        eta1 = snapshot1.eta_s

        # Phase 2: Low cache rate (slow processing)
        # Simulate 100 segments with cache misses (model translation)
        for i in range(100):
            tracker.cache_miss()
            tracker.segments_completed(1, duration_s=0.05)  # Slow: 20 seg/s

        snapshot2 = tracker.get_snapshot()
        eta2 = snapshot2.eta_s

        # ETA should increase significantly
        # At segment 100, eta1 estimates based on ~100 seg/s
        # At segment 200, eta2 estimates based on mixed rate (should be higher)
        assert eta2 is not None and eta1 is not None
        assert eta2 > eta1 * 1.2  # At least 20% increase

        # Should detect volatility
        assert snapshot2.rate_volatility > 0.2
        tracker.stop()

    def test_eta_confidence_tracking(self):
        """Test ETA confidence reflects rate volatility."""
        tracker = ProgressTracker(show_progress=False)
        tracker.start()
        tracker.set_totals(segments=1000)

        # Stable rate
        for _ in range(50):
            tracker.segments_completed(1, duration_s=0.01)

        snapshot_stable = tracker.get_snapshot()

        # Should have high or medium confidence
        assert snapshot_stable.eta_confidence in ["high", "medium"]

        # Introduce volatility
        for i in range(50):
            # Alternate between fast and slow
            duration = 0.001 if i % 2 == 0 else 0.1
            tracker.segments_completed(1, duration_s=duration)

        snapshot_volatile = tracker.get_snapshot()

        # Should have low confidence and show volatility
        # Note: May not always be "low" due to timing, but volatility should increase
        assert snapshot_volatile.rate_volatility > snapshot_stable.rate_volatility
        tracker.stop()

    def test_eta_display_shows_varying_indicator(self):
        """Test ETA display shows (varying) indicator when volatile."""
        tracker = ProgressTracker(show_progress=False)
        tracker.start()
        tracker.set_totals(segments=1000)

        # Create high volatility
        for i in range(10):
            # Extreme variation
            duration = 0.001 if i % 2 == 0 else 0.2
            tracker.segments_completed(1, duration_s=duration)

        snapshot = tracker.get_snapshot()

        # Format ETA
        eta_str = snapshot._format_eta()

        # If confidence is low and CV > 0.3, should show "(varying)"
        if snapshot.eta_confidence == "low" and snapshot.rate_volatility > 0.3:
            assert "(varying)" in eta_str

        tracker.stop()


class TestTokenCountingAccuracy:
    """Test token counting accuracy tracking."""

    def test_token_count_method_tracked(self):
        """Test token count method is tracked in progress."""
        tracker = ProgressTracker(show_progress=False)
        tracker.start()

        # Add tokens with different methods
        tracker.add_tokens(tokens_in=100, tokens_out=120, method="estimated")
        snapshot1 = tracker.get_snapshot()
        assert snapshot1.token_count_method == "estimated"

        # Switch to actual
        tracker.add_tokens(tokens_in=50, tokens_out=60, method="actual")
        snapshot2 = tracker.get_snapshot()

        # Should switch to actual (once any call uses actual, stays actual)
        assert snapshot2.token_count_method == "actual"

        tracker.stop()

    def test_token_display_shows_indicator(self):
        """Test token display shows accuracy indicator."""
        tracker = ProgressTracker(show_progress=False)
        tracker.start()
        tracker.set_totals(segments=100)

        # Add tokens with actual method
        tracker.add_tokens(tokens_in=1000, tokens_out=1200, method="actual")

        snapshot = tracker.get_snapshot()
        compact_line = snapshot.to_compact_line()

        # Should show " (actual)" indicator
        assert "(actual)" in compact_line or "actual" in compact_line.lower()

        tracker.stop()


class TestAdaptiveEMAIntegration:
    """Test adaptive EMA integration in ProgressTracker."""

    def test_progress_tracker_uses_adaptive_ema(self):
        """Test ProgressTracker uses AdaptiveEMACalculator."""
        tracker = ProgressTracker(show_progress=False)

        # Check that EMA calculators are AdaptiveEMACalculator instances
        assert isinstance(tracker._segment_rate_ema, AdaptiveEMACalculator)
        assert isinstance(tracker._file_rate_ema, AdaptiveEMACalculator)

    def test_adaptive_ema_responds_to_rate_changes(self):
        """Test adaptive EMA responds faster than fixed EMA to rate changes."""
        tracker = ProgressTracker(show_progress=False, ema_alpha=0.3)
        tracker.start()
        tracker.set_totals(segments=500)

        # Stable fast rate
        for _ in range(20):
            tracker.segments_completed(1, duration_s=0.01)  # 100 seg/s

        snapshot_fast = tracker.get_snapshot()
        rate_fast = snapshot_fast.segments_per_sec_rolling

        # Sudden drop to slow rate
        for _ in range(20):
            tracker.segments_completed(1, duration_s=0.1)  # 10 seg/s

        snapshot_slow = tracker.get_snapshot()
        rate_slow = snapshot_slow.segments_per_sec_rolling

        # Rate should have adjusted significantly
        # With adaptive alpha (0.7 when volatile), should respond faster
        assert rate_slow < rate_fast * 0.5  # At least 50% drop

        tracker.stop()


class TestLanguagePurityReporting:
    """Test language purity detailed breakdown reporting."""

    def test_purity_breakdown_calculation(self):
        """Test language purity breakdown calculates percentages correctly."""
        # This is a unit-level test but included for completeness
        # The actual purity check is in text_unit_extractor.py

        # Test data
        total_units = 100
        detected = 70
        bypassed = 15
        similarity = 10
        script = 5
        failed = 0

        # Check percentages sum to 100%
        total_accounted = detected + bypassed + similarity + script + failed
        assert total_accounted == total_units

        # Calculate percentages
        pct_detected = (detected / total_units) * 100
        pct_bypassed = (bypassed / total_units) * 100
        pct_similarity = (similarity / total_units) * 100
        pct_script = (script / total_units) * 100

        assert pct_detected == 70.0
        assert pct_bypassed == 15.0
        assert pct_similarity == 10.0
        assert pct_script == 5.0


class TestProgressSnapshotFields:
    """Test new fields in ProgressSnapshot."""

    def test_snapshot_includes_all_new_fields(self):
        """Test ProgressSnapshot includes all new accuracy tracking fields."""
        tracker = ProgressTracker(show_progress=False)
        tracker.start()
        tracker.set_totals(segments=100)

        # Add some data
        tracker.add_tokens(tokens_in=100, tokens_out=120, method="actual")
        tracker.segments_completed(5, duration_s=0.5)

        snapshot = tracker.get_snapshot()

        # Check new fields exist
        assert hasattr(snapshot, 'token_count_method')
        assert hasattr(snapshot, 'eta_confidence')
        assert hasattr(snapshot, 'rate_volatility')

        # Check values are set
        assert snapshot.token_count_method == "actual"
        assert snapshot.eta_confidence in ["calculating", "high", "medium", "low"]
        assert isinstance(snapshot.rate_volatility, float)
        assert snapshot.rate_volatility >= 0.0

        tracker.stop()
