"""
Model Store and Manager - Deterministic model acquisition and organization.

Manages model downloads, storage layout, and manifest tracking according to
specs/models/ORGANIZATION.md specifications.

Key Features:
- Deterministic local paths (models/ directory, NOT HuggingFace cache)
- Model manifest tracking (models/model_manifest.json)
- Permission-based download control (no silent downloads in production)
- Support for multilingual, Opus pair, and CT2 quantized models
"""
import hashlib
import json
import logging
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from .registry import ModelInfo, ModelRegistry

logger = logging.getLogger(__name__)


class ModelDownloadError(Exception):
    """Raised when model download fails."""
    pass


class ModelNotFoundError(Exception):
    """Raised when model is not found locally and downloads are disabled."""
    pass


class ModelManifest:
    """
    Manages models/model_manifest.json for tracking downloaded models.

    Manifest Schema:
    {
      "version": "1.0",
      "last_updated": "2026-01-17T14:30:00Z",
      "models": [
        {
          "model_id": "m2m100_418m",
          "local_path": "models/m2m100_418M",
          "download_source": "huggingface:facebook/m2m100_418M",
          "backend": "huggingface",
          "size_mb": 1600,
          "files": [
            {"name": "pytorch_model.bin", "size_bytes": 1677721600, "sha256": "abc123..."}
          ],
          "downloaded_at": "2026-01-17T10:00:00Z",
          "verified": true
        }
      ]
    }
    """

    def __init__(self, manifest_path: Path = Path("models/model_manifest.json")):
        """
        Initialize manifest manager.

        Args:
            manifest_path: Path to manifest JSON file
        """
        self.manifest_path = manifest_path
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load manifest from disk or create empty."""
        if not self.manifest_path.exists():
            return {
                "version": "1.0",
                "last_updated": datetime.now(UTC).isoformat(),
                "models": []
            }

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid manifest JSON at {self.manifest_path}: {e}")
            # Backup corrupted manifest
            backup_path = self.manifest_path.with_suffix(".json.backup")
            if self.manifest_path.exists():
                self.manifest_path.rename(backup_path)
                logger.warning(f"Backed up corrupted manifest to {backup_path}")
            return {
                "version": "1.0",
                "last_updated": datetime.now(UTC).isoformat(),
                "models": []
            }

    def save(self) -> None:
        """Save manifest to disk atomically."""
        self._data["last_updated"] = datetime.now(UTC).isoformat()

        # Ensure directory exists
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write using temp file + rename
        temp_path = self.manifest_path.with_suffix(".json.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, sort_keys=False)

            # Atomic rename (Windows: requires removing target first)
            if self.manifest_path.exists():
                self.manifest_path.unlink()
            temp_path.rename(self.manifest_path)

            logger.debug(f"Manifest saved to {self.manifest_path}")
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise IOError(f"Failed to save manifest: {e}") from e

    def get_model_entry(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get manifest entry for model."""
        for entry in self._data["models"]:
            if entry["model_id"] == model_id:
                return entry
        return None

    def add_or_update_model(
        self,
        model_id: str,
        local_path: Path,
        download_source: str,
        backend: str,
        size_mb: float,
        files: List[Dict[str, Any]]
    ) -> None:
        """
        Add or update model entry in manifest.

        Args:
            model_id: Model identifier
            local_path: Path where model is stored
            download_source: Source (e.g., "huggingface:facebook/m2m100_418M")
            backend: Backend type (huggingface, ctranslate2, opus)
            size_mb: Total size in MB
            files: List of file metadata with checksums
        """
        entry = {
            "model_id": model_id,
            "local_path": str(local_path),
            "download_source": download_source,
            "backend": backend,
            "size_mb": round(size_mb, 2),
            "files": files,
            "downloaded_at": datetime.now(UTC).isoformat(),
            "verified": True
        }

        # Remove existing entry if present
        self._data["models"] = [
            m for m in self._data["models"] if m["model_id"] != model_id
        ]

        # Add new entry
        self._data["models"].append(entry)

        logger.info(f"Manifest entry updated: {model_id} -> {local_path}")

    def remove_model(self, model_id: str) -> None:
        """Remove model entry from manifest."""
        self._data["models"] = [
            m for m in self._data["models"] if m["model_id"] != model_id
        ]
        logger.info(f"Manifest entry removed: {model_id}")

    def list_models(self) -> List[str]:
        """List all model IDs in manifest."""
        return [entry["model_id"] for entry in self._data["models"]]

    def is_model_present(self, model_id: str) -> bool:
        """Check if model is in manifest and marked verified."""
        entry = self.get_model_entry(model_id)
        return entry is not None and entry.get("verified", False)


class ModelStore:
    """
    Manages model storage, download, and organization.

    Implements deterministic path layout from specs/models/ORGANIZATION.md:
    - Multilingual HF: models/<canonical-dir>/ (e.g., models/m2m100_418M/)
    - Opus pairs: models/opus/opus-mt-en-<lang>/ (e.g., models/opus/opus-mt-en-fr/)
    - CT2 quantized: models/ct2/<model_id>/ (e.g., models/ct2/m2m100_418m_int8/)
    """

    def __init__(
        self,
        registry: ModelRegistry,
        models_dir: Path = Path("models"),
        allow_downloads: bool = False
    ):
        """
        Initialize model store.

        Args:
            registry: ModelRegistry instance
            models_dir: Base directory for model storage (default: models/)
            allow_downloads: Whether to allow automatic downloads (default: False)
        """
        self.registry = registry
        self.models_dir = models_dir
        self.allow_downloads = allow_downloads
        self.manifest = ModelManifest(models_dir / "model_manifest.json")

        # Ensure base directories exist
        self.models_dir.mkdir(parents=True, exist_ok=True)
        (self.models_dir / "opus").mkdir(exist_ok=True)
        (self.models_dir / "ct2").mkdir(exist_ok=True)

    def resolve_local_path(self, model_info: ModelInfo) -> Path:
        """
        Resolve deterministic local path for model according to spec.

        Args:
            model_info: Model metadata

        Returns:
            Path where model should be stored

        Layout:
        - Multilingual HF: models/<local_path or inferred from hf_id>
        - Opus pair: models/opus/opus-mt-en-<lang>/
        - CT2: models/ct2/<model_id>/
        """
        # If local_path is specified in registry, use it (relative to models_dir)
        if model_info.local_path:
            path = Path(model_info.local_path)
            # Make absolute if relative
            if not path.is_absolute():
                path = self.models_dir / path
            return path

        # Infer path based on backend and model_id
        if model_info.backend == "ctranslate2":
            # CT2 models: models/ct2/<model_id>/
            return self.models_dir / "ct2" / model_info.model_id

        elif model_info.hf_model_id and "opus-mt-" in model_info.hf_model_id:
            # Opus models: models/opus/<repo-name>/
            # e.g., Helsinki-NLP/opus-mt-en-fr -> models/opus/opus-mt-en-fr/
            repo_name = model_info.hf_model_id.split("/")[-1]
            return self.models_dir / "opus" / repo_name

        else:
            # Multilingual HF: models/<model_id>/
            return self.models_dir / model_info.model_id

    def check_model_present(self, model_info: ModelInfo) -> bool:
        """
        Check if model is present locally.

        Args:
            model_info: Model metadata

        Returns:
            True if model files exist and are valid
        """
        local_path = self.resolve_local_path(model_info)

        # Check if directory exists
        if not local_path.exists():
            return False

        # For HuggingFace models, check for config.json
        if model_info.backend == "huggingface":
            if not (local_path / "config.json").exists():
                logger.debug(f"Model incomplete: missing config.json at {local_path}")
                return False

        # For CT2 models, check for model.bin
        elif model_info.backend == "ctranslate2":
            if not (local_path / "model.bin").exists():
                logger.debug(f"CT2 model incomplete: missing model.bin at {local_path}")
                return False

        # Model appears valid
        return True

    def ensure_model_downloaded(self, model_id: str) -> Path:
        """
        Ensure model is downloaded, downloading if necessary and allowed.

        Args:
            model_id: Model identifier from registry

        Returns:
            Path to local model directory

        Raises:
            ModelNotFoundError: If model not present and downloads disabled
            ModelDownloadError: If download fails
        """
        model_info = self.registry.get_model(model_id)
        local_path = self.resolve_local_path(model_info)

        # Check if already present
        if self.check_model_present(model_info):
            logger.debug(f"Model already present: {model_id} at {local_path}")
            return local_path

        # Model not present - check if downloads allowed
        if not self.allow_downloads:
            raise ModelNotFoundError(
                f"Model '{model_id}' not found at {local_path} and downloads are disabled. "
                f"Enable downloads with --allow-downloads or manually download first."
            )

        # Download model
        logger.info(f"Downloading model: {model_id} to {local_path}")
        return self._download_model(model_info, local_path)

    def _download_model(
        self,
        model_info: ModelInfo,
        local_path: Path,
        max_retries: int = 3
    ) -> Path:
        """
        Download model from HuggingFace Hub.

        Args:
            model_info: Model metadata
            local_path: Target directory
            max_retries: Number of retry attempts

        Returns:
            Path to downloaded model

        Raises:
            ModelDownloadError: If download fails
        """
        if not model_info.hf_model_id:
            raise ModelDownloadError(
                f"Cannot download model '{model_info.model_id}': no hf_model_id specified"
            )

        try:
            from huggingface_hub import snapshot_download
        except ImportError as e:
            raise ModelDownloadError(
                "huggingface_hub is required for model downloads. "
                "Install with: pip install huggingface_hub"
            ) from e

        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Download with retry logic
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Downloading {model_info.hf_model_id} "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )

                downloaded_path = snapshot_download(
                    repo_id=model_info.hf_model_id,
                    local_dir=str(local_path),
                    local_dir_use_symlinks=False,  # Copy files, don't symlink
                    resume_download=True,  # Resume interrupted downloads
                    # ignore_patterns=["*.msgpack", "*.h5"],  # Skip unnecessary files
                )

                logger.info(f"Download complete: {model_info.model_id}")

                # Compute file checksums and update manifest
                self._update_manifest_after_download(
                    model_info, local_path, downloaded_path
                )

                return Path(downloaded_path)

            except Exception as e:
                logger.warning(
                    f"Download attempt {attempt + 1} failed for {model_info.model_id}: {e}"
                )

                if attempt == max_retries - 1:
                    # Last attempt failed
                    raise ModelDownloadError(
                        f"Failed to download {model_info.model_id} after {max_retries} attempts: {e}"
                    ) from e

                # Exponential backoff before retry
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)

        # Should never reach here, but satisfy type checker
        raise ModelDownloadError(f"Download failed for {model_info.model_id}")

    def _update_manifest_after_download(
        self,
        model_info: ModelInfo,
        local_path: Path,
        downloaded_path: str
    ) -> None:
        """
        Update manifest with download metadata and checksums.

        Args:
            model_info: Model metadata
            local_path: Target path
            downloaded_path: Actual download path from HF
        """
        # Compute file metadata with checksums
        files_metadata = []
        total_size_bytes = 0

        for file_path in Path(downloaded_path).rglob("*"):
            if file_path.is_file():
                size_bytes = file_path.stat().st_size
                total_size_bytes += size_bytes

                # Compute SHA256 for files under 100MB (skip large model files)
                if size_bytes < 100 * 1024 * 1024:
                    checksum = self._compute_sha256(file_path)
                else:
                    checksum = None

                files_metadata.append({
                    "name": file_path.name,
                    "relative_path": str(file_path.relative_to(downloaded_path)),
                    "size_bytes": size_bytes,
                    "sha256": checksum
                })

        # Update manifest
        self.manifest.add_or_update_model(
            model_id=model_info.model_id,
            local_path=local_path,
            download_source=f"huggingface:{model_info.hf_model_id}",
            backend=model_info.backend,
            size_mb=total_size_bytes / (1024 ** 2),
            files=files_metadata
        )
        self.manifest.save()

        logger.info(
            f"Manifest updated: {model_info.model_id} "
            f"({len(files_metadata)} files, {total_size_bytes / (1024**2):.1f} MB)"
        )

    def _compute_sha256(self, file_path: Path) -> str:
        """
        Compute SHA256 checksum of file.

        Args:
            file_path: Path to file

        Returns:
            Hex-encoded SHA256 hash
        """
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    def verify_model(self, model_id: str) -> bool:
        """
        Verify model integrity against manifest.

        Args:
            model_id: Model identifier

        Returns:
            True if model passes verification
        """
        # Check if model is in manifest
        manifest_entry = self.manifest.get_model_entry(model_id)
        if not manifest_entry:
            logger.warning(f"Model not in manifest: {model_id}")
            return False

        # Get local path
        model_info = self.registry.get_model(model_id)
        local_path = self.resolve_local_path(model_info)

        if not local_path.exists():
            logger.error(f"Model directory not found: {local_path}")
            return False

        # Verify files (only check files with checksums)
        files_to_verify = [
            f for f in manifest_entry.get("files", [])
            if f.get("sha256")
        ]

        verified_count = 0
        for file_meta in files_to_verify:
            file_path = local_path / file_meta["relative_path"]

            if not file_path.exists():
                logger.error(f"Missing file: {file_path}")
                return False

            # Verify checksum
            actual_checksum = self._compute_sha256(file_path)
            expected_checksum = file_meta["sha256"]

            if actual_checksum != expected_checksum:
                logger.error(
                    f"Checksum mismatch for {file_path}: "
                    f"expected {expected_checksum}, got {actual_checksum}"
                )
                return False

            verified_count += 1

        logger.info(f"Model verified: {model_id} ({verified_count} files checked)")
        return True

    def download_all_models(
        self,
        language_filter: Optional[List[str]] = None,
        max_workers: int = 3
    ) -> Dict[str, bool]:
        """
        Download all models in registry (or filtered subset).

        Args:
            language_filter: Optional list of language codes to filter models
            max_workers: Maximum parallel downloads

        Returns:
            Dict mapping model_id to success status
        """
        # Get models to download
        models_to_download = []
        for model_info in self.registry.list_models():
            # Skip if already present
            if self.check_model_present(model_info):
                logger.info(f"Skipping {model_info.model_id}: already present")
                continue

            # Apply language filter if specified
            if language_filter and model_info.supported_pairs != "all":
                if not any(
                    lang in language_filter
                    for pair in model_info.supported_pairs
                    for lang in pair
                ):
                    logger.debug(f"Skipping {model_info.model_id}: no matching language")
                    continue

            models_to_download.append(model_info)

        if not models_to_download:
            logger.info("No models to download")
            return {}

        logger.info(f"Downloading {len(models_to_download)} models...")

        # Download in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._download_model,
                    model_info,
                    self.resolve_local_path(model_info)
                ): model_info
                for model_info in models_to_download
            }

            for future in as_completed(futures):
                model_info = futures[future]
                try:
                    path = future.result()
                    results[model_info.model_id] = True
                    logger.info(f"✓ {model_info.model_id}: {path}")
                except Exception as e:
                    results[model_info.model_id] = False
                    logger.error(f"✗ {model_info.model_id}: {e}")

        return results

    def list_downloaded_models(self) -> List[str]:
        """List models that are downloaded and verified."""
        return self.manifest.list_models()

    def get_download_plan(self) -> Dict[str, Any]:
        """
        Generate download plan showing what needs to be downloaded.

        Returns:
            Dict with plan details:
            - total_models: int
            - already_present: List[str]
            - needs_download: List[str]
            - total_size_mb: float
        """
        already_present = []
        needs_download = []
        total_size_mb = 0.0

        for model_info in self.registry.list_models():
            if self.check_model_present(model_info):
                already_present.append(model_info.model_id)
            else:
                needs_download.append(model_info.model_id)
                total_size_mb += model_info.model_size_mb

        return {
            "total_models": len(self.registry.models),
            "already_present": already_present,
            "needs_download": needs_download,
            "total_size_mb": round(total_size_mb, 2),
            "needs_download_count": len(needs_download),
            "already_present_count": len(already_present)
        }
