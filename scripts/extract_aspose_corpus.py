#!/usr/bin/env python3
"""Extract benchmark corpus from Aspose content (READ-ONLY)."""
import json
import re
import sys
from pathlib import Path

ASPOSE_CONTENT_DIR = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content")

def clean_text(text: str) -> str:
    """Clean text by removing code blocks, URLs, and special formatting."""
    # Remove code blocks
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)

    # Remove URLs
    text = re.sub(r'https?://[^\s]+', '', text)

    # Remove markdown formatting
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # Links
    text = re.sub(r'[#*_~]', '', text)  # Headers, bold, italic, strikethrough

    # Remove multiple spaces and newlines
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def extract_text_segments(file_path: Path, content_type: str) -> list[dict]:
    """Extract clean text segments from markdown file.

    Args:
        file_path: Path to markdown file
        content_type: Type of content (docs, blog, products, etc.)

    Returns:
        List of segments with metadata
    """
    try:
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}")
        return []

    segments = []

    # Split by paragraphs (double newline)
    paragraphs = content.split('\n\n')

    for para in paragraphs:
        cleaned = clean_text(para)

        # Filter criteria
        if len(cleaned) < 20:  # Too short
            continue
        if len(cleaned) > 500:  # Too long
            continue
        if not cleaned:  # Empty after cleaning
            continue
        if cleaned.count('{') > 3:  # Likely contains code/templates
            continue
        if cleaned.count('|') > 5:  # Likely a table
            continue

        # Check for potential PII (basic)
        if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', cleaned):
            continue  # Skip if contains email
        if re.search(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', cleaned):
            continue  # Skip if contains phone number

        segments.append({
            "text": cleaned,
            "source_file": str(file_path.relative_to(ASPOSE_CONTENT_DIR)),
            "content_type": content_type,
            "length": len(cleaned)
        })

    return segments


def determine_content_type(file_path: Path) -> str:
    """Determine content type from file path."""
    parts = file_path.parts

    if 'blog' in parts:
        return 'blog'
    elif 'docs' in parts or 'documentation' in parts:
        return 'docs'
    elif 'products' in parts or 'product' in parts:
        return 'products'
    elif 'knowledge-base' in parts or 'kb' in parts:
        return 'kb'
    elif 'about' in parts:
        return 'about'
    elif 'reference' in parts or 'api' in parts:
        return 'reference'
    else:
        return 'other'


def main():
    if not ASPOSE_CONTENT_DIR.exists():
        print(f"✗ Aspose content directory not found: {ASPOSE_CONTENT_DIR}")
        print("  This directory is required for extracting benchmark corpus.")
        print("  If running in different environment, update ASPOSE_CONTENT_DIR in script.")
        return 1

    print(f"Scanning {ASPOSE_CONTENT_DIR} (READ-ONLY)...")
    print("This script will NEVER modify files in the Aspose directory.")
    print()

    corpus_by_type = {}
    total_files = 0

    # Scan markdown files
    for md_file in ASPOSE_CONTENT_DIR.rglob("*.md"):
        if md_file.name.startswith('.'):
            continue  # Skip hidden files

        content_type = determine_content_type(md_file)

        segments = extract_text_segments(md_file, content_type)

        if content_type not in corpus_by_type:
            corpus_by_type[content_type] = []

        corpus_by_type[content_type].extend(segments)
        total_files += 1

        if total_files % 100 == 0:
            total_segments = sum(len(segs) for segs in corpus_by_type.values())
            print(f"  Processed {total_files} files, extracted {total_segments} segments...")

    # Stratified sampling: limit segments per content type
    max_per_type = 500
    corpus = []

    for content_type, segments in sorted(corpus_by_type.items()):
        # Sample evenly by length (short, medium, long)
        segments_sorted = sorted(segments, key=lambda x: x['length'])

        if len(segments) > max_per_type:
            # Take samples from different parts of distribution
            step = len(segments) // max_per_type
            sampled = segments_sorted[::step][:max_per_type]
        else:
            sampled = segments_sorted

        corpus.extend(sampled)
        print(f"  {content_type}: {len(sampled)} segments (from {len(segments)} extracted)")

    # Ensure output directory exists
    output_dir = Path("data/benchmarks")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save corpus
    output_file = output_dir / "aspose_corpus.json"
    with open(output_file, "w", encoding='utf-8') as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)

    # Generate statistics
    print()
    print("=" * 60)
    print(f"✓ Extracted {len(corpus)} segments from {total_files} files")
    print(f"✓ Saved to {output_file}")
    print()
    print("Corpus statistics:")
    print(f"  Total segments: {len(corpus)}")
    print(f"  Avg length: {sum(s['length'] for s in corpus) / len(corpus):.1f} chars")
    print(f"  Min length: {min(s['length'] for s in corpus)} chars")
    print(f"  Max length: {max(s['length'] for s in corpus)} chars")
    print()
    print("Content type distribution:")
    for content_type in sorted(set(s['content_type'] for s in corpus)):
        count = sum(1 for s in corpus if s['content_type'] == content_type)
        print(f"  {content_type}: {count} ({100*count/len(corpus):.1f}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
