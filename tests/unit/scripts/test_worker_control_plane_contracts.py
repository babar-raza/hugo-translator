"""
Contract tests for worker control-plane scripts.
"""

import re
from pathlib import Path


def test_scheduler_setup_includes_autonomous_verification_task():
    """Scheduler script must register verification task and verify all 4 tasks."""
    script = Path("scripts/ops/setup_task_scheduler.ps1").read_text(encoding="utf-8")

    assert "[4/4] Creating task: HugoTranslator-AutonomousVerification" in script
    assert '-TaskName "HugoTranslator-AutonomousVerification"' in script
    assert '"HugoTranslator-AutonomousVerification"' in script
    assert "$verifiedCount -eq $expectedTasks.Count" in script


def test_health_check_reports_auditable_provenance_and_avoids_pid_collision():
    """Health check script must expose provenance fields and avoid read-only $PID assignment."""
    script = Path("scripts/ops/check_worker_health.ps1").read_text(encoding="utf-8")

    assert "last_success_ts" in script
    assert "last_error_ts" in script
    assert "log_path" in script
    assert "verification_worker" in script
    assert "Resolve-LogPath" in script
    assert "ConsoleLogPath" in script
    assert "hugo-translator.ndjson" in script

    # PowerShell variable names are case-insensitive; assigning to $pid collides with read-only $PID.
    assert not re.search(r"^\s*\$pid\s*=", script, flags=re.IGNORECASE | re.MULTILINE)
