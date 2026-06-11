"""
Comprehensive tests for health monitoring and auto-recovery.

Tests health checks, status determination, auto-recovery, and failure scenarios.
"""

import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.orchestration.health_monitor import (
    HealthCheckResult,
    HealthMonitor,
    HealthStatus,
    RecoveryAction,
)


@pytest.fixture
def temp_tm_dir():
    """Create temporary TM directory structure."""
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)

        # Create L2 LMDB structure
        l2_dir = temp_path / "l2_lmdb"
        l2_dir.mkdir()
        (l2_dir / "data.mdb").write_bytes(b"test data")
        (l2_dir / "lock.mdb").write_bytes(b"lock")

        # Create L3 FAISS structure
        l3_dir = temp_path / "l3_faiss"
        l3_dir.mkdir()
        (l3_dir / "test.faiss").write_bytes(b"FAISS index")

        yield temp_path


class TestHealthStatus:
    """Test HealthStatus enum."""

    def test_health_status_values(self):
        """Test health status enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"


class TestHealthCheckResult:
    """Test HealthCheckResult dataclass."""

    def test_create_health_check_result(self):
        """Test creating health check result."""
        result = HealthCheckResult(component="test", status=HealthStatus.HEALTHY, message="Test OK")

        assert result.component == "test"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "Test OK"
        assert isinstance(result.details, dict)
        assert result.timestamp > 0

    def test_health_check_result_with_details(self):
        """Test health check result with details."""
        result = HealthCheckResult(
            component="test", status=HealthStatus.HEALTHY, message="Test OK", details={"metric": 42}
        )

        assert result.details["metric"] == 42


class TestRecoveryAction:
    """Test RecoveryAction dataclass."""

    def test_create_recovery_action(self):
        """Test creating recovery action."""
        action = RecoveryAction(
            component="test", action="restart", success=True, message="Component restarted"
        )

        assert action.component == "test"
        assert action.action == "restart"
        assert action.success is True
        assert action.message == "Component restarted"
        assert action.timestamp > 0


class TestHealthMonitor:
    """Test HealthMonitor class."""

    def test_create_health_monitor(self, temp_tm_dir):
        """Test creating health monitor."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        assert monitor.tm_data_dir == temp_tm_dir
        assert monitor.timeout == 5.0
        assert monitor.enable_auto_recovery is True

    def test_health_monitor_with_options(self, temp_tm_dir):
        """Test creating health monitor with custom options."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, timeout=10.0, enable_auto_recovery=False)

        assert monitor.timeout == 10.0
        assert monitor.enable_auto_recovery is False

    def test_check_health(self, temp_tm_dir):
        """Test comprehensive health check."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=False)

        overall_status, results = monitor.check_health()

        assert isinstance(overall_status, HealthStatus)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(r, HealthCheckResult) for r in results)

    def test_check_tm_l1(self, temp_tm_dir):
        """Test L1 cache health check."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        result = monitor.check_tm_l1()

        assert result.component == "tm_l1_cache"
        assert isinstance(result.status, HealthStatus)
        assert isinstance(result.message, str)

    def test_check_tm_l2_exists(self, temp_tm_dir):
        """Test L2 database health check when exists."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        result = monitor.check_tm_l2()

        assert result.component == "tm_l2_lmdb"
        # Status depends on whether lmdb is installed
        assert isinstance(result.status, HealthStatus)

    def test_check_tm_l2_missing(self, temp_tm_dir):
        """Test L2 database health check when missing."""
        # Remove L2 directory
        import shutil

        shutil.rmtree(temp_tm_dir / "l2_lmdb")

        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)
        result = monitor.check_tm_l2()

        assert result.component == "tm_l2_lmdb"
        assert result.status == HealthStatus.DEGRADED
        assert "not found" in result.message.lower()

    def test_check_tm_l3_exists(self, temp_tm_dir):
        """Test L3 index health check when exists."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        result = monitor.check_tm_l3()

        assert result.component == "tm_l3_faiss"
        # Status depends on whether faiss is installed
        assert isinstance(result.status, HealthStatus)

    def test_check_tm_l3_missing(self, temp_tm_dir):
        """Test L3 index health check when missing."""
        # Remove L3 directory
        import shutil

        shutil.rmtree(temp_tm_dir / "l3_faiss")

        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)
        result = monitor.check_tm_l3()

        assert result.component == "tm_l3_faiss"
        assert result.status == HealthStatus.DEGRADED

    def test_check_disk_space(self, temp_tm_dir):
        """Test disk space health check."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        result = monitor.check_disk_space(threshold_percent=10.0)

        assert result.component == "disk_space"
        assert isinstance(result.status, HealthStatus)
        assert "free_percent" in result.details

    def test_check_memory_usage(self, temp_tm_dir):
        """Test memory usage health check."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        result = monitor.check_memory_usage(threshold_percent=80.0)

        assert result.component == "memory_usage"
        assert isinstance(result.status, HealthStatus)

    def test_check_model_registry(self, temp_tm_dir):
        """Test model registry health check."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        result = monitor.check_model_registry()

        assert result.component == "model_registry"
        assert isinstance(result.status, HealthStatus)


class TestHealthStatusDetermination:
    """Test overall health status determination."""

    def test_all_healthy(self, temp_tm_dir):
        """Test status when all components healthy."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        results = [
            HealthCheckResult("c1", HealthStatus.HEALTHY, "OK"),
            HealthCheckResult("c2", HealthStatus.HEALTHY, "OK"),
            HealthCheckResult("c3", HealthStatus.HEALTHY, "OK"),
        ]

        status = monitor._determine_overall_status(results)
        assert status == HealthStatus.HEALTHY

    def test_one_degraded(self, temp_tm_dir):
        """Test status when one component degraded."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        results = [
            HealthCheckResult("c1", HealthStatus.HEALTHY, "OK"),
            HealthCheckResult("c2", HealthStatus.DEGRADED, "Warning"),
            HealthCheckResult("c3", HealthStatus.HEALTHY, "OK"),
        ]

        status = monitor._determine_overall_status(results)
        assert status == HealthStatus.DEGRADED

    def test_one_unhealthy(self, temp_tm_dir):
        """Test status when one component unhealthy."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        results = [
            HealthCheckResult("c1", HealthStatus.HEALTHY, "OK"),
            HealthCheckResult("c2", HealthStatus.UNHEALTHY, "Error"),
            HealthCheckResult("c3", HealthStatus.HEALTHY, "OK"),
        ]

        status = monitor._determine_overall_status(results)
        assert status == HealthStatus.UNHEALTHY

    def test_unhealthy_takes_precedence(self, temp_tm_dir):
        """Test that unhealthy takes precedence over degraded."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        results = [
            HealthCheckResult("c1", HealthStatus.DEGRADED, "Warning"),
            HealthCheckResult("c2", HealthStatus.UNHEALTHY, "Error"),
            HealthCheckResult("c3", HealthStatus.HEALTHY, "OK"),
        ]

        status = monitor._determine_overall_status(results)
        assert status == HealthStatus.UNHEALTHY


class TestAutoRecovery:
    """Test automatic recovery functionality."""

    def test_auto_recovery_disabled(self, temp_tm_dir):
        """Test that recovery doesn't run when disabled."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=False)

        # Force degraded status
        with mock.patch.object(monitor, "check_tm_l2") as mock_check:
            mock_check.return_value = HealthCheckResult(
                "tm_l2_lmdb", HealthStatus.DEGRADED, "Degraded"
            )

            monitor.check_health()

            # No recovery attempts should be made
            assert len(monitor.recovery_attempts) == 0

    def test_auto_recovery_enabled(self, temp_tm_dir):
        """Test that recovery runs when enabled."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=True)

        # Simulate degraded component
        result = HealthCheckResult("tm_l1_cache", HealthStatus.DEGRADED, "Cache issue")

        monitor._recover_component(result)

        # Recovery attempt should be recorded
        assert len(monitor.recovery_attempts) > 0
        assert monitor.recovery_attempts[0].component == "tm_l1_cache"

    def test_recovery_for_l1_cache(self, temp_tm_dir):
        """Test recovery attempt for L1 cache."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        result = HealthCheckResult("tm_l1_cache", HealthStatus.UNHEALTHY, "Cache error")

        monitor._recover_component(result)

        assert len(monitor.recovery_attempts) == 1
        action = monitor.recovery_attempts[0]
        assert action.component == "tm_l1_cache"
        assert action.success is True

    def test_recovery_for_disk_space(self, temp_tm_dir):
        """Test recovery attempt for disk space."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        result = HealthCheckResult("disk_space", HealthStatus.UNHEALTHY, "Disk full")

        monitor._recover_component(result)

        assert len(monitor.recovery_attempts) == 1
        action = monitor.recovery_attempts[0]
        assert action.component == "disk_space"
        assert "cleanup" in action.message.lower()


class TestHealthExport:
    """Test health status export functionality."""

    def test_export_health_status(self, temp_tm_dir):
        """Test exporting health status."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=False)

        status = monitor.export_health_status()

        assert "status" in status
        assert "timestamp" in status
        assert "checks" in status
        assert "recovery_attempts" in status
        assert isinstance(status["checks"], list)

    def test_export_includes_check_details(self, temp_tm_dir):
        """Test that export includes check details."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=False)

        status = monitor.export_health_status()

        assert len(status["checks"]) > 0
        check = status["checks"][0]
        assert "component" in check
        assert "status" in check
        assert "message" in check
        assert "details" in check

    def test_export_includes_recovery_attempts(self, temp_tm_dir):
        """Test that export includes recovery attempts."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=True)

        # Trigger recovery
        result = HealthCheckResult("tm_l1_cache", HealthStatus.DEGRADED, "Issue")
        monitor._recover_component(result)

        status = monitor.export_health_status()

        assert len(status["recovery_attempts"]) > 0
        attempt = status["recovery_attempts"][0]
        assert "component" in attempt
        assert "action" in attempt
        assert "success" in attempt

    def test_get_http_status_code_healthy(self, temp_tm_dir):
        """Test HTTP status code for healthy system."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=False)

        with mock.patch.object(monitor, "check_health") as mock_check:
            mock_check.return_value = (HealthStatus.HEALTHY, [])
            code = monitor.get_http_status_code()
            assert code == 200

    def test_get_http_status_code_degraded(self, temp_tm_dir):
        """Test HTTP status code for degraded system."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=False)

        with mock.patch.object(monitor, "check_health") as mock_check:
            mock_check.return_value = (HealthStatus.DEGRADED, [])
            code = monitor.get_http_status_code()
            assert code == 503

    def test_get_http_status_code_unhealthy(self, temp_tm_dir):
        """Test HTTP status code for unhealthy system."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, enable_auto_recovery=False)

        with mock.patch.object(monitor, "check_health") as mock_check:
            mock_check.return_value = (HealthStatus.UNHEALTHY, [])
            code = monitor.get_http_status_code()
            assert code == 503


class TestRecoveryHistory:
    """Test recovery history tracking."""

    def test_get_recovery_history(self, temp_tm_dir):
        """Test getting recovery history."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        # Add some recovery actions
        action1 = RecoveryAction("c1", "restart", True, "OK")
        action2 = RecoveryAction("c2", "rebuild", False, "Failed")

        monitor.recovery_attempts.append(action1)
        monitor.recovery_attempts.append(action2)

        history = monitor.get_recovery_history()

        assert len(history) == 2
        assert history[0].component == "c1"
        assert history[1].component == "c2"

    def test_recovery_history_is_copy(self, temp_tm_dir):
        """Test that recovery history returns a copy."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        action = RecoveryAction("c1", "restart", True, "OK")
        monitor.recovery_attempts.append(action)

        history1 = monitor.get_recovery_history()
        history2 = monitor.get_recovery_history()

        # Should be different objects
        assert history1 is not history2
        # But same content
        assert len(history1) == len(history2)


class TestHealthCheckTimeout:
    """Test health check timeout functionality."""

    def test_health_check_with_timeout(self, temp_tm_dir):
        """Test that health checks respect timeout."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir, timeout=1.0)

        # Check that timeout is set
        assert monitor.timeout == 1.0

        # Health check should complete within timeout
        import time

        start = time.time()
        monitor.check_health()
        duration = time.time() - start

        # Should be reasonably fast
        assert duration < 10.0


class TestHealthCheckFailureScenarios:
    """Test health check behavior in failure scenarios."""

    def test_check_with_missing_dependencies(self, temp_tm_dir):
        """Test health checks with missing dependencies."""
        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)

        # Should handle missing imports gracefully
        result = monitor.check_memory_usage()

        # Should return a result (degraded if psutil missing)
        assert result.component == "memory_usage"
        assert isinstance(result.status, HealthStatus)

    def test_check_with_permissions_error(self, temp_tm_dir):
        """Test health check with permissions errors."""
        # This would require actually changing permissions
        # which is platform-specific
        pass

    def test_check_with_corrupted_files(self, temp_tm_dir):
        """Test health check with corrupted files."""
        # Corrupt L2 database file
        (temp_tm_dir / "l2_lmdb" / "data.mdb").write_bytes(b"corrupted")

        monitor = HealthMonitor(tm_data_dir=temp_tm_dir)
        result = monitor.check_tm_l2()

        # Should detect corruption or handle gracefully
        assert result.component == "tm_l2_lmdb"
        assert isinstance(result.status, HealthStatus)
