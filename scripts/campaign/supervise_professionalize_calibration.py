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
    # pythonw.exe (a GUI-subsystem executable, used here to suppress console
    # flashes) does not reliably inherit a console parent's stdio handles.
    # Without an explicit redirect, the child's first print() blocks forever
    # on an unusable stdout handle -- reproduced directly: the same workload
    # completes normally with this redirect in place, and hangs from the
    # very first line without it. This was silent for every past run: no
    # error, no output, just an indefinite hang until the timeout kill.
    child_log_path = args.evidence_output.with_suffix(".child-log.txt")
    child_log_path.parent.mkdir(parents=True, exist_ok=True)
    write_state(args.state, status="RUNNING", stage="calibration", started_at=time.time(), deadline_at=time.time() + args.timeout_seconds)
    with child_log_path.open("w", encoding="utf-8") as child_log:
        child = subprocess.Popen(
            command,
            cwd=args.runtime,
            stdout=child_log,
            stderr=subprocess.STDOUT,
            **hidden_subprocess_kwargs(new_process_group=True),
        )
        deadline = time.monotonic() + args.timeout_seconds
        while child.poll() is None and time.monotonic() < deadline:
            write_state(args.state, status="RUNNING", stage="calibration", child_pid=child.pid, child_log=str(child_log_path), deadline_at=time.time() + max(0, deadline-time.monotonic()))
            time.sleep(5)
        if child.poll() is None:
            subprocess.run(["taskkill.exe", "/PID", str(child.pid), "/T", "/F"], capture_output=True, check=False)
            payload = {
                "terminal_reason": "timed_out",
                "timed_out": True,
                "finished_at": time.time(),
                "child_log": str(child_log_path),
            }
            atomic_write(args.evidence_output, json.dumps(payload, indent=2), create_parents=True, fsync=True)
            write_state(args.state, status="TIMED_OUT", stage="calibration", child_pid=child.pid, child_log=str(child_log_path))
            return 2
    write_state(args.state, status="COMPLETED" if child.returncode == 0 else "FAILED", stage="calibration", exit_code=child.returncode, child_log=str(child_log_path))
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
