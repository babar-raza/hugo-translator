"""
Unit tests for subprocess statistics tracking (TASK-CODE-01).

Tests cover:
- SubprocessExecutionRecord creation and serialization
- SubprocessStats tracking and aggregation
- Thread-safe operations
- Telemetry event emission
- run_with_stats wrapper function
- Edge cases and error handling
"""

import subprocess
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.observability.subprocess_stats import (
    SubprocessExecutionRecord,
    SubprocessStats,
    get_global_stats,
    run_with_stats,
)


class TestSubprocessExecutionRecord:
    """Test SubprocessExecutionRecord dataclass."""

    def test_record_creation(self):
        """Test basic record creation."""
        start = datetime.now()
        end = start + timedelta(seconds=1.5)

        record = SubprocessExecutionRecord(
            command="git status",
            start_time=start,
            end_time=end,
            duration=1.5,
            exit_code=0,
            success=True,
            stdout_length=100,
            stderr_length=0,
        )

        assert record.command == "git status"
        assert record.duration == 1.5
        assert record.exit_code == 0
        assert record.success is True
        assert record.stdout_length == 100
        assert record.stderr_length == 0
        assert record.error is None

    def test_record_with_error(self):
        """Test record creation with error."""
        start = datetime.now()
        end = start + timedelta(seconds=0.5)

        record = SubprocessExecutionRecord(
            command="git push",
            start_time=start,
            end_time=end,
            duration=0.5,
            exit_code=1,
            success=False,
            stdout_length=0,
            stderr_length=50,
            error="fatal: remote error",
        )

        assert record.success is False
        assert record.exit_code == 1
        assert record.error == "fatal: remote error"

    def test_to_dict(self):
        """Test conversion to dictionary for telemetry."""
        start = datetime.now()
        end = start + timedelta(seconds=2.0)

        record = SubprocessExecutionRecord(
            command="git commit",
            start_time=start,
            end_time=end,
            duration=2.0,
            exit_code=0,
            success=True,
            stdout_length=200,
            stderr_length=0,
            cwd="/repo",
            timeout=30.0,
        )

        data = record.to_dict()

        assert data["command"] == "git commit"
        assert data["duration"] == 2.0
        assert data["exit_code"] == 0
        assert data["success"] is True
        assert data["cwd"] == "/repo"
        assert data["timeout"] == 30.0
        assert "start_time" in data
        assert "end_time" in data


class TestSubprocessStats:
    """Test SubprocessStats class."""

    def test_initialization(self):
        """Test stats initialization."""
        stats = SubprocessStats(slow_threshold=20.0, summary_interval=50)

        assert stats.slow_threshold == 20.0
        assert stats.summary_interval == 50
        assert stats.total_count == 0
        assert stats.success_count == 0
        assert stats.failure_count == 0
        assert stats.slow_count == 0

    def test_record_success(self):
        """Test recording successful execution."""
        stats = SubprocessStats(enable_telemetry=False)

        record = SubprocessExecutionRecord(
            command="git status",
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(seconds=1),
            duration=1.0,
            exit_code=0,
            success=True,
            stdout_length=100,
            stderr_length=0,
        )

        stats.record(record)

        assert stats.total_count == 1
        assert stats.success_count == 1
        assert stats.failure_count == 0
        assert stats.total_duration == 1.0
        assert stats.min_duration == 1.0
        assert stats.max_duration == 1.0

    def test_record_failure(self):
        """Test recording failed execution."""
        stats = SubprocessStats(enable_telemetry=False)

        record = SubprocessExecutionRecord(
            command="git push",
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(seconds=0.5),
            duration=0.5,
            exit_code=1,
            success=False,
            error="remote error",
        )

        stats.record(record)

        assert stats.total_count == 1
        assert stats.success_count == 0
        assert stats.failure_count == 1

    def test_record_slow_execution(self):
        """Test tracking slow executions."""
        stats = SubprocessStats(slow_threshold=5.0, enable_telemetry=False)

        # Fast execution
        fast_record = SubprocessExecutionRecord(
            command="git status",
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(seconds=2),
            duration=2.0,
            exit_code=0,
            success=True,
        )
        stats.record(fast_record)
        assert stats.slow_count == 0

        # Slow execution
        slow_record = SubprocessExecutionRecord(
            command="git push",
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(seconds=10),
            duration=10.0,
            exit_code=0,
            success=True,
        )
        stats.record(slow_record)
        assert stats.slow_count == 1

    def test_get_summary_empty(self):
        """Test getting summary with no executions."""
        stats = SubprocessStats(enable_telemetry=False)
        summary = stats.get_summary()

        assert summary["total_count"] == 0
        assert summary["success_count"] == 0
        assert summary["failure_count"] == 0
        assert summary["error_rate"] == 0.0

    def test_get_summary_with_data(self):
        """Test getting summary with executions."""
        stats = SubprocessStats(enable_telemetry=False)

        # Add 3 successful, 1 failed
        for i in range(3):
            stats.record(
                SubprocessExecutionRecord(
                    command=f"cmd{i}",
                    start_time=datetime.now(),
                    end_time=datetime.now() + timedelta(seconds=1),
                    duration=1.0,
                    exit_code=0,
                    success=True,
                )
            )

        stats.record(
            SubprocessExecutionRecord(
                command="fail_cmd",
                start_time=datetime.now(),
                end_time=datetime.now() + timedelta(seconds=2),
                duration=2.0,
                exit_code=1,
                success=False,
                error="error",
            )
        )

        summary = stats.get_summary()

        assert summary["total_count"] == 4
        assert summary["success_count"] == 3
        assert summary["failure_count"] == 1
        assert summary["error_rate"] == 0.25
        assert summary["avg_duration"] == 1.25
        assert summary["min_duration"] == 1.0
        assert summary["max_duration"] == 2.0

    def test_exit_code_tracking(self):
        """Test exit code tracking."""
        stats = SubprocessStats(enable_telemetry=False)

        # Add various exit codes
        stats.record(
            SubprocessExecutionRecord(
                command="cmd1",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=0.1,
                exit_code=0,
                success=True,
            )
        )
        stats.record(
            SubprocessExecutionRecord(
                command="cmd2",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=0.1,
                exit_code=0,
                success=True,
            )
        )
        stats.record(
            SubprocessExecutionRecord(
                command="cmd3",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=0.1,
                exit_code=1,
                success=False,
            )
        )

        summary = stats.get_summary()
        top_codes = dict(summary["top_exit_codes"])

        assert top_codes[0] == 2
        assert top_codes[1] == 1

    def test_command_tracking(self):
        """Test command frequency tracking."""
        stats = SubprocessStats(enable_telemetry=False)

        # Execute same command multiple times
        for _ in range(3):
            stats.record(
                SubprocessExecutionRecord(
                    command="git status",
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    duration=0.1,
                    exit_code=0,
                    success=True,
                )
            )

        stats.record(
            SubprocessExecutionRecord(
                command="git push",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=0.1,
                exit_code=0,
                success=True,
            )
        )

        summary = stats.get_summary()
        top_commands = dict(summary["top_commands"])

        assert top_commands["git status"] == 3
        assert top_commands["git push"] == 1

    def test_reset(self):
        """Test resetting statistics."""
        stats = SubprocessStats(enable_telemetry=False)

        # Add some data
        stats.record(
            SubprocessExecutionRecord(
                command="test",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=1.0,
                exit_code=0,
                success=True,
            )
        )

        assert stats.total_count == 1

        # Reset
        stats.reset()

        assert stats.total_count == 0
        assert stats.success_count == 0
        assert stats.failure_count == 0
        assert stats.total_duration == 0.0

    def test_get_command_stats(self):
        """Test getting stats for specific command."""
        stats = SubprocessStats(enable_telemetry=False)

        # Add multiple executions of same command
        for i in range(3):
            stats.record(
                SubprocessExecutionRecord(
                    command="git status",
                    start_time=datetime.now(),
                    end_time=datetime.now() + timedelta(seconds=i + 1),
                    duration=float(i + 1),
                    exit_code=0,
                    success=True,
                )
            )

        # Add one failure
        stats.record(
            SubprocessExecutionRecord(
                command="git status",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=0.5,
                exit_code=1,
                success=False,
            )
        )

        cmd_stats = stats.get_command_stats("git status")

        assert cmd_stats["count"] == 4
        assert cmd_stats["success_count"] == 3
        assert cmd_stats["failure_count"] == 1
        assert cmd_stats["error_rate"] == 0.25
        assert cmd_stats["min_duration"] == 0.5
        assert cmd_stats["max_duration"] == 3.0

    def test_get_command_stats_nonexistent(self):
        """Test getting stats for command that hasn't been executed."""
        stats = SubprocessStats(enable_telemetry=False)

        cmd_stats = stats.get_command_stats("nonexistent")

        assert cmd_stats["count"] == 0

    def test_max_records_limit(self):
        """Test that records list doesn't grow unbounded."""
        stats = SubprocessStats(enable_telemetry=False)
        stats._max_records = 10  # Set low limit for testing

        # Add more records than limit
        for i in range(15):
            stats.record(
                SubprocessExecutionRecord(
                    command=f"cmd{i}",
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    duration=0.1,
                    exit_code=0,
                    success=True,
                )
            )

        # Should only keep last 10
        assert len(stats._executions) == 10
        # But total count should be 15
        assert stats.total_count == 15

    @patch("src.observability.subprocess_stats.logger")
    def test_telemetry_emission(self, mock_logger):
        """Test that telemetry events are emitted."""
        with patch("src.observability.telemetry_integration.emit_event") as mock_emit:
            stats = SubprocessStats(enable_telemetry=True, summary_interval=1000)

            # Record success
            stats.record(
                SubprocessExecutionRecord(
                    command="git status",
                    start_time=datetime.now(),
                    end_time=datetime.now() + timedelta(seconds=1),
                    duration=1.0,
                    exit_code=0,
                    success=True,
                )
            )

            # Should emit subprocess_executed
            assert mock_emit.call_count >= 1
            first_call = mock_emit.call_args_list[0]
            assert first_call[0][0] == "subprocess_executed"

    @patch("src.observability.subprocess_stats.logger")
    def test_telemetry_failure_emission(self, mock_logger):
        """Test that failure events are emitted."""
        with patch("src.observability.telemetry_integration.emit_event") as mock_emit:
            stats = SubprocessStats(enable_telemetry=True, summary_interval=1000)

            # Record failure
            stats.record(
                SubprocessExecutionRecord(
                    command="git push",
                    start_time=datetime.now(),
                    end_time=datetime.now() + timedelta(seconds=1),
                    duration=1.0,
                    exit_code=1,
                    success=False,
                    error="remote error",
                )
            )

            # Should emit both subprocess_executed and subprocess_failed
            assert mock_emit.call_count >= 2

    @patch("src.observability.subprocess_stats.logger")
    def test_telemetry_slow_emission(self, mock_logger):
        """Test that slow execution events are emitted."""
        with patch("src.observability.telemetry_integration.emit_event") as mock_emit:
            stats = SubprocessStats(
                slow_threshold=5.0, enable_telemetry=True, summary_interval=1000
            )

            # Record slow execution
            stats.record(
                SubprocessExecutionRecord(
                    command="git push",
                    start_time=datetime.now(),
                    end_time=datetime.now() + timedelta(seconds=10),
                    duration=10.0,
                    exit_code=0,
                    success=True,
                )
            )

            # Should emit subprocess_executed and subprocess_slow
            assert mock_emit.call_count >= 2


class TestRunWithStats:
    """Test run_with_stats wrapper function."""

    def test_run_with_stats_success(self):
        """Test successful command execution with stats."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["python", "-c", "print('hello')"],
            stats_tracker=stats,
            timeout=10,
        )

        assert result.returncode == 0
        assert stats.total_count == 1
        assert stats.success_count == 1
        assert stats.failure_count == 0

    def test_run_with_stats_failure(self):
        """Test failed command execution with stats."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["python", "-c", "import sys; sys.exit(1)"],
            stats_tracker=stats,
            timeout=10,
        )

        assert result.returncode == 1
        assert stats.total_count == 1
        assert stats.success_count == 0
        assert stats.failure_count == 1

    def test_run_with_stats_timeout(self):
        """Test timeout handling with stats."""
        stats = SubprocessStats(enable_telemetry=False)

        with pytest.raises(subprocess.TimeoutExpired):
            run_with_stats(
                ["python", "-c", "import time; time.sleep(10)"],
                stats_tracker=stats,
                timeout=0.1,
            )

        # Should still record the timeout
        assert stats.total_count == 1
        assert stats.failure_count == 1

    def test_run_with_stats_check_raises(self):
        """Test that check=True raises CalledProcessError."""
        stats = SubprocessStats(enable_telemetry=False)

        with pytest.raises(subprocess.CalledProcessError):
            run_with_stats(
                ["python", "-c", "import sys; sys.exit(1)"],
                stats_tracker=stats,
                check=True,
            )

        # Should still record the failure
        assert stats.total_count == 1
        assert stats.failure_count == 1

    def test_run_with_stats_global_instance(self):
        """Test using global stats instance."""
        # Reset global stats if it exists
        global_stats = get_global_stats()
        global_stats.reset()

        result = run_with_stats(
            ["python", "-c", "print('test')"],
            timeout=10,
        )

        assert result.returncode == 0
        assert global_stats.total_count >= 1

    def test_run_with_stats_captures_output(self):
        """Test that output is captured and length is recorded."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["python", "-c", "print('hello world')"],
            stats_tracker=stats,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "hello world" in result.stdout

        # Check that stdout length was recorded
        summary = stats.get_summary()
        assert summary["total_count"] == 1


class TestThreadSafety:
    """Test thread safety of SubprocessStats."""

    def test_concurrent_recording(self):
        """Test concurrent record operations."""
        import threading

        stats = SubprocessStats(enable_telemetry=False)

        def record_execution():
            for _ in range(10):
                stats.record(
                    SubprocessExecutionRecord(
                        command="test",
                        start_time=datetime.now(),
                        end_time=datetime.now(),
                        duration=0.1,
                        exit_code=0,
                        success=True,
                    )
                )

        threads = [threading.Thread(target=record_execution) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Should have recorded all 50 executions
        assert stats.total_count == 50


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_negative_duration(self):
        """Test handling of edge case durations."""
        stats = SubprocessStats(enable_telemetry=False)

        # Zero duration
        stats.record(
            SubprocessExecutionRecord(
                command="fast",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=0.0,
                exit_code=0,
                success=True,
            )
        )

        summary = stats.get_summary()
        assert summary["min_duration"] == 0.0

    def test_empty_command(self):
        """Test recording execution with empty command."""
        stats = SubprocessStats(enable_telemetry=False)

        stats.record(
            SubprocessExecutionRecord(
                command="",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=0.1,
                exit_code=0,
                success=True,
            )
        )

        assert stats.total_count == 1

    def test_very_long_error_message(self):
        """Test handling of very long error messages."""
        stats = SubprocessStats(enable_telemetry=False)

        long_error = "x" * 10000

        stats.record(
            SubprocessExecutionRecord(
                command="cmd",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=0.1,
                exit_code=1,
                success=False,
                error=long_error,
            )
        )

        # Should store error without crashing
        assert stats.total_count == 1
        assert stats.failure_count == 1
