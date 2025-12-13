"""
Live Translation Test - GPU/CUDA version with actual models

Tests the Hugo Translation System on real Hugo files using actual
translation models (m2m100) from HuggingFace with CUDA acceleration.
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.translation_engine.parser import HugoParser
from src.translation_engine.extractor import SegmentExtractor
from src.translation_engine.reconstructor import MarkdownReconstructor
from src.translation_engine.validation import ValidationSuite
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.tm.l3_semantic import L3SemanticTM
from src.tm.translation_memory import TranslationMemory
from src.model_runtime import ModelRegistry, ModelLoader, HardwareDetector
from src.utils.models import SiteProfile, BodyRules, FrontmatterMode, FrontmatterRule

# Test configuration - reduced for GPU testing
TARGET_LANGS = ["es", "fa"]  # Start with 2 languages

def determine_subdomain(file_path: str) -> str:
    """Extract subdomain from file path."""
    path = Path(file_path)
    for part in path.parts:
        if ".aspose.net" in part:
            return part
    return "unknown"

def create_default_site_profile(site_id: str) -> SiteProfile:
    """Create a default site profile for testing."""
    return SiteProfile(
        site_id=site_id,
        content_roots=["content"],
        default_source_lang="en",
        target_langs=TARGET_LANGS,
        frontmatter={
            "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "sample_type": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
            "source_url": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
        },
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=["block_code", "code_inline"],
            preserve_patterns=[r"\{\{[^}]+\}\}", r"\{%[^%]+%\}"],
            placeholder_syntax=[r"\{\{<[^>]+>\}\}"],
        ),
    )

def calculate_output_path(input_path: Path, target_lang: str, output_dir: Path) -> Path:
    """
    Calculate output path based on input structure.

    Args:
        input_path: Path to input file
        target_lang: Target language code
        output_dir: Base output directory

    Returns:
        Output file path maintaining subdomain structure
    """
    # Get subdomain and create corresponding output path
    subdomain = determine_subdomain(str(input_path))

    # Create output structure: output_dir/subdomain/lang/filename
    output_path = output_dir / subdomain / target_lang / input_path.name
    return output_path

def main():
    """Main test execution."""
    print("=" * 80)
    print("LIVE TRANSLATION TEST - GPU/CUDA with M2M100")
    print("=" * 80)
    print(f"Target languages: {', '.join(TARGET_LANGS)}")
    print()

    # Setup paths
    project_root = Path(__file__).parent.parent
    samples_dir = project_root / "samples"
    output_dir = project_root / "output" / "live_translation_gpu"
    tm_base_path = project_root / "data" / "tm"
    registry_path = project_root / "config" / "model_registry.yaml"

    # Find all sample markdown files (limit to first 5 for GPU testing)
    print("Scanning for sample files...")
    input_files = list(samples_dir.glob("**/*.md"))
    input_files = [f for f in input_files if "sample-live" in f.name][:5]  # Limit to 5 files

    print(f"Found {len(input_files)} sample files to translate (limited for GPU test)")
    for file in input_files:
        subdomain = determine_subdomain(str(file))
        print(f"  - {subdomain}/{file.name}")

    if not input_files:
        print("\n[ERROR] No sample files found! Exiting.")
        return 1

    # Initialize components
    print("\nInitializing components...")
    print("  - Hardware Detection...")
    hw_detector = HardwareDetector()
    hw_info = hw_detector.detect()

    if not hw_info.gpu_available:
        print("  [ERROR] No GPU detected! This test requires CUDA GPU.")
        print("  Please use live_translation_simple.py for CPU-only testing.")
        return 1

    print(f"    Device: cuda")
    print(f"    GPU: {hw_info.gpu_name}")
    print(f"    VRAM: {hw_info.gpu_memory_gb:.1f}GB")
    print(f"    CPUs: {hw_info.cpu_count}, RAM: {hw_info.total_ram_gb:.1f}GB")

    print("  - Translation Memory...")
    tm_base_path.mkdir(parents=True, exist_ok=True)
    l1 = L1Cache(max_size=10000)
    l2 = L2PersistentTM(db_path=str(tm_base_path / "l2_live_gpu.lmdb"), max_size_mb=1024)

    # Initialize L3 with CPU to avoid memory issues
    print("  - L3 Semantic TM (CPU mode for embeddings)...")
    l3 = L3SemanticTM(
        index_path=str(tm_base_path / "l3_live_gpu.faiss"),
        embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        use_gpu=False  # Use CPU for embeddings to save VRAM
    )
    tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

    print("  - Model Registry...")
    if not registry_path.exists():
        print(f"    [ERROR] Registry not found: {registry_path}")
        print("    Cannot load translation models!")
        return 1

    registry = ModelRegistry(registry_path=str(registry_path))

    print("  - Model Loader (CUDA for translation)...")
    model_loader = ModelLoader(registry=registry, device="cuda")

    # Select and load model - use m2m100_418m
    model_id = "m2m100_418m"
    print(f"  - Loading model: {model_id}...")
    try:
        model_info = registry.get_model(model_id)
        if not model_info:
            print(f"    [ERROR] Model {model_id} not found in registry!")
            return 1

        print(f"    Model: {model_info.name}")
        print(f"    Backend: {model_info.backend}")
        print(f"    Size: {model_info.model_size_mb}MB")

        backend = model_loader.load_model(model_id)
        print("    [OK] Model loaded successfully on GPU!")
    except Exception as e:
        print(f"    [ERROR] Failed to load model: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("  - Validation Suite...")
    validator = ValidationSuite()

    print("\n[OK] All components initialized")

    # Track statistics
    stats = {
        "total_files": len(input_files),
        "total_translations": len(input_files) * len(TARGET_LANGS),
        "successful": 0,
        "failed": 0,
        "tm_hits": {"L1": 0, "L2": 0, "L3": 0, "none": 0},
        "validation_issues": 0,
        "total_segments": 0,
        "translation_time": 0.0,
        "model_translation_time": 0.0,
    }

    # Track all output files
    all_output_files = []
    translation_quality_issues = []

    # Translate each file
    for file_idx, input_path in enumerate(input_files):
        subdomain = determine_subdomain(str(input_path))
        file_name = input_path.name

        print(f"\n{'=' * 80}")
        print(f"[{file_idx + 1}/{len(input_files)}] File: {file_name} ({subdomain})")
        print(f"{'=' * 80}")

        # Read input file
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"[ERROR] Failed to read file: {e}")
            stats["failed"] += len(TARGET_LANGS)
            continue

        # Parse once
        try:
            parser = HugoParser()
            parsed = parser.parse_string(content)

            # Create site profile for this subdomain
            site_profile = create_default_site_profile(subdomain)
            extractor = SegmentExtractor(site_profile)
            segments = extractor.extract_all(parsed)
            print(f"  Extracted {len(segments)} segments to translate")
            stats["total_segments"] += len(segments)
        except Exception as e:
            print(f"[ERROR] Failed to parse file: {e}")
            import traceback
            traceback.print_exc()
            stats["failed"] += len(TARGET_LANGS)
            continue

        for target_lang in TARGET_LANGS:
            print(f"\n  Translating to {target_lang}...")

            try:
                start_time = time.time()

                # Translate segments - build translation dictionary
                translations = {}
                tm_stats = {"L1": 0, "L2": 0, "L3": 0, "none": 0}
                model_translation_time = 0.0

                for i, seg in enumerate(segments):
                    if (i + 1) % 10 == 0:
                        print(f"    Progress: {i+1}/{len(segments)} segments...", flush=True)

                    source_text = seg.source_text
                    segment_id = seg.id

                    # Try TM first
                    tm_result = tm.lookup(subdomain, "en", target_lang, source_text)
                    if tm_result and tm_result.hit:
                        translations[segment_id] = tm_result.translation
                        # Track which layer hit
                        if hasattr(tm_result, 'layer'):
                            tm_stats[tm_result.layer] = tm_stats.get(tm_result.layer, 0) + 1
                        else:
                            tm_stats["L1"] += 1
                    else:
                        # Use loaded model to translate
                        model_start = time.time()
                        translation_results = backend.translate([source_text], "en", target_lang)
                        model_translation_time += time.time() - model_start

                        translated_text = translation_results[0] if translation_results else source_text

                        # Store in TM for future use
                        tm.store(subdomain, "en", target_lang, source_text, translated_text)
                        translations[segment_id] = translated_text
                        tm_stats["none"] += 1

                translation_time = time.time() - start_time
                stats["translation_time"] += translation_time
                stats["model_translation_time"] += model_translation_time

                print(f"    Translation stats: {tm_stats['L1']+tm_stats['L2']+tm_stats['L3']} TM hits, {tm_stats['none']} model translations")
                print(f"    Model GPU time: {model_translation_time:.2f}s")

                # Update global TM stats
                for layer, count in tm_stats.items():
                    stats["tm_hits"][layer] += count

                # Reconstruct
                reconstructor = MarkdownReconstructor(site_profile)
                translated_content = reconstructor.reconstruct_document(parsed, translations, target_lang)

                # Validate translation
                validation_result = validator.validate(content, translated_content)
                if not validation_result.success:
                    stats["validation_issues"] += len(validation_result.issues)
                    translation_quality_issues.append({
                        "file": str(input_path),
                        "target_lang": target_lang,
                        "issues": validation_result.issues
                    })
                    print(f"    [WARNING] {len(validation_result.issues)} validation issues")

                # Calculate output path
                output_path = calculate_output_path(input_path, target_lang, output_dir)

                # Create output directory
                output_path.parent.mkdir(parents=True, exist_ok=True)

                # Write output
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(translated_content)

                print(f"    [OK] Saved to: {output_path.relative_to(project_root)}")
                print(f"    Total time: {translation_time:.2f}s")

                all_output_files.append(str(output_path))
                stats["successful"] += 1

            except Exception as e:
                import traceback
                print(f"    [ERROR] {str(e)}")
                traceback.print_exc()
                stats["failed"] += 1

    # Generate translation quality report
    print(f"\n{'=' * 80}")
    print("Generating Quality Report")
    print(f"{'=' * 80}")

    reports_dir = project_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    quality_report_path = reports_dir / "translation_quality_gpu.md"

    with open(quality_report_path, 'w', encoding='utf-8') as f:
        f.write("# Translation Quality Report (GPU)\n\n")
        f.write(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Hardware:** {hw_info.gpu_name} ({hw_info.gpu_memory_gb:.1f}GB VRAM)\n\n")
        f.write(f"**Model:** {model_id} (CUDA accelerated)\n\n")

        f.write("## Summary\n\n")
        f.write(f"- **Total Files:** {stats['total_files']}\n")
        f.write(f"- **Total Translations:** {stats['total_translations']}\n")
        f.write(f"- **Successful:** {stats['successful']}\n")
        f.write(f"- **Failed:** {stats['failed']}\n")
        f.write(f"- **Total Segments:** {stats['total_segments']}\n")
        f.write(f"- **Validation Issues:** {stats['validation_issues']}\n\n")

        f.write("## Translation Memory Performance\n\n")
        total_tm_lookups = sum(stats['tm_hits'].values())
        if total_tm_lookups > 0:
            f.write(f"- **Total Lookups:** {total_tm_lookups}\n")
            f.write(f"- **L1 Cache Hits:** {stats['tm_hits']['L1']} ({100*stats['tm_hits']['L1']/total_tm_lookups:.1f}%)\n")
            f.write(f"- **L2 Persistent Hits:** {stats['tm_hits']['L2']} ({100*stats['tm_hits']['L2']/total_tm_lookups:.1f}%)\n")
            f.write(f"- **L3 Semantic Hits:** {stats['tm_hits']['L3']} ({100*stats['tm_hits']['L3']/total_tm_lookups:.1f}%)\n")
            f.write(f"- **GPU Model Translations:** {stats['tm_hits']['none']} ({100*stats['tm_hits']['none']/total_tm_lookups:.1f}%)\n")
            tm_hit_rate = (stats['tm_hits']['L1'] + stats['tm_hits']['L2'] + stats['tm_hits']['L3']) / total_tm_lookups
            f.write(f"- **Overall TM Hit Rate:** {100*tm_hit_rate:.1f}%\n\n")
        else:
            f.write("No TM lookups recorded.\n\n")

        f.write("## Performance Metrics\n\n")
        f.write(f"- **Total Translation Time:** {stats['translation_time']:.2f}s\n")
        f.write(f"- **GPU Model Time:** {stats['model_translation_time']:.2f}s\n")
        if stats['successful'] > 0:
            f.write(f"- **Avg Time per Translation:** {stats['translation_time']/stats['successful']:.2f}s\n")
        if stats['total_segments'] > 0:
            f.write(f"- **Avg Time per Segment:** {1000*stats['translation_time']/stats['total_segments']:.0f}ms\n")
        if stats['tm_hits']['none'] > 0:
            f.write(f"- **Avg GPU Model Time per Segment:** {1000*stats['model_translation_time']/stats['tm_hits']['none']:.0f}ms\n\n")

        if translation_quality_issues:
            f.write("## Validation Issues\n\n")
            for issue_entry in translation_quality_issues:
                f.write(f"### {issue_entry['file']} → {issue_entry['target_lang']}\n\n")
                for issue in issue_entry['issues']:
                    f.write(f"- **{issue.severity.name}**: {issue.message}\n")
                    if issue.location:
                        f.write(f"  - Location: {issue.location}\n")
                f.write("\n")
        else:
            f.write("## Validation Issues\n\n")
            f.write("No validation issues detected. All translations passed quality checks.\n\n")

        f.write("## Output Files\n\n")
        for output_file in all_output_files:
            f.write(f"- `{output_file}`\n")

    print(f"Quality report saved to: {quality_report_path}")

    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total translations: {stats['total_translations']}")
    print(f"Successful: {stats['successful']}")
    print(f"Failed: {stats['failed']}")
    print(f"Validation issues: {stats['validation_issues']}")
    print(f"Total segments: {stats['total_segments']}")
    print(f"Translation time: {stats['translation_time']:.2f}s")
    print(f"GPU model time: {stats['model_translation_time']:.2f}s")

    total_tm_lookups = sum(stats['tm_hits'].values())
    if total_tm_lookups > 0:
        tm_hit_rate = (stats['tm_hits']['L1'] + stats['tm_hits']['L2'] + stats['tm_hits']['L3']) / total_tm_lookups
        print(f"TM hit rate: {100*tm_hit_rate:.1f}%")

    print(f"\nOutput directory: {output_dir}")
    print(f"Quality report: {quality_report_path}")
    print()

    if stats["failed"] == 0:
        print("[SUCCESS] All GPU translations completed successfully!")
        return 0
    else:
        print(f"[WARNING] {stats['failed']} translations failed")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
