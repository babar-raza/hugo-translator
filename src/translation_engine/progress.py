"""Progress tracking system for translation resilience.

This module provides crash-safe progress tracking for the translation engine,
enabling resume capability after unexpected termination.

Implementation follows RES-01 from the translation resilience plan.
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Handle both package imports and direct imports for testing
try:
    from ..utils.atomic_write import atomic_write
except ImportError:
    from utils.atomic_write import atomic_write

logger = logging.getLogger(__name__)


class ProgressCorruptionError(Exception):
    """Raised when progress file is corrupted."""
    pass


class ProgressValidationError(Exception):
    """
    RES-07: Raised when progress file validation fails.

    Includes a `recoverable` flag indicating whether recovery is possible.
    """

    def __init__(self, message: str, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable


@dataclass
class ProgressState:
    """
    Complete state for resumable translation.

    Schema Version: 1.0
    """
    # Identification
    run_id: str
    schema_version: str = "1.0"

    # Context
    site_id: str = ""
    source_dir: str = ""
    output_dir: str = ""
    target_langs: list[str] = field(default_factory=list)

    # Progress tracking
    total_files: int = 0
    completed_files: dict[str, list[str]] = field(default_factory=dict)  # {file_path: [completed_langs]}
    failed_files: dict[str, dict[str, str]] = field(default_factory=dict)  # {file_path: {lang: error_msg}}

    # Statistics
    files_processed: int = 0
    translations_completed: int = 0
    translations_failed: int = 0

    # Timestamps
    started_at: str = ""
    last_updated: str = ""

    # Configuration snapshot
    config_snapshot: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'ProgressState':
        """
        Load from dict with validation.

        Args:
            data: Dictionary to load from

        Returns:
            ProgressState instance

        Raises:
            ValueError: If schema version is unsupported
        """
        # Validate schema version
        version = data.get('schema_version', '1.0')
        if version != '1.0':
            raise ValueError(f"Unsupported schema version: {version}")

        # Filter to only valid fields
        valid_fields = {
            'run_id', 'schema_version', 'site_id', 'source_dir', 'output_dir',
            'target_langs', 'total_files', 'completed_files', 'failed_files',
            'files_processed', 'translations_completed', 'translations_failed',
            'started_at', 'last_updated', 'config_snapshot'
        }
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return cls(**filtered_data)


class ProgressTracker:
    """
    Atomic progress tracking with crash recovery.

    Features:
    - Atomic writes (no corruption on crash)
    - Progress file per run (supports concurrent runs)
    - Validation on load (detects corruption)
    - Clean separation of concerns

    Usage:
        # Start new translation run
        tracker = ProgressTracker(
            progress_dir=Path(".translation_progress"),
            site_id="my.site",
            source_dir=Path("content"),
            output_dir=Path("output"),
            target_langs=["es", "fr"]
        )

        # Initialize with discovered files
        tracker.initialize(all_files)

        # During translation
        for file in files:
            for lang in langs:
                try:
                    translate(file, lang)
                    tracker.mark_completed(file, lang)
                except Exception as e:
                    tracker.mark_failed(file, lang, str(e))

        # On successful completion
        tracker.clear()

        # Resume after crash
        tracker = ProgressTracker.find_latest(progress_dir, site_id)
        pending = tracker.get_pending(all_files)
    """

    def __init__(
        self,
        progress_dir: Path,
        run_id: str | None = None,
        site_id: str = "",
        source_dir: Path = Path("."),
        output_dir: Path = Path("output"),
        target_langs: list[str] | None = None
    ):
        """
        Initialize progress tracker.

        Args:
            progress_dir: Directory to store progress files
            run_id: Unique run identifier (generates UUID if None)
            site_id: Site being translated
            source_dir: Source directory path
            output_dir: Output directory path
            target_langs: Target languages
        """
        self.progress_dir = Path(progress_dir)
        self.progress_dir.mkdir(parents=True, exist_ok=True)

        self.run_id = run_id or str(uuid.uuid4())
        self.progress_file = self.progress_dir / f"progress_{self.run_id}.json"

        # Initialize or load state
        if self.progress_file.exists():
            self.state = self._load_state()
            logger.info(f"Loaded existing progress: {self.state.translations_completed} completed")
        else:
            now = datetime.now(timezone.utc).isoformat()
            self.state = ProgressState(
                run_id=self.run_id,
                site_id=site_id,
                source_dir=str(source_dir),
                output_dir=str(output_dir),
                target_langs=target_langs or [],
                total_files=0,
                completed_files={},
                failed_files={},
                started_at=now,
                last_updated=now
            )

    def _load_state(self) -> ProgressState:
        """
        Load and validate progress state from disk.

        Returns:
            ProgressState instance

        Raises:
            ProgressCorruptionError: If file is corrupted
        """
        try:
            with open(self.progress_file, encoding='utf-8') as f:
                data = json.load(f)
            return ProgressState.from_dict(data)
        except json.JSONDecodeError as e:
            raise ProgressCorruptionError(
                f"Progress file corrupted (invalid JSON): {self.progress_file}. Error: {e}"
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ProgressCorruptionError(
                f"Progress file corrupted (invalid structure): {self.progress_file}. Error: {e}"
            )

    def _save_state(self) -> None:
        """Atomically save progress state to disk."""
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        json_content = json.dumps(self.state.to_dict(), indent=2, ensure_ascii=False)
        atomic_write(self.progress_file, json_content)

    def initialize(self, all_files: list[Path]) -> None:
        """
        Initialize progress tracking for a batch of files.

        Args:
            all_files: List of all files to be translated
        """
        self.state.total_files = len(all_files)
        self._save_state()
        logger.info(f"Initialized progress tracking for {len(all_files)} files")

    def mark_completed(self, file_path: Path, lang: str) -> None:
        """
        Mark a file translation as completed.

        Args:
            file_path: Path to source file
            lang: Target language code
        """
        file_key = str(file_path)

        if file_key not in self.state.completed_files:
            self.state.completed_files[file_key] = []

        if lang not in self.state.completed_files[file_key]:
            self.state.completed_files[file_key].append(lang)
            self.state.translations_completed += 1

        # Remove from failed if exists
        if file_key in self.state.failed_files:
            self.state.failed_files[file_key].pop(lang, None)
            if not self.state.failed_files[file_key]:
                del self.state.failed_files[file_key]

        # Update file count when all languages are done
        if self.state.target_langs:
            all_langs_done = set(self.state.completed_files[file_key]) >= set(self.state.target_langs)
            # Only count files_processed once when all langs complete
            completed_for_file = len(self.state.completed_files[file_key])
            if all_langs_done and completed_for_file == len(self.state.target_langs):
                self.state.files_processed += 1

        self._save_state()

    def mark_failed(self, file_path: Path, lang: str, error: str) -> None:
        """
        Mark a file translation as failed.

        Args:
            file_path: Path to source file
            lang: Target language code
            error: Error message
        """
        file_key = str(file_path)

        if file_key not in self.state.failed_files:
            self.state.failed_files[file_key] = {}

        self.state.failed_files[file_key][lang] = error
        self.state.translations_failed += 1

        self._save_state()

    def get_pending(self, all_files: list[Path]) -> list[tuple[Path, str]]:
        """
        Get list of (file, lang) pairs that still need translation.

        Args:
            all_files: All files discovered for translation

        Returns:
            List of (file_path, lang) tuples not yet completed
        """
        pending = []

        for file_path in all_files:
            file_key = str(file_path)
            completed_langs = set(self.state.completed_files.get(file_key, []))

            for lang in self.state.target_langs:
                if lang not in completed_langs:
                    pending.append((file_path, lang))

        return pending

    def get_statistics(self) -> dict[str, Any]:
        """
        Get current progress statistics.

        Returns:
            Dictionary with progress statistics
        """
        total_translations = self.state.total_files * len(self.state.target_langs) if self.state.target_langs else 0
        completed = self.state.translations_completed

        return {
            'run_id': self.state.run_id,
            'site_id': self.state.site_id,
            'total_files': self.state.total_files,
            'files_processed': self.state.files_processed,
            'translations_completed': self.state.translations_completed,
            'translations_failed': self.state.translations_failed,
            'translations_pending': max(0, total_translations - completed),
            'progress_percent': (
                (completed / total_translations * 100)
                if total_translations > 0 else 0
            ),
            'started_at': self.state.started_at,
            'last_updated': self.state.last_updated
        }

    def clear(self) -> None:
        """Remove progress file (called on successful completion)."""
        if self.progress_file.exists():
            self.progress_file.unlink()
            logger.info(f"Cleared progress file: {self.progress_file}")

    def is_complete(self) -> bool:
        """
        Check if all work is complete.

        Returns:
            True if all translations are completed
        """
        if not self.state.target_langs or self.state.total_files == 0:
            return True

        total_translations = self.state.total_files * len(self.state.target_langs)
        return self.state.translations_completed >= total_translations

    @classmethod
    def find_latest(cls, progress_dir: Path, site_id: str) -> Optional['ProgressTracker']:
        """
        Find the most recent progress file for a site.

        Args:
            progress_dir: Directory containing progress files
            site_id: Site identifier

        Returns:
            ProgressTracker instance or None if no progress found
        """
        progress_dir = Path(progress_dir)
        if not progress_dir.exists():
            return None

        progress_files = list(progress_dir.glob("progress_*.json"))
        if not progress_files:
            return None

        # Find most recent for this site
        latest_file = None
        latest_time = None

        for pf in progress_files:
            try:
                with open(pf, encoding='utf-8') as f:
                    data = json.load(f)

                if data.get('site_id') == site_id:
                    updated_str = data.get('last_updated', '')
                    if updated_str:
                        # Handle both timezone-aware and naive timestamps
                        updated = datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
                        if latest_time is None or updated > latest_time:
                            latest_time = updated
                            latest_file = pf
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Skipping corrupted progress file {pf}: {e}")
                continue

        if latest_file:
            run_id = latest_file.stem.replace('progress_', '')
            return cls(progress_dir=progress_dir, run_id=run_id)

        return None

    @classmethod
    def list_all(cls, progress_dir: Path) -> list[dict[str, Any]]:
        """
        List all progress files with their statistics.

        Args:
            progress_dir: Directory containing progress files

        Returns:
            List of dictionaries with progress info
        """
        progress_dir = Path(progress_dir)
        if not progress_dir.exists():
            return []

        results = []
        for pf in progress_dir.glob("progress_*.json"):
            try:
                with open(pf, encoding='utf-8') as f:
                    data = json.load(f)

                results.append({
                    'file': str(pf),
                    'run_id': data.get('run_id', 'unknown'),
                    'site_id': data.get('site_id', 'unknown'),
                    'translations_completed': data.get('translations_completed', 0),
                    'translations_failed': data.get('translations_failed', 0),
                    'last_updated': data.get('last_updated', '')
                })
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        # Sort by last_updated descending
        results.sort(key=lambda x: x.get('last_updated', ''), reverse=True)
        return results

    @staticmethod
    def validate_progress_file(progress_file: Path) -> tuple[bool, str, bool]:
        """
        RES-07: Validate progress file integrity.

        Checks:
        - File is valid JSON
        - Required fields present
        - Schema version supported
        - Data types correct
        - Logical consistency (e.g., completed_files <= total_files)

        Args:
            progress_file: Path to progress file

        Returns:
            (is_valid: bool, error_message: str, is_recoverable: bool)
        """
        try:
            with open(progress_file, encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return (False, f"Invalid JSON: {e}", False)
        except FileNotFoundError:
            return (False, "File not found", False)
        except Exception as e:
            return (False, f"Cannot read file: {e}", False)

        # Check required fields
        required_fields = [
            'run_id', 'schema_version', 'site_id',
            'total_files', 'completed_files', 'started_at'
        ]

        missing = [f for f in required_fields if f not in data]
        if missing:
            return (False, f"Missing fields: {missing}", True)

        # Check schema version
        version = data.get('schema_version')
        if version != '1.0':
            return (False, f"Unsupported schema version: {version}", False)

        # Check data types
        try:
            total_files = int(data['total_files'])
            if total_files < 0:
                return (False, "total_files cannot be negative", True)

            completed = data['completed_files']
            if not isinstance(completed, dict):
                return (False, "completed_files must be a dict", True)

        except (ValueError, TypeError) as e:
            return (False, f"Invalid data type: {e}", True)

        # Check logical consistency
        num_completed = sum(len(langs) if isinstance(langs, list) else 0
                           for langs in data['completed_files'].values())
        if num_completed > total_files * 10:  # Sanity check (10 languages max)
            return (False, "Suspiciously high completion count", True)

        return (True, "Valid", False)

    @classmethod
    def recover_progress_file(cls, progress_file: Path) -> Optional['ProgressTracker']:
        """
        RES-07: Attempt to recover corrupted progress file.

        Recovery strategies:
        1. Try to salvage partial data
        2. Reset to safe state
        3. Return None if unrecoverable

        Args:
            progress_file: Path to corrupted progress file

        Returns:
            ProgressTracker with recovered state, or None
        """
        logger.warning(f"Attempting to recover progress file: {progress_file}")

        try:
            with open(progress_file, encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            logger.error("Progress file has invalid JSON - unrecoverable")
            return None
        except Exception as e:
            logger.error(f"Cannot read progress file: {e}")
            return None

        # Try to extract essential fields
        try:
            run_id = data.get('run_id', str(uuid.uuid4()))
            site_id = data.get('site_id', 'unknown')
            source_dir = data.get('source_dir', '.')
            output_dir = data.get('output_dir', 'output')
            target_langs = data.get('target_langs', [])

            # Ensure target_langs is a list
            if not isinstance(target_langs, list):
                target_langs = []

            # Create new tracker with recovered data
            tracker = cls(
                progress_dir=progress_file.parent,
                run_id=run_id,
                site_id=site_id,
                source_dir=Path(source_dir),
                output_dir=Path(output_dir),
                target_langs=target_langs
            )

            # Try to recover completed_files
            completed = data.get('completed_files', {})
            if isinstance(completed, dict):
                # Validate and clean completed_files
                clean_completed = {}
                for file_key, langs in completed.items():
                    if isinstance(langs, list):
                        clean_completed[file_key] = [l for l in langs if isinstance(l, str)]
                    elif isinstance(langs, str):
                        clean_completed[file_key] = [langs]

                tracker.state.completed_files = clean_completed
                tracker.state.translations_completed = sum(
                    len(langs) for langs in clean_completed.values()
                )

                # Calculate files_processed
                if target_langs:
                    tracker.state.files_processed = len([
                        f for f, langs in clean_completed.items()
                        if set(langs) >= set(target_langs)
                    ])
                else:
                    tracker.state.files_processed = len(clean_completed)

            # Try to recover failed_files
            failed = data.get('failed_files', {})
            if isinstance(failed, dict):
                clean_failed = {}
                for file_key, lang_errors in failed.items():
                    if isinstance(lang_errors, dict):
                        clean_failed[file_key] = {
                            k: str(v) for k, v in lang_errors.items()
                            if isinstance(k, str)
                        }
                tracker.state.failed_files = clean_failed
                tracker.state.translations_failed = sum(
                    len(errs) for errs in clean_failed.values()
                )

            # Recover total_files if present
            total_files = data.get('total_files', 0)
            if isinstance(total_files, (int, float)) and total_files >= 0:
                tracker.state.total_files = int(total_files)

            logger.info(
                f"Successfully recovered progress: "
                f"{tracker.state.files_processed} files, "
                f"{tracker.state.translations_completed} translations"
            )

            # Save recovered state
            tracker._save_state()

            return tracker

        except Exception as e:
            logger.error(f"Recovery failed: {e}")
            return None
