"""
Parallel language executor for concurrent multi-language processing.

T303: federated-splashing-panda
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LanguageExecutionResult:
    """
    Result of executing translation for a single language.

    Attributes:
        language_code: Target language code
        success: True if translation succeeded
        output_path: Path to output file (if successful)
        error: Error message (if failed)
        stats: Translation statistics (if available)
    """
    language_code: str
    success: bool
    output_path: Optional[Path] = None
    error: Optional[str] = None
    stats: Optional[Any] = None


class ParallelLanguageExecutor:
    """
    Parallel executor for concurrent language processing.

    Uses ThreadPoolExecutor to process multiple languages concurrently,
    with error isolation (failure in one language doesn't block others).

    Example:
        executor = ParallelLanguageExecutor(max_workers=2, engine=translation_engine)
        results = executor.execute(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["de", "fr", "es"],
            force=False
        )
        # results = {"de": LanguageExecutionResult(...), "fr": ..., "es": ...}
    """

    def __init__(self, max_workers: int, engine: Any):
        """
        Initialize parallel executor.

        Args:
            max_workers: Maximum number of concurrent threads
            engine: TranslationEngine instance (must have _translate_single_language method)
        """
        self.max_workers = max_workers
        self.engine = engine

        logger.info(f"ParallelLanguageExecutor initialized with {max_workers} workers")

    def execute(
        self,
        site_id: str,
        file_path: Path,
        target_langs: List[str],
        force: bool = False,
    ) -> Dict[str, LanguageExecutionResult]:
        """
        Execute translations for multiple languages in parallel.

        Args:
            site_id: Site identifier
            file_path: Path to source file
            target_langs: List of target language codes
            force: Force retranslation (bypass cache)

        Returns:
            Dict mapping language code to LanguageExecutionResult
        """
        logger.info(
            f"Starting parallel execution: {len(target_langs)} languages, "
            f"{self.max_workers} workers, file={file_path}"
        )

        results: Dict[str, LanguageExecutionResult] = {}

        # Use ThreadPoolExecutor for concurrent execution
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit tasks for all languages
            future_to_lang = {}
            for lang in target_langs:
                future = executor.submit(
                    self._translate_language_safe,
                    site_id=site_id,
                    file_path=file_path,
                    language=lang,
                    force=force,
                )
                future_to_lang[future] = lang

            # Collect results as they complete
            for future in as_completed(future_to_lang):
                lang = future_to_lang[future]
                try:
                    result = future.result()
                    results[lang] = result

                    if result.success:
                        logger.info(f"✓ Completed {lang}: {result.output_path}")
                    else:
                        logger.error(f"✗ Failed {lang}: {result.error}")

                except Exception as e:
                    # Unexpected exception from future.result()
                    logger.error(f"✗ Exception for {lang}: {e}")
                    results[lang] = LanguageExecutionResult(
                        language_code=lang,
                        success=False,
                        error=f"Unexpected exception: {e}",
                    )

        logger.info(
            f"Parallel execution complete: "
            f"{sum(1 for r in results.values() if r.success)}/{len(target_langs)} succeeded"
        )

        return results

    def _translate_language_safe(
        self,
        site_id: str,
        file_path: Path,
        language: str,
        force: bool,
    ) -> LanguageExecutionResult:
        """
        Safely translate file for single language with error handling.

        This method is executed in a worker thread. Any exceptions are caught
        and returned as LanguageExecutionResult with success=False.

        Args:
            site_id: Site identifier
            file_path: Path to source file
            language: Target language code
            force: Force retranslation

        Returns:
            LanguageExecutionResult with success status and output/error
        """
        try:
            logger.debug(f"Translating {file_path} to {language}")

            # Call engine method for single language translation
            # (This method will be added to TranslationEngine in T304)
            result = self.engine._translate_single_language(
                site_id=site_id,
                file_path=file_path,
                target_lang=language,
                force=force,
            )

            # Extract output path from result
            output_path = None
            if result.success and result.outputs:
                output_path = result.outputs.get(language)

            return LanguageExecutionResult(
                language_code=language,
                success=result.success,
                output_path=output_path,
                error=None if result.success else ", ".join(result.errors),
                stats=result.stats,
            )

        except Exception as e:
            logger.error(f"Exception translating {file_path} to {language}: {e}", exc_info=True)
            return LanguageExecutionResult(
                language_code=language,
                success=False,
                error=str(e),
            )

    def get_stats_summary(self, results: Dict[str, LanguageExecutionResult]) -> Dict[str, Any]:
        """
        Get aggregate statistics from parallel execution results.

        Args:
            results: Dict of language -> LanguageExecutionResult

        Returns:
            Dict with aggregate statistics
        """
        total_languages = len(results)
        successful_languages = sum(1 for r in results.values() if r.success)
        failed_languages = total_languages - successful_languages

        # Aggregate translation stats if available
        total_segments = 0
        total_tm_hits = 0
        total_translated = 0

        for result in results.values():
            if result.stats:
                total_segments += getattr(result.stats, "total_segments", 0)
                total_tm_hits += getattr(result.stats, "tm_hits", 0)
                total_translated += getattr(result.stats, "translated_segments", 0)

        return {
            "total_languages": total_languages,
            "successful_languages": successful_languages,
            "failed_languages": failed_languages,
            "total_segments": total_segments,
            "total_tm_hits": total_tm_hits,
            "total_translated": total_translated,
        }
