#!/usr/bin/env python3
"""
Stratified Corpus Creator for Benchmark Matrix.

Creates a stratified sample of aspose.net content across:
- Subdomains: docs.aspose.net, reference.aspose.net, about.aspose.net, releases.aspose.net, downloads.aspose.net
- Families: slides, words, cells, pdf, email, tasks, barcode, imaging, diagram, note, html, 3d, cad, gis, zip, tex, psd, omr, svg, finance, drawing, font, page, etc. (26+ families)

Output: data/benchmark_corpus/stratified_manifest.yaml
"""

import argparse
import hashlib
import logging
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# Lazy import to avoid torch dependency during verification
def get_hugo_parser():
    """Lazy import HugoParser to avoid torch dependency."""
    from src.translation_engine.parser import HugoParser

    return HugoParser()


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Aspose product families (26 core families)
ASPOSE_FAMILIES = [
    "slides",
    "words",
    "cells",
    "pdf",
    "email",
    "tasks",
    "barcode",
    "imaging",
    "diagram",
    "note",
    "html",
    "3d",
    "cad",
    "gis",
    "zip",
    "tex",
    "psd",
    "omr",
    "svg",
    "finance",
    "drawing",
    "font",
    "page",
    "ocr",
    "total",
    "annotation",
]

# Aspose subdomains (5 primary subdomains)
ASPOSE_SUBDOMAINS = [
    "docs.aspose.net",
    "reference.aspose.net",
    "about.aspose.net",
    "releases.aspose.net",
    "downloads.aspose.net",
]


def estimate_token_count(text: str) -> int:
    """Estimate token count (simple heuristic: ~4 chars per token)."""
    return len(text) // 4


def extract_text_from_ast(ast_nodes: list) -> str:
    """Extract plain text from AST nodes recursively."""
    from src.translation_engine.parser.ast_nodes import NodeType

    text_parts = []

    def extract_from_node(node):
        """Recursively extract text from a node."""
        # Text nodes have raw content
        if node.type == NodeType.TEXT:
            if hasattr(node, "raw") and node.raw:
                text_parts.append(node.raw)

        # Code blocks and code spans have raw content
        elif node.type in (NodeType.CODE_BLOCK, NodeType.CODE_SPAN):
            if hasattr(node, "raw") and node.raw:
                text_parts.append(node.raw)

        # Recurse into children
        if hasattr(node, "children") and node.children:
            for child in node.children:
                extract_from_node(child)

    for node in ast_nodes:
        extract_from_node(node)

    return " ".join(text_parts)


def extract_family_from_path(path: Path) -> str | None:
    """
    Extract Aspose family from file path.

    Examples:
        content/docs.aspose.net/slides/en/... -> slides
        content/reference.aspose.net/words/... -> words
    """
    parts = path.parts
    for family in ASPOSE_FAMILIES:
        if family in parts:
            return family
    return None


def extract_subdomain_from_path(path: Path) -> str | None:
    """
    Extract subdomain from file path.

    Examples:
        content/docs.aspose.net/slides/... -> docs.aspose.net
        content/reference.aspose.net/words/... -> reference.aspose.net
    """
    parts = path.parts
    for subdomain in ASPOSE_SUBDOMAINS:
        if subdomain in parts:
            return subdomain
    return None


def collect_markdown_files(
    content_root: Path,
    include_families: list[str] | None = None,
    include_subdomains: list[str] | None = None,
) -> list[Path]:
    """
    Collect all markdown files from content root.

    Args:
        content_root: Root directory containing aspose.net content
        include_families: Filter to specific families (None = all)
        include_subdomains: Filter to specific subdomains (None = all)

    Returns:
        List of markdown file paths
    """
    logger.info(f"Collecting markdown files from {content_root}")

    markdown_files = []
    for md_file in content_root.rglob("*.md"):
        # Extract family and subdomain
        family = extract_family_from_path(md_file)
        subdomain = extract_subdomain_from_path(md_file)

        # Apply filters
        if include_families and family not in include_families:
            continue
        if include_subdomains and subdomain not in include_subdomains:
            continue

        markdown_files.append(md_file)

    logger.info(f"Found {len(markdown_files)} markdown files")
    return markdown_files


def create_stratified_sample(
    content_root: Path,
    target_samples: int = 150,
    min_samples_per_cell: int = 30,
    max_tokens_per_sample: int = 2000,
    seed: int = 42,
) -> dict:
    """
    Create stratified sample across subdomains × families.

    Args:
        content_root: Root directory containing aspose.net content
        target_samples: Total number of samples to collect
        min_samples_per_cell: Minimum samples per (subdomain, family) cell
        max_tokens_per_sample: Maximum tokens per sample (for filtering large files)
        seed: Random seed for reproducibility

    Returns:
        Dictionary containing manifest metadata and samples
    """
    random.seed(seed)

    logger.info(f"Creating stratified sample with target={target_samples} samples")
    logger.info(
        f"Stratification: {len(ASPOSE_SUBDOMAINS)} subdomains × {len(ASPOSE_FAMILIES)} families"
    )

    # Collect all markdown files
    all_files = collect_markdown_files(content_root)

    # Organize files by (subdomain, family)
    cells = defaultdict(list)
    for file_path in all_files:
        subdomain = extract_subdomain_from_path(file_path)
        family = extract_family_from_path(file_path)

        if subdomain and family:
            cells[(subdomain, family)].append(file_path)

    logger.info(f"Organized files into {len(cells)} non-empty cells")

    # Calculate sampling strategy
    total_cells = len(cells)
    if total_cells == 0:
        raise ValueError("No valid files found for stratified sampling")

    samples_per_cell = max(min_samples_per_cell, target_samples // total_cells)
    logger.info(f"Target samples per cell: {samples_per_cell}")

    # Sample from each cell
    samples = []
    parser = get_hugo_parser()

    for (subdomain, family), files in sorted(cells.items()):
        logger.info(f"Sampling from {subdomain}/{family}: {len(files)} files available")

        # Shuffle files and sample
        sampled_files = random.sample(files, min(samples_per_cell, len(files)))

        for file_path in sampled_files:
            try:
                # Parse file to extract text
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()

                parsed = parser.parse_string(content)
                # Extract text from AST nodes
                text = extract_text_from_ast(parsed.ast)

                # Skip if too large
                tokens = estimate_token_count(text)
                if tokens > max_tokens_per_sample:
                    logger.debug(f"Skipping large file: {file_path.name} ({tokens} tokens)")
                    continue

                # Create sample ID
                sample_id = hashlib.md5(str(file_path).encode()).hexdigest()[:8]

                # Relative path from content_root
                rel_path = file_path.relative_to(content_root)

                samples.append(
                    {
                        "id": f"{subdomain}_{family}_{sample_id}",
                        "subdomain": subdomain,
                        "family": family,
                        "path": str(rel_path),
                        "tokens": tokens,
                        "lang": "en",
                        "category": f"{subdomain}/{family}",
                    }
                )

                if len(samples) >= target_samples:
                    break

            except Exception as e:
                logger.warning(f"Failed to process {file_path}: {e}")
                continue

        if len(samples) >= target_samples:
            break

    # Create manifest
    manifest = {
        "version": "1.0",
        "source": str(content_root),
        "collected": datetime.now(UTC).isoformat(),
        "total_samples": len(samples),
        "stratification": {
            "subdomains": list(ASPOSE_SUBDOMAINS),
            "families": list(ASPOSE_FAMILIES),
            "cells": total_cells,
            "samples_per_cell_target": samples_per_cell,
        },
        "samples": samples,
    }

    logger.info(f"Created stratified manifest with {len(samples)} samples")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Create stratified benchmark corpus")
    parser.add_argument(
        "--content-root",
        type=Path,
        default=Path("D:/onedrive/Documents/GitHub/aspose.net/content"),
        help="Root directory containing aspose.net content",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/benchmark_corpus/stratified_manifest.yaml"),
        help="Output path for stratified manifest",
    )
    parser.add_argument(
        "--target-samples", type=int, default=150, help="Target number of samples to collect"
    )
    parser.add_argument(
        "--min-samples-per-cell",
        type=int,
        default=30,
        help="Minimum samples per (subdomain, family) cell",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")

    args = parser.parse_args()

    # Validate content root exists
    if not args.content_root.exists():
        logger.error(f"Content root not found: {args.content_root}")
        logger.info("Using fallback: current directory samples")
        args.content_root = Path("data/benchmark_corpus")

    # Create stratified sample
    manifest = create_stratified_sample(
        content_root=args.content_root,
        target_samples=args.target_samples,
        min_samples_per_cell=args.min_samples_per_cell,
        seed=args.seed,
    )

    # Write manifest to file
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True)

    logger.info(f"Wrote stratified manifest to {args.output}")
    logger.info(f"Total samples: {manifest['total_samples']}")
    logger.info(f"Stratification cells: {manifest['stratification']['cells']}")

    # Print summary by subdomain and family
    by_subdomain = defaultdict(int)
    by_family = defaultdict(int)
    for sample in manifest["samples"]:
        by_subdomain[sample["subdomain"]] += 1
        by_family[sample["family"]] += 1

    print("\n" + "=" * 60)
    print("STRATIFIED CORPUS SUMMARY")
    print("=" * 60)
    print(f"\nTotal samples: {manifest['total_samples']}")
    print("\nBy subdomain:")
    for subdomain, count in sorted(by_subdomain.items()):
        print(f"  {subdomain:30} {count:3} samples")
    print("\nBy family:")
    for family, count in sorted(by_family.items()):
        print(f"  {family:30} {count:3} samples")


if __name__ == "__main__":
    main()
