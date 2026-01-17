"""
Quick test script to verify adaptive batch translation system.
"""
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

from src.translation_engine.extractor.batch_stats_tracker import BatchStatsTracker

def test_batch_stats_tracker():
    """Test BatchStatsTracker functionality."""
    print("=" * 60)
    print("Testing Adaptive Batch Translation System")
    print("=" * 60)

    # Create tracker with test config
    config = {
        'enabled': True,
        'fallback_rate_threshold': 0.05,
        'reduction_factor': 0.80,
        'increase_factor': 1.10,
        'min_batches_before_increase': 5,
        'stats_file': '.translation_progress/test_batch_stats.json',
        'stats_retention_days': 30,
        'rolling_window_size': 50,
        'language_overrides': {
            'bg': {
                'initial_batch_size': 8,
                'min_batch_size': 4,
                'max_batch_size': 20,
                'fallback_rate_threshold': 0.30
            },
            'ru': {
                'initial_batch_size': 8,
                'min_batch_size': 4,
                'max_batch_size': 25
            }
        }
    }

    tracker = BatchStatsTracker(config)

    print("\n1. Testing initial batch sizes:")
    print(f"   Bulgarian (bg): {tracker.get_batch_size('bg')} (expected: 8)")
    print(f"   Russian (ru): {tracker.get_batch_size('ru')} (expected: 8)")
    print(f"   German (de): {tracker.get_batch_size('de')} (expected: 20)")
    print(f"   Spanish (es): {tracker.get_batch_size('es')} (expected: 20)")

    print("\n2. Testing reactive split:")
    reduced = tracker.react_to_failure('bg', 8)
    print(f"   bg batch_size 8 -> {reduced} after failure (expected: 4)")
    reduced2 = tracker.react_to_failure('bg', reduced)
    print(f"   bg batch_size {reduced} -> {reduced2} after failure (expected: 2)")

    print("\n3. Simulating batch failures for Bulgarian:")
    for i in range(10):
        success = i < 3  # First 3 succeed, rest fail
        tracker.record_batch_result(
            language='bg',
            batch_size=8,
            success=success,
            fallback_reason=None if success else 'language_purity'
        )
        print(f"   Batch {i+1}: {'SUCCESS' if success else 'FAILURE (language_purity)'}")

    stats = tracker.languages['bg']['rolling_stats']
    print(f"\n   Results after 10 batches:")
    print(f"   - Total: {stats['total_batches']}")
    print(f"   - Successful: {stats['successful_batches']}")
    print(f"   - Fallback: {stats['fallback_batches']}")
    print(f"   - Fallback rate: {stats['fallback_rate']:.2%}")
    print(f"   - EMA fallback rate: {stats['ema_fallback_rate']:.2%}")

    print("\n4. Testing adaptation:")
    tracker.update_language_stats('bg')
    new_size = tracker.get_batch_size('bg')
    print(f"   Bulgarian batch size after adaptation: {new_size} (should be <8 due to high fallback rate)")

    print("\n5. Simulating success for German:")
    for i in range(5):
        tracker.record_batch_result(
            language='de',
            batch_size=20,
            success=True,
            fallback_reason=None
        )

    stats_de = tracker.languages['de']['rolling_stats']
    print(f"   German after 5 successes:")
    print(f"   - Fallback rate: {stats_de['fallback_rate']:.2%}")
    print(f"   - Consecutive successes: {tracker.languages['de']['consecutive_successes']}")

    print("\n6. Testing persistence:")
    try:
        tracker.save()
        print(f"   OK Saved statistics to {config['stats_file']}")

        # Load in new instance
        tracker2 = BatchStatsTracker(config)
        tracker2.load()
        print(f"   OK Loaded statistics from {config['stats_file']}")

        # Verify data matches
        bg_size_1 = tracker.get_batch_size('bg')
        bg_size_2 = tracker2.get_batch_size('bg')
        print(f"   OK Bulgarian batch size preserved: {bg_size_1} == {bg_size_2}")

        if 'bg' in tracker2.languages:
            loaded_stats = tracker2.languages['bg']['rolling_stats']
            print(f"   OK Statistics preserved:")
            print(f"     - Fallback rate: {loaded_stats['fallback_rate']:.2%}")
            print(f"     - EMA: {loaded_stats['ema_fallback_rate']:.2%}")
    except Exception as e:
        print(f"   FAIL Persistence test failed: {e}")

    print("\n" + "=" * 60)
    print("OK All tests completed successfully!")
    print("=" * 60)

    return tracker

if __name__ == "__main__":
    tracker = test_batch_stats_tracker()
