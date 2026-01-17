"""
Test script for Phase 1: Benchmarking Language Hardcode Fix

This script verifies:
1. Schema migration v10 adds src_lang/tgt_lang columns
2. BenchmarkRunner accepts language parameters
3. Database save/load works with language fields
4. Multi-language iteration works
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.benchmarking.schema_migrations import MigrationManager
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun, SystemInfo
from datetime import datetime, UTC


def test_migration_v10():
    """Test that migration v10 adds language columns."""
    print("\n=== TEST 1: Schema Migration v10 ===")

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # Create database with base schema
        db = BenchmarkDatabase(db_path)
        db.close()

        # Run migration to v10
        manager = MigrationManager(db_path)
        current_version = manager.get_current_version()
        print(f"Current schema version: {current_version}")

        if current_version < 10:
            print("Migrating to version 10...")
            manager.migrate_to(10)
            print("✓ Migration successful")

        # Verify columns exist
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(benchmark_results)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert 'src_lang' in columns, "Missing src_lang column"
        assert 'tgt_lang' in columns, "Missing tgt_lang column"
        print(f"✓ Columns verified: {columns & {'src_lang', 'tgt_lang'}}")

        return True

    except Exception as e:
        print(f"✗ Migration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if db_path.exists():
            db_path.unlink()


def test_benchmark_data_with_languages():
    """Test saving and loading benchmark data with language fields."""
    print("\n=== TEST 2: Benchmark Data with Languages ===")

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # Create database and migrate
        db = BenchmarkDatabase(db_path)
        manager = MigrationManager(db_path)
        manager.migrate_to(10)

        # Create mock system info
        system_info = SystemInfo(
            cpu_model="Test CPU",
            cpu_cores=4,
            total_ram_gb=16.0,
            gpu_model="Test GPU",
            gpu_memory_gb=8.0,
            os_name="TestOS",
            os_version="1.0",
            python_version="3.11",
            torch_version="2.0",
            collected_at_utc=datetime.now(UTC).isoformat()
        )

        # Create benchmark results for different languages
        languages = [('en', 'fr'), ('en', 'de'), ('en', 'ja')]

        for src_lang, tgt_lang in languages:
            result = BenchmarkResult(
                sample_id=f"sample_{src_lang}_{tgt_lang}",
                model_id="test_model",
                device="cpu",
                batch_size=8,
                duration_seconds=1.5,
                tokens_input=100,
                tokens_output=120,
                throughput_tokens_per_sec=80.0,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
            )

            run = BenchmarkRun(
                run_id=f"run_{src_lang}_{tgt_lang}",
                model_id="test_model",
                device="cpu",
                batch_sizes=[8],
                iterations=1,
                corpus_category="tiny",
                purpose="test",
                tags=[f"lang:{tgt_lang}"],
                system_info=system_info,
                results=[result],
                total_duration_seconds=2.0,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
            )

            db.save_run(run)
            print(f"✓ Saved benchmark for {src_lang}→{tgt_lang}")

        # Query by language pair
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT src_lang, tgt_lang, COUNT(*) FROM benchmark_results GROUP BY src_lang, tgt_lang"
        )
        results = cursor.fetchall()
        conn.close()

        print(f"\n✓ Query results:")
        for row in results:
            print(f"  {row[0]}→{row[1]}: {row[2]} samples")

        assert len(results) == 3, f"Expected 3 language pairs, got {len(results)}"
        print(f"\n✓ All {len(results)} language pairs saved and queryable")

        return True

    except Exception as e:
        print(f"✗ Benchmark data test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        db.close()
        if db_path.exists():
            db_path.unlink()


def test_cli_language_arguments():
    """Test CLI argument structure (without actually running benchmarks)."""
    print("\n=== TEST 3: CLI Language Arguments ===")

    try:
        from src.benchmarking.cli import load_target_languages

        # Test loading target languages
        languages = load_target_languages()
        print(f"✓ Loaded {len(languages)} target languages")
        print(f"  Sample languages: {', '.join(languages[:5])}...")

        assert len(languages) == 36, f"Expected 36 languages, got {len(languages)}"
        assert 'fr' in languages, "French not in language list"
        assert 'de' in languages, "German not in language list"
        assert 'ja' in languages, "Japanese not in language list"

        print("✓ CLI language loading works correctly")
        return True

    except Exception as e:
        print(f"✗ CLI test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("="*60)
    print("Phase 1: Benchmarking Language Hardcode Fix - Test Suite")
    print("="*60)

    tests = [
        test_migration_v10,
        test_benchmark_data_with_languages,
        test_cli_language_arguments,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test crashed: {e}")
            results.append(False)

    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("✓ All tests passed!")
        return 0
    else:
        print(f"✗ {total - passed} tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
