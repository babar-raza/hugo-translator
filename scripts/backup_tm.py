#!/usr/bin/env python3
"""
Backup Translation Memory and Configuration.

Creates compressed backups of L2 LMDB database, L3 FAISS index,
and configuration files with integrity verification.

Phase 5.3 Migration:
    Supports optional SharedEngines for telemetry tracking.
    Falls back to standalone mode if engines not available.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
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
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_directory_size(path: Path) -> int:
    """
    Calculate total size of directory.

    Args:
        path: Directory path

    Returns:
        Total size in bytes
    """
    total = 0
    for entry in path.rglob('*'):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def count_directory_files(path: Path) -> int:
    """
    Count files in directory recursively.

    Args:
        path: Directory path

    Returns:
        Number of files
    """
    return sum(1 for _ in path.rglob('*') if _.is_file())


def create_backup_metadata(
    tm_data_dir: Path,
    config_dir: Path,
    version: str = "1.0.0"
) -> dict:
    """
    Create metadata for backup.

    Args:
        tm_data_dir: TM data directory
        config_dir: Config directory
        version: System version

    Returns:
        Metadata dictionary
    """
    metadata = {
        "backup_timestamp": datetime.now().isoformat(),
        "system_version": version,
        "backup_type": "full",
        "components": {}
    }

    # L2 LMDB metadata
    l2_path = tm_data_dir / "l2_lmdb"
    if l2_path.exists():
        metadata["components"]["l2_lmdb"] = {
            "path": "tm_data/l2_lmdb",
            "size_bytes": get_directory_size(l2_path),
            "file_count": count_directory_files(l2_path),
            "exists": True
        }

    # L3 FAISS metadata
    l3_path = tm_data_dir / "l3_faiss"
    if l3_path.exists():
        metadata["components"]["l3_faiss"] = {
            "path": "tm_data/l3_faiss",
            "size_bytes": get_directory_size(l3_path),
            "file_count": count_directory_files(l3_path),
            "exists": True
        }

    # Config metadata
    if config_dir.exists():
        metadata["components"]["config"] = {
            "path": "config",
            "size_bytes": get_directory_size(config_dir),
            "file_count": count_directory_files(config_dir),
            "exists": True
        }

    # Calculate totals
    metadata["total_size_bytes"] = sum(
        comp.get("size_bytes", 0)
        for comp in metadata["components"].values()
    )
    metadata["total_files"] = sum(
        comp.get("file_count", 0)
        for comp in metadata["components"].values()
    )

    return metadata


def create_backup(
    output_path: Path,
    tm_data_dir: Path,
    config_dir: Path,
    rotate: int | None = None,
    compression: str = "gz",
    engines: Optional["SharedEngines"] = None,
) -> tuple[bool, str]:
    """
    Create compressed backup of TM and configs.

    Args:
        output_path: Output backup file path
        tm_data_dir: TM data directory
        config_dir: Config directory
        rotate: Keep only last N backups (None = keep all)
        compression: Compression type ('gz', 'bz2', 'xz', '')
        engines: Optional SharedEngines for telemetry (Phase 5.3)

    Returns:
        Tuple of (success, message)
    """
    start_time = datetime.now()

    # PHASE 5.3: Emit backup started event
    if engines:
        try:
            engines.telemetry.track_event(
                event_type="backup_started",
                output_path=str(output_path),
                compression=compression
            )
        except Exception as e:
            logger.debug(f"Telemetry event failed (non-fatal): {e}")

    try:
        # Validate paths
        if not tm_data_dir.exists():
            error_msg = f"TM data directory not found: {tm_data_dir}"

            # PHASE 5.3: Emit failure event
            if engines:
                try:
                    engines.telemetry.track_event(
                        event_type="backup_failed",
                        error=error_msg
                    )
                except Exception as e:
                    logger.debug(f"Telemetry event failed (non-fatal): {e}")

            return False, error_msg

        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Create metadata
        logger.info("Creating backup metadata...")
        metadata = create_backup_metadata(tm_data_dir, config_dir)

        # Determine compression mode
        if compression:
            tar_mode = f"w:{compression}"
        else:
            tar_mode = "w"

        logger.info(f"Creating backup: {output_path}")
        logger.info(f"Total size: {metadata['total_size_bytes'] / (1024*1024):.2f} MB")
        logger.info(f"Total files: {metadata['total_files']}")

        # Create tarball
        with tarfile.open(output_path, tar_mode) as tar:
            # Add metadata
            metadata_path = output_path.parent / "metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            tar.add(metadata_path, arcname="metadata.json")
            metadata_path.unlink()

            # Add L2 LMDB
            l2_path = tm_data_dir / "l2_lmdb"
            if l2_path.exists():
                logger.info("Backing up L2 LMDB database...")
                tar.add(l2_path, arcname="tm_data/l2_lmdb")

            # Add L3 FAISS
            l3_path = tm_data_dir / "l3_faiss"
            if l3_path.exists():
                logger.info("Backing up L3 FAISS index...")
                tar.add(l3_path, arcname="tm_data/l3_faiss")

            # Add configs
            if config_dir.exists():
                logger.info("Backing up configuration files...")
                for config_file in config_dir.glob("*.yaml"):
                    tar.add(config_file, arcname=f"config/{config_file.name}")
                for config_file in config_dir.glob("*.yml"):
                    tar.add(config_file, arcname=f"config/{config_file.name}")

        # Calculate checksum
        logger.info("Calculating backup checksum...")
        checksum = calculate_checksum(output_path)
        checksum_path = output_path.parent / f"{output_path.name}.sha256"
        with open(checksum_path, 'w') as f:
            f.write(f"{checksum}  {output_path.name}\n")

        backup_size = output_path.stat().st_size
        duration_seconds = (datetime.now() - start_time).total_seconds()

        logger.info(f"Backup created successfully: {output_path}")
        logger.info(f"Backup size: {backup_size / (1024*1024):.2f} MB")
        logger.info(f"Checksum: {checksum}")
        logger.info(f"Checksum file: {checksum_path}")
        logger.info(f"Duration: {duration_seconds:.1f}s")

        # PHASE 5.3: Emit backup completed event
        if engines:
            try:
                engines.telemetry.track_event(
                    event_type="backup_completed",
                    output_path=str(output_path),
                    backup_size_mb=backup_size / (1024*1024),
                    duration_seconds=duration_seconds,
                    checksum=checksum,
                    total_files=metadata.get('total_files', 0)
                )
            except Exception as e:
                logger.debug(f"Telemetry event failed (non-fatal): {e}")

        # Rotate old backups if requested
        if rotate is not None and rotate > 0:
            rotate_backups(output_path.parent, rotate)

        return True, f"Backup created successfully: {output_path}"

    except Exception as e:
        logger.error(f"Backup failed: {e}", exc_info=True)

        # PHASE 5.3: Emit failure event
        if engines:
            try:
                engines.telemetry.track_event(
                    event_type="backup_failed",
                    error=str(e),
                    duration_seconds=(datetime.now() - start_time).total_seconds()
                )
            except Exception as tel_err:
                logger.debug(f"Telemetry event failed (non-fatal): {tel_err}")

        return False, f"Backup failed: {e}"


def rotate_backups(backup_dir: Path, keep_count: int) -> None:
    """
    Rotate backups, keeping only the last N backups.

    Args:
        backup_dir: Directory containing backups
        keep_count: Number of backups to keep
    """
    try:
        # Find all backup files
        backups = sorted(
            backup_dir.glob("tm_*.tar.*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        # Remove old backups
        for backup in backups[keep_count:]:
            logger.info(f"Rotating old backup: {backup}")
            backup.unlink()

            # Remove associated checksum file
            checksum_file = backup.parent / f"{backup.name}.sha256"
            if checksum_file.exists():
                checksum_file.unlink()

        if len(backups) > keep_count:
            logger.info(f"Kept {keep_count} most recent backups, removed {len(backups) - keep_count}")

    except Exception as e:
        logger.warning(f"Failed to rotate backups: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Backup Translation Memory and Configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create backup with default paths
  python scripts/backup_tm.py --output backups/tm_20250101.tar.gz

  # Create backup with custom TM data directory
  python scripts/backup_tm.py --tm-data ./data/tm --output backups/tm_20250101.tar.gz

  # Create backup and rotate old backups (keep last 7)
  python scripts/backup_tm.py --output backups/tm_20250101.tar.gz --rotate 7

  # Create uncompressed backup (faster)
  python scripts/backup_tm.py --output backups/tm_20250101.tar --compression none

  # Enable telemetry tracking (Phase 5.3)
  USE_SHARED_ENGINES=true python scripts/backup_tm.py --output backups/tm_20250101.tar.gz
        """
    )

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        required=True,
        help="Output backup file path (e.g., backups/tm_20250101.tar.gz)"
    )

    parser.add_argument(
        "--tm-data",
        type=str,
        default="./data/tm",
        help="TM data directory path. Default: ./data/tm"
    )

    parser.add_argument(
        "--config",
        type=str,
        default="./config",
        help="Config directory path. Default: ./config"
    )

    parser.add_argument(
        "--rotate",
        type=int,
        help="Keep only last N backups (removes older backups)"
    )

    parser.add_argument(
        "--compression",
        choices=["gz", "bz2", "xz", "none"],
        default="gz",
        help="Compression type. Default: gz"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Parse paths
    output_path = Path(args.output).resolve()
    tm_data_dir = Path(args.tm_data).resolve()
    config_dir = Path(args.config).resolve()

    # Validate compression
    compression = None if args.compression == "none" else args.compression

    # PHASE 5.3: Optionally initialize SharedEngines
    use_shared_engines = os.getenv("USE_SHARED_ENGINES", "false").lower() in ("true", "1", "yes")
    shared_engines = None

    if use_shared_engines:
        logger.info("SharedEngines enabled via USE_SHARED_ENGINES environment variable")
        try:
            from src.shared_engines.composition_root import CompositionRoot

            # Create minimal engines configuration for telemetry
            engines_config = {
                "config_root": str(config_dir),
                "log_level": "DEBUG" if args.verbose else "INFO",
                "telemetry_enabled": True,
            }

            shared_engines = CompositionRoot.create_from_config(engines_config)
            logger.info("SharedEngines created successfully for telemetry tracking")

        except Exception as e:
            logger.warning(f"Failed to create SharedEngines: {e}")
            logger.info("Continuing in standalone mode (no telemetry)")
            shared_engines = None

    # Create backup
    logger.info("Starting backup process...")
    logger.info(f"TM data directory: {tm_data_dir}")
    logger.info(f"Config directory: {config_dir}")
    logger.info(f"Output: {output_path}")
    if shared_engines:
        logger.info("Telemetry: ENABLED")

    success, message = create_backup(
        output_path=output_path,
        tm_data_dir=tm_data_dir,
        config_dir=config_dir,
        rotate=args.rotate,
        compression=compression,
        engines=shared_engines,
    )

    if success:
        logger.info(message)
        return 0
    else:
        logger.error(message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
