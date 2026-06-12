#!/usr/bin/env python3
"""
Restore Translation Memory and Configuration.

Restores TM data and configs from backup with integrity verification.
Supports restoration to different location for testing.
"""

import argparse
import hashlib
import json
import logging
import sys
import tarfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def calculate_checksum(file_path: Path) -> str:
    """
    Calculate SHA256 checksum of a file.

    Args:
        file_path: Path to file

    Returns:
        Hex digest of SHA256 hash
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_backup_integrity(backup_path: Path) -> tuple[bool, str]:
    """
    Verify backup integrity using checksum.

    Args:
        backup_path: Path to backup file

    Returns:
        Tuple of (valid, message)
    """
    try:
        checksum_path = backup_path.parent / f"{backup_path.name}.sha256"

        if not checksum_path.exists():
            return False, f"Checksum file not found: {checksum_path}"

        # Read expected checksum
        with open(checksum_path) as f:
            expected = f.read().strip().split()[0]

        # Calculate actual checksum
        logger.info("Verifying backup integrity...")
        actual = calculate_checksum(backup_path)

        if actual == expected:
            logger.info("Backup integrity verified")
            return True, "Backup integrity verified"
        else:
            return False, f"Checksum mismatch! Expected: {expected}, Got: {actual}"

    except Exception as e:
        return False, f"Integrity verification failed: {e}"


def read_backup_metadata(backup_path: Path) -> dict | None:
    """
    Read metadata from backup.

    Args:
        backup_path: Path to backup file

    Returns:
        Metadata dictionary or None if not found
    """
    try:
        with tarfile.open(backup_path, "r:*") as tar:
            # Extract metadata
            try:
                metadata_member = tar.getmember("metadata.json")
                metadata_file = tar.extractfile(metadata_member)
                if metadata_file:
                    metadata = json.load(metadata_file)
                    return metadata
            except KeyError:
                logger.warning("Metadata not found in backup")
                return None

    except Exception as e:
        logger.error(f"Failed to read metadata: {e}")
        return None


def restore_backup(
    backup_path: Path, target_dir: Path | None = None, verify: bool = True, dry_run: bool = False
) -> tuple[bool, str]:
    """
    Restore backup to target directory.

    Args:
        backup_path: Path to backup file
        target_dir: Target directory (None = use original paths)
        verify: Verify integrity before restoring
        dry_run: Show what would be restored without actually doing it

    Returns:
        Tuple of (success, message)
    """
    try:
        # Verify backup exists
        if not backup_path.exists():
            return False, f"Backup file not found: {backup_path}"

        # Verify integrity if requested
        if verify:
            valid, message = verify_backup_integrity(backup_path)
            if not valid:
                return False, message

        # Read metadata
        metadata = read_backup_metadata(backup_path)
        if metadata:
            logger.info("Backup Information:")
            logger.info(f"  Timestamp: {metadata.get('backup_timestamp')}")
            logger.info(f"  Version: {metadata.get('system_version')}")
            logger.info(f"  Type: {metadata.get('backup_type')}")
            logger.info(
                f"  Total Size: {metadata.get('total_size_bytes', 0) / (1024 * 1024):.2f} MB"
            )
            logger.info(f"  Total Files: {metadata.get('total_files', 0)}")

            # Show components
            logger.info("Components:")
            for name, info in metadata.get("components", {}).items():
                logger.info(
                    f"    {name}: {info.get('file_count', 0)} files, "
                    f"{info.get('size_bytes', 0) / (1024 * 1024):.2f} MB"
                )

        if dry_run:
            logger.info("DRY RUN: Would restore the following:")
            with tarfile.open(backup_path, "r:*") as tar:
                for member in tar.getmembers():
                    if target_dir:
                        dest = target_dir / member.name
                    else:
                        dest = Path.cwd() / member.name
                    logger.info(f"  {member.name} -> {dest}")
            return True, "Dry run completed successfully"

        # Perform restore
        logger.info(f"Restoring backup: {backup_path}")

        if target_dir:
            logger.info(f"Target directory: {target_dir}")
            target_dir.mkdir(parents=True, exist_ok=True)
            restore_path = target_dir
        else:
            logger.info("Restoring to original locations")
            restore_path = Path.cwd()

        # Extract backup
        with tarfile.open(backup_path, "r:*") as tar:
            # Get all members except metadata
            members = [m for m in tar.getmembers() if m.name != "metadata.json"]

            logger.info(f"Extracting {len(members)} files...")

            # Extract files
            for member in members:
                if target_dir:
                    # Extract to target directory
                    tar.extract(member, path=target_dir)
                else:
                    # Extract to current directory (original paths)
                    tar.extract(member, path=restore_path)

        logger.info("Restore completed successfully")

        # Verify restored files
        if verify and metadata:
            logger.info("Verifying restored files...")
            errors = []

            for name, info in metadata.get("components", {}).items():
                if target_dir:
                    component_path = target_dir / info["path"]
                else:
                    component_path = restore_path / info["path"]

                if component_path.exists():
                    logger.info(f"  {name}: OK")
                else:
                    error_msg = f"  {name}: MISSING at {component_path}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            if errors:
                return False, "Verification failed:\n" + "\n".join(errors)

        return True, f"Backup restored successfully to: {target_dir or restore_path}"

    except Exception as e:
        logger.error(f"Restore failed: {e}", exc_info=True)
        return False, f"Restore failed: {e}"


def test_corrupted_backup(backup_path: Path) -> tuple[bool, str]:
    """
    Test if backup is corrupted.

    Args:
        backup_path: Path to backup file

    Returns:
        Tuple of (corrupted, message)
    """
    try:
        # Try to open tarball
        with tarfile.open(backup_path, "r:*") as tar:
            # Try to list members
            members = tar.getmembers()

            if not members:
                return True, "Backup appears empty"

            # Check if metadata exists
            has_metadata = any(m.name == "metadata.json" for m in members)
            if not has_metadata:
                return True, "Backup missing metadata"

        return False, "Backup appears valid"

    except tarfile.TarError as e:
        return True, f"Backup is corrupted: {e}"
    except Exception as e:
        return True, f"Error reading backup: {e}"


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Restore Translation Memory and Configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Restore backup to original locations
  python scripts/restore_tm.py --backup backups/tm_20250101.tar.gz

  # Restore to different location for testing
  python scripts/restore_tm.py --backup backups/tm_20250101.tar.gz --target /tmp/test_restore

  # Restore with verification
  python scripts/restore_tm.py --backup backups/tm_20250101.tar.gz --verify

  # Dry run (show what would be restored)
  python scripts/restore_tm.py --backup backups/tm_20250101.tar.gz --dry-run

  # Test if backup is corrupted
  python scripts/restore_tm.py --backup backups/tm_20250101.tar.gz --test
        """,
    )

    parser.add_argument("--backup", "-b", type=str, required=True, help="Backup file path")

    parser.add_argument(
        "--target", "-t", type=str, help="Target directory (default: restore to original locations)"
    )

    parser.add_argument(
        "--verify", action="store_true", help="Verify backup integrity before restoring"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be restored without actually restoring",
    )

    parser.add_argument(
        "--test", action="store_true", help="Test if backup is corrupted (no restoration)"
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Parse paths
    backup_path = Path(args.backup).resolve()
    target_dir = Path(args.target).resolve() if args.target else None

    # Test mode
    if args.test:
        logger.info("Testing backup for corruption...")
        corrupted, message = test_corrupted_backup(backup_path)

        if corrupted:
            logger.error(f"CORRUPTED: {message}")
            return 1
        else:
            logger.info(f"VALID: {message}")
            return 0

    # Restore backup
    logger.info("Starting restore process...")
    logger.info(f"Backup: {backup_path}")

    success, message = restore_backup(
        backup_path=backup_path, target_dir=target_dir, verify=args.verify, dry_run=args.dry_run
    )

    if success:
        logger.info(message)
        return 0
    else:
        logger.error(message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
