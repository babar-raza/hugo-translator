#!/usr/bin/env python3
"""
E2E Dry Run Script for slides translation test.

Tests translation pipeline on a single file to one locale.
"""

import os
import sys
import time
from pathlib import Path

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

def run_dry_run():
    """Run dry run translation test."""

    print("=" * 60)
    print("E2E DRY RUN - Translation Pipeline Test")
    print("=" * 60)

    # Import components
    print("\n[1/5] Importing components...")
    try:
        import torch

        from src.model_runtime import ModelLoader
        from src.model_runtime.registry import ModelRegistry
        from src.tm import TranslationMemory
        from src.tm.l1_cache import L1Cache
        from src.tm.l2_persistent import L2PersistentTM
        from src.tm.l3_semantic import L3SemanticTM
        from src.translation_engine import TranslationEngine
        from src.utils.config_loader import ConfigService
        print("   OK: All components imported successfully")
    except ImportError as e:
        print(f"   ERROR: Import failed: {e}")
        return False

    # Initialize components
    print("\n[2/5] Initializing components...")
    try:
        config_path = REPO_ROOT / "config"
        config_service = ConfigService(config_path)
        print(f"   OK: ConfigService loaded from {config_path}")

        # Initialize TM layers
        l1_cache = L1Cache(max_size=10000)
        print("   OK: L1Cache initialized (max_size=10000)")

        lmdb_path = REPO_ROOT / "data" / "tm" / "l2_lmdb"
        lmdb_path.parent.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(lmdb_path))
        print(f"   OK: L2PersistentTM initialized at {lmdb_path}")

        faiss_path = REPO_ROOT / "data" / "tm" / "l3_faiss"
        faiss_path.mkdir(parents=True, exist_ok=True)
        l3_semantic = L3SemanticTM(index_path=str(faiss_path))
        print(f"   OK: L3SemanticTM initialized at {faiss_path}")

        tm = TranslationMemory(l1_cache=l1_cache, l2_persistent=l2_persistent, l3_semantic=l3_semantic)
        print("   OK: TranslationMemory initialized with all 3 layers")

        # Initialize ModelLoader with registry
        registry_path = config_path / "model_registry.yaml"
        model_registry = ModelRegistry(registry_path)

        # Detect device
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"   OK: Device detected: {device}")
        if device == "cuda":
            print(f"   OK: GPU: {torch.cuda.get_device_name(0)}")

        model_loader = ModelLoader(registry=model_registry, device=device)
        print("   OK: ModelLoader initialized with registry")

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            enable_telemetry=True
        )
        print("   OK: TranslationEngine initialized")
    except Exception as e:
        print(f"   ERROR: Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Debug: Check site profile
    site_profile = config_service.get_site_profile("products.aspose.net")
    print(f"   DEBUG: Site profile loaded: {site_profile.site_id}")
    print(f"   DEBUG: output_layout: {site_profile.output_layout}")
    if site_profile.output_layout:
        print(f"   DEBUG: per_language_folders: {site_profile.output_layout.per_language_folders}")
    print(f"   DEBUG: default_source_lang: {site_profile.default_source_lang}")

    # Test file path
    source_dir = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en")
    test_file = source_dir / "_index.md"

    print(f"\n[3/5] Testing with file: {test_file}")
    if not test_file.exists():
        print(f"   ERROR: File not found: {test_file}")
        return False
    print(f"   OK: File exists ({test_file.stat().st_size} bytes)")

    # Single locale dry run
    target_lang = "de"
    print(f"\n[4/5] Translating to '{target_lang}'...")

    start_time = time.time()
    try:
        result = engine.translate_file(
            site_id="products.aspose.net",
            file_path=test_file,
            target_langs=[target_lang],
        )
        duration = time.time() - start_time

        print("\n   Results:")
        print(f"   - Success: {result.success}")
        print(f"   - Duration: {duration:.2f}s")
        print(f"   - Total segments: {result.stats.total_segments}")
        print(f"   - TM hits: {result.stats.tm_hits}")
        print(f"   - Translated segments: {result.stats.translated_segments}")
        print(f"   - Tokens input: {result.stats.tokens_input}")
        print(f"   - Tokens output: {result.stats.tokens_output}")

        if result.outputs:
            for lang, output_path in result.outputs.items():
                print(f"   - Output [{lang}]: {output_path}")

        if result.errors:
            print(f"   - Errors: {result.errors}")

        if result.warnings:
            print(f"   - Warnings: {result.warnings}")

    except Exception as e:
        print(f"   ERROR: Translation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Verify output
    print("\n[5/5] Verifying output...")
    if result.success and result.outputs:
        output_path = result.outputs.get(target_lang)
        if output_path and output_path.exists():
            content = output_path.read_text(encoding='utf-8')
            print(f"   OK: Output file exists ({len(content)} chars)")

            # Basic validation
            if "---" in content and "title:" in content:
                print("   OK: Frontmatter detected")
            else:
                print("   WARNING: Frontmatter may be missing")

            if len(content) > 100:
                print("   OK: Content appears substantial")
            else:
                print("   WARNING: Content seems too short")

            # Show preview
            print("\n   Preview (first 500 chars):")
            print("-" * 40)
            print(content[:500])
            print("-" * 40)

            return True
        else:
            print(f"   ERROR: Output file not found at {output_path}")
            return False
    else:
        print("   ERROR: Translation failed")
        return False


if __name__ == "__main__":
    success = run_dry_run()
    print("\n" + "=" * 60)
    if success:
        print("DRY RUN: PASSED")
    else:
        print("DRY RUN: FAILED")
    print("=" * 60)
    sys.exit(0 if success else 1)
