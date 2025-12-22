"""
Round-robin language scheduler for multi-language processing.

T302: federated-splashing-panda
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LanguageWorkload:
    """
    Workload tracking for a single language in round-robin processing.

    Attributes:
        language_code: Target language code (e.g., "de", "fr", "es")
        total_texts: Total number of texts to translate
        completed_texts: Number of texts completed so far
        missing_texts: Number of texts missing from TM cache
    """
    language_code: str
    total_texts: int = 0
    completed_texts: int = 0
    missing_texts: int = 0

    @property
    def remaining_texts(self) -> int:
        """Number of texts remaining to translate."""
        return self.total_texts - self.completed_texts

    @property
    def is_complete(self) -> bool:
        """Check if all texts for this language are complete."""
        return self.completed_texts >= self.total_texts

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage (0.0 to 100.0)."""
        if self.total_texts == 0:
            return 100.0
        return (self.completed_texts / self.total_texts) * 100.0


def sort_languages_by_missing_count(
    workloads: List[LanguageWorkload],
    order: str = "desc"
) -> List[LanguageWorkload]:
    """
    Sort languages by missing translation count.

    Args:
        workloads: List of language workloads to sort
        order: Sort order - "desc" (most missing first) or "asc" (least missing first)

    Returns:
        Sorted list of workloads
    """
    reverse = (order == "desc")
    return sorted(workloads, key=lambda w: w.missing_texts, reverse=reverse)


class RoundRobinScheduler:
    """
    Round-robin scheduler for multi-language processing.

    Processes N texts per language in round-robin fashion, switching between
    languages to enable incremental progress and memory management.

    Example:
        scheduler = RoundRobinScheduler(
            languages=["de", "fr", "es"],
            total_texts=100,
            texts_per_round=10,
            sort_order="desc",
            tm=translation_memory,
            site_id="example"
        )

        while True:
            batch = scheduler.get_next_batch()
            if batch is None:
                break
            language, texts = batch
            # Translate texts for language
            scheduler.mark_batch_complete(language, len(texts))
    """

    def __init__(
        self,
        languages: List[str],
        total_texts: int,
        texts_per_round: int,
        sort_order: str,
        tm: Optional[object] = None,
        site_id: Optional[str] = None,
    ):
        """
        Initialize round-robin scheduler.

        Args:
            languages: List of target language codes
            total_texts: Total number of texts to translate
            texts_per_round: Number of texts to process per language per round
            sort_order: Language sort order - "desc" or "asc"
            tm: Translation memory instance (optional, for missing count detection)
            site_id: Site ID (optional, for TM queries)
        """
        self.languages = languages
        self.total_texts = total_texts
        self.texts_per_round = texts_per_round
        self.sort_order = sort_order
        self.tm = tm
        self.site_id = site_id

        # Initialize workloads
        self.workloads: Dict[str, LanguageWorkload] = {}
        self._initialize_workloads()

        # Current round tracking
        self.current_round = 0
        self._sorted_languages: List[str] = []
        self._update_sorted_languages()

        logger.info(
            f"RoundRobinScheduler initialized: {len(self.languages)} languages, "
            f"{self.texts_per_round} texts/round, sort={self.sort_order}"
        )

    def _initialize_workloads(self) -> None:
        """
        Initialize language workloads.

        For each language, creates a LanguageWorkload with:
        - total_texts: Total number of texts to translate
        - completed_texts: 0 (none completed yet)
        - missing_texts: Number of texts missing from TM (if TM provided)
        """
        for lang in self.languages:
            workload = LanguageWorkload(
                language_code=lang,
                total_texts=self.total_texts,
                completed_texts=0,
                missing_texts=self._get_missing_count(lang),
            )
            self.workloads[lang] = workload

            logger.debug(
                f"Initialized workload for {lang}: "
                f"{workload.total_texts} total, {workload.missing_texts} missing"
            )

    def _get_missing_count(self, language: str) -> int:
        """
        Get count of missing translations for a language from TM.

        Args:
            language: Target language code

        Returns:
            Number of missing translations (total_texts if TM not available)
        """
        # If TM not provided, assume all texts are missing
        if self.tm is None or self.site_id is None:
            return self.total_texts

        # TODO: Query TM for missing count when TM API is finalized
        # For now, return total_texts as conservative estimate
        return self.total_texts

    def _update_sorted_languages(self) -> None:
        """Update sorted language list based on current workloads."""
        # Get incomplete workloads
        incomplete = [
            w for w in self.workloads.values()
            if not w.is_complete
        ]

        # Sort by missing count
        sorted_workloads = sort_languages_by_missing_count(
            incomplete,
            order=self.sort_order
        )

        # Extract language codes
        self._sorted_languages = [w.language_code for w in sorted_workloads]

    def get_next_batch(self) -> Optional[Tuple[str, int]]:
        """
        Get next batch of texts to process.

        Returns:
            Tuple of (language_code, text_count) for next batch,
            or None if all languages complete
        """
        # Update sorted list
        self._update_sorted_languages()

        # Check if all complete
        if not self._sorted_languages:
            logger.info("All languages complete")
            return None

        # Get next language in round-robin order
        lang_index = self.current_round % len(self._sorted_languages)
        language = self._sorted_languages[lang_index]

        # Get workload
        workload = self.workloads[language]

        # Calculate batch size (min of texts_per_round and remaining)
        batch_size = min(self.texts_per_round, workload.remaining_texts)

        logger.debug(
            f"Round {self.current_round}: {language} - {batch_size} texts "
            f"({workload.completed_texts}/{workload.total_texts} complete)"
        )

        # Increment round counter
        self.current_round += 1

        return (language, batch_size)

    def mark_batch_complete(self, language: str, count: int) -> None:
        """
        Mark a batch of texts as complete for a language.

        Args:
            language: Language code
            count: Number of texts completed
        """
        if language not in self.workloads:
            logger.warning(f"Unknown language: {language}")
            return

        workload = self.workloads[language]
        workload.completed_texts += count

        logger.debug(
            f"Marked {count} texts complete for {language}: "
            f"{workload.completed_texts}/{workload.total_texts} "
            f"({workload.progress_percentage:.1f}%)"
        )

        # Log completion
        if workload.is_complete:
            logger.info(f"Language {language} complete: {workload.total_texts} texts")

    def get_progress_summary(self) -> Dict[str, Dict[str, any]]:
        """
        Get progress summary for all languages.

        Returns:
            Dict mapping language code to progress info:
            {
                "de": {
                    "total": 100,
                    "completed": 50,
                    "remaining": 50,
                    "progress": 50.0,
                    "is_complete": False
                },
                ...
            }
        """
        summary = {}
        for lang, workload in self.workloads.items():
            summary[lang] = {
                "total": workload.total_texts,
                "completed": workload.completed_texts,
                "remaining": workload.remaining_texts,
                "missing": workload.missing_texts,
                "progress": workload.progress_percentage,
                "is_complete": workload.is_complete,
            }
        return summary

    def get_overall_progress(self) -> Dict[str, any]:
        """
        Get overall progress across all languages.

        Returns:
            Dict with overall statistics:
            {
                "total_languages": 3,
                "completed_languages": 1,
                "total_texts": 300,
                "completed_texts": 150,
                "progress": 50.0
            }
        """
        total_languages = len(self.workloads)
        completed_languages = sum(1 for w in self.workloads.values() if w.is_complete)
        total_texts = sum(w.total_texts for w in self.workloads.values())
        completed_texts = sum(w.completed_texts for w in self.workloads.values())

        progress = 0.0
        if total_texts > 0:
            progress = (completed_texts / total_texts) * 100.0

        return {
            "total_languages": total_languages,
            "completed_languages": completed_languages,
            "remaining_languages": total_languages - completed_languages,
            "total_texts": total_texts,
            "completed_texts": completed_texts,
            "remaining_texts": total_texts - completed_texts,
            "progress": progress,
            "current_round": self.current_round,
        }
