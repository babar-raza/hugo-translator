"""Unit tests for AdaptiveEMACalculator."""
from src.observability.progress import AdaptiveEMACalculator


class TestAdaptiveEMACalculator:
    """Test adaptive EMA calculator with volatility detection."""

    def test_initialization(self):
        """Test AdaptiveEMACalculator initializes with correct defaults."""
        ema = AdaptiveEMACalculator()

        assert ema.baseline_alpha == 0.3
        assert ema.adaptive_alpha == 0.7
        assert ema.volatility_threshold == 0.30
        assert ema.window_size == 10
        assert ema._current_alpha == 0.3

    def test_initialization_with_custom_parameters(self):
        """Test AdaptiveEMACalculator with custom parameters."""
        ema = AdaptiveEMACalculator(
            baseline_alpha=0.2,
            adaptive_alpha=0.8,
            window_size=20,
            volatility_threshold=0.25
        )

        assert ema.baseline_alpha == 0.2
        assert ema.adaptive_alpha == 0.8
        assert ema.window_size == 20
        assert ema.volatility_threshold == 0.25

    def test_stable_rate_uses_baseline_alpha(self):
        """Test low volatility uses baseline alpha (0.3)."""
        ema = AdaptiveEMACalculator(baseline_alpha=0.3, adaptive_alpha=0.7)

        # Add 10 samples with low volatility (all same value)
        for _ in range(10):
            ema.add_sample(10.0)

        state = ema.get_volatility_state()
        assert state["is_volatile"] == False
        assert state["current_alpha"] == 0.3
        assert state["cv"] < 0.30

    def test_volatile_rate_uses_adaptive_alpha(self):
        """Test high volatility switches to adaptive alpha (0.7)."""
        ema = AdaptiveEMACalculator(baseline_alpha=0.3, adaptive_alpha=0.7)

        # Add samples with high volatility
        ema.add_sample(100.0)
        ema.add_sample(20.0)
        ema.add_sample(100.0)
        ema.add_sample(20.0)
        ema.add_sample(100.0)

        state = ema.get_volatility_state()
        assert state["is_volatile"] == True
        assert state["current_alpha"] == 0.7
        assert state["cv"] > 0.30

    def test_coefficient_of_variation_calculation(self):
        """Test CV calculation is correct."""
        ema = AdaptiveEMACalculator()

        # Add samples: mean=10, std_dev=0 → CV=0
        for _ in range(5):
            ema.add_sample(10.0)

        state = ema.get_volatility_state()
        assert state["cv"] == 0.0

        # Add samples with variation: [10, 20, 30] → CV > 0
        ema.reset()
        ema.add_sample(10.0)
        ema.add_sample(20.0)
        ema.add_sample(30.0)

        state = ema.get_volatility_state()
        # mean = 20, std_dev = 8.16, CV = 8.16/20 = 0.408
        assert state["cv"] > 0.3

    def test_cv_returns_zero_with_insufficient_samples(self):
        """Test CV returns 0 when less than 2 samples."""
        ema = AdaptiveEMACalculator()

        # No samples
        state = ema.get_volatility_state()
        assert state["cv"] == 0.0

        # One sample
        ema.add_sample(10.0)
        state = ema.get_volatility_state()
        assert state["cv"] == 0.0

    def test_cv_returns_zero_when_mean_is_zero(self):
        """Test CV returns 0 when mean is zero (avoid division by zero)."""
        ema = AdaptiveEMACalculator()

        ema.add_sample(0.0)
        ema.add_sample(0.0)
        ema.add_sample(0.0)

        state = ema.get_volatility_state()
        assert state["cv"] == 0.0

    def test_ema_value_with_stable_rate(self):
        """Test EMA converges correctly with stable rate."""
        ema = AdaptiveEMACalculator(baseline_alpha=0.3)

        # Add stable samples
        for _ in range(10):
            value = ema.add_sample(10.0)

        # Should converge to 10.0
        assert 9.0 < ema.get_value() <= 10.0

    def test_ema_value_with_volatile_rate(self):
        """Test EMA responds faster with volatile rate (higher alpha)."""
        ema = AdaptiveEMACalculator(baseline_alpha=0.3, adaptive_alpha=0.7)

        # Start with high value
        for _ in range(5):
            ema.add_sample(100.0)

        # Sudden drop (creates volatility)
        for _ in range(5):
            ema.add_sample(20.0)

        state = ema.get_volatility_state()
        # Should detect volatility and switch to adaptive alpha
        assert state["is_volatile"] == True
        assert state["current_alpha"] == 0.7

    def test_moving_average_calculation(self):
        """Test simple moving average calculation."""
        ema = AdaptiveEMACalculator(window_size=5)

        # Add samples
        ema.add_sample(10.0)
        ema.add_sample(20.0)
        ema.add_sample(30.0)

        # SMA = (10 + 20 + 30) / 3 = 20
        assert ema.get_moving_average() == 20.0

    def test_reset_clears_state(self):
        """Test reset clears all state including alpha."""
        ema = AdaptiveEMACalculator(baseline_alpha=0.3, adaptive_alpha=0.7)

        # Add volatile samples
        ema.add_sample(100.0)
        ema.add_sample(20.0)
        ema.add_sample(100.0)

        # Should be volatile
        state = ema.get_volatility_state()
        assert state["is_volatile"] == True

        # Reset
        ema.reset()

        # Should be cleared
        assert ema.get_value() == 0.0
        assert ema.get_moving_average() == 0.0
        state = ema.get_volatility_state()
        assert state["sample_count"] == 0
        assert state["current_alpha"] == 0.3  # Reset to baseline

    def test_window_size_limits_samples(self):
        """Test window size limits number of samples tracked."""
        ema = AdaptiveEMACalculator(window_size=5)

        # Add 10 samples (more than window size)
        for i in range(10):
            ema.add_sample(float(i))

        state = ema.get_volatility_state()
        # Should only track last 5 samples
        assert state["sample_count"] == 5

    def test_volatility_threshold_controls_switching(self):
        """Test volatility threshold controls when alpha switches."""
        # High threshold - harder to trigger volatility
        ema_high = AdaptiveEMACalculator(volatility_threshold=0.5)

        # Low threshold - easier to trigger volatility
        ema_low = AdaptiveEMACalculator(volatility_threshold=0.1)

        # Same volatile samples
        for val in [10.0, 20.0, 10.0, 20.0]:
            ema_high.add_sample(val)
            ema_low.add_sample(val)

        # High threshold should not detect volatility
        state_high = ema_high.get_volatility_state()
        # CV for [10, 20, 10, 20] is around 0.33

        # Low threshold should detect volatility
        state_low = ema_low.get_volatility_state()
        assert state_low["is_volatile"] == True

    def test_thread_safety(self):
        """Test basic thread safety with locks."""
        import threading

        ema = AdaptiveEMACalculator()

        def add_samples():
            for _ in range(100):
                ema.add_sample(10.0)

        # Run in multiple threads
        threads = [threading.Thread(target=add_samples) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have processed all samples without errors
        value = ema.get_value()
        assert value > 0
        state = ema.get_volatility_state()
        assert state["sample_count"] == 10  # window_size limit
