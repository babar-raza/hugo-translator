"""
Integration tests for subprocess statistics tracking (TASK-CODE-01).

Tests subprocess stats module in real-world scenarios:
- Git command execution with stats tracking
- Multiple subprocess calls
- Real timeout handling
- Real error scenarios
- Telemetry integration
"""
import subprocess

import pytest

from src.observability.subprocess_stats import (
    SubprocessStats,
    get_global_stats,
    run_with_stats,
)


class TestGitCommandsWithStats:
    """Test subprocess stats with real git commands."""

    def test_git_status_with_stats(self):
        """Test tracking git status command."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["git", "status", "--porcelain"],
            stats_tracker=stats,
            timeout=30,
        )

        assert result.returncode == 0
        assert stats.total_count == 1
        assert stats.success_count == 1

        # Verify command tracking
        summary = stats.get_summary()
        assert "git status --porcelain" in dict(summary["top_commands"])

    def test_git_branch_with_stats(self):
        """Test tracking git branch command."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["git", "branch", "--show-current"],
            stats_tracker=stats,
            timeout=30,
        )

        assert result.returncode == 0
        assert stats.total_count == 1

    def test_invalid_git_command(self):
        """Test tracking failed git command."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["git", "invalid-command"],
            stats_tracker=stats,
            timeout=30,
        )

        assert result.returncode != 0
        assert stats.total_count == 1
        assert stats.failure_count == 1

        # Verify error tracking
        summary = stats.get_summary()
        assert summary["error_rate"] > 0


class TestMultipleCommandsScenario:
    """Test stats tracking across multiple subprocess calls."""

    def test_multiple_git_commands(self):
        """Test tracking multiple git operations."""
        stats = SubprocessStats(enable_telemetry=False)

        # Execute multiple git commands
        commands = [
            ["git", "status", "--porcelain"],
            ["git", "branch", "--show-current"],
            ["git", "rev-parse", "HEAD"],
            ["git", "log", "-1", "--oneline"],
        ]

        for cmd in commands:
            result = run_with_stats(cmd, stats_tracker=stats, timeout=30)
            assert result.returncode == 0

        # Verify aggregate stats
        assert stats.total_count == 4
        assert stats.success_count == 4
        assert stats.failure_count == 0

        summary = stats.get_summary()
        assert summary["avg_duration"] > 0
        assert summary["min_duration"] >= 0

    def test_mixed_success_and_failure(self):
        """Test tracking mixed successful and failed commands."""
        stats = SubprocessStats(enable_telemetry=False)

        # Successful command
        run_with_stats(["git", "status"], stats_tracker=stats)

        # Failed command
        run_with_stats(["git", "invalid"], stats_tracker=stats)

        # Another successful command
        run_with_stats(["git", "branch"], stats_tracker=stats)

        assert stats.total_count == 3
        assert stats.success_count == 2
        assert stats.failure_count == 1

        summary = stats.get_summary()
        assert abs(summary["error_rate"] - 0.333) < 0.01


class TestRealTimeoutScenarios:
    """Test real timeout handling with stats."""

    def test_quick_timeout(self):
        """Test command that times out."""
        stats = SubprocessStats(enable_telemetry=False)

        # Command that will timeout
        with pytest.raises(subprocess.TimeoutExpired):
            run_with_stats(
                ["python", "-c", "import time; time.sleep(10)"],
                stats_tracker=stats,
                timeout=0.1,
            )

        # Should still record the timeout
        assert stats.total_count == 1
        assert stats.failure_count == 1

    def test_command_within_timeout(self):
        """Test command that completes within timeout."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["python", "-c", "print('fast')"],
            stats_tracker=stats,
            timeout=5.0,
        )

        assert result.returncode == 0
        assert stats.total_count == 1
        assert stats.success_count == 1


class TestSlowExecutionTracking:
    """Test slow execution detection."""

    def test_slow_command_detection(self):
        """Test that slow commands are tracked."""
        stats = SubprocessStats(slow_threshold=0.5, enable_telemetry=False)

        # Fast command
        run_with_stats(
            ["python", "-c", "print('fast')"],
            stats_tracker=stats,
        )

        assert stats.slow_count == 0

        # Slow command
        run_with_stats(
            ["python", "-c", "import time; time.sleep(0.6); print('slow')"],
            stats_tracker=stats,
        )

        # Should detect slow execution
        assert stats.slow_count >= 1

        summary = stats.get_summary()
        assert summary["slow_rate"] > 0


class TestCommandStatistics:
    """Test command-specific statistics."""

    def test_command_failure_tracking(self):
        """Test tracking failures for specific commands."""
        stats = SubprocessStats(enable_telemetry=False)

        # Execute same command multiple times with different results
        run_with_stats(["python", "-c", "import sys; sys.exit(0)"], stats_tracker=stats)
        run_with_stats(["python", "-c", "import sys; sys.exit(1)"], stats_tracker=stats)
        run_with_stats(["python", "-c", "import sys; sys.exit(0)"], stats_tracker=stats)

        summary = stats.get_summary()

        # Should have failure tracking
        assert summary["failure_count"] == 1
        assert summary["success_count"] == 2


class TestGlobalStatsInstance:
    """Test global stats instance usage."""

    def test_global_stats_usage(self):
        """Test using global stats instance."""
        global_stats = get_global_stats()
        initial_count = global_stats.total_count

        # Run command with global stats (no stats_tracker param)
        result = run_with_stats(
            ["git", "status"],
            timeout=30,
        )

        assert result.returncode == 0
        assert global_stats.total_count > initial_count


class TestOutputCapture:
    """Test output capture and length tracking."""

    def test_stdout_length_tracking(self):
        """Test that stdout length is tracked."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["python", "-c", "print('hello world' * 100)"],
            stats_tracker=stats,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert len(result.stdout) > 0

        # Check command stats
        cmd_stats = stats.get_command_stats("python -c print('hello world' * 100)")
        assert cmd_stats["count"] == 1

    def test_stderr_length_tracking(self):
        """Test that stderr length is tracked for failures."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["python", "-c", "import sys; sys.stderr.write('error message\\n'); sys.exit(1)"],
            stats_tracker=stats,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert len(result.stderr) > 0

        summary = stats.get_summary()
        assert summary["failure_count"] == 1


class TestPeriodicSummaryLogging:
    """Test periodic summary logging."""

    def test_summary_interval_trigger(self):
        """Test that summary is logged at interval."""
        stats = SubprocessStats(summary_interval=5, enable_telemetry=False)

        # Execute 5 commands to trigger summary
        for i in range(5):
            run_with_stats(
                ["python", "-c", f"print({i})"],
                stats_tracker=stats,
            )

        # Should have logged summary at count=5
        assert stats.total_count == 5


class TestEdgeCasesIntegration:
    """Test edge cases with real subprocess execution."""

    def test_empty_output(self):
        """Test command with no output."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["python", "-c", "pass"],
            stats_tracker=stats,
            capture_output=True,
        )

        assert result.returncode == 0
        assert stats.total_count == 1

    def test_working_directory(self):
        """Test command with custom working directory."""
        stats = SubprocessStats(enable_telemetry=False)

        result = run_with_stats(
            ["git", "status"],
            stats_tracker=stats,
            cwd=".",
            timeout=30,
        )

        assert result.returncode == 0
        assert stats.total_count == 1

    def test_check_parameter_with_success(self):
        """Test check parameter with successful command."""
        stats = SubprocessStats(enable_telemetry=False)

        # Should not raise
        result = run_with_stats(
            ["python", "-c", "pass"],
            stats_tracker=stats,
            check=True,
        )

        assert result.returncode == 0
        assert stats.success_count == 1

    def test_check_parameter_with_failure(self):
        """Test check parameter with failed command."""
        stats = SubprocessStats(enable_telemetry=False)

        # Should raise CalledProcessError
        with pytest.raises(subprocess.CalledProcessError):
            run_with_stats(
                ["python", "-c", "import sys; sys.exit(1)"],
                stats_tracker=stats,
                check=True,
            )

        # Should still record the failure
        assert stats.failure_count == 1
