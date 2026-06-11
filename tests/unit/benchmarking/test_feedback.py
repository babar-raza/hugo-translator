"""Unit tests for recommendation feedback loop (BM-03)."""

from datetime import datetime

import pytest

from src.benchmarking.feedback import (
    AdaptiveWeightLearner,
    FeedbackCollector,
    RecommendationFeedback,
)
from src.benchmarking.storage import BenchmarkRun
from src.benchmarking.system_info import SystemInfo

# temp_db fixture imported from conftest.py


@pytest.fixture
def system_info():
    """Create test system info."""
    return SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=8,
        total_ram_gb=16.0,
        os_name="Linux",
        os_version="5.15.0",
        python_version="3.11.0",
        collected_at_utc="2025-12-24T10:00:00Z",
    )


@pytest.fixture
def db_with_runs(temp_db, system_info):
    """Create temp_db with pre-existing benchmark runs for FK satisfaction.

    The recommendation_feedback table has FK to benchmark_runs(run_id),
    so tests inserting feedback need corresponding runs to exist first.
    """
    # All run IDs used in feedback tests
    run_ids = [
        "rec_001",
        "rec_002",  # Basic tests
        "rec_a",
        "rec_b",  # Model filter tests
        "rec_0",
        "rec_1",
        "rec_2",
        "rec_3",
        "rec_4",  # History tests
        "rec_success",
        "rec_fail",  # Success/failure tests
    ]

    for run_id in run_ids:
        run = BenchmarkRun(
            run_id=run_id,
            model_id="model_a",
            device="cpu",
            batch_sizes=[8],
            iterations=1,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=system_info,
            results=[],
            total_duration_seconds=1.0,
        )
        temp_db.save_run(run)

    return temp_db


@pytest.fixture
def sample_feedback(system_info):
    """Create sample feedback."""
    return RecommendationFeedback(
        feedback_id="fb_001",
        recommendation_id="rec_001",
        model_id_recommended="model_a",
        model_id_used="model_a",
        device_recommended="cpu",
        device_used="cpu",
        predicted_throughput=100.0,
        actual_throughput=95.0,
        predicted_memory_mb=1000.0,
        actual_memory_mb=1050.0,
        success=True,
        quality_score=0.95,
        failure_reason=None,
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        system_info=system_info,
    )


def test_bm03_feedback_collector_creates_table(temp_db):
    """Test that FeedbackCollector creates feedback table."""
    collector = FeedbackCollector(temp_db)

    # Verify table exists by querying it
    with temp_db._get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='recommendation_feedback'"
        )
        assert cursor.fetchone() is not None


def test_bm03_record_feedback(db_with_runs, sample_feedback):
    """Test recording feedback."""
    collector = FeedbackCollector(db_with_runs)

    collector.record_feedback(sample_feedback)

    # Verify feedback was recorded
    feedback = collector.get_feedback_for_recommendation("rec_001")
    assert feedback is not None
    assert feedback.feedback_id == "fb_001"
    assert feedback.model_id_recommended == "model_a"


def test_bm03_get_feedback_for_nonexistent_recommendation(temp_db):
    """Test getting feedback for non-existent recommendation."""
    collector = FeedbackCollector(temp_db)

    feedback = collector.get_feedback_for_recommendation("nonexistent")

    assert feedback is None


def test_bm03_get_feedback_for_recommendation(db_with_runs, sample_feedback):
    """Test getting feedback for specific recommendation."""
    collector = FeedbackCollector(db_with_runs)
    collector.record_feedback(sample_feedback)

    feedback = collector.get_feedback_for_recommendation("rec_001")

    assert feedback is not None
    assert feedback.recommendation_id == "rec_001"
    assert feedback.predicted_throughput == 100.0
    assert feedback.actual_throughput == 95.0


def test_bm03_feedback_roundtrip(db_with_runs, sample_feedback):
    """Test that feedback can be stored and retrieved with all fields."""
    collector = FeedbackCollector(db_with_runs)

    collector.record_feedback(sample_feedback)
    retrieved = collector.get_feedback_for_recommendation("rec_001")

    assert retrieved.feedback_id == sample_feedback.feedback_id
    assert retrieved.recommendation_id == sample_feedback.recommendation_id
    assert retrieved.model_id_recommended == sample_feedback.model_id_recommended
    assert retrieved.model_id_used == sample_feedback.model_id_used
    assert retrieved.success == sample_feedback.success
    assert retrieved.quality_score == sample_feedback.quality_score


def test_bm03_accuracy_metrics_empty(temp_db):
    """Test accuracy metrics with no feedback."""
    collector = FeedbackCollector(temp_db)

    accuracy = collector.get_accuracy_metrics()

    assert accuracy.total_recommendations == 0
    assert accuracy.followed_count == 0
    assert accuracy.success_rate == 0.0


def test_bm03_accuracy_metrics_single_feedback(db_with_runs, sample_feedback):
    """Test accuracy metrics with single feedback."""
    collector = FeedbackCollector(db_with_runs)
    collector.record_feedback(sample_feedback)

    accuracy = collector.get_accuracy_metrics()

    assert accuracy.total_recommendations == 1
    assert accuracy.followed_count == 1  # Recommended = used
    assert accuracy.success_rate == 1.0  # Success = True


def test_bm03_accuracy_metrics_not_followed(db_with_runs, sample_feedback):
    """Test accuracy when recommendation not followed."""
    collector = FeedbackCollector(db_with_runs)

    # User chose different model
    feedback = sample_feedback
    feedback.model_id_used = "model_b"  # Different from recommended
    collector.record_feedback(feedback)

    accuracy = collector.get_accuracy_metrics()

    assert accuracy.total_recommendations == 1
    assert accuracy.followed_count == 0  # Not followed


def test_bm03_accuracy_metrics_prediction_error(db_with_runs, system_info):
    """Test accuracy metrics calculate prediction error."""
    collector = FeedbackCollector(db_with_runs)

    # Create feedback with prediction error
    feedback = RecommendationFeedback(
        feedback_id="fb_002",
        recommendation_id="rec_002",
        model_id_recommended="model_a",
        model_id_used="model_a",
        device_recommended="cpu",
        device_used="cpu",
        predicted_throughput=100.0,
        actual_throughput=80.0,  # 20% error
        predicted_memory_mb=1000.0,
        actual_memory_mb=1100.0,  # 10% error
        success=True,
        quality_score=None,
        failure_reason=None,
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        system_info=system_info,
    )

    collector.record_feedback(feedback)
    accuracy = collector.get_accuracy_metrics()

    # Should have some prediction error
    assert accuracy.avg_throughput_error_percent > 0
    assert accuracy.avg_memory_error_percent > 0


def test_bm03_accuracy_metrics_filter_by_model(db_with_runs, system_info):
    """Test accuracy metrics filtered by model ID."""
    collector = FeedbackCollector(db_with_runs)

    # Record feedback for two different models
    feedback_a = RecommendationFeedback(
        feedback_id="fb_a",
        recommendation_id="rec_a",
        model_id_recommended="model_a",
        model_id_used="model_a",
        device_recommended="cpu",
        device_used="cpu",
        predicted_throughput=100.0,
        actual_throughput=95.0,
        predicted_memory_mb=1000.0,
        actual_memory_mb=1050.0,
        success=True,
        quality_score=None,
        failure_reason=None,
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        system_info=system_info,
    )

    feedback_b = RecommendationFeedback(
        feedback_id="fb_b",
        recommendation_id="rec_b",
        model_id_recommended="model_b",
        model_id_used="model_b",
        device_recommended="cpu",
        device_used="cpu",
        predicted_throughput=50.0,
        actual_throughput=45.0,
        predicted_memory_mb=500.0,
        actual_memory_mb=525.0,
        success=True,
        quality_score=None,
        failure_reason=None,
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        system_info=system_info,
    )

    collector.record_feedback(feedback_a)
    collector.record_feedback(feedback_b)

    # Get accuracy for model_a only
    accuracy_a = collector.get_accuracy_metrics(model_id="model_a")

    assert accuracy_a.total_recommendations == 1
    assert accuracy_a.followed_count == 1


def test_bm03_get_feedback_history(db_with_runs, system_info):
    """Test getting feedback history."""
    collector = FeedbackCollector(db_with_runs)

    # Record multiple feedbacks
    for i in range(5):
        feedback = RecommendationFeedback(
            feedback_id=f"fb_{i}",
            recommendation_id=f"rec_{i}",
            model_id_recommended="model_a",
            model_id_used="model_a",
            device_recommended="cpu",
            device_used="cpu",
            predicted_throughput=100.0,
            actual_throughput=95.0,
            predicted_memory_mb=1000.0,
            actual_memory_mb=1050.0,
            success=True,
            quality_score=None,
            failure_reason=None,
            timestamp_utc=datetime.utcnow().isoformat() + "Z",
            system_info=system_info,
        )
        collector.record_feedback(feedback)

    history = collector.get_feedback_history(limit=10)

    assert len(history) == 5
    # Should be ordered by recency (most recent first)
    assert history[0].feedback_id == "fb_4"


def test_bm03_adaptive_weight_learner_creates_table(temp_db):
    """Test that AdaptiveWeightLearner creates weights table."""
    learner = AdaptiveWeightLearner(temp_db)

    # Verify table exists
    with temp_db._get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='recommendation_weights'"
        )
        assert cursor.fetchone() is not None


def test_bm03_adaptive_weight_learner_default_weights(temp_db):
    """Test that learner returns default weights initially."""
    learner = AdaptiveWeightLearner(temp_db)

    weights = learner.get_current_weights()

    # Should have default weights
    assert "throughput" in weights
    assert "memory" in weights
    assert "compatibility" in weights
    assert "historical_success" in weights


def test_bm03_adaptive_weight_learner_update_weights(db_with_runs, sample_feedback):
    """Test weight update based on feedback."""
    learner = AdaptiveWeightLearner(db_with_runs, learning_rate=0.1)

    initial_weights = learner.get_current_weights()
    updated_weights = learner.update_weights(sample_feedback)

    # Weights should change (but not drastically with learning_rate=0.1)
    assert updated_weights != initial_weights


def test_bm03_adaptive_weight_learner_weight_bounds(db_with_runs, system_info):
    """Test that weights stay within bounds."""
    learner = AdaptiveWeightLearner(db_with_runs, learning_rate=0.9)

    # Create feedback with large error to trigger significant updates
    feedback = RecommendationFeedback(
        feedback_id="fb_001",
        recommendation_id="rec_001",
        model_id_recommended="model_a",
        model_id_used="model_a",
        device_recommended="cpu",
        device_used="cpu",
        predicted_throughput=100.0,
        actual_throughput=10.0,  # 90% error
        predicted_memory_mb=1000.0,
        actual_memory_mb=10000.0,  # 900% error
        success=False,
        quality_score=None,
        failure_reason="OOM",
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        system_info=system_info,
    )

    # Apply many updates
    for _ in range(10):
        weights = learner.update_weights(feedback)

    # Weights should stay within bounds [0.1, 2.0]
    for weight in weights.values():
        assert 0.1 <= weight <= 2.0


def test_bm03_adaptive_weight_learner_learning_rate_bounds(temp_db):
    """Test that learning rate is clamped to [0, 1]."""
    learner_low = AdaptiveWeightLearner(temp_db, learning_rate=-1.0)
    learner_high = AdaptiveWeightLearner(temp_db, learning_rate=2.0)

    assert learner_low.learning_rate == 0.0
    assert learner_high.learning_rate == 1.0


def test_bm03_adaptive_weight_learner_history(db_with_runs, sample_feedback):
    """Test weight history tracking."""
    learner = AdaptiveWeightLearner(db_with_runs)

    # Update weights multiple times
    for i in range(3):
        learner.update_weights(sample_feedback)

    history = learner.get_weight_history()

    # Should have 3 weight updates
    assert len(history) >= 3

    # Each entry should be (timestamp, weights_dict)
    timestamp, weights = history[0]
    assert isinstance(timestamp, str)
    assert isinstance(weights, dict)


def test_bm03_feedback_success_failure_handling(db_with_runs, system_info):
    """Test handling of successful vs failed recommendations."""
    collector = FeedbackCollector(db_with_runs)

    # Successful feedback
    success_feedback = RecommendationFeedback(
        feedback_id="fb_success",
        recommendation_id="rec_success",
        model_id_recommended="model_a",
        model_id_used="model_a",
        device_recommended="cpu",
        device_used="cpu",
        predicted_throughput=100.0,
        actual_throughput=95.0,
        predicted_memory_mb=1000.0,
        actual_memory_mb=1050.0,
        success=True,
        quality_score=0.95,
        failure_reason=None,
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        system_info=system_info,
    )

    # Failed feedback
    fail_feedback = RecommendationFeedback(
        feedback_id="fb_fail",
        recommendation_id="rec_fail",
        model_id_recommended="model_b",
        model_id_used="model_b",
        device_recommended="cpu",
        device_used="cpu",
        predicted_throughput=100.0,
        actual_throughput=0.0,  # Failed
        predicted_memory_mb=1000.0,
        actual_memory_mb=0.0,
        success=False,
        quality_score=None,
        failure_reason="Out of memory",
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        system_info=system_info,
    )

    collector.record_feedback(success_feedback)
    collector.record_feedback(fail_feedback)

    accuracy = collector.get_accuracy_metrics()

    # Success rate should be 50% (1 success, 1 failure)
    assert accuracy.success_rate == 0.5


def test_bm03_integration_workflow(db_with_runs, system_info):
    """Integration test: full feedback cycle."""
    collector = FeedbackCollector(db_with_runs)
    learner = AdaptiveWeightLearner(db_with_runs)

    # 1. Record initial feedback
    feedback1 = RecommendationFeedback(
        feedback_id="fb_1",
        recommendation_id="rec_1",
        model_id_recommended="model_a",
        model_id_used="model_a",
        device_recommended="cpu",
        device_used="cpu",
        predicted_throughput=100.0,
        actual_throughput=95.0,
        predicted_memory_mb=1000.0,
        actual_memory_mb=1050.0,
        success=True,
        quality_score=0.95,
        failure_reason=None,
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        system_info=system_info,
    )

    collector.record_feedback(feedback1)

    # 2. Update weights based on feedback
    initial_weights = learner.get_current_weights()
    updated_weights = learner.update_weights(feedback1)

    # 3. Get accuracy metrics
    accuracy = collector.get_accuracy_metrics()

    # Verify workflow completed
    assert accuracy.total_recommendations == 1
    assert updated_weights != initial_weights

    # 4. Get feedback history
    history = collector.get_feedback_history()
    assert len(history) == 1

    # 5. Get weight history
    weight_history = learner.get_weight_history()
    assert len(weight_history) >= 1
