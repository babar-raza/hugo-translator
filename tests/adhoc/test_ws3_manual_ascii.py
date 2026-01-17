"""
Manual test runner for WS3-HARDWARE-BASELINE (no pytest dependency).
"""
import sys
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Direct import to avoid engine dependencies
import importlib.util
spec = importlib.util.spec_from_file_location(
    "batch_stats_tracker",
    project_root / "src" / "translation_engine" / "extractor" / "batch_stats_tracker.py"
)
batch_stats_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch_stats_module)

BatchStatsTracker = batch_stats_module.BatchStatsTracker


def test_priority_1_config_override():
    """Config override takes precedence over hardware baseline."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {
            'stats_file': str(Path(tmp) / 'batch_stats.json'),
            'language_overrides': {
                'de': {'initial_batch_size': 50}
            }
        }
        tracker = BatchStatsTracker(config, hardware_baseline=30)
        result = tracker._get_language_baseline('de')
        assert result == 50, f"Expected 50, got {result}"
        print("[PASS] Test 1 passed: Config override (50) beats hardware baseline (30)")


def test_priority_2_cyrillic_conservative_cap():
    """Cyrillic languages capped at conservative value."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {'stats_file': str(Path(tmp) / 'batch_stats.json')}
        tracker = BatchStatsTracker(config, hardware_baseline=30)

        for lang in ['ru', 'bg', 'uk']:
            result = tracker._get_language_baseline(lang)
            assert result == 8, f"Expected 8 for {lang}, got {result}"
        print("[PASS] Test 2 passed: Cyrillic languages capped at 8 (min(8, 30))")


def test_priority_3_hardware_baseline_for_latin():
    """Latin languages use hardware baseline."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {'stats_file': str(Path(tmp) / 'batch_stats.json')}
        tracker = BatchStatsTracker(config, hardware_baseline=30)

        for lang in ['de', 'fr', 'es']:
            result = tracker._get_language_baseline(lang)
            assert result == 30, f"Expected 30 for {lang}, got {result}"
        print("[PASS] Test 3 passed: Latin languages use hardware baseline (30)")


def test_priority_4_hardcoded_fallback():
    """Hardcoded value used when no hardware baseline."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {'stats_file': str(Path(tmp) / 'batch_stats.json')}
        tracker = BatchStatsTracker(config, hardware_baseline=None)

        result_latin = tracker._get_language_baseline('de')
        assert result_latin == 20, f"Expected 20 for Latin, got {result_latin}"

        result_cyrillic = tracker._get_language_baseline('ru')
        assert result_cyrillic == 8, f"Expected 8 for Cyrillic, got {result_cyrillic}"

        print("[PASS] Test 4 passed: Hardcoded fallback (20 for Latin, 8 for Cyrillic)")


def test_backward_compatibility():
    """Behavior identical to pre-WS3 when hardware_baseline=None."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {'stats_file': str(Path(tmp) / 'batch_stats.json')}
        tracker = BatchStatsTracker(config)  # No hardware_baseline parameter

        assert tracker.hardware_baseline is None
        assert tracker._get_language_baseline('de') == 20
        assert tracker._get_language_baseline('ru') == 8
        assert tracker._get_language_baseline('ar') == 10

        print("[PASS] Test 5 passed: Backward compatibility maintained")


def test_cyrillic_uses_lower_hardware():
    """Cyrillic uses hardware baseline if lower than conservative."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {'stats_file': str(Path(tmp) / 'batch_stats.json')}
        tracker = BatchStatsTracker(config, hardware_baseline=5)

        result = tracker._get_language_baseline('ru')
        assert result == 5, f"Expected 5, got {result}"
        print("[PASS] Test 6 passed: Cyrillic uses hardware baseline (5) when lower than conservative (8)")


def test_config_override_beats_all():
    """Config override beats everything."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {
            'stats_file': str(Path(tmp) / 'batch_stats.json'),
            'language_overrides': {
                'ru': {'initial_batch_size': 50},  # Override Cyrillic conservative
            }
        }
        tracker = BatchStatsTracker(config, hardware_baseline=30)

        result = tracker._get_language_baseline('ru')
        assert result == 50, f"Expected 50, got {result}"
        print("[PASS] Test 7 passed: Config override (50) beats Cyrillic conservative (8) and hardware (30)")


def test_gpu_high_vram_scenario():
    """GPU with high VRAM scenario."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {'stats_file': str(Path(tmp) / 'batch_stats.json')}
        tracker = BatchStatsTracker(config, hardware_baseline=60)

        # Latin uses hardware baseline
        assert tracker._get_language_baseline('de') == 60
        # Cyrillic capped
        assert tracker._get_language_baseline('ru') == 8

        print("[PASS] Test 8 passed: High VRAM scenario (Latin=60, Cyrillic=8)")


def test_gpu_low_vram_scenario():
    """GPU with low VRAM scenario."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {'stats_file': str(Path(tmp) / 'batch_stats.json')}
        tracker = BatchStatsTracker(config, hardware_baseline=4)

        # Latin uses hardware baseline
        assert tracker._get_language_baseline('de') == 4
        # Cyrillic uses hardware baseline (lower than conservative)
        assert tracker._get_language_baseline('ru') == 4

        print("[PASS] Test 9 passed: Low VRAM scenario (Latin=4, Cyrillic=4)")


def test_arabic_conservative_cap():
    """Arabic languages follow conservative cap logic."""
    with tempfile.TemporaryDirectory() as tmp:
        config = {'stats_file': str(Path(tmp) / 'batch_stats.json')}
        tracker = BatchStatsTracker(config, hardware_baseline=30)

        # Arabic capped at 10
        assert tracker._get_language_baseline('ar') == 10
        assert tracker._get_language_baseline('fa') == 10

        print("[PASS] Test 10 passed: Arabic languages capped at 10 (min(10, 30))")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("WS3-HARDWARE-BASELINE Unit Tests")
    print("=" * 60)
    print()

    tests = [
        test_priority_1_config_override,
        test_priority_2_cyrillic_conservative_cap,
        test_priority_3_hardware_baseline_for_latin,
        test_priority_4_hardcoded_fallback,
        test_backward_compatibility,
        test_cyrillic_uses_lower_hardware,
        test_config_override_beats_all,
        test_gpu_high_vram_scenario,
        test_gpu_low_vram_scenario,
        test_arabic_conservative_cap,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] Test failed: {test.__name__}")
            print(f"  Error: {e}")
            failed += 1
        except Exception as e:
            print(f"[FAIL] Test error: {test.__name__}")
            print(f"  Error: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
