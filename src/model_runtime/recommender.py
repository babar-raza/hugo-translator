"""
Model Recommendation Engine for intelligent model selection.

Recommends translation models based on:
- Historical benchmark data (when available)
- Hardware constraints (RAM, CPU/GPU)
- Target throughput requirements
- Fallback to registry heuristics
"""
import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from .hardware import HardwareDetector, HardwareInfo
from .registry import ModelRegistry

logger = logging.getLogger(__name__)


@dataclass
class ModelRecommendation:
    """Model recommendation with expected performance."""

    model_id: str
    backend: str
    device: str
    expected_throughput: Optional[float]  # tokens/sec
    expected_memory_mb: Optional[float]  # MB
    confidence: Literal["high", "medium", "low"]
    rationale: str  # Explanation of why this model was chosen

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "model_id": self.model_id,
            "backend": self.backend,
            "device": self.device,
            "expected_throughput": self.expected_throughput,
            "expected_memory_mb": self.expected_memory_mb,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


class ModelRecommender:
    """
    Intelligent model recommender using benchmarks and heuristics.

    Workflow:
    1. If BenchmarkStorage available: Query historical runs matching constraints
    2. Fallback: Use ModelRegistry heuristics (prefer CT2/INT8 on CPU)
    3. Return recommendation with confidence score
    """

    def __init__(
        self,
        registry: ModelRegistry,
        benchmark_storage: Optional[Any] = None,
        hardware_detector: Optional[HardwareDetector] = None,
    ):
        """
        Initialize model recommender.

        Args:
            registry: ModelRegistry instance
            benchmark_storage: Optional BenchmarkDatabase for historical data
            hardware_detector: Optional HardwareDetector (auto-created if None)
        """
        self.registry = registry
        self.benchmark_storage = benchmark_storage
        self.hardware_detector = hardware_detector or HardwareDetector()
        self.hardware_info = self.hardware_detector.detect()

        logger.info(
            f"ModelRecommender initialized (benchmarks={'available' if benchmark_storage else 'not available'})"
        )

    def recommend(
        self,
        target_throughput: Optional[float] = None,
        max_memory_gb: Optional[float] = None,
        device_preference: Optional[str] = None,
    ) -> ModelRecommendation:
        """
        Recommend best model for given constraints.

        Args:
            target_throughput: Minimum desired tokens/sec (optional)
            max_memory_gb: Maximum memory budget in GB (optional)
            device_preference: Preferred device ("cpu", "cuda", "mps") (optional)

        Returns:
            ModelRecommendation with expected performance and confidence

        Raises:
            ValueError: If no models fit the constraints
        """
        logger.info(
            f"Recommending model (throughput={target_throughput}, "
            f"max_memory={max_memory_gb}GB, device={device_preference})"
        )

        # Try benchmark-backed recommendation first
        if self.benchmark_storage is not None:
            try:
                recommendation = self._recommend_from_benchmarks(
                    target_throughput, max_memory_gb, device_preference
                )
                if recommendation:
                    logger.info(f"Benchmark-backed recommendation: {recommendation.model_id}")
                    return recommendation
            except Exception as e:
                logger.warning(f"Benchmark query failed, falling back to heuristics: {e}")

        # Fallback to registry heuristics
        logger.info("Using registry heuristics for recommendation")
        return self._recommend_from_heuristics(
            target_throughput, max_memory_gb, device_preference
        )

    def _recommend_from_benchmarks(
        self,
        target_throughput: Optional[float],
        max_memory_gb: Optional[float],
        device_preference: Optional[str],
    ) -> Optional[ModelRecommendation]:
        """
        Recommend model based on historical benchmark data.

        Args:
            target_throughput: Minimum desired tokens/sec
            max_memory_gb: Maximum memory budget in GB
            device_preference: Preferred device

        Returns:
            ModelRecommendation if suitable benchmark found, None otherwise
        """
        device = device_preference or self.hardware_info.recommended_device
        max_memory_mb = max_memory_gb * 1024 if max_memory_gb else None

        # Query runs matching device preference
        runs = self.benchmark_storage.list_runs(device=device, limit=100)

        if not runs:
            logger.info(f"No benchmark runs found for device={device}")
            return None

        # Score each run based on constraints
        candidates = []
        for run_id, model_id, run_device, timestamp, result_count in runs:
            run = self.benchmark_storage.get_run(run_id)
            if not run or not run.results:
                continue

            # Calculate average metrics
            avg_throughput = sum(r.throughput_tokens_per_sec for r in run.results) / len(
                run.results
            )
            peak_memory = max(
                (r.peak_memory_mb for r in run.results if r.peak_memory_mb), default=None
            )

            # Filter by constraints
            if target_throughput and avg_throughput < target_throughput:
                continue
            if max_memory_mb and peak_memory and peak_memory > max_memory_mb:
                continue

            # Get model info from registry
            try:
                model_info = self.registry.get_model(model_id)
            except KeyError:
                logger.warning(f"Model {model_id} from benchmarks not in registry")
                continue

            candidates.append(
                {
                    "model_id": model_id,
                    "model_info": model_info,
                    "throughput": avg_throughput,
                    "memory": peak_memory,
                    "run_id": run_id,
                    "timestamp": timestamp,
                }
            )

        if not candidates:
            logger.info("No benchmark candidates match constraints")
            return None

        # Select best candidate (highest throughput)
        best = max(candidates, key=lambda c: c["throughput"])

        rationale = (
            f"Based on benchmark run {best['run_id'][:8]} from {best['timestamp'][:10]}. "
            f"Measured throughput: {best['throughput']:.1f} tokens/sec"
        )
        if best["memory"]:
            rationale += f", peak memory: {best['memory']:.0f}MB"

        return ModelRecommendation(
            model_id=best["model_id"],
            backend=best["model_info"].backend,
            device=device,
            expected_throughput=best["throughput"],
            expected_memory_mb=best["memory"],
            confidence="high",
            rationale=rationale,
        )

    def _recommend_from_heuristics(
        self,
        target_throughput: Optional[float],
        max_memory_gb: Optional[float],
        device_preference: Optional[str],
    ) -> ModelRecommendation:
        """
        Recommend model using registry heuristics.

        Prefers:
        - CTranslate2 backend on CPU (faster inference)
        - INT8 quantized models for lower memory
        - Smaller models when memory constrained

        Args:
            target_throughput: Minimum desired tokens/sec (advisory only)
            max_memory_gb: Maximum memory budget in GB
            device_preference: Preferred device

        Returns:
            ModelRecommendation based on heuristics

        Raises:
            ValueError: If no models fit memory constraint
        """
        device = device_preference or self.hardware_info.recommended_device
        models = list(self.registry.models.values())

        # Filter by memory constraint
        if max_memory_gb:
            max_memory_mb = max_memory_gb * 1024
            models = [m for m in models if m.model_size_mb <= max_memory_mb]
            if not models:
                raise ValueError(
                    f"No models fit memory constraint: max={max_memory_gb}GB. "
                    f"Smallest model requires {min(self.registry.models.values(), key=lambda m: m.model_size_mb).model_size_mb / 1024:.1f}GB"
                )

        # Score models based on heuristics
        scored = []
        for model in models:
            score = 0.0

            # Prefer CTranslate2 backend (optimized for inference)
            if model.backend == "ctranslate2":
                score += 20.0
                # Extra bonus for INT8 quantized models on CPU
                if device == "cpu" and "int8" in model.model_id.lower():
                    score += 15.0
            elif model.backend == "huggingface":
                score += 10.0

            # Device compatibility
            if model.optimal_device == device:
                score += 10.0

            # Prefer smaller models for faster loading
            size_penalty = model.model_size_mb / 1000
            score -= size_penalty

            # Memory headroom bonus
            if max_memory_gb:
                headroom = (max_memory_gb * 1024 - model.model_size_mb) / (max_memory_gb * 1024)
                score += headroom * 5.0

            scored.append((score, model))

        if not scored:
            raise ValueError("No suitable models found in registry")

        # Select highest scored model
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_model = scored[0]

        # Build rationale
        rationale_parts = []
        if best_model.backend == "ctranslate2":
            rationale_parts.append("CTranslate2 backend (optimized for inference)")
            if "int8" in best_model.model_id.lower():
                rationale_parts.append("INT8 quantization (lower memory, faster on CPU)")
        if device == "cpu":
            rationale_parts.append("CPU-optimized selection")

        rationale_parts.append(f"Model size: {best_model.model_size_mb}MB")
        if max_memory_gb:
            rationale_parts.append(f"Fits {max_memory_gb}GB constraint")

        rationale = "Heuristic-based: " + ", ".join(rationale_parts)

        # Estimate throughput (rough heuristic)
        estimated_throughput = None
        if best_model.backend == "ctranslate2":
            # CT2 is ~2-4x faster than HF
            base_throughput = 15.0 if device == "cpu" else 40.0
            estimated_throughput = base_throughput
            if "int8" in best_model.model_id.lower():
                estimated_throughput *= 1.5  # INT8 speedup

        # Estimate memory (model size + overhead)
        estimated_memory = best_model.model_size_mb * 1.2  # 20% overhead

        # Confidence based on constraint satisfaction
        confidence = "medium"
        if target_throughput and estimated_throughput and estimated_throughput < target_throughput:
            confidence = "low"
            rationale += f" (estimated throughput {estimated_throughput:.1f} may not meet target {target_throughput:.1f})"

        return ModelRecommendation(
            model_id=best_model.model_id,
            backend=best_model.backend,
            device=device,
            expected_throughput=estimated_throughput,
            expected_memory_mb=estimated_memory,
            confidence=confidence,
            rationale=rationale,
        )


def main():
    """CLI entry point for model recommendation."""
    parser = argparse.ArgumentParser(
        description="Recommend translation model based on constraints and benchmarks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Recommend model for CPU with 4GB memory limit
  python -m src.model_runtime.recommender --max-memory 4 --device cpu

  # Recommend model targeting 10 tokens/sec throughput
  python -m src.model_runtime.recommender --target-throughput 10

  # Use custom registry and benchmark database
  python -m src.model_runtime.recommender \\
    --registry config/model_registry.yaml \\
    --benchmark-db data/benchmarks/cpu.db \\
    --max-memory 4 --device cpu

  # Get JSON output for scripting
  python -m src.model_runtime.recommender --device cpu --format json
        """,
    )

    parser.add_argument(
        "--target-throughput",
        type=float,
        help="Minimum target throughput (tokens/sec)",
    )
    parser.add_argument(
        "--max-memory",
        type=float,
        help="Maximum memory budget (GB)",
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "cuda", "mps"],
        help="Preferred device (default: auto-detect)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("config/model_registry.yaml"),
        help="Path to model registry YAML (default: config/model_registry.yaml)",
    )
    parser.add_argument(
        "--benchmark-db",
        type=Path,
        help="Path to benchmark database (optional, enables data-driven recommendations)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        # Load registry
        if not args.registry.exists():
            print(f"ERROR: Registry file not found: {args.registry}", file=sys.stderr)
            sys.exit(1)

        registry = ModelRegistry(args.registry)
        logger.info(f"Loaded registry with {len(registry)} models")

        # Load benchmark storage if provided
        benchmark_storage = None
        if args.benchmark_db:
            if not args.benchmark_db.exists():
                print(
                    f"WARNING: Benchmark database not found: {args.benchmark_db}",
                    file=sys.stderr,
                )
                print("Falling back to heuristic recommendations", file=sys.stderr)
            else:
                try:
                    from ..benchmarking.storage import BenchmarkDatabase

                    benchmark_storage = BenchmarkDatabase(args.benchmark_db)
                    logger.info(f"Loaded benchmark database: {args.benchmark_db}")
                except ImportError:
                    print(
                        "WARNING: Benchmark storage not available (missing dependencies)",
                        file=sys.stderr,
                    )

        # Create recommender
        recommender = ModelRecommender(
            registry=registry,
            benchmark_storage=benchmark_storage,
        )

        # Get recommendation
        recommendation = recommender.recommend(
            target_throughput=args.target_throughput,
            max_memory_gb=args.max_memory,
            device_preference=args.device,
        )

        # Output recommendation
        if args.format == "json":
            print(json.dumps(recommendation.to_dict(), indent=2))
        else:
            # Human-readable text format
            print("\n" + "=" * 70)
            print("MODEL RECOMMENDATION")
            print("=" * 70)
            print(f"Model ID:      {recommendation.model_id}")
            print(f"Backend:       {recommendation.backend}")
            print(f"Device:        {recommendation.device}")
            print(f"Confidence:    {recommendation.confidence}")

            if recommendation.expected_throughput:
                print(f"Throughput:    ~{recommendation.expected_throughput:.1f} tokens/sec")
            else:
                print(f"Throughput:    (not estimated)")

            if recommendation.expected_memory_mb:
                print(f"Memory:        ~{recommendation.expected_memory_mb:.0f}MB")
            else:
                print(f"Memory:        (not estimated)")

            print(f"\nRationale:")
            print(f"  {recommendation.rationale}")
            print("=" * 70 + "\n")

    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logger.exception("Unexpected error during recommendation")
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
