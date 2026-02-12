"""
Window Scheduler - Timezone-aware scheduling for autonomous workers.

Provides scheduling logic for running tasks within a daily time window with:
- Timezone-aware time calculations (no dependency on local machine time)
- Even distribution of runs across the window with optional jitter
- Support for both daemon (self-scheduling) and oneshot modes
"""

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass
class ScheduleConfig:
    """
    Configuration for window-based scheduling.

    Attributes:
        runs_per_day: Number of times to run per day
        window_start: Start of daily window (HH:MM format)
        window_end: End of daily window (HH:MM format)
        timezone: Timezone name (e.g., "America/Los_Angeles")
        jitter_minutes: Random jitter to add/subtract (default: 10 minutes)

    Example:
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
            jitter_minutes=10
        )
    """
    runs_per_day: int
    window_start: str  # HH:MM
    window_end: str    # HH:MM
    timezone: str
    jitter_minutes: int = 10

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.runs_per_day < 1:
            raise ValueError(f"runs_per_day must be >= 1, got {self.runs_per_day}")

        if self.jitter_minutes < 0:
            raise ValueError(f"jitter_minutes must be >= 0, got {self.jitter_minutes}")

        # Validate time formats
        try:
            self._parse_time(self.window_start)
        except ValueError as e:
            raise ValueError(f"Invalid window_start format '{self.window_start}': {e}")

        try:
            self._parse_time(self.window_end)
        except ValueError as e:
            raise ValueError(f"Invalid window_end format '{self.window_end}': {e}")

        # Validate timezone
        try:
            ZoneInfo(self.timezone)
        except Exception as e:
            raise ValueError(f"Invalid timezone '{self.timezone}': {e}")

    @staticmethod
    def _parse_time(time_str: str) -> dt_time:
        """Parse HH:MM time string into datetime.time object."""
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError(f"Expected HH:MM format, got '{time_str}'")

        hour = int(parts[0])
        minute = int(parts[1])

        if not (0 <= hour <= 23):
            raise ValueError(f"Hour must be 0-23, got {hour}")
        if not (0 <= minute <= 59):
            raise ValueError(f"Minute must be 0-59, got {minute}")

        return dt_time(hour, minute)


class WindowScheduler:
    """
    Scheduler for running tasks within a daily time window.

    Computes run times by:
    1. Dividing the window into equal intervals
    2. Adding optional jitter to each run time
    3. Ensuring all times are in the specified timezone

    Example:
        config = ScheduleConfig(
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
            jitter_minutes=10
        )

        scheduler = WindowScheduler(config)

        # Get next run time
        next_run = scheduler.get_next_run_time()
        logger.info(f"Next run at: {next_run}")

        # Wait until next run
        scheduler.sleep_until_next_run()
        # ... execute task ...
    """

    def __init__(self, config: ScheduleConfig, min_gap_seconds: int = 300):
        """
        Initialize scheduler with configuration.

        Args:
            config: Schedule configuration
            min_gap_seconds: Minimum gap between runs in seconds (default: 300 = 5 min)
        """
        self.config = config
        self.tz = ZoneInfo(config.timezone)
        self.min_gap_seconds = min_gap_seconds
        self._last_run_end: Optional[datetime] = None

        logger.info(
            f"Initialized WindowScheduler: {config.runs_per_day} runs/day, "
            f"window {config.window_start}-{config.window_end} {config.timezone}, "
            f"min_gap={min_gap_seconds}s"
        )

    def mark_run_complete(self):
        """Record that a run has completed, for overlap protection."""
        self._last_run_end = datetime.now(self.tz)

    def get_base_run_times_today(self) -> List[datetime]:
        """
        Get base run times for today (without jitter).

        Divides the window into equal intervals based on runs_per_day.

        Returns:
            List of datetimes in the configured timezone

        Example:
            # 5 runs from 10:00-22:00
            # Returns times at: 10:00, 13:00, 16:00, 19:00, 22:00
        """
        now = datetime.now(self.tz)
        today = now.date()

        # Parse window start/end times
        start_time = self.config._parse_time(self.config.window_start)
        end_time = self.config._parse_time(self.config.window_end)

        # Create datetime objects for today's window
        window_start = datetime.combine(today, start_time, tzinfo=self.tz)
        window_end = datetime.combine(today, end_time, tzinfo=self.tz)

        # Calculate interval between runs
        window_duration = (window_end - window_start).total_seconds()
        interval_seconds = window_duration / (self.config.runs_per_day - 1) if self.config.runs_per_day > 1 else 0

        # Generate base run times
        base_times = []
        for i in range(self.config.runs_per_day):
            run_time = window_start + timedelta(seconds=i * interval_seconds)
            base_times.append(run_time)

        return base_times

    def apply_jitter(self, base_time: datetime) -> datetime:
        """
        Apply random jitter to a base time.

        Jitter is uniformly distributed in [-jitter_minutes, +jitter_minutes].

        Args:
            base_time: Base datetime to jitter

        Returns:
            Jittered datetime
        """
        if self.config.jitter_minutes == 0:
            return base_time

        # Random jitter in range [-jitter_minutes, +jitter_minutes]
        jitter_seconds = random.randint(
            -self.config.jitter_minutes * 60,
            self.config.jitter_minutes * 60
        )

        jittered_time = base_time + timedelta(seconds=jitter_seconds)

        logger.debug(
            f"Applied jitter: {base_time.strftime('%H:%M:%S')} -> "
            f"{jittered_time.strftime('%H:%M:%S')} ({jitter_seconds}s)"
        )

        return jittered_time

    def get_next_run_time(self, apply_jitter: bool = True) -> Optional[datetime]:
        """
        Get the next scheduled run time.

        Logic:
        1. Get today's base run times
        2. Filter out times that have already passed
        3. If no runs left today, return first run tomorrow
        4. Apply jitter if requested

        Args:
            apply_jitter: Whether to apply random jitter (default: True)

        Returns:
            Next run time as timezone-aware datetime, or None if no more runs today
            and tomorrow's schedule hasn't been computed yet
        """
        now = datetime.now(self.tz)

        # Get today's base run times
        today_runs = self.get_base_run_times_today()

        # Filter to future runs only
        future_runs = [t for t in today_runs if t > now]

        if future_runs:
            # Return next run today
            next_run = future_runs[0]
            if apply_jitter:
                next_run = self.apply_jitter(next_run)
            return next_run
        else:
            # No more runs today, get first run tomorrow
            tomorrow = now.date() + timedelta(days=1)
            start_time = self.config._parse_time(self.config.window_start)

            next_run = datetime.combine(tomorrow, start_time, tzinfo=self.tz)
            if apply_jitter:
                next_run = self.apply_jitter(next_run)
            return next_run

    def sleep_until_next_run(self, apply_jitter: bool = True) -> datetime:
        """
        Sleep until the next scheduled run time.

        Args:
            apply_jitter: Whether to apply random jitter (default: True)

        Returns:
            The datetime when execution resumes (after sleep)

        Example:
            scheduler = WindowScheduler(config)

            while True:
                # Sleep until next run
                run_time = scheduler.sleep_until_next_run()

                # Execute task
                logger.info(f"Running at {run_time}")
                execute_translation_task()
        """
        next_run = self.get_next_run_time(apply_jitter=apply_jitter)
        now = datetime.now(self.tz)

        # Enforce minimum gap between runs
        if self._last_run_end is not None:
            earliest_allowed = self._last_run_end + timedelta(seconds=self.min_gap_seconds)
            if next_run < earliest_allowed:
                next_run = earliest_allowed
                logger.info(
                    f"Enforcing {self.min_gap_seconds}s minimum gap. "
                    f"Next run adjusted to {next_run.strftime('%H:%M:%S')}"
                )

        if next_run <= now:
            # Already past run time, return immediately
            logger.warning(f"Next run time {next_run} is in the past, executing immediately")
            return now

        sleep_seconds = (next_run - now).total_seconds()

        logger.info(
            f"Sleeping until {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"({sleep_seconds:.0f} seconds)"
        )

        time.sleep(sleep_seconds)

        return next_run

    def is_within_window(self, check_time: Optional[datetime] = None) -> bool:
        """
        Check if a given time is within the daily window.

        Args:
            check_time: Time to check (default: now in configured timezone)

        Returns:
            True if within window, False otherwise
        """
        if check_time is None:
            check_time = datetime.now(self.tz)

        # Ensure check_time is in the correct timezone
        if check_time.tzinfo != self.tz:
            check_time = check_time.astimezone(self.tz)

        # Parse window times for today
        start_time = self.config._parse_time(self.config.window_start)
        end_time = self.config._parse_time(self.config.window_end)

        current_time = check_time.time()

        # Check if current time is within [start, end]
        return start_time <= current_time <= end_time
