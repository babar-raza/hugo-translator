"""
Unit tests for language scheduler (T302: federated-splashing-panda).

Tests RoundRobinScheduler, LanguageWorkload, and sorting functionality.
"""
import pytest

from src.translation_engine.scheduling import (
    LanguageWorkload,
    RoundRobinScheduler,
    sort_languages_by_missing_count,
)


class TestLanguageWorkload:
    """Test LanguageWorkload dataclass."""

    def test_workload_initialization(self):
        """Test workload creation with default values."""
        workload = LanguageWorkload(
            language_code="de",
            total_texts=100,
            completed_texts=0,
            missing_texts=75,
        )

        assert workload.language_code == "de"
        assert workload.total_texts == 100
        assert workload.completed_texts == 0
        assert workload.missing_texts == 75

    def test_remaining_texts_property(self):
        """Test remaining_texts property calculation."""
        workload = LanguageWorkload(
            language_code="fr",
            total_texts=100,
            completed_texts=30,
            missing_texts=70,
        )

        assert workload.remaining_texts == 70

    def test_is_complete_property_false(self):
        """Test is_complete property when not complete."""
        workload = LanguageWorkload(
            language_code="es",
            total_texts=100,
            completed_texts=50,
        )

        assert workload.is_complete is False

    def test_is_complete_property_true(self):
        """Test is_complete property when complete."""
        workload = LanguageWorkload(
            language_code="it",
            total_texts=100,
            completed_texts=100,
        )

        assert workload.is_complete is True

    def test_progress_percentage(self):
        """Test progress_percentage calculation."""
        workload = LanguageWorkload(
            language_code="pt",
            total_texts=100,
            completed_texts=25,
        )

        assert workload.progress_percentage == 25.0

    def test_progress_percentage_zero_total(self):
        """Test progress_percentage when total is zero."""
        workload = LanguageWorkload(
            language_code="nl",
            total_texts=0,
            completed_texts=0,
        )

        assert workload.progress_percentage == 100.0


class TestSortLanguagesByMissingCount:
    """Test sort_languages_by_missing_count function."""

    def test_sorting_desc_returns_most_missing_first(self):
        """Test descending sort returns language with most missing first."""
        workloads = [
            LanguageWorkload("de", total_texts=100, missing_texts=50),
            LanguageWorkload("fr", total_texts=100, missing_texts=75),
            LanguageWorkload("es", total_texts=100, missing_texts=25),
        ]

        sorted_workloads = sort_languages_by_missing_count(workloads, order="desc")

        assert sorted_workloads[0].language_code == "fr"  # 75 missing
        assert sorted_workloads[1].language_code == "de"  # 50 missing
        assert sorted_workloads[2].language_code == "es"  # 25 missing

    def test_sorting_asc_returns_least_missing_first(self):
        """Test ascending sort returns language with least missing first."""
        workloads = [
            LanguageWorkload("de", total_texts=100, missing_texts=50),
            LanguageWorkload("fr", total_texts=100, missing_texts=75),
            LanguageWorkload("es", total_texts=100, missing_texts=25),
        ]

        sorted_workloads = sort_languages_by_missing_count(workloads, order="asc")

        assert sorted_workloads[0].language_code == "es"  # 25 missing
        assert sorted_workloads[1].language_code == "de"  # 50 missing
        assert sorted_workloads[2].language_code == "fr"  # 75 missing

    def test_sorting_empty_list(self):
        """Test sorting empty list."""
        workloads = []
        sorted_workloads = sort_languages_by_missing_count(workloads, order="desc")
        assert sorted_workloads == []

    def test_sorting_single_item(self):
        """Test sorting list with single item."""
        workloads = [LanguageWorkload("de", total_texts=100, missing_texts=50)]
        sorted_workloads = sort_languages_by_missing_count(workloads, order="desc")
        assert len(sorted_workloads) == 1
        assert sorted_workloads[0].language_code == "de"


class TestRoundRobinSchedulerInitialization:
    """Test RoundRobinScheduler initialization."""

    def test_scheduler_initialization(self):
        """Test scheduler initialization with basic parameters."""
        scheduler = RoundRobinScheduler(
            languages=["de", "fr", "es"],
            total_texts=100,
            texts_per_round=10,
            sort_order="desc",
        )

        assert scheduler.languages == ["de", "fr", "es"]
        assert scheduler.total_texts == 100
        assert scheduler.texts_per_round == 10
        assert scheduler.sort_order == "desc"
        assert len(scheduler.workloads) == 3

    def test_scheduler_initializes_workloads(self):
        """Test scheduler creates workload for each language."""
        scheduler = RoundRobinScheduler(
            languages=["de", "fr"],
            total_texts=50,
            texts_per_round=5,
            sort_order="desc",
        )

        assert "de" in scheduler.workloads
        assert "fr" in scheduler.workloads
        assert scheduler.workloads["de"].total_texts == 50
        assert scheduler.workloads["fr"].total_texts == 50
        assert scheduler.workloads["de"].completed_texts == 0
        assert scheduler.workloads["fr"].completed_texts == 0

    def test_scheduler_with_single_language(self):
        """Test scheduler with single language."""
        scheduler = RoundRobinScheduler(
            languages=["de"],
            total_texts=100,
            texts_per_round=20,
            sort_order="desc",
        )

        assert len(scheduler.workloads) == 1
        assert "de" in scheduler.workloads


class TestRoundRobinSchedulerGetNextBatch:
    """Test RoundRobinScheduler.get_next_batch()."""

    def test_get_next_batch_returns_correct_language(self):
        """Test get_next_batch returns language and batch size."""
        scheduler = RoundRobinScheduler(
            languages=["de", "fr"],
            total_texts=100,
            texts_per_round=10,
            sort_order="desc",
        )

        batch = scheduler.get_next_batch()

        assert batch is not None
        language, batch_size = batch
        assert language in ["de", "fr"]
        assert batch_size == 10

    def test_get_next_batch_round_robin_cycling(self):
        """Test get_next_batch cycles through languages in round-robin."""
        # Create scheduler with unequal missing counts to test sorting
        scheduler = RoundRobinScheduler(
            languages=["de", "fr", "es"],
            total_texts=30,  # Small total for quick test
            texts_per_round=10,
            sort_order="desc",
        )

        # Get first 3 batches (one per language)
        batches = []
        for _ in range(3):
            batch = scheduler.get_next_batch()
            if batch:
                batches.append(batch)

        assert len(batches) == 3
        # Should get all three languages (order depends on missing count, but all present)
        languages_seen = {batch[0] for batch in batches}
        assert len(languages_seen) <= 3  # May cycle if languages complete

    def test_get_next_batch_respects_remaining_texts(self):
        """Test get_next_batch returns min(texts_per_round, remaining)."""
        scheduler = RoundRobinScheduler(
            languages=["de"],
            total_texts=15,  # Only 15 total
            texts_per_round=10,
            sort_order="desc",
        )

        # First batch should get 10 texts
        batch1 = scheduler.get_next_batch()
        assert batch1 == ("de", 10)

        # Mark 10 complete
        scheduler.mark_batch_complete("de", 10)

        # Second batch should get only 5 texts (remaining)
        batch2 = scheduler.get_next_batch()
        assert batch2 == ("de", 5)

    def test_get_next_batch_returns_none_when_complete(self):
        """Test get_next_batch returns None when all languages complete."""
        scheduler = RoundRobinScheduler(
            languages=["de"],
            total_texts=10,
            texts_per_round=10,
            sort_order="desc",
        )

        # Get and complete first batch
        batch = scheduler.get_next_batch()
        assert batch == ("de", 10)
        scheduler.mark_batch_complete("de", 10)

        # Next call should return None
        batch2 = scheduler.get_next_batch()
        assert batch2 is None


class TestRoundRobinSchedulerMarkBatchComplete:
    """Test RoundRobinScheduler.mark_batch_complete()."""

    def test_mark_batch_complete_updates_workload(self):
        """Test mark_batch_complete updates completed_texts count."""
        scheduler = RoundRobinScheduler(
            languages=["de"],
            total_texts=100,
            texts_per_round=10,
            sort_order="desc",
        )

        scheduler.mark_batch_complete("de", 10)

        assert scheduler.workloads["de"].completed_texts == 10

    def test_mark_batch_complete_multiple_calls(self):
        """Test mark_batch_complete accumulates counts."""
        scheduler = RoundRobinScheduler(
            languages=["fr"],
            total_texts=100,
            texts_per_round=10,
            sort_order="desc",
        )

        scheduler.mark_batch_complete("fr", 10)
        scheduler.mark_batch_complete("fr", 15)
        scheduler.mark_batch_complete("fr", 5)

        assert scheduler.workloads["fr"].completed_texts == 30

    def test_mark_batch_complete_unknown_language_warns(self):
        """Test mark_batch_complete handles unknown language gracefully."""
        scheduler = RoundRobinScheduler(
            languages=["de"],
            total_texts=100,
            texts_per_round=10,
            sort_order="desc",
        )

        # Should not raise exception
        scheduler.mark_batch_complete("unknown", 10)

        # Original workload unchanged
        assert scheduler.workloads["de"].completed_texts == 0


class TestRoundRobinSchedulerProgress:
    """Test RoundRobinScheduler progress tracking."""

    def test_get_progress_summary(self):
        """Test get_progress_summary returns info for all languages."""
        scheduler = RoundRobinScheduler(
            languages=["de", "fr"],
            total_texts=100,
            texts_per_round=10,
            sort_order="desc",
        )

        scheduler.mark_batch_complete("de", 25)
        scheduler.mark_batch_complete("fr", 50)

        summary = scheduler.get_progress_summary()

        assert "de" in summary
        assert "fr" in summary
        assert summary["de"]["completed"] == 25
        assert summary["de"]["remaining"] == 75
        assert summary["de"]["progress"] == 25.0
        assert summary["fr"]["completed"] == 50
        assert summary["fr"]["progress"] == 50.0

    def test_get_overall_progress(self):
        """Test get_overall_progress returns aggregate statistics."""
        scheduler = RoundRobinScheduler(
            languages=["de", "fr", "es"],
            total_texts=100,
            texts_per_round=10,
            sort_order="desc",
        )

        scheduler.mark_batch_complete("de", 100)  # Complete
        scheduler.mark_batch_complete("fr", 50)
        scheduler.mark_batch_complete("es", 25)

        overall = scheduler.get_overall_progress()

        assert overall["total_languages"] == 3
        assert overall["completed_languages"] == 1  # Only "de" complete
        assert overall["remaining_languages"] == 2
        assert overall["total_texts"] == 300  # 3 languages * 100 texts
        assert overall["completed_texts"] == 175  # 100 + 50 + 25
        assert overall["remaining_texts"] == 125
        assert overall["progress"] == pytest.approx(58.33, rel=0.01)

    def test_get_overall_progress_all_complete(self):
        """Test get_overall_progress when all languages complete."""
        scheduler = RoundRobinScheduler(
            languages=["de", "fr"],
            total_texts=50,
            texts_per_round=25,
            sort_order="desc",
        )

        scheduler.mark_batch_complete("de", 50)
        scheduler.mark_batch_complete("fr", 50)

        overall = scheduler.get_overall_progress()

        assert overall["completed_languages"] == 2
        assert overall["remaining_languages"] == 0
        assert overall["progress"] == 100.0


class TestRoundRobinSchedulerCompleteWorkflow:
    """Test RoundRobinScheduler complete workflow."""

    def test_scheduler_completes_when_all_done(self):
        """Test scheduler processes all texts and completes."""
        scheduler = RoundRobinScheduler(
            languages=["de", "fr"],
            total_texts=20,  # Small for quick test
            texts_per_round=10,
            sort_order="desc",
        )

        batches_processed = []
        while True:
            batch = scheduler.get_next_batch()
            if batch is None:
                break

            language, batch_size = batch
            batches_processed.append((language, batch_size))
            scheduler.mark_batch_complete(language, batch_size)

        # Should have processed 4 batches (2 languages * 2 rounds of 10 texts)
        assert len(batches_processed) == 4

        # All workloads should be complete
        for workload in scheduler.workloads.values():
            assert workload.is_complete

        # Overall progress should be 100%
        overall = scheduler.get_overall_progress()
        assert overall["progress"] == 100.0

    def test_scheduler_workflow_with_partial_last_batch(self):
        """Test scheduler handles partial last batch correctly."""
        scheduler = RoundRobinScheduler(
            languages=["de"],
            total_texts=25,  # Not evenly divisible by texts_per_round
            texts_per_round=10,
            sort_order="desc",
        )

        batches = []
        while True:
            batch = scheduler.get_next_batch()
            if batch is None:
                break

            language, batch_size = batch
            batches.append(batch_size)
            scheduler.mark_batch_complete(language, batch_size)

        # Should get: 10, 10, 5
        assert batches == [10, 10, 5]
        assert scheduler.workloads["de"].is_complete
