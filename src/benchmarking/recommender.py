"""Model recommendation system for benchmarking.

Recommends optimal model configurations based on hardware and requirements.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.benchmarking.feedback import AdaptiveWeightLearner, RecommendationFeedback
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.system_info import SystemInfo

logger = logging.getLogger(__name__)


@dataclass
class ModelRecommendation:
    """Recommendation for model configuration."""

    recommendation_id: str
    model_id: str
    device: str
    batch_size: int
    predicted_throughput: float
    predicted_memory_mb: float
    confidence_score: float  # 0-1, higher is better
    reasoning: str  # Explanation of why this was recommended


class ModelRecommender:
    """Recommends optimal model configurations based on system and requirements."""

    def __init__(self, db: BenchmarkDatabase, learning_rate: float = 0.1):
        """Initialize model recommender.

        Args:
            db: Benchmark database instance
            learning_rate: Learning rate for adaptive weight updates (0-1)
        """
        self.db = db
        self.weight_learner = AdaptiveWeightLearner(db, learning_rate)
        self._active_recommendations: Dict[str, ModelRecommendation] = {}

    def recommend(
        self,
        system_info: SystemInfo,
        requirements: Optional[Dict[str, any]] = None,
    ) -> ModelRecommendation:
        """Generate a model recommendation based on system and requirements.

        Args:
            system_info: Current system hardware information
            requirements: Optional requirements dict with keys:
                - max_memory_mb: Maximum memory constraint
                - min_throughput: Minimum throughput requirement
                - prefer_quality: Prefer quality over speed (bool)

        Returns:
            ModelRecommendation with best config for this system
        """
        requirements = requirements or {}

        # Get current weights
        weights = self.weight_learner.get_current_weights()

        # Query similar benchmark runs
        runs = self._find_similar_runs(system_info)

        if not runs:
            # No historical data - use conservative defaults
            return self._default_recommendation(system_info, requirements)

        # Score each run based on weighted criteria
        scored_runs = []
        for run in runs:
            score = self._calculate_score(run, weights, requirements)
            scored_runs.append((score, run))

        # Sort by score (descending)
        scored_runs.sort(key=lambda x: x[0], reverse=True)

        # Take best run
        best_score, best_run = scored_runs[0]

        # Extract recommendation
        recommendation = ModelRecommendation(
            recommendation_id=f"rec_{best_run.run_id}",
            model_id=best_run.model_id,
            device=best_run.device,
            batch_size=best_run.batch_sizes[0] if best_run.batch_sizes else 8,
            predicted_throughput=self._estimate_throughput(best_run),
            predicted_memory_mb=self._estimate_memory(best_run),
            confidence_score=min(1.0, best_score / 10.0),  # Normalize to 0-1
            reasoning=self._generate_reasoning(best_run, best_score, weights),
        )

        # Track recommendation
        self._active_recommendations[recommendation.recommendation_id] = recommendation

        logger.info(
            f"Generated recommendation: {recommendation.model_id} on {recommendation.device} "
            f"(confidence: {recommendation.confidence_score:.2f})"
        )

        return recommendation

    def record_outcome(self, feedback: RecommendationFeedback) -> None:
        """Record the outcome of a recommendation to improve future suggestions.

        Args:
            feedback: Feedback data including actual vs predicted performance

        Raises:
            ValueError: If feedback data is invalid
        """
        # Validate feedback
        if feedback.recommendation_id not in self._active_recommendations:
            logger.warning(f"Unknown recommendation_id: {feedback.recommendation_id}")
            # Still update weights, just log warning
            # return

        # Update weights via learner
        new_weights = self.weight_learner.update_weights(feedback)

        logger.info(
            f"Updated weights based on feedback: {feedback.recommendation_id} "
            f"(throughput error: {abs(feedback.predicted_throughput - feedback.actual_throughput):.1f}, "
            f"memory error: {abs(feedback.predicted_memory_mb - feedback.actual_memory_mb):.1f})"
        )

        # Remove from active tracking
        if feedback.recommendation_id in self._active_recommendations:
            del self._active_recommendations[feedback.recommendation_id]

    def get_oom_safe_batch_size(
        self,
        device: str,
        max_memory_mb: Optional[float] = None,
        safety_margin: float = 0.20,
        min_samples: int = 3
    ) -> Dict[str, any]:
        """Recommend OOM-safe batch size based on historical peak memory.

        Args:
            device: Device string ('cuda', 'cuda:0', etc.)
            max_memory_mb: Maximum GPU memory in MB (auto-detect if None)
            safety_margin: Safety buffer (0.20 = keep 20% free)
            min_samples: Minimum historical samples required for confidence

        Returns:
            {
                'recommended_batch_size': int,
                'estimated_peak_mb': float,
                'safety_margin_pct': float,
                'confidence_samples': int,
                'max_memory_mb': float,
                'warning': Optional[str]  # If insufficient data
            }
        """
        if not device.startswith('cuda'):
            logger.warning(f"OOM-safe recommendations only for CUDA devices, got: {device}")
            return {
                'recommended_batch_size': 8,
                'estimated_peak_mb': 0.0,
                'safety_margin_pct': safety_margin * 100,
                'confidence_samples': 0,
                'max_memory_mb': 0.0,
                'warning': f'Not a CUDA device: {device}'
            }

        # Auto-detect GPU memory if not provided
        if max_memory_mb is None:
            max_memory_mb = self._detect_gpu_memory(device)
            if max_memory_mb is None:
                logger.error("Could not detect GPU memory and none provided")
                return self._conservative_fallback(device, 8192.0, safety_margin)

        # Calculate safe memory limit (with safety margin)
        safe_limit_mb = max_memory_mb * (1.0 - safety_margin)

        # Query historical peak memory data grouped by batch size
        conn = self.db.get_connection()
        cursor = conn.execute("""
            SELECT
                batch_size,
                AVG(peak_memory_mb) as avg_peak_mb,
                MAX(peak_memory_mb) as max_peak_mb,
                COUNT(*) as sample_count
            FROM benchmark_results
            WHERE device = ?
              AND peak_memory_mb IS NOT NULL
              AND errors = '[]'
            GROUP BY batch_size
            HAVING sample_count >= ?
            ORDER BY batch_size DESC
        """, (device, min_samples))

        results = cursor.fetchall()
        if not results:
            logger.warning(f"No historical GPU memory data for device {device}")
            return self._conservative_fallback(device, max_memory_mb, safety_margin)

        # Find largest batch size that stays under safe limit
        for row in results:
            batch_size = row[0]
            avg_peak_mb = row[1]
            max_peak_mb = row[2]
            sample_count = row[3]

            # Use max observed (conservative) rather than average
            if max_peak_mb <= safe_limit_mb:
                logger.info(
                    f"Recommended batch_size={batch_size} "
                    f"(peak {max_peak_mb:.0f}MB / {max_memory_mb:.0f}MB = "
                    f"{max_peak_mb/max_memory_mb*100:.1f}% utilization, "
                    f"{safety_margin*100:.0f}% safety margin)"
                )
                return {
                    'recommended_batch_size': batch_size,
                    'estimated_peak_mb': max_peak_mb,
                    'average_peak_mb': avg_peak_mb,
                    'safety_margin_pct': safety_margin * 100,
                    'confidence_samples': sample_count,
                    'max_memory_mb': max_memory_mb
                }

        # No safe batch size found - even smallest batch too large
        smallest = results[-1]
        logger.warning(
            f"No safe batch size found. Even batch_size={smallest[0]} "
            f"uses {smallest[2]:.0f}MB (limit: {safe_limit_mb:.0f}MB)"
        )
        return {
            'recommended_batch_size': 1,
            'estimated_peak_mb': smallest[2],
            'safety_margin_pct': safety_margin * 100,
            'confidence_samples': 0,
            'max_memory_mb': max_memory_mb,
            'warning': 'Insufficient GPU memory - consider smaller model or CPU'
        }

    def _detect_gpu_memory(self, device: str) -> Optional[float]:
        """Auto-detect total GPU memory in MB.

        Args:
            device: Device string ('cuda', 'cuda:0', etc.)

        Returns:
            Total GPU memory in MB, or None if detection fails
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return None

            device_id = 0
            if ':' in device:
                device_id = int(device.split(':')[1])

            props = torch.cuda.get_device_properties(device_id)
            return props.total_memory / (1024 ** 2)  # bytes to MB
        except Exception as e:
            logger.error(f"Failed to detect GPU memory: {e}")
            return None

    def _conservative_fallback(
        self, device: str, max_memory_mb: float, safety_margin: float
    ) -> Dict[str, any]:
        """Ultra-conservative fallback when no safe batch size found.

        Args:
            device: Device string
            max_memory_mb: Maximum memory in MB
            safety_margin: Safety margin (0-1)

        Returns:
            Conservative recommendation dict
        """
        return {
            'recommended_batch_size': 1,
            'estimated_peak_mb': max_memory_mb * 0.5,
            'safety_margin_pct': safety_margin * 100,
            'confidence_samples': 0,
            'max_memory_mb': max_memory_mb,
            'warning': 'No historical data within memory limit - using conservative defaults'
        }

    def _find_similar_runs(self, system_info: SystemInfo) -> List:
        """Find benchmark runs from similar systems.

        Args:
            system_info: System to match against

        Returns:
            List of similar BenchmarkRun objects
        """
        # Query runs with similar CPU cores and RAM
        # Tolerate +/- 2 cores and +/- 4GB RAM
        all_runs = self.db.list_runs(limit=100)

        similar_runs = []
        for run_id, model_id, device, timestamp, result_count in all_runs:
            run = self.db.get_run(run_id)
            if run and run.system_info:
                cpu_diff = abs(run.system_info.cpu_cores - system_info.cpu_cores)
                ram_diff = abs(run.system_info.total_ram_gb - system_info.total_ram_gb)

                # Similarity threshold
                if cpu_diff <= 2 and ram_diff <= 4.0:
                    similar_runs.append(run)

        logger.debug(f"Found {len(similar_runs)} similar benchmark runs")
        return similar_runs

    def _calculate_score(
        self, run, weights: Dict[str, float], requirements: Dict[str, any]
    ) -> float:
        """Calculate weighted score for a benchmark run.

        Args:
            run: BenchmarkRun to score
            weights: Feature weights from learner
            requirements: User requirements

        Returns:
            Score (higher is better)
        """
        score = 0.0

        # Throughput component
        if run.results:
            avg_throughput = sum(r.throughput_tokens_per_sec for r in run.results) / len(
                run.results
            )
            score += avg_throughput * weights.get("throughput", 1.0)

        # Memory component (inverse - lower is better)
        if run.results:
            max_memory = max(
                (r.peak_memory_mb for r in run.results if r.peak_memory_mb), default=0
            )
            if max_memory > 0:
                # Penalize high memory usage
                memory_score = 10000.0 / max_memory  # Inverse
                score += memory_score * weights.get("memory", 0.8)

        # Success rate component
        if run.results:
            success_rate = sum(1 for r in run.results if not r.errors) / len(run.results)
            score += success_rate * 100 * weights.get("historical_success", 0.4)

        # Requirements adherence
        if requirements.get("max_memory_mb") and run.results:
            max_memory = max(
                (r.peak_memory_mb for r in run.results if r.peak_memory_mb), default=0
            )
            if max_memory > requirements["max_memory_mb"]:
                score *= 0.5  # Heavy penalty for violating memory constraint

        return score

    def _estimate_throughput(self, run) -> float:
        """Estimate throughput from benchmark run.

        Args:
            run: BenchmarkRun

        Returns:
            Estimated throughput in tokens/sec
        """
        if not run.results:
            return 0.0

        return sum(r.throughput_tokens_per_sec for r in run.results) / len(run.results)

    def _estimate_memory(self, run) -> float:
        """Estimate memory usage from benchmark run.

        Args:
            run: BenchmarkRun

        Returns:
            Estimated peak memory in MB
        """
        if not run.results:
            return 0.0

        return max((r.peak_memory_mb for r in run.results if r.peak_memory_mb), default=0.0)

    def _generate_reasoning(
        self, run, score: float, weights: Dict[str, float]
    ) -> str:
        """Generate human-readable reasoning for recommendation.

        Args:
            run: Recommended BenchmarkRun
            score: Calculated score
            weights: Current feature weights

        Returns:
            Reasoning string
        """
        reasons = []

        if run.results:
            avg_throughput = self._estimate_throughput(run)
            reasons.append(f"avg throughput {avg_throughput:.1f} tokens/sec")

            max_memory = self._estimate_memory(run)
            reasons.append(f"peak memory {max_memory:.0f}MB")

        reasons.append(f"similarity score {score:.1f}")

        return f"Recommended based on: {', '.join(reasons)}"

    def _default_recommendation(
        self, system_info: SystemInfo, requirements: Dict[str, any]
    ) -> ModelRecommendation:
        """Generate default recommendation when no historical data available.

        Args:
            system_info: System information
            requirements: User requirements

        Returns:
            Conservative default recommendation
        """
        # Conservative defaults based on CPU cores
        if system_info.cpu_cores <= 4:
            batch_size = 4
            model_id = "facebook/m2m100_418M"  # Smallest model
        elif system_info.cpu_cores <= 8:
            batch_size = 8
            model_id = "facebook/m2m100_418M"
        else:
            batch_size = 16
            model_id = "facebook/m2m100_1.2B"  # Medium model

        # Prefer CPU for safety on first run
        device = "cpu"

        recommendation = ModelRecommendation(
            recommendation_id="rec_default",
            model_id=model_id,
            device=device,
            batch_size=batch_size,
            predicted_throughput=10.0,  # Conservative estimate
            predicted_memory_mb=2000.0,  # Conservative estimate
            confidence_score=0.3,  # Low confidence - no historical data
            reasoning="Default recommendation (no historical benchmarks found)",
        )

        logger.info(
            f"Generated default recommendation: {model_id} on {device} "
            f"(no historical data available)"
        )

        return recommendation
