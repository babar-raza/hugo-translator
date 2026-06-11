"""Unit tests for Translation Memory cache monitoring.

Tests cover:
- Cache size reporting
- Usage percentage calculation
- Warning threshold detection
- Critical threshold alerts
- Recommendation messages
"""

import sys
from pathlib import Path
from unittest import mock

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tm.l2_persistent import L2PersistentTM
from tm.monitoring import CacheMonitor, CacheSizeReport, create_monitor_from_path


class TestCacheSizeReport:
    """Tests for CacheSizeReport dataclass."""

    def test_report_string_format(self):
        """Test string representation has expected format."""
        report = CacheSizeReport(
            current_bytes=500 * 1024 * 1024,  # 500MB
            max_bytes=1024 * 1024 * 1024,  # 1GB
            usage_percent=48.83,
            entry_count=10000,
            warning=False,
        )

        report_str = str(report)
        assert "500.0MB" in report_str
        assert "1024MB" in report_str
        assert "48.8%" in report_str or "48.83%" in report_str
        assert "10000" in report_str

    def test_report_current_mb(self):
        """Test megabyte conversion."""
        report = CacheSizeReport(
            current_bytes=512 * 1024 * 1024,
            max_bytes=1024 * 1024 * 1024,
            usage_percent=50.0,
            entry_count=1000,
            warning=False,
        )

        assert report.current_mb == 512.0

    def test_report_current_gb(self):
        """Test gigabyte conversion."""
        report = CacheSizeReport(
            current_bytes=1024 * 1024 * 1024,
            max_bytes=2 * 1024 * 1024 * 1024,
            usage_percent=50.0,
            entry_count=1000,
            warning=False,
        )

        assert report.current_gb == 1.0

    def test_report_to_dict(self):
        """Test dictionary conversion."""
        report = CacheSizeReport(
            current_bytes=512 * 1024 * 1024,
            max_bytes=1024 * 1024 * 1024,
            usage_percent=50.0,
            entry_count=1000,
            warning=True,
            recommendation="Test recommendation",
        )

        d = report.to_dict()

        assert d["current_bytes"] == 512 * 1024 * 1024
        assert d["current_mb"] == 512.0
        assert d["usage_percent"] == 50.0
        assert d["entry_count"] == 1000
        assert d["warning"] is True
        assert d["recommendation"] == "Test recommendation"


class TestCacheMonitor:
    """Tests for CacheMonitor class."""

    @pytest.fixture
    def mock_l2(self):
        """Create a mock L2PersistentTM."""
        mock_env = mock.MagicMock()

        # Default stats: 50% usage
        mock_env.stat.return_value = {
            "psize": 4096,  # page size
            "entries": 5000,
        }
        mock_env.info.return_value = {
            "last_pgno": 12800,  # ~50MB used
            "map_size": 100 * 1024 * 1024,  # 100MB max
        }

        mock_l2 = mock.MagicMock(spec=L2PersistentTM)
        mock_l2.env = mock_env

        return mock_l2

    def test_monitor_reports_size(self, mock_l2):
        """Test basic size reporting."""
        monitor = CacheMonitor(mock_l2)
        report = monitor.check_size()

        assert report.entry_count == 5000
        assert report.max_bytes == 100 * 1024 * 1024
        # 12800 pages * 4096 bytes = 52428800 bytes (~52MB)
        assert report.current_bytes == 52428800

    def test_monitor_calculates_usage_percent(self, mock_l2):
        """Test usage percentage calculation."""
        monitor = CacheMonitor(mock_l2)
        report = monitor.check_size()

        # 52428800 / 104857600 * 100 = 50%
        expected_usage = (12800 * 4096) / (100 * 1024 * 1024) * 100
        assert abs(report.usage_percent - expected_usage) < 0.1

    def test_monitor_no_warning_below_threshold(self, mock_l2):
        """Test no warning when below threshold."""
        monitor = CacheMonitor(mock_l2, warn_threshold_percent=80)
        report = monitor.check_size()

        assert report.warning is False
        assert report.recommendation is None

    def test_monitor_warns_at_threshold(self, mock_l2):
        """Test warning at warn threshold."""
        # Set usage to 85%
        mock_l2.env.info.return_value = {
            "last_pgno": 21760,  # ~85% of 100MB
            "map_size": 100 * 1024 * 1024,
        }

        monitor = CacheMonitor(mock_l2, warn_threshold_percent=80)
        report = monitor.check_size()

        assert report.warning is True
        assert "WARNING" in report.recommendation

    def test_monitor_critical_at_high_usage(self, mock_l2):
        """Test critical alert at critical threshold."""
        # Set usage to 96%
        mock_l2.env.info.return_value = {
            "last_pgno": 24576,  # ~96% of 100MB
            "map_size": 100 * 1024 * 1024,
        }

        monitor = CacheMonitor(mock_l2, critical_threshold_percent=95)
        report = monitor.check_size()

        assert report.warning is True
        assert "CRITICAL" in report.recommendation

    def test_monitor_provides_recommendations(self, mock_l2):
        """Test actionable recommendations are provided."""
        # Set usage to 96%
        mock_l2.env.info.return_value = {"last_pgno": 24576, "map_size": 100 * 1024 * 1024}

        monitor = CacheMonitor(mock_l2, critical_threshold_percent=95)
        report = monitor.check_size()

        assert report.recommendation is not None
        assert "max_size_mb" in report.recommendation

    def test_monitor_is_healthy(self, mock_l2):
        """Test is_healthy method."""
        monitor = CacheMonitor(mock_l2, warn_threshold_percent=80)

        # Default mock is 50% usage
        assert monitor.is_healthy() is True

        # Set usage to 85%
        mock_l2.env.info.return_value = {"last_pgno": 21760, "map_size": 100 * 1024 * 1024}
        assert monitor.is_healthy() is False

    def test_monitor_get_usage_percent(self, mock_l2):
        """Test get_usage_percent method."""
        monitor = CacheMonitor(mock_l2)

        usage = monitor.get_usage_percent()

        expected = (12800 * 4096) / (100 * 1024 * 1024) * 100
        assert abs(usage - expected) < 0.1


class TestCacheMonitorValidation:
    """Tests for threshold validation."""

    @pytest.fixture
    def mock_l2(self):
        """Create a mock L2PersistentTM."""
        mock_env = mock.MagicMock()
        mock_env.stat.return_value = {"psize": 4096, "entries": 1000}
        mock_env.info.return_value = {"last_pgno": 1000, "map_size": 100 * 1024 * 1024}

        mock_l2 = mock.MagicMock(spec=L2PersistentTM)
        mock_l2.env = mock_env
        return mock_l2

    def test_invalid_warn_threshold_too_low(self, mock_l2):
        """Test validation rejects warn_threshold <= 0."""
        with pytest.raises(ValueError, match="warn_threshold"):
            CacheMonitor(mock_l2, warn_threshold_percent=0)

    def test_invalid_warn_threshold_too_high(self, mock_l2):
        """Test validation rejects warn_threshold >= 100."""
        with pytest.raises(ValueError, match="warn_threshold"):
            CacheMonitor(mock_l2, warn_threshold_percent=100)

    def test_invalid_critical_threshold_too_low(self, mock_l2):
        """Test validation rejects critical_threshold <= 0."""
        with pytest.raises(ValueError, match="critical_threshold"):
            CacheMonitor(mock_l2, critical_threshold_percent=0)

    def test_warn_must_be_less_than_critical(self, mock_l2):
        """Test warn threshold must be less than critical."""
        with pytest.raises(ValueError, match="must be less than"):
            CacheMonitor(mock_l2, warn_threshold_percent=90, critical_threshold_percent=80)

    def test_warn_cannot_equal_critical(self, mock_l2):
        """Test warn threshold cannot equal critical."""
        with pytest.raises(ValueError, match="must be less than"):
            CacheMonitor(mock_l2, warn_threshold_percent=80, critical_threshold_percent=80)


class TestCacheMonitorIntegration:
    """Integration tests with real LMDB database."""

    @pytest.fixture
    def l2_with_data(self, tmp_path):
        """Create L2PersistentTM with some test data."""
        db_path = tmp_path / "test_tm"
        l2 = L2PersistentTM(db_path, max_size_mb=10)

        # Add some test entries
        for i in range(100):
            l2.store(
                site_id="test.site",
                src_lang="en",
                tgt_lang="es",
                text=f"Test source text {i}",
                translation=f"Test translation {i}",
            )

        return l2

    def test_monitor_with_real_lmdb(self, l2_with_data):
        """Test monitoring with real LMDB database."""
        monitor = CacheMonitor(l2_with_data)
        report = monitor.check_size()

        # Should have 100 entries
        assert report.entry_count == 100

        # Should have some size
        assert report.current_bytes > 0
        assert report.max_bytes == 10 * 1024 * 1024

        # Should be healthy (well below threshold)
        assert report.warning is False
        assert report.usage_percent < 80

    def test_monitor_with_empty_cache(self, tmp_path):
        """Test monitoring with empty cache."""
        db_path = tmp_path / "empty_tm"
        l2 = L2PersistentTM(db_path, max_size_mb=10)

        monitor = CacheMonitor(l2)
        report = monitor.check_size()

        assert report.entry_count == 0
        assert report.warning is False


class TestCreateMonitorFromPath:
    """Tests for create_monitor_from_path convenience function."""

    def test_create_monitor_from_path(self, tmp_path):
        """Test creating monitor from path."""
        db_path = tmp_path / "test_tm"

        # Create initial database
        l2 = L2PersistentTM(db_path, max_size_mb=10)
        l2.close()

        # Create monitor from path
        monitor = create_monitor_from_path(db_path)

        assert isinstance(monitor, CacheMonitor)
        report = monitor.check_size()
        assert report.max_bytes == 1024 * 1024 * 1024  # Default 1GB

    def test_create_monitor_with_custom_thresholds(self, tmp_path):
        """Test creating monitor with custom thresholds."""
        db_path = tmp_path / "test_tm"
        l2 = L2PersistentTM(db_path, max_size_mb=10)
        l2.close()

        monitor = create_monitor_from_path(
            db_path, warn_threshold_percent=70, critical_threshold_percent=90
        )

        assert monitor.warn_threshold == 70
        assert monitor.critical_threshold == 90
