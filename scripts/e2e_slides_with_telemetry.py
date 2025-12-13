#!/usr/bin/env python3
"""
E2E Translation Run for Aspose Slides with Enhanced Telemetry.

Translates markdown files from D:/onedrive/Documents/GitHub/aspose.net/content/products.aspose.net/slides/en
to all target locales with full telemetry tracking.
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime

# Add src to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

# Set up logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# All 35 target locales
TARGET_LOCALES = [
    "de", "es", "fr", "ja", "ko", "ru", "zh", "ar", "it", "pt",
    "pl", "fa", "id", "cs", "vi", "tr", "th", "sv", "el", "uk",
    "he", "bg", "ca", "da", "fi", "hr", "hu", "ro", "sk", "sr",
    "nl", "hi", "lt", "lv", "ms"
]

# Source directory (user-specified)
SOURCE_DIR = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en")


def run_translation_with_telemetry():
    """Run full E2E translation with enhanced telemetry."""

    start_time = datetime.now()
    print("=" * 80)
    print("E2E TRANSLATION - Aspose Slides with Enhanced Telemetry")
    print(f"Started: {start_time.isoformat()}")
    print(f"Source: {SOURCE_DIR}")
    print(f"Target Locales: {len(TARGET_LOCALES)}")
    print("=" * 80)

    # Import components
    print("\n[1/6] Importing components...")
    try:
        from src.translation_engine import TranslationEngine
        from src.utils.config_loader import ConfigService
        from src.tm import TranslationMemory
        from src.tm.l1_cache import L1Cache
        from src.tm.l2_persistent import L2PersistentTM
        from src.tm.l3_semantic import L3SemanticTM
        from src.model_runtime import ModelLoader
        from src.model_runtime.registry import ModelRegistry
        from src.observability.telemetry_integration import get_telemetry, configure_telemetry
        import torch
        print("   OK: All components imported")
    except ImportError as e:
        print(f"   ERROR: Import failed: {e}")
        import traceback
        traceback.print_exc()
        return None

    # Initialize Telemetry
    print("\n[2/6] Initializing Enhanced Telemetry...")
    try:
        telemetry = configure_telemetry(
            agent_name="hugo-translator-slides",
            enabled=True
        )
        if telemetry.is_available():
            print(f"   OK: Telemetry ACTIVE (TEL-03 integration)")
            print(f"   OK: Agent: {telemetry.agent_name}")
        else:
            print(f"   WARNING: Telemetry not available (continuing without tracking)")
    except Exception as e:
        print(f"   WARNING: Telemetry initialization warning: {e}")
        telemetry = None

    # Initialize components
    print("\n[3/6] Initializing translation components...")
    try:
        config_path = REPO_ROOT / "config"
        config_service = ConfigService(config_path)
        print("   OK: ConfigService loaded")

        # Initialize TM layers
        l1_cache = L1Cache(max_size=50000)  # Larger cache for full run
        print("   OK: L1Cache initialized (50K entries)")

        lmdb_path = REPO_ROOT / "data" / "tm" / "l2_lmdb"
        lmdb_path.parent.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(lmdb_path))
        print(f"   OK: L2PersistentTM initialized")

        faiss_path = REPO_ROOT / "data" / "tm" / "l3_faiss"
        faiss_path.mkdir(parents=True, exist_ok=True)
        l3_semantic = L3SemanticTM(index_path=str(faiss_path))
        print(f"   OK: L3SemanticTM initialized")

        tm = TranslationMemory(l1_cache=l1_cache, l2_persistent=l2_persistent, l3_semantic=l3_semantic)
        print("   OK: TranslationMemory initialized (L1+L2+L3)")

        # Initialize ModelLoader
        registry_path = config_path / "model_registry.yaml"
        model_registry = ModelRegistry(registry_path)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"   OK: Device: {device}")
        if device == "cuda":
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"   OK: GPU: {gpu_name} ({gpu_memory:.1f}GB)")

        model_loader = ModelLoader(registry=model_registry, device=device)
        print("   OK: ModelLoader initialized")

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            enable_telemetry=True  # Enable internal telemetry tracking
        )
        print("   OK: TranslationEngine initialized with telemetry")
    except Exception as e:
        print(f"   ERROR: Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return None

    # Verify source directory
    print(f"\n[4/6] Scanning source directory...")
    print(f"   Path: {SOURCE_DIR}")

    if not SOURCE_DIR.exists():
        print(f"   ERROR: Source directory does not exist!")
        return None

    # Find all markdown files (recursive)
    md_files = sorted(SOURCE_DIR.glob("**/*.md"))
    print(f"   OK: Found {len(md_files)} markdown files")

    if len(md_files) == 0:
        print(f"   ERROR: No markdown files found!")
        return None

    # Show first 10 files
    print(f"\n   Files to translate (showing first 10):")
    for f in md_files[:10]:
        rel_path = f.relative_to(SOURCE_DIR)
        size_kb = f.stat().st_size / 1024
        print(f"      - {rel_path} ({size_kb:.1f}KB)")
    if len(md_files) > 10:
        print(f"      ... and {len(md_files) - 10} more files")

    # Track results
    results = {
        "start_time": start_time.isoformat(),
        "source_dir": str(SOURCE_DIR),
        "total_files": len(md_files),
        "total_locales": len(TARGET_LOCALES),
        "expected_outputs": len(md_files) * len(TARGET_LOCALES),
        "successful": 0,
        "failed": 0,
        "errors": [],
        "file_results": {},
        "locale_stats": {},
        "total_segments": 0,
        "total_tm_hits": 0,
        "total_l1_hits": 0,
        "total_l2_hits": 0,
        "total_l3_hits": 0,
        "total_translated": 0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_tokens_cached": 0,
    }

    # Initialize locale stats
    for locale in TARGET_LOCALES:
        results["locale_stats"][locale] = {
            "files": 0,
            "segments": 0,
            "tm_hits": 0,
            "translated": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "errors": []
        }

    print(f"\n[5/6] Translating {len(md_files)} files to {len(TARGET_LOCALES)} locales...")
    print(f"   Total expected outputs: {results['expected_outputs']}")
    print("   Telemetry: ACTIVE and tracking all operations")
    print("-" * 80)

    # Start telemetry session for entire batch
    if telemetry and telemetry.is_available():
        telemetry_ctx = telemetry.track_translation_session(
            job_type="batch_translate_directory",
            trigger_type="cli",
            file_path=SOURCE_DIR,
            target_langs=TARGET_LOCALES,
            file_count=len(md_files)
        )
    else:
        telemetry_ctx = None

    # Translate each file
    file_start = time.time()
    try:
        with (telemetry_ctx if telemetry_ctx else DummyContext()):
            for file_idx, md_file in enumerate(md_files, 1):
                file_results = {"locales": {}, "success": True}

                rel_path = md_file.relative_to(SOURCE_DIR)
                print(f"\n[File {file_idx}/{len(md_files)}] {rel_path}")

                # Translate to all locales
                try:
                    result = engine.translate_file(
                        site_id="products.aspose.net",
                        file_path=md_file,
                        target_langs=TARGET_LOCALES,
                    )

                    # Track stats
                    results["total_segments"] += result.stats.total_segments
                    results["total_tm_hits"] += result.stats.tm_hits
                    results["total_l1_hits"] += result.stats.l1_hits
                    results["total_l2_hits"] += result.stats.l2_hits
                    results["total_l3_hits"] += result.stats.l3_hits
                    results["total_translated"] += result.stats.translated_segments
                    results["total_tokens_in"] += result.stats.tokens_input
                    results["total_tokens_out"] += result.stats.tokens_output
                    results["total_tokens_cached"] += result.stats.tokens_cached

                    if result.success:
                        results["successful"] += len(TARGET_LOCALES)
                        print(f"   SUCCESS: {len(TARGET_LOCALES)} locales")
                        print(f"   Segments: {result.stats.total_segments}, TM: {result.stats.tm_hits} (L1:{result.stats.l1_hits} L2:{result.stats.l2_hits} L3:{result.stats.l3_hits}), Model: {result.stats.translated_segments}")
                        print(f"   Tokens: {result.stats.tokens_input} in / {result.stats.tokens_output} out / {result.stats.tokens_cached} cached")

                        # Update locale stats
                        for locale in TARGET_LOCALES:
                            results["locale_stats"][locale]["files"] += 1
                            results["locale_stats"][locale]["segments"] += result.stats.total_segments // len(TARGET_LOCALES)
                    else:
                        file_results["success"] = False
                        for error in result.errors:
                            results["errors"].append(f"{rel_path}: {error}")
                            # Try to identify which locale failed
                            for locale in TARGET_LOCALES:
                                if locale in str(error):
                                    results["locale_stats"][locale]["errors"].append(error)
                                    results["failed"] += 1
                                    break
                            else:
                                results["failed"] += len(TARGET_LOCALES)
                        print(f"   ERRORS: {result.errors}")

                    # Track output paths
                    if result.outputs:
                        for locale, output_path in result.outputs.items():
                            file_results["locales"][locale] = str(output_path)

                except Exception as e:
                    file_results["success"] = False
                    results["failed"] += len(TARGET_LOCALES)
                    results["errors"].append(f"{rel_path}: {str(e)}")
                    print(f"   EXCEPTION: {e}")
                    import traceback
                    traceback.print_exc()

                results["file_results"][str(rel_path)] = file_results

                # Progress
                elapsed = time.time() - file_start
                files_remaining = len(md_files) - file_idx
                if file_idx > 0:
                    avg_time = elapsed / file_idx
                    eta = avg_time * files_remaining
                    print(f"   Progress: {file_idx}/{len(md_files)} files, Elapsed: {elapsed:.1f}s, ETA: {eta:.1f}s")

    except KeyboardInterrupt:
        print("\n\nTranslation interrupted by user")
        results["interrupted"] = True
    except Exception as e:
        print(f"\n\nCritical error during translation: {e}")
        import traceback
        traceback.print_exc()
        results["critical_error"] = str(e)

    print("\n" + "-" * 80)

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    results["end_time"] = end_time.isoformat()
    results["duration_seconds"] = duration

    print(f"\n[6/6] Summary")
    print("=" * 80)
    print(f"Duration: {duration:.1f}s ({duration/60:.1f} minutes)")
    print(f"Files processed: {len(md_files)}")
    print(f"Locales: {len(TARGET_LOCALES)}")
    print(f"Expected outputs: {results['expected_outputs']}")
    print(f"Successful: {results['successful']}")
    print(f"Failed: {results['failed']}")

    print(f"\nSegment Statistics:")
    print(f"  Total segments: {results['total_segments']:,}")
    print(f"  TM hits: {results['total_tm_hits']:,}")
    print(f"    - L1 hits: {results['total_l1_hits']:,}")
    print(f"    - L2 hits: {results['total_l2_hits']:,}")
    print(f"    - L3 hits: {results['total_l3_hits']:,}")
    print(f"  Model translated: {results['total_translated']:,}")
    if results['total_segments'] > 0:
        tm_rate = results['total_tm_hits'] / results['total_segments'] * 100
        print(f"  TM hit rate: {tm_rate:.1f}%")

    print(f"\nToken Usage:")
    print(f"  Input tokens: {results['total_tokens_in']:,}")
    print(f"  Output tokens: {results['total_tokens_out']:,}")
    print(f"  Cached tokens: {results['total_tokens_cached']:,}")
    print(f"  Total tokens: {results['total_tokens_in'] + results['total_tokens_out']:,}")
    if results['total_tokens_in'] + results['total_tokens_out'] > 0:
        cache_rate = results['total_tokens_cached'] / (results['total_tokens_in'] + results['total_tokens_out']) * 100
        print(f"  Cache rate: {cache_rate:.1f}%")

    if results["errors"]:
        print(f"\nErrors ({len(results['errors'])}):")
        for err in results["errors"][:10]:  # Show first 10
            print(f"  - {err}")
        if len(results["errors"]) > 10:
            print(f"  ... and {len(results['errors']) - 10} more")

    if telemetry and telemetry.is_available():
        print(f"\nTelemetry Status: ACTIVE - All metrics captured")
    else:
        print(f"\nTelemetry Status: Not available")

    print("=" * 80)

    return results


class DummyContext:
    """Dummy context manager for when telemetry is unavailable."""
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def save_results(results: dict):
    """Save results to JSON file."""
    import json

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = REPO_ROOT / "reports" / "translation_e2e" / f"{timestamp}_slides"
    output_dir.mkdir(parents=True, exist_ok=True)

    results_file = output_dir / "e2e_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nResults saved to: {results_file}")
    return results_file


if __name__ == "__main__":
    print("\nStarting E2E Translation with Enhanced Telemetry\n")

    results = run_translation_with_telemetry()

    if results:
        save_results(results)

        success_rate = results["successful"] / results["expected_outputs"] * 100 if results["expected_outputs"] > 0 else 0

        print(f"\n{'='*80}")
        if success_rate >= 95:
            print(f"FINAL STATUS: PASS ({success_rate:.1f}% success rate)")
            sys.exit(0)
        else:
            print(f"FINAL STATUS: PARTIAL ({success_rate:.1f}% success rate)")
            sys.exit(1)
    else:
        print(f"\n{'='*80}")
        print("FINAL STATUS: FAIL (initialization error)")
        sys.exit(1)
