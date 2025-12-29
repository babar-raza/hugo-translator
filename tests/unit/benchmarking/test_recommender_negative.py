"""Negative test cases and edge cases for ModelRecommender."""
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.benchmarking.feedback import RecommendationFeedback
from src.benchmarking.recommender import ModelRecommender, ModelRecommendation
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkRun, BenchmarkResult
from src.benchmarking.system_info import SystemInfo


def test_recommend_with_no_historical_data():
    """Should return default recommendation when no benchmark history exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        # Should return default recommendation, not crash
        rec = recommender.recommend(system_info)

        assert rec is not None
        assert isinstance(rec, ModelRecommendation)
        assert rec.model_id is not None
        assert rec.device is not None
        assert rec.batch_size > 0
        assert 0.0 <= rec.confidence_score <= 1.0


def test_recommend_with_null_requirements():
    """Should handle None requirements gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        # Explicitly pass None for requirements
        rec = recommender.recommend(system_info, requirements=None)

        assert rec is not None
        assert isinstance(rec, ModelRecommendation)


def test_recommend_with_empty_requirements():
    """Should handle empty requirements dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        # Empty requirements dict
        rec = recommender.recommend(system_info, requirements={})

        assert rec is not None


def test_recommend_with_conflicting_requirements():
    """Should handle conflicting requirements (high throughput + low memory)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        # Conflicting requirements
        requirements = {
            "max_memory_mb": 100,  # Very low memory
            "min_throughput": 10000,  # Very high throughput
        }

        # Should still return a recommendation (best effort)
        rec = recommender.recommend(system_info, requirements)

        assert rec is not None
        assert isinstance(rec, ModelRecommendation)


def test_recommend_with_invalid_requirement_types():
    """Should handle invalid requirement types gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        # Invalid types in requirements
        requirements = {
            "max_memory_mb": "not_a_number",  # Should be int/float
            "min_throughput": None,
            "prefer_quality": "yes",  # Should be bool
        }

        # Should either handle gracefully or raise TypeError
        try:
            rec = recommender.recommend(system_info, requirements)
            # If it succeeds, should still return valid recommendation
            assert rec is not None
        except (TypeError, ValueError):
            # Also acceptable - validation error
            pass


def test_recommend_with_zero_cpu_cores():
    """Should handle system with zero CPU cores."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=0,  # Invalid - zero cores
            ram_total_gb=16.0,
        )

        # Should handle gracefully (might return default or error)
        try:
            rec = recommender.recommend(system_info)
            assert rec is not None
        except (ValueError, ZeroDivisionError):
            # Also acceptable
            pass


def test_recommend_with_negative_ram():
    """Should handle system with negative RAM."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=-16.0,  # Invalid - negative RAM
        )

        # Should handle gracefully
        try:
            rec = recommender.recommend(system_info)
            assert rec is not None
        except ValueError:
            # Also acceptable
            pass


def test_record_outcome_with_unknown_recommendation_id():
    """Should handle feedback for unknown recommendation gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        feedback = RecommendationFeedback(
            recommendation_id="unknown_rec_id",  # Not tracked
            predicted_throughput=100.0,
            actual_throughput=95.0,
            predicted_memory_mb=1000.0,
            actual_memory_mb=1100.0,
            success=True,
        )

        # Should not crash, just log warning
        recommender.record_outcome(feedback)  # Should succeed


def test_record_outcome_with_negative_throughput():
    """Should handle feedback with negative throughput values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        feedback = RecommendationFeedback(
            recommendation_id="test_rec",
            predicted_throughput=-100.0,  # Invalid - negative
            actual_throughput=-95.0,  # Invalid - negative
            predicted_memory_mb=1000.0,
            actual_memory_mb=1100.0,
            success=True,
        )

        # Should either handle gracefully or raise ValueError
        try:
            recommender.record_outcome(feedback)
        except ValueError:
            # Validation error acceptable
            pass


def test_record_outcome_with_extreme_values():
    """Should handle feedback with extremely large values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        feedback = RecommendationFeedback(
            recommendation_id="test_rec",
            predicted_throughput=1e15,  # Extremely large
            actual_throughput=1e16,  # Even larger
            predicted_memory_mb=1e12,  # Terabytes of memory
            actual_memory_mb=1e13,
            success=True,
        )

        # Should handle without overflow
        try:
            recommender.record_outcome(feedback)
        except (OverflowError, ValueError):
            # Acceptable
            pass


def test_record_outcome_with_nan_values():
    """Should handle feedback with NaN values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        feedback = RecommendationFeedback(
            recommendation_id="test_rec",
            predicted_throughput=float("nan"),  # NaN value
            actual_throughput=100.0,
            predicted_memory_mb=1000.0,
            actual_memory_mb=float("nan"),  # NaN value
            success=True,
        )

        # Should handle NaN gracefully
        try:
            recommender.record_outcome(feedback)
        except (ValueError, TypeError):
            # Validation error acceptable
            pass


def test_recommend_with_runs_having_empty_results():
    """Should handle benchmark runs with no results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Create run with empty results
        run = BenchmarkRun(
            run_id="empty_results",
            model_id="test_model",
            device="cpu",
            batch_sizes=[8],
            iterations=0,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test_cpu",
                cpu_cores=8,
                ram_total_gb=16.0,
            ),
            results=[],  # Empty results
        )
        db.save_run(run)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        # Should handle runs with empty results
        rec = recommender.recommend(system_info)

        assert rec is not None


def test_recommend_with_runs_having_zero_throughput():
    """Should handle benchmark runs with zero throughput."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Create run with zero throughput
        run = BenchmarkRun(
            run_id="zero_throughput",
            model_id="test_model",
            device="cpu",
            batch_sizes=[8],
            iterations=10,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test_cpu",
                cpu_cores=8,
                ram_total_gb=16.0,
            ),
            results=[
                BenchmarkResult(
                    iteration=1,
                    batch_size=8,
                    duration_seconds=10.0,
                    throughput_tokens_per_sec=0.0,  # Zero throughput
                    peak_memory_mb=1000.0,
                    errors=None,
                )
            ],
        )
        db.save_run(run)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        # Should handle zero throughput gracefully
        rec = recommender.recommend(system_info)

        assert rec is not None
        # Confidence should be low for zero throughput
        assert 0.0 <= rec.confidence_score <= 1.0


def test_recommend_with_invalid_learning_rate():
    """Should reject invalid learning rates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Negative learning rate
        with pytest.raises((ValueError, AssertionError)):
            ModelRecommender(db, learning_rate=-0.5)

        # Learning rate > 1
        with pytest.raises((ValueError, AssertionError)):
            ModelRecommender(db, learning_rate=2.0)


def test_recommend_with_extremely_large_system():
    """Should handle system with extreme specs (1000 cores, 1TB RAM)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="massive_cpu",
            cpu_cores=1000,  # 1000 cores
            ram_total_gb=1024.0,  # 1TB RAM
        )

        # Should handle extreme specs
        rec = recommender.recommend(system_info)

        assert rec is not None
        assert rec.batch_size > 0


def test_recommend_with_extremely_small_system():
    """Should handle system with minimal specs (1 core, 1GB RAM)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="tiny_cpu",
            cpu_cores=1,  # Single core
            ram_total_gb=1.0,  # 1GB RAM
        )

        # Should handle minimal specs
        rec = recommender.recommend(system_info)

        assert rec is not None
        assert rec.batch_size > 0


def test_confidence_score_always_in_range():
    """Confidence score should always be in [0, 1] range."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Create multiple runs with varying quality
        for i in range(10):
            run = BenchmarkRun(
                run_id=f"run_{i}",
                model_id=f"model_{i}",
                device="cpu",
                batch_sizes=[8],
                iterations=10,
                corpus_category="test",
                purpose="test",
                tags=[],
                system_info=SystemInfo(
                    python_version="3.11",
                    platform="linux",
                    cpu_model="test_cpu",
                    cpu_cores=8,
                    ram_total_gb=16.0,
                ),
                results=[
                    BenchmarkResult(
                        iteration=1,
                        batch_size=8,
                        duration_seconds=1.0,
                        throughput_tokens_per_sec=i * 100.0,  # Varying throughput
                        peak_memory_mb=1000.0,
                        errors=None,
                    )
                ],
            )
            db.save_run(run)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        # Generate multiple recommendations
        for _ in range(5):
            rec = recommender.recommend(system_info)
            # Confidence MUST be in [0, 1]
            assert 0.0 <= rec.confidence_score <= 1.0, \
                f"Confidence {rec.confidence_score} outside valid range"


def test_batch_size_always_positive():
    """Recommended batch size should always be positive."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Create run with empty batch_sizes
        run = BenchmarkRun(
            run_id="no_batches",
            model_id="test_model",
            device="cpu",
            batch_sizes=[],  # Empty batch sizes
            iterations=10,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test_cpu",
                cpu_cores=8,
                ram_total_gb=16.0,
            ),
            results=[],
        )
        db.save_run(run)

        recommender = ModelRecommender(db)

        system_info = SystemInfo(
            python_version="3.11",
            platform="linux",
            cpu_model="test_cpu",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

        rec = recommender.recommend(system_info)

        # Batch size MUST be positive
        assert rec.batch_size > 0, "Batch size must be positive"
