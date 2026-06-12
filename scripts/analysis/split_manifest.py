#!/usr/bin/env python3
"""
Manifest Splitter for Stage B Batch Processing

Splits a large manifest file into smaller, deterministic batches.
Validates all paths exist and produces machine-readable metadata.

Usage:
    python scripts/split_manifest.py \
        --input manifests/bulk_manifest.txt \
        --output-dir manifests/bulk_batches_fr \
        --batch-size 100 \
        --prefix bulk_fr
"""

import argparse
import json
import sys
from pathlib import Path

# Fix Unicode encoding issues on Windows console
if sys.stdout.encoding != "utf-8":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def validate_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    """Validate that all paths exist. Returns (valid, missing)."""
    valid = []
    missing = []

    for path_str in paths:
        path = Path(path_str.strip())
        if path.exists() and path.is_file():
            valid.append(path_str.strip())
        else:
            missing.append(path_str.strip())

    return valid, missing


def split_manifest(
    input_file: Path, output_dir: Path, batch_size: int, prefix: str, fail_on_missing: bool = True
) -> dict:
    """
    Split manifest into batches.

    Returns metadata dict with batch information.
    """
    # Read input manifest
    print(f"Reading manifest: {input_file}")
    with open(input_file, encoding="utf-8") as f:
        all_paths = [line.strip() for line in f if line.strip()]

    print(f"Total files in manifest: {len(all_paths)}")

    # Validate paths
    print("Validating paths...")
    valid_paths, missing_paths = validate_paths(all_paths)

    if missing_paths:
        print(f"\nWARNING: {len(missing_paths)} paths do not exist:")
        for path in missing_paths[:10]:  # Show first 10
            print(f"  - {path}")
        if len(missing_paths) > 10:
            print(f"  ... and {len(missing_paths) - 10} more")

        if fail_on_missing:
            print(f"\nFAILED: {len(missing_paths)} missing paths")
            sys.exit(1)
        else:
            print(f"\nContinuing with {len(valid_paths)} valid paths")
            all_paths = valid_paths
    else:
        print(f"OK: All {len(all_paths)} paths validated")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {output_dir}")

    # Split into batches
    num_batches = (len(all_paths) + batch_size - 1) // batch_size
    print(f"Splitting into {num_batches} batches (size={batch_size})")

    batch_files = []
    for batch_idx in range(num_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, len(all_paths))
        batch_paths = all_paths[start_idx:end_idx]

        # Write batch file
        batch_filename = f"{prefix}_{batch_idx + 1:04d}.txt"
        batch_path = output_dir / batch_filename

        with open(batch_path, "w", encoding="utf-8") as f:
            for path in batch_paths:
                f.write(path + "\n")

        batch_files.append(
            {
                "batch_id": batch_idx + 1,
                "filename": batch_filename,
                "file_count": len(batch_paths),
                "start_index": start_idx,
                "end_index": end_idx - 1,
            }
        )

        print(f"  Batch {batch_idx + 1:04d}: {len(batch_paths)} files -> {batch_filename}")

    # Create metadata
    metadata = {
        "source_manifest": str(input_file.absolute()),
        "output_directory": str(output_dir.absolute()),
        "prefix": prefix,
        "batch_size": batch_size,
        "total_files": len(all_paths),
        "total_batches": num_batches,
        "batches": batch_files,
        "missing_paths_count": len(missing_paths),
    }

    # Write metadata
    metadata_path = output_dir / "batch_manifest.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nMetadata written: {metadata_path}")
    print("\nSummary:")
    print(f"   Total files: {len(all_paths)}")
    print(f"   Total batches: {num_batches}")
    print(f"   Batch size: {batch_size}")
    print(f"   Output: {output_dir}")

    return metadata


def main():
    parser = argparse.ArgumentParser(description="Split manifest file into deterministic batches")
    parser.add_argument(
        "--input", type=Path, required=True, help="Input manifest file (one path per line)"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Output directory for batch files"
    )
    parser.add_argument("--batch-size", type=int, required=True, help="Number of files per batch")
    parser.add_argument(
        "--prefix", type=str, default="batch", help="Prefix for batch filenames (default: batch)"
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Continue even if some paths are missing (default: fail)",
    )

    args = parser.parse_args()

    # Validate input
    if not args.input.exists():
        print(f"ERROR: Input manifest not found: {args.input}")
        sys.exit(1)

    if args.batch_size < 1:
        print("ERROR: Batch size must be >= 1")
        sys.exit(1)

    # Run splitter
    try:
        metadata = split_manifest(
            input_file=args.input,
            output_dir=args.output_dir,
            batch_size=args.batch_size,
            prefix=args.prefix,
            fail_on_missing=not args.allow_missing,
        )
        print("\nSUCCESS")
        return 0
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
