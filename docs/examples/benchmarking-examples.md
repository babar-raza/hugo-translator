# Benchmarking Examples

**Last Updated**: 2025-12-24
**Status**: Production-Ready

## Basic Benchmark Run

```python
from pathlib import Path
from src.benchmarking.runner import BenchmarkRunner
from src.benchmarking.storage import BenchmarkDatabase

# Initialize database
db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))

# Run benchmark
runner = BenchmarkRunner(db)
run_id = runner.run_benchmark(
    model_id="facebook/m2m100_418M",
    device="cpu",
    batch_size=8,
    corpus_category="small",
    iterations=3,
)

print(f"Benchmark completed: {run_id}")
```

## Model Comparison

```python
from src.benchmarking.storage import BenchmarkDatabase
from pathlib import Path

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))

# Compare multiple models
models = ["facebook/m2m100_418M", "ct2/m2m100_418m", "ct2/m2m100_418m_int8"]
run_ids = []

for model_id in models:
    run_id = runner.run_benchmark(
        model_id=model_id,
        device="cpu",
        batch_size=8,
        corpus_category="small",
        iterations=3,
    )
    run_ids.append(run_id)

# Compare results
comparison = db.compare_runs(run_ids, metric="throughput_tokens_per_sec")
for run_id, stats in comparison.items():
    run = db.get_run(run_id)
    print(f"{run.model_id}:")
    print(f"  Mean throughput: {stats['mean']:.1f} tokens/sec")
    print(f"  P95 throughput: {stats['p95']:.1f} tokens/sec")
```

## Get Recommendations

```python
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.recommender import ModelRecommender
from src.benchmarking.system_info import SystemInfoCollector
from pathlib import Path

# Initialize
db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
recommender = ModelRecommender(db)
collector = SystemInfoCollector()

# Get system info
system_info = collector.collect()

# Get recommendation with constraints
recommendation = recommender.recommend(
    system_info=system_info,
    requirements={
        "max_memory_mb": 4000,
        "min_throughput": 30.0,
    }
)

print(f"Recommended model: {recommendation.model_id}")
print(f"Batch size: {recommendation.batch_size}")
print(f"Expected throughput: {recommendation.predicted_throughput:.1f} tokens/sec")
print(f"Expected memory: {recommendation.predicted_memory_mb:.0f} MB")
print(f"Confidence: {recommendation.confidence_score:.2%}")
print(f"Reasoning: {recommendation.reasoning}")
```

## Record Production Metrics

```python
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.production_ingestor import ProductionMetricsIngestor
from pathlib import Path

# Initialize with OPT-IN enabled
db = BenchmarkDatabase(Path("data/benchmarks/production.db"))
ingestor = ProductionMetricsIngestor(db, enabled=True)

# Record translation
ingestor.record_translation_run(
    file_path="content/blog/article.md",
    target_lang="es",
    segments_translated=200,
    segments_from_tm=150,
    segments_translated_new=50,
    translation_model="facebook/m2m100_418M",
    retry_count=1,
    success=True,
    duration_seconds=65.3,
)
```

## Provide Feedback

```python
from src.benchmarking.feedback import RecommendationFeedback

# After using recommendation, measure actual performance
actual_throughput = 32.5  # tokens/sec
actual_memory_mb = 3850.0  # MB

# Create feedback
feedback = RecommendationFeedback(
    recommendation_id=recommendation.recommendation_id,
    predicted_throughput=recommendation.predicted_throughput,
    actual_throughput=actual_throughput,
    predicted_memory_mb=recommendation.predicted_memory_mb,
    actual_memory_mb=actual_memory_mb,
    user_satisfied=True,
)

# Submit feedback to improve future recommendations
recommender.record_outcome(feedback)
print("Feedback recorded - system will learn from this outcome")
```

See [Benchmarking API Reference](../api/benchmarking-api.md) for full API details.
