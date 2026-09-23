"""Run calibration as a bounded Windows child and leave durable evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from src.utils.atomic_write import atomic_write
from src.utils.windows_process import hidden_python_executable, hidden_subprocess_kwargs


def write_state(path: Path, **values) -> None:
    values.update(last_progress_at=time.time())
    atomic_write(path, json.dumps(values, indent=2, sort_keys=True), create_parents=True, fsync=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args, remainder = parser.parse_known_args()
    command = [hidden_python_executable(), str(args.runtime / "scripts/campaign/llm_preflight_calibration.py"), *remainder]
    write_state(args.state, status="RUNNING", stage="calibration", started_at=time.time(), deadline_at=time.time() + args.timeout_seconds)
    child = subprocess.Popen(command, cwd=args.runtime, **hidden_subprocess_kwargs(new_process_group=True))
    deadline = time.monotonic() + args.timeout_seconds
    while child.poll() is None and time.monotonic() < deadline:
        write_state(args.state, status="RUNNING", stage="calibration", child_pid=child.pid, deadline_at=time.time() + max(0, deadline-time.monotonic()))
        time.sleep(5)
    if child.poll() is None:
        subprocess.run(["taskkill.exe", "/PID", str(child.pid), "/T", "/F"], capture_output=True, check=False)
        payload = {"terminal_reason": "timed_out", "timed_out": True, "finished_at": time.time(), "calibration": {"concurrency_ramp": []}}
        atomic_write(args.evidence_output, json.dumps(payload, indent=2), create_parents=True, fsync=True)
        write_state(args.state, status="TIMED_OUT", stage="calibration", child_pid=child.pid)
        return 2
    write_state(args.state, status="COMPLETED" if child.returncode == 0 else "FAILED", stage="calibration", exit_code=child.returncode)
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
