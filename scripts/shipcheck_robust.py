"""
Shipcheck runner for production-readiness gating - ROBUST VERSION

Key improvements:
- Timeouts for all subprocess calls (prevents hanging)
- Streaming output to files (prevents deadlocks)
- PYTHONPATH setup (ensures repo imports work)
- Graceful timeout handling with triage entries
- Always writes summary/results/triage even on failure

Writes all outputs under reports/shipcheck/{RUN_ID}/.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import subprocess
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _ensure_dirs(run_root: Path) -> Dict[str, Path]:
    logs_dir = run_root / "logs"
    evidence_dir = run_root / "evidence"
    run_root.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return {"logs": logs_dir, "evidence": evidence_dir}


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_command_streaming(
    cmd: List[str],
    log_path: Path,
    env: Optional[Dict[str, str]] = None,
    timeout_sec: int = 180,
) -> Dict[str, Any]:
    """
    Run command with streaming output to file and timeout.

    Prevents deadlocks by writing stdout/stderr incrementally.
    Kills process on timeout and marks as FAIL.
    """
    start = time.perf_counter()

    # Write command header
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"$ {' '.join(cmd)}\n")
        f.write(f"timeout={timeout_sec}s\n\n")

    try:
        # Start process with piped outputs
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,  # Line buffered
        )

        # Stream output to file
        timed_out = False
        exit_code = None

        def stream_output():
            nonlocal exit_code
            with open(log_path, "a", encoding="utf-8") as f:
                for line in process.stdout:
                    f.write(line)
                    f.flush()
            exit_code = process.wait()

        thread = threading.Thread(target=stream_output)
        thread.start()
        thread.join(timeout=timeout_sec)

        if thread.is_alive():
            # Timeout occurred
            timed_out = True
            process.kill()
            thread.join(timeout=5)

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n*** TIMEOUT after {timeout_sec}s ***\n")
                f.write(f"Process killed.\n")
                f.write(f"\nReproduction command:\n")
                f.write(f"{' '.join(cmd)}\n")

            exit_code = 124  # Standard timeout exit code

        duration = time.perf_counter() - start

        # Append footer
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\nexit_code={exit_code}\n")
            f.write(f"duration={duration:.3f}s\n")
            if timed_out:
                f.write(f"status=TIMEOUT\n")

        return {
            "exit_code": exit_code,
            "duration_sec": round(duration, 3),
            "log": str(log_path),
            "timed_out": timed_out,
        }

    except Exception as exc:
        duration = time.perf_counter() - start
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n*** EXCEPTION ***\n")
            f.write(f"{type(exc).__name__}: {exc}\n")
            f.write(f"\nexit_code=1\n")
            f.write(f"duration={duration:.3f}s\n")

        return {
            "exit_code": 1,
            "duration_sec": round(duration, 3),
            "log": str(log_path),
            "error": str(exc),
        }


def _capture_env(log_path: Path) -> Dict[str, Any]:
    start = time.perf_counter()
    lines = [
        f"python_executable={sys.executable}",
        f"python_version={sys.version}",
        f"platform={platform.platform()}",
        f"cwd={os.getcwd()}",
        f"PYTHONPATH={os.environ.get('PYTHONPATH', 'NOT SET')}",
    ]
    _write_text(log_path, "\n".join(lines) + "\n")
    duration = time.perf_counter() - start
    return {"exit_code": 0, "duration_sec": round(duration, 3), "log": str(log_path)}


def _import_check(log_path: Path) -> Dict[str, Any]:
    start = time.perf_counter()
    errors: List[str] = []
    modules = ["src.cli", "src.translation_engine.engine"]
    for module_name in modules:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")

    status_lines = ["import_check=pass"]
    if errors:
        status_lines = ["import_check=fail"] + errors

    _write_text(log_path, "\n".join(status_lines) + "\n")
    duration = time.perf_counter() - start
    exit_code = 1 if errors else 0
    return {
        "exit_code": exit_code,
        "duration_sec": round(duration, 3),
        "log": str(log_path),
        "errors": errors,
    }


def _cli_help_checks(log_path: Path, timeout_sec: int = 30) -> Dict[str, Any]:
    """Check CLI help commands with timeout."""
    cmd_1 = [sys.executable, "-m", "src.cli", "--help"]
    cmd_2 = [sys.executable, "-m", "src.cli", "translate", "--help"]

    start = time.perf_counter()

    try:
        # Run both commands with timeout
        result_1 = subprocess.run(
            cmd_1,
            capture_output=True,
            text=True,
            timeout=timeout_sec
        )
        result_2 = subprocess.run(
            cmd_2,
            capture_output=True,
            text=True,
            timeout=timeout_sec
        )

        output = [
            f"$ {' '.join(cmd_1)}",
            f"exit_code={result_1.returncode}",
            result_1.stdout.rstrip(),
        ]
        if result_1.stderr:
            output.append(result_1.stderr.rstrip())
        output.append("")

        output.append(f"$ {' '.join(cmd_2)}")
        output.append(f"exit_code={result_2.returncode}")
        output.append(result_2.stdout.rstrip())
        if result_2.stderr:
            output.append(result_2.stderr.rstrip())

        _write_text(log_path, "\n".join(output) + "\n")
        duration = time.perf_counter() - start
        exit_code = 1 if result_1.returncode != 0 or result_2.returncode != 0 else 0

        return {
            "exit_code": exit_code,
            "duration_sec": round(duration, 3),
            "log": str(log_path),
        }

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        _write_text(
            log_path,
            f"*** TIMEOUT after {timeout_sec}s ***\n\nCommands:\n{' '.join(cmd_1)}\n{' '.join(cmd_2)}\n"
        )
        return {
            "exit_code": 124,
            "duration_sec": round(duration, 3),
            "log": str(log_path),
            "timed_out": True,
        }


def _build_summary(
    run_root: Path,
    run_id: str,
    mode: str,
    started_at: str,
    finished_at: str,
    steps: List[Dict[str, Any]],
    success: bool,
) -> str:
    lines = [
        "# Shipcheck Summary (ROBUST)",
        f"- Run ID: {run_id}",
        f"- Mode: {mode}",
        f"- Started: {started_at}",
        f"- Finished: {finished_at}",
        f"- Result: {'PASS' if success else 'FAIL'}",
        "",
        "## Steps",
    ]
    for step in steps:
        status = step["status"].upper()
        timeout_note = " (TIMEOUT)" if step.get("timed_out") else ""
        lines.append(f"- {step['name']}: {status}{timeout_note} ({step['log']})")

    lines += [
        "",
        "## Artifacts",
        f"- {run_root / 'summary.md'}",
        f"- {run_root / 'results.json'}",
        f"- {run_root / 'triage.md'}",
    ]
    return "\n".join(lines) + "\n"


def _write_triage(triage_path: Path, steps: List[Dict[str, Any]]) -> None:
    lines = ["# Triage", ""]
    failures = [step for step in steps if step["status"] == "fail"]
    if not failures:
        lines.append("- P0: none")
        lines.append("- P1: none")
        _write_text(triage_path, "\n".join(lines) + "\n")
        return

    for step in failures:
        severity = step.get("severity", "P0")
        message = step.get("message", "See log for details.")

        if step.get("timed_out"):
            message += f" - TIMEOUT (killed after {step.get('timeout_sec', 'unknown')}s)"
            message += f" - Reproduce: see {step['log']}"

        lines.append(f"- {severity}: {step['name']} failed - {message}")

    _write_text(triage_path, "\n".join(lines) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run shipcheck gates (ROBUST).")
    parser.add_argument("--run-id", help="Optional run ID (YYYYMMDD-HHMMSS)")
    parser.add_argument(
        "--run-root",
        default="reports/shipcheck",
        help="Base directory for shipcheck runs",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full checks (includes additional pytest passes)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Explicitly run quick mode (default)",
    )
    args = parser.parse_args(argv)

    run_id = args.run_id or _now_run_id()
    run_root = Path(args.run_root) / run_id
    dirs = _ensure_dirs(run_root)

    # Ensure PYTHONPATH includes repo root
    repo_root = Path(__file__).parent.parent.resolve()
    test_env = os.environ.copy()
    pythonpath = str(repo_root)
    if "PYTHONPATH" in test_env:
        pythonpath = pythonpath + os.pathsep + test_env["PYTHONPATH"]
    test_env["PYTHONPATH"] = pythonpath
    test_env["SHIPCHECK_RUN_ROOT"] = str(run_root)
    test_env["SHIPCHECK_RUN_ID"] = run_id
    test_env["SHIPCHECK_MODE"] = "full" if args.full else "quick"

    started_at = datetime.now().isoformat()
    steps: List[Dict[str, Any]] = []

    # Step 1: Capture environment
    env_log = dirs["logs"] / "env.txt"
    env_result = _capture_env(env_log)
    steps.append({
        "name": "env_capture",
        "status": "pass",
        "log": str(env_log),
        "duration_sec": env_result["duration_sec"],
        "severity": "P1",
    })

    # Step 2: Import check
    import_log = dirs["logs"] / "import_check.txt"
    import_result = _import_check(import_log)
    steps.append({
        "name": "import_check",
        "status": "pass" if import_result["exit_code"] == 0 else "fail",
        "log": str(import_log),
        "duration_sec": import_result["duration_sec"],
        "severity": "P0",
        "message": "; ".join(import_result.get("errors", [])) if import_result["exit_code"] else "",
    })

    # Step 3: CLI help checks
    cli_log = dirs["logs"] / "cli_help.txt"
    cli_result = _cli_help_checks(cli_log, timeout_sec=30)
    steps.append({
        "name": "cli_help",
        "status": "pass" if cli_result["exit_code"] == 0 else "fail",
        "log": str(cli_log),
        "duration_sec": cli_result["duration_sec"],
        "severity": "P1",
        "timed_out": cli_result.get("timed_out", False),
        "timeout_sec": 30,
    })

    # Step 4: Pytest quick (with timeout)
    pytest_log = dirs["logs"] / "pytest_quick.txt"
    pytest_timeout = 600 if args.full else 180  # 10 min full, 3 min quick
    pytest_result = _run_command_streaming(
        [sys.executable, "-m", "pytest", "-q", "tests/contract/"],
        pytest_log,
        env=test_env,
        timeout_sec=pytest_timeout,
    )
    steps.append({
        "name": "pytest_quick",
        "status": "pass" if pytest_result["exit_code"] == 0 else "fail",
        "log": str(pytest_log),
        "duration_sec": pytest_result["duration_sec"],
        "severity": "P0",
        "timed_out": pytest_result.get("timed_out", False),
        "timeout_sec": pytest_timeout,
    })

    # Step 5: Pytest E2E (full mode only)
    if args.full:
        pytest_full_log = dirs["logs"] / "pytest_e2e.txt"
        pytest_full_result = _run_command_streaming(
            [sys.executable, "-m", "pytest", "-q", "-m", "e2e"],
            pytest_full_log,
            env=test_env,
            timeout_sec=600,
        )
        steps.append({
            "name": "pytest_e2e",
            "status": "pass" if pytest_full_result["exit_code"] == 0 else "fail",
            "log": str(pytest_full_log),
            "duration_sec": pytest_full_result["duration_sec"],
            "severity": "P0",
            "timed_out": pytest_full_result.get("timed_out", False),
            "timeout_sec": 600,
        })

    finished_at = datetime.now().isoformat()
    success = all(step["status"] == "pass" for step in steps)

    # Always write results, even on failure
    results = {
        "run_id": run_id,
        "run_root": str(run_root),
        "mode": "full" if args.full else "quick",
        "started_at": started_at,
        "finished_at": finished_at,
        "success": success,
        "steps": steps,
        "improvements": [
            "Timeouts on all subprocess calls",
            "Streaming output to files",
            "PYTHONPATH setup for repo imports",
            "Graceful timeout handling",
            "Always writes artifacts",
        ],
    }
    _write_text(run_root / "results.json", json.dumps(results, indent=2) + "\n")

    summary = _build_summary(run_root, run_id, results["mode"], started_at, finished_at, steps, success)
    _write_text(run_root / "summary.md", summary)

    _write_triage(run_root / "triage.md", steps)

    print(f"\nShipcheck completed: {run_root}")
    print(f"Result: {'PASS' if success else 'FAIL'}")
    print(f"Summary: {run_root / 'summary.md'}")

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
