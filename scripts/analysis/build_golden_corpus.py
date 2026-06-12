#!/usr/bin/env python3
"""
Golden Corpus Builder - Deterministic document sampling for benchmarking.

Usage:
    python scripts/build_golden_corpus.py --source D:/onedrive/Documents/GitHub/aspose.net/content \
                                           --output data/golden_corpus \
                                           --count 50 \
                                           --seed 42
"""

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def classify_document_complexity(file_path: Path) -> tuple[str, dict]:
    """Classify document and return (tier, features)"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}")
        return "simple", {"error": str(e)}

    features = {
        "file_size": len(content),
        "code_block_count": content.count("```"),
        "shortcode_count": content.count("{{<") + content.count("{{%"),
        "has_tables": ("|" in content and "---" in content),
        "has_math": ("$$" in content or "\\(" in content),
        "has_frontmatter": content.startswith("---\n"),
        "line_count": content.count("\n"),
    }

    # Classify
    if (
        features["code_block_count"] == 0
        and features["shortcode_count"] == 0
        and features["file_size"] < 2000
    ):
        tier = "simple"
    elif (
        features["code_block_count"] > 5
        or features["shortcode_count"] > 3
        or features["has_tables"]
        or features["has_math"]
    ):
        tier = "complex"
    elif "nested" in content.lower() or features["shortcode_count"] > 5:
        tier = "edge"
    else:
        tier = "medium"

    return tier, features


def stable_hash(path: Path, seed: int) -> int:
    """Deterministic hash for sampling"""
    h = hashlib.md5(f"{path}:{seed}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def detect_language_focus(file_path: Path) -> str:
    """Detect primary programming language mentioned"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore").lower()
    except:
        return "agnostic"

    language_indicators = {
        "python": ["python", "import ", "def ", ".py"],
        "java": ["java", "class ", "public static", ".java"],
        "csharp": ["c#", "csharp", "namespace ", "using System"],
        "agnostic": [],
    }

    scores = {}
    for lang, indicators in language_indicators.items():
        if lang == "agnostic":
            continue
        scores[lang] = sum(content.count(ind) for ind in indicators)

    max_lang = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else "agnostic"
    return max_lang


def build_corpus(source_dir: Path, output_dir: Path, target_count: int, seed: int):
    """Main corpus building logic"""

    # Step 1: Discover all markdown files
    print(f"Scanning {source_dir}...")
    if not source_dir.exists():
        print(f"[ERROR] Source directory does not exist: {source_dir}")
        print("   Please verify the path and try again.")
        return

    all_files = list(source_dir.rglob("*.md"))
    print(f"Found {len(all_files)} markdown files")

    if len(all_files) == 0:
        print("[ERROR] No markdown files found in source directory")
        return

    # Step 2: Classify all files
    print("Classifying documents...")
    classified = {}
    for f in all_files:
        tier, features = classify_document_complexity(f)
        lang = detect_language_focus(f)
        classified[f] = {"tier": tier, "features": features, "language": lang}

    # Step 3: Stratified sampling
    tier_targets = {"simple": 10, "medium": 20, "complex": 15, "edge": 5}

    selected_files = []
    for tier, count in tier_targets.items():
        tier_files = [f for f, info in classified.items() if info["tier"] == tier]
        tier_sorted = sorted(tier_files, key=lambda f: stable_hash(f, seed))
        selected = tier_sorted[:count]
        selected_files.extend(selected)
        print(f"  {tier.upper()}: selected {len(selected)}/{count} (available: {len(tier_files)})")

    print(f"\nTotal selected: {len(selected_files)} files")

    # Step 4: Copy files to output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "metadata": {
            "seed": seed,
            "total_count": len(selected_files),
            "source": str(source_dir),
            "build_date": datetime.now(timezone.utc).isoformat(),
        },
        "documents": [],
    }

    for idx, src_file in enumerate(selected_files):
        # Preserve directory structure (relative to source)
        rel_path = src_file.relative_to(source_dir)
        dest_file = output_dir / f"doc_{idx:03d}_{rel_path.name}"

        # Copy file
        shutil.copy2(src_file, dest_file)

        # Compute MD5 checksum
        md5 = hashlib.md5(dest_file.read_bytes()).hexdigest()

        # Add to manifest
        info = classified[src_file]
        manifest["documents"].append(
            {
                "id": f"doc_{idx:03d}",
                "filename": dest_file.name,
                "original_path": str(rel_path),
                "tier": info["tier"],
                "language_focus": info["language"],
                "features": info["features"],
                "md5": md5,
            }
        )

    # Step 5: Write manifest
    manifest_file = output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))

    print("\n[OK] Golden corpus built:")
    print(f"   Files: {len(manifest['documents'])}")
    print(f"   Output: {output_dir}")
    print(f"   Manifest: {manifest_file}")

    # Step 6: Print summary statistics
    tier_counts = {}
    lang_counts = {}
    for doc_info in manifest["documents"]:
        tier_counts[doc_info["tier"]] = tier_counts.get(doc_info["tier"], 0) + 1
        lang_counts[doc_info["language_focus"]] = lang_counts.get(doc_info["language_focus"], 0) + 1

    print("\n[STATS] Distribution:")
    print(f"   Tiers: {tier_counts}")
    print(f"   Languages: {lang_counts}")


def verify_corpus(corpus_dir: Path):
    """Verify corpus integrity"""
    manifest_file = corpus_dir / "manifest.json"
    if not manifest_file.exists():
        print("[ERROR] manifest.json not found")
        return False

    manifest = json.loads(manifest_file.read_text())

    print(f"Verifying {len(manifest['documents'])} files...")
    all_valid = True
    for doc_info in manifest["documents"]:
        file_path = corpus_dir / doc_info["filename"]
        if not file_path.exists():
            print(f"[ERROR] Missing: {doc_info['filename']}")
            all_valid = False
            continue

        actual_md5 = hashlib.md5(file_path.read_bytes()).hexdigest()
        if actual_md5 != doc_info["md5"]:
            print(f"[ERROR] Checksum mismatch: {doc_info['filename']}")
            all_valid = False

    if all_valid:
        print("[OK] All files verified")
    return all_valid


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build golden corpus for benchmarking")
    parser.add_argument("--source", type=Path, help="Source directory (Aspose.net content)")
    parser.add_argument(
        "--output", type=Path, default=Path("data/golden_corpus"), help="Output directory"
    )
    parser.add_argument("--count", type=int, default=50, help="Target document count")
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for deterministic sampling"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Verify existing corpus instead of building"
    )

    args = parser.parse_args()

    if args.verify:
        success = verify_corpus(args.output)
        exit(0 if success else 1)
    else:
        if not args.source:
            parser.error("--source is required for building corpus")
        build_corpus(args.source, args.output, args.count, args.seed)
