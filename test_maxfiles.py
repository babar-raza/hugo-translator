#!/usr/bin/env python
"""
Quick test script to verify --max-files implementation.
Bypasses full CLI infrastructure to focus on engine logic.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from utils.config_loader import ConfigService
from translation_engine import TranslationEngine
from model_runtime import ModelLoader
from model_runtime.registry import ModelRegistry
from tm import TranslationMemory
from tm.l1_cache import L1Cache
from tm.l2_persistent import L2PersistentTM
from tm.l3_semantic import L3SemanticTM

def main():
    print("=== Testing --max-files implementation ===\n")

    # Setup
    config_root = Path("config")
    config_service = ConfigService(config_root=config_root)

    # Get global config for TM
    global_config = config_service.global_config
    tm_config = global_config.translation_memory

    # Initialize TM layers
    print("Initializing Translation Memory...")
    l1_cache = L1Cache(max_size=tm_config.l1_cache.max_entries)
    l2_persistent = L2PersistentTM(db_path=tm_config.l2_persistent.db_path)
    l3_semantic = L3SemanticTM(
        index_path=tm_config.l3_semantic.index_path,
        model_name=tm_config.l3_semantic.model_name,
        top_k=tm_config.l3_semantic.top_k,
        min_similarity=tm_config.l3_semantic.min_similarity
    )

    tm = TranslationMemory(
        l1_cache=l1_cache,
        l2_persistent=l2_persistent,
        l3_semantic=l3_semantic
    )
    print("TM initialized\n")

    # Initialize Model Loader
    print("Initializing Model Loader...")
    registry_path = config_root / "model_registry.yaml"
    model_registry = ModelRegistry(registry_path)
    model_loader = ModelLoader(
        model_registry=model_registry,
        device="cuda",  # or "cpu"
    )
    print(f"Model Loader initialized\n")

    # Initialize Translation Engine
    print("Initializing Translation Engine...")
    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader,
        enable_telemetry=False  # Disable to avoid hang
    )
    print("Engine initialized\n")

    # Test max_files parameter
    test_dir = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en")
    max_files = 5

    print(f"Testing translate_directory with max_files={max_files}")
    print(f"Input directory: {test_dir}")
    print(f"Site: kb.aspose.net")
    print(f"Target language: de\n")

    # Check if directory exists
    if not test_dir.exists():
        print(f"ERROR: Directory not found: {test_dir}")
        return 1

    # Count files before translation
    all_md_files = list(test_dir.glob("**/*.md"))
    print(f"Total .md files in directory: {len(all_md_files)}")

    # Run translation with max_files
    try:
        result = engine.translate_directory(
            site_id="kb.aspose.net",
            directory=test_dir,
            target_langs=["de"],
            recursive=True,
            parallel=False,  # Sequential for simpler testing
            max_files=max_files,
            skip_site_lock=False,
            trigger_type="test"
        )

        print(f"\n=== Translation Complete ===")
        print(f"Total files processed: {result.total_files}")
        print(f"Expected (with max_files): {max_files}")
        print(f"Successful: {result.successful_files}")
        print(f"Failed: {result.failed_files}")

        # Verify max_files limit was applied
        if result.total_files == max_files:
            print(f"\n✅ SUCCESS: max_files={max_files} limit was correctly applied")
            return 0
        elif result.total_files < max_files:
            print(f"\n✅ SUCCESS: Processed {result.total_files} files (fewer than max_files, likely filtered)")
            return 0
        else:
            print(f"\n❌ FAIL: Expected max {max_files} files but processed {result.total_files}")
            return 1

    except Exception as e:
        print(f"\n❌ ERROR during translation: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
