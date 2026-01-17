"""
Telemetry Integration for hugo-translator (TEL-04).

Bridges hugo-translator translation operations with the TEL-03 telemetry platform
to track translation metrics, token usage, cache performance, and file operations.
"""
import logging
import os
import sys
import time
import weakref
from pathlib import Path
from typing import Optional, Dict, Any, List
from threading import Lock

import re

logger = logging.getLogger(__name__)

from src.observability.git_context import get_git_context


def extract_website(site_id: Optional[str]) -> str:
    """
    Extract root domain from site_id for the 'website' telemetry field.

    Args:
        site_id: Full site identifier (e.g., "products.aspose.com")

    Returns:
        Root domain (e.g., "aspose.com") or empty string if not extractable.

    Examples:
        >>> extract_website("products.aspose.com")
        "aspose.com"
        >>> extract_website("blog.aspose.net")
        "aspose.net"
        >>> extract_website("docs.groupdocs.cloud")
        "groupdocs.cloud"
    """
    if not site_id:
        return ""

    parts = site_id.split(".")
    if len(parts) >= 2:
        # Return last two parts (domain.tld)
        return ".".join(parts[-2:])
    return site_id


def map_website_section(subdomain: Optional[str]) -> str:
    """
    Map subdomain to website_section for telemetry field.

    Args:
        subdomain: First part of site_id (e.g., "products", "blog", "kb")

    Returns:
        Normalized section name ("Docs", "Blog", "KB", etc.) or "NA" if unknown.

    Examples:
        >>> map_website_section("products")
        "Docs"
        >>> map_website_section("blog")
        "Blog"
        >>> map_website_section("kb")
        "KB"
    """
    if not subdomain:
        return "NA"

    # Mapping table: subdomain -> section name
    section_map = {
        "products": "Docs",
        "docs": "Docs",
        "reference": "Reference",
        "blog": "Blog",
        "kb": "KB",
        "forum": "Forum",
        "purchase": "Purchase",
        "releases": "Releases",
        "api": "API",
    }

    # TFR-01: Handle full site_id (e.g., "blog.aspose.net") by extracting first part
    subdomain_part = subdomain.split(".")[0] if "." in subdomain else subdomain
    return section_map.get(subdomain_part.lower(), "NA")


# TFR-02: Product family mapping to capitalized Aspose product names
PRODUCT_FAMILY_MAP = {
    "slides": "Aspose.Slides",
    "words": "Aspose.Words",
    "cells": "Aspose.Cells",
    "pdf": "Aspose.PDF",
    "email": "Aspose.Email",
    "imaging": "Aspose.Imaging",
    "barcode": "Aspose.BarCode",
    "diagram": "Aspose.Diagram",
    "tasks": "Aspose.Tasks",
    "ocr": "Aspose.OCR",
    "note": "Aspose.Note",
    "cad": "Aspose.CAD",
    "3d": "Aspose.3D",
    "html": "Aspose.HTML",
    "gis": "Aspose.GIS",
    "zip": "Aspose.ZIP",
    "font": "Aspose.Font",
    "psd": "Aspose.PSD",
    "tex": "Aspose.TeX",
    "page": "Aspose.Page",
    "drawing": "Aspose.Drawing",
    "svg": "Aspose.SVG",
    "finance": "Aspose.Finance",
    "pub": "Aspose.PUB",
    "omr": "Aspose.OMR",
}


def get_product_family_name(product_key: Optional[str]) -> Optional[str]:
    """
    Map product key to capitalized product family name (TFR-02).

    Args:
        product_key: Lowercase product key (e.g., "slides", "words")

    Returns:
        Capitalized product name (e.g., "Aspose.Slides") or fallback format.
    """
    if not product_key:
        return None
    return PRODUCT_FAMILY_MAP.get(product_key.lower(), f"Aspose.{product_key.title()}")


def get_item_name(job_type: str) -> str:
    """
    Get item_name based on job_type for telemetry field.

    Args:
        job_type: Type of translation job

    Returns:
        "Segments" for file translation, "Files" for directory translation.

    Examples:
        >>> get_item_name("translate_file")
        "Segments"
        >>> get_item_name("translate_directory")
        "Files"
    """
    if job_type == "translate_file":
        return "Segments"
    elif job_type == "translate_directory":
        return "Files"
    return "Items"


def build_output_summary(
    job_type: str,
    outputs: Optional[Dict] = None,
    successful_files: Optional[int] = None,
    total_files: Optional[int] = None,
    files_generated: Optional[int] = None,
    errors: Optional[List] = None,
    skipped_langs: Optional[List] = None,
    skip_reasons: Optional[Dict] = None,
) -> str:
    """
    Build standardized output_summary string for RunRecord (SR-03, TEL-05-B, RES-05).

    Args:
        job_type: Type of job ("translate_file" or "translate_directory")
        outputs: For single file: dict of target_lang -> output_path
        successful_files: For directory: number of successful files
        total_files: For directory: total files processed
        files_generated: For directory: total output files created
        errors: List of errors encountered
        skipped_langs: For single file: list of languages skipped (output exists)
        skip_reasons: For single file: dict of {lang: reason} for skipped languages

    Returns:
        Formatted output summary string

    Examples:
        >>> build_output_summary("translate_file", outputs={"es": "a.md", "fr": "b.md"}, errors=[])
        "2 translations, 0 errors"
        >>> build_output_summary("translate_file", outputs={"es": "a.md", "fr": "b.md"}, skipped_langs=["de"], errors=[])
        "2 translations, 1 skipped (existing outputs), 0 errors"
        >>> build_output_summary("translate_directory", successful_files=8, total_files=10, files_generated=16, errors=[])
        "8/10 files translated, 16 outputs"
    """
    error_count = len(errors) if errors else 0

    if job_type == "translate_file":
        translation_count = len(outputs) if outputs else 0
        skip_count = len(skipped_langs) if skipped_langs else 0

        # RES-05: Include skip information when available
        if skip_count > 0:
            return f"{translation_count} translations, {skip_count} skipped (existing outputs), {error_count} errors"
        else:
            return f"{translation_count} translations, {error_count} errors"
    elif job_type == "translate_directory":
        successful = successful_files if successful_files is not None else 0
        total = total_files if total_files is not None else 0
        generated = files_generated if files_generated is not None else 0
        return f"{successful}/{total} files translated, {generated} outputs"
    else:
        return f"Job completed, {error_count} errors"


def build_error_summary(errors: List[str], max_errors: int = 5) -> str:
    """
    Build standardized error_summary string for RunRecord (SR-03, TEL-05-B).

    Truncates to max_errors to prevent excessively long summaries.

    Args:
        errors: List of error messages
        max_errors: Maximum number of errors to include (default: 5)

    Returns:
        Semicolon-separated error summary string, or empty string if no errors

    Examples:
        >>> build_error_summary(["Error 1", "Error 2"])
        "Error 1; Error 2"
        >>> build_error_summary([])
        ""
    """
    if not errors:
        return ""
    truncated = errors[:max_errors]
    return "; ".join(truncated)


def calculate_items_metrics(
    job_type: str,
    stats: Optional[Any] = None,
    total_files: Optional[int] = None,
    successful_files: Optional[int] = None,
    failed_files: Optional[int] = None,
    skip_count: int = 0,
) -> Dict[str, int]:
    """
    Calculate items_discovered, items_succeeded, items_failed for RunRecord (SR-03, TEL-05-B).

    Semantics:
    - For single file translation:
        - items_discovered = total_segments (all segments that need translation)
        - items_succeeded = translated_segments + tm_hits (segments successfully translated)
        - items_failed = skipped_segments (segments that failed/were skipped)
        - NOTE: Languages skipped due to existing outputs are excluded from items_succeeded

    - For directory translation:
        - items_discovered = total_files (all files found)
        - items_succeeded = successful_files (files that translated successfully)
        - items_failed = failed_files (files that failed)

    Args:
        job_type: Type of job ("translate_file" or "translate_directory")
        stats: TranslationStats object (for single file)
        total_files: Total files discovered (for directory)
        successful_files: Successful files (for directory)
        failed_files: Failed files (for directory)
        skip_count: Number of languages skipped (for single file, default: 0)

    Returns:
        Dict with keys: items_discovered, items_succeeded, items_failed, items_skipped

    Examples:
        >>> calculate_items_metrics("translate_file", stats=mock_stats, skip_count=2)
        {"items_discovered": 10, "items_succeeded": 9, "items_failed": 1, "items_skipped": 2}
        >>> calculate_items_metrics("translate_directory", total_files=10, successful_files=8, failed_files=2)
        {"items_discovered": 10, "items_succeeded": 8, "items_failed": 2, "items_skipped": 0}
    """
    if job_type == "translate_file":
        # Single file: items = segments
        if stats:
            # RES-05: Items succeeded should exclude skipped languages
            # We report on segment-level work actually performed
            return {
                "items_discovered": stats.total_segments,
                "items_succeeded": stats.translated_segments + stats.tm_hits,
                "items_failed": stats.skipped_segments,
                "items_skipped": skip_count,
            }
        else:
            return {
                "items_discovered": 0,
                "items_succeeded": 0,
                "items_failed": 0,
                "items_skipped": 0,
            }
    elif job_type == "translate_directory":
        # Directory: items = files
        return {
            "items_discovered": total_files if total_files is not None else 0,
            "items_succeeded": successful_files if successful_files is not None else 0,
            "items_failed": failed_files if failed_files is not None else 0,
            "items_skipped": 0,  # Directory-level skipping not tracked separately
        }
    else:
        return {
            "items_discovered": 0,
            "items_succeeded": 0,
            "items_failed": 0,
            "items_skipped": 0,
        }


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

    Field Semantics (TEL-07-C):
        - product: Set to product_family (e.g., "slides", "words") rather than "hugo-translator".
          Rationale: agent_name already identifies the tool; product enables per-product analytics.
        - platform: Set to documentation target platform (e.g., ".NET", "Java") not runtime ("python").
          Rationale: Runtime is always Python; doc platform enables per-platform translation analytics.
          Falls back to DEFAULT_PLATFORM env var (default: ".NET") if not detected from path.
        - product_family: Aspose product family extracted from path (slides, words, cells, etc.).
        - subdomain: Site subdomain from site_id (products, docs, reference, etc.).

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

    # TFR-01: Use full site_id as subdomain (not just first part)
    # This allows proper identification like "blog.aspose.net" vs just "blog"
    if site_id:
        result["subdomain"] = site_id

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
                result["product"] = pf  # Keep lowercase for product field
                # TFR-02: Use capitalized product family name
                result["product_family"] = get_product_family_name(pf)
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

    # Apply default platform if not detected from path
    if result["platform"] is None:
        result["platform"] = os.getenv("DEFAULT_PLATFORM", ".NET")

    return result


# Add local-telemetry src to path if available
# Configurable via TELEMETRY_SRC_PATH environment variable.
# Set TELEMETRY_SRC_PATH to override default location for different deployments.
TELEMETRY_SRC_PATH = Path(
    os.getenv(
        'TELEMETRY_SRC_PATH',
        r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
    )
)

if not TELEMETRY_SRC_PATH.exists():
    logger.warning(f"Telemetry path not found: {TELEMETRY_SRC_PATH}. Telemetry will be unavailable.")
elif str(TELEMETRY_SRC_PATH) not in sys.path:
    logger.info(f"Loading telemetry from: {TELEMETRY_SRC_PATH}")
    sys.path.insert(0, str(TELEMETRY_SRC_PATH))
else:
    logger.debug(f"Telemetry path already in sys.path: {TELEMETRY_SRC_PATH}")

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


def _safe_duration_ms(stats: Optional[Any], context: str = "") -> tuple:
    """
    Safely calculate duration_ms from TranslationStats.

    TI-01: Add observability for duration_ms fallback scenarios.
    Emits metrics and structured logs when fallback to 0 is used.

    Args:
        stats: TranslationStats object (or None)
        context: Context string for logging (e.g., "translate_file", "translate_directory")

    Returns:
        Tuple of (duration_ms as int, used_fallback as bool)
        - duration_ms: Always an integer (never None)
        - used_fallback: True if fallback to 0 was used, False for legitimate values
    """
    from src.translation_engine.models import TranslationStats

    # Handle None stats
    if stats is None:
        logger.warning(
            "Duration fallback: stats is None",
            extra={"context": context, "reason": "none_stats"}
        )
        # Emit metric for observability
        try:
            from src.observability.metrics import get_metrics
            metrics = get_metrics()
            metrics.increment('telemetry_duration_fallback', labels={'reason': 'none_stats'})
        except (ImportError, Exception):
            pass  # Graceful degradation if metrics unavailable
        return (0, True)

    # Handle None or invalid duration_seconds
    try:
        if stats.duration_seconds is None:
            logger.warning(
                "Duration fallback: duration_seconds is None",
                extra={"context": context, "reason": "none_duration"}
            )
            try:
                from src.observability.metrics import get_metrics
                metrics = get_metrics()
                metrics.increment('telemetry_duration_fallback', labels={'reason': 'none_duration'})
            except (ImportError, Exception):
                pass
            return (0, True)
        elif stats.duration_seconds == 0.0:
            # Legitimate 0 - not a fallback
            return (0, False)
        else:
            # Valid duration, calculate ms
            return (int(stats.duration_seconds * 1000), False)
    except (TypeError, ValueError, AttributeError) as e:
        logger.warning(
            f"Duration fallback: invalid type - {e}",
            extra={"context": context, "reason": "invalid_type"}
        )
        try:
            from src.observability.metrics import get_metrics
            metrics = get_metrics()
            metrics.increment('telemetry_duration_fallback', labels={'reason': 'invalid_type'})
        except (ImportError, Exception):
            pass
        return (0, True)


class TranslationTelemetry:
    """
    Telemetry integration wrapper for hugo-translator.

    Provides context managers and helpers to track translation sessions
    with token counts, file operations, and cache performance metrics.

    Thread Safety:
        This class is thread-safe for concurrent session management.
        Multiple threads can safely call start_translation_session() and
        complete_translation_session() when using --parallel-languages flag.
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
        self._sessions_lock = Lock()

        # Retry configuration for associate_commit API
        self.associate_commit_max_retries = 3
        self.associate_commit_retry_delay = 1.0  # Initial delay in seconds

        # Initialize client if telemetry is available
        if self.enabled:
            try:
                # Detect subprocess context where stdout/stderr might be closed
                # In such contexts, telemetry initialization may fail with I/O errors
                import sys
                if sys.stdout is None or (hasattr(sys.stdout, 'closed') and sys.stdout.closed):
                    # Subprocess context detected - disable telemetry silently
                    self.enabled = False
                    self.client = None
                    self._supported_fields = set()
                    return

                if config is None:
                    config = TelemetryConfig.from_env()
                self.client = TelemetryClient(config)
                # TC-VALID-01: Detect supported fields based on client version
                self._supported_fields = self._detect_supported_fields()
            except Exception as e:
                # Gracefully disable telemetry on initialization failure
                # Wrap logging to handle closed file descriptors in subprocess contexts
                try:
                    import logging
                    logging.getLogger(__name__).debug(f"Telemetry initialization failed (non-critical): {e}")
                except (OSError, ValueError):
                    # If logging also fails due to closed streams, silently ignore
                    pass
                self.enabled = False
                self.client = None
                self._supported_fields = set()
        else:
            self.client = None
            self._supported_fields = set()

    @staticmethod
    def _version_gte(version: str, threshold: str) -> bool:
        """
        Compare semantic versions (greater than or equal).

        TC-VALID-01: Helper for version comparison to determine field support.

        Args:
            version: Version string (e.g., "2.2.0")
            threshold: Threshold version (e.g., "2.2.0")

        Returns:
            True if version >= threshold, False otherwise

        Examples:
            >>> TranslationTelemetry._version_gte("2.2.0", "2.2.0")
            True
            >>> TranslationTelemetry._version_gte("2.3.1", "2.2.0")
            True
            >>> TranslationTelemetry._version_gte("2.1.0", "2.2.0")
            False
        """
        try:
            # Try using packaging library if available
            from packaging import version as pkg_version
            return pkg_version.parse(version) >= pkg_version.parse(threshold)
        except ImportError:
            # Fallback: simple numeric comparison
            try:
                v_parts = [int(x) for x in version.split('.')[:3]]
                t_parts = [int(x) for x in threshold.split('.')[:3]]
                # Pad with zeros if needed
                while len(v_parts) < 3:
                    v_parts.append(0)
                while len(t_parts) < 3:
                    t_parts.append(0)
                return tuple(v_parts) >= tuple(t_parts)
            except (ValueError, AttributeError):
                # If parsing fails, assume old version (conservative)
                logger.warning(f"Failed to parse version '{version}', assuming old version")
                return False

    def _detect_supported_fields(self) -> set:
        """
        Detect which telemetry fields the client supports based on version.

        TC-VALID-01: Runtime field detection to prevent 422 API errors.

        Version compatibility:
        - v2.1.x: Base fields (agent_name, job_type, etc.)
        - v2.2.0+: Adds git_commit_hash, git_commit_source, git_commit_author, git_commit_timestamp

        Returns:
            Set of supported field names

        Side effects:
            Logs warning if client version < 2.2.0
        """
        if not self.client:
            return set()

        # Try to get version from client instance
        client_version = getattr(self.client, '__version__', None)

        # Fallback: Try package-level version
        if not client_version:
            try:
                import telemetry
                client_version = getattr(telemetry, '__version__', None)
            except (ImportError, AttributeError):
                pass

        # Conservative fallback if version not detected
        if not client_version:
            logger.warning(
                "Could not detect telemetry client version. "
                "Assuming v2.1.0 for field compatibility."
            )
            client_version = "2.1.0"

        # Log warning for old versions
        if not self._version_gte(client_version, "2.2.0"):
            logger.warning(
                f"Telemetry client version {client_version} < 2.2.0 detected. "
                "Git commit association fields will be excluded to prevent API errors."
            )

        # Base fields supported in all versions
        supported = {
            'agent_name', 'job_type', 'trigger_type', 'input_summary',
            'agent_owner', 'environment', 'source_ref', 'target_ref',
            'git_repo', 'git_branch', 'git_run_tag', 'host',
            'product', 'product_family', 'subdomain', 'platform',
            'website', 'website_section', 'item_name', 'error_summary',
            'duration_ms', 'items_discovered', 'items_succeeded', 'items_failed',
            'metrics_json', 'output_summary',
        }

        # Fields added in v2.2.0
        if self._version_gte(client_version, "2.2.0"):
            supported.update({
                'git_commit_hash',
                'git_commit_source',
                'git_commit_author',
                'git_commit_timestamp',
            })

        logger.debug(f"Detected telemetry client v{client_version}, {len(supported)} fields supported")
        return supported

    def start_translation_session(
        self,
        job_type: str,
        trigger_type: str = "cli",
        file_path: Optional[Path] = None,
        target_langs: Optional[list] = None,
        errors: Optional[List[str]] = None,
        **additional_context
    ):
        """
        Start a translation session with explicit POST to telemetry API.

        This is the explicit POST method for Phase 2 refactoring. Use this when you need
        direct access to the run context for later updates (e.g., git commit association).

        Args:
            job_type: Type of translation job (e.g., "translate_file", "translate_directory")
            trigger_type: How translation was triggered ("cli", "web", "scheduled")
            file_path: Source file being translated
            target_langs: List of target languages
            errors: Optional list of error messages for error_summary
            **additional_context: Additional context to track (including site_id)

        Returns:
            Tuple of (run_context, context_manager) where:
            - run_context: RunContext for setting metrics
            - context_manager: Internal CM for cleanup (call __exit__ later)

        Memory Safety:
            Session entries in _active_sessions are automatically cleaned up when
            the returned run_context is garbage collected. This ensures no memory
            leaks occur if complete_translation_session() is not called due to
            exceptions or unexpected program termination. Cleanup is thread-safe
            and uses the same _sessions_lock as session creation/completion.
        """
        if not self.enabled or not self.client:
            # Return dummy context if telemetry is disabled
            return (DummyRunContext(), None)

        # Build all the same context as track_translation_session
        # (reuse the logic by calling track_translation_session which returns CM)
        context_manager = self._build_telemetry_context(
            job_type, trigger_type, file_path, target_langs, errors, **additional_context
        )

        # Enter the context manager to start the session (POST)
        run_context = context_manager.__enter__()

        # GAP-04: Create a proxy wrapper that users hold
        # This allows weakref cleanup when users discard their reference,
        # even if the underlying context_manager still exists in _active_sessions
        class SessionProxy:
            """Proxy wrapper for run_context that enables weakref-based cleanup."""
            def __init__(self, wrapped):
                self._wrapped = wrapped

            def __getattr__(self, name):
                return getattr(self._wrapped, name)

            def set_metrics(self, **kwargs):
                return self._wrapped.set_metrics(**kwargs)

            def log_event(self, event_type, payload=None):
                return self._wrapped.log_event(event_type, payload)

            def increment_counter(self, counter_name, amount=1.0):
                return self._wrapped.increment_counter(counter_name, amount)

            def get_partial_metrics(self):
                return self._wrapped.get_partial_metrics()

        proxy = SessionProxy(run_context)

        # Store the CM so we can call __exit__ later in complete_translation_session
        # Use proxy object as key (not run_context) since that's what users hold
        session_id = id(proxy)

        # GAP-04: Register weakref cleanup callback for leaked sessions
        # If proxy is garbage collected before complete_translation_session(),
        # automatically remove the _active_sessions entry to prevent memory leaks
        def cleanup_leaked_session(ref):
            with self._sessions_lock:
                cleaned = self._active_sessions.pop(session_id, None)
                if cleaned:
                    logger.debug(f"Auto-cleaned leaked telemetry session {session_id}")

        # Create weakref with callback - must store ref to prevent immediate GC
        proxy_ref = weakref.ref(proxy, cleanup_leaked_session)

        with self._sessions_lock:
            if not hasattr(self, '_active_sessions'):
                self._active_sessions = {}
            # Store context_manager, underlying run_context, and weakref
            self._active_sessions[session_id] = (context_manager, run_context, proxy_ref)

        return (proxy, context_manager)

    def _build_telemetry_context(
        self,
        job_type: str,
        trigger_type: str = "cli",
        file_path: Optional[Path] = None,
        target_langs: Optional[list] = None,
        errors: Optional[List[str]] = None,
        **additional_context
    ):
        """
        Build telemetry context manager with all fields populated.

        Internal helper method to avoid code duplication between
        track_translation_session and start_translation_session.
        """
        # Build input summary from context
        summary_parts = []
        if file_path:
            summary_parts.append(f"file={file_path}")
        if target_langs:
            summary_parts.append(f"langs={','.join(target_langs)}")
        for key, value in additional_context.items():
            summary_parts.append(f"{key}={value}")

        input_summary = "; ".join(summary_parts) if summary_parts else None

        # Capture git/environment context (TEL-05-C, TFR-03)
        # TFR-03: Pass input file path to get git context from input repo
        git_ctx = get_git_context(input_path=file_path)

        # Extract business context (TEL-05-A)
        site_id = additional_context.get("site_id")
        biz_ctx = extract_business_context(file_path, site_id)

        # Get agent_owner from env var or use default (TEL-06-B)
        agent_owner = os.getenv("AGENT_OWNER", "Babar Raza")

        # Get environment from env var or use default (dev/staging/prod)
        environment = os.getenv("HUGO_TRANSLATOR_ENV", "dev")

        # Build source_ref from file_path or directory (absolute path for traceability)
        source_ref = None
        if file_path:
            source_ref = str(Path(file_path).resolve())
        elif additional_context.get("directory"):
            source_ref = str(Path(additional_context["directory"]).resolve())

        # TSC-01: Extract website and website_section
        website = extract_website(site_id)
        website_section = map_website_section(biz_ctx.get("subdomain"))

        # TSC-02: Get item_name based on job_type
        item_name = get_item_name(job_type)

        # TSC-03: Build error_summary if errors provided
        error_summary = build_error_summary(errors or [])

        # TC-VALID-01: Build kwargs dict for field filtering
        track_run_kwargs = {
            'agent_name': self.agent_name,
            'job_type': job_type,
            'trigger_type': trigger_type,
            'input_summary': input_summary,
            'agent_owner': agent_owner,  # TEL-06-B: Always set agent_owner
            'environment': environment,  # Environment detection (dev/staging/prod)
            'source_ref': source_ref,  # Source file/directory absolute path
            # Git context (TEL-05-C)
            'git_repo': git_ctx.get("git_repo"),
            'git_branch': git_ctx.get("git_branch"),
            'git_run_tag': git_ctx.get("git_run_tag"),
            'host': git_ctx.get("host"),
            # Business context (TEL-05-A)
            'product': biz_ctx.get("product"),
            'product_family': biz_ctx.get("product_family"),
            'subdomain': biz_ctx.get("subdomain"),
            'platform': biz_ctx.get("platform"),
            # TSC-01: Website fields (Agentic Metrics schema compliance)
            'website': website,
            'website_section': website_section,
            # TSC-02: Item tracking field
            'item_name': item_name,
            # TSC-03: Error summary (step_name not in RunRecord schema)
            'error_summary': error_summary,
        }

        # TC-VALID-01: Filter fields based on client version compatibility
        if hasattr(self, '_supported_fields') and self._supported_fields:
            track_run_kwargs = {
                k: v for k, v in track_run_kwargs.items()
                if k in self._supported_fields
            }

        # Create run context using TEL-03 API with filtered fields
        return self.client.track_run(**track_run_kwargs)

    def track_translation_session(
        self,
        job_type: str,
        trigger_type: str = "cli",
        file_path: Optional[Path] = None,
        target_langs: Optional[list] = None,
        errors: Optional[List[str]] = None,
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
            errors: Optional list of error messages for error_summary
            **additional_context: Additional context to track (including site_id)

        Returns:
            Context manager for the translation run

        Telemetry Fields (TEL-07-C, TSC-01, TSC-03):
            This method populates the following telemetry fields with intentional semantics:
            - agent_name: Always "hugo-translator" (identifies the tool)
            - agent_owner: From AGENT_OWNER env var or default "Babar Raza"
            - product: Product family from path (e.g., "slides") - NOT "hugo-translator"
            - platform: Doc target platform (e.g., ".NET") - NOT runtime "python"
            - product_family: Same as product (Aspose product family)
            - subdomain: Site subdomain from site_id (e.g., "products", "docs")
            - git_repo, git_branch, host: Captured from git/environment context
            - website: Root domain extracted from site_id (e.g., "aspose.com")
            - website_section: Section name from subdomain (e.g., "Docs", "Blog")
            - item_name: What is being counted ("Segments" or "Files")
            - error_summary: Truncated error messages if any

            NOTE: Fields step_name, source_ref, target_ref, environment are documented
            in agentic-metrics-logging-integration-guide but NOT supported by
            local-telemetry RunRecord schema. Use metrics_json for custom fields.
        """
        if not self.enabled or not self.client:
            # Return dummy context manager if telemetry is disabled
            return DummyRunContext()

        # Use helper method to build context (DRY principle)
        return self._build_telemetry_context(
            job_type, trigger_type, file_path, target_langs, errors, **additional_context
        )

    def complete_translation_session(
        self,
        run_context,
        status: str = "success",
        error_summary: Optional[str] = None
    ):
        """
        Complete a translation session with explicit PATCH to telemetry API.

        This is the explicit PATCH method for Phase 2 refactoring. Call this after
        translation work is done to finalize the telemetry entry.

        Args:
            run_context: RunContext from start_translation_session()
            status: Final status ("success", "failure", "partial")
            error_summary: Optional error summary for failures

        Returns:
            None
        """
        if not self.enabled or not run_context or isinstance(run_context, DummyRunContext):
            return

        # Retrieve the stored context manager
        with self._sessions_lock:
            if not hasattr(self, '_active_sessions'):
                logger.warning("No active session found for run_context")
                return

            session_data = self._active_sessions.get(id(run_context))
            if not session_data:
                logger.warning("Context manager not found for run_context")
                return

            # GAP-04: Handle tuple format (context_manager, run_context, weakref)
            if isinstance(session_data, tuple):
                context_manager = session_data[0]
            else:
                context_manager = session_data

        # Set final status if needed (outside lock - network call)
        if error_summary:
            run_context.set_metrics(error_summary=error_summary)

        # Exit the context manager to finalize the session (PATCH)
        try:
            context_manager.__exit__(None, None, None)
        finally:
            # Clean up stored reference
            with self._sessions_lock:
                del self._active_sessions[id(run_context)]

    def track_translation_stats(
        self,
        run_context,
        stats,
        job_type: str = "translate_file",
        output_paths: Optional[Dict[str, Path]] = None
    ):
        """
        Set translation statistics as metrics on a run context.

        Args:
            run_context: Active run context from track_translation_session()
            stats: TranslationStats object with metrics to track
            job_type: Type of job for calculating items_* fields
            output_paths: Optional dict of language -> output path for target_ref
        """
        if not self.enabled or not run_context:
            return

        # TI-01: Use centralized helper with observability
        # If stats is None, helper will create default stats and log fallback
        duration_ms, used_fallback = _safe_duration_ms(stats, context="track_translation_stats")

        # If stats was None, create empty stats for metrics dict
        if stats is None:
            from src.translation_engine.models import TranslationStats
            stats = TranslationStats()

        # TSC-02: Calculate items_* using existing helper
        items_metrics = calculate_items_metrics(
            job_type=job_type,
            stats=stats,
            total_files=getattr(stats, 'files_translated', 0) + getattr(stats, 'skipped_segments', 0),
            successful_files=getattr(stats, 'files_translated', 0),
            failed_files=0,  # Derive from errors if available
        )

        # Build custom metrics dict from stats
        # NOTE: items_skipped is NOT in RunRecord schema, so we include it in metrics_json
        items_skipped = stats.skipped_segments if job_type == "translate_file" else 0

        # NEW: Add validation metrics (if validation was performed)
        validation_metrics = {}
        if stats.validation_decision:
            validation_metrics = {
                "validation_passed": stats.validation_passed,
                "validation_failed": stats.validation_failed,
                "validation_retried": stats.validation_retried,
                "validation_decision": stats.validation_decision,
                "validation_errors": stats.validation_errors,
                "validation_warnings": stats.validation_warnings,
                "validation_info": stats.validation_info,
                "validation_duration_ms": stats.validation_duration_ms,
                "retry_duration_ms": stats.retry_duration_ms,
            }

        # NEW: Add AST translation metrics (if AST enabled)
        ast_metrics = {}
        if stats.ast_translation_enabled:
            ast_metrics = {
                "ast_translation_enabled": True,
                "ast_units_extracted": stats.ast_units_extracted,
                "ast_units_translatable": stats.ast_units_translatable,
                "ast_units_protected": stats.ast_units_protected,
                "ast_batch_calls": stats.ast_batch_calls,
                "ast_individual_fallbacks": stats.ast_individual_fallbacks,
            }

        custom_metrics = {
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
            "items_skipped": items_skipped,  # Include here since not in RunRecord
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
            # NEW: Merge validation and AST metrics
            **validation_metrics,
            **ast_metrics,
        }

        # Build target_ref from output_paths if provided (JSON array of absolute paths)
        target_ref = None
        if output_paths:
            import json
            # Convert to list of absolute paths
            abs_paths = [str(Path(p).resolve()) for p in output_paths.values() if p]
            # Convert to JSON string
            target_ref_json = json.dumps(abs_paths)
            # Truncate to 1KB for large directories (per plan spec)
            if len(target_ref_json) > 1024:
                target_ref = target_ref_json[:1020] + "...]"
            else:
                target_ref = target_ref_json

        # Set metrics using TEL-03 API
        # IMPORTANT: Send metrics_json as dict (not JSON string) to match API schema
        # API expects: {"type": "object"}, not string
        # TSC-02: Include items_* fields for schema compliance
        # NOTE: items_skipped is NOT in RunRecord schema, so it's in metrics_json
        set_metrics_kwargs = {
            "duration_ms": duration_ms,
            "items_discovered": items_metrics["items_discovered"],
            "items_succeeded": items_metrics["items_succeeded"],
            "items_failed": items_metrics["items_failed"],
            "metrics_json": custom_metrics,  # Contains items_skipped and other custom metrics
        }

        # Add target_ref if available
        if target_ref:
            set_metrics_kwargs["target_ref"] = target_ref

        run_context.set_metrics(**set_metrics_kwargs)

    def associate_commit(
        self,
        run_context,
        commit_hash: str,
        commit_source: str = "llm",
        commit_author: Optional[str] = None,
        commit_timestamp: Optional[str] = None
    ) -> bool:
        """
        Associate git commit with telemetry run via API.

        Calls the /api/v1/runs/{event_id}/associate-commit endpoint to link
        a git commit with this translation run for traceability.

        Retry Behavior:
            - Automatically retries up to 3 times for transient failures (ConnectionError, TimeoutError)
            - Uses exponential backoff: 1s, 2s, 4s delays between retries
            - Does NOT retry on client errors (4xx responses) or other exceptions
            - Logs each retry attempt at WARNING level
            - Returns False if all retries fail (non-fatal)

        Args:
            run_context: RunContext from start_translation_session() or track_translation_session()
            commit_hash: Git commit SHA (40-char or 7-char short hash)
            commit_source: "llm" (automated), "manual", or "ci"
            commit_author: Git author string (e.g., "Name <email>")
            commit_timestamp: ISO timestamp of commit

        Returns:
            True if successful, False if failed (non-fatal)
        """
        if not self.enabled or not run_context or isinstance(run_context, DummyRunContext):
            return False

        if not self.client:
            logger.warning("Telemetry client not available for commit association")
            return False

        # Try to get event_id from run_context (do this once before retry loop)
        event_id = getattr(run_context, 'event_id', None)
        if not event_id:
            # Fallback: Try to get from internal storage
            if hasattr(run_context, '_event_id'):
                event_id = run_context._event_id
            else:
                logger.warning("Cannot associate commit: event_id not available from run_context")
                return False

        # Check if the client has an associate_commit method
        if not hasattr(self.client, 'associate_commit'):
            # Fallback: Set git commit fields via set_metrics (PATCH)
            logger.debug("Client doesn't support associate_commit, using set_metrics fallback")
            run_context.set_metrics(
                git_commit_hash=commit_hash,
                git_commit_source=commit_source,
                git_commit_author=commit_author,
                git_commit_timestamp=commit_timestamp,
            )
            return True

        # Retry loop with exponential backoff
        for attempt in range(self.associate_commit_max_retries):
            try:
                # Call the associate_commit API endpoint
                self.client.associate_commit(
                    event_id=event_id,
                    commit_hash=commit_hash,
                    commit_source=commit_source,
                    commit_author=commit_author,
                    commit_timestamp=commit_timestamp,
                )

                logger.debug(f"Associated commit {commit_hash[:7]} with telemetry run {event_id}")
                return True

            except (ConnectionError, TimeoutError) as e:
                # Transient error - retry with exponential backoff
                if attempt < self.associate_commit_max_retries - 1:
                    delay = self.associate_commit_retry_delay * (2 ** attempt)
                    logger.warning(
                        f"Failed to associate commit (attempt {attempt + 1}/{self.associate_commit_max_retries}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    # Final attempt failed
                    logger.warning(f"Failed to associate commit after {self.associate_commit_max_retries} attempts: {e}")
                    return False

            except Exception as e:
                # Non-transient error (e.g., 4xx client error) - don't retry
                logger.warning(f"Failed to associate commit with telemetry (not retrying): {e}")
                return False

        # Should not reach here, but return False as fallback
        return False

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

    def get_partial_metrics(self) -> Dict[str, Any]:
        """
        Get partial metrics captured so far (GS-04, GS-05).

        Returns empty dict for DummyRunContext. Real RunContext from local-telemetry
        should return partial items_*, metrics_json, etc.

        Returns:
            Dict with partial metrics (empty for dummy context)
        """
        return {}


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


def emit_event(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """
    Emit a telemetry event using the global telemetry instance.

    This is a convenience function for emitting events without needing to
    manage a RunContext. Events are logged via structlog for observability.

    Note: For translation jobs with run contexts, prefer using
    run_context.log_event() instead for better correlation.

    Args:
        event_type: Type of event (e.g., "subprocess_executed")
        payload: Event payload data (optional)

    Example:
        >>> emit_event("subprocess_executed", {
        ...     "command": "git status",
        ...     "exit_code": 0,
        ...     "duration": 0.5
        ... })
    """
    try:
        # Use structlog for event logging (matches existing pattern)
        import structlog
        logger = structlog.get_logger("hugo_translator.telemetry")
        logger.info(event_type, **(payload or {}))
    except Exception as e:
        # Don't let telemetry failures break operations
        import logging
        logging.getLogger(__name__).debug(f"Failed to emit event {event_type}: {e}")
