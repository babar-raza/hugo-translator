"""
Live Translation Test - Real Aspose.net files with CUDA

Tests the Hugo Translation System on real content files from aspose.net repository.
Translates to: es, fa, el, ja, zh, ru using GPU (CUDA).

Output rules:
- For non-blog subdomains: Replace /en/ with /{lang}/
- For blog.aspose.net: Keep same folder, append language (e.g., index.es.md)
"""

import os
import sys
from pathlib import Path
from typing import List, Tuple, Dict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.translation_engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.tm import TranslationMemory
from src.model_runtime import ModelRegistry
from src.observability.logger import StructuredLogger

# Test configuration
TARGET_LANGS = ["es", "fa", "el", "ja", "zh", "ru"]
USE_GPU = True  # Force GPU usage

# Input files (absolute paths)
INPUT_FILES = [
    r"D:\onedrive\Documents\GitHub\aspose.net\content\about.aspose.net\en\acquisition\index.md",
    r"D:\onedrive\Documents\GitHub\aspose.net\content\blog.aspose.net\words\extract-word-document-text-dotnet-csharp\index.md",
    r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\words\en\markdown-file-processor\_index.md",
    r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\words\en\document-converter\doc-to-docx.md",
    r"D:\onedrive\Documents\GitHub\aspose.net\content\reference.aspose.net\cells\en\_index.md",
    r"D:\onedrive\Documents\GitHub\aspose.net\content\reference.aspose.net\cells\en\Aspose.Cells.HtmlSaveOptions.md",
    r"D:\onedrive\Documents\GitHub\aspose.net\content\websites.aspose.net\en\aspose\_index.md",
]

def determine_subdomain(file_path: str) -> str:
    """Extract subdomain from file path."""
    path = Path(file_path)
    for part in path.parts:
        if ".aspose.net" in part:
            return part
    return "unknown"

def calculate_output_path(input_path: str, target_lang: str) -> str:
    """
    Calculate output path based on subdomain rules.

    Rules:
    - blog.aspose.net: Same folder, append language to filename (index.es.md)
    - All others: Replace /en/ with /{lang}/
    """
    path = Path(input_path)
    subdomain = determine_subdomain(input_path)

    if subdomain == "blog.aspose.net":
        # For blog: Same folder, filename with language suffix
        # e.g., index.md -> index.es.md
        stem = path.stem  # "index"
        suffix = path.suffix  # ".md"
        new_name = f"{stem}.{target_lang}{suffix}"
        return str(path.parent / new_name)
    else:
        # For others: Replace /en/ with /{lang}/
        path_str = str(path)
        if "\\en\\" in path_str:
            return path_str.replace("\\en\\", f"\\{target_lang}\\")
        elif "/en/" in path_str:
            return path_str.replace("/en/", f"/{target_lang}/")
        else:
            # If no /en/, put translation next to source
            stem = path.stem
            suffix = path.suffix
            new_name = f"{stem}.{target_lang}{suffix}"
            return str(path.parent / new_name)

def translate_file(
    engine: TranslationEngine,
    input_path: str,
    target_lang: str,
    subdomain: str
) -> Tuple[bool, str, str]:
    """
    Translate a single file.

    Returns:
        (success, output_path, error_message)
    """
    try:
        # Read input file
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Translate
        result = engine.translate_file(
            content=content,
            source_lang="en",
            target_lang=target_lang,
            site_profile=subdomain  # Use subdomain as site_id
        )

        if not result.success:
            return False, "", f"Translation failed: {', '.join([str(v) for v in result.validation_issues])}"

        # Calculate output path
        output_path = calculate_output_path(input_path, target_lang)

        # Create output directory if needed
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write output
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result.translated_content)

        return True, output_path, ""

    except Exception as e:
        return False, "", str(e)

def main():
    """Main test execution."""
    print("=" * 80)
    print("LIVE TRANSLATION TEST - Aspose.net Real Files")
    print("=" * 80)
    print(f"Target languages: {', '.join(TARGET_LANGS)}")
    print(f"GPU mode: {USE_GPU}")
    print()

    # Initialize logger
    logger = StructuredLogger(name="live-test")

    # Load configuration
    print("Loading configuration...")
    config_root = Path(__file__).parent.parent / "config"
    config_service = ConfigService(config_root=config_root)

    # Initialize Translation Memory
    print("Initializing Translation Memory...")
    tm_path = Path(__file__).parent.parent / "data" / "tm"
    tm = TranslationMemory(tm_path=str(tm_path))

    # Initialize Model Registry
    print("Initializing Model Registry...")
    registry_path = Path(__file__).parent.parent / "config" / "model_registry.yaml"
    registry = ModelRegistry(
        registry_path=str(registry_path),
        force_device="cuda" if USE_GPU else "cpu"
    )

    # Get best available model for GPU
    print("Loading translation model...")
    model_info = registry.select_model(
        source_lang="en",
        target_lang="es",  # Start with Spanish, will work for all
        preferred_backend="transformers",  # HuggingFace for GPU
        preferred_hardware="gpu" if USE_GPU else "cpu"
    )
    print(f"Selected model: {model_info.model_id} on {model_info.hardware}")

    # Initialize Translation Engine
    print("Initializing Translation Engine...")
    engine = TranslationEngine(
        config_service=config_service,
        translation_memory=tm,
        model_registry=registry,
        logger=logger
    )

    # Track all output files
    all_output_files = []

    # Check which files exist
    print("\nChecking input files...")
    existing_files = []
    for file_path in INPUT_FILES:
        if Path(file_path).exists():
            existing_files.append(file_path)
            subdomain = determine_subdomain(file_path)
            print(f"  ✓ {subdomain}: {Path(file_path).name}")
        else:
            print(f"  ✗ Not found: {file_path}")

    if not existing_files:
        print("\n❌ No input files found! Exiting.")
        return

    print(f"\nFound {len(existing_files)} files to translate")
    print()

    # Translate each file
    total = len(existing_files) * len(TARGET_LANGS)
    current = 0
    success_count = 0
    failed_count = 0

    for input_path in existing_files:
        subdomain = determine_subdomain(input_path)
        file_name = Path(input_path).name

        print(f"\n{'=' * 80}")
        print(f"File: {file_name} ({subdomain})")
        print(f"{'=' * 80}")

        for target_lang in TARGET_LANGS:
            current += 1
            print(f"[{current}/{total}] Translating to {target_lang}...", end=" ", flush=True)

            success, output_path, error = translate_file(
                engine=engine,
                input_path=input_path,
                target_lang=target_lang,
                subdomain=subdomain
            )

            if success:
                print(f"✓ {output_path}")
                all_output_files.append(output_path)
                success_count += 1
            else:
                print(f"✗ Failed: {error}")
                failed_count += 1

    # Write all file locations to tests/live.txt
    output_list_file = Path(__file__).parent / "live.txt"
    print(f"\n{'=' * 80}")
    print(f"Writing file locations to {output_list_file}")
    print(f"{'=' * 80}")

    with open(output_list_file, 'w', encoding='utf-8') as f:
        f.write("# Live Translation Test - Output Files\n")
        f.write(f"# Generated: {len(all_output_files)} files\n")
        f.write(f"# Success: {success_count}, Failed: {failed_count}\n")
        f.write(f"# Target languages: {', '.join(TARGET_LANGS)}\n")
        f.write(f"# GPU mode: {USE_GPU}\n\n")

        # Group by subdomain
        by_subdomain: Dict[str, List[str]] = {}
        for output_path in all_output_files:
            subdomain = determine_subdomain(output_path)
            if subdomain not in by_subdomain:
                by_subdomain[subdomain] = []
            by_subdomain[subdomain].append(output_path)

        for subdomain, paths in sorted(by_subdomain.items()):
            f.write(f"\n## {subdomain}\n\n")
            for path in sorted(paths):
                f.write(f"{path}\n")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total translations: {total}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failed_count}")
    print(f"Output list: {output_list_file}")
    print()

    if failed_count == 0:
        print("✓ All translations completed successfully!")
    else:
        print(f"⚠ {failed_count} translations failed")

    print("=" * 80)

if __name__ == "__main__":
    main()
