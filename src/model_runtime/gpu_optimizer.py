"""
GPU-specific runtime optimization for translation models.

Provides automatic tuning of batch size based on available VRAM
for optimal GPU performance while avoiding OOM errors.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

try:
    import torch
except ImportError:
    torch = None

logger = logging.getLogger(__name__)


@dataclass
class GPUConfig:
    """Runtime configuration for GPU-optimized translation."""

    batch_size: int
    device: str
    estimated_vram_mb: float
    total_vram_mb: float
    target_utilization: float


class GPUOptimizer:
    """
    GPU-specific runtime optimizer.

    Detects GPU capabilities and computes optimal batch size based on:
    - Available VRAM
    - Model size and precision
    - Target VRAM utilization (default 85%)
    """

    # Constants for heuristics
    MIN_BATCH_SIZE = 1
    MAX_BATCH_SIZE = 64
    CUDA_RESERVED_MB = 500  # Reserve for CUDA overhead

    # VRAM requirements per batch item (MB) - empirical estimates
    # Format: model_size -> precision -> MB per batch item
    VRAM_PER_ITEM = {
        "600M": {"fp32": 50, "fp16": 25, "int8": 15},
        "1.3B": {"fp32": 80, "fp16": 40, "int8": 20},
        "3.3B": {"fp32": 150, "fp16": 75, "int8": 35},
    }

    # Model base memory (loaded model weights + buffers) in MB
    # Format: model_size -> precision -> base VRAM in MB
    MODEL_BASE_VRAM = {
        "600M": {"fp32": 2400, "fp16": 1200, "int8": 600},
        "1.3B": {"fp32": 5200, "fp16": 2600, "int8": 1300},
        "3.3B": {"fp32": 13200, "fp16": 6600, "int8": 3300},
    }

    def __init__(
        self,
        model_name: Optional[str] = None,
        precision: str = "fp16",
        batch_size_override: Optional[int] = None,
        target_utilization: float = 0.85,
        device_id: int = 0,
    ):
        """
        Initialize GPU optimizer.

        Args:
            model_name: Model name or path (used to infer size)
            precision: Loading precision (fp32, fp16, int8)
            batch_size_override: Manual override for batch size
            target_utilization: Target VRAM utilization (0.0-1.0, default 0.85)
            device_id: CUDA device ID (default 0)
        """
        self.model_name = model_name
        self.precision = precision
        self.batch_size_override = batch_size_override
        self.target_utilization = max(0.5, min(0.95, target_utilization))
        self.device_id = device_id

    def optimize(self) -> GPUConfig:
        """
        Compute optimal runtime configuration for current GPU.

        Returns:
            GPUConfig with optimized batch size and estimates

        Raises:
            RuntimeError: If CUDA is not available
        """
        # Check CUDA availability
        if torch is None:
            raise RuntimeError("PyTorch not installed")

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available")

        if self.device_id >= torch.cuda.device_count():
            raise RuntimeError(
                f"Invalid device ID {self.device_id}. "
                f"Available devices: {torch.cuda.device_count()}"
            )

        # Detect GPU memory
        total_vram_mb = self._detect_gpu_vram()

        # Infer model size from name
        model_size = self._infer_model_size(self.model_name)

        # Compute optimal batch size
        batch_size = self._compute_batch_size(
            total_vram_mb=total_vram_mb,
            model_size=model_size,
            precision=self.precision,
        )

        # Apply override if specified
        if self.batch_size_override is not None:
            batch_size = self._clamp_batch_size(self.batch_size_override)
            logger.info(f"Using batch size override: {batch_size}")

        # Estimate actual VRAM usage
        estimated_vram_mb = self._estimate_vram_usage(
            model_size=model_size,
            precision=self.precision,
            batch_size=batch_size,
        )

        utilization = estimated_vram_mb / total_vram_mb

        # Log configuration
        logger.info(
            f"GPU optimization: VRAM={total_vram_mb:.0f}MB, model={model_size}, "
            f"precision={self.precision}, batch_size={batch_size}, "
            f"estimated_usage={estimated_vram_mb:.0f}MB ({utilization*100:.1f}%)"
        )

        return GPUConfig(
            batch_size=batch_size,
            device=f"cuda:{self.device_id}",
            estimated_vram_mb=estimated_vram_mb,
            total_vram_mb=total_vram_mb,
            target_utilization=self.target_utilization,
        )

    def _detect_gpu_vram(self) -> float:
        """
        Detect total GPU VRAM in MB.

        Returns:
            Total VRAM in megabytes
        """
        props = torch.cuda.get_device_properties(self.device_id)
        total_bytes = props.total_memory
        total_mb = total_bytes / (1024**2)

        logger.debug(
            f"Detected GPU: {props.name}, VRAM: {total_mb:.0f}MB "
            f"({total_mb/1024:.1f}GB)"
        )

        return total_mb

    def _infer_model_size(self, model_name: Optional[str]) -> str:
        """
        Infer model size category from model name.

        Args:
            model_name: Model name or path

        Returns:
            Model size category (600M, 1.3B, 3.3B)
        """
        if model_name is None:
            # Default to largest model (conservative)
            logger.warning("Model name not provided, assuming 3.3B model size")
            return "3.3B"

        # Extract size from common patterns
        # Examples: "facebook/nllb-200-3.3B", "nllb-200-distilled-600M"
        size_patterns = [
            (r"600M|distilled-600M", "600M"),
            (r"1\.?3B", "1.3B"),
            (r"3\.?3B", "3.3B"),
        ]

        for pattern, size in size_patterns:
            if re.search(pattern, model_name, re.IGNORECASE):
                logger.debug(f"Inferred model size: {size} from '{model_name}'")
                return size

        # Default to largest (conservative)
        logger.warning(
            f"Could not infer model size from '{model_name}', assuming 3.3B"
        )
        return "3.3B"

    def _compute_batch_size(
        self,
        total_vram_mb: float,
        model_size: str,
        precision: str,
    ) -> int:
        """
        Compute optimal batch size based on VRAM and model characteristics.

        Strategy:
        - Reserve CUDA_RESERVED_MB for CUDA overhead
        - Allocate MODEL_BASE_VRAM for model weights
        - Use remaining VRAM for batches to hit target_utilization
        - Enforce safety bounds [MIN_BATCH_SIZE, MAX_BATCH_SIZE]

        Args:
            total_vram_mb: Total GPU VRAM
            model_size: Model size category (600M, 1.3B, 3.3B)
            precision: Loading precision (fp32, fp16, int8)

        Returns:
            Recommended batch size
        """
        # Get model parameters
        base_vram = self.MODEL_BASE_VRAM.get(model_size, {}).get(
            precision, self.MODEL_BASE_VRAM["3.3B"][precision]
        )
        vram_per_item = self.VRAM_PER_ITEM.get(model_size, {}).get(
            precision, self.VRAM_PER_ITEM["3.3B"][precision]
        )

        # Calculate target VRAM allocation
        target_vram = total_vram_mb * self.target_utilization

        # Calculate available VRAM for batching
        available_for_batch = target_vram - base_vram - self.CUDA_RESERVED_MB

        if available_for_batch <= 0:
            logger.warning(
                f"Model base VRAM ({base_vram}MB) + reserved ({self.CUDA_RESERVED_MB}MB) "
                f"exceeds target VRAM ({target_vram:.0f}MB). Using minimum batch size."
            )
            return self.MIN_BATCH_SIZE

        # Calculate batch size
        optimal_batch = int(available_for_batch / vram_per_item)

        # Enforce bounds
        batch_size = self._clamp_batch_size(optimal_batch)

        if batch_size != optimal_batch:
            logger.info(
                f"Optimal batch size {optimal_batch} clamped to {batch_size}"
            )

        return batch_size

    def _estimate_vram_usage(
        self,
        model_size: str,
        precision: str,
        batch_size: int,
    ) -> float:
        """
        Estimate total VRAM usage for given configuration.

        Args:
            model_size: Model size category
            precision: Loading precision
            batch_size: Batch size

        Returns:
            Estimated VRAM usage in MB
        """
        base_vram = self.MODEL_BASE_VRAM.get(model_size, {}).get(
            precision, self.MODEL_BASE_VRAM["3.3B"][precision]
        )
        vram_per_item = self.VRAM_PER_ITEM.get(model_size, {}).get(
            precision, self.VRAM_PER_ITEM["3.3B"][precision]
        )

        total_vram = (
            base_vram + self.CUDA_RESERVED_MB + (vram_per_item * batch_size)
        )

        return total_vram

    def _clamp_batch_size(self, batch_size: int) -> int:
        """
        Clamp batch size to safety bounds.

        Args:
            batch_size: Proposed batch size

        Returns:
            Clamped batch size in [MIN_BATCH_SIZE, MAX_BATCH_SIZE]
        """
        clamped = max(self.MIN_BATCH_SIZE, min(self.MAX_BATCH_SIZE, batch_size))

        if clamped != batch_size:
            logger.debug(
                f"Batch size {batch_size} clamped to bounds [{self.MIN_BATCH_SIZE}, "
                f"{self.MAX_BATCH_SIZE}] -> {clamped}"
            )

        return clamped
