#!/usr/bin/env python3
"""
Materialize Input Tree from Manifest (HARDENED)

Creates a directory tree from a manifest file (list of absolute file paths).
The CLI can then process this directory as input.

Hardening improvements (2026-02-02):
- Windows long-path support (\\?\ prefix for paths > 260 chars)
- Retry logic with exponential backoff (3 attempts for mkdir/copy)
- Enhanced diagnostics (OSError details, path lengths, cwd)
- Post-operation verification (mkdir/copy success explicitly checked)
- Path normalization and validation

Usage:
    python materialize_input_tree_from_manifest.py \\
        --manifest batch_01.txt \\
        --corpus-root D:\\repos\\aspose.net\\content \\
        --dest-root temp_input \\
        --receipt receipt.json

Purpose:
    Batch runners create manifest files listing absolute paths to translate.
    The CLI expects a directory tree, not a manifest file.
    This script bridges the gap by copying manifest files into a temp directory.

Safety:
    - Validates all input paths exist
    - Fails loudly if any file is missing
    - Uses shutil.copy2() to preserve metadata
    - Generates receipt JSON for auditability
    - Retries transient failures (OneDrive sync, file locks)
    - Supports Windows long paths (> 260 characters)
"""

import argparse
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, TypeVar, Any, Dict, List

# Fix encoding issues on Windows when output is redirected to file
if sys.platform == 'win32':
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

T = TypeVar('T')


def to_long_path(path: Path) -> Path:
    """
    Convert path to Windows long-path format (\\?\ prefix) if needed.

    Windows has 260-char limit (MAX_PATH) for traditional APIs.
    Long-path format supports up to 32,767 characters.

    Only applies to:
    - Windows platform
    - Absolute paths
    - Paths not already in long format
    - Not UNC paths (\\\\server\\share)

    Returns:
        Path object with \\?\ prefix on Windows, unchanged on other platforms
    """
    # Only on Windows
    if platform.system() != 'Windows':
        return path

    # Must be absolute
    if not path.is_absolute():
        return path

    # Convert to string for manipulation
    path_str = str(path)

    # Already in long format
    if path_str.startswith('\\\\?\\'):
        return path

    # UNC paths (\\\\server\\share) need different handling: \\\\?\\UNC\\server\\share
    if path_str.startswith('\\\\'):
        # UNC path - convert to \\?\UNC\server\share
        long_path_str = '\\\\?\\UNC\\' + path_str[2:]
        return Path(long_path_str)

    # Regular absolute path - add \\?\ prefix
    long_path_str = '\\\\?\\' + path_str
    return Path(long_path_str)


def retry_with_backoff(
    operation: Callable[[], T],
    operation_name: str,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> T:
    """
    Retry an operation with exponential backoff.

    Args:
        operation: Callable that performs the operation
        operation_name: Human-readable name for logging
        max_attempts: Maximum number of attempts (default: 3)
        initial_delay: Initial delay in seconds (default: 1.0)
        backoff_factor: Multiplier for delay on each retry (default: 2.0)

    Returns:
        Result of successful operation

    Raises:
        Last exception encountered if all attempts fail
    """
    attempt = 0
    delay = initial_delay
    last_exception = None

    while attempt < max_attempts:
        attempt += 1
        try:
            result = operation()
            if attempt > 1:
                print(f"  ✓ SUCCESS on attempt {attempt}/{max_attempts}")
            return result
        except Exception as e:
            last_exception = e
            if attempt < max_attempts:
                print(f"  ⚠ {operation_name} failed (attempt {attempt}/{max_attempts}): {e}")
                print(f"  ⏳ Retrying in {delay:.1f}s...")
                time.sleep(delay)
                delay *= backoff_factor
            else:
                print(f"  ✗ {operation_name} failed after {max_attempts} attempts")

    # All attempts exhausted
    raise last_exception


def materialize_tree(
    manifest_path: Path,
    corpus_root: Path,
    dest_root: Path,
) -> dict:
    """
    Copy files from manifest into dest_root, preserving relative paths.

    Args:
        manifest_path: Path to manifest file (one absolute path per line)
        corpus_root: Base directory for computing relative paths
        dest_root: Destination directory to create tree in

    Returns:
        dict with keys: files_requested, files_copied, missing_files, failed_files, dest_root

    Raises:
        FileNotFoundError: If manifest or corpus_root doesn't exist
        ValueError: If manifest is empty
        OSError: If critical filesystem operations fail after retries
    """
    # Validate inputs
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    if not corpus_root.exists():
        raise FileNotFoundError(f"Corpus root not found: {corpus_root}")

    # Read manifest
    with open(manifest_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        raise ValueError(f"Manifest is empty: {manifest_path}")

    # Normalize and validate paths
    normalized_paths = []
    for line_num, line in enumerate(lines, start=1):
        try:
            source_path = Path(line).resolve()  # Absolute path, normalized

            # Validate under corpus root (security check)
            try:
                source_path.relative_to(corpus_root)
            except ValueError:
                print(f"⚠ WARNING: File not under corpus root (line {line_num}): {source_path}", file=sys.stderr)
                print(f"  Corpus root: {corpus_root}", file=sys.stderr)
                # Allow but warn - might be legitimate edge cases

            normalized_paths.append(source_path)
        except Exception as e:
            print(f"⚠ WARNING: Invalid path in manifest (line {line_num}): {line}", file=sys.stderr)
            print(f"  Error: {e}", file=sys.stderr)
            # Skip invalid paths
            continue

    if not normalized_paths:
        raise ValueError(f"No valid paths found in manifest: {manifest_path}")

    # Create dest root with retry
    print(f"Creating destination root: {dest_root}")
    retry_with_backoff(
        operation=lambda: dest_root.mkdir(parents=True, exist_ok=True),
        operation_name=f"mkdir {dest_root}",
        max_attempts=3,
    )

    # Verify dest root exists
    if not dest_root.exists():
        raise OSError(f"mkdir succeeded but directory doesn't exist: {dest_root}")

    # Track results
    files_requested = len(normalized_paths)
    files_copied = 0
    missing_files = []
    failed_files = []

    print(f"Materializing {files_requested} files...")

    for idx, source_path in enumerate(normalized_paths, start=1):
        # Apply long-path support
        source_long = to_long_path(source_path)

        # Validate file exists
        if not source_long.exists():
            missing_files.append(str(source_path))
            print(f"  ✗ Missing ({idx}/{files_requested}): {source_path}", file=sys.stderr)
            continue

        # Compute relative path
        try:
            relative_path = source_path.relative_to(corpus_root)
        except ValueError:
            # File is not under corpus_root - use just the filename (fallback)
            relative_path = Path(source_path.name)
            print(f"  ⚠ Using filename only for path outside corpus root: {source_path}", file=sys.stderr)

        # Create destination path
        dest_path = dest_root / relative_path
        dest_long = to_long_path(dest_path)

        try:
            # Create parent directory with retry
            retry_with_backoff(
                operation=lambda: dest_long.parent.mkdir(parents=True, exist_ok=True),
                operation_name=f"mkdir {dest_path.parent.name}",
                max_attempts=3,
            )

            # Verify parent exists
            if not dest_long.parent.exists():
                raise OSError(f"mkdir succeeded but parent doesn't exist: {dest_path.parent}")

            # Copy file with retry
            retry_with_backoff(
                operation=lambda: shutil.copy2(str(source_long), str(dest_long)),
                operation_name=f"copy {source_path.name}",
                max_attempts=3,
            )

            # Verify copy succeeded
            if not dest_long.exists():
                raise OSError(f"copy succeeded but file doesn't exist: {dest_path}")

            if dest_long.stat().st_size == 0:
                raise OSError(f"copy succeeded but file is empty: {dest_path}")

            files_copied += 1

            # Progress indicator
            if idx % 10 == 0 or idx == files_requested:
                print(f"  [{idx}/{files_requested}] Copied: {relative_path}")

        except OSError as e:
            # Filesystem error (WinError 3, permissions, etc.)
            error_code = getattr(e, 'winerror', None)
            error_detail = {
                "path": str(source_path),
                "error": str(e),
                "error_code": error_code,
            }
            failed_files.append(error_detail)

            print(f"  ✗ FILESYSTEM ERROR ({idx}/{files_requested}): {e}", file=sys.stderr)
            if error_code:
                print(f"     Error code: {error_code} (WinError {error_code})", file=sys.stderr)
            print(f"     Source: {source_path}", file=sys.stderr)
            print(f"     Source exists: {source_long.exists()}", file=sys.stderr)
            print(f"     Source length: {len(str(source_path))} chars", file=sys.stderr)
            print(f"     Dest: {dest_path}", file=sys.stderr)
            print(f"     Dest parent: {dest_path.parent}", file=sys.stderr)
            print(f"     Dest parent exists: {dest_long.parent.exists()}", file=sys.stderr)
            print(f"     Dest length: {len(str(dest_path))} chars", file=sys.stderr)
            print(f"     Current working directory: {os.getcwd()}", file=sys.stderr)

            # List dest root if exists
            if dest_root.exists():
                try:
                    items = list(dest_root.iterdir())
                    print(f"     Dest root contains {len(items)} items", file=sys.stderr)
                except:
                    pass

            # Continue to next file (don't abort entire batch on single file failure)
            continue

        except Exception as e:
            # Unexpected error
            error_detail = {
                "path": str(source_path),
                "error": str(e),
                "type": type(e).__name__,
            }
            failed_files.append(error_detail)
            print(f"  ✗ UNEXPECTED ERROR ({idx}/{files_requested}): {e}", file=sys.stderr)
            continue

    # Summary
    print(f"\n Summary:")
    print(f"  Requested: {files_requested}")
    print(f"  Copied: {files_copied}")
    print(f"  Missing: {len(missing_files)}")
    print(f"  Failed: {len(failed_files)}")

    # Fail if any files missing
    if missing_files:
        raise FileNotFoundError(
            f"Missing {len(missing_files)} files from manifest:\n" +
            "\n".join(missing_files[:5]) +
            (f"\n... and {len(missing_files) - 5} more" if len(missing_files) > 5 else "")
        )

    # Fail if all files failed
    if files_copied == 0 and failed_files:
        raise OSError(
            f"All files failed to copy ({len(failed_files)} failures). " +
            f"First error: {failed_files[0]['error']}"
        )

    # Warn if some files failed but some succeeded
    if failed_files:
        print(f"\n⚠ WARNING: {len(failed_files)} files failed to copy", file=sys.stderr)
        print(f"  Continuing with {files_copied}/{files_requested} successfully copied files", file=sys.stderr)

    return {
        "files_requested": files_requested,
        "files_copied": files_copied,
        "missing_files": missing_files,
        "failed_files": failed_files,
        "dest_root": str(dest_root.resolve()),
    }


def write_receipt(
    receipt_path: Path,
    manifest_path: Path,
    corpus_root: Path,
    dest_root: Path,
    result: dict,
    status: str = "SUCCESS",
):
    """Write a JSON receipt of the materialization operation."""
    receipt = {
        "manifest": str(manifest_path.resolve()),
        "corpus_root": str(corpus_root.resolve()),
        "dest_root": result["dest_root"],
        "files_requested": result["files_requested"],
        "files_copied": result["files_copied"],
        "missing_files": result["missing_files"],
        "failed_files": result.get("failed_files", []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }

    # Ensure receipt directory exists
    receipt_path.parent.mkdir(parents=True, exist_ok=True)

    with open(receipt_path, 'w', encoding='utf-8') as f:
        json.dump(receipt, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Materialize directory tree from manifest file (HARDENED)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python materialize_input_tree_from_manifest.py \\
      --manifest batch_01.txt \\
      --corpus-root D:\\repos\\aspose.net\\content \\
      --dest-root temp_input \\
      --receipt receipt.json

  # The CLI can then process the materialized tree:
  python -m src.cli \\
      --input temp_input \\
      --output output \\
      --target-langs fr

Hardening Features (2026-02-02):
  - Windows long-path support (\\\\?\\ prefix for paths > 260 chars)
  - Retry logic with exponential backoff (3 attempts, 1s/2s/4s delays)
  - Enhanced diagnostics (OSError details, path lengths, working directory)
  - Post-operation verification (mkdir/copy explicitly validated)
  - Path normalization (absolute paths, security checks)
        """
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to manifest file (one absolute file path per line)"
    )

    parser.add_argument(
        "--corpus-root",
        type=Path,
        required=True,
        help="Base directory for computing relative paths"
    )

    parser.add_argument(
        "--dest-root",
        type=Path,
        required=True,
        help="Destination directory to create tree in (will be created)"
    )

    parser.add_argument(
        "--receipt",
        type=Path,
        required=True,
        help="Path to write JSON receipt"
    )

    args = parser.parse_args()

    try:
        # Materialize the tree
        print(f"Materializing tree from: {args.manifest}")
        print(f"Corpus root: {args.corpus_root}")
        print(f"Destination: {args.dest_root}")
        print(f"Working directory: {os.getcwd()}")
        print()

        result = materialize_tree(
            manifest_path=args.manifest,
            corpus_root=args.corpus_root,
            dest_root=args.dest_root,
        )

        # Determine status
        if result["failed_files"]:
            status = "PARTIAL_SUCCESS"
        elif result["files_copied"] == result["files_requested"]:
            status = "SUCCESS"
        else:
            status = "INCOMPLETE"

        # Write receipt
        write_receipt(
            receipt_path=args.receipt,
            manifest_path=args.manifest,
            corpus_root=args.corpus_root,
            dest_root=args.dest_root,
            result=result,
            status=status,
        )

        # Report success
        print(f"\n✓ SUCCESS: Materialized {result['files_copied']}/{result['files_requested']} files")
        print(f"✓ Receipt written to: {args.receipt}")

        # Exit with warning if partial
        if result["failed_files"]:
            print(f"\n⚠ WARNING: {len(result['failed_files'])} files failed (see receipt for details)", file=sys.stderr)
            return 2  # Partial success exit code

        return 0

    except FileNotFoundError as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)

        # Try to write partial receipt
        try:
            write_receipt(
                receipt_path=args.receipt,
                manifest_path=args.manifest,
                corpus_root=args.corpus_root,
                dest_root=args.dest_root,
                result={"files_requested": 0, "files_copied": 0, "missing_files": [str(e)], "failed_files": [], "dest_root": str(args.dest_root)},
                status="FAILED",
            )
        except:
            pass

        return 1

    except ValueError as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        return 1

    except OSError as e:
        error_code = getattr(e, 'winerror', None)
        print(f"\n✗ FILESYSTEM ERROR: {e}", file=sys.stderr)
        if error_code:
            print(f"   Error code: {error_code} (WinError {error_code})", file=sys.stderr)
        print(f"   Working directory: {os.getcwd()}", file=sys.stderr)

        # Try to write partial receipt
        try:
            write_receipt(
                receipt_path=args.receipt,
                manifest_path=args.manifest,
                corpus_root=args.corpus_root,
                dest_root=args.dest_root,
                result={"files_requested": 0, "files_copied": 0, "missing_files": [], "failed_files": [{"error": str(e)}], "dest_root": str(args.dest_root)},
                status="FAILED",
            )
        except:
            pass

        return 1

    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
