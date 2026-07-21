"""
Adaptive Similarity Tracker for Language Detection.

Tracks language detection results and automatically learns which language pairs
cause false positives. When failure rate exceeds threshold over minimum samples,
the pair is added to similarity groups to prevent future rejections.

Example: If Catalan is frequently misdetected as Spanish (>30% over 50 samples),
the system learns that ca-es are similar and accepts both as valid.
"""

import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SimilarityTracker:
    """
    Track and adapt language similarity relationships based on detection failures.

    Features:
    - Conservative baseline similarity groups (Romance, Cyrillic, Arabic, etc.)
    - Rolling window statistics (configurable, default 50 samples)
    - High-failure-rate pairs are FLAGGED FOR HUMAN REVIEW (default 30% over 50
      samples) via `adapt()` — they land in `pending_pairs`, not `learned_pairs`,
      and do NOT affect `are_similar()` until explicitly approved via
      `approve_pending()`. (TC-QG-006B, HT-QUALITY-GATES-001: a high FastText
      disagreement rate between two languages is evidence of a translation- or
      detection-quality problem at least as often as it is evidence the
      languages are genuinely similar — see `.translation_progress/
      language_similarities.json`'s pre-existing `learned_pairs`, several of
      which are not linguistically related [e.g. hr-uz, en-hr] and read as
      untranslated-English-residue or garbled output being silently
      whitelisted rather than flagged. Auto-committing was removed; review is
      now a required, explicit, logged step.)
    - JSON persistence for cross-session learning
    - Adaptation history logging
    """

    # Conservative baseline similarity groups
    DEFAULT_BASELINE_GROUPS = {
        "romance": ["ca", "es", "pt", "fr", "it", "ro", "gl"],
        "cyrillic": ["bg", "ru", "mk", "uk", "sr", "be"],
        "arabic": ["ar", "fa", "ur", "ps"],
        "devanagari": ["hi", "mr", "ne", "sa"],
        "nordic": ["da", "no", "sv", "is"],
        "chinese": ["zh-CN", "zh-TW", "zh-HK", "zh"],
    }

    def __init__(self, config: dict[str, Any]):
        """
        Initialize similarity tracker.

        Args:
            config: Configuration dictionary with keys:
                - stats_file: Path to JSON persistence file
                - failure_rate_threshold: Trigger adaptation if exceeded (default 0.30)
                - min_samples: Minimum samples before adapting (default 50)
                - rolling_window_size: Size of rolling statistics window (default 50)
                - baseline_groups: Override default baseline groups
                - log_adaptations: Enable adaptation logging (default True)
        """
        self.config = config
        self.stats_file = Path(config.get("stats_file", ".translation_progress/language_similarities.json"))
        self.failure_rate_threshold = config.get("failure_rate_threshold", 0.30)
        self.min_samples = config.get("min_samples", 50)
        self.rolling_window_size = config.get("rolling_window_size", 50)
        self.log_adaptations = config.get("log_adaptations", True)

        # Load baseline groups (with fallback to defaults)
        self.baseline_groups = config.get("baseline_groups", self.DEFAULT_BASELINE_GROUPS)

        # Runtime state
        self.learned_pairs: dict[str, dict[str, Any]] = {}  # Approved pairs — affect are_similar()
        self.pending_pairs: dict[str, dict[str, Any]] = {}  # Flagged by adapt(), awaiting human approval
        self.revoked_pairs: dict[str, dict[str, Any]] = {}  # Previously-learned pairs a reviewer revoked
        self.rolling_stats: dict[str, deque] = {}  # Rolling window per pair

        # Ensure stats directory exists
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(
            f"SimilarityTracker initialized: threshold={self.failure_rate_threshold:.2%}, "
            f"min_samples={self.min_samples}, window={self.rolling_window_size}"
        )

    def load(self) -> None:
        """Load statistics and learned pairs from JSON file."""
        if not self.stats_file.exists():
            logger.info(f"No existing similarity stats found at {self.stats_file}, starting fresh")
            return

        try:
            with open(self.stats_file, encoding="utf-8") as f:
                data = json.load(f)

            # Load learned pairs (approved — affect are_similar()) and pending pairs
            # (flagged by adapt(), awaiting human approval — do NOT affect are_similar()).
            self.learned_pairs = data.get("learned_pairs", {})
            self.pending_pairs = data.get("pending_pairs", {})
            self.revoked_pairs = data.get("revoked_pairs", {})

            # Load rolling stats (reconstruct deques)
            raw_stats = data.get("rolling_stats", {})
            for pair_key, samples in raw_stats.items():
                self.rolling_stats[pair_key] = deque(samples, maxlen=self.rolling_window_size)

            logger.info(
                f"Loaded similarity statistics: {len(self.learned_pairs)} learned pairs, "
                f"{len(self.pending_pairs)} pending review, "
                f"{len(self.rolling_stats)} tracked pairs"
            )

        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load similarity stats from {self.stats_file}: {e}")
            logger.warning("Starting with empty statistics")

    def save(self) -> None:
        """Save statistics and learned pairs to JSON file."""
        data = {
            "version": "1.1",
            "last_updated": datetime.now().isoformat(),
            "baseline_groups": self.baseline_groups,
            "learned_pairs": self.learned_pairs,
            "pending_pairs": self.pending_pairs,
            "revoked_pairs": self.revoked_pairs,
            "rolling_stats": {
                # Convert deques to lists for JSON serialization
                pair_key: list(samples)
                for pair_key, samples in self.rolling_stats.items()
            },
        }

        try:
            # Write to temp file first, then rename (atomic)
            temp_file = self.stats_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            temp_file.replace(self.stats_file)

            logger.debug(f"Saved similarity statistics: {len(self.learned_pairs)} learned pairs")

        except OSError as e:
            logger.error(f"Failed to save similarity stats to {self.stats_file}: {e}")

    def are_similar(self, lang1: str, lang2: str) -> bool:
        """
        Check if two languages are in the same similarity group.

        Uses both baseline groups and learned pairs.

        Args:
            lang1: First language code
            lang2: Second language code

        Returns:
            True if languages are similar, False otherwise
        """
        # Exact match
        if lang1 == lang2:
            return True

        # Normalize pair key (alphabetical order)
        pair_key = self._get_pair_key(lang1, lang2)

        # Check learned pairs
        if pair_key in self.learned_pairs:
            logger.debug(f"Languages similar (learned): {lang1}-{lang2}")
            return True

        # Check baseline groups
        for group_name, languages in self.baseline_groups.items():
            if lang1 in languages and lang2 in languages:
                logger.debug(f"Languages similar (baseline {group_name}): {lang1}-{lang2}")
                return True

        return False

    def record_detection(
        self,
        expected_lang: str,
        detected_lang: str,
        confidence: float,
        success: bool,
    ) -> None:
        """
        Record language detection result for adaptive learning.

        Args:
            expected_lang: Expected language code
            detected_lang: Detected language code
            confidence: Detection confidence (0.0-1.0)
            success: True if detection was accepted (either exact or similar match)
        """
        # Skip if same language
        if expected_lang == detected_lang:
            return

        # Get pair key
        pair_key = self._get_pair_key(expected_lang, detected_lang)

        # Initialize rolling stats if needed
        if pair_key not in self.rolling_stats:
            self.rolling_stats[pair_key] = deque(maxlen=self.rolling_window_size)

        # Add sample
        sample = {
            "expected": expected_lang,
            "detected": detected_lang,
            "confidence": confidence,
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }
        self.rolling_stats[pair_key].append(sample)

        logger.debug(
            f"Recorded detection: {expected_lang}→{detected_lang} success={success} "
            f"confidence={confidence:.2f} (total_samples={len(self.rolling_stats[pair_key])})"
        )

    def adapt(self) -> list[tuple[str, str, float, str]]:
        """
        Analyze statistics and FLAG high-failure-rate pairs for human review.

        Checks all tracked pairs and adds to `pending_pairs` (NOT `learned_pairs`)
        if:
        - Sample count >= min_samples
        - Failure rate > failure_rate_threshold

        IMPORTANT (TC-QG-006B): this method no longer auto-commits pairs into
        `learned_pairs`. A high FastText disagreement rate between two
        languages is not, by itself, proof the languages are similar — it can
        equally mean a translation is repeatedly coming out untranslated or
        garbled for that target language. Auto-promoting such pairs silently
        disables the purity/TM-poison safety net for exactly the failure it
        was supposed to catch. Flagged pairs require an explicit
        `approve_pending()` call (with a recorded reason/approver) before they
        affect `are_similar()`. Call `reject_pending()` to dismiss a
        false-positive flag without silently losing the audit trail.

        Returns:
            List of newly flagged pairs: [(lang1, lang2, failure_rate, reason), ...]
        """
        newly_flagged = []

        for pair_key, samples in self.rolling_stats.items():
            # Skip if already approved or already flagged
            if pair_key in self.learned_pairs or pair_key in self.pending_pairs:
                continue

            # Check if we have enough samples
            if len(samples) < self.min_samples:
                continue

            # Calculate failure rate (ratio of failed detections)
            failures = sum(1 for s in samples if not s["success"])
            failure_rate = failures / len(samples)

            # Check if failure rate exceeds threshold
            if failure_rate > self.failure_rate_threshold:
                lang1, lang2 = pair_key.split("-")
                reason = f"failure_rate {failure_rate:.1%} > threshold {self.failure_rate_threshold:.1%}"

                self.pending_pairs[pair_key] = {
                    "failure_rate": failure_rate,
                    "samples": len(samples),
                    "flagged": datetime.now().isoformat(),
                    "reason": reason,
                }

                newly_flagged.append((lang1, lang2, failure_rate, reason))

                if self.log_adaptations:
                    logger.warning(
                        f"SIMILARITY PENDING REVIEW: {lang1}-{lang2} exceeded the failure-rate "
                        f"threshold and needs human approval before being treated as similar "
                        f"(failure_rate={failure_rate:.1%}, samples={len(samples)}). "
                        f"Call approve_pending('{pair_key}', approved_by=...) to accept, or "
                        f"reject_pending('{pair_key}', reason=...) to dismiss."
                    )

        return newly_flagged

    def approve_pending(self, pair_key: str, approved_by: str, note: str = "") -> bool:
        """
        Promote a pending pair to `learned_pairs`, making it affect `are_similar()`.

        This is the explicit, auditable human-approval step required by
        TC-QG-006B. Returns False (no-op) if `pair_key` isn't currently pending.
        """
        pending = self.pending_pairs.pop(pair_key, None)
        if pending is None:
            logger.warning(f"approve_pending: {pair_key!r} is not in pending_pairs — no-op")
            return False

        self.learned_pairs[pair_key] = {
            **pending,
            "added": datetime.now().isoformat(),
            "approved_by": approved_by,
            "approval_note": note,
        }
        logger.info(f"SIMILARITY APPROVED: {pair_key} added to similar pairs by {approved_by!r}")
        return True

    def reject_pending(self, pair_key: str, reason: str = "") -> bool:
        """
        Dismiss a pending pair without promoting it, keeping an audit trail.

        Returns False (no-op) if `pair_key` isn't currently pending.
        """
        pending = self.pending_pairs.pop(pair_key, None)
        if pending is None:
            logger.warning(f"reject_pending: {pair_key!r} is not in pending_pairs — no-op")
            return False

        logger.info(f"SIMILARITY REJECTED: {pair_key} dismissed ({reason or 'no reason given'})")
        return True

    def revoke_learned(self, pair_key: str, revoked_by: str, reason: str = "") -> bool:
        """
        Remove a pair from `learned_pairs`, restoring the purity/TM-poison
        safety net for it. Companion to `approve_pending()`/`reject_pending()`
        for pairs that were already committed before TC-QG-006B's human-
        approval gate existed (TC-QG-006A found 8 such pairs in the live
        stats file, none with a defensible linguistic-similarity rationale —
        see HT-QUALITY-GATES-001 plan Part 12).

        The revocation itself, with its reason, is kept in `revoked_pairs`
        (not silently deleted) so there's a durable record of what was
        reviewed and why — mirrors this project's `.supervisor` anti-
        overclaim convention of never discarding audit trail.

        Returns False (no-op) if `pair_key` isn't currently in `learned_pairs`.
        """
        entry = self.learned_pairs.pop(pair_key, None)
        if entry is None:
            logger.warning(f"revoke_learned: {pair_key!r} is not in learned_pairs — no-op")
            return False

        self.revoked_pairs[pair_key] = {
            **entry,
            "revoked": datetime.now().isoformat(),
            "revoked_by": revoked_by,
            "revocation_reason": reason,
        }

        logger.warning(
            f"SIMILARITY REVOKED: {pair_key} removed from learned_pairs by {revoked_by!r} "
            f"({reason or 'no reason given'}) — purity/TM-poison checks now apply to this pair again."
        )
        return True

    def get_statistics(self) -> dict[str, Any]:
        """
        Get current statistics for all tracked pairs.

        Returns:
            Dictionary with statistics per pair
        """
        stats = {}

        for pair_key, samples in self.rolling_stats.items():
            if len(samples) == 0:
                continue

            failures = sum(1 for s in samples if not s["success"])
            failure_rate = failures / len(samples)

            stats[pair_key] = {
                "total_samples": len(samples),
                "failures": failures,
                "failure_rate": failure_rate,
                "is_learned": pair_key in self.learned_pairs,
                "is_pending": pair_key in self.pending_pairs,
            }

        return stats

    def _get_pair_key(self, lang1: str, lang2: str) -> str:
        """
        Get normalized pair key (alphabetical order).

        Args:
            lang1: First language code
            lang2: Second language code

        Returns:
            Pair key like "ca-es" (alphabetical)
        """
        return "-".join(sorted([lang1, lang2]))

    def __repr__(self) -> str:
        return (
            f"SimilarityTracker(baseline_groups={len(self.baseline_groups)}, "
            f"learned_pairs={len(self.learned_pairs)}, "
            f"pending_pairs={len(self.pending_pairs)}, "
            f"tracked_pairs={len(self.rolling_stats)})"
        )
