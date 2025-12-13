"""
Telemetry Integration for hugo-translator (TEL-04).

Bridges hugo-translator translation operations with the TEL-03 telemetry platform
to track translation metrics, token usage, cache performance, and file operations.
"""
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

import re

from src.observability.git_context import get_git_context


def extract_business_context(
    file_path: Optional[Path] = None,
    site_id: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    Extract business context dimensions from file path and site_id (TEL-05-A).

    Args:
        file_path: Source file path (e.g., /content/slides/net/getting-started.md)
        site_id: Site identifier (e.g., products.aspose.com)

    Returns:
        Dict with keys: product_family, subdomain, platform, product.
        Values are None if not extractable.

    Examples:
        >>> extract_business_context(Path("/slides/net/guide.md"), "products.aspose.com")
        {'product_family': 'slides', 'subdomain': 'products', 'platform': '.NET', 'product': 'slides'}
    """
    result: Dict[str, Optional[str]] = {
        "product_family": None,
        "subdomain": None,
        "platform": None,
        "product": None,
    }

    # Extract subdomain from site_id (first part before first dot)
    if site_id:
        parts = site_id.split(".")
        if parts:
            result["subdomain"] = parts[0]

    # Extract product_family and platform from file path
    if file_path:
        path_str = str(file_path).replace("\\", "/").lower()

        # Known product families (Aspose products)
        product_families = [
            "slides", "words", "cells", "pdf", "email", "imaging",
            "barcode", "diagram", "tasks", "ocr", "cad", "3d",
            "html", "zip", "tex", "page", "psd", "font", "note",
            "gis", "drawing", "svg", "pub", "finance", "omr",
        ]

        # Find product family in path
        for pf in product_families:
            # Match /slides/, /words/, etc. in path
            if f"/{pf}/" in path_str or path_str.startswith(f"{pf}/"):
                result["product_family"] = pf
                result["product"] = pf  # product = product_family for now
                break

        # Platform detection patterns
        platform_patterns = [
            (r"/net/|/\.net/|dotnet", ".NET"),
            (r"/java/", "Java"),
            (r"/python/|/python-net/", "Python"),
            (r"/cpp/|/c\+\+/", "C++"),
            (r"/nodejs/|/node/", "Node.js"),
            (r"/php/", "PHP"),
            (r"/android/", "Android"),
            (r"/sharepoint/", "SharePoint"),
            (r"/reporting/|/jasperreports/", "JasperReports"),
        ]

        for pattern, platform in platform_patterns:
            if re.search(pattern, path_str):
                result["platform"] = platform
                break

    return result


# Add local-telemetry src to path if available
TELEMETRY_SRC_PATH = Path(r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src")
if TELEMETRY_SRC_PATH.exists() and str(TELEMETRY_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(TELEMETRY_SRC_PATH))

try:
    from telemetry.client import TelemetryClient
    from telemetry.config import TelemetryConfig
    TELEMETRY_AVAILABLE = True
except ImportError:
    TELEMETRY_AVAILABLE = False
    # Create dummy classes for graceful degradation
    class TelemetryClient:
        pass

    class TelemetryConfig:
        @classmethod
        def from_env(cls):
            return cls()


class TranslationTelemetry:
    """
    Telemetry integration wrapper for hugo-translator.

    Provides context managers and helpers to track translation sessions
    with token counts, file operations, and cache performance metrics.
    """

    def __init__(
        self,
        agent_name: str = "hugo-translator",
        enabled: bool = True,
        config: Optional[Any] = None,
    ):
        """
        Initialize telemetry integration.

        Args:
            agent_name: Name of the translation agent
            enabled: Whether telemetry is enabled (default: True)
            config: Optional TelemetryConfig instance (defaults to from_env())
        """
        self.enabled = enabled and TELEMETRY_AVAILABLE
        self.agent_name = agent_name

        # Initialize client if telemetry is available
        if self.enabled:
            try:
                if config is None:
                    config = TelemetryConfig.from_env()
                self.client = TelemetryClient(config)
            except Exception as e:
                print(f"[WARN] Failed to initialize telemetry: {e}")
                self.enabled = False
                self.client = None
        else:
            self.client = None

    def track_translation_session(
        self,
        job_type: str,
        trigger_type: str = "cli",
        file_path: Optional[Path] = None,
        target_langs: Optional[list] = None,
        **additional_context
    ):
        """
        Context manager for tracking a translation session.

        Usage:
            with telemetry.track_translation_session(
                job_type="translate_file",
                file_path=Path("content/example.md"),
                target_langs=["es", "fr"]
            ) as ctx:
                # Perform translation...
                ctx.set_metrics(tokens_input=150, tokens_output=200)

        Args:
            job_type: Type of translation job (e.g., "translate_file", "translate_directory")
            trigger_type: How translation was triggered ("cli", "web", "scheduled")
            file_path: Source file being translated
            target_langs: List of target languages
            **additional_context: Additional context to track

        Returns:
            Context manager for the translation run
        """
        if not self.enabled or not self.client:
            # Return dummy context manager if telemetry is disabled
            return DummyRunContext()

        # Build input summary from context
        summary_parts = []
        if file_path:
            summary_parts.append(f"file={file_path}")
        if target_langs:
            summary_parts.append(f"langs={','.join(target_langs)}")
        for key, value in additional_context.items():
            summary_parts.append(f"{key}={value}")

        input_summary = "; ".join(summary_parts) if summary_parts else None

        # Capture git/environment context (TEL-05-C)
        git_ctx = get_git_context()

        # Extract business context (TEL-05-A)
        site_id = additional_context.get("site_id")
        biz_ctx = extract_business_context(file_path, site_id)

        # Get agent_owner from env var or use default (TEL-06-B)
        agent_owner = os.getenv("AGENT_OWNER", "Babar Raza")

        # Create run context using TEL-03 API with git + business context
        return self.client.track_run(
            agent_name=self.agent_name,
            job_type=job_type,
            trigger_type=trigger_type,
            input_summary=input_summary,
            agent_owner=agent_owner,  # TEL-06-B: Always set agent_owner
            # Git context (TEL-05-C)
            git_repo=git_ctx.get("git_repo"),
            git_branch=git_ctx.get("git_branch"),
            git_run_tag=git_ctx.get("git_run_tag"),
            host=git_ctx.get("host"),
            # Business context (TEL-05-A)
            product=biz_ctx.get("product"),
            product_family=biz_ctx.get("product_family"),
            subdomain=biz_ctx.get("subdomain"),
            platform=biz_ctx.get("platform"),
        )

    def track_translation_stats(self, run_context, stats):
        """
        Set translation statistics as metrics on a run context.

        Args:
            run_context: Active run context from track_translation_session()
            stats: TranslationStats object with metrics to track
        """
        if not self.enabled or not run_context:
            return

        # Build metrics dict from stats
        metrics = {
            # Token metrics
            "tokens_input": stats.tokens_input,
            "tokens_output": stats.tokens_output,
            "tokens_cached": stats.tokens_cached,
            "tokens_total": stats.tokens_total,
            # Segment metrics
            "total_segments": stats.total_segments,
            "tm_hits": stats.tm_hits,
            "l1_hits": stats.l1_hits,
            "l2_hits": stats.l2_hits,
            "l3_hits": stats.l3_hits,
            "translated_segments": stats.translated_segments,
            "skipped_segments": stats.skipped_segments,  # TEL-05-A: additional stat
            # File operation metrics
            "md_files_added": stats.md_files_added,
            "md_files_updated": stats.md_files_updated,
            "bytes_written_md": stats.bytes_written_md,
            "tm_entries_stored": stats.tm_entries_stored,
            "files_translated": stats.files_translated,  # TEL-05-A: additional stat
            "files_generated": stats.files_generated,  # TEL-05-A: additional stat
            # Calculated metrics
            "tm_hit_rate": stats.tm_hit_rate,
            "token_cache_rate": stats.token_cache_rate,
            "duration_seconds": stats.duration_seconds,
        }

        # Set all metrics at once using TEL-03 API
        run_context.set_metrics(**metrics)

    def is_available(self) -> bool:
        """Check if telemetry is available and enabled."""
        return self.enabled and self.client is not None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        return False

    def track_validation_decision(
        self,
        run_context,
        decision: str,
        retry_count: int,
        error_count: int,
        warning_count: int,
        validator_results: Dict[str, bool],
        feedback_provided: bool,
    ):
        """
        Track validation decision metrics and emit decision event.

        Args:
            run_context: Active run context from track_translation_session()
            decision: ACCEPT/RETRY/REJECT
            retry_count: Number of retries attempted
            error_count: Number of validation errors
            warning_count: Number of validation warnings
            validator_results: Dict mapping validator names to pass/fail status
            feedback_provided: Whether retry feedback was provided
        """
        if not self.enabled or not run_context:
            return

        # Emit validation_decision_made event
        run_context.log_event(
            "validation_decision_made",
            payload={
                "decision": decision,
                "retry_count": retry_count,
                "error_count": error_count,
                "warning_count": warning_count,
                "validator_results": validator_results,
                "feedback_provided": feedback_provided,
            },
        )

        # Update aggregated metrics (if run_context supports counter increment)
        if hasattr(run_context, "increment_counter"):
            run_context.increment_counter("total_validations", 1.0)

            if decision == "ACCEPT":
                run_context.increment_counter("accept_count", 1.0)
            elif decision == "RETRY":
                run_context.increment_counter("retry_count", 1.0)
            elif decision == "REJECT":
                run_context.increment_counter("reject_count", 1.0)

    def track_validation_error(
        self,
        run_context,
        validator_name: str,
        error_type: str,
        severity: str,
        message: str,
    ):
        """
        Track individual validation error.

        Args:
            run_context: Active run context from track_translation_session()
            validator_name: Name of the validator that failed
            error_type: Type/category of the error
            severity: ERROR/WARNING/INFO
            message: Error message
        """
        if not self.enabled or not run_context:
            return

        # Emit validation_error event
        run_context.log_event(
            "validation_error",
            payload={
                "validator_name": validator_name,
                "error_type": error_type,
                "severity": severity,
                "message": message,
            },
        )


class DummyRunContext:
    """
    Dummy run context for when telemetry is disabled.

    Provides the same interface as RunContext but does nothing.
    """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def set_metrics(self, **kwargs):
        """No-op set_metrics."""
        pass

    def log_event(self, event_type: str, payload: Optional[Dict[str, Any]] = None):
        """No-op log_event."""
        pass

    def increment_counter(self, counter_name: str, amount: float = 1.0):
        """No-op increment_counter."""
        pass


# Global telemetry instance (can be configured once and reused)
_global_telemetry: Optional[TranslationTelemetry] = None


def get_telemetry(
    agent_name: str = "hugo-translator",
) -> TranslationTelemetry:
    """
    Get or create global telemetry instance.

    Args:
        agent_name: Name of the translation agent

    Returns:
        TranslationTelemetry instance
    """
    global _global_telemetry

    if _global_telemetry is None:
        # Check if telemetry is disabled via environment variable
        enabled = os.getenv("HUGO_TRANSLATOR_TELEMETRY_ENABLED", "true").lower() in (
            "true", "1", "yes", "on"
        )
        _global_telemetry = TranslationTelemetry(
            agent_name=agent_name,
            enabled=enabled,
        )

    return _global_telemetry


def configure_telemetry(
    agent_name: str = "hugo-translator",
    enabled: bool = True,
    config: Optional[Any] = None,
) -> TranslationTelemetry:
    """
    Configure global telemetry instance.

    Args:
        agent_name: Name of the translation agent
        enabled: Whether telemetry is enabled
        config: Optional TelemetryConfig instance

    Returns:
        Configured TranslationTelemetry instance
    """
    global _global_telemetry
    _global_telemetry = TranslationTelemetry(
        agent_name=agent_name,
        enabled=enabled,
        config=config,
    )
    return _global_telemetry
