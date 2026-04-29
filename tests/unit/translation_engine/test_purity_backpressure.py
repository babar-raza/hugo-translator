"""
TC-AST-02 Issue C: Purity backpressure in BatchStatsTracker.

Verifies that after `purity_failure_backpressure_threshold` consecutive
language-purity failures for the same language, current_batch_size is reduced
by 1. The counter resets on any success.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.translation_engine.extractor.batch_stats_tracker import BatchStatsTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(threshold: int = 3, stats_file: str | None = None, tmp_path=None) -> BatchStatsTracker:
    sf = str(tmp_path / "bs.json") if tmp_path else "/tmp/test_bs_purity.json"
    return BatchStatsTracker(
        config={
            'stats_file': sf,
            'purity_failure_backpressure_threshold': threshold,
        }
    )


def _init_lang(tracker: BatchStatsTracker, lang: str, batch_size: int = 20) -> None:
    """Initialize a language entry via record_batch_result (creates entry in self.languages)."""
    tracker.record_batch_result(lang, batch_size, success=True)


def _record_purity_failure(tracker: BatchStatsTracker, lang: str, batch_size: int = 20) -> None:
    tracker.record_batch_result(lang, batch_size, success=False, fallback_reason='language_purity')


def _record_success(tracker: BatchStatsTracker, lang: str, batch_size: int = 20) -> None:
    tracker.record_batch_result(lang, batch_size, success=True)


# ---------------------------------------------------------------------------
# Config key test
# ---------------------------------------------------------------------------

def test_config_key_present():
    """purity_failure_backpressure_threshold must exist in global.yaml."""
    import yaml
    cfg_path = Path("config/global.yaml")
    if not cfg_path.exists():
        pytest.skip("config/global.yaml not present in working directory")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    te = cfg.get('translation_engine', {})
    assert 'purity_failure_backpressure_threshold' in te, (
        "purity_failure_backpressure_threshold missing from translation_engine config"
    )
    threshold = int(te['purity_failure_backpressure_threshold'])
    assert threshold >= 1, "purity_failure_backpressure_threshold must be >= 1"


# ---------------------------------------------------------------------------
# Backpressure behaviour tests
# ---------------------------------------------------------------------------

def test_three_consecutive_purity_failures_reduce_batch_size(tmp_path):
    """After 3 consecutive purity failures, current_batch_size decrements by 1."""
    tracker = _make_tracker(threshold=3, tmp_path=tmp_path)
    lang = "hi"

    # Initialise language entry and capture initial batch size
    _init_lang(tracker, lang)
    initial_size = tracker.languages[lang]['current_batch_size']

    _record_purity_failure(tracker, lang)
    _record_purity_failure(tracker, lang)
    # Before threshold: size unchanged
    assert tracker.languages[lang]['current_batch_size'] == initial_size

    _record_purity_failure(tracker, lang)  # 3rd consecutive — threshold hit
    assert tracker.languages[lang]['current_batch_size'] == initial_size - 1, (
        "After 3 consecutive purity failures, batch size must decrement by 1"
    )


def test_success_resets_purity_failure_counter(tmp_path):
    """A single success resets consecutive_purity_failures to 0."""
    tracker = _make_tracker(threshold=3, tmp_path=tmp_path)
    lang = "hi"
    _init_lang(tracker, lang)

    _record_purity_failure(tracker, lang)
    _record_purity_failure(tracker, lang)
    _record_success(tracker, lang)  # reset
    assert tracker.languages[lang]['consecutive_purity_failures'] == 0

    # Now 2 more failures should NOT trigger backpressure (counter reset)
    initial_size = tracker.languages[lang]['current_batch_size']
    _record_purity_failure(tracker, lang)
    _record_purity_failure(tracker, lang)
    assert tracker.languages[lang]['current_batch_size'] == initial_size, (
        "After counter reset by success, 2 failures should not trigger backpressure"
    )


def test_batch_size_minimum_is_one(tmp_path):
    """batch_size must not go below 1 regardless of how many purity failures occur."""
    tracker = _make_tracker(threshold=1, tmp_path=tmp_path)  # every failure triggers
    lang = "hi"
    _init_lang(tracker, lang)
    # Force batch_size to 1 to test the floor guard
    tracker.languages[lang]['current_batch_size'] = 1

    _record_purity_failure(tracker, lang)
    assert tracker.languages[lang]['current_batch_size'] == 1, (
        "batch_size must not go below 1"
    )


def test_non_purity_failure_does_not_increment_purity_counter(tmp_path):
    """Mapping failures or exception failures must NOT increment consecutive_purity_failures."""
    tracker = _make_tracker(threshold=3, tmp_path=tmp_path)
    lang = "hi"
    _init_lang(tracker, lang)

    tracker.record_batch_result(lang, 20, success=False, fallback_reason='mapping')
    tracker.record_batch_result(lang, 20, success=False, fallback_reason='exception')
    assert tracker.languages[lang].get('consecutive_purity_failures', 0) == 0, (
        "Non-purity failures must not increment consecutive_purity_failures counter"
    )


def test_backpressure_threshold_configurable(tmp_path):
    """threshold=5 means 4 consecutive failures do NOT trigger backpressure."""
    tracker = _make_tracker(threshold=5, tmp_path=tmp_path)
    lang = "hi"
    _init_lang(tracker, lang)
    initial_size = tracker.languages[lang]['current_batch_size']

    for _ in range(4):
        _record_purity_failure(tracker, lang)

    assert tracker.languages[lang]['current_batch_size'] == initial_size, (
        "With threshold=5, only 4 failures must not trigger backpressure"
    )

    _record_purity_failure(tracker, lang)  # 5th — now it fires
    assert tracker.languages[lang]['current_batch_size'] == initial_size - 1


def test_backpressure_applies_per_language(tmp_path):
    """Purity failures for lang A must not affect lang B's batch_size."""
    tracker = _make_tracker(threshold=3, tmp_path=tmp_path)
    for lang in ["hi", "ar"]:
        _init_lang(tracker, lang)
    size_ar = tracker.languages["ar"]['current_batch_size']

    # 3 consecutive failures for Hindi
    for _ in range(3):
        _record_purity_failure(tracker, "hi")

    # Arabic must be unaffected
    assert tracker.languages["ar"]['current_batch_size'] == size_ar, (
        "Purity backpressure for 'hi' must not reduce 'ar' batch_size"
    )
