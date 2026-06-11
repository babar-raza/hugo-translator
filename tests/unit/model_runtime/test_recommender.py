"""
Unit tests for ModelRecommender.

Tests cover:
- Benchmark-backed recommendations
- Fallback heuristics
- Constraint handling (memory, throughput, device)
- Error cases (no models fit, missing benchmarks)
- Confidence scoring
"""

from unittest.mock import MagicMock

import pytest

from src.benchmarking.storage import BenchmarkResult, BenchmarkRun, SystemInfo
from src.model_runtime.hardware import HardwareDetector, HardwareInfo
from src.model_runtime.recommender import ModelRecommender
from src.model_runtime.registry import ModelInfo, ModelRegistry


@pytest.fixture
def mock_registry():
    """Create mock registry with test models."""
    registry = MagicMock(spec=ModelRegistry)

    # Define test models
    models = {
        "m2m100_418m": ModelInfo(
            model_id="m2m100_418m",
            name="M2M100 418M",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=1600,
            min_ram_gb=2.0,
            optimal_device="cuda",
            parameters=418_000_000,
        ),
        "m2m100_418m_ct2": ModelInfo(
            model_id="m2m100_418m_ct2",
            name="M2M100 418M CT2",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=800,
            min_ram_gb=1.0,
            optimal_device="cpu",
            parameters=418_000_000,
        ),
        "m2m100_418m_ct2_int8": ModelInfo(
            model_id="m2m100_418m_ct2_int8",
            name="M2M100 418M CT2 INT8",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=400,
            min_ram_gb=0.5,
            optimal_device="cpu",
            parameters=418_000_000,
        ),
        "nllb_200_600m": ModelInfo(
            model_id="nllb_200_600m",
            name="NLLB-200 600M",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=2400,
            min_ram_gb=3.0,
            optimal_device="cuda",
            parameters=600_000_000,
        ),
    }

    registry.models = models
    registry.get_model.side_effect = lambda model_id: models[model_id]

    return registry


@pytest.fixture
def mock_hardware():
    """Create mock hardware detector."""
    detector = MagicMock(spec=HardwareDetector)
    detector.detect.return_value = HardwareInfo(
        cpu_count=8,
        total_ram_gb=16.0,
        has_cuda=False,
        cuda_devices=[],
        has_mps=False,
        recommended_device="cpu",
        platform="test",
        python_version="3.10",
    )
    return detector


@pytest.fixture
def mock_benchmark_storage():
    """Create mock benchmark storage with test data."""
    storage = MagicMock()

    # Mock runs for different models
    runs = [
        ("run1", "m2m100_418m_ct2_int8", "cpu", "2025-12-19T10:00:00", 10),
        ("run2", "m2m100_418m_ct2", "cpu", "2025-12-19T09:00:00", 10),
        ("run3", "m2m100_418m", "cuda", "2025-12-19T08:00:00", 10),
    ]
    storage.list_runs.return_value = runs

    # Mock detailed run data
    def get_run(run_id):
        if run_id == "run1":
            return BenchmarkRun(
                run_id="run1",
                model_id="m2m100_418m_ct2_int8",
                device="cpu",
                batch_sizes=[4],
                iterations=10,
                corpus_category="test",
                purpose="benchmark",
                tags=["cpu", "int8"],
                system_info=SystemInfo(
                    cpu_model="Test CPU",
                    cpu_cores=8,
                    total_ram_gb=16.0,
                ),
                results=[
                    BenchmarkResult(
                        sample_id=f"sample_{i}",
                        model_id="m2m100_418m_ct2_int8",
                        device="cpu",
                        batch_size=4,
                        duration_seconds=0.5,
                        tokens_input=100,
                        tokens_output=100,
                        throughput_tokens_per_sec=20.0,
                        peak_memory_mb=300.0,
                    )
                    for i in range(10)
                ],
                total_duration_seconds=5.0,
            )
        elif run_id == "run2":
            return BenchmarkRun(
                run_id="run2",
                model_id="m2m100_418m_ct2",
                device="cpu",
                batch_sizes=[4],
                iterations=10,
                corpus_category="test",
                purpose="benchmark",
                tags=["cpu"],
                system_info=SystemInfo(
                    cpu_model="Test CPU",
                    cpu_cores=8,
                    total_ram_gb=16.0,
                ),
                results=[
                    BenchmarkResult(
                        sample_id=f"sample_{i}",
                        model_id="m2m100_418m_ct2",
                        device="cpu",
                        batch_size=4,
                        duration_seconds=0.6,
                        tokens_input=100,
                        tokens_output=100,
                        throughput_tokens_per_sec=15.0,
                        peak_memory_mb=600.0,
                    )
                    for i in range(10)
                ],
                total_duration_seconds=6.0,
            )
        return None

    storage.get_run.side_effect = get_run

    return storage


class TestModelRecommenderBenchmarks:
    """Test benchmark-backed recommendations."""

    def test_recommend_from_benchmarks_highest_throughput(
        self, mock_registry, mock_hardware, mock_benchmark_storage
    ):
        """Test that benchmark recommendation selects highest throughput model."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=mock_benchmark_storage,
            hardware_detector=mock_hardware,
        )

        recommendation = recommender.recommend(device_preference="cpu")

        # Should select INT8 model (20 tokens/sec > 15 tokens/sec)
        assert recommendation.model_id == "m2m100_418m_ct2_int8"
        assert recommendation.backend == "ctranslate2"
        assert recommendation.device == "cpu"
        assert recommendation.confidence == "high"
        assert recommendation.expected_throughput == 20.0
        assert "benchmark run" in recommendation.rationale.lower()

    def test_recommend_from_benchmarks_memory_constraint(
        self, mock_registry, mock_hardware, mock_benchmark_storage
    ):
        """Test that benchmark recommendation respects memory constraint."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=mock_benchmark_storage,
            hardware_detector=mock_hardware,
        )

        # Memory constraint filters out 600MB model
        recommendation = recommender.recommend(
            device_preference="cpu",
            max_memory_gb=0.4,  # 400MB
        )

        assert recommendation.model_id == "m2m100_418m_ct2_int8"
        assert recommendation.expected_memory_mb == 300.0

    def test_recommend_from_benchmarks_throughput_constraint(
        self, mock_registry, mock_hardware, mock_benchmark_storage
    ):
        """Test that benchmark recommendation filters by throughput target."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=mock_benchmark_storage,
            hardware_detector=mock_hardware,
        )

        # Only INT8 model meets 18 tokens/sec target
        recommendation = recommender.recommend(device_preference="cpu", target_throughput=18.0)

        assert recommendation.model_id == "m2m100_418m_ct2_int8"
        assert recommendation.expected_throughput >= 18.0

    def test_recommend_from_benchmarks_no_match_falls_back(
        self, mock_registry, mock_hardware, mock_benchmark_storage
    ):
        """Test fallback to heuristics when no benchmarks match constraints."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=mock_benchmark_storage,
            hardware_detector=mock_hardware,
        )

        # Impossible throughput requirement forces heuristic fallback
        recommendation = recommender.recommend(device_preference="cpu", target_throughput=1000.0)

        # Should use heuristics (confidence = medium)
        assert recommendation.confidence in ["medium", "low"]
        assert "heuristic" in recommendation.rationale.lower()


class TestModelRecommenderHeuristics:
    """Test fallback heuristic recommendations."""

    def test_recommend_heuristic_prefers_ct2_int8_on_cpu(self, mock_registry, mock_hardware):
        """Test that heuristics prefer CT2 INT8 models on CPU."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=None,  # No benchmarks
            hardware_detector=mock_hardware,
        )

        recommendation = recommender.recommend(device_preference="cpu")

        # Should select CT2 INT8 model
        assert recommendation.model_id == "m2m100_418m_ct2_int8"
        assert recommendation.backend == "ctranslate2"
        assert "int8" in recommendation.model_id.lower()
        assert recommendation.confidence == "medium"
        assert "heuristic" in recommendation.rationale.lower()

    def test_recommend_heuristic_respects_memory_constraint(self, mock_registry, mock_hardware):
        """Test that heuristics respect memory constraints."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=None,
            hardware_detector=mock_hardware,
        )

        # 1GB constraint filters out all but INT8 model
        recommendation = recommender.recommend(device_preference="cpu", max_memory_gb=1.0)

        assert recommendation.model_id == "m2m100_418m_ct2_int8"
        assert recommendation.expected_memory_mb <= 1024

    def test_recommend_heuristic_no_models_fit_memory(self, mock_registry, mock_hardware):
        """Test error handling when no models fit memory constraint."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=None,
            hardware_detector=mock_hardware,
        )

        # 100MB constraint too small for any model
        with pytest.raises(ValueError, match="No models fit memory constraint"):
            recommender.recommend(device_preference="cpu", max_memory_gb=0.1)

    def test_recommend_heuristic_throughput_warning(self, mock_registry, mock_hardware):
        """Test that heuristics warn when throughput target may not be met."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=None,
            hardware_detector=mock_hardware,
        )

        # High throughput target (heuristic estimates ~20-30 tokens/sec)
        recommendation = recommender.recommend(device_preference="cpu", target_throughput=100.0)

        # Should return recommendation with low confidence
        assert recommendation.confidence == "low"
        assert "may not meet target" in recommendation.rationale.lower()

    def test_recommend_heuristic_device_compatibility(self, mock_registry, mock_hardware):
        """Test that heuristics consider device compatibility."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=None,
            hardware_detector=mock_hardware,
        )

        # CPU preference should favor cpu-optimal models
        cpu_rec = recommender.recommend(device_preference="cpu")
        assert cpu_rec.model_id == "m2m100_418m_ct2_int8"
        assert cpu_rec.device == "cpu"


class TestModelRecommenderEdgeCases:
    """Test edge cases and error handling."""

    def test_recommend_with_empty_registry(self, mock_hardware):
        """Test error handling with empty registry."""
        empty_registry = MagicMock(spec=ModelRegistry)
        empty_registry.models = {}

        recommender = ModelRecommender(
            registry=empty_registry,
            benchmark_storage=None,
            hardware_detector=mock_hardware,
        )

        with pytest.raises(ValueError, match="No suitable models found"):
            recommender.recommend(device_preference="cpu")

    def test_recommend_with_benchmark_error(
        self, mock_registry, mock_hardware, mock_benchmark_storage
    ):
        """Test fallback to heuristics when benchmark query fails."""
        # Make benchmark storage raise exception
        mock_benchmark_storage.list_runs.side_effect = Exception("Database error")

        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=mock_benchmark_storage,
            hardware_detector=mock_hardware,
        )

        # Should fall back to heuristics
        recommendation = recommender.recommend(device_preference="cpu")

        assert recommendation.confidence == "medium"
        assert "heuristic" in recommendation.rationale.lower()

    def test_recommend_auto_detects_device(self, mock_registry, mock_hardware):
        """Test that recommender auto-detects device when not specified."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=None,
            hardware_detector=mock_hardware,
        )

        recommendation = recommender.recommend()

        # Should use hardware detector's recommended device (cpu)
        assert recommendation.device == "cpu"

    def test_recommendation_to_dict(self, mock_registry, mock_hardware):
        """Test ModelRecommendation.to_dict() serialization."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=None,
            hardware_detector=mock_hardware,
        )

        recommendation = recommender.recommend(device_preference="cpu")
        data = recommendation.to_dict()

        # Verify all required fields present
        assert "model_id" in data
        assert "backend" in data
        assert "device" in data
        assert "expected_throughput" in data
        assert "expected_memory_mb" in data
        assert "confidence" in data
        assert "rationale" in data

        # Should be JSON-serializable
        import json

        json_str = json.dumps(data)
        assert len(json_str) > 0


class TestModelRecommenderBenchmarkStorage:
    """Test integration with BenchmarkStorage."""

    def test_benchmark_storage_optional(self, mock_registry, mock_hardware):
        """Test that benchmark storage is optional."""
        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=None,  # Explicitly None
            hardware_detector=mock_hardware,
        )

        # Should work fine with just heuristics
        recommendation = recommender.recommend(device_preference="cpu")
        assert recommendation.model_id is not None

    def test_benchmark_storage_no_runs_for_device(
        self, mock_registry, mock_hardware, mock_benchmark_storage
    ):
        """Test handling when benchmark has no runs for requested device."""
        # Mock empty results for GPU
        mock_benchmark_storage.list_runs.return_value = []

        recommender = ModelRecommender(
            registry=mock_registry,
            benchmark_storage=mock_benchmark_storage,
            hardware_detector=mock_hardware,
        )

        # Should fall back to heuristics
        recommendation = recommender.recommend(device_preference="cuda")

        assert recommendation.confidence == "medium"
        assert "heuristic" in recommendation.rationale.lower()
