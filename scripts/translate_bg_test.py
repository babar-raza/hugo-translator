#!/usr/bin/env python
"""Quick BG translation test to verify structure preservation fix."""

import sys
import os
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, 'src')

REPO_ROOT = Path(__file__).parent.resolve()
SOURCE_DIR = Path("D:/onedrive/Documents/GitHub/aspose.net/content/products.aspose.net/slides/en")

def main():
    import torch
    from src.translation_engine import TranslationEngine
    from src.utils.config_loader import ConfigService
    from src.tm import TranslationMemory
    from src.tm.l1_cache import L1Cache
    from src.tm.l2_persistent import L2PersistentTM
    from src.tm.l3_semantic import L3SemanticTM
    from src.model_runtime import ModelLoader
    from src.model_runtime.registry import ModelRegistry

    print("=" * 70)
    print("BG TRANSLATION TEST - Structure Preservation Verification")
    print("=" * 70)

    # Initialize components
    print("\n[1/4] Initializing components...")
    config_path = REPO_ROOT / "config"
    config_service = ConfigService(config_path)

    # Simplified TM init
    l1_cache = L1Cache(max_size=1000)
    lmdb_path = REPO_ROOT / "data" / "tm" / "l2_lmdb"
    lmdb_path.parent.mkdir(parents=True, exist_ok=True)
    l2_persistent = L2PersistentTM(str(lmdb_path))
    faiss_path = REPO_ROOT / "data" / "tm" / "l3_faiss"
    faiss_path.mkdir(parents=True, exist_ok=True)
    l3_semantic = L3SemanticTM(index_path=str(faiss_path))
    tm = TranslationMemory(l1_cache=l1_cache, l2_persistent=l2_persistent, l3_semantic=l3_semantic)

    # Model loader
    registry_path = config_path / "model_registry.yaml"
    model_registry = ModelRegistry(registry_path)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_loader = ModelLoader(registry=model_registry, device=device)

    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader,
        enable_telemetry=False
    )
    print("   OK: Engine initialized")

    # Find test files
    print("\n[2/4] Finding test files...")
    md_files = sorted(SOURCE_DIR.glob("**/_index.md"))[:3]
    print(f"   Found {len(md_files)} files to translate")

    # Translate to BG
    print("\n[3/4] Translating to BG...")
    for i, file in enumerate(md_files, 1):
        rel_path = file.relative_to(SOURCE_DIR)
        print(f"   [{i}/{len(md_files)}] {rel_path}...")
        try:
            result = engine.translate_file(
                site_id='products.aspose.net',
                file_path=file,
                target_langs=['bg']
            )
            print(f"       Success: {result.success}")
            if result.outputs:
                for lang, output_path in result.outputs.items():
                    print(f"       Output: {output_path}")
        except Exception as e:
            print(f"       Error: {e}")
            import traceback
            traceback.print_exc()

    # Validate structure
    print("\n[4/4] Validating BG structure...")
    bg_dir = Path("D:/onedrive/Documents/GitHub/aspose.net/content/products.aspose.net/slides/bg")

    total_drift = 0
    files_checked = 0
    passing = 0

    for en_file in md_files:
        rel_path = en_file.relative_to(SOURCE_DIR)
        bg_file = bg_dir / rel_path

        if bg_file.exists():
            en_content = en_file.read_text(encoding='utf-8')
            bg_content = bg_file.read_text(encoding='utf-8')

            en_lines = len(en_content.strip().split('\n'))
            bg_lines = len(bg_content.strip().split('\n'))
            drift = abs(en_lines - bg_lines) / max(en_lines, 1) * 100

            # Count YAML comments
            def count_yaml_comments(content):
                lines = content.split('\n')
                in_fm = False
                count = 0
                for line in lines:
                    if line.strip() == '---':
                        in_fm = not in_fm
                        if not in_fm:
                            break
                    elif in_fm and line.strip().startswith('#'):
                        count += 1
                return count

            en_comments = count_yaml_comments(en_content)
            bg_comments = count_yaml_comments(bg_content)

            status = "PASS" if drift < 20 and en_comments == bg_comments else "FAIL"
            if status == "PASS":
                passing += 1

            print(f"   {rel_path}: {status}")
            print(f"       Lines: EN={en_lines} BG={bg_lines} Drift={drift:.1f}%")
            print(f"       Comments: EN={en_comments} BG={bg_comments}")

            total_drift += drift
            files_checked += 1

    print("\n" + "=" * 70)
    print("SUMMARY:")
    print(f"   Files checked: {files_checked}")
    print(f"   Passing: {passing}")
    if files_checked > 0:
        avg_drift = total_drift / files_checked
        print(f"   Average drift: {avg_drift:.1f}%")
        if avg_drift < 10 and passing == files_checked:
            print("\n   *** STRUCTURE DRIFT IS COMPLETELY FIXED! ***")
        elif avg_drift < 20:
            print("\n   *** STRUCTURE DRIFT IS MOSTLY FIXED ***")
        else:
            print("\n   *** STRUCTURE DRIFT STILL PRESENT ***")
    print("=" * 70)

if __name__ == "__main__":
    main()
