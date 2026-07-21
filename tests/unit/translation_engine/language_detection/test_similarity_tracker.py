"""
TC-QG-006B (HT-QUALITY-GATES-001): SimilarityTracker.adapt() no longer
auto-commits high-failure-rate language pairs into `learned_pairs`.

Root cause this heals: a high FastText disagreement rate between two
languages is not, by itself, proof the languages are linguistically similar —
it is equally consistent with translations repeatedly coming out untranslated
or garbled for that target language. The pre-fix `adapt()` silently promoted
such pairs into `learned_pairs`, which permanently disables the
language-purity gate (write_gate.py) and TM poisoned-hit rejection
(translation_memory.py) for that pair. TC-QG-006A's audit of the live
`.translation_progress/language_similarities.json` found 8 pairs auto-learned
this way that are not plausible linguistic near-neighbors (e.g. en-hr, de-fi,
hr-uz, bg-en) — several show `detected=en` at high confidence, consistent
with untranslated English residue being whitelisted rather than flagged.

Verifies:
- A simulated 30%-over-50-samples scenario flags the pair into
  `pending_pairs`, NOT `learned_pairs` (the specific acceptance criterion).
- `are_similar()` returns False for a pending-but-unapproved pair.
- `approve_pending()` moves a pair into `learned_pairs` with an audit trail
  (approved_by, approval_note) and `are_similar()` then returns True.
- `reject_pending()` dismisses a flagged pair without promoting it.
- `adapt()` does not re-flag a pair that's already pending or already learned.
- save()/load() round-trips `pending_pairs` alongside `learned_pairs`.
"""

import json

from src.translation_engine.language_detection.similarity_tracker import SimilarityTracker


def _make_tracker(tmp_path, **overrides):
    config = {
        "stats_file": str(tmp_path / "language_similarities.json"),
        "failure_rate_threshold": 0.30,
        "min_samples": 50,
        "rolling_window_size": 50,
        "baseline_groups": {},  # isolate from DEFAULT_BASELINE_GROUPS for these tests
        "log_adaptations": True,
        **overrides,
    }
    return SimilarityTracker(config)


def _feed_high_failure_samples(tracker, lang1, lang2, n=50, failure_rate=0.8):
    """Record n detection samples for (lang1, lang2) with the given failure rate."""
    n_fail = round(n * failure_rate)
    for i in range(n):
        success = i >= n_fail
        tracker.record_detection(
            expected_lang=lang1, detected_lang=lang2, confidence=0.9, success=success
        )


def test_adapt_flags_pending_not_learned(tmp_path):
    tracker = _make_tracker(tmp_path)
    _feed_high_failure_samples(tracker, "hr", "uz", n=50, failure_rate=0.8)

    newly_flagged = tracker.adapt()

    assert len(newly_flagged) == 1
    assert "hr-uz" in tracker.pending_pairs
    assert "hr-uz" not in tracker.learned_pairs, (
        "adapt() must not auto-commit into learned_pairs — this is the exact "
        "behavior that silently whitelisted 8 non-similar pairs in production."
    )


def test_pending_pair_does_not_affect_are_similar(tmp_path):
    tracker = _make_tracker(tmp_path)
    _feed_high_failure_samples(tracker, "en", "hr", n=50, failure_rate=0.9)
    tracker.adapt()

    assert "en-hr" in tracker.pending_pairs
    assert tracker.are_similar("en", "hr") is False, (
        "A pending (unapproved) pair must not be treated as similar."
    )


def test_approve_pending_promotes_and_affects_are_similar(tmp_path):
    tracker = _make_tracker(tmp_path)
    _feed_high_failure_samples(tracker, "ca", "es", n=50, failure_rate=0.4)
    tracker.adapt()
    assert "ca-es" in tracker.pending_pairs

    approved = tracker.approve_pending("ca-es", approved_by="qa-lead", note="Genuinely close Romance pair")

    assert approved is True
    assert "ca-es" not in tracker.pending_pairs
    assert "ca-es" in tracker.learned_pairs
    assert tracker.learned_pairs["ca-es"]["approved_by"] == "qa-lead"
    assert tracker.are_similar("ca", "es") is True


def test_reject_pending_dismisses_without_promoting(tmp_path):
    tracker = _make_tracker(tmp_path)
    _feed_high_failure_samples(tracker, "bg", "en", n=50, failure_rate=1.0)
    tracker.adapt()
    assert "bg-en" in tracker.pending_pairs

    rejected = tracker.reject_pending("bg-en", reason="detected=en at high confidence — untranslated residue, not similarity")

    assert rejected is True
    assert "bg-en" not in tracker.pending_pairs
    assert "bg-en" not in tracker.learned_pairs
    assert tracker.are_similar("bg", "en") is False


def test_approve_pending_noop_when_not_pending(tmp_path):
    tracker = _make_tracker(tmp_path)
    assert tracker.approve_pending("xx-yy", approved_by="someone") is False
    assert "xx-yy" not in tracker.learned_pairs


def test_adapt_does_not_reflag_pending_or_learned_pairs(tmp_path):
    tracker = _make_tracker(tmp_path)
    _feed_high_failure_samples(tracker, "cs", "hr", n=50, failure_rate=0.9)
    first_pass = tracker.adapt()
    assert len(first_pass) == 1

    # Feed more samples for the same pair, still over threshold.
    _feed_high_failure_samples(tracker, "cs", "hr", n=10, failure_rate=1.0)
    second_pass = tracker.adapt()

    assert second_pass == [], "adapt() must not re-flag a pair already in pending_pairs"


def test_save_load_roundtrips_pending_pairs(tmp_path):
    tracker = _make_tracker(tmp_path)
    _feed_high_failure_samples(tracker, "fi", "de", n=50, failure_rate=0.95)
    tracker.adapt()
    assert "de-fi" in tracker.pending_pairs
    tracker.save()

    on_disk = json.loads((tmp_path / "language_similarities.json").read_text(encoding="utf-8"))
    assert "de-fi" in on_disk["pending_pairs"]
    assert "de-fi" not in on_disk.get("learned_pairs", {})

    reloaded = _make_tracker(tmp_path)
    reloaded.load()
    assert "de-fi" in reloaded.pending_pairs
    assert reloaded.are_similar("de", "fi") is False


def test_below_threshold_failure_rate_is_never_flagged(tmp_path):
    tracker = _make_tracker(tmp_path)
    _feed_high_failure_samples(tracker, "fr", "it", n=50, failure_rate=0.1)

    newly_flagged = tracker.adapt()

    assert newly_flagged == []
    assert tracker.pending_pairs == {}


def test_revoke_learned_removes_from_learned_pairs_and_disables_similarity(tmp_path):
    """TC-QG-006A/production-grade review: pairs already in learned_pairs
    before TC-QG-006B's human-approval gate existed can be revoked."""
    tracker = _make_tracker(tmp_path)
    tracker.learned_pairs["bg-en"] = {
        "failure_rate": 1.0, "samples": 50, "added": "2026-02-28T18:10:49",
        "reason": "failure_rate 100.0% > threshold 30.0%",
    }
    assert tracker.are_similar("bg", "en") is True

    revoked = tracker.revoke_learned(
        "bg-en", revoked_by="independent-review", reason="detected=en at 0.82 confidence in 50/50 samples"
    )

    assert revoked is True
    assert "bg-en" not in tracker.learned_pairs
    assert "bg-en" in tracker.revoked_pairs
    assert tracker.revoked_pairs["bg-en"]["revoked_by"] == "independent-review"
    assert tracker.are_similar("bg", "en") is False


def test_revoke_learned_noop_when_not_learned(tmp_path):
    tracker = _make_tracker(tmp_path)
    assert tracker.revoke_learned("xx-yy", revoked_by="someone") is False
    assert "xx-yy" not in tracker.revoked_pairs


def test_save_load_roundtrips_revoked_pairs(tmp_path):
    tracker = _make_tracker(tmp_path)
    tracker.learned_pairs["hr-uz"] = {"failure_rate": 0.9, "samples": 50, "added": "x", "reason": "x"}
    tracker.revoke_learned("hr-uz", revoked_by="independent-review", reason="no linguistic basis")
    tracker.save()

    reloaded = _make_tracker(tmp_path)
    reloaded.load()
    assert "hr-uz" in reloaded.revoked_pairs
    assert "hr-uz" not in reloaded.learned_pairs
    assert reloaded.are_similar("hr", "uz") is False
