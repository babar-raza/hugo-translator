"""Cache size monitoring for Translation Memory.

This module provides monitoring capabilities for the LMDB-based L2 cache,
including size tracking, usage percentage calculation, and threshold warnings.

Implementation follows TM-04 from the TM cache integrity plan.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .l2_persistent import L2PersistentTM

logger = logging.getLogger(__name__)


@dataclass
class CacheSizeReport:
    """Cache size and usage statistics."""
    current_bytes: int
    max_bytes: int
    usage_percent: float
    entry_count: int
    warning: bool
    recommendation: str | None = None

    @property
    def current_mb(self) -> float:
        """Current size in megabytes."""
        return self.current_bytes / (1024 * 1024)

    @property
    def current_gb(self) -> float:
        """Current size in gigabytes."""
        return self.current_bytes / (1024 * 1024 * 1024)

    @property
    def max_mb(self) -> float:
        """Maximum size in megabytes."""
        return self.max_bytes / (1024 * 1024)

    @property
    def max_gb(self) -> float:
        """Maximum size in gigabytes."""
        return self.max_bytes / (1024 * 1024 * 1024)

    def __str__(self) -> str:
        return (
            f"CacheSizeReport({self.current_mb:.1f}MB / {self.max_mb:.0f}MB, "
            f"{self.usage_percent:.1f}% used, {self.entry_count} entries)"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "current_bytes": self.current_bytes,
            "current_mb": round(self.current_mb, 2),
            "current_gb": round(self.current_gb, 4),
            "max_bytes": self.max_bytes,
            "max_mb": round(self.max_mb, 0),
            "max_gb": round(self.max_gb, 2),
            "usage_percent": round(self.usage_percent, 2),
            "entry_count": self.entry_count,
            "warning": self.warning,
            "recommendation": self.recommendation
        }


class CacheMonitor:
    """
    Monitor LMDB cache size and health.

    Provides real-time monitoring of cache usage with configurable
    warning and critical thresholds. Designed to be lightweight
    and non-blocking for use during translation runs.
    """

    # Default thresholds
    DEFAULT_WARN_THRESHOLD = 80  # 80%
    DEFAULT_CRITICAL_THRESHOLD = 95  # 95%

    def __init__(
        self,
        l2: 'L2PersistentTM',
        warn_threshold_percent: int = DEFAULT_WARN_THRESHOLD,
        critical_threshold_percent: int = DEFAULT_CRITICAL_THRESHOLD
    ):
        """
        Initialize cache monitor.

        Args:
            l2: L2PersistentTM instance to monitor
            warn_threshold_percent: Warning threshold (default: 80%)
            critical_threshold_percent: Critical threshold (default: 95%)
        """
        self.l2 = l2
        self.warn_threshold = warn_threshold_percent
        self.critical_threshold = critical_threshold_percent

        # Validate thresholds
        if not (0 < warn_threshold_percent < 100):
            raise ValueError(f"warn_threshold must be between 0 and 100, got {warn_threshold_percent}")
        if not (0 < critical_threshold_percent <= 100):
            raise ValueError(f"critical_threshold must be between 0 and 100, got {critical_threshold_percent}")
        if warn_threshold_percent >= critical_threshold_percent:
            raise ValueError(
                f"warn_threshold ({warn_threshold_percent}) must be less than "
                f"critical_threshold ({critical_threshold_percent})"
            )

    def check_size(self) -> CacheSizeReport:
        """
        Get current cache size and check thresholds.

        Returns:
            CacheSizeReport with size statistics and warnings
        """
        # Get LMDB stats
        stat = self.l2.env.stat()
        info = self.l2.env.info()

        # Calculate sizes
        # LMDB stores data in pages; calculate actual used space
        page_size = stat['psize']
        last_page = info['last_pgno']
        current_bytes = page_size * last_page
        max_bytes = info['map_size']

        # Calculate usage percentage
        usage_percent = (current_bytes / max_bytes) * 100 if max_bytes > 0 else 0
        entry_count = stat['entries']

        # Determine status
        warning = usage_percent >= self.warn_threshold
        recommendation = None

        if usage_percent >= self.critical_threshold:
            recommendation = (
                "CRITICAL: Cache nearly full. "
                "Actions: (1) Increase max_size_mb parameter, (2) Archive old translations, "
                "(3) Clear entries for deprecated sites using tm.clear()"
            )
        elif usage_percent >= self.warn_threshold:
            recommendation = (
                "WARNING: Cache usage high. "
                "Consider archiving old translations or increasing max_size_mb parameter."
            )

        report = CacheSizeReport(
            current_bytes=current_bytes,
            max_bytes=max_bytes,
            usage_percent=usage_percent,
            entry_count=entry_count,
            warning=warning,
            recommendation=recommendation
        )

        # Log appropriately based on status
        if usage_percent >= self.critical_threshold:
            logger.error(str(report))
            if recommendation:
                logger.error(recommendation)
        elif warning:
            logger.warning(str(report))
            if recommendation:
                logger.warning(recommendation)
        else:
            logger.info(str(report))

        return report

    def is_healthy(self) -> bool:
        """
        Quick health check - is cache below warning threshold?

        Returns:
            True if cache is healthy (below warning threshold)
        """
        report = self.check_size()
        return not report.warning

    def get_usage_percent(self) -> float:
        """
        Get current usage as a percentage.

        Returns:
            Usage percentage (0-100)
        """
        stat = self.l2.env.stat()
        info = self.l2.env.info()

        page_size = stat['psize']
        last_page = info['last_pgno']
        current_bytes = page_size * last_page
        max_bytes = info['map_size']

        return (current_bytes / max_bytes) * 100 if max_bytes > 0 else 0


def create_monitor_from_path(
    db_path: Path,
    warn_threshold_percent: int = CacheMonitor.DEFAULT_WARN_THRESHOLD,
    critical_threshold_percent: int = CacheMonitor.DEFAULT_CRITICAL_THRESHOLD
) -> CacheMonitor:
    """
    Create a CacheMonitor from a database path.

    Convenience function for creating a monitor without having
    to instantiate L2PersistentTM manually.

    Args:
        db_path: Path to LMDB database directory
        warn_threshold_percent: Warning threshold (default: 80%)
        critical_threshold_percent: Critical threshold (default: 95%)

    Returns:
        CacheMonitor instance
    """
    from .l2_persistent import L2PersistentTM

    l2 = L2PersistentTM(db_path)
    return CacheMonitor(
        l2=l2,
        warn_threshold_percent=warn_threshold_percent,
        critical_threshold_percent=critical_threshold_percent
    )
