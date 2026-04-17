"""
Timestamped rotating file handler for log files.

This module provides a custom RotatingFileHandler that adds timestamps to rotated
log files while keeping the active log file name clean (without timestamp).

Behavior:
- Active log file: hugo-translator.ndjson (clean name, no timestamp)
- Rotated files: hugo-translator-2026-01-12_14-30-45.ndjson.1,
                 hugo-translator-2026-01-12_14-25-30.ndjson.2, etc.

The timestamp is inserted BEFORE the file extension to maintain readability and
compatibility with log analysis tools that filter by extension.

Example Usage:
    from pathlib import Path
    from src.observability.timestamped_rotating_handler import TimestampedRotatingFileHandler

    handler = TimestampedRotatingFileHandler(
        filename="logs/hugo-translator.ndjson",
        maxBytes=100 * 1024 * 1024,  # 100MB
        backupCount=10,
        encoding="utf-8"
    )

    # When the file reaches maxBytes:
    # 1. Current file gets renamed: hugo-translator-2026-01-12_14-30-45.ndjson.1
    # 2. Previous .1 becomes .2, .2 becomes .3, etc.
    # 3. New active file is created: hugo-translator.ndjson (clean name)
"""

import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


class TimestampedRotatingFileHandler(RotatingFileHandler):
    """
    Custom rotating file handler that adds timestamps to rotated files only.

    This handler extends RotatingFileHandler to insert timestamps into the filename
    when rotating logs, making it easier to identify and manage historical log files.
    The active log file maintains a clean name without timestamps.

    Attributes:
        baseFilename: Base filename for the log file (inherited)
        maxBytes: Maximum size before rotation (inherited)
        backupCount: Number of backup files to keep (inherited)
    """

    def doRollover(self):
        """
        Perform a rollover with timestamp insertion.

        This method overrides the parent's doRollover to add timestamps to rotated
        files. The rotation process:

        1. Close the current file stream
        2. Rotate existing backups (.1 → .2, .2 → .3, etc.)
        3. Rename current log with timestamp and .1 suffix
        4. Reopen a new clean active log file

        The timestamp format is: YYYY-MM-DD_HH-MM-SS

        Example rotation sequence:
            Before rotation:
                hugo-translator.ndjson (active, 100MB)
                hugo-translator-2026-01-11_10-15-30.ndjson.1

            After rotation:
                hugo-translator.ndjson (active, empty)
                hugo-translator-2026-01-12_14-30-45.ndjson.1 (just rotated)
                hugo-translator-2026-01-11_10-15-30.ndjson.2 (pushed down)
        """
        # Close the current file stream
        if self.stream:
            self.stream.close()
            self.stream = None

        # Generate timestamp for this rotation
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Parse the base filename to separate stem and extension
        base_path = Path(self.baseFilename)
        stem = base_path.stem  # e.g., "hugo-translator"
        suffix = base_path.suffix  # e.g., ".ndjson"
        parent = base_path.parent

        # First, clean up any files at or beyond backupCount level
        # These are files that would exceed our backup limit
        for i in range(self.backupCount, self.backupCount + 10):  # Check up to +10 levels
            pattern = f"{stem}-*{suffix}.{i}"
            for old_file in parent.glob(pattern):
                try:
                    old_file.unlink()
                except OSError:
                    pass

        # Rotate existing backup files (oldest to newest)
        # Move .{backupCount-1} to .{backupCount}, then .{backupCount-2} to .{backupCount-1}, etc.
        # This ensures we don't overwrite files we haven't moved yet
        for i in range(self.backupCount - 1, 0, -1):
            # Look for ALL files matching: <stem>-*<suffix>.i
            pattern = f"{stem}-*{suffix}.{i}"
            matching_files = sorted(parent.glob(pattern), reverse=True)  # Sort by name, newest first

            if not matching_files:
                continue  # No files at this level, skip

            # Keep only the FIRST (newest) file, delete all others
            source_file = matching_files[0]
            for stale_file in matching_files[1:]:
                try:
                    stale_file.unlink()
                except OSError:
                    pass

            # Calculate destination filename with incremented backup number
            source_str = str(source_file)
            dest_str = source_str[:-len(f".{i}")] + f".{i + 1}"
            dest_file = Path(dest_str)

            # If we're rotating to backupCount level, delete ALL existing files at that level first
            # (This handles the case where previous rotations left multiple .N files)
            if i + 1 == self.backupCount:
                cleanup_pattern = f"{stem}-*{suffix}.{i + 1}"
                for cleanup_file in parent.glob(cleanup_pattern):
                    try:
                        cleanup_file.unlink()
                    except OSError:
                        pass

            # Delete destination if it still exists
            if dest_file.exists():
                try:
                    dest_file.unlink()
                except OSError:
                    pass

            # Rename source to destination
            try:
                source_file.rename(dest_file)
            except OSError:
                pass  # Continue even if rename fails

        # Now rename the current log file with timestamp and .1 suffix
        # Current: hugo-translator.ndjson → hugo-translator-2026-01-12_14-30-45.ndjson.1
        timestamped_name = f"{stem}-{timestamp}{suffix}.1"
        dfn = parent / timestamped_name

        # Remove destination if it exists (shouldn't happen, but be safe)
        if dfn.exists():
            try:
                dfn.unlink()
            except OSError:
                pass

        # Rename current log file to timestamped backup
        if os.path.exists(self.baseFilename):
            try:
                os.rename(self.baseFilename, str(dfn))
            except OSError:
                pass  # Continue even if rename fails

        # Reopen the active log file with clean name (no timestamp)
        if not self.delay:
            self.stream = self._open()


# Example and testing utilities
def _example_usage():
    """
    Example demonstrating how to use TimestampedRotatingFileHandler.

    This function is for documentation purposes and is not called during normal
    operation.
    """
    import logging
    from pathlib import Path

    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Set up logger with timestamped rotating handler
    logger = logging.getLogger("example")
    logger.setLevel(logging.DEBUG)

    # Create handler with 1KB max size for quick rotation testing
    handler = TimestampedRotatingFileHandler(
        filename=str(log_dir / "example.log"),
        maxBytes=1024,  # 1KB for quick rotation
        backupCount=5,
        encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    logger.addHandler(handler)

    # Write some log entries
    for i in range(100):
        logger.info(f"Log entry {i}: This is a test message with some content")

    print("Log rotation example completed. Check the logs directory.")
    print("You should see:")
    print("  - example.log (active, clean name)")
    print("  - example-YYYY-MM-DD_HH-MM-SS.log.1 (most recent rotation)")
    print("  - example-YYYY-MM-DD_HH-MM-SS.log.2 (older rotation)")
    print("  - etc.")


if __name__ == "__main__":
    _example_usage()
