"""Model inventory management and tracking system."""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


@dataclass
class ModelEntry:
    """Single model entry in inventory."""
    model_id: str
    backend: str
    local_path: str
    size_mb: float
    downloaded_at: str
    last_verified: Optional[str] = None
    verification_status: Optional[str] = None
    hf_model_id: Optional[str] = None
    supported_pairs: Optional[str] = None
    license: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class InventoryStats:
    """Inventory statistics."""
    total_models: int
    total_size_mb: float
    total_size_gb: float
    models_by_backend: Dict[str, int]
    models_by_status: Dict[str, int]
    last_updated: str


class ModelInventory:
    """Manage model inventory database."""

    def __init__(self, models_dir: Path, inventory_file: Optional[Path] = None):
        """Initialize inventory manager.

        Args:
            models_dir: Base directory for models
            inventory_file: Path to inventory.json (default: models_dir/inventory.json)
        """
        self.models_dir = Path(models_dir)
        self.inventory_file = inventory_file or (self.models_dir / "inventory.json")

    def scan(self) -> List[ModelEntry]:
        """Scan models directory and build inventory.

        Returns:
            List of model entries
        """
        entries = []

        # Scan each backend directory
        for backend_dir in self.models_dir.iterdir():
            if not backend_dir.is_dir():
                continue
            if backend_dir.name in ['cache', '.git']:
                continue

            backend = backend_dir.name

            # Scan each model in backend
            for model_dir in backend_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                if model_dir.name.startswith('.'):
                    continue

                # Read metadata if exists
                metadata_file = model_dir / ".metadata.json"
                metadata = {}

                if metadata_file.exists():
                    try:
                        with open(metadata_file) as f:
                            metadata = json.load(f)
                    except Exception as e:
                        logger.warning(f"Could not read metadata for {model_dir.name}: {e}")

                # Calculate size
                try:
                    total_size = sum(f.stat().st_size for f in model_dir.rglob('*') if f.is_file())
                    size_mb = total_size / (1024 * 1024)
                except Exception as e:
                    logger.warning(f"Could not calculate size for {model_dir.name}: {e}")
                    size_mb = 0.0

                # Create entry
                entry = ModelEntry(
                    model_id=model_dir.name,
                    backend=backend,
                    local_path=str(model_dir.relative_to(self.models_dir.parent)),
                    size_mb=round(size_mb, 2),
                    downloaded_at=metadata.get("downloaded_at", "unknown"),
                    last_verified=metadata.get("last_verified"),
                    verification_status=metadata.get("verification_status"),
                    hf_model_id=metadata.get("hf_model_id"),
                    supported_pairs=metadata.get("supported_pairs"),
                    license=metadata.get("license")
                )

                entries.append(entry)

        return entries

    def update(self, entries: Optional[List[ModelEntry]] = None) -> None:
        """Update inventory file.

        Args:
            entries: List of model entries (scans if not provided)
        """
        if entries is None:
            entries = self.scan()

        # Build inventory data
        inventory = {
            "version": "1.0",
            "last_updated": datetime.now(UTC).isoformat(),
            "total_models": len(entries),
            "total_size_mb": sum(e.size_mb for e in entries),
            "models": [e.to_dict() for e in entries]
        }

        # Atomic write
        temp_file = self.inventory_file.with_suffix(".json.tmp")
        with open(temp_file, 'w') as f:
            json.dump(inventory, f, indent=2)
        temp_file.rename(self.inventory_file)

        logger.info(f"Updated inventory: {len(entries)} models, {inventory['total_size_mb']:.1f} MB")

    def load(self) -> List[ModelEntry]:
        """Load inventory from file.

        Returns:
            List of model entries
        """
        if not self.inventory_file.exists():
            return []

        try:
            with open(self.inventory_file) as f:
                data = json.load(f)

            return [ModelEntry(**entry) for entry in data.get("models", [])]
        except Exception as e:
            logger.error(f"Could not load inventory: {e}")
            return []

    def get_stats(self) -> InventoryStats:
        """Get inventory statistics.

        Returns:
            InventoryStats with summary data
        """
        entries = self.load()

        if not entries:
            return InventoryStats(
                total_models=0,
                total_size_mb=0.0,
                total_size_gb=0.0,
                models_by_backend={},
                models_by_status={},
                last_updated="never"
            )

        total_size_mb = sum(e.size_mb for e in entries)

        # Count by backend
        models_by_backend = {}
        for entry in entries:
            models_by_backend[entry.backend] = models_by_backend.get(entry.backend, 0) + 1

        # Count by verification status
        models_by_status = {}
        for entry in entries:
            status = entry.verification_status or "unknown"
            models_by_status[status] = models_by_status.get(status, 0) + 1

        # Get last updated time
        if self.inventory_file.exists():
            with open(self.inventory_file) as f:
                data = json.load(f)
            last_updated = data.get("last_updated", "unknown")
        else:
            last_updated = "never"

        return InventoryStats(
            total_models=len(entries),
            total_size_mb=round(total_size_mb, 2),
            total_size_gb=round(total_size_mb / 1024, 2),
            models_by_backend=models_by_backend,
            models_by_status=models_by_status,
            last_updated=last_updated
        )

    def find(
        self,
        model_id: Optional[str] = None,
        backend: Optional[str] = None,
        min_size_mb: Optional[float] = None,
        max_size_mb: Optional[float] = None,
        verification_status: Optional[str] = None
    ) -> List[ModelEntry]:
        """Find models matching criteria.

        Args:
            model_id: Filter by model ID (exact match)
            backend: Filter by backend
            min_size_mb: Minimum size in MB
            max_size_mb: Maximum size in MB
            verification_status: Filter by verification status

        Returns:
            List of matching model entries
        """
        entries = self.load()
        results = []

        for entry in entries:
            # Apply filters
            if model_id and entry.model_id != model_id:
                continue
            if backend and entry.backend != backend:
                continue
            if min_size_mb and entry.size_mb < min_size_mb:
                continue
            if max_size_mb and entry.size_mb > max_size_mb:
                continue
            if verification_status and entry.verification_status != verification_status:
                continue

            results.append(entry)

        return results
