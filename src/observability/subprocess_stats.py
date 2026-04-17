"""
Subprocess Statistics Tracking (TASK-CODE-01).

Provides comprehensive statistics tracking for subprocess executions including:
- Execution metrics (duration, success/failure counts, exit codes)
- Resource usage tracking
- Error tracking and diagnostics
- Telemetry integration for observability

Usage:
    from src.observability.subprocess_stats import (
        SubprocessStats,
        SubprocessExecutionRecord,
        run_with_stats,
    )

    # Global stats instance
    stats = SubprocessStats()

    # Method 1: Use wrapper function
    result = run_with_stats(
        ["git", "status"],
        stats_tracker=stats,
        timeout=30
    )

    # Method 2: Manual recording
    record = SubprocessExecutionRecord(
        command="git status",
        start_time=datetime.now(),
        end_time=datetime.now(),
        duration=0.5,
        exit_code=0,
        success=True,
        stdout_length=100,
        stderr_length=0,
    )
    stats.record(record)

    # Get summary statistics
    summary = stats.get_summary()
"""
import logging
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_SLOW_THRESHOLD_SECONDS = 30.0
DEFAULT_SUMMARY_INTERVAL = 100  # Log summary every N executions
TELEMETRY_ENABLED = True  # Global flag for telemetry emission


@dataclass
class SubprocessExecutionRecord:
    """Record of a single subprocess execution."""

    command: str  # Command executed (e.g., "git status")
    start_time: datetime
    end_time: datetime
    duration: float  # Duration in seconds
    exit_code: int
    success: bool  # True if exit_code == 0
    stdout_length: int = 0  # Length of stdout in bytes
    stderr_length: int = 0  # Length of stderr in bytes
    error: str | None = None  # Error message if failed
    cwd: str | None = None  # Working directory
    timeout: float | None = None  # Timeout value if set

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary for telemetry."""
        return {
            "command": self.command,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration": self.duration,
            "exit_code": self.exit_code,
            "success": self.success,
            "stdout_length": self.stdout_length,
            "stderr_length": self.stderr_length,
            "error": self.error,
            "cwd": self.cwd,
            "timeout": self.timeout,
        }


class SubprocessStats:
    """
    Track statistics for subprocess executions.

    Features:
    - Thread-safe operation with locks
    - Real-time tracking of executions
    - Aggregate statistics calculation
    - Periodic summary logging
    - Telemetry event emission
    - Error analysis and diagnostics

    Thread Safety:
        All public methods are thread-safe using internal locks.
    """

    def __init__(
        self,
        slow_threshold: float = DEFAULT_SLOW_THRESHOLD_SECONDS,
        summary_interval: int = DEFAULT_SUMMARY_INTERVAL,
        enable_telemetry: bool = TELEMETRY_ENABLED,
    ):
        """
        Initialize SubprocessStats tracker.

        Args:
            slow_threshold: Threshold in seconds for slow execution alerts
            summary_interval: Log summary every N executions
            enable_telemetry: Enable telemetry event emission
        """
        self._lock = Lock()

        # Configuration
        self.slow_threshold = slow_threshold
        self.summary_interval = summary_interval
        self.enable_telemetry = enable_telemetry

        # Execution records (limited to last 1000 for memory efficiency)
        self._executions: list[SubprocessExecutionRecord] = []
        self._max_records = 1000

        # Aggregate counters
        self.total_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.slow_count = 0  # Executions exceeding slow_threshold

        # Duration tracking
        self.total_duration = 0.0
        self.min_duration = float("inf")
        self.max_duration = 0.0

        # Exit code tracking
        self._exit_codes: Counter = Counter()

        # Command tracking
        self._command_counts: Counter = Counter()
        self._command_failures: Counter = Counter()

        # Error tracking
        self._errors: list[tuple[str, str]] = []  # (command, error) pairs
        self._max_errors = 100

        # Last summary log timestamp
        self._last_summary_log = 0

    def record(self, record: SubprocessExecutionRecord) -> None:
        """
        Record a subprocess execution.

        Thread-safe method to record execution and emit telemetry events.

        Args:
            record: SubprocessExecutionRecord to record
        """
        with self._lock:
            # Add to executions list (with size limit)
            self._executions.append(record)
            if len(self._executions) > self._max_records:
                self._executions.pop(0)  # Remove oldest

            # Update counters
            self.total_count += 1
            if record.success:
                self.success_count += 1
            else:
                self.failure_count += 1
                # Track error
                if record.error and len(self._errors) < self._max_errors:
                    self._errors.append((record.command, record.error))
                self._command_failures[record.command] += 1

            # Track duration statistics
            self.total_duration += record.duration
            self.min_duration = min(self.min_duration, record.duration)
            self.max_duration = max(self.max_duration, record.duration)

            # Track slow executions
            if record.duration >= self.slow_threshold:
                self.slow_count += 1

            # Track exit codes
            self._exit_codes[record.exit_code] += 1

            # Track command counts
            self._command_counts[record.command] += 1

        # Emit telemetry events (outside lock to avoid blocking)
        if self.enable_telemetry:
            self._emit_telemetry(record)

        # Periodic summary logging
        if self.total_count % self.summary_interval == 0:
            self._log_summary()

    def get_summary(self) -> dict[str, Any]:
        """
        Get aggregate statistics summary.

        Returns:
            Dictionary with comprehensive statistics including:
            - Counts (total, success, failure, slow)
            - Error rate
            - Duration statistics (avg, min, max)
            - Top exit codes
            - Top commands
            - Top failing commands
        """
        with self._lock:
            if self.total_count == 0:
                return {
                    "total_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "error_rate": 0.0,
                }

            avg_duration = self.total_duration / self.total_count

            return {
                # Counts
                "total_count": self.total_count,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "slow_count": self.slow_count,
                # Rates
                "error_rate": self.failure_count / self.total_count,
                "slow_rate": self.slow_count / self.total_count,
                # Duration statistics
                "avg_duration": avg_duration,
                "min_duration": self.min_duration if self.min_duration != float("inf") else 0.0,
                "max_duration": self.max_duration,
                "total_duration": self.total_duration,
                # Top exit codes (top 5)
                "top_exit_codes": self._exit_codes.most_common(5),
                # Top commands (top 10)
                "top_commands": self._command_counts.most_common(10),
                # Top failing commands (top 5)
                "top_failing_commands": self._command_failures.most_common(5),
                # Recent errors (last 5)
                "recent_errors": self._errors[-5:] if self._errors else [],
            }

    def reset(self) -> None:
        """
        Reset all statistics.

        Thread-safe method to clear all tracked data and reset counters.
        """
        with self._lock:
            self._executions.clear()
            self.total_count = 0
            self.success_count = 0
            self.failure_count = 0
            self.slow_count = 0
            self.total_duration = 0.0
            self.min_duration = float("inf")
            self.max_duration = 0.0
            self._exit_codes.clear()
            self._command_counts.clear()
            self._command_failures.clear()
            self._errors.clear()
            self._last_summary_log = 0

    def get_command_stats(self, command: str) -> dict[str, Any]:
        """
        Get statistics for a specific command.

        Args:
            command: Command to get stats for

        Returns:
            Dictionary with command-specific statistics
        """
        with self._lock:
            # Filter executions for this command
            command_execs = [e for e in self._executions if e.command == command]

            if not command_execs:
                return {
                    "command": command,
                    "count": 0,
                }

            successes = sum(1 for e in command_execs if e.success)
            failures = sum(1 for e in command_execs if not e.success)
            durations = [e.duration for e in command_execs]

            return {
                "command": command,
                "count": len(command_execs),
                "success_count": successes,
                "failure_count": failures,
                "error_rate": failures / len(command_execs),
                "avg_duration": sum(durations) / len(durations),
                "min_duration": min(durations),
                "max_duration": max(durations),
            }

    def _emit_telemetry(self, record: SubprocessExecutionRecord) -> None:
        """
        Emit telemetry events for subprocess execution.

        Events emitted:
        - subprocess_executed: Every execution
        - subprocess_failed: Non-zero exit code
        - subprocess_slow: Duration exceeds threshold

        Args:
            record: Execution record to emit events for
        """
        try:
            # Import telemetry platform (lazy import to avoid circular deps)
            from src.observability.telemetry_integration import emit_event

            # Event 1: subprocess_executed (every execution)
            emit_event(
                "subprocess_executed",
                {
                    "command": record.command,
                    "exit_code": record.exit_code,
                    "success": record.success,
                    "duration": record.duration,
                    "stdout_length": record.stdout_length,
                    "stderr_length": record.stderr_length,
                    "cwd": record.cwd,
                },
            )

            # Event 2: subprocess_failed (failures only)
            if not record.success:
                emit_event(
                    "subprocess_failed",
                    {
                        "command": record.command,
                        "exit_code": record.exit_code,
                        "duration": record.duration,
                        "error": record.error or f"Exit code {record.exit_code}",
                        "stderr_length": record.stderr_length,
                    },
                )

            # Event 3: subprocess_slow (slow executions)
            if record.duration >= self.slow_threshold:
                emit_event(
                    "subprocess_slow",
                    {
                        "command": record.command,
                        "duration": record.duration,
                        "threshold": self.slow_threshold,
                        "exit_code": record.exit_code,
                    },
                )

        except Exception as e:
            # Don't let telemetry failures break stats tracking
            logger.debug(f"Failed to emit telemetry for subprocess: {e}")

    def _log_summary(self) -> None:
        """
        Log periodic summary statistics.

        Logs at INFO level every summary_interval executions.
        Also emits subprocess_stats_summary telemetry event.
        """
        try:
            summary = self.get_summary()

            logger.info(
                f"Subprocess stats: {summary['total_count']} total, "
                f"{summary['success_count']} success, "
                f"{summary['failure_count']} failed "
                f"(error rate: {summary['error_rate']:.1%}), "
                f"avg duration: {summary['avg_duration']:.2f}s"
            )

            # Emit summary telemetry event
            if self.enable_telemetry:
                try:
                    from src.observability.telemetry_integration import emit_event

                    emit_event("subprocess_stats_summary", summary)
                except Exception as e:
                    logger.debug(f"Failed to emit summary telemetry: {e}")

        except Exception as e:
            logger.warning(f"Failed to log subprocess summary: {e}")


# Global stats instance for convenience
_global_stats: SubprocessStats | None = None


def get_global_stats() -> SubprocessStats:
    """
    Get or create global SubprocessStats instance.

    Returns:
        Global SubprocessStats instance
    """
    global _global_stats
    if _global_stats is None:
        _global_stats = SubprocessStats()
    return _global_stats


def run_with_stats(
    args: list[str],
    stats_tracker: SubprocessStats | None = None,
    timeout: float | None = None,
    cwd: str | None = None,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """
    Run subprocess command with automatic stats tracking.

    Wrapper around subprocess.run() that automatically tracks execution
    statistics and emits telemetry events.

    Args:
        args: Command and arguments to run
        stats_tracker: SubprocessStats instance (uses global if None)
        timeout: Timeout in seconds
        cwd: Working directory
        capture_output: Capture stdout/stderr
        text: Decode output as text
        check: Raise CalledProcessError on non-zero exit
        **kwargs: Additional arguments to subprocess.run()

    Returns:
        CompletedProcess from subprocess.run()

    Raises:
        subprocess.CalledProcessError: If check=True and exit code != 0
        subprocess.TimeoutExpired: If timeout is exceeded

    Example:
        >>> result = run_with_stats(["git", "status"], timeout=30)
        >>> print(result.returncode)
        0
    """
    if stats_tracker is None:
        stats_tracker = get_global_stats()

    # Build command string for logging
    command_str = " ".join(args)

    # Record start time
    start_time = datetime.now()
    error_msg = None
    result = None

    try:
        # Run subprocess
        result = subprocess.run(
            args,
            timeout=timeout,
            cwd=cwd,
            capture_output=capture_output,
            text=text,
            check=check,
            **kwargs,
        )

        # Record end time
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Build execution record
        record = SubprocessExecutionRecord(
            command=command_str,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            exit_code=result.returncode,
            success=(result.returncode == 0),
            stdout_length=len(result.stdout) if result.stdout else 0,
            stderr_length=len(result.stderr) if result.stderr else 0,
            error=None if result.returncode == 0 else result.stderr[:200] if result.stderr else f"Exit code {result.returncode}",
            cwd=cwd,
            timeout=timeout,
        )

        # Record stats
        stats_tracker.record(record)

        return result

    except subprocess.TimeoutExpired as e:
        # Record timeout as failure
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        record = SubprocessExecutionRecord(
            command=command_str,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            exit_code=-1,  # Special code for timeout
            success=False,
            stdout_length=len(e.stdout) if e.stdout else 0,
            stderr_length=len(e.stderr) if e.stderr else 0,
            error=f"Timeout after {timeout}s",
            cwd=cwd,
            timeout=timeout,
        )
        stats_tracker.record(record)

        # Re-raise timeout
        raise

    except subprocess.CalledProcessError as e:
        # Record CalledProcessError as failure
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        record = SubprocessExecutionRecord(
            command=command_str,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            exit_code=e.returncode,
            success=False,
            stdout_length=len(e.stdout) if e.stdout else 0,
            stderr_length=len(e.stderr) if e.stderr else 0,
            error=e.stderr[:200] if e.stderr else f"Exit code {e.returncode}",
            cwd=cwd,
            timeout=timeout,
        )
        stats_tracker.record(record)

        # Re-raise CalledProcessError
        raise

    except Exception as e:
        # Record generic exception as failure
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        record = SubprocessExecutionRecord(
            command=command_str,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            exit_code=-2,  # Special code for exception
            success=False,
            stdout_length=0,
            stderr_length=0,
            error=str(e),
            cwd=cwd,
            timeout=timeout,
        )
        stats_tracker.record(record)

        # Re-raise exception
        raise
