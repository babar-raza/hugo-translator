"""End-to-end integration tests for benchmarking system (SR-07).

Tests the complete workflow:
1. BenchmarkDatabase with schema migrations
2. ModelRecommender with feedback loop
3. Production metrics recording
4. Timing instrumentation
"""

import tempfile
from datetime import datetime
from pathlib import Path

from src.benchmarking.feedback import RecommendationFeedback
from src.benchmarking.recommender import ModelRecommender
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun, SystemInfo


class TestBenchmarkingEndToEnd:
    """End-to-end tests for complete benchmarking workflow."""

    def test_complete_recommendation_workflow(self):
        """Test complete workflow from benchmark → recommendation → feedback → learning."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "benchmarks.db"
            db = BenchmarkDatabase(db_path)

            # Step 1: Save initial benchmark run
            system_info = SystemInfo(
                cpu_model="Intel i7-9700K",
                cpu_cores=8,
                total_ram_gb=16.0,
                gpu_model="NVIDIA RTX 2070",
                gpu_memory_gb=8.0,
                has_cuda=True,
            )

            benchmark_run = BenchmarkRun(
                run_id="run_001",
                model_id="facebook/m2m100_418M",
                device="cuda",
                batch_sizes=[8, 16],
                iterations=10,
                corpus_category="test",
                purpose="testing",
                tags=["test"],
                system_info=system_info,
                results=[
                    BenchmarkResult(
                        sample_id="sample_001",
                        model_id="facebook/m2m100_418M",
                        device="cuda",
                        batch_size=8,
                        duration_seconds=2.5,
                        tokens_input=100,
                        tokens_output=120,
                        throughput_tokens_per_sec=48.0,
                        peak_memory_mb=1200.0,
                    ),
                    BenchmarkResult(
                        sample_id="sample_002",
                        model_id="facebook/m2m100_418M",
                        device="cuda",
                        batch_size=16,
                        duration_seconds=4.0,
                        tokens_input=200,
                        tokens_output=240,
                        throughput_tokens_per_sec=60.0,
                        peak_memory_mb=2000.0,
                    ),
                ],
                total_duration_seconds=6.5,
            )

            db.save_run(benchmark_run)

            # Step 2: Generate recommendation from historical data
            recommender = ModelRecommender(db, learning_rate=0.1)

            # Create similar system for recommendation
            similar_system = SystemInfo(
                cpu_model="Intel i7-9700",
                cpu_cores=8,
                total_ram_gb=16.0,
            )

            recommendation = recommender.recommend(similar_system)

            # Verify recommendation
            assert recommendation is not None
            assert recommendation.model_id == "facebook/m2m100_418M"
            assert recommendation.device == "cuda"
            assert recommendation.batch_size in [8, 16]
            assert recommendation.predicted_throughput > 0
            assert recommendation.confidence_score > 0

            # Step 3: Record feedback for recommendation
            from datetime import datetime
            feedback = RecommendationFeedback(
                feedback_id="feedback_001",
                recommendation_id=recommendation.recommendation_id,
                model_id_recommended=recommendation.model_id,
                model_id_used=recommendation.model_id,
                device_recommended=recommendation.device,
                device_used=recommendation.device,
                predicted_throughput=recommendation.predicted_throughput,
                actual_throughput=55.0,  # Actual was slightly different
                predicted_memory_mb=recommendation.predicted_memory_mb,
                actual_memory_mb=1800.0,
                success=True,
                quality_score=None,
                failure_reason=None,
                timestamp_utc=datetime.utcnow().isoformat() + "Z",
                system_info=similar_system,
            )

            # Record outcome to update weights
            recommender.record_outcome(feedback)

            # Step 4: Verify feedback was stored
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM recommendation_feedback WHERE feedback_id = ?",
                    (feedback.feedback_id,),
                )
                assert cursor.fetchone()[0] == 1
            finally:
                db._close_connection(conn)

            # Step 5: Verify weights were updated
            weights = recommender.weight_learner.get_current_weights()
            assert "throughput" in weights
            assert "memory" in weights
            assert "historical_success" in weights

    def test_schema_migration_with_data_preservation(self):
        """Test that schema migrations preserve existing data."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "benchmarks.db"

            # Create v1 database manually
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            try:
                # Create minimal v1 schema
                conn.execute(
                    """
                    CREATE TABLE schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE benchmark_runs (
                        run_id TEXT PRIMARY KEY,
                        model_id TEXT NOT NULL,
                        device TEXT NOT NULL,
                        batch_sizes TEXT NOT NULL,
                        iterations INTEGER NOT NULL,
                        corpus_category TEXT,
                        purpose TEXT NOT NULL,
                        tags TEXT NOT NULL,
                        total_duration_seconds REAL NOT NULL,
                        timestamp_utc TEXT NOT NULL,
                        metadata TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (1, datetime('now'))"
                )
                conn.execute(
                    """
                    INSERT INTO benchmark_runs VALUES
                    ('test_run', 'test_model', 'cpu', '[8]', 1, 'test', 'testing',
                     '[]', 10.0, '2024-01-01T00:00:00Z', '{}')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            # Open with BenchmarkDatabase (triggers migrations)
            db = BenchmarkDatabase(db_path)

            # Verify migration to current version (SCHEMA_VERSION = 10)
            assert db.get_schema_version() == 10

            # Verify data preserved
            run = db.get_run("test_run")
            assert run is not None
            assert run.model_id == "test_model"

    def test_production_metrics_workflow(self):
        """Test production metrics recording integration."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "benchmarks.db"
            db = BenchmarkDatabase(db_path)

            # Simulate production metrics recording
            from src.benchmarking.production_ingestor import ProductionMetricsIngestor

            ingestor = ProductionMetricsIngestor(db, enabled=True)

            # Record a translation run
            ingestor.record_translation_run(
                file_path="test/file.md",
                target_lang="es",
                segments_translated=50,
                segments_from_tm=30,
                segments_translated_new=20,
                translation_model="facebook/m2m100_418M",
                retry_count=1,
                success=True,
            )

            # Verify run was saved
            runs = db.list_runs(limit=10)
            assert len(runs) > 0

            # Verify production run has correct metadata
            run_id = runs[0][0]
            run = db.get_run(run_id)
            assert run is not None
            assert run.purpose == "production"
            assert "production" in run.tags

    def test_timing_instrumentation_integration(self):
        """Test that timing metrics are captured across all components."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            # Test L3 timing metrics
            from src.tm.l3_semantic import L3SemanticTM

            l3_path = Path(tmpdir) / "l3_index"
            l3 = L3SemanticTM(
                index_path=l3_path,
                embedding_model="all-MiniLM-L6-v2",
                save_interval=0,  # Disable periodic saves for test
            )

            # Add entry and verify timing tracked
            l3.add_entry(
                entry_id="entry_001",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Hello world",
                translation="Hola mundo",
            )

            metrics = l3.get_timing_metrics()
            assert metrics["add_entry"]["count"] == 1
            assert metrics["add_entry"]["mean"] > 0

            # Perform semantic search and verify timing
            l3.semantic_search(
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                query_text="Hello world",
            )

            metrics = l3.get_timing_metrics()
            assert metrics["semantic_search"]["count"] == 1
            assert metrics["cache_hits"] + metrics["cache_misses"] == 1

            # Test batch optimizer timing
            from src.orchestration.batch_optimizer import create_batch_optimizer

            optimizer = create_batch_optimizer(initial_batch_size=8)
            items = [f"Test item {i}" for i in range(100)]

            optimizer.prepare_batches(items)

            timing_metrics = optimizer.get_timing_metrics()
            assert timing_metrics["prepare_batches"]["count"] == 1
            assert timing_metrics["prepare_batches"]["mean"] > 0

    def test_foreign_key_cascade_integration(self):
        """Test that foreign key cascades work correctly in practice."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "benchmarks.db"
            db = BenchmarkDatabase(db_path)

            # Create benchmark run
            system_info = SystemInfo(
                cpu_model="Test CPU",
                cpu_cores=4,
                total_ram_gb=8.0,
            )

            run = BenchmarkRun(
                run_id="cascade_test_run",
                model_id="test_model",
                device="cpu",
                batch_sizes=[8],
                iterations=1,
                corpus_category="test",
                purpose="testing",
                tags=["test"],
                system_info=system_info,
                results=[],
                total_duration_seconds=1.0,
            )
            db.save_run(run)

            # Create feedback referencing this run
            conn = db._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO recommendation_feedback
                    (feedback_id, recommendation_id, model_id_recommended, model_id_used,
                     device_recommended, device_used, predicted_throughput, actual_throughput,
                     predicted_memory_mb, actual_memory_mb, success, quality_score,
                     failure_reason, timestamp_utc, system_info_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "cascade_feedback",
                        "cascade_test_run",
                        "test_model",
                        "test_model",
                        "cpu",
                        "cpu",
                        100.0,
                        95.0,
                        1000.0,
                        950.0,
                        1,
                        None,
                        None,
                        "2024-01-01T00:00:00Z",
                        "{}",
                    ),
                )
                conn.commit()

                # Verify feedback exists
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM recommendation_feedback WHERE recommendation_id = ?",
                    ("cascade_test_run",),
                )
                assert cursor.fetchone()[0] == 1

            finally:
                db._close_connection(conn)

            # Delete the run
            db.delete_run("cascade_test_run")

            # Verify feedback was cascade-deleted
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM recommendation_feedback WHERE recommendation_id = ?",
                    ("cascade_test_run",),
                )
                assert cursor.fetchone()[0] == 0
            finally:
                db._close_connection(conn)

    def test_adaptive_weight_learning(self):
        """Test that adaptive weight learning improves recommendations over time."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "benchmarks.db"
            db = BenchmarkDatabase(db_path)

            # Save multiple benchmark runs with varying performance
            for i in range(5):
                system_info = SystemInfo(
                    cpu_model="Intel i7",
                    cpu_cores=8,
                    total_ram_gb=16.0,
                )

                run = BenchmarkRun(
                    run_id=f"run_{i:03d}",
                    model_id="facebook/m2m100_418M",
                    device="cuda",
                    batch_sizes=[8 + i * 4],
                    iterations=10,
                    corpus_category="test",
                    purpose="testing",
                    tags=["test"],
                    system_info=system_info,
                    results=[
                        BenchmarkResult(
                            sample_id=f"sample_{i:03d}",
                            model_id="facebook/m2m100_418M",
                            device="cuda",
                            batch_size=8 + i * 4,
                            duration_seconds=2.0 + i * 0.5,
                            tokens_input=100,
                            tokens_output=120,
                            throughput_tokens_per_sec=40.0 + i * 5,
                            peak_memory_mb=1000.0 + i * 200,
                        )
                    ],
                    total_duration_seconds=2.0 + i * 0.5,
                )
                db.save_run(run)

            # Create recommender
            recommender = ModelRecommender(db, learning_rate=0.2)

            # Get initial weights
            initial_weights = recommender.weight_learner.get_current_weights()

            # Generate recommendation and provide feedback multiple times
            for i in range(3):
                system_info = SystemInfo(
                    cpu_model="Intel i7",
                    cpu_cores=8,
                    total_ram_gb=16.0,
                )

                recommendation = recommender.recommend(system_info)

                # Provide feedback that actual throughput was better than predicted
                feedback = RecommendationFeedback(
                    feedback_id=f"feedback_{i:03d}",
                    recommendation_id=recommendation.recommendation_id,
                    model_id_recommended=recommendation.model_id,
                    model_id_used=recommendation.model_id,
                    device_recommended=recommendation.device,
                    device_used=recommendation.device,
                    predicted_throughput=recommendation.predicted_throughput,
                    actual_throughput=recommendation.predicted_throughput * 1.1,  # 10% better
                    predicted_memory_mb=recommendation.predicted_memory_mb,
                    actual_memory_mb=recommendation.predicted_memory_mb * 0.9,  # 10% less
                    success=True,
                    quality_score=None,
                    failure_reason=None,
                    timestamp_utc=datetime.utcnow().isoformat() + "Z",
                    system_info=system_info,
                )

                recommender.record_outcome(feedback)

            # Get final weights
            final_weights = recommender.weight_learner.get_current_weights()

            # Verify weights changed (learning occurred)
            assert initial_weights != final_weights
            assert "throughput" in final_weights
            assert "memory" in final_weights
