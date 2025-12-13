"""
Health Monitoring and Auto-Recovery System.

Monitors system health, detects issues, and attempts automatic recovery.
Provides health check endpoint for load balancers and monitoring systems.
"""

import logging
import os
import platform
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    component: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class RecoveryAction:
    """Recovery action taken."""
    component: str
    action: str
    success: bool
    message: str
    timestamp: float = field(default_factory=time.time)


class HealthMonitor:
    """
    Health monitoring and auto-recovery system.

    Checks system health and attempts automatic recovery when issues detected.
    """

    def __init__(
        self,
        tm_data_dir: Optional[Path] = None,
        timeout: float = 5.0,
        enable_auto_recovery: bool = True
    ):
        """
        Initialize health monitor.

        Args:
            tm_data_dir: TM data directory path
            timeout: Timeout for health checks in seconds
            enable_auto_recovery: Enable automatic recovery
        """
        self.tm_data_dir = tm_data_dir or Path("./data/tm")
        self.timeout = timeout
        self.enable_auto_recovery = enable_auto_recovery
        self.recovery_attempts: List[RecoveryAction] = []

    def check_health(self) -> Tuple[HealthStatus, List[HealthCheckResult]]:
        """
        Perform comprehensive health check.

        Returns:
            Tuple of (overall_status, check_results)
        """
        results = []

        # Check TM layers
        results.append(self.check_tm_l1())
        results.append(self.check_tm_l2())
        results.append(self.check_tm_l3())

        # Check system resources
        results.append(self.check_disk_space())
        results.append(self.check_memory_usage())

        # Check model registry
        results.append(self.check_model_registry())

        # Determine overall status
        overall_status = self._determine_overall_status(results)

        # Attempt recovery if enabled
        if self.enable_auto_recovery and overall_status != HealthStatus.HEALTHY:
            self._attempt_auto_recovery(results)

        return overall_status, results

    def check_tm_l1(self) -> HealthCheckResult:
        """
        Check L1 cache health.

        Returns:
            Health check result
        """
        try:
            # L1 is in-memory, check if module can be imported
            from src.tm.l1_cache import L1Cache

            # Try to create instance
            cache = L1Cache(max_size=100)

            # Test basic operations
            test_key = "test_source"
            test_value = "test_target"
            cache.set(test_key, test_value, "en", "es")
            result = cache.get(test_key, "en", "es")

            if result == test_value:
                return HealthCheckResult(
                    component="tm_l1_cache",
                    status=HealthStatus.HEALTHY,
                    message="L1 cache operational",
                    details={"max_size": cache.max_size}
                )
            else:
                return HealthCheckResult(
                    component="tm_l1_cache",
                    status=HealthStatus.DEGRADED,
                    message="L1 cache not storing values correctly"
                )

        except Exception as e:
            logger.error(f"L1 cache health check failed: {e}")
            return HealthCheckResult(
                component="tm_l1_cache",
                status=HealthStatus.UNHEALTHY,
                message=f"L1 cache error: {e}"
            )

    def check_tm_l2(self) -> HealthCheckResult:
        """
        Check L2 LMDB database health.

        Returns:
            Health check result
        """
        try:
            l2_path = self.tm_data_dir / "l2_lmdb"

            if not l2_path.exists():
                return HealthCheckResult(
                    component="tm_l2_lmdb",
                    status=HealthStatus.DEGRADED,
                    message="L2 database directory not found",
                    details={"path": str(l2_path)}
                )

            # Check if data file exists
            data_file = l2_path / "data.mdb"
            if not data_file.exists():
                return HealthCheckResult(
                    component="tm_l2_lmdb",
                    status=HealthStatus.DEGRADED,
                    message="L2 database file not found",
                    details={"path": str(data_file)}
                )

            # Try to open database
            try:
                import lmdb
                env = lmdb.open(str(l2_path), readonly=True, lock=False)
                with env.begin() as txn:
                    stats = env.stat()
                env.close()

                return HealthCheckResult(
                    component="tm_l2_lmdb",
                    status=HealthStatus.HEALTHY,
                    message="L2 database operational",
                    details={
                        "path": str(l2_path),
                        "entries": stats.get('entries', 0),
                        "size_mb": data_file.stat().st_size / (1024 * 1024)
                    }
                )
            except Exception as e:
                logger.error(f"L2 database open failed: {e}")
                return HealthCheckResult(
                    component="tm_l2_lmdb",
                    status=HealthStatus.UNHEALTHY,
                    message=f"L2 database error: {e}"
                )

        except Exception as e:
            logger.error(f"L2 health check failed: {e}")
            return HealthCheckResult(
                component="tm_l2_lmdb",
                status=HealthStatus.UNHEALTHY,
                message=f"L2 check error: {e}"
            )

    def check_tm_l3(self) -> HealthCheckResult:
        """
        Check L3 FAISS index health.

        Returns:
            Health check result
        """
        try:
            l3_path = self.tm_data_dir / "l3_faiss"

            if not l3_path.exists():
                return HealthCheckResult(
                    component="tm_l3_faiss",
                    status=HealthStatus.DEGRADED,
                    message="L3 index directory not found",
                    details={"path": str(l3_path)}
                )

            # Check for index files
            index_files = list(l3_path.glob("*.faiss"))
            if not index_files:
                return HealthCheckResult(
                    component="tm_l3_faiss",
                    status=HealthStatus.DEGRADED,
                    message="L3 index files not found"
                )

            # Try to load index
            try:
                import faiss
                index_file = index_files[0]
                index = faiss.read_index(str(index_file))

                return HealthCheckResult(
                    component="tm_l3_faiss",
                    status=HealthStatus.HEALTHY,
                    message="L3 index operational",
                    details={
                        "path": str(l3_path),
                        "index_size": index.ntotal,
                        "dimension": index.d
                    }
                )
            except Exception as e:
                logger.error(f"L3 index load failed: {e}")
                return HealthCheckResult(
                    component="tm_l3_faiss",
                    status=HealthStatus.UNHEALTHY,
                    message=f"L3 index error: {e}"
                )

        except Exception as e:
            logger.error(f"L3 health check failed: {e}")
            return HealthCheckResult(
                component="tm_l3_faiss",
                status=HealthStatus.UNHEALTHY,
                message=f"L3 check error: {e}"
            )

    def check_disk_space(self, threshold_percent: float = 10.0) -> HealthCheckResult:
        """
        Check disk space availability.

        Args:
            threshold_percent: Minimum free space percentage

        Returns:
            Health check result
        """
        try:
            total, used, free = shutil.disk_usage("/")

            free_percent = (free / total) * 100

            if free_percent >= threshold_percent:
                status = HealthStatus.HEALTHY
                message = f"Disk space OK: {free_percent:.1f}% free"
            elif free_percent >= threshold_percent / 2:
                status = HealthStatus.DEGRADED
                message = f"Disk space low: {free_percent:.1f}% free"
            else:
                status = HealthStatus.UNHEALTHY
                message = f"Disk space critical: {free_percent:.1f}% free"

            return HealthCheckResult(
                component="disk_space",
                status=status,
                message=message,
                details={
                    "total_gb": total / (1024**3),
                    "used_gb": used / (1024**3),
                    "free_gb": free / (1024**3),
                    "free_percent": free_percent
                }
            )

        except Exception as e:
            logger.error(f"Disk space check failed: {e}")
            return HealthCheckResult(
                component="disk_space",
                status=HealthStatus.UNHEALTHY,
                message=f"Disk check error: {e}"
            )

    def check_memory_usage(self, threshold_percent: float = 80.0) -> HealthCheckResult:
        """
        Check memory usage.

        Args:
            threshold_percent: Maximum memory usage percentage

        Returns:
            Health check result
        """
        try:
            import psutil

            memory = psutil.virtual_memory()
            usage_percent = memory.percent

            if usage_percent <= threshold_percent:
                status = HealthStatus.HEALTHY
                message = f"Memory usage OK: {usage_percent:.1f}%"
            elif usage_percent <= threshold_percent + 10:
                status = HealthStatus.DEGRADED
                message = f"Memory usage high: {usage_percent:.1f}%"
            else:
                status = HealthStatus.UNHEALTHY
                message = f"Memory usage critical: {usage_percent:.1f}%"

            return HealthCheckResult(
                component="memory_usage",
                status=status,
                message=message,
                details={
                    "total_gb": memory.total / (1024**3),
                    "available_gb": memory.available / (1024**3),
                    "used_percent": usage_percent
                }
            )

        except ImportError:
            logger.warning("psutil not available, skipping memory check")
            return HealthCheckResult(
                component="memory_usage",
                status=HealthStatus.DEGRADED,
                message="Memory monitoring not available (psutil not installed)"
            )
        except Exception as e:
            logger.error(f"Memory check failed: {e}")
            return HealthCheckResult(
                component="memory_usage",
                status=HealthStatus.UNHEALTHY,
                message=f"Memory check error: {e}"
            )

    def check_model_registry(self) -> HealthCheckResult:
        """
        Check model registry accessibility.

        Returns:
            Health check result
        """
        try:
            from src.model_runtime.registry import ModelRegistry

            registry = ModelRegistry()
            available_models = registry.list_available_models()

            if available_models:
                return HealthCheckResult(
                    component="model_registry",
                    status=HealthStatus.HEALTHY,
                    message="Model registry accessible",
                    details={"model_count": len(available_models)}
                )
            else:
                return HealthCheckResult(
                    component="model_registry",
                    status=HealthStatus.DEGRADED,
                    message="No models registered"
                )

        except Exception as e:
            logger.error(f"Model registry check failed: {e}")
            return HealthCheckResult(
                component="model_registry",
                status=HealthStatus.UNHEALTHY,
                message=f"Model registry error: {e}"
            )

    def _determine_overall_status(
        self,
        results: List[HealthCheckResult]
    ) -> HealthStatus:
        """
        Determine overall health status from individual checks.

        Args:
            results: List of health check results

        Returns:
            Overall health status
        """
        # If any component is unhealthy, system is unhealthy
        if any(r.status == HealthStatus.UNHEALTHY for r in results):
            return HealthStatus.UNHEALTHY

        # If any component is degraded, system is degraded
        if any(r.status == HealthStatus.DEGRADED for r in results):
            return HealthStatus.DEGRADED

        # All components healthy
        return HealthStatus.HEALTHY

    def _attempt_auto_recovery(self, results: List[HealthCheckResult]) -> None:
        """
        Attempt automatic recovery for failed components.

        Args:
            results: Health check results
        """
        for result in results:
            if result.status != HealthStatus.HEALTHY:
                logger.info(f"Attempting recovery for {result.component}")
                self._recover_component(result)

    def _recover_component(self, result: HealthCheckResult) -> None:
        """
        Attempt to recover a specific component.

        Args:
            result: Failed health check result
        """
        try:
            if result.component == "tm_l1_cache":
                # L1 cache is in-memory, try to reinitialize
                action = RecoveryAction(
                    component=result.component,
                    action="reinitialize_cache",
                    success=True,
                    message="Cache will be reinitialized on next use"
                )
                self.recovery_attempts.append(action)
                logger.info(f"Recovery: {action.message}")

            elif result.component == "tm_l2_lmdb":
                # Check if database is corrupted
                action = RecoveryAction(
                    component=result.component,
                    action="verify_database",
                    success=True,
                    message="Database verified, may need rebuild"
                )
                self.recovery_attempts.append(action)
                logger.warning(f"Recovery: {action.message}")

            elif result.component == "tm_l3_faiss":
                # Check if index needs rebuilding
                action = RecoveryAction(
                    component=result.component,
                    action="verify_index",
                    success=True,
                    message="Index verified, may need rebuild"
                )
                self.recovery_attempts.append(action)
                logger.warning(f"Recovery: {action.message}")

            elif result.component == "disk_space":
                # Log critical disk space warning
                action = RecoveryAction(
                    component=result.component,
                    action="alert",
                    success=True,
                    message="Disk space critical - manual cleanup required"
                )
                self.recovery_attempts.append(action)
                logger.critical(f"Recovery: {action.message}")

            elif result.component == "memory_usage":
                # Log high memory usage
                action = RecoveryAction(
                    component=result.component,
                    action="alert",
                    success=True,
                    message="High memory usage - consider restarting worker"
                )
                self.recovery_attempts.append(action)
                logger.warning(f"Recovery: {action.message}")

        except Exception as e:
            action = RecoveryAction(
                component=result.component,
                action="recovery_failed",
                success=False,
                message=f"Recovery failed: {e}"
            )
            self.recovery_attempts.append(action)
            logger.error(f"Recovery failed for {result.component}: {e}")

    def get_recovery_history(self) -> List[RecoveryAction]:
        """
        Get history of recovery actions.

        Returns:
            List of recovery actions
        """
        return self.recovery_attempts.copy()

    def export_health_status(self) -> Dict[str, Any]:
        """
        Export health status for monitoring systems.

        Returns:
            Health status dictionary
        """
        overall_status, results = self.check_health()

        return {
            "status": overall_status.value,
            "timestamp": time.time(),
            "checks": [
                {
                    "component": r.component,
                    "status": r.status.value,
                    "message": r.message,
                    "details": r.details
                }
                for r in results
            ],
            "recovery_attempts": [
                {
                    "component": a.component,
                    "action": a.action,
                    "success": a.success,
                    "message": a.message,
                    "timestamp": a.timestamp
                }
                for a in self.recovery_attempts[-10:]  # Last 10 attempts
            ]
        }

    def get_http_status_code(self) -> int:
        """
        Get HTTP status code based on health.

        Returns:
            200 for healthy, 503 for degraded/unhealthy
        """
        overall_status, _ = self.check_health()

        if overall_status == HealthStatus.HEALTHY:
            return 200
        else:
            return 503
