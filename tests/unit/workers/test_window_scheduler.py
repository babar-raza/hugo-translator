"""
Unit tests for WindowScheduler - Timezone-aware scheduling logic.
"""

from datetime import datetime, timedelta
from datetime import time as dt_time
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.workers.window_scheduler import ScheduleConfig, WindowScheduler


class TestScheduleConfig:
    """Tests for ScheduleConfig validation."""

    def test_valid_config(self):
        """Test creating valid configuration."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
            jitter_minutes=10,
        )

        assert config.runs_per_day == 5
        assert config.window_start == "10:00"
        assert config.window_end == "22:00"
        assert config.timezone == "America/Los_Angeles"
        assert config.jitter_minutes == 10

    def test_invalid_runs_per_day(self):
        """Test that runs_per_day must be >= 1."""
        with pytest.raises(ValueError, match="runs_per_day must be >= 1"):
            ScheduleConfig(
                runs_per_day=0,
                window_start="10:00",
                window_end="22:00",
                timezone="America/Los_Angeles",
            )

    def test_invalid_jitter(self):
        """Test that jitter_minutes must be >= 0."""
        with pytest.raises(ValueError, match="jitter_minutes must be >= 0"):
            ScheduleConfig(
                runs_per_day=5,
                window_start="10:00",
                window_end="22:00",
                timezone="America/Los_Angeles",
                jitter_minutes=-5,
            )

    def test_invalid_time_format(self):
        """Test that time strings must be HH:MM format."""
        with pytest.raises(ValueError, match="Expected HH:MM format"):
            ScheduleConfig(
                runs_per_day=5,
                window_start="10:00:00",  # Invalid: seconds included
                window_end="22:00",
                timezone="America/Los_Angeles",
            )

    def test_invalid_hour(self):
        """Test that hour must be 0-23."""
        with pytest.raises(ValueError, match="Hour must be 0-23"):
            ScheduleConfig(
                runs_per_day=5,
                window_start="25:00",  # Invalid: hour > 23
                window_end="22:00",
                timezone="America/Los_Angeles",
            )

    def test_invalid_minute(self):
        """Test that minute must be 0-59."""
        with pytest.raises(ValueError, match="Minute must be 0-59"):
            ScheduleConfig(
                runs_per_day=5,
                window_start="10:60",  # Invalid: minute > 59
                window_end="22:00",
                timezone="America/Los_Angeles",
            )

    def test_invalid_timezone(self):
        """Test that timezone must be valid."""
        with pytest.raises(ValueError, match="Invalid timezone"):
            ScheduleConfig(
                runs_per_day=5,
                window_start="10:00",
                window_end="22:00",
                timezone="Invalid/Timezone",
            )


class TestWindowScheduler:
    """Tests for WindowScheduler scheduling logic."""

    def test_initialization(self):
        """Test scheduler initialization."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        assert scheduler.config == config
        assert scheduler.tz == ZoneInfo("America/Los_Angeles")

    def test_get_base_run_times_five_runs(self):
        """Test getting base run times for 5 runs/day."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        # Mock current time to 2025-01-16 09:00 PST (before window)
        mock_now = datetime(2025, 1, 16, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

        with patch("src.workers.window_scheduler.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            run_times = scheduler.get_base_run_times_today()

        # Verify 5 runs
        assert len(run_times) == 5

        # Verify times are evenly distributed
        # Window: 10:00-22:00 = 12 hours
        # Interval: 12 hours / 4 = 3 hours
        # Times: 10:00, 13:00, 16:00, 19:00, 22:00
        expected_times = [
            dt_time(10, 0),
            dt_time(13, 0),
            dt_time(16, 0),
            dt_time(19, 0),
            dt_time(22, 0),
        ]

        for run_time, expected_time in zip(run_times, expected_times, strict=False):
            assert run_time.time() == expected_time

    def test_get_base_run_times_single_run(self):
        """Test getting base run times for 1 run/day."""
        config = ScheduleConfig(
            runs_per_day=1,
            window_start="14:00",
            window_end="14:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        mock_now = datetime(2025, 1, 16, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

        with patch("src.workers.window_scheduler.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            run_times = scheduler.get_base_run_times_today()

        assert len(run_times) == 1
        assert run_times[0].time() == dt_time(14, 0)

    def test_apply_jitter_no_jitter(self):
        """Test jitter application with jitter_minutes=0."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
            jitter_minutes=0,
        )
        scheduler = WindowScheduler(config)

        base_time = datetime(2025, 1, 16, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        jittered = scheduler.apply_jitter(base_time)

        # Should return unchanged
        assert jittered == base_time

    def test_apply_jitter_with_jitter(self):
        """Test jitter application with jitter_minutes=10."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
            jitter_minutes=10,
        )
        scheduler = WindowScheduler(config)

        base_time = datetime(2025, 1, 16, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

        # Run multiple times to ensure jitter is within bounds
        for _ in range(10):
            jittered = scheduler.apply_jitter(base_time)

            # Jitter should be in range [-10, +10] minutes
            delta_seconds = abs((jittered - base_time).total_seconds())
            assert delta_seconds <= 10 * 60  # 10 minutes

    def test_get_next_run_time_before_window(self):
        """Test next run time when current time is before window."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        # Current time: 09:00 (before first run at 10:00)
        mock_now = datetime(2025, 1, 16, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

        with patch("src.workers.window_scheduler.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            next_run = scheduler.get_next_run_time(apply_jitter=False)

        # Should return first run of today (10:00)
        assert next_run.date() == mock_now.date()
        assert next_run.time() == dt_time(10, 0)

    def test_get_next_run_time_during_window(self):
        """Test next run time when current time is during window."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        # Current time: 14:30 (between 13:00 and 16:00 runs)
        mock_now = datetime(2025, 1, 16, 14, 30, tzinfo=ZoneInfo("America/Los_Angeles"))

        with patch("src.workers.window_scheduler.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            next_run = scheduler.get_next_run_time(apply_jitter=False)

        # Should return next run (16:00)
        assert next_run.date() == mock_now.date()
        assert next_run.time() == dt_time(16, 0)

    def test_get_next_run_time_after_window(self):
        """Test next run time when current time is after window."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        # Current time: 23:00 (after last run at 22:00)
        mock_now = datetime(2025, 1, 16, 23, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

        with patch("src.workers.window_scheduler.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            next_run = scheduler.get_next_run_time(apply_jitter=False)

        # Should return first run of tomorrow (10:00)
        expected_date = mock_now.date() + timedelta(days=1)
        assert next_run.date() == expected_date
        assert next_run.time() == dt_time(10, 0)

    def test_is_within_window_before(self):
        """Test is_within_window before window starts."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        check_time = datetime(2025, 1, 16, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        assert not scheduler.is_within_window(check_time)

    def test_is_within_window_at_start(self):
        """Test is_within_window at window start."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        check_time = datetime(2025, 1, 16, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        assert scheduler.is_within_window(check_time)

    def test_is_within_window_during(self):
        """Test is_within_window during window."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        check_time = datetime(2025, 1, 16, 15, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        assert scheduler.is_within_window(check_time)

    def test_is_within_window_at_end(self):
        """Test is_within_window at window end."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        check_time = datetime(2025, 1, 16, 22, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        assert scheduler.is_within_window(check_time)

    def test_is_within_window_after(self):
        """Test is_within_window after window ends."""
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        check_time = datetime(2025, 1, 16, 23, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        assert not scheduler.is_within_window(check_time)

    def test_timezone_independence(self):
        """Test that scheduler uses configured timezone, not system timezone."""
        # Create scheduler for LA timezone
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        # Mock current time as NYC time (3 hours ahead)
        mock_now_nyc = datetime(2025, 1, 16, 13, 0, tzinfo=ZoneInfo("America/New_York"))

        # Convert to LA time (should be 10:00 LA)
        mock_now_la = mock_now_nyc.astimezone(ZoneInfo("America/Los_Angeles"))

        with patch("src.workers.window_scheduler.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now_la
            next_run = scheduler.get_next_run_time(apply_jitter=False)

        # Should return next run in LA timezone (13:00 LA time)
        assert next_run.tzinfo == ZoneInfo("America/Los_Angeles")
        assert next_run.time() == dt_time(13, 0)

    def test_daylight_saving_time_transition(self):
        """Test that scheduler handles DST transitions correctly."""
        # Note: This test verifies that zoneinfo handles DST automatically
        config = ScheduleConfig(
            runs_per_day=2,
            window_start="02:00",
            window_end="04:00",
            timezone="America/Los_Angeles",
        )
        scheduler = WindowScheduler(config)

        # Mock time during DST transition (spring forward)
        # 2025-03-09 is DST transition date in America/Los_Angeles
        mock_now = datetime(2025, 3, 9, 1, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

        with patch("src.workers.window_scheduler.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            run_times = scheduler.get_base_run_times_today()

        # Should still have 2 runs despite DST transition
        assert len(run_times) == 2

        # Times should be in LA timezone (PST/PDT handled by zoneinfo)
        for run_time in run_times:
            assert run_time.tzinfo == ZoneInfo("America/Los_Angeles")
