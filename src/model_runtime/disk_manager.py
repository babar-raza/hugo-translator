"""Disk space management for model storage."""
import shutil
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DiskUsage:
    """Disk usage statistics."""
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_used: float

    @property
    def total_gb(self) -> float:
        """Total space in GB."""
        return self.total_bytes / (1024 ** 3)

    @property
    def used_gb(self) -> float:
        """Used space in GB."""
        return self.used_bytes / (1024 ** 3)

    @property
    def free_gb(self) -> float:
        """Free space in GB."""
        return self.free_bytes / (1024 ** 3)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total_gb": round(self.total_gb, 2),
            "used_gb": round(self.used_gb, 2),
            "free_gb": round(self.free_gb, 2),
            "percent_used": round(self.percent_used, 1)
        }


@dataclass
class ModelDiskInfo:
    """Disk usage info for a single model."""
    model_id: str
    path: Path
    size_mb: float
    last_accessed: Optional[str] = None
    backend: Optional[str] = None

    @property
    def size_gb(self) -> float:
        """Size in GB."""
        return self.size_mb / 1024

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "model_id": self.model_id,
            "path": str(self.path),
            "size_mb": round(self.size_mb, 1),
            "size_gb": round(self.size_gb, 2),
            "last_accessed": self.last_accessed,
            "backend": self.backend
        }


class DiskManager:
    """Manage disk space for model storage."""

    # Warning thresholds
    WARN_THRESHOLD = 0.90  # Warn at 90% full
    CRITICAL_THRESHOLD = 0.95  # Critical at 95% full

    def __init__(self, models_dir: str = "models"):
        """Initialize disk manager.

        Args:
            models_dir: Root directory for models
        """
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def get_disk_usage(self) -> DiskUsage:
        """Get disk usage statistics for models partition.

        Returns:
            DiskUsage object with usage statistics
        """
        stat = shutil.disk_usage(self.models_dir)

        return DiskUsage(
            total_bytes=stat.total,
            used_bytes=stat.used,
            free_bytes=stat.free,
            percent_used=(stat.used / stat.total) * 100
        )

    def get_models_usage(self) -> List[ModelDiskInfo]:
        """Get disk usage for each model.

        Returns:
            List of ModelDiskInfo for all models
        """
        models = []

        # Scan backend directories
        for backend_dir in self.models_dir.iterdir():
            if not backend_dir.is_dir():
                continue

            backend = backend_dir.name

            # Scan model directories
            for model_dir in backend_dir.iterdir():
                if not model_dir.is_dir() or model_dir.name.startswith('.'):
                    continue

                model_id = model_dir.name
                size_mb = self._calculate_dir_size(model_dir)

                # Try to get last access time
                last_accessed = None
                metadata_file = model_dir / ".metadata.json"
                if metadata_file.exists():
                    last_accessed = datetime.fromtimestamp(
                        metadata_file.stat().st_mtime
                    ).isoformat()

                models.append(ModelDiskInfo(
                    model_id=model_id,
                    path=model_dir,
                    size_mb=size_mb,
                    last_accessed=last_accessed,
                    backend=backend
                ))

        return sorted(models, key=lambda m: m.size_mb, reverse=True)

    def _calculate_dir_size(self, path: Path) -> float:
        """Calculate total size of directory in MB.

        Args:
            path: Directory path

        Returns:
            Size in MB
        """
        total = 0
        try:
            for item in path.rglob('*'):
                if item.is_file():
                    total += item.stat().st_size
        except (PermissionError, OSError) as e:
            logger.warning(f"Error calculating size for {path}: {e}")

        return total / (1024 * 1024)

    def estimate_space_needed(self, model_sizes_mb: List[float]) -> float:
        """Estimate space needed for downloading models.

        Args:
            model_sizes_mb: List of model sizes in MB

        Returns:
            Estimated total space needed in MB (with 10% buffer)
        """
        total = sum(model_sizes_mb)
        # Add 10% buffer for temporary files, metadata, etc.
        return total * 1.1

    def check_space_available(self, needed_mb: float) -> Tuple[bool, str]:
        """Check if sufficient space is available.

        Args:
            needed_mb: Space needed in MB

        Returns:
            Tuple of (sufficient: bool, message: str)
        """
        usage = self.get_disk_usage()
        needed_bytes = needed_mb * 1024 * 1024

        if needed_bytes > usage.free_bytes:
            return False, (
                f"Insufficient disk space. Need {needed_mb/1024:.2f} GB, "
                f"but only {usage.free_gb:.2f} GB available."
            )

        # Check if download would push over critical threshold
        projected_used = (usage.used_bytes + needed_bytes) / usage.total_bytes

        if projected_used > self.CRITICAL_THRESHOLD:
            return False, (
                f"Download would exceed critical threshold ({self.CRITICAL_THRESHOLD*100}%). "
                f"Projected usage: {projected_used*100:.1f}%"
            )

        if projected_used > self.WARN_THRESHOLD:
            return True, (
                f"Warning: Download will use {projected_used*100:.1f}% of disk. "
                f"Consider cleaning up after completion."
            )

        return True, f"Sufficient space available ({usage.free_gb:.2f} GB free)"

    def find_cleanup_candidates(
        self,
        min_size_mb: float = 100,
        days_since_access: Optional[int] = None
    ) -> List[ModelDiskInfo]:
        """Find models that could be cleaned up.

        Args:
            min_size_mb: Minimum size to consider for cleanup (default: 100 MB)
            days_since_access: Only include if not accessed in N days

        Returns:
            List of ModelDiskInfo for cleanup candidates
        """
        models = self.get_models_usage()
        candidates = []

        for model in models:
            # Skip small models
            if model.size_mb < min_size_mb:
                continue

            # Check access time if specified
            if days_since_access is not None and model.last_accessed:
                try:
                    last_access = datetime.fromisoformat(model.last_accessed)
                    days_ago = (datetime.now() - last_access).days
                    if days_ago < days_since_access:
                        continue
                except ValueError:
                    pass

            candidates.append(model)

        return candidates

    def get_total_models_size(self) -> float:
        """Get total size of all models in GB.

        Returns:
            Total size in GB
        """
        models = self.get_models_usage()
        total_mb = sum(m.size_mb for m in models)
        return total_mb / 1024

    def get_usage_by_backend(self) -> Dict[str, float]:
        """Get disk usage grouped by backend.

        Returns:
            Dictionary mapping backend name to size in GB
        """
        models = self.get_models_usage()
        usage = {}

        for model in models:
            backend = model.backend or "unknown"
            usage[backend] = usage.get(backend, 0) + model.size_gb

        return usage
