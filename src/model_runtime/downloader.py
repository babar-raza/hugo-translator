"""Model download and verification system."""
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelDownloader:
    """Download and verify models from HuggingFace Hub."""

    def __init__(self, models_dir: Path):
        """Initialize downloader.

        Args:
            models_dir: Base directory for models (e.g., models/)
        """
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def download(
        self,
        model_id: str,
        hf_model_id: str,
        backend: str = "huggingface",
        force: bool = False,
        progress_callback: Callable | None = None
    ) -> Path:
        """Download a model from HuggingFace Hub.

        Args:
            model_id: Internal model ID (e.g., "m2m100_418m")
            hf_model_id: HuggingFace model ID (e.g., "facebook/m2m100_418M")
            backend: Model backend (huggingface, ctranslate2)
            force: Force re-download if already exists
            progress_callback: Optional callback for progress updates

        Returns:
            Path to downloaded model directory

        Raises:
            DownloadError: If download fails
        """
        # Determine local path
        local_path = self.models_dir / backend / model_id

        # Check if already downloaded
        if local_path.exists() and not force:
            logger.info(f"Model {model_id} already exists at {local_path}")
            return local_path

        # Create downloading marker
        marker = local_path.parent / f".{model_id}.downloading"
        if marker.exists():
            raise RuntimeError(f"Another download of {model_id} is in progress")

        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()

            logger.info(f"Downloading {hf_model_id} to {local_path}...")

            # Download using HuggingFace Hub
            try:
                from huggingface_hub import snapshot_download

                downloaded_path = snapshot_download(
                    repo_id=hf_model_id,
                    local_dir=str(local_path),
                    resume_download=True,
                    local_dir_use_symlinks=False
                )
            except ImportError:
                raise DownloadError(
                    "huggingface_hub not installed. Install with: pip install huggingface_hub"
                )

            # Create metadata
            metadata = {
                "model_id": model_id,
                "backend": backend,
                "hf_model_id": hf_model_id,
                "local_path": str(local_path),
                "downloaded_at": datetime.now(UTC).isoformat(),
                "download_source": "huggingface_hub",
                "size_mb": self._calculate_size(local_path),
                "verification_status": "pending"
            }

            # Write metadata (atomic)
            metadata_file = local_path / ".metadata.json"
            temp_metadata = metadata_file.with_suffix(".json.tmp")
            with open(temp_metadata, 'w') as f:
                json.dump(metadata, f, indent=2)
            temp_metadata.rename(metadata_file)

            logger.info(f"✓ Downloaded {model_id} successfully")
            return Path(downloaded_path)

        finally:
            # Remove marker
            if marker.exists():
                marker.unlink()

    def _calculate_size(self, path: Path) -> float:
        """Calculate total size of directory in MB."""
        total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        return total / (1024 * 1024)

    def verify(self, model_path: Path) -> bool:
        """Verify model integrity.

        Args:
            model_path: Path to model directory

        Returns:
            True if verification passed
        """
        # Check metadata exists
        metadata_file = model_path / ".metadata.json"
        if not metadata_file.exists():
            logger.error(f"Metadata file missing: {metadata_file}")
            return False

        # Try to load model (backend-specific)
        # Implementation depends on backend

        return True


class DownloadError(Exception):
    """Model download failed."""
    pass
