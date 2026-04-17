"""
HealingEngine - Unified retry and recovery logic.

Wraps existing RetryHandler to provide consistent interface for
automatic recovery from failures with exponential backoff.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.translation_engine.retry_handler import RetryHandler

logger = logging.getLogger(__name__)


class HealingEngine:
    """
    Unified healing engine for retry and recovery.

    Wraps RetryHandler to provide consistent interface for:
    - Exponential backoff retry logic
    - OOM error recovery with batch size reduction
    - Automatic GPU cache cleanup
    - Recovery callbacks for learning

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        batch_reduction_factor: Factor to reduce batch size by (default: 0.5)
        min_batch_size: Minimum batch size (default: 1)

    Example:
        # Initialize engine
        healing_engine = HealingEngine(
            max_retries=3,
            batch_reduction_factor=0.5
        )

        # Retry translation with automatic healing
        result = healing_engine.with_retry(
            func=engine.translate_file,
            file_path=Path("example.md"),
            initial_batch_size=9,
            target_lang="es"
        )

        # With recovery callback
        def on_recovery(failed_size: int, success_size: int):
            print(f"Recovered: {failed_size} -> {success_size}")

        result = healing_engine.with_retry(
            func=engine.translate_file,
            file_path=Path("example.md"),
            initial_batch_size=9,
            on_oom_recovery=on_recovery
        )
    """

    def __init__(
        self,
        max_retries: int = 3,
        batch_reduction_factor: float = 0.5,
        min_batch_size: int = 1
    ):
        """Initialize healing engine."""
        self.max_retries = max_retries
        self.batch_reduction_factor = batch_reduction_factor
        self.min_batch_size = min_batch_size

        # Create retry handler
        self.retry_handler = RetryHandler(
            max_retries=max_retries,
            batch_reduction_factor=batch_reduction_factor,
            min_batch_size=min_batch_size
        )

        logger.info(
            f"HealingEngine initialized: max_retries={max_retries}, "
            f"reduction_factor={batch_reduction_factor}, "
            f"min_batch_size={min_batch_size}"
        )

    def with_retry(
        self,
        func: Callable,
        file_path: Path,
        initial_batch_size: int,
        on_oom_recovery: Callable[[int, int], None] | None = None,
        **kwargs: Any
    ) -> Any:
        """
        Execute function with automatic retry and healing on failure.

        Uses exponential batch size reduction strategy on OOM errors:
        Example: 9 → 4 → 2 → 1

        Args:
            func: Function to execute (e.g., engine.translate_file)
            file_path: Path to file being processed
            initial_batch_size: Starting batch size
            on_oom_recovery: Optional callback after successful recovery
                            Signature: (failed_batch_size, success_batch_size) -> None
            **kwargs: Additional arguments to pass to func

        Returns:
            Result from successful function execution

        Raises:
            Exception: If all retries fail

        Example:
            result = engine.with_retry(
                func=translation_engine.translate_file,
                file_path=Path("example.md"),
                initial_batch_size=9,
                target_lang="es",
                model="m2m100_418m"
            )
        """
        logger.debug(
            f"Executing with retry: {file_path.name}, "
            f"initial_batch_size={initial_batch_size}"
        )

        return self.retry_handler.translate_file_with_retry(
            translate_func=func,
            file_path=file_path,
            initial_batch_size=initial_batch_size,
            on_oom_recovery=on_oom_recovery,
            **kwargs
        )

    def is_oom_error(self, exception: Exception) -> bool:
        """
        Check if exception is an OOM error.

        Args:
            exception: Exception to check

        Returns:
            True if OOM error, False otherwise

        Example:
            try:
                # ... code ...
            except Exception as e:
                if engine.is_oom_error(e):
                    # Handle OOM
                    pass
        """
        return self.retry_handler._is_oom_error(exception)

    def reduce_batch_size(self, current_batch_size: int) -> int:
        """
        Calculate reduced batch size for next retry.

        Args:
            current_batch_size: Current batch size

        Returns:
            Reduced batch size (respects min_batch_size)

        Example:
            new_size = engine.reduce_batch_size(9)  # Returns 4
            new_size = engine.reduce_batch_size(4)  # Returns 2
            new_size = engine.reduce_batch_size(2)  # Returns 1
            new_size = engine.reduce_batch_size(1)  # Returns 1 (min)
        """
        reduced = max(
            self.min_batch_size,
            int(current_batch_size * self.batch_reduction_factor)
        )
        logger.debug(f"Reduced batch size: {current_batch_size} -> {reduced}")
        return reduced

    def get_max_retries(self) -> int:
        """
        Get maximum number of retry attempts.

        Returns:
            Max retries

        Example:
            max_retries = engine.get_max_retries()
        """
        return self.max_retries

    def get_reduction_factor(self) -> float:
        """
        Get batch size reduction factor.

        Returns:
            Reduction factor (0-1)

        Example:
            factor = engine.get_reduction_factor()  # 0.5
        """
        return self.batch_reduction_factor

    def get_min_batch_size(self) -> int:
        """
        Get minimum batch size.

        Returns:
            Minimum batch size

        Example:
            min_size = engine.get_min_batch_size()  # 1
        """
        return self.min_batch_size

    def update_config(self, **kwargs: Any) -> None:
        """
        Update healing configuration at runtime.

        Args:
            **kwargs: Configuration fields to update

        Example:
            engine.update_config(max_retries=5, batch_reduction_factor=0.6)
        """
        if "max_retries" in kwargs:
            self.max_retries = kwargs["max_retries"]
            self.retry_handler.max_retries = kwargs["max_retries"]
            logger.info(f"Updated max_retries: {kwargs['max_retries']}")

        if "batch_reduction_factor" in kwargs:
            self.batch_reduction_factor = kwargs["batch_reduction_factor"]
            self.retry_handler.batch_reduction_factor = kwargs["batch_reduction_factor"]
            logger.info(f"Updated batch_reduction_factor: {kwargs['batch_reduction_factor']}")

        if "min_batch_size" in kwargs:
            self.min_batch_size = kwargs["min_batch_size"]
            self.retry_handler.min_batch_size = kwargs["min_batch_size"]
            logger.info(f"Updated min_batch_size: {kwargs['min_batch_size']}")

        # Log unknown keys
        known_keys = {"max_retries", "batch_reduction_factor", "min_batch_size"}
        for key in kwargs:
            if key not in known_keys:
                logger.warning(f"Unknown config key: {key}")

    def get_retry_handler(self) -> RetryHandler:
        """
        Get underlying RetryHandler for advanced usage.

        Returns:
            RetryHandler instance

        Note:
            Most code should use HealingEngine methods instead of
            accessing the handler directly.

        Example:
            handler = engine.get_retry_handler()
            # Advanced retry operations...
        """
        return self.retry_handler
