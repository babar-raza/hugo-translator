"""Recommendation feedback loop for adaptive learning.

Enables the benchmarking system to learn from recommendation outcomes,
tracking which recommendations were followed, measuring accuracy, and
adapting scoring weights over time.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import logging

from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.system_info import SystemInfo

logger = logging.getLogger(__name__)


@dataclass
class RecommendationFeedback:
    """Feedback record for a recommendation outcome."""

    feedback_id: str
    recommendation_id: str
    model_id_recommended: str
    model_id_used: str  # May differ if user chose differently
    device_recommended: str
    device_used: str
    predicted_throughput: float
    actual_throughput: float
    predicted_memory_mb: float
    actual_memory_mb: float
    success: bool  # True if run completed without errors
    quality_score: Optional[float]  # Translation quality if measured (0-1)
    failure_reason: Optional[str]  # Error message if failed
    timestamp_utc: str
    system_info: SystemInfo


@dataclass
class RecommendationAccuracy:
    """Accuracy metrics for recommendations."""

    total_recommendations: int
    followed_count: int  # How many times users followed the recommendation
    success_rate: float  # Percentage of successful runs
    avg_throughput_error_percent: float  # Average prediction error for throughput
    avg_memory_error_percent: float  # Average prediction error for memory


class FeedbackCollector:
    """Collects and manages recommendation feedback."""

    def __init__(self, db: BenchmarkDatabase):
        """Initialize feedback collector.

        Args:
            db: Benchmark database instance
        """
        self.db = db
        self._ensure_feedback_table()

    def _ensure_feedback_table(self) -> None:
        """Ensure feedback table exists in database.

        Note: Table creation now handled by BenchmarkDatabase schema migrations (v3).
        This method is kept for backward compatibility but is now a no-op.
        """
        # Table is created via migrations in BenchmarkDatabase
        pass

    def record_feedback(self, feedback: RecommendationFeedback) -> None:
        """Record recommendation feedback.

        Args:
            feedback: Feedback data to record

        Raises:
            Exception: If database operation fails
        """
        try:
            with self.db._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO recommendation_feedback (
                        feedback_id, recommendation_id,
                        model_id_recommended, model_id_used,
                        device_recommended, device_used,
                        predicted_throughput, actual_throughput,
                        predicted_memory_mb, actual_memory_mb,
                        success, quality_score, failure_reason,
                        timestamp_utc, system_info_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feedback.feedback_id,
                        feedback.recommendation_id,
                        feedback.model_id_recommended,
                        feedback.model_id_used,
                        feedback.device_recommended,
                        feedback.device_used,
                        feedback.predicted_throughput,
                        feedback.actual_throughput,
                        feedback.predicted_memory_mb,
                        feedback.actual_memory_mb,
                        1 if feedback.success else 0,
                        feedback.quality_score,
                        feedback.failure_reason,
                        feedback.timestamp_utc,
                        feedback.system_info.to_json(),
                    ),
                )
                conn.commit()

            logger.info(f"Recorded feedback {feedback.feedback_id} for recommendation {feedback.recommendation_id}")

        except Exception as e:
            logger.error(f"Failed to record feedback: {e}", exc_info=True)
            raise

    def get_feedback_for_recommendation(
        self, recommendation_id: str
    ) -> Optional[RecommendationFeedback]:
        """Get feedback for a specific recommendation.

        Args:
            recommendation_id: Recommendation ID to query

        Returns:
            RecommendationFeedback if found, None otherwise
        """
        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT feedback_id, recommendation_id,
                           model_id_recommended, model_id_used,
                           device_recommended, device_used,
                           predicted_throughput, actual_throughput,
                           predicted_memory_mb, actual_memory_mb,
                           success, quality_score, failure_reason,
                           timestamp_utc, system_info_json
                    FROM recommendation_feedback
                    WHERE recommendation_id = ?
                    ORDER BY timestamp_utc DESC
                    LIMIT 1
                    """,
                    (recommendation_id,),
                )

                row = cursor.fetchone()
                if not row:
                    return None

                return RecommendationFeedback(
                    feedback_id=row[0],
                    recommendation_id=row[1],
                    model_id_recommended=row[2],
                    model_id_used=row[3],
                    device_recommended=row[4],
                    device_used=row[5],
                    predicted_throughput=row[6],
                    actual_throughput=row[7],
                    predicted_memory_mb=row[8],
                    actual_memory_mb=row[9],
                    success=bool(row[10]),
                    quality_score=row[11],
                    failure_reason=row[12],
                    timestamp_utc=row[13],
                    system_info=SystemInfo.from_json(row[14]),
                )

        except Exception as e:
            logger.error(f"Failed to get feedback: {e}")
            return None

    def get_accuracy_metrics(
        self, model_id: Optional[str] = None
    ) -> RecommendationAccuracy:
        """Calculate accuracy metrics for recommendations.

        Args:
            model_id: Optional filter by model ID

        Returns:
            RecommendationAccuracy with aggregate metrics
        """
        try:
            with self.db._get_connection() as conn:
                # Build query
                where_clause = ""
                params = []
                if model_id:
                    where_clause = "WHERE model_id_recommended = ?"
                    params = [model_id]

                # Count totals
                cursor = conn.execute(
                    f"SELECT COUNT(*) FROM recommendation_feedback {where_clause}",
                    params,
                )
                total = cursor.fetchone()[0]

                if total == 0:
                    return RecommendationAccuracy(
                        total_recommendations=0,
                        followed_count=0,
                        success_rate=0.0,
                        avg_throughput_error_percent=0.0,
                        avg_memory_error_percent=0.0,
                    )

                # Count followed recommendations
                cursor = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM recommendation_feedback
                    {where_clause}
                    {'AND' if where_clause else 'WHERE'} model_id_recommended = model_id_used
                    AND device_recommended = device_used
                    """,
                    params,
                )
                followed = cursor.fetchone()[0]

                # Calculate success rate
                cursor = conn.execute(
                    f"SELECT AVG(success) FROM recommendation_feedback {where_clause}",
                    params,
                )
                success_rate = cursor.fetchone()[0] or 0.0

                # Calculate throughput error (only for successful runs)
                cursor = conn.execute(
                    f"""
                    SELECT AVG(ABS((predicted_throughput - actual_throughput) / actual_throughput * 100))
                    FROM recommendation_feedback
                    {where_clause}
                    {'AND' if where_clause else 'WHERE'} success = 1 AND actual_throughput > 0
                    """,
                    params,
                )
                throughput_error = cursor.fetchone()[0] or 0.0

                # Calculate memory error (only for successful runs)
                cursor = conn.execute(
                    f"""
                    SELECT AVG(ABS((predicted_memory_mb - actual_memory_mb) / actual_memory_mb * 100))
                    FROM recommendation_feedback
                    {where_clause}
                    {'AND' if where_clause else 'WHERE'} success = 1 AND actual_memory_mb > 0
                    """,
                    params,
                )
                memory_error = cursor.fetchone()[0] or 0.0

                return RecommendationAccuracy(
                    total_recommendations=total,
                    followed_count=followed,
                    success_rate=success_rate,
                    avg_throughput_error_percent=throughput_error,
                    avg_memory_error_percent=memory_error,
                )

        except Exception as e:
            logger.error(f"Failed to get accuracy metrics: {e}")
            return RecommendationAccuracy(
                total_recommendations=0,
                followed_count=0,
                success_rate=0.0,
                avg_throughput_error_percent=0.0,
                avg_memory_error_percent=0.0,
            )

    def get_feedback_history(self, limit: int = 100) -> List[RecommendationFeedback]:
        """Get recent feedback history.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of RecommendationFeedback ordered by recency
        """
        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT feedback_id, recommendation_id,
                           model_id_recommended, model_id_used,
                           device_recommended, device_used,
                           predicted_throughput, actual_throughput,
                           predicted_memory_mb, actual_memory_mb,
                           success, quality_score, failure_reason,
                           timestamp_utc, system_info_json
                    FROM recommendation_feedback
                    ORDER BY timestamp_utc DESC
                    LIMIT ?
                    """,
                    (limit,),
                )

                feedbacks = []
                for row in cursor.fetchall():
                    feedbacks.append(
                        RecommendationFeedback(
                            feedback_id=row[0],
                            recommendation_id=row[1],
                            model_id_recommended=row[2],
                            model_id_used=row[3],
                            device_recommended=row[4],
                            device_used=row[5],
                            predicted_throughput=row[6],
                            actual_throughput=row[7],
                            predicted_memory_mb=row[8],
                            actual_memory_mb=row[9],
                            success=bool(row[10]),
                            quality_score=row[11],
                            failure_reason=row[12],
                            timestamp_utc=row[13],
                            system_info=SystemInfo.from_json(row[14]),
                        )
                    )

                return feedbacks

        except Exception as e:
            logger.error(f"Failed to get feedback history: {e}")
            return []


class AdaptiveWeightLearner:
    """Learns and adapts recommendation scoring weights from feedback."""

    def __init__(self, db: BenchmarkDatabase, learning_rate: float = 0.1):
        """Initialize adaptive weight learner.

        Args:
            db: Benchmark database instance
            learning_rate: Learning rate for weight updates (0-1)
        """
        self.db = db
        self.learning_rate = max(0.0, min(1.0, learning_rate))  # Clamp to [0, 1]
        self._ensure_weights_table()

    def _ensure_weights_table(self) -> None:
        """Ensure weights table exists in database.

        Note: Table creation now handled by BenchmarkDatabase schema migrations (v4).
        This method is kept for backward compatibility but is now a no-op.
        """
        # Table is created via migrations in BenchmarkDatabase
        pass

    def update_weights(
        self, feedback: RecommendationFeedback
    ) -> Dict[str, float]:
        """Update weights based on feedback.

        Uses gradient descent-like update:
        - Increase weight for factors that led to accurate predictions
        - Decrease weight for factors that led to poor predictions

        Args:
            feedback: Feedback to learn from

        Returns:
            Updated weights dictionary
        """
        try:
            # Get current weights
            current_weights = self.get_current_weights()

            # Calculate prediction errors
            throughput_error = abs(
                (feedback.predicted_throughput - feedback.actual_throughput)
                / feedback.actual_throughput
            ) if feedback.actual_throughput > 0 else 0.0

            memory_error = abs(
                (feedback.predicted_memory_mb - feedback.actual_memory_mb)
                / feedback.actual_memory_mb
            ) if feedback.actual_memory_mb > 0 else 0.0

            # Combined error (0 = perfect, 1+ = bad)
            combined_error = (throughput_error + memory_error) / 2

            # Determine update direction
            # If error is low, this was a good recommendation -> reinforce
            # If error is high, this was a poor recommendation -> adjust
            if feedback.success and combined_error < 0.2:
                # Good prediction - slight increase in confidence
                adjustment = 1.0 + (self.learning_rate * 0.1)
            elif combined_error > 0.5:
                # Poor prediction - reduce confidence
                adjustment = 1.0 - (self.learning_rate * 0.2)
            else:
                # Neutral - no change
                adjustment = 1.0

            # Update weights with bounds [0.1, 2.0]
            updated_weights = {}
            for key, value in current_weights.items():
                new_value = value * adjustment
                updated_weights[key] = max(0.1, min(2.0, new_value))

            # Normalize weights to sum to original total
            total = sum(current_weights.values())
            updated_total = sum(updated_weights.values())
            if updated_total > 0:
                normalization = total / updated_total
                updated_weights = {k: v * normalization for k, v in updated_weights.items()}

            # Store updated weights
            self._store_weights(updated_weights)

            logger.info(f"Updated weights based on feedback {feedback.feedback_id}")
            return updated_weights

        except Exception as e:
            logger.error(f"Failed to update weights: {e}")
            return self.get_current_weights()

    def get_current_weights(self) -> Dict[str, float]:
        """Get current recommendation weights.

        Returns:
            Dictionary of weight names to values
        """
        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT weights_json FROM recommendation_weights
                    ORDER BY timestamp_utc DESC
                    LIMIT 1
                    """
                )

                row = cursor.fetchone()
                if row:
                    import json
                    return json.loads(row[0])

        except Exception as e:
            logger.error(f"Failed to get current weights: {e}")

        # Return default weights if none found
        return {
            "throughput": 1.0,
            "memory": 0.8,
            "compatibility": 0.6,
            "historical_success": 0.4,
        }

    def _store_weights(self, weights: Dict[str, float]) -> None:
        """Store weights to database."""
        try:
            import json

            weight_id = str(uuid.uuid4())
            timestamp = datetime.utcnow().isoformat() + "Z"

            with self.db._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO recommendation_weights (weight_id, timestamp_utc, weights_json)
                    VALUES (?, ?, ?)
                    """,
                    (weight_id, timestamp, json.dumps(weights)),
                )
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to store weights: {e}")

    def get_weight_history(self) -> List[tuple[str, Dict[str, float]]]:
        """Get historical weight updates.

        Returns:
            List of (timestamp, weights) tuples
        """
        try:
            import json

            with self.db._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT timestamp_utc, weights_json
                    FROM recommendation_weights
                    ORDER BY timestamp_utc DESC
                    LIMIT 100
                    """
                )

                history = []
                for row in cursor.fetchall():
                    history.append((row[0], json.loads(row[1])))

                return history

        except Exception as e:
            logger.error(f"Failed to get weight history: {e}")
            return []
