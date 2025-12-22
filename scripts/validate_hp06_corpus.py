#!/usr/bin/env python3
"""
HEAL-HP06-04: Real-World Corpus Validation

Uses the hugo-translator system's TranslationEngine with TM caching
to validate baseline preservation metrics.
"""

import sys
import random
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional

# Add project root to path for src.* imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.translation_engine import TranslationEngine
from src.tm import L1Cache, L2PersistentTM, TranslationMemory
from src.model_runtime import ModelLoader
from src.model_runtime.registry import ModelRegistry
from src.utils.config_loader import ConfigService


@dataclass
class PreservationMetrics:
    """Metrics for measuring preservation quality."""
    file_path: str
    source_links: int
    target_links: int
    link_preservation: float

    source_code_blocks: int
    target_code_blocks: int
    code_block_preservation: float

    source_images: int
    target_images: int
    image_preservation: float

    source_bold: int
    target_bold: int
    source_italic: int
    target_italic: int
    formatting_preservation: float


def count_markdown_elements(content: str) -> Dict[str, int]:
    """Count markdown structural elements."""
    # Count links [text](url)
    links = len(re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content))

    # Count code blocks ```
    code_blocks = len(re.findall(r'```[^`]*```', content, re.DOTALL))

    # Count images ![alt](url)
    images = len(re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', content))

    # Count bold **text**
    bold = len(re.findall(r'\*\*[^*]+\*\*', content))

    # Count italic *text*
    italic = len(re.findall(r'(?<!\*)\*(?!\*)([^*]+)\*(?!\*)', content))

    return {
        "links": links,
        "code_blocks": code_blocks,
        "images": images,
        "bold": bold,
        "italic": italic
    }


def calculate_preservation(source_content: str, translated_content: str, file_path: str) -> PreservationMetrics:
    """Calculate preservation metrics for a translation."""
    source_counts = count_markdown_elements(source_content)
    target_counts = count_markdown_elements(translated_content)

    # Calculate preservation percentages
    link_pres = (target_counts["links"] / max(source_counts["links"], 1)) * 100
    code_pres = (target_counts["code_blocks"] / max(source_counts["code_blocks"], 1)) * 100
    image_pres = (target_counts["images"] / max(source_counts["images"], 1)) * 100

    # Formatting preservation (average of bold and italic)
    bold_pres = (target_counts["bold"] / max(source_counts["bold"], 1)) * 100
    italic_pres = (target_counts["italic"] / max(source_counts["italic"], 1)) * 100
    format_pres = (bold_pres + italic_pres) / 2 if (source_counts["bold"] + source_counts["italic"]) > 0 else 100.0

    return PreservationMetrics(
        file_path=file_path,
        source_links=source_counts["links"],
        target_links=target_counts["links"],
        link_preservation=link_pres,
        source_code_blocks=source_counts["code_blocks"],
        target_code_blocks=target_counts["code_blocks"],
        code_block_preservation=code_pres,
        source_images=source_counts["images"],
        target_images=target_counts["images"],
        image_preservation=image_pres,
        source_bold=source_counts["bold"],
        target_bold=target_counts["bold"],
        source_italic=source_counts["italic"],
        target_italic=target_counts["italic"],
        formatting_preservation=format_pres
    )


def setup_translation_engine(config_dir: Path, tm_path: Path) -> TranslationEngine:
    """Initialize the translation engine with TM caching."""
    # Initialize config service
    config_service = ConfigService(config_root=config_dir)

    # Initialize TM layers
    l1_cache = L1Cache(max_size=10000)
    l2_persistent = L2PersistentTM(db_path=tm_path)

    # Create unified TM
    tm = TranslationMemory(
        l1_cache=l1_cache,
        l2_persistent=l2_persistent,
    )

    # Initialize model registry and loader
    registry_path = config_dir / "model_registry.yaml"
    registry = ModelRegistry(registry_path=registry_path)
    model_loader = ModelLoader(registry=registry)

    # Create translation engine
    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader,
        enable_validation=False,  # Disable validation for baseline test
        enable_telemetry=False,
    )

    return engine


def validate_corpus(engine: TranslationEngine, corpus_dir: Path, site_id: str, sample_size: int = 5) -> List[PreservationMetrics]:
    """Validate translation on corpus sample."""
    # Collect English files
    print(f"\nCollecting English files from {corpus_dir}...")
    english_files = list(corpus_dir.rglob("**/en/**/*.md"))

    if not english_files:
        print(f"[ERROR] No English files found in {corpus_dir}")
        return []

    print(f"Found {len(english_files)} English files")

    # Random sample
    sample_files = random.sample(english_files, min(sample_size, len(english_files)))
    print(f"Selected {len(sample_files)} files for validation")

    # Validate each file
    results = []
    for i, file_path in enumerate(sample_files, 1):
        print(f"\n[{i}/{len(sample_files)}] Processing: {file_path.name}")

        try:
            # Read source content
            source_content = file_path.read_text(encoding="utf-8")

            # Translate using engine (target_langs is a list)
            result = engine.translate_file(
                site_id=site_id,
                file_path=file_path,
                target_langs=["de"],
            )

            if result.success and "de" in result.outputs:
                # Read translated content from output file
                output_path = result.outputs["de"]
                translated_content = output_path.read_text(encoding="utf-8")

                # Calculate preservation metrics
                metrics = calculate_preservation(
                    source_content,
                    translated_content,
                    str(file_path)
                )
                results.append(metrics)

                print(f"  Links: {metrics.link_preservation:.1f}% | "
                      f"Code: {metrics.code_block_preservation:.1f}% | "
                      f"Images: {metrics.image_preservation:.1f}% | "
                      f"Format: {metrics.formatting_preservation:.1f}%")

                # Show TM stats
                tm_stats = engine.tm.stats()
                print(f"  TM: {tm_stats.l1_hits} L1 hits, {tm_stats.l2_size} L2 entries")
            else:
                errors = ", ".join(result.errors) if result.errors else "unknown"
                print(f"  [SKIP] Translation failed: {errors}")

        except Exception as e:
            print(f"  [ERROR] Failed to process: {e}")
            import traceback
            traceback.print_exc()
            continue

    return results


def generate_report(results: List[PreservationMetrics], output_path: Path):
    """Generate baseline validation report."""
    if not results:
        print("[ERROR] No results to report")
        return

    # Calculate aggregate metrics
    avg_link = sum(r.link_preservation for r in results) / len(results)
    avg_code = sum(r.code_block_preservation for r in results) / len(results)
    avg_image = sum(r.image_preservation for r in results) / len(results)
    avg_format = sum(r.formatting_preservation for r in results) / len(results)

    # Count perfect preservation
    perfect_links = sum(1 for r in results if r.link_preservation == 100.0)
    perfect_code = sum(1 for r in results if r.code_block_preservation == 100.0)
    perfect_images = sum(1 for r in results if r.image_preservation == 100.0)
    files_with_corruption = sum(1 for r in results if r.link_preservation < 100 or r.code_block_preservation < 100 or r.image_preservation < 100)

    # Generate report
    report_lines = [
        "# HP-06 Baseline Validation Report",
        "",
        "**Validation Date**: 2025-12-16",
        f"**Files Analyzed**: {len(results)}",
        "**Method**: System TranslationEngine with TM caching",
        "**Purpose**: Measure translation preservation rates",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        "### Measured Preservation Rates",
        "",
        "| Metric | Average | Perfect Files | Files with Corruption |",
        "|--------|---------|---------------|----------------------|",
        f"| **Link preservation** | **{avg_link:.1f}%** | {perfect_links}/{len(results)} | {len(results) - perfect_links} |",
        f"| **Code preservation** | **{avg_code:.1f}%** | {perfect_code}/{len(results)} | {len(results) - perfect_code} |",
        f"| **Image preservation** | **{avg_image:.1f}%** | {perfect_images}/{len(results)} | {len(results) - perfect_images} |",
        f"| **Formatting preservation** | **{avg_format:.1f}%** | N/A | N/A |",
        "",
        f"**Key Finding**: {files_with_corruption} of {len(results)} files ({files_with_corruption/len(results)*100:.1f}%) have structural issues",
        "",
        "---",
        "",
        "## Detailed Results",
        "",
        "| File | Links | Code | Images | Format | Status |",
        "|------|-------|------|--------|--------|--------|"
    ]

    for r in results:
        file_name = Path(r.file_path).name
        has_corruption = r.link_preservation < 100 or r.code_block_preservation < 100 or r.image_preservation < 100
        status = "ISSUE" if has_corruption else "OK"
        report_lines.append(
            f"| {file_name} | {r.link_preservation:.0f}% | "
            f"{r.code_block_preservation:.0f}% | {r.image_preservation:.0f}% | "
            f"{r.formatting_preservation:.0f}% | {status} |"
        )

    report_lines.extend([
        "",
        "---",
        "",
        "*HP-06 Validation Report*",
        "*Generated: 2025-12-16*",
    ])

    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n[OK] Report written to: {output_path}")


def main():
    """Main entry point."""
    project_root = Path(__file__).parent.parent
    config_dir = project_root / "config"
    tm_path = project_root / "data" / "tm" / "hp06_validation.lmdb"
    corpus_dir = Path("D:/onedrive/Documents/GitHub/aspose.net/content")
    output_path = project_root / "reports" / "HP06_BASELINE_VALIDATION.md"
    site_id = "products.aspose.net"  # Site profile to use

    print("="*60)
    print("HP-06 Corpus Validation (Using System Engine)")
    print("="*60)
    print(f"Config: {config_dir}")
    print(f"TM: {tm_path}")
    print(f"Corpus: {corpus_dir}")
    print(f"Site ID: {site_id}")
    print(f"Sample size: 5 files")
    print()

    # Check corpus exists
    if not corpus_dir.exists():
        print(f"[ERROR] Corpus not found at {corpus_dir}")
        return 1

    try:
        # Initialize engine
        print("Initializing translation engine...")
        engine = setup_translation_engine(config_dir, tm_path)
        print("[OK] Engine initialized")

        # Run validation
        results = validate_corpus(engine, corpus_dir, site_id=site_id, sample_size=5)

        if not results:
            print("[ERROR] No results generated")
            return 1

        # Generate report
        generate_report(results, output_path)

        # Cleanup
        engine.tm.close()

        print("\n" + "="*60)
        print("[SUCCESS] Validation complete")
        print(f"Report: {output_path}")
        print("="*60)

        return 0

    except Exception as e:
        print(f"\n[ERROR] Validation failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
