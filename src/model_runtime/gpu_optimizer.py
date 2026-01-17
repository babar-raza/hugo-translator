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
    - Target VRAM utilization (default 70%)
    """

    # Constants for heuristics
    MIN_BATCH_SIZE = 1
    MAX_BATCH_SIZE = 64
    CUDA_RESERVED_MB = 1536  # Reserve for CUDA overhead + safety margin (increased to prevent OOM)

    # VRAM requirements per batch item (MB) - conservative estimates with safety margin
    # Format: model_size -> precision -> MB per batch item
    # NOTE: These account for PEAK memory during generation (logits + activations)
    VRAM_PER_ITEM = {
        "418M": {"fp32": 120, "fp16": 80, "int8": 40},  # Increased to account for generation overhead
        "600M": {"fp32": 150, "fp16": 90, "int8": 50},  # with max_new_tokens=512
        "1.3B": {"fp32": 220, "fp16": 130, "int8": 70},  # (logits tensor dominates memory)
        "3.3B": {"fp32": 350, "fp16": 200, "int8": 100},  # Previous values were too optimistic
    }

    # Model base memory (loaded model weights + buffers) in MB
    # Format: model_size -> precision -> base VRAM in MB
    MODEL_BASE_VRAM = {
        "418M": {"fp32": 1700, "fp16": 850, "int8": 425},
        "600M": {"fp32": 2400, "fp16": 1200, "int8": 600},
        "1.3B": {"fp32": 5200, "fp16": 2600, "int8": 1300},
        "3.3B": {"fp32": 13200, "fp16": 6600, "int8": 3300},
    }

    def __init__(
        self,
        model_name: Optional[str] = None,
        precision: str = "fp16",
        batch_size_override: Optional[int] = None,
        target_utilization: float = 0.40,
        device_id: int = 0,
        max_vram_mb: Optional[float] = None,
    ):
        """
        Initialize GPU optimizer.

        Args:
            model_name: Model name or path (used to infer size)
            precision: Loading precision (fp32, fp16, int8)
            batch_size_override: Manual override for batch size
            target_utilization: Target VRAM utilization (0.0-1.0, default 0.40)
                               Reduced from 0.70 to account for generation peak memory
            device_id: CUDA device ID (default 0)
            max_vram_mb: Maximum VRAM to use (overrides detected VRAM if specified)
        """
        self.model_name = model_name
        self.precision = precision
        self.batch_size_override = batch_size_override
        self.target_utilization = max(0.3, min(0.95, target_utilization))
        self.device_id = device_id
        self.max_vram_mb = max_vram_mb

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
        detected_vram_mb = self._detect_gpu_vram()

        # Use configured max_vram_mb if specified, otherwise use detected VRAM
        total_vram_mb = self.max_vram_mb if self.max_vram_mb is not None else detected_vram_mb

        if self.max_vram_mb is not None and self.max_vram_mb < detected_vram_mb:
            logger.info(
                f"Using configured VRAM limit: {self.max_vram_mb:.0f}MB "
                f"(detected: {detected_vram_mb:.0f}MB)"
            )

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
            Model size category (418M, 600M, 1.3B, 3.3B)
        """
        if model_name is None:
            # Default to smallest model (conservative for unknown)
            logger.debug("Model name not provided to GPUOptimizer, assuming 418M model size for VRAM calculation")
            return "418M"

        # Extract size from common patterns
        # Examples: "facebook/m2m100_418M", "facebook/nllb-200-3.3B", "nllb-200-distilled-600M"
        size_patterns = [
            (r"418M|m2m100_418", "418M"),
            (r"600M|distilled-600M", "600M"),
            (r"1\.?3B", "1.3B"),
            (r"3\.?3B", "3.3B"),
        ]

        for pattern, size in size_patterns:
            if re.search(pattern, model_name, re.IGNORECASE):
                logger.debug(f"Inferred model size: {size} from '{model_name}'")
                return size

        # Default to smallest (conservative for unknown models)
        logger.warning(
            f"Could not infer model size from '{model_name}', assuming 418M (smallest)"
        )
        return "418M"

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
        # Get model parameters (fallback to 418M for unknown)
        base_vram = self.MODEL_BASE_VRAM.get(model_size, {}).get(
            precision, self.MODEL_BASE_VRAM["418M"][precision]
        )
        vram_per_item = self.VRAM_PER_ITEM.get(model_size, {}).get(
            precision, self.VRAM_PER_ITEM["418M"][precision]
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

        # Apply safety cap based on available VRAM to prevent OOM
        # For limited VRAM (<= 4GB), cap batch size more aggressively
        if total_vram_mb <= 4096:
            safety_cap = min(16, optimal_batch)  # Cap at 16 for 4GB or less
            if optimal_batch > safety_cap:
                logger.info(
                    f"Applying safety cap for limited VRAM ({total_vram_mb:.0f}MB): "
                    f"optimal={optimal_batch} -> capped={safety_cap}"
                )
                optimal_batch = safety_cap

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
            precision, self.MODEL_BASE_VRAM["418M"][precision]
        )
        vram_per_item = self.VRAM_PER_ITEM.get(model_size, {}).get(
            precision, self.VRAM_PER_ITEM["418M"][precision]
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
