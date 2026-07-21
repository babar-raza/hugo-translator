"""
Batch Statistics Tracker for Adaptive Batch Translation.

This module provides persistent tracking and adaptation of batch sizes
based on per-language translation performance. It implements a reactive
adaptive system that learns from failures and adjusts batch sizes across
translation sessions.

Key Features:
- Per-language rolling statistics (last 50 batches)
- Adaptive batch size calculation with EMA smoothing
- Reactive splitting on immediate failures
- JSON persistence for cross-session learning
- Language-aware baselines (Cyrillic vs Latin)
"""

import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BatchStatsTracker:
    """
    Track and adapt batch translation statistics across sessions.

    The tracker maintains per-language statistics including:
    - Current adaptive batch size
    - Rolling window of batch results
    - Exponential moving average of fallback rate
    - Adaptation history

    Adaptation Strategy:
    - REDUCE: Decrease batch size by 20% when EMA fallback rate exceeds threshold
    - INCREASE: Increase batch size by 10% after 5 consecutive successes
    - REACTIVE: Immediately split failing batches in half (8→4→2→1)

    Storage:
    - JSON file in .translation_progress/batch_stats.json
    - Automatic cleanup of stale entries (>30 days)
    """

    # Language groups with known translation challenges
    CYRILLIC_LANGUAGES = {'bg', 'ru', 'mk', 'uk', 'sr', 'be'}  # Cyrillic script
    ARABIC_SCRIPT_LANGUAGES = {'ar', 'fa', 'ur', 'ps'}  # Arabic script

    def __init__(self, config: dict[str, Any], hardware_baseline: int | None = None):
        """
        Initialize batch statistics tracker.

        Args:
            config: Configuration dictionary with keys:
                - stats_file: Path to statistics JSON file
                - fallback_rate_threshold: Trigger adaptation if exceeded (default 0.05)
                - reduction_factor: Batch size reduction multiplier (default 0.80)
                - increase_factor: Batch size increase multiplier (default 1.10)
                - min_batches_before_increase: Consecutive successes required (default 5)
                - language_overrides: Per-language configuration overrides
                - stats_retention_days: Auto-cleanup age threshold (default 30)
            hardware_baseline: Optional hardware-calculated initial batch size from GPU optimizer.
                Used as baseline for new languages when no config override exists.
                Priority: config override > script conservative > hardware_baseline > hardcoded (20)
        """
        self.config = config
        self.hardware_baseline = hardware_baseline
        self.stats_file = Path(config.get('stats_file', '.translation_progress/batch_stats.json'))
        self.languages: dict[str, dict[str, Any]] = {}
        # Languages this process instance has actually modified since its last
        # save. Multiple concurrent processes (one per heal/shard job) share
        # this single JSON file, each with its own in-memory `languages` dict
        # loaded once at startup. Without tracking dirty keys, save() would
        # blindly overwrite the whole file with this process's snapshot --
        # including STALE copies of languages other concurrent processes have
        # since updated -- silently reverting their batch-size growth. Only
        # the languages this process itself touched are safe to overwrite;
        # everything else must come from a fresh on-disk read at save time.
        self._dirty_languages: set[str] = set()

        # Adaptation parameters
        self.fallback_rate_threshold = config.get('fallback_rate_threshold', 0.05)
        self.reduction_factor = config.get('reduction_factor', 0.80)
        self.increase_factor = config.get('increase_factor', 1.10)
        self.min_batches_before_increase = config.get('min_batches_before_increase', 5)
        self.stats_retention_days = config.get('stats_retention_days', 30)
        # TC-AST-02: Purity backpressure — reduce batch size by 1 after this many
        # consecutive purity failures for the same language (default: 3).
        self.purity_failure_backpressure_threshold = int(
            config.get('purity_failure_backpressure_threshold', 3)
        )

        # Ensure stats directory exists
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(
            f"BatchStatsTracker initialized: threshold={self.fallback_rate_threshold}, "
            f"reduction={self.reduction_factor}, increase={self.increase_factor}"
        )

    def load(self) -> None:
        """
        Load statistics from JSON file.

        Creates new file if it doesn't exist. Performs automatic cleanup
        of stale entries based on stats_retention_days.
        """
        if not self.stats_file.exists():
            logger.info(f"No existing batch stats found at {self.stats_file}, starting fresh")
            self._initialize_empty_stats()
            return

        try:
            with open(self.stats_file, encoding='utf-8') as f:
                data = json.load(f)

            self.languages = data.get('languages', {})
            version = data.get('version', '1.0')

            # Cleanup stale entries
            self._cleanup_stale_entries()

            logger.info(
                f"Loaded batch statistics (v{version}): "
                f"{len(self.languages)} languages tracked"
            )
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load batch stats from {self.stats_file}: {e}")
            logger.warning("Starting with empty statistics")
            self._initialize_empty_stats()

    def save(self) -> None:
        """
        Save statistics to JSON file.

        Writes atomically to prevent corruption. Includes metadata
        like version and last update timestamp.

        Multiple processes (one per concurrent heal/shard job) share this
        file, each with its own in-memory `languages` snapshot loaded once
        at startup. To avoid one process's stale copy of a language it
        never touched silently reverting another process's concurrent
        growth for that same language, this does a merge rather than a
        blind overwrite: languages this instance has actually modified
        (self._dirty_languages) come from memory; everything else is
        re-read fresh from disk immediately before writing. Fixed
        2026-07-16 alongside the baseline/max_size ceiling bug -- both
        were needed together to get real batch-size growth in production
        (confirmed live: languages processed by 2+ concurrent jobs, e.g.
        'fi' via unified_shard_5 + review_latin_m2m, never grew past
        baseline despite thousands of consecutive successes).
        """
        on_disk_languages: dict[str, dict[str, Any]] = {}
        if self.stats_file.exists():
            try:
                with open(self.stats_file, encoding='utf-8') as f:
                    on_disk_languages = json.load(f).get('languages', {})
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(
                    f"save(): could not re-read {self.stats_file} for merge ({e}); "
                    f"falling back to this process's own snapshot for all languages"
                )
                on_disk_languages = {}

        merged = dict(on_disk_languages)
        for lang in self._dirty_languages:
            if lang in self.languages:
                merged[lang] = self.languages[lang]

        data = {
            'version': '1.0',
            'last_updated': datetime.now().isoformat(),
            'languages': merged
        }

        try:
            # Write to temp file first, then rename (atomic)
            temp_file = self.stats_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            temp_file.replace(self.stats_file)

            # Keep this process's in-memory view consistent with what's now
            # on disk (picks up other processes' concurrent progress for
            # languages this instance doesn't own).
            self.languages = merged

            logger.debug(
                f"Saved batch statistics: {len(merged)} languages "
                f"({len(self._dirty_languages)} owned by this process)"
            )
        except OSError as e:
            logger.error(f"Failed to save batch stats to {self.stats_file}: {e}")

    def get_batch_size(self, target_lang: str) -> int:
        """
        Get adaptive batch size for target language.

        Args:
            target_lang: ISO 639-1 language code (e.g., 'bg', 'de', 'fr')

        Returns:
            Adaptive batch size based on historical performance,
            or baseline for new languages
        """
        # Get language stats or create new entry
        lang_stats = self.languages.get(target_lang)

        if not lang_stats:
            # New language: use baseline from config
            baseline = self._get_language_baseline(target_lang)
            logger.debug(
                f"New language {target_lang}: using baseline batch_size={baseline}"
            )
            return baseline

        # Return current adaptive size
        current_size = lang_stats.get('current_batch_size', 20)
        baseline = lang_stats.get('baseline_batch_size', 20)
        fallback_rate = lang_stats['rolling_stats'].get('fallback_rate', 0.0)

        logger.debug(
            f"Adaptive batch size for {target_lang}: {current_size} "
            f"(baseline={baseline}, fallback_rate={fallback_rate:.2%})"
        )

        return current_size

    def record_batch_result(
        self,
        language: str,
        batch_size: int,
        success: bool,
        fallback_reason: str | None = None
    ) -> None:
        """
        Record batch translation result.

        Updates rolling statistics including:
        - Total/successful/fallback batch counts
        - Fallback rate and EMA
        - Consecutive success counter
        - Language-specific failure reasons

        Args:
            language: Target language code
            batch_size: Size of the batch processed
            success: True if batch succeeded without fallback
            fallback_reason: Reason for fallback ('language_purity', 'mapping', etc.)
        """
        # Initialize language entry if needed
        if language not in self.languages:
            self.languages[language] = self._create_language_entry(language)

        self._dirty_languages.add(language)

        # Update rolling statistics
        stats = self.languages[language]['rolling_stats']
        stats['total_batches'] += 1

        if success:
            stats['successful_batches'] += 1
            self.languages[language]['consecutive_successes'] += 1
            self.languages[language]['consecutive_purity_failures'] = 0  # reset on any success
        else:
            stats['fallback_batches'] += 1
            self.languages[language]['consecutive_successes'] = 0

            # Track failure reasons
            if fallback_reason == 'language_purity':
                stats['language_purity_failures'] += 1
                # TC-AST-02: Purity backpressure — decrement batch size after threshold consecutive failures.
                purity_fail_count = self.languages[language].get('consecutive_purity_failures', 0) + 1
                self.languages[language]['consecutive_purity_failures'] = purity_fail_count
                if purity_fail_count >= self.purity_failure_backpressure_threshold:
                    current_size = self.languages[language].get('current_batch_size', 20)
                    new_size = max(1, current_size - 1)
                    if new_size < current_size:
                        self.languages[language]['current_batch_size'] = new_size
                        logger.info(
                            "Purity backpressure: %s batch_size %d→%d after %d consecutive purity failures",
                            language, current_size, new_size, purity_fail_count,
                        )
            elif fallback_reason == 'mapping':
                stats['mapping_failures'] = stats.get('mapping_failures', 0) + 1
            elif fallback_reason == 'exception':
                stats['exception_failures'] = stats.get('exception_failures', 0) + 1

        # Calculate fallback rate
        total = stats['total_batches']
        fallback = stats['fallback_batches']
        stats['fallback_rate'] = fallback / total if total > 0 else 0.0

        # Update EMA (exponential moving average) for smooth adaptation
        alpha = 0.2  # Smoothing factor (0.2 = 20% weight to new data)
        current_fail = 0 if success else 1
        prev_ema = stats.get('ema_fallback_rate', 0.0)
        stats['ema_fallback_rate'] = alpha * current_fail + (1 - alpha) * prev_ema

        # Update timestamp
        self.languages[language]['last_batch_timestamp'] = datetime.now().isoformat()

        logger.debug(
            f"Recorded batch result: {language} size={batch_size} success={success} "
            f"reason={fallback_reason} (fallback_rate={stats['fallback_rate']:.2%}, "
            f"ema={stats['ema_fallback_rate']:.2%})"
        )

    def react_to_failure(self, target_lang: str, current_batch_size: int) -> int:
        """
        Immediate reaction to batch failure (reactive splitting).

        This is called DURING translation when a batch fails, providing
        an immediate reduced batch size for retry. This is separate from
        long-term adaptation (update_language_stats).

        Strategy: Split batch in half (more aggressive than long-term reduction)

        Args:
            target_lang: Target language code
            current_batch_size: Current failing batch size

        Returns:
            Reduced batch size for immediate retry (minimum 1)
        """
        # Reduce by 50% (more aggressive than long-term 20% reduction)
        new_size = max(1, current_batch_size // 2)

        # WS4: Enhanced reactive split logging (Requirement 15)
        logger.info(
            f"REACTIVE BATCH SPLIT: {target_lang} {current_batch_size}→{new_size} | "
            f"Trigger: batch_failure | "
            f"Action: Immediate batch size halving for recovery"
        )

        return new_size

    def update_language_stats(self, target_lang: str) -> None:
        """
        Update batch size based on performance (long-term adaptation).

        Called AFTER processing all batches for a language to adapt
        the baseline batch size for future translations.

        Adaptation Rules:
        - REDUCE: If EMA fallback rate > threshold, reduce by reduction_factor
        - INCREASE: If 5+ consecutive successes and below max_size (config ceiling),
          increase by increase_factor. NOTE: previously capped at `baseline` (the
          cold-start value) instead of `max_size` -- that bug pinned every language
          at its cold-start batch size forever, since baseline is never revised
          upward. Fixed 2026-07-16.

        Args:
            target_lang: Target language code
        """
        if target_lang not in self.languages:
            return

        self._dirty_languages.add(target_lang)

        lang_data = self.languages[target_lang]
        stats = lang_data['rolling_stats']
        current_size = lang_data['current_batch_size']

        # Get min/max from config
        overrides = self.config.get('language_overrides', {}).get(target_lang, {})
        min_size = overrides.get('min_batch_size', 4)
        max_size = overrides.get('max_batch_size', 50)
        baseline = lang_data['baseline_batch_size']

        # Check if we have enough data to adapt
        if stats['total_batches'] < 3:
            logger.debug(
                f"Insufficient data for adaptation: {target_lang} "
                f"(only {stats['total_batches']} batches)"
            )
            return

        # REDUCTION: High fallback rate
        ema_rate = stats.get('ema_fallback_rate', 0.0)
        threshold = overrides.get('fallback_rate_threshold', self.fallback_rate_threshold)

        if ema_rate > threshold:
            new_size = max(min_size, int(current_size * self.reduction_factor))
            if new_size != current_size:
                # Prepare detailed reason
                reason_detail = f"ema_fallback_rate {ema_rate:.1%} > threshold {threshold:.1%}"
                if new_size == min_size:
                    reason_detail += ", capped at min_size"

                self._log_adaptation(
                    target_lang, 'REDUCE', current_size, new_size,
                    reason_detail
                )
                lang_data['current_batch_size'] = new_size
                return  # Don't check for increase in same update

        # INCREASE: Sustained success (only if below max_size)
        # FIX Concern #10: Use math.ceil + minimum +1 to ensure batch size actually increases
        # Previous bug: int(4 * 1.10) = int(4.4) = 4 (no increase!)
        # Fixed: max(current+1, ceil(current*factor)) ensures at least +1
        consecutive = lang_data.get('consecutive_successes', 0)
        if consecutive >= self.min_batches_before_increase and current_size < max_size:
            # Use ceil to round up AND ensure at least +1 increase
            proportional_increase = math.ceil(current_size * self.increase_factor)
            new_size = min(max_size, max(current_size + 1, proportional_increase))
            if new_size != current_size:
                # Prepare detailed reason
                reason_detail = f"consecutive_successes {consecutive} >= {self.min_batches_before_increase}"
                if new_size == max_size:
                    reason_detail += ", capped at max_size"

                self._log_adaptation(
                    target_lang, 'INCREASE', current_size, new_size,
                    reason_detail
                )
                lang_data['current_batch_size'] = new_size
                lang_data['consecutive_successes'] = 0  # Reset counter

    def _get_language_baseline(self, lang_code: str) -> int:
        """
        Get baseline batch size from config with language-specific overrides.

        Priority hierarchy (highest to lowest):
        1. Config override - explicit user configuration takes precedence
        2. Script conservative - safety cap for complex scripts (Cyrillic, Arabic)
        3. Hardware baseline - GPU optimizer calculated batch size
        4. Hardcoded fallback - default value when no other information available

        Args:
            lang_code: ISO 639-1 language code

        Returns:
            Baseline batch size for this language
        """
        overrides = self.config.get('language_overrides', {})

        # Priority 1: Check for explicit config override (highest priority)
        if lang_code in overrides:
            return overrides[lang_code].get('initial_batch_size', 20)

        # Priority 2: Script-based conservative baselines (safety for complex scripts)
        # For Cyrillic: use min of conservative value and hardware baseline (if available)
        if lang_code in self.CYRILLIC_LANGUAGES:
            conservative_cyrillic = 8
            if self.hardware_baseline is not None:
                # Cap at conservative value for safety (Cyrillic has higher token counts)
                return min(conservative_cyrillic, self.hardware_baseline)
            return conservative_cyrillic

        # Arabic script languages (similar conservative approach)
        if lang_code in self.ARABIC_SCRIPT_LANGUAGES:
            conservative_arabic = 10
            if self.hardware_baseline is not None:
                return min(conservative_arabic, self.hardware_baseline)
            return conservative_arabic

        # Priority 3: Hardware baseline from GPU optimizer (if available)
        if self.hardware_baseline is not None:
            return self.hardware_baseline

        # Priority 4: Hardcoded fallback for Latin-based and other languages
        return 20

    def _create_language_entry(self, language: str) -> dict[str, Any]:
        """
        Create new language entry with baseline values.

        Args:
            language: Language code

        Returns:
            Initialized language statistics dictionary
        """
        baseline = self._get_language_baseline(language)

        return {
            'current_batch_size': baseline,
            'baseline_batch_size': baseline,
            'rolling_stats': {
                'total_batches': 0,
                'successful_batches': 0,
                'fallback_batches': 0,
                'language_purity_failures': 0,
                'mapping_failures': 0,
                'exception_failures': 0,
                'fallback_rate': 0.0,
                'ema_fallback_rate': 0.0
            },
            'adaptation_history': [],
            'consecutive_successes': 0,
            'consecutive_purity_failures': 0,
            'last_batch_timestamp': None
        }

    def _log_adaptation(
        self,
        language: str,
        action: str,
        from_size: int,
        to_size: int,
        reason: str
    ) -> None:
        """
        Log adaptation to history and logger.

        Args:
            language: Language code
            action: 'reduce' or 'increase'
            from_size: Previous batch size
            to_size: New batch size
            reason: Reason for adaptation
        """
        adaptation = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'from': from_size,
            'to': to_size,
            'reason': reason
        }

        self.languages[language]['adaptation_history'].append(adaptation)

        # Keep only last 20 adaptations to prevent unbounded growth
        history = self.languages[language]['adaptation_history']
        if len(history) > 20:
            self.languages[language]['adaptation_history'] = history[-20:]

        # WS4: Enhanced batch adaptation logging with detailed stats (Requirement 14)
        stats = self.languages[language]['rolling_stats']
        total_batches = stats.get('total_batches', 0)
        successful_batches = stats.get('successful_batches', 0)
        fallback_rate = stats.get('fallback_rate', 0.0)
        purity_failures = stats.get('language_purity_failures', 0)
        mapping_failures = stats.get('mapping_failures', 0)
        exception_failures = stats.get('exception_failures', 0)

        logger.info(
            f"BATCH ADAPTATION: {language} {from_size}→{to_size} | "
            f"Reason: {reason} | "
            f"Stats: {successful_batches}/{total_batches} successful "
            f"({fallback_rate:.1%} fallback rate) | "
            f"Failures: purity={purity_failures} mapping={mapping_failures} exception={exception_failures}"
        )

    def _initialize_empty_stats(self) -> None:
        """Initialize empty statistics dictionary."""
        self.languages = {}

    def _cleanup_stale_entries(self) -> None:
        """
        Remove language entries that haven't been used recently.

        Prevents unbounded growth of statistics file by removing
        entries older than stats_retention_days.
        """
        if self.stats_retention_days <= 0:
            return  # Cleanup disabled

        cutoff = datetime.now() - timedelta(days=self.stats_retention_days)
        stale_languages = []

        for lang, data in self.languages.items():
            last_update = data.get('last_batch_timestamp')
            if not last_update:
                continue

            try:
                last_update_dt = datetime.fromisoformat(last_update)
                if last_update_dt < cutoff:
                    stale_languages.append(lang)
            except ValueError:
                # Invalid timestamp format, skip
                continue

        if stale_languages:
            for lang in stale_languages:
                del self.languages[lang]

            logger.info(
                f"Cleaned up {len(stale_languages)} stale language entries: "
                f"{', '.join(stale_languages)}"
            )
