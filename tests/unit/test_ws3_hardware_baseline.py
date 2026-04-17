"""
Unit tests for WS3-HARDWARE-BASELINE integration.

Tests the priority hierarchy for batch size initialization:
1. Config override > Script conservative > Hardware baseline > Hardcoded (20)
"""

import pytest

from src.translation_engine.extractor.batch_stats_tracker import BatchStatsTracker


class TestHardwareBaselinePriority:
    """Test priority hierarchy for hardware baseline."""

    @pytest.fixture
    def base_config(self, tmp_path):
        """Base configuration without overrides."""
        return {
            'stats_file': str(tmp_path / 'batch_stats.json'),
            'fallback_rate_threshold': 0.05,
            'reduction_factor': 0.80,
            'increase_factor': 1.10,
            'min_batches_before_increase': 5,
            'stats_retention_days': 30,
        }

    def test_priority_1_config_override_highest(self, base_config):
        """Config override takes precedence over all other sources."""
        config = {
            **base_config,
            'language_overrides': {
                'de': {'initial_batch_size': 50}
            }
        }
        tracker = BatchStatsTracker(config, hardware_baseline=30)

        # Config override (50) beats hardware baseline (30)
        assert tracker._get_language_baseline('de') == 50

    def test_priority_2_cyrillic_conservative_cap(self, base_config):
        """Cyrillic languages capped at conservative value even with higher hardware baseline."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=30)

        # Cyrillic conservative (8) caps hardware baseline (30)
        assert tracker._get_language_baseline('ru') == 8
        assert tracker._get_language_baseline('bg') == 8
        assert tracker._get_language_baseline('uk') == 8

    def test_priority_2_cyrillic_uses_hardware_if_lower(self, base_config):
        """Cyrillic languages use hardware baseline if it's lower than conservative cap."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=5)

        # Hardware baseline (5) is lower than conservative (8), so use 5
        assert tracker._get_language_baseline('ru') == 5

    def test_priority_2_arabic_conservative_cap(self, base_config):
        """Arabic languages capped at conservative value even with higher hardware baseline."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=30)

        # Arabic conservative (10) caps hardware baseline (30)
        assert tracker._get_language_baseline('ar') == 10
        assert tracker._get_language_baseline('fa') == 10

    def test_priority_2_arabic_uses_hardware_if_lower(self, base_config):
        """Arabic languages use hardware baseline if it's lower than conservative cap."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=7)

        # Hardware baseline (7) is lower than conservative (10), so use 7
        assert tracker._get_language_baseline('ar') == 7

    def test_priority_3_hardware_baseline_for_latin(self, base_config):
        """Latin languages use hardware baseline when available."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=30)

        # Hardware baseline (30) used instead of hardcoded (20)
        assert tracker._get_language_baseline('de') == 30
        assert tracker._get_language_baseline('fr') == 30
        assert tracker._get_language_baseline('es') == 30

    def test_priority_4_hardcoded_fallback_when_no_hardware(self, base_config):
        """Hardcoded value used when hardware baseline not available."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=None)

        # No hardware baseline, fall back to hardcoded (20)
        assert tracker._get_language_baseline('de') == 20
        assert tracker._get_language_baseline('fr') == 20

    def test_priority_4_hardcoded_fallback_cyrillic_without_hardware(self, base_config):
        """Cyrillic falls back to conservative value when no hardware baseline."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=None)

        # No hardware baseline, use conservative (8)
        assert tracker._get_language_baseline('ru') == 8
        assert tracker._get_language_baseline('bg') == 8


class TestBackwardCompatibility:
    """Test backward compatibility when hardware_baseline is not provided."""

    @pytest.fixture
    def base_config(self, tmp_path):
        """Base configuration."""
        return {
            'stats_file': str(tmp_path / 'batch_stats.json'),
        }

    def test_none_default_parameter(self, base_config):
        """hardware_baseline defaults to None when not provided."""
        tracker = BatchStatsTracker(base_config)
        assert tracker.hardware_baseline is None

    def test_behavior_identical_to_pre_ws3(self, base_config):
        """Behavior identical to pre-WS3 when hardware_baseline=None."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=None)

        # Latin languages: hardcoded 20
        assert tracker._get_language_baseline('de') == 20
        assert tracker._get_language_baseline('fr') == 20

        # Cyrillic: conservative 8
        assert tracker._get_language_baseline('ru') == 8
        assert tracker._get_language_baseline('bg') == 8

        # Arabic: conservative 10
        assert tracker._get_language_baseline('ar') == 10


class TestConfigOverridePrecedence:
    """Test that config overrides always win."""

    @pytest.fixture
    def base_config(self, tmp_path):
        """Configuration with language overrides."""
        return {
            'stats_file': str(tmp_path / 'batch_stats.json'),
            'language_overrides': {
                'ru': {'initial_batch_size': 50},  # Override Cyrillic conservative
                'de': {'initial_batch_size': 100}, # Override hardware baseline
            }
        }

    def test_override_beats_cyrillic_conservative(self, base_config):
        """Config override beats Cyrillic conservative cap."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=30)

        # Config override (50) beats conservative (8) and hardware (30)
        assert tracker._get_language_baseline('ru') == 50

    def test_override_beats_hardware_baseline(self, base_config):
        """Config override beats hardware baseline."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=30)

        # Config override (100) beats hardware baseline (30)
        assert tracker._get_language_baseline('de') == 100

    def test_override_beats_hardcoded_fallback(self, base_config):
        """Config override beats hardcoded fallback."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=None)

        # Config override (100) beats hardcoded (20)
        assert tracker._get_language_baseline('de') == 100


class TestCyrillicSafety:
    """Test that Cyrillic safety cap is always enforced."""

    @pytest.fixture
    def base_config(self, tmp_path):
        """Base configuration."""
        return {
            'stats_file': str(tmp_path / 'batch_stats.json'),
        }

    def test_cyrillic_never_exceeds_conservative_without_override(self, base_config):
        """Cyrillic languages never exceed conservative cap without config override."""
        # Test various hardware baselines
        for hardware_baseline in [10, 20, 30, 50, 100]:
            tracker = BatchStatsTracker(base_config, hardware_baseline=hardware_baseline)

            # All Cyrillic languages capped at 8
            assert tracker._get_language_baseline('ru') == 8
            assert tracker._get_language_baseline('bg') == 8
            assert tracker._get_language_baseline('uk') == 8

    def test_cyrillic_uses_lower_hardware_baseline(self, base_config):
        """Cyrillic uses hardware baseline if it's lower than conservative."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=5)

        # Hardware baseline (5) is lower than conservative (8)
        assert tracker._get_language_baseline('ru') == 5

    def test_cyrillic_config_override_can_exceed_conservative(self, base_config):
        """Config override can exceed conservative cap (user knows what they're doing)."""
        config = {
            **base_config,
            'language_overrides': {
                'ru': {'initial_batch_size': 50}
            }
        }
        tracker = BatchStatsTracker(config, hardware_baseline=30)

        # Config override (50) can exceed conservative (8)
        assert tracker._get_language_baseline('ru') == 50


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    @pytest.fixture
    def base_config(self, tmp_path):
        """Base configuration."""
        return {
            'stats_file': str(tmp_path / 'batch_stats.json'),
        }

    def test_gpu_runtime_with_high_vram(self, base_config):
        """GPU with high VRAM provides large hardware baseline."""
        # Simulates GPU optimizer suggesting batch_size=60
        tracker = BatchStatsTracker(base_config, hardware_baseline=60)

        # Latin languages use hardware baseline
        assert tracker._get_language_baseline('de') == 60
        assert tracker._get_language_baseline('fr') == 60

        # Cyrillic capped at conservative
        assert tracker._get_language_baseline('ru') == 8
        assert tracker._get_language_baseline('bg') == 8

    def test_gpu_runtime_with_low_vram(self, base_config):
        """GPU with low VRAM provides small hardware baseline."""
        # Simulates GPU optimizer suggesting batch_size=4
        tracker = BatchStatsTracker(base_config, hardware_baseline=4)

        # Latin languages use hardware baseline
        assert tracker._get_language_baseline('de') == 4

        # Cyrillic uses hardware baseline (lower than conservative)
        assert tracker._get_language_baseline('ru') == 4

    def test_cpu_runtime_no_gpu_optimizer(self, base_config):
        """CPU runtime has no GPU optimizer, hardware_baseline=None."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=None)

        # All languages use pre-WS3 defaults
        assert tracker._get_language_baseline('de') == 20
        assert tracker._get_language_baseline('ru') == 8
        assert tracker._get_language_baseline('ar') == 10

    def test_mixed_config_and_hardware(self, base_config):
        """Mix of config overrides and hardware baseline."""
        config = {
            **base_config,
            'language_overrides': {
                'de': {'initial_batch_size': 100},  # Explicit override
            }
        }
        tracker = BatchStatsTracker(config, hardware_baseline=30)

        # German: config override
        assert tracker._get_language_baseline('de') == 100

        # French: hardware baseline
        assert tracker._get_language_baseline('fr') == 30

        # Russian: conservative cap
        assert tracker._get_language_baseline('ru') == 8


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def base_config(self, tmp_path):
        """Base configuration."""
        return {
            'stats_file': str(tmp_path / 'batch_stats.json'),
        }

    def test_hardware_baseline_zero(self, base_config):
        """hardware_baseline=0 is treated as valid value."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=0)

        # Zero is valid (though unusual), should be used
        # Note: This might indicate GPU optimizer failure, but not None
        assert tracker._get_language_baseline('de') == 0

    def test_hardware_baseline_very_large(self, base_config):
        """Very large hardware baseline values."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=1000)

        # Large value used for Latin languages
        assert tracker._get_language_baseline('de') == 1000

        # Cyrillic still capped
        assert tracker._get_language_baseline('ru') == 8

    def test_unknown_language_code(self, base_config):
        """Unknown language codes use hardware baseline or fallback."""
        tracker = BatchStatsTracker(base_config, hardware_baseline=30)

        # Unknown language uses hardware baseline (not Cyrillic/Arabic)
        assert tracker._get_language_baseline('xx') == 30

        # Without hardware baseline, uses hardcoded fallback
        tracker_no_hw = BatchStatsTracker(base_config, hardware_baseline=None)
        assert tracker_no_hw._get_language_baseline('xx') == 20
