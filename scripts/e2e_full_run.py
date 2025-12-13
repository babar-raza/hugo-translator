#!/usr/bin/env python3
"""
E2E Full Run Script for slides translation.

Translates all 10 markdown files in en/ to 35 locales.
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

def run_full_translation():
    """Run full E2E translation."""

    start_time = datetime.now()
    print("=" * 70)
    print("E2E FULL RUN - Translation Pipeline")
    print(f"Started: {start_time.isoformat()}")
    print(f"Target Locales: {len(TARGET_LOCALES)}")
    print("=" * 70)

    # Import components
    print("\n[1/5] Importing components...")
    try:
        from src.translation_engine import TranslationEngine
        from src.utils.config_loader import ConfigService
        from src.tm import TranslationMemory
        from src.tm.l1_cache import L1Cache
        from src.tm.l2_persistent import L2PersistentTM
        from src.tm.l3_semantic import L3SemanticTM
        from src.model_runtime import ModelLoader
        from src.model_runtime.registry import ModelRegistry
        import torch
        print("   OK: All components imported")
    except ImportError as e:
        print(f"   ERROR: Import failed: {e}")
        return None

    # Initialize components
    print("\n[2/5] Initializing components...")
    try:
        config_path = REPO_ROOT / "config"
        config_service = ConfigService(config_path)

        # Initialize TM layers
        l1_cache = L1Cache(max_size=50000)  # Larger cache for full run
        lmdb_path = REPO_ROOT / "data" / "tm" / "l2_lmdb"
        lmdb_path.parent.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(lmdb_path))

        faiss_path = REPO_ROOT / "data" / "tm" / "l3_faiss"
        faiss_path.mkdir(parents=True, exist_ok=True)
        l3_semantic = L3SemanticTM(index_path=str(faiss_path))

        tm = TranslationMemory(l1_cache=l1_cache, l2_persistent=l2_persistent, l3_semantic=l3_semantic)

        # Initialize ModelLoader
        registry_path = config_path / "model_registry.yaml"
        model_registry = ModelRegistry(registry_path)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"   Device: {device}")
        if device == "cuda":
            print(f"   GPU: {torch.cuda.get_device_name(0)}")

        model_loader = ModelLoader(registry=model_registry, device=device)

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            enable_telemetry=True
        )
        print("   OK: All components initialized")
    except Exception as e:
        print(f"   ERROR: Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return None

    # Source directory
    source_dir = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en")

    print(f"\n[3/5] Scanning source directory...")
    print(f"   Path: {source_dir}")

    # Find all markdown files (recursive)
    md_files = sorted(source_dir.glob("**/*.md"))
    print(f"   Found {len(md_files)} markdown files")
    for f in md_files:
        rel_path = f.relative_to(source_dir)
        print(f"      - {rel_path}")

    # Track results
    results = {
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
        "total_translated": 0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
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

    print(f"\n[4/5] Translating {len(md_files)} files to {len(TARGET_LOCALES)} locales...")
    print(f"   Total expected outputs: {results['expected_outputs']}")
    print("-" * 70)

    # Translate each file
    file_start = time.time()
    for file_idx, md_file in enumerate(md_files, 1):
        file_results = {"locales": {}, "success": True}

        print(f"\n[File {file_idx}/{len(md_files)}] {md_file.name}")

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
            results["total_translated"] += result.stats.translated_segments
            results["total_tokens_in"] += result.stats.tokens_input
            results["total_tokens_out"] += result.stats.tokens_output

            if result.success:
                results["successful"] += len(TARGET_LOCALES)
                print(f"   SUCCESS: {len(TARGET_LOCALES)} locales")
                print(f"   Segments: {result.stats.total_segments}, TM: {result.stats.tm_hits}, Model: {result.stats.translated_segments}")
                print(f"   Tokens: {result.stats.tokens_input} in / {result.stats.tokens_output} out")

                # Update locale stats
                for locale in TARGET_LOCALES:
                    results["locale_stats"][locale]["files"] += 1
                    results["locale_stats"][locale]["segments"] += result.stats.total_segments // len(TARGET_LOCALES)
            else:
                file_results["success"] = False
                for error in result.errors:
                    results["errors"].append(f"{md_file.name}: {error}")
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
            results["errors"].append(f"{md_file.name}: {str(e)}")
            print(f"   EXCEPTION: {e}")

        results["file_results"][md_file.name] = file_results

        # Progress
        elapsed = time.time() - file_start
        files_remaining = len(md_files) - file_idx
        if file_idx > 0:
            avg_time = elapsed / file_idx
            eta = avg_time * files_remaining
            print(f"   Progress: {file_idx}/{len(md_files)} files, ETA: {eta:.1f}s")

    print("\n" + "-" * 70)

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print(f"\n[5/5] Summary")
    print("=" * 70)
    print(f"Duration: {duration:.1f}s ({duration/60:.1f} minutes)")
    print(f"Files processed: {len(md_files)}")
    print(f"Locales: {len(TARGET_LOCALES)}")
    print(f"Expected outputs: {results['expected_outputs']}")
    print(f"Successful: {results['successful']}")
    print(f"Failed: {results['failed']}")
    print(f"\nSegment Statistics:")
    print(f"  Total segments: {results['total_segments']}")
    print(f"  TM hits: {results['total_tm_hits']}")
    print(f"  Model translated: {results['total_translated']}")
    if results['total_segments'] > 0:
        tm_rate = results['total_tm_hits'] / results['total_segments'] * 100
        print(f"  TM hit rate: {tm_rate:.1f}%")
    print(f"\nToken Usage:")
    print(f"  Input tokens: {results['total_tokens_in']}")
    print(f"  Output tokens: {results['total_tokens_out']}")

    if results["errors"]:
        print(f"\nErrors ({len(results['errors'])}):")
        for err in results["errors"][:10]:  # Show first 10
            print(f"  - {err}")
        if len(results["errors"]) > 10:
            print(f"  ... and {len(results['errors']) - 10} more")

    print("=" * 70)

    # Add timing info
    results["start_time"] = start_time.isoformat()
    results["end_time"] = end_time.isoformat()
    results["duration_seconds"] = duration

    return results


def save_results(results: dict):
    """Save results to JSON file."""
    import json

    output_dir = REPO_ROOT / "reports" / "translation_e2e" / "2025-12-12_slides"
    output_dir.mkdir(parents=True, exist_ok=True)

    results_file = output_dir / "e2e_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nResults saved to: {results_file}")
    return results_file


if __name__ == "__main__":
    results = run_full_translation()

    if results:
        save_results(results)

        success_rate = results["successful"] / results["expected_outputs"] * 100 if results["expected_outputs"] > 0 else 0
        print(f"\nFINAL STATUS: {'PASS' if success_rate >= 95 else 'FAIL'} ({success_rate:.1f}% success rate)")
        sys.exit(0 if success_rate >= 95 else 1)
    else:
        print("\nFINAL STATUS: FAIL (initialization error)")
        sys.exit(1)
