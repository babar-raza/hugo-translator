"""Concurrency and thread safety tests for benchmarking system."""
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from src.benchmarking.feedback import AdaptiveWeightLearner, RecommendationFeedback
from src.benchmarking.production_ingestor import ProductionMetricsIngestor
from src.benchmarking.recommender import ModelRecommender
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkRun, BenchmarkResult
from src.benchmarking.system_info import SystemInfo, SystemInfoCollector


def create_test_run(run_id: str, cpu_cores: int = 8) -> BenchmarkRun:
    """Helper to create a test benchmark run."""
    return BenchmarkRun(
        run_id=run_id,
        model_id="test_model",
        device="cpu",
        batch_sizes=[8],
        iterations=10,
        corpus_category="test",
        purpose="test",
        tags=["test"],
        system_info=SystemInfo(
            python_version="3.11",
            os_name="Linux",
            cpu_model="test_cpu",
            cpu_cores=cpu_cores,
            total_ram_gb=16.0,
        ),
        results=[
            BenchmarkResult(
                sample_id="sample-1",
                model_id="test_model",
                device="cpu",
                batch_size=8,
                duration_seconds=1.0,
                tokens_input=100,
                tokens_output=100,
                throughput_tokens_per_sec=100.0,
                peak_memory_mb=1000.0,
            )
        ],
    )


def test_concurrent_database_writes():
    """10 threads writing simultaneously should not corrupt database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        def write_run(i: int):
            """Write a single run to the database."""
            run = create_test_run(f"concurrent_run_{i}")
            db.save_run(run)
            return i

        # Execute 100 writes across 10 threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_run, i) for i in range(100)]

            # Wait for all to complete
            results = [f.result() for f in as_completed(futures)]

        # Verify all 100 runs saved
        runs = db.list_runs(limit=200)
        assert len(runs) == 100, f"Expected 100 runs, got {len(runs)}"

        # Verify database integrity - all runs retrievable
        for i in range(100):
            run = db.get_run(f"concurrent_run_{i}")
            assert run is not None, f"Run {i} not found after concurrent write"


def test_concurrent_reads_and_writes():
    """Concurrent reads and writes should not interfere."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Pre-populate with some runs
        for i in range(20):
            db.save_run(create_test_run(f"initial_run_{i}"))

        write_count = 0
        read_count = 0
        errors = []
        lock = threading.Lock()

        def write_worker(worker_id: int):
            """Write runs continuously."""
            nonlocal write_count
            try:
                for i in range(10):
                    run = create_test_run(f"write_worker_{worker_id}_run_{i}")
                    db.save_run(run)
                    with lock:
                        write_count += 1
                    time.sleep(0.001)  # Small delay
            except Exception as e:
                errors.append(f"Write worker {worker_id}: {e}")

        def read_worker(worker_id: int):
            """Read runs continuously."""
            nonlocal read_count
            try:
                for i in range(20):
                    runs = db.list_runs(limit=50)
                    with lock:
                        read_count += 1
                    time.sleep(0.001)  # Small delay
            except Exception as e:
                errors.append(f"Read worker {worker_id}: {e}")

        # Start 5 write workers and 5 read workers
        with ThreadPoolExecutor(max_workers=10) as executor:
            write_futures = [executor.submit(write_worker, i) for i in range(5)]
            read_futures = [executor.submit(read_worker, i) for i in range(5)]

            # Wait for all to complete
            for f in write_futures + read_futures:
                f.result()

        # Verify no errors
        assert len(errors) == 0, f"Errors during concurrent access: {errors}"

        # Verify expected write count
        assert write_count == 50, f"Expected 50 writes, got {write_count}"

        # Verify expected read count
        assert read_count == 100, f"Expected 100 reads, got {read_count}"

        # Verify database integrity
        all_runs = db.list_runs(limit=200)
        assert len(all_runs) >= 70, f"Expected at least 70 runs, got {len(all_runs)}"


def test_concurrent_recommender_requests():
    """Multiple threads requesting recommendations simultaneously."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Pre-populate with benchmark data
        for i in range(50):
            db.save_run(create_test_run(f"bench_run_{i}", cpu_cores=8))

        recommender = ModelRecommender(db)
        recommendations = []
        errors = []
        lock = threading.Lock()

        def request_recommendation(worker_id: int):
            """Request a recommendation."""
            try:
                system_info = SystemInfo(
                    python_version="3.11",
                    os_name="Linux",
                    cpu_model="test_cpu",
                    cpu_cores=8,
                    total_ram_gb=16.0,
                )

                rec = recommender.recommend(system_info)

                with lock:
                    recommendations.append(rec)

            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")

        # Execute 20 concurrent recommendation requests
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(request_recommendation, i) for i in range(20)]

            for f in as_completed(futures):
                f.result()

        # Verify no errors
        assert len(errors) == 0, f"Errors during concurrent recommendations: {errors}"

        # Verify all recommendations generated
        assert len(recommendations) == 20, \
            f"Expected 20 recommendations, got {len(recommendations)}"

        # Verify all recommendations are valid
        for rec in recommendations:
            assert rec.model_id is not None
            assert rec.batch_size > 0
            assert 0.0 <= rec.confidence_score <= 1.0


def test_concurrent_feedback_updates():
    """Multiple threads recording feedback simultaneously."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Pre-populate with benchmark data
        for i in range(20):
            db.save_run(create_test_run(f"bench_run_{i}"))

        recommender = ModelRecommender(db)
        errors = []

        def record_feedback(worker_id: int):
            """Record feedback for a recommendation."""
            try:
                # Generate recommendation first
                system_info = SystemInfo(
                    python_version="3.11",
                    os_name="Linux",
                    cpu_model="test_cpu",
                    cpu_cores=8,
                    total_ram_gb=16.0,
                )

                rec = recommender.recommend(system_info)

                # Record feedback
                feedback = RecommendationFeedback(
                    recommendation_id=rec.recommendation_id,
                    predicted_throughput=rec.predicted_throughput,
                    actual_throughput=rec.predicted_throughput * 0.95,  # 5% error
                    predicted_memory_mb=rec.predicted_memory_mb,
                    actual_memory_mb=rec.predicted_memory_mb * 1.05,  # 5% error
                    success=True,
                )

                recommender.record_outcome(feedback)

            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")

        # Execute 15 concurrent feedback recordings
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record_feedback, i) for i in range(15)]

            for f in as_completed(futures):
                f.result()

        # Verify no errors
        assert len(errors) == 0, f"Errors during concurrent feedback: {errors}"


def test_concurrent_production_metrics_recording():
    """Multiple threads recording production metrics simultaneously."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        ingestor = ProductionMetricsIngestor(db, enabled=True)
        errors = []

        def record_translation(worker_id: int):
            """Record a production translation."""
            try:
                ingestor.record_translation_run(
                    file_path=f"test_{worker_id}.md",
                    target_lang="es",
                    segments_translated=10,
                    segments_from_tm=5,
                    segments_translated_new=5,
                    translation_model="test_model",
                    retry_count=0,
                    success=True,
                    duration_seconds=1.0,
                )
            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")

        # Execute 50 concurrent production metric recordings
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record_translation, i) for i in range(50)]

            for f in as_completed(futures):
                f.result()

        # Verify no errors
        assert len(errors) == 0, f"Errors during concurrent production recording: {errors}"

        # Verify all runs recorded
        runs = db.list_runs(limit=100)
        assert len(runs) == 50, f"Expected 50 production runs, got {len(runs)}"


def test_concurrent_weight_learner_updates():
    """Multiple threads updating weights simultaneously."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        learner = AdaptiveWeightLearner(db, learning_rate=0.1)
        errors = []
        lock = threading.Lock()

        def update_weights(worker_id: int):
            """Update weights with feedback."""
            try:
                feedback = RecommendationFeedback(
                    recommendation_id=f"rec_{worker_id}",
                    predicted_throughput=100.0,
                    actual_throughput=95.0 + worker_id,  # Varying performance
                    predicted_memory_mb=1000.0,
                    actual_memory_mb=1100.0 + worker_id * 10,
                    success=True,
                )

                learner.update_weights(feedback)

            except Exception as e:
                with lock:
                    errors.append(f"Worker {worker_id}: {e}")

        # Execute 30 concurrent weight updates
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(update_weights, i) for i in range(30)]

            for f in as_completed(futures):
                f.result()

        # Verify no errors
        assert len(errors) == 0, f"Errors during concurrent weight updates: {errors}"

        # Verify weights are still valid
        weights = learner.get_current_weights()
        assert isinstance(weights, dict)
        for key, value in weights.items():
            assert isinstance(value, (int, float)), f"Weight {key} has invalid type"
            assert value >= 0, f"Weight {key} is negative: {value}"


def test_concurrent_system_info_collection():
    """Multiple threads collecting system info simultaneously."""
    errors = []

    def collect_info(worker_id: int):
        """Collect system information."""
        try:
            collector = SystemInfoCollector()
            info = collector.collect()

            # Verify info is valid
            assert info.cpu_cores > 0
            assert info.total_ram_gb > 0

        except Exception as e:
            errors.append(f"Worker {worker_id}: {e}")

    # Execute 20 concurrent system info collections
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(collect_info, i) for i in range(20)]

        for f in as_completed(futures):
            f.result()

    # Verify no errors
    assert len(errors) == 0, f"Errors during concurrent info collection: {errors}"


def test_concurrent_database_deletion():
    """Concurrent deletes should not corrupt database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Pre-populate with runs
        for i in range(100):
            db.save_run(create_test_run(f"delete_run_{i}"))

        errors = []

        def delete_run(run_id: str):
            """Delete a single run."""
            try:
                db.delete_run(run_id)
            except Exception as e:
                errors.append(f"Delete {run_id}: {e}")

        # Execute 50 concurrent deletes
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(delete_run, f"delete_run_{i}")
                for i in range(50)
            ]

            for f in as_completed(futures):
                f.result()

        # Verify no errors
        assert len(errors) == 0, f"Errors during concurrent deletes: {errors}"

        # Verify 50 runs remain
        remaining_runs = db.list_runs(limit=200)
        assert len(remaining_runs) == 50, \
            f"Expected 50 runs remaining, got {len(remaining_runs)}"


def test_stress_concurrent_mixed_operations():
    """Stress test with mixed read/write/update/delete operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Pre-populate
        for i in range(50):
            db.save_run(create_test_run(f"stress_run_{i}"))

        recommender = ModelRecommender(db)
        ingestor = ProductionMetricsIngestor(db, enabled=True)

        errors = []
        lock = threading.Lock()

        def writer(worker_id: int):
            """Write new runs."""
            try:
                for i in range(5):
                    run = create_test_run(f"writer_{worker_id}_run_{i}")
                    db.save_run(run)
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    errors.append(f"Writer {worker_id}: {e}")

        def reader(worker_id: int):
            """Read runs."""
            try:
                for i in range(10):
                    db.list_runs(limit=30)
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    errors.append(f"Reader {worker_id}: {e}")

        def recommender_worker(worker_id: int):
            """Generate recommendations."""
            try:
                for i in range(3):
                    system_info = SystemInfo(
                        python_version="3.11",
                        os_name="Linux",
                        cpu_model="test_cpu",
                        cpu_cores=8,
                        total_ram_gb=16.0,
                    )
                    recommender.recommend(system_info)
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    errors.append(f"Recommender {worker_id}: {e}")

        def production_worker(worker_id: int):
            """Record production metrics."""
            try:
                for i in range(3):
                    ingestor.record_translation_run(
                        file_path=f"stress_{worker_id}_{i}.md",
                        target_lang="es",
                        segments_translated=10,
                        segments_from_tm=5,
                        segments_translated_new=5,
                        translation_model="test_model",
                        retry_count=0,
                        success=True,
                    )
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    errors.append(f"Production {worker_id}: {e}")

        # Execute mixed workload
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []

            # 5 writers
            futures.extend([executor.submit(writer, i) for i in range(5)])

            # 5 readers
            futures.extend([executor.submit(reader, i) for i in range(5)])

            # 5 recommenders
            futures.extend([executor.submit(recommender_worker, i) for i in range(5)])

            # 5 production workers
            futures.extend([executor.submit(production_worker, i) for i in range(5)])

            # Wait for all to complete
            for f in as_completed(futures):
                f.result()

        # Verify no errors
        assert len(errors) == 0, f"Errors during stress test: {errors}"

        # Verify database is still functional
        runs = db.list_runs(limit=200)
        assert len(runs) > 50, "Database appears corrupted after stress test"
