"""
File-level OOM Retry Handler for Translation Engine.

Provides exponential batch size reduction with retry logic to handle
CUDA Out-of-Memory errors during translation. Enables autonomous recovery
without manual intervention.

Strategy: When OOM occurs, reduce batch size by 50% and retry (9→4→2→1).
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


class RetryHandler:
    """
    File-level OOM retry handler with exponential batch size reduction.

    Provides automatic recovery from CUDA OOM errors by progressively reducing
    batch size and retrying translation. Integrates with BatchStatsTracker to
    learn optimal batch sizes over time.

    Retry sequence: initial_batch_size → half → quarter → 1
    Example: 9 → 4 → 2 → 1
    """

    def __init__(
        self,
        max_retries: int = 3,
        batch_reduction_factor: float = 0.5,
        min_batch_size: int = 1,
    ):
        """
        Initialize retry handler.

        Args:
            max_retries: Maximum number of retry attempts per file
            batch_reduction_factor: Factor to reduce batch size by on each retry (default 0.5 = halve)
            min_batch_size: Minimum batch size (default 1)
        """
        self.max_retries = max_retries
        self.batch_reduction_factor = batch_reduction_factor
        self.min_batch_size = min_batch_size

        logger.debug(
            f"RetryHandler initialized: max_retries={max_retries}, "
            f"reduction_factor={batch_reduction_factor}"
        )

    def translate_file_with_retry(
        self,
        translate_func: callable,
        file_path: Path,
        initial_batch_size: int,
        on_oom_recovery: Callable[[int, int], None] | None = None,
        **kwargs
    ) -> Any:
        """
        Attempt file translation with exponential batch reduction on OOM.

        Strategy: Halve batch size on each OOM failure until success or minimum reached.
        Sequence: 9 → 4 → 2 → 1

        Args:
            translate_func: Translation function to call (e.g., engine.translate_file)
            file_path: Path to file being translated
            initial_batch_size: Starting batch size
            on_oom_recovery: Optional callback invoked after successful OOM recovery.
                            Signature: (failed_batch_size: int, success_batch_size: int) -> None
                            Called with the batch size that failed and the batch size that succeeded.
            **kwargs: Additional arguments to pass to translate_file

        Returns:
            Translation result (FileResult or similar)

        Raises:
            torch.cuda.OutOfMemoryError: If all retries fail with OOM
            Exception: If translation fails for other reasons
        """
        batch_size = initial_batch_size

        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"Attempt {attempt + 1}/{self.max_retries} for {file_path.name} "
                    f"with batch_size={batch_size}"
                )

                # Attempt translation with current batch size
                result = translate_func(
                    file_path=file_path,
                    batch_size=batch_size,
                    **kwargs
                )

                # WS2-CALLBACK: Invoke learning callback after successful recovery
                if attempt > 0 and on_oom_recovery is not None:
                    try:
                        on_oom_recovery(initial_batch_size, batch_size)
                        logger.debug(
                            f"OOM recovery callback invoked: {initial_batch_size}→{batch_size}"
                        )
                    except Exception as callback_error:
                        logger.warning(
                            f"OOM recovery callback failed (non-critical): {callback_error}"
                        )

                return result

            except Exception as e:
                # Check if it's a CUDA OOM error
                is_oom = self._is_oom_error(e)

                if is_oom and attempt < self.max_retries - 1:
                    # Reduce batch size and retry
                    batch_size = max(self.min_batch_size, batch_size // 2)

                    logger.warning(
                        f"OOM on {file_path.name} (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying with reduced batch_size={batch_size}"
                    )

                    # Aggressive GPU cleanup
                    if TORCH_AVAILABLE and torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()

                    continue

                # Non-OOM error or final attempt - re-raise
                raise

        # All retries exhausted
        logger.error(
            f"File translation failed after {self.max_retries} attempts with exponential batch reduction. "
            f"Final batch_size={batch_size}"
        )
        raise

    def _is_oom_error(self, exception: Exception) -> bool:
        """
        OOM-01: Check if exception is CUDA OOM error with enhanced logging.

        Args:
            exception: Exception to check

        Returns:
            True if this is a CUDA OOM error, False otherwise
        """
        error_str = str(exception).lower()

        oom_patterns = [
            "cuda out of memory",
            "out of memory",
            "oom",
            "cudnn_status_not_enough_memory",
            "cublas error",
        ]

        for pattern in oom_patterns:
            if pattern in error_str:
                logger.debug(
                    f"OOM detected in RetryHandler: pattern='{pattern}' matched in error"
                )
                return True

        # Log non-OOM for troubleshooting
        error_preview = error_str[:150] + "..." if len(error_str) > 150 else error_str
        logger.debug(f"NOT OOM in RetryHandler: {error_preview}")
        return False
