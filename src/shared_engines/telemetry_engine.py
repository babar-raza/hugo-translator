"""
TelemetryEngine - Unified telemetry for events, metrics, and benchmarking.

Wraps existing TranslationTelemetry to provide consistent telemetry interface
for both manual CLI and autonomous workers.
"""

import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from src.observability.telemetry_integration import (
    TranslationTelemetry,
    get_telemetry,
    configure_telemetry
)

logger = logging.getLogger(__name__)


class TelemetryEngine:
    """
    Unified telemetry engine for tracking translation operations.

    Wraps TranslationTelemetry to provide consistent interface across
    execution modes (manual CLI, autonomous workers).

    Args:
        agent_name: Name of the translation agent (default: "hugo-translator")
        enabled: Whether telemetry is enabled (default: True)
        config: Optional telemetry configuration

    Example:
        telemetry = TelemetryEngine(agent_name="hugo-translator")

        # Track translation session
        with telemetry.track_translation_session(
            job_type="translate_file",
            file_path=Path("content/example.md"),
            target_langs=["es", "fr"]
        ) as ctx:
            # Perform translation...
            ctx.set_metrics(tokens_input=150, tokens_output=200)
    """

    def __init__(
        self,
        agent_name: str = "hugo-translator",
        enabled: bool = True,
        config: Optional[Any] = None
    ):
        """Initialize telemetry engine."""
        self.agent_name = agent_name
        self.enabled = enabled

        # Initialize underlying telemetry client
        if config:
            self.telemetry = configure_telemetry(
                agent_name=agent_name,
                enabled=enabled,
                config=config
            )
        else:
            self.telemetry = get_telemetry(agent_name=agent_name)

        logger.info(
            f"TelemetryEngine initialized: agent={agent_name}, enabled={enabled}"
        )

    def track_translation_session(
        self,
        job_type: str,
        trigger_type: str = "cli",
        file_path: Optional[Path] = None,
        target_langs: Optional[List[str]] = None,
        errors: Optional[List[str]] = None,
        **additional_context
    ):
        """
        Context manager for tracking a translation session.

        Args:
            job_type: Type of translation job (e.g., "translate_file", "translate_directory")
            trigger_type: How translation was triggered ("cli", "web", "scheduled")
            file_path: Source file being translated
            target_langs: List of target languages
            errors: Optional list of error messages
            **additional_context: Additional context (site_id, etc.)

        Returns:
            Context manager for the translation run

        Example:
            with engine.track_translation_session(
                job_type="translate_file",
                file_path=Path("example.md"),
                target_langs=["es", "fr"],
                site_id="products.aspose.com"
            ) as ctx:
                # ... translate ...
                ctx.set_metrics(tokens_input=150, tokens_output=200)
        """
        return self.telemetry.track_translation_session(
            job_type=job_type,
            trigger_type=trigger_type,
            file_path=file_path,
            target_langs=target_langs,
            errors=errors,
            **additional_context
        )

    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Emit a telemetry event.

        Convenience method for simple event tracking without context manager.

        Args:
            event_type: Type of event (e.g., "model_loaded", "cache_hit")
            data: Event data dictionary

        Example:
            engine.emit("model_loaded", {
                "model_id": "m2m100_418m",
                "device": "cuda",
                "load_time_ms": 1500
            })
        """
        if not self.enabled:
            return

        logger.debug(f"Telemetry event: {event_type}, data={data}")

        # Note: TranslationTelemetry doesn't have a direct emit() method,
        # so we log the event. In future, this could write to a separate
        # event stream or buffer.
        # For now, we just log it for observability.

    def is_enabled(self) -> bool:
        """
        Check if telemetry is enabled.

        Returns:
            True if telemetry is active, False otherwise
        """
        return self.enabled and self.telemetry.enabled

    def get_telemetry_client(self) -> Optional[TranslationTelemetry]:
        """
        Get underlying telemetry client for advanced usage.

        Returns:
            TranslationTelemetry instance or None if disabled

        Note:
            Most code should use TelemetryEngine methods instead of
            accessing the client directly.
        """
        return self.telemetry if self.enabled else None

    def shutdown(self) -> None:
        """
        Clean up telemetry resources.

        Flushes any pending events and closes connections.
        """
        if self.enabled and self.telemetry and self.telemetry.client:
            logger.info(f"Shutting down TelemetryEngine: {self.agent_name}")
            # Telemetry client cleanup (if needed)
            # Currently TranslationTelemetry doesn't have explicit cleanup
            logger.info(f"TelemetryEngine shut down: {self.agent_name}")
