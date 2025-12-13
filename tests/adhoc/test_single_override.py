"""
Test single file translation with override-mode refresh.
This verifies that the TM cache override correctly bypasses corrupted cached translations.
"""
import sys
sys.path.insert(0, 'src')

import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    # Import after path setup
    from translation_engine import TranslationEngine
    from tm import TranslationMemory
    from model_runtime import ModelLoader
    from utils.config_loader import ConfigService

    print("=" * 60)
    print("Testing TM Cache Override with refresh mode")
    print("=" * 60)

    # Setup paths
    input_file = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-converter\_index.md")
    output_dir = Path("output/override-test-bg")
    site_id = "products.aspose.net"
    target_lang = "bg"

    if not input_file.exists():
        print(f"ERROR: Input file not found: {input_file}")
        return 1

    print(f"\nInput file: {input_file}")
    print(f"Output dir: {output_dir}")
    print(f"Site ID: {site_id}")
    print(f"Target language: {target_lang}")
    print(f"Override mode: refresh")
    print()

    # Initialize components
    config_path = Path("config")
    config_service = ConfigService(config_path)
    site_profile = config_service.get_site_profile(site_id)

    print(f"Site profile loaded: {site_profile.site_id}")
    print(f"Preserve patterns: {site_profile.body.preserve_patterns}")
    print()

    # Initialize TM
    tm_path = Path("data/tm")
    tm = TranslationMemory(
        l2_path=tm_path / "l2_lmdb",
        l3_path=tm_path / "l3_faiss",
        site_profile=site_profile,
    )

    # Initialize model loader
    model_loader = ModelLoader()

    # Create engine WITH override-mode refresh
    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader,
        enable_validation=True,
        override_mode="refresh",  # <-- This bypasses cache for fresh translations
    )

    print("Translating with override-mode=refresh...")
    print("(This will bypass cached translations and force fresh translations)")
    print()

    # Translate single file
    result = engine.translate_file(
        input_path=input_file,
        output_dir=output_dir,
        site_id=site_id,
        target_lang=target_lang,
        source_lang="en",
    )

    print()
    print("=" * 60)
    print("Translation Result:")
    print("=" * 60)
    print(f"Status: {result.status}")
    print(f"Output path: {result.output_path}")
    print(f"Segments: {result.stats.total_segments if result.stats else 'N/A'}")

    # Get override stats
    override_stats = engine.get_override_stats()
    print()
    print("Override Stats:")
    print(f"  Mode: {override_stats.get('mode', 'unknown')}")
    print(f"  Bypasses: {override_stats.get('override_bypasses', 0)}")
    print(f"  Force translates: {override_stats.get('force_translates', 0)}")
    print(f"  Cache updates: {override_stats.get('cache_updates', 0)}")

    # Verify output
    if result.output_path and Path(result.output_path).exists():
        print()
        print("=" * 60)
        print("Checking output for NuGet link:")
        print("=" * 60)

        with open(result.output_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for corrupted link pattern
        if "[NuGet] ( " in content or "Aspose, Slides" in content:
            print("FAIL: Output still has corrupted NuGet link!")
            print("The override-mode refresh did NOT work correctly.")

            # Show the problematic section
            for line in content.split('\n'):
                if 'NuGet' in line:
                    print(f"  Found: {line[:150]}...")
        else:
            # Check for correct link
            if "[NuGet](https://www.nuget.org/packages/Aspose.Slides.NET/)" in content:
                print("PASS: Output has correct NuGet link!")
            else:
                print("WARN: NuGet link format may have changed")
                for line in content.split('\n'):
                    if 'NuGet' in line:
                        print(f"  Found: {line[:150]}...")

    return 0

if __name__ == "__main__":
    sys.exit(main())
