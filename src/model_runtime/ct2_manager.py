"""
CT2 Conversion Manager - First-class CT2 workflow automation.

Manages CTranslate2 model conversions with:
- Path conventions (models/ct2/<model_id>__<quant>)
- Registry and manifest updates
- Model validation
- Device-aware conversion planning
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .ct2_converter import CT2ConversionPipeline
from .model_store import ModelManifest
from .registry import ModelInfo, ModelRegistry

logger = logging.getLogger(__name__)


@dataclass
class CT2ConversionResult:
    """Result of a CT2 conversion operation."""

    model_id: str
    source_model_id: str
    output_path: Path
    quantization: str
    size_mb: float
    success: bool
    error: str | None = None


class CT2ConversionManager:
    """
    High-level manager for CT2 model conversions.

    Handles:
    - Path conventions (models/ct2/<base_model_id>__<quant>)
    - Registry and manifest updates
    - Validation and verification
    """

    def __init__(
        self,
        registry: ModelRegistry,
        models_dir: Path = Path("models"),
        manifest_path: Path | None = None,
    ):
        """
        Initialize CT2 conversion manager.

        Args:
            registry: Model registry for metadata
            models_dir: Base directory for models (default: models/)
            manifest_path: Path to manifest (default: models/model_manifest.json)
        """
        self.registry = registry
        self.models_dir = models_dir
        self.ct2_dir = models_dir / "ct2"
        self.manifest_path = manifest_path or (models_dir / "model_manifest.json")
        self.manifest = ModelManifest(self.manifest_path)
        self.pipeline = CT2ConversionPipeline()

        # Ensure CT2 directory exists
        self.ct2_dir.mkdir(parents=True, exist_ok=True)

    def get_ct2_path(self, base_model_id: str, quantization: str) -> Path:
        """
        Get CT2 model path following convention.

        Convention: models/ct2/<base_model_id>__<quant>
        Example: models/ct2/m2m100_418m__int8

        Args:
            base_model_id: Source model ID (e.g., "m2m100_418m")
            quantization: Quantization type (e.g., "int8")

        Returns:
            Path to CT2 model directory
        """
        ct2_model_id = f"{base_model_id}__{quantization}"
        return self.ct2_dir / ct2_model_id

    def get_ct2_model_id(self, base_model_id: str, quantization: str) -> str:
        """
        Get CT2 model ID following convention.

        Args:
            base_model_id: Source model ID
            quantization: Quantization type

        Returns:
            CT2 model ID (e.g., "m2m100_418m__int8_ct2")
        """
        return f"{base_model_id}__{quantization}_ct2"

    def ensure_ct2(
        self,
        model_id: str,
        quantization: Literal["int8", "int16", "float16", "float32"] = "int8",
        device_target: Literal["cpu", "cuda"] = "cpu",
        force: bool = False,
    ) -> CT2ConversionResult:
        """
        Ensure CT2 model exists, converting if necessary.

        Steps:
        1. Check if CT2 model already exists and is valid
        2. If not, get source model path from registry/manifest
        3. Convert to CT2 format with specified quantization
        4. Validate converted model
        5. Update manifest and registry

        Args:
            model_id: Source model ID to convert (e.g., "m2m100_418m")
            quantization: Target quantization (int8 recommended for CPU)
            device_target: Target device ("cpu" or "cuda")
            force: Force reconversion even if exists

        Returns:
            CT2ConversionResult with conversion status
        """
        logger.info(f"Ensuring CT2 model: {model_id} ({quantization}, {device_target})")

        # Get CT2 paths
        ct2_path = self.get_ct2_path(model_id, quantization)
        ct2_model_id = self.get_ct2_model_id(model_id, quantization)

        # Check if already exists and valid (unless force)
        if not force and ct2_path.exists():
            if self.pipeline.validate_ct2_model(ct2_path):
                logger.info(f"CT2 model already exists and is valid: {ct2_path}")
                size_mb = sum(
                    f.stat().st_size for f in ct2_path.rglob("*") if f.is_file()
                ) / (1024 * 1024)
                return CT2ConversionResult(
                    model_id=ct2_model_id,
                    source_model_id=model_id,
                    output_path=ct2_path,
                    quantization=quantization,
                    size_mb=size_mb,
                    success=True,
                )
            else:
                logger.warning("Existing CT2 model is invalid, will reconvert")

        # Get source model info
        source_model = self.registry.get_model(model_id)
        if not source_model:
            error_msg = f"Source model not found in registry: {model_id}"
            logger.error(error_msg)
            return CT2ConversionResult(
                model_id=ct2_model_id,
                source_model_id=model_id,
                output_path=ct2_path,
                quantization=quantization,
                size_mb=0.0,
                success=False,
                error=error_msg,
            )

        # Get source model path (from manifest or local_path)
        source_path = self._get_source_model_path(source_model)
        if not source_path or not source_path.exists():
            error_msg = f"Source model not found on disk: {source_path}"
            logger.error(error_msg)
            return CT2ConversionResult(
                model_id=ct2_model_id,
                source_model_id=model_id,
                output_path=ct2_path,
                quantization=quantization,
                size_mb=0.0,
                success=False,
                error=error_msg,
            )

        # Convert model
        logger.info(f"Converting {source_path} -> {ct2_path}")
        success = self.pipeline.convert_model(
            model_path=source_path,
            output_path=ct2_path,
            quantization=quantization,
            force=force,
        )

        if not success:
            return CT2ConversionResult(
                model_id=ct2_model_id,
                source_model_id=model_id,
                output_path=ct2_path,
                quantization=quantization,
                size_mb=0.0,
                success=False,
                error="Conversion failed",
            )

        # Validate converted model
        if not self.pipeline.validate_ct2_model(ct2_path):
            return CT2ConversionResult(
                model_id=ct2_model_id,
                source_model_id=model_id,
                output_path=ct2_path,
                quantization=quantization,
                size_mb=0.0,
                success=False,
                error="Validation failed",
            )

        # Get model size
        size_mb = sum(
            f.stat().st_size for f in ct2_path.rglob("*") if f.is_file()
        ) / (1024 * 1024)

        # Update manifest
        self._update_manifest(ct2_model_id, ct2_path, source_model, size_mb, quantization)

        # Update registry
        self._update_registry(
            ct2_model_id, ct2_path, source_model, size_mb, quantization, device_target
        )

        logger.info(f"✓ CT2 conversion complete: {ct2_model_id} ({size_mb:.1f}MB)")

        return CT2ConversionResult(
            model_id=ct2_model_id,
            source_model_id=model_id,
            output_path=ct2_path,
            quantization=quantization,
            size_mb=size_mb,
            success=True,
        )

    def _get_source_model_path(self, source_model: ModelInfo) -> Path | None:
        """
        Get source model path from manifest or registry.

        Args:
            source_model: Source model info

        Returns:
            Path to source model, or None if not found
        """
        # Try manifest first
        manifest_entry = self.manifest.get_model_entry(source_model.model_id)
        if manifest_entry:
            path = Path(manifest_entry["local_path"])
            if path.exists():
                return path

        # Try local_path from registry
        if source_model.local_path:
            path = Path(source_model.local_path)
            if path.exists():
                return path

        # Try default path based on model type
        if source_model.backend == "huggingface":
            # Try models/<model_id> (lowercase HF path convention)
            if source_model.hf_model_id:
                # Extract model name from HF ID (e.g., facebook/m2m100_418M -> m2m100_418M)
                model_name = source_model.hf_model_id.split("/")[-1]
                path = self.models_dir / model_name
                if path.exists():
                    return path

        return None

    def _update_manifest(
        self,
        ct2_model_id: str,
        ct2_path: Path,
        source_model: ModelInfo,
        size_mb: float,
        quantization: str,
    ) -> None:
        """
        Update manifest with CT2 model entry.

        Args:
            ct2_model_id: CT2 model ID
            ct2_path: Path to CT2 model
            source_model: Source model info
            size_mb: Model size in MB
            quantization: Quantization type
        """
        logger.info(f"Updating manifest: {ct2_model_id}")

        # Collect file metadata
        files = []
        for file in ct2_path.rglob("*"):
            if file.is_file():
                files.append({
                    "name": file.name,
                    "relative_path": str(file.relative_to(ct2_path)),
                    "size_bytes": file.stat().st_size,
                    # Skip SHA256 for large files (manifest uses this convention)
                })

        # Add/update manifest entry
        self.manifest.add_or_update_model(
            model_id=ct2_model_id,
            local_path=str(ct2_path),
            download_source=f"ct2_conversion:{source_model.model_id}",
            backend="ctranslate2",
            size_mb=size_mb,
            files=files,
        )

        self.manifest.save()
        logger.info(f"✓ Manifest updated for {ct2_model_id}")

    def _update_registry(
        self,
        ct2_model_id: str,
        ct2_path: Path,
        source_model: ModelInfo,
        size_mb: float,
        quantization: str,
        device_target: str,
    ) -> None:
        """
        Update registry with CT2 model entry.

        Inherits supported_pairs from source model.

        Args:
            ct2_model_id: CT2 model ID
            ct2_path: Path to CT2 model
            source_model: Source model info
            size_mb: Model size in MB
            quantization: Quantization type
            device_target: Target device
        """
        logger.info(f"Updating registry: {ct2_model_id}")

        # Check if already exists
        existing = self.registry.get_model(ct2_model_id)
        if existing:
            logger.info(f"CT2 model already in registry: {ct2_model_id}")
            return

        # Create CT2 model entry (inherit supported_pairs from source)
        ct2_model = ModelInfo(
            model_id=ct2_model_id,
            name=f"{source_model.name} (CT2 {quantization.upper()})",
            backend="ctranslate2",
            supported_pairs=source_model.supported_pairs,  # Inherit language pairs
            model_size_mb=int(size_mb),
            min_ram_gb=source_model.min_ram_gb * 0.6,  # CT2 uses ~60% of original RAM
            optimal_device=device_target,
            parameters=source_model.parameters,
            license=source_model.license,
            local_path=ct2_path,
            hf_model_id=source_model.hf_model_id,
            description=f"CTranslate2 {quantization.upper()} quantized version of {source_model.model_id}",
            max_new_tokens=source_model.max_new_tokens,
        )

        # Register model
        self.registry.register_model(ct2_model)
        logger.info(f"✓ Registry updated for {ct2_model_id}")

    def list_ct2_models(self) -> list[tuple[str, bool, Path | None]]:
        """
        List all CT2 models (existing and potential).

        Returns:
            List of (model_id, exists, path) tuples
        """
        ct2_models = []

        # Check all models in registry for CT2 variants
        for model in self.registry.list_models():
            if model.backend == "ctranslate2":
                # Already a CT2 model
                exists = model.local_path and model.local_path.exists()
                ct2_models.append((model.model_id, exists, model.local_path))
            elif model.backend in ["huggingface", "opus"]:
                # Check for possible CT2 conversions
                for quant in ["int8", "float16"]:
                    ct2_path = self.get_ct2_path(model.model_id, quant)
                    ct2_model_id = self.get_ct2_model_id(model.model_id, quant)
                    exists = ct2_path.exists() and self.pipeline.validate_ct2_model(ct2_path)
                    ct2_models.append((ct2_model_id, exists, ct2_path if exists else None))

        return ct2_models

    def plan_conversion(
        self,
        model_ids: list[str],
        quantization: str = "int8",
    ) -> list[dict]:
        """
        Plan CT2 conversions without executing.

        Args:
            model_ids: List of model IDs to convert
            quantization: Target quantization

        Returns:
            List of conversion plans
        """
        plans = []

        for model_id in model_ids:
            model = self.registry.get_model(model_id)
            if not model:
                plans.append({
                    "model_id": model_id,
                    "status": "error",
                    "error": "Model not found in registry",
                })
                continue

            ct2_path = self.get_ct2_path(model_id, quantization)
            ct2_model_id = self.get_ct2_model_id(model_id, quantization)

            source_path = self._get_source_model_path(model)
            if not source_path or not source_path.exists():
                plans.append({
                    "model_id": model_id,
                    "ct2_model_id": ct2_model_id,
                    "status": "error",
                    "error": "Source model not downloaded",
                    "source_path": str(source_path) if source_path else None,
                })
                continue

            exists = ct2_path.exists() and self.pipeline.validate_ct2_model(ct2_path)

            plans.append({
                "model_id": model_id,
                "ct2_model_id": ct2_model_id,
                "status": "exists" if exists else "needs_conversion",
                "source_path": str(source_path),
                "output_path": str(ct2_path),
                "quantization": quantization,
                "estimated_size_mb": model.model_size_mb * 0.3,  # CT2 ~30% of original
            })

        return plans
