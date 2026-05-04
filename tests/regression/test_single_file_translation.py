"""Test single file translation with array reconstruction fix."""
import os
import sys
from pathlib import Path

# Add src to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_single_translation():
    """Test translating the presentation-to-pdf-converter file."""
    import torch

    from src.model_runtime import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.tm import TranslationMemory
    from src.tm.l1_cache import L1Cache
    from src.tm.l2_persistent import L2PersistentTM
    from src.tm.l3_semantic import L3SemanticTM
    from src.translation_engine import TranslationEngine
    from src.utils.config_loader import ConfigService

    print("=" * 80)
    print("TESTING: Single File Translation with Array Fix")
    print("=" * 80)

    # Initialize components
    print("\n[1/4] Initializing components...")
    config_path = REPO_ROOT / "config"
    config_service = ConfigService(config_path)
    print("   OK: ConfigService loaded")

    # Initialize TM layers
    l1_cache = L1Cache(max_size=10000)
    print("   OK: L1Cache initialized")

    lmdb_path = REPO_ROOT / "data" / "tm" / "l2_lmdb"
    l2_persistent = L2PersistentTM(str(lmdb_path), max_size_mb=20)
    print("   OK: L2PersistentTM initialized")

    # Initialize L3
    l3_index_dir = REPO_ROOT / "data" / "tm" / "l3_faiss"
    l3_semantic = L3SemanticTM(index_path=str(l3_index_dir))
    print("   OK: L3SemanticTM initialized")

    # Create TM
    tm = TranslationMemory(
        l1_cache=l1_cache,
        l2_persistent=l2_persistent,
        l3_semantic=l3_semantic
    )
    print("   OK: TranslationMemory initialized")

    # Check GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"   OK: Device: {device}")
    if device == "cuda":
        gpu_name = torch.cuda.get_device_name(0)
        print(f"   OK: GPU: {gpu_name}")

    # Initialize model registry and loader
    registry_path = config_path / "model_registry.yaml"
    registry = ModelRegistry(registry_path)
    model_loader = ModelLoader(registry=registry, device=device)
    print("   OK: ModelLoader initialized")

    # Initialize translation engine
    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader
    )
    print("   OK: TranslationEngine initialized")

    # Test file
    test_file = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-to-pdf-converter\_index.md")

    print("\n[2/4] Translating test file...")
    print(f"   Source: {test_file}")
    print("   Target: de (German)")

    result = engine.translate_file(
        site_id="products.aspose.net",
        file_path=test_file,
        target_langs=["de"],
    )

    print("\n[3/4] Translation Results:")
    print(f"   Success: {result.success}")
    print(f"   Duration: {result.stats.duration_seconds:.2f}s")
    print(f"   Segments: {result.stats.total_segments}")
    for lang, output_path in result.outputs.items():
        print(f"   {lang}: {output_path}")

    # Verify output
    print("\n[4/4] Verifying output...")
    if result.success and "de" in result.outputs:
        output_file = result.outputs["de"]
        if output_file.exists():
            content = output_file.read_text(encoding="utf-8")

            # Check for translated array content
            if "Konvertieren Sie PowerPoint" in content or "Converting Presentations" in content:
                # Check body.block structure
                if "body:" in content and "block:" in content:
                    # Parse to check array structure
                    import yaml
                    try:
                        # Extract frontmatter
                        parts = content.split("---")
                        if len(parts) >= 3:
                            fm_text = parts[1]
                            fm = yaml.safe_load(fm_text)

                            if "body" in fm and "block" in fm["body"] and isinstance(fm["body"]["block"], list):
                                print("   [PASS] body.block is an array")

                                # Check if array elements have translations
                                first_block = fm["body"]["block"][0]
                                if "title_left" in first_block:
                                    title = first_block["title_left"]
                                    if "Converting" in title:
                                        print(f"   [FAIL] title_left NOT translated: {title[:50]}")
                                    else:
                                        print(f"   [PASS] title_left translated: {title[:50]}...")

                                if "content_left" in first_block:
                                    content_val = first_block["content_left"]
                                    if isinstance(content_val, str):
                                        if "Add the Aspose" in content_val:
                                            print("   [FAIL] content_left NOT translated")
                                        else:
                                            print(f"   [PASS] content_left translated: {content_val[:50]}...")
                            else:
                                print("   [FAIL] body.block is not an array")
                    except Exception as e:
                        print(f"   [ERROR] Failed to parse YAML: {e}")
                else:
                    print("   [FAIL] body.block not found in output")
            else:
                print("   [WARNING] Could not determine translation status")

            print(f"\n   Output file size: {len(content)} chars")
        else:
            print(f"   [FAIL] Output file does not exist: {output_file}")
    else:
        print("   [FAIL] Translation failed")

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    test_single_translation()
