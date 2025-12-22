"""
Unit tests for parallel language executor (T303: federated-splashing-panda).

Tests ParallelLanguageExecutor and LanguageExecutionResult.
"""
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from concurrent.futures import ThreadPoolExecutor
from src.translation_engine.scheduling import (
    LanguageExecutionResult,
    ParallelLanguageExecutor,
)


class TestLanguageExecutionResult:
    """Test LanguageExecutionResult dataclass."""

    def test_result_initialization_success(self):
        """Test successful result initialization."""
        result = LanguageExecutionResult(
            language_code="de",
            success=True,
            output_path=Path("output/post_de.md"),
            error=None,
            stats={"total_segments": 10},
        )

        assert result.language_code == "de"
        assert result.success is True
        assert result.output_path == Path("output/post_de.md")
        assert result.error is None
        assert result.stats == {"total_segments": 10}

    def test_result_initialization_failure(self):
        """Test failed result initialization."""
        result = LanguageExecutionResult(
            language_code="fr",
            success=False,
            output_path=None,
            error="Translation failed",
            stats=None,
        )

        assert result.language_code == "fr"
        assert result.success is False
        assert result.output_path is None
        assert result.error == "Translation failed"
        assert result.stats is None


class TestParallelLanguageExecutorInitialization:
    """Test ParallelLanguageExecutor initialization."""

    def test_executor_initialization(self):
        """Test executor initialization with basic parameters."""
        mock_engine = Mock()
        executor = ParallelLanguageExecutor(max_workers=2, engine=mock_engine)

        assert executor.max_workers == 2
        assert executor.engine is mock_engine

    def test_executor_initialization_single_worker(self):
        """Test executor with single worker (essentially serial)."""
        mock_engine = Mock()
        executor = ParallelLanguageExecutor(max_workers=1, engine=mock_engine)

        assert executor.max_workers == 1

    def test_executor_initialization_many_workers(self):
        """Test executor with many workers."""
        mock_engine = Mock()
        executor = ParallelLanguageExecutor(max_workers=8, engine=mock_engine)

        assert executor.max_workers == 8


class TestParallelLanguageExecutorExecute:
    """Test ParallelLanguageExecutor.execute()."""

    def test_parallel_executor_runs_languages_concurrently(self):
        """Test executor processes multiple languages in parallel."""
        # Create mock engine with _translate_single_language method
        mock_engine = Mock()

        # Mock successful translation results
        def mock_translate(site_id, file_path, target_lang, force):
            mock_result = Mock()
            mock_result.success = True
            mock_result.outputs = {target_lang: Path(f"output/post_{target_lang}.md")}
            mock_result.errors = []
            mock_result.stats = Mock(total_segments=10, tm_hits=5)
            return mock_result

        mock_engine._translate_single_language = Mock(side_effect=mock_translate)

        # Create executor
        executor = ParallelLanguageExecutor(max_workers=2, engine=mock_engine)

        # Execute for multiple languages
        results = executor.execute(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["de", "fr", "es"],
            force=False,
        )

        # Verify all languages processed
        assert len(results) == 3
        assert "de" in results
        assert "fr" in results
        assert "es" in results

        # Verify all succeeded
        assert all(r.success for r in results.values())

        # Verify engine called for each language
        assert mock_engine._translate_single_language.call_count == 3

    def test_parallel_executor_handles_single_language_failure(self):
        """Test executor continues when one language fails."""
        mock_engine = Mock()

        # Mock translations: "fr" fails, others succeed
        def mock_translate(site_id, file_path, target_lang, force):
            mock_result = Mock()
            if target_lang == "fr":
                mock_result.success = False
                mock_result.outputs = {}
                mock_result.errors = ["Translation error"]
                mock_result.stats = None
            else:
                mock_result.success = True
                mock_result.outputs = {target_lang: Path(f"output/post_{target_lang}.md")}
                mock_result.errors = []
                mock_result.stats = Mock(total_segments=10)
            return mock_result

        mock_engine._translate_single_language = Mock(side_effect=mock_translate)

        executor = ParallelLanguageExecutor(max_workers=2, engine=mock_engine)

        results = executor.execute(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["de", "fr", "es"],
            force=False,
        )

        # All languages should have results
        assert len(results) == 3

        # "fr" should have failed
        assert results["fr"].success is False
        assert results["fr"].error is not None

        # Others should have succeeded
        assert results["de"].success is True
        assert results["es"].success is True

    def test_parallel_executor_handles_exception_in_worker(self):
        """Test executor handles exceptions raised in worker threads."""
        mock_engine = Mock()

        # Mock translations: "fr" raises exception, others succeed
        def mock_translate(site_id, file_path, target_lang, force):
            if target_lang == "fr":
                raise RuntimeError("Model crash")

            mock_result = Mock()
            mock_result.success = True
            mock_result.outputs = {target_lang: Path(f"output/post_{target_lang}.md")}
            mock_result.errors = []
            mock_result.stats = Mock(total_segments=10)
            return mock_result

        mock_engine._translate_single_language = Mock(side_effect=mock_translate)

        executor = ParallelLanguageExecutor(max_workers=2, engine=mock_engine)

        results = executor.execute(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["de", "fr", "es"],
            force=False,
        )

        # All languages should have results
        assert len(results) == 3

        # "fr" should have error result
        assert results["fr"].success is False
        assert "Model crash" in results["fr"].error

        # Others should have succeeded
        assert results["de"].success is True
        assert results["es"].success is True

    def test_parallel_executor_with_force_retranslate(self):
        """Test executor passes force parameter correctly."""
        mock_engine = Mock()

        def mock_translate(site_id, file_path, target_lang, force):
            mock_result = Mock()
            mock_result.success = True
            mock_result.outputs = {target_lang: Path(f"output/post_{target_lang}.md")}
            mock_result.errors = []
            mock_result.stats = Mock()
            return mock_result

        mock_engine._translate_single_language = Mock(side_effect=mock_translate)

        executor = ParallelLanguageExecutor(max_workers=2, engine=mock_engine)

        results = executor.execute(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["de", "fr"],
            force=True,  # Force retranslation
        )

        # Verify force=True was passed to all calls
        for call in mock_engine._translate_single_language.call_args_list:
            assert call.kwargs["force"] is True

    def test_parallel_executor_single_language(self):
        """Test executor works with single language (no real parallelism)."""
        mock_engine = Mock()

        def mock_translate(site_id, file_path, target_lang, force):
            mock_result = Mock()
            mock_result.success = True
            mock_result.outputs = {target_lang: Path(f"output/post_{target_lang}.md")}
            mock_result.errors = []
            mock_result.stats = Mock()
            return mock_result

        mock_engine._translate_single_language = Mock(side_effect=mock_translate)

        executor = ParallelLanguageExecutor(max_workers=4, engine=mock_engine)

        results = executor.execute(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["de"],
            force=False,
        )

        assert len(results) == 1
        assert results["de"].success is True


class TestParallelLanguageExecutorTranslateSafe:
    """Test ParallelLanguageExecutor._translate_language_safe()."""

    def test_translate_safe_success(self):
        """Test _translate_language_safe with successful translation."""
        mock_engine = Mock()

        mock_result = Mock()
        mock_result.success = True
        mock_result.outputs = {"de": Path("output/post_de.md")}
        mock_result.errors = []
        mock_result.stats = Mock(total_segments=10, tm_hits=5)

        mock_engine._translate_single_language = Mock(return_value=mock_result)

        executor = ParallelLanguageExecutor(max_workers=2, engine=mock_engine)

        result = executor._translate_language_safe(
            site_id="example",
            file_path=Path("content/post.md"),
            language="de",
            force=False,
        )

        assert result.success is True
        assert result.language_code == "de"
        assert result.output_path == Path("output/post_de.md")
        assert result.error is None
        assert result.stats is not None

    def test_translate_safe_failure(self):
        """Test _translate_language_safe with failed translation."""
        mock_engine = Mock()

        mock_result = Mock()
        mock_result.success = False
        mock_result.outputs = {}
        mock_result.errors = ["Translation error", "Validation failed"]
        mock_result.stats = None

        mock_engine._translate_single_language = Mock(return_value=mock_result)

        executor = ParallelLanguageExecutor(max_workers=2, engine=mock_engine)

        result = executor._translate_language_safe(
            site_id="example",
            file_path=Path("content/post.md"),
            language="fr",
            force=False,
        )

        assert result.success is False
        assert result.language_code == "fr"
        assert result.output_path is None
        assert "Translation error" in result.error
        assert result.stats is None

    def test_translate_safe_exception(self):
        """Test _translate_language_safe handles exception gracefully."""
        mock_engine = Mock()
        mock_engine._translate_single_language = Mock(side_effect=RuntimeError("Model crash"))

        executor = ParallelLanguageExecutor(max_workers=2, engine=mock_engine)

        result = executor._translate_language_safe(
            site_id="example",
            file_path=Path("content/post.md"),
            language="es",
            force=False,
        )

        assert result.success is False
        assert result.language_code == "es"
        assert "Model crash" in result.error


class TestParallelLanguageExecutorStats:
    """Test ParallelLanguageExecutor.get_stats_summary()."""

    def test_get_stats_summary(self):
        """Test get_stats_summary aggregates statistics correctly."""
        mock_stats_1 = Mock(total_segments=10, tm_hits=5, translated_segments=5)
        mock_stats_2 = Mock(total_segments=15, tm_hits=10, translated_segments=5)

        results = {
            "de": LanguageExecutionResult(
                language_code="de",
                success=True,
                stats=mock_stats_1,
            ),
            "fr": LanguageExecutionResult(
                language_code="fr",
                success=True,
                stats=mock_stats_2,
            ),
            "es": LanguageExecutionResult(
                language_code="es",
                success=False,
                error="Translation failed",
                stats=None,
            ),
        }

        executor = ParallelLanguageExecutor(max_workers=2, engine=Mock())
        summary = executor.get_stats_summary(results)

        assert summary["total_languages"] == 3
        assert summary["successful_languages"] == 2
        assert summary["failed_languages"] == 1
        assert summary["total_segments"] == 25  # 10 + 15 + 0
        assert summary["total_tm_hits"] == 15  # 5 + 10 + 0
        assert summary["total_translated"] == 10  # 5 + 5 + 0

    def test_get_stats_summary_all_failed(self):
        """Test get_stats_summary when all languages failed."""
        results = {
            "de": LanguageExecutionResult("de", success=False, error="Error 1"),
            "fr": LanguageExecutionResult("fr", success=False, error="Error 2"),
        }

        executor = ParallelLanguageExecutor(max_workers=2, engine=Mock())
        summary = executor.get_stats_summary(results)

        assert summary["total_languages"] == 2
        assert summary["successful_languages"] == 0
        assert summary["failed_languages"] == 2
        assert summary["total_segments"] == 0

    def test_get_stats_summary_all_succeeded(self):
        """Test get_stats_summary when all languages succeeded."""
        mock_stats = Mock(total_segments=10, tm_hits=5, translated_segments=5)

        results = {
            "de": LanguageExecutionResult("de", success=True, stats=mock_stats),
            "fr": LanguageExecutionResult("fr", success=True, stats=mock_stats),
        }

        executor = ParallelLanguageExecutor(max_workers=2, engine=Mock())
        summary = executor.get_stats_summary(results)

        assert summary["total_languages"] == 2
        assert summary["successful_languages"] == 2
        assert summary["failed_languages"] == 0
        assert summary["total_segments"] == 20  # 10 + 10


class TestParallelLanguageExecutorConcurrency:
    """Test ParallelLanguageExecutor concurrency behavior."""

    @patch("src.translation_engine.scheduling.parallel_executor.ThreadPoolExecutor")
    def test_parallel_executor_max_workers_limits_concurrency(self, mock_pool_class):
        """Test executor respects max_workers limit."""
        # Create mock pool instance
        mock_pool = MagicMock()
        mock_pool_class.return_value.__enter__.return_value = mock_pool

        # Mock submit to return mock futures
        mock_future = Mock()
        mock_future.result = Mock(return_value=LanguageExecutionResult("de", success=True))
        mock_pool.submit = Mock(return_value=mock_future)

        # Mock as_completed to return futures
        with patch("src.translation_engine.scheduling.parallel_executor.as_completed", return_value=[mock_future]):
            mock_engine = Mock()
            executor = ParallelLanguageExecutor(max_workers=3, engine=mock_engine)

            executor.execute(
                site_id="example",
                file_path=Path("content/post.md"),
                target_langs=["de"],
                force=False,
            )

            # Verify ThreadPoolExecutor created with max_workers=3
            mock_pool_class.assert_called_once_with(max_workers=3)

    def test_parallel_executor_actual_concurrency(self):
        """Test that executor actually runs tasks concurrently."""
        import time
        import threading

        mock_engine = Mock()
        execution_times = {}
        lock = threading.Lock()

        def mock_translate(site_id, file_path, target_lang, force):
            # Record start time
            with lock:
                execution_times[target_lang] = {"start": time.time()}

            # Simulate work
            time.sleep(0.1)

            # Record end time
            with lock:
                execution_times[target_lang]["end"] = time.time()

            mock_result = Mock()
            mock_result.success = True
            mock_result.outputs = {target_lang: Path(f"output/post_{target_lang}.md")}
            mock_result.errors = []
            mock_result.stats = Mock()
            return mock_result

        mock_engine._translate_single_language = Mock(side_effect=mock_translate)

        executor = ParallelLanguageExecutor(max_workers=3, engine=mock_engine)

        start = time.time()
        results = executor.execute(
            site_id="example",
            file_path=Path("content/post.md"),
            target_langs=["de", "fr", "es"],
            force=False,
        )
        end = time.time()

        # Total time should be ~0.1s (concurrent), not ~0.3s (serial)
        total_time = end - start
        assert total_time < 0.25  # Allow some overhead, but should be much less than 0.3s

        # Verify some overlap in execution (concurrent execution)
        # At least two languages should have overlapping execution windows
        overlaps = 0
        langs = list(execution_times.keys())
        for i in range(len(langs)):
            for j in range(i + 1, len(langs)):
                lang1, lang2 = langs[i], langs[j]
                # Check if execution windows overlap
                if (execution_times[lang1]["start"] < execution_times[lang2]["end"] and
                    execution_times[lang2]["start"] < execution_times[lang1]["end"]):
                    overlaps += 1

        # With 3 languages running concurrently, we should see overlaps
        assert overlaps >= 1  # At least one pair should overlap
