"""
Standalone script to find corrupted translation files.

Uses fasttext-predict (minimal dependencies) to detect language mismatches.
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
import subprocess
import tempfile


def detect_language_fasttext(text: str) -> Tuple[str, float]:
    """
    Detect language using fasttext-predict CLI tool.

    Returns:
        (language_code, confidence)
    """
    # Write text to temp file
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as f:
        f.write(text.replace('\n', ' '))  # Single line for fasttext
        temp_file = f.name

    try:
        # Run fasttext predict
        result = subprocess.run(
            ['fasttext-predict', 'models/lid.176.bin', temp_file],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            # Parse output: __label__en 0.9999
            line = result.stdout.strip()
            if line:
                parts = line.split()
                lang = parts[0].replace('__label__', '')
                confidence = float(parts[1]) if len(parts) > 1 else 0.0
                return lang, confidence

    except Exception as e:
        print(f"Warning: FastText detection failed: {e}")

    finally:
        # Clean up temp file
        try:
            Path(temp_file).unlink()
        except:
            pass

    return "unknown", 0.0


def scan_for_corrupted_files(
    content_dir: Path,
    languages: List[str],
    modified_since: str = None,
    min_confidence: float = 0.70,
    max_files_per_lang: int = 50
) -> List[Tuple[Path, str, str, float]]:
    """
    Scan for corrupted translation files.

    Args:
        content_dir: Root content directory to scan
        languages: List of language codes to check
        modified_since: ISO date string
        min_confidence: Minimum FastText confidence
        max_files_per_lang: Max files to check per language (for speed)

    Returns:
        List of (file_path, expected_lang, detected_lang, confidence)
    """
    corrupted_files = []

    # Parse modified_since date if provided
    cutoff_date = None
    if modified_since:
        try:
            cutoff_date = datetime.fromisoformat(modified_since)
        except ValueError:
            print(f"Warning: Invalid date format: {modified_since}")

    # Scan each language
    for lang in languages:
        pattern = f"**/*.{lang}.md"
        print(f"\nScanning {pattern}...")

        files_checked = 0
        files_skipped = 0

        for file_path in content_dir.rglob(pattern):
            # Check modification date if specified
            if cutoff_date:
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if file_mtime < cutoff_date:
                    files_skipped += 1
                    continue  # Skip old files

            # Limit number of files checked for performance
            if files_checked >= max_files_per_lang:
                print(f"  (Reached limit of {max_files_per_lang} files, skipping rest)")
                break

            # Read file content
            try:
                content = file_path.read_text(encoding='utf-8')
            except Exception as e:
                print(f"  ✗ Error reading {file_path}: {e}")
                continue

            # Skip empty or very short files
            if len(content.strip()) < 100:
                continue

            # Extract just the body content (skip frontmatter)
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    content = parts[2]  # Content after second ---

            # Take first 5000 chars for detection (enough for accuracy, faster)
            sample = content[:5000].strip()
            if len(sample) < 50:
                continue

            files_checked += 1

            # Detect actual language
            detected_lang, confidence = detect_language_fasttext(sample)

            # Check for mismatch
            if detected_lang != lang and confidence >= min_confidence:
                corrupted_files.append((file_path, lang, detected_lang, confidence))
                print(f"  ✗ MISMATCH: {file_path.relative_to(content_dir)}")
                print(f"    Expected: {lang}, Detected: {detected_lang} ({confidence:.2%})")

        print(f"  Checked {files_checked} files (skipped {files_skipped} old files)")

    return corrupted_files


def main():
    parser = argparse.ArgumentParser(
        description="Find corrupted translation files"
    )
    parser.add_argument(
        "--content-dir",
        type=Path,
        default=Path("D:/onedrive/Documents/GitHub/aspose.net/content"),
        help="Content directory to scan"
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["uk"],
        help="Languages to check (default: uk)"
    )
    parser.add_argument(
        "--modified-since",
        type=str,
        help="Only check files modified after this date (2025-12-01)"
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.70,
        help="Minimum FastText confidence (default: 0.70)"
    )
    parser.add_argument(
        "--max-files-per-lang",
        type=int,
        default=50,
        help="Max files to check per language (default: 50)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("corrupted_files_report.txt"),
        help="Output report file"
    )

    args = parser.parse_args()

    if not args.content_dir.exists():
        print(f"Error: Content directory not found: {args.content_dir}")
        return 1

    print("=" * 80)
    print("Corrupted Translation File Scanner (Standalone)")
    print("=" * 80)
    print(f"Content directory: {args.content_dir}")
    print(f"Languages: {', '.join(args.languages)}")
    if args.modified_since:
        print(f"Modified since: {args.modified_since}")
    print(f"Minimum confidence: {args.min_confidence:.0%}")
    print(f"Max files per language: {args.max_files_per_lang}")
    print()

    # Scan
    corrupted_files = scan_for_corrupted_files(
        content_dir=args.content_dir,
        languages=args.languages,
        modified_since=args.modified_since,
        min_confidence=args.min_confidence,
        max_files_per_lang=args.max_files_per_lang
    )

    # Report
    print("\n" + "=" * 80)
    print(f"RESULTS: Found {len(corrupted_files)} corrupted files")
    print("=" * 80)

    if corrupted_files:
        # Write report
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(f"Corrupted Translation File Report\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n")
            f.write(f"\n{'='*80}\n\n")

            for file_path, expected, detected, confidence in corrupted_files:
                rel_path = file_path.relative_to(args.content_dir)
                f.write(f"File: {rel_path}\n")
                f.write(f"  Expected: {expected}\n")
                f.write(f"  Detected: {detected} ({confidence:.2%})\n")
                f.write(f"  Full path: {file_path}\n")
                f.write(f"\n")

        print(f"\n✓ Report written to: {args.output}")
        print("\nTo restore these files:")
        print(f"  cd {args.content_dir.parent}")
        for file_path, _, _, _ in corrupted_files[:10]:  # Show first 10
            rel_path = file_path.relative_to(args.content_dir.parent)
            print(f"  git checkout HEAD -- \"{rel_path}\"")
        if len(corrupted_files) > 10:
            print(f"  ... and {len(corrupted_files) - 10} more")

        return 1

    else:
        print("\n✓ No corrupted files found!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
