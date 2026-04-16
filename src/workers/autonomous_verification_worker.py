"""
Autonomous Verification Worker.

Runs scheduled verification passes that validate baseline project readiness and
produces auditable lifecycle state for scheduler/health tooling.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from src.observability.worker_telemetry import (
    complete_worker_run,
    emit_worker_event,
    start_worker_run,
)
from src.workers.window_scheduler import ScheduleConfig, WindowScheduler
from src.workers.worker_state import record_worker_state

logger = logging.getLogger(__name__)


@dataclass
class AutonomousVerificationWorkerConfig:
    """Configuration for the autonomous verification worker."""

    config_root: str = "config/"
    mode: str = "oneshot"
    runs_per_day: int = 4
    window_start: str = "08:00"
    window_end: str = "23:00"
    timezone: str = "America/Los_Angeles"
    jitter_minutes: int = 15

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "AutonomousVerificationWorkerConfig":
        """Create worker config from CLI arguments."""
        return cls(
            config_root=args.config_root,
            mode=args.mode,
            runs_per_day=args.runs_per_day,
            window_start=args.window_start,
            window_end=args.window_end,
            timezone=args.timezone,
            jitter_minutes=args.jitter_minutes,
        )


class AutonomousVerificationWorker:
    """Scheduler-friendly verification worker with durable state records."""

    _worker_id = "verification_worker"
    _worker_log_path = "data/logs/verification_worker.log"

    def __init__(self, config: AutonomousVerificationWorkerConfig):
        self.config = config
        self.scheduler: Optional[WindowScheduler] = None
        self._heartbeat_stop_event: Optional[threading.Event] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._lifecycle_event_id: Optional[str] = None
        self._daemon_start_time: float = 0.0

    def setup(self) -> None:
        """Initialize scheduler dependencies."""
        config_root = Path(self.config.config_root)
        if not config_root.exists():
            raise FileNotFoundError(f"Config root not found: {config_root}")

        if self.config.mode == "daemon":
            schedule_config = ScheduleConfig(
                runs_per_day=self.config.runs_per_day,
                window_start=self.config.window_start,
                window_end=self.config.window_end,
                timezone=self.config.timezone,
                jitter_minutes=self.config.jitter_minutes,
            )
            self.scheduler = WindowScheduler(schedule_config)

    def _write_pid_file(self) -> None:
        pid_path = Path("data/logs") / f"{self._worker_id}.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def _write_heartbeat(self, status: str = "alive") -> None:
        heartbeat_path = Path("data/logs") / f"{self._worker_id}.heartbeat"
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now().isoformat(),
            "pid": os.getpid(),
            "status": status,
        }
        heartbeat_path.write_text(json.dumps(payload), encoding="utf-8")

    def _record_state(self, state: str, *, success: bool = False, error: Optional[str] = None) -> None:
        record_worker_state(
            self._worker_id,
            state,
            success=success,
            error=error,
            log_path=self._worker_log_path,
        )

    def _start_heartbeat_thread(self) -> None:
        self._heartbeat_stop_event = threading.Event()

        def _heartbeat_loop() -> None:
            while self._heartbeat_stop_event and not self._heartbeat_stop_event.is_set():
                try:
                    self._write_heartbeat("alive")
                except Exception as exc:
                    logger.warning(f"Heartbeat write failed: {exc}")
                self._heartbeat_stop_event.wait(timeout=60)

        self._heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            name=f"{self._worker_id}-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat_thread(self) -> None:
        if self._heartbeat_stop_event is not None:
            self._heartbeat_stop_event.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)

    def _run_verification_pass(self) -> Dict[str, object]:
        """
        Execute one deterministic verification pass.

        Current pass validates project config/profile presence so scheduler runs
        have actionable success/failure semantics without network dependencies.
        """
        config_root = Path(self.config.config_root)
        site_profiles_dir = config_root / "site_profiles"
        profile_count = len(list(site_profiles_dir.glob("*.yaml"))) if site_profiles_dir.exists() else 0

        checks = {
            "config_root_exists": config_root.exists(),
            "site_profiles_dir_exists": site_profiles_dir.exists(),
            "site_profiles_count": profile_count,
        }
        failed_checks = [name for name, ok in checks.items() if ok is False]
        status = "success" if not failed_checks else "failure"

        emit_worker_event(
            agent_name="verification_worker",
            job_type="worker_verification_pass",
            status=status,
            metrics=checks,
            error_summary="; ".join(failed_checks) if failed_checks else None,
        )

        if failed_checks:
            raise RuntimeError(f"Verification checks failed: {', '.join(failed_checks)}")

        return checks

    def run(self) -> None:
        """Run oneshot or daemon verification workflow."""
        self._write_pid_file()
        self._write_heartbeat("starting")
        self._record_state("starting")
        self._start_heartbeat_thread()
        self._lifecycle_event_id = start_worker_run(
            "verification_worker",
            "worker_lifecycle",
            context={
                "mode": self.config.mode,
                "runs_per_day": self.config.runs_per_day,
            },
        )
        self._daemon_start_time = time.time()

        try:
            if self.config.mode == "oneshot":
                self._run_oneshot()
            elif self.config.mode == "daemon":
                self._run_daemon()
            else:
                raise ValueError(f"Invalid mode: {self.config.mode}")
        finally:
            self._stop_heartbeat_thread()
            self._write_heartbeat("stopped")
            self._record_state("stopped")

    def _run_oneshot(self) -> None:
        try:
            self._run_verification_pass()
            self._record_state("run_completed", success=True)
            if self._lifecycle_event_id:
                complete_worker_run(
                    self._lifecycle_event_id,
                    status="success",
                    duration_ms=int((time.time() - self._daemon_start_time) * 1000),
                )
        except Exception as exc:
            self._record_state("run_failed", error=str(exc))
            if self._lifecycle_event_id:
                complete_worker_run(
                    self._lifecycle_event_id,
                    status="failure",
                    duration_ms=int((time.time() - self._daemon_start_time) * 1000),
                    error_summary=str(exc),
                )
            raise

    def _run_daemon(self) -> None:
        if self.scheduler is None:
            raise RuntimeError("Scheduler not initialized for daemon mode")

        run_count = 0
        while True:
            self._write_heartbeat("sleeping")
            self._record_state("sleeping")
            self.scheduler.sleep_until_next_run()
            run_count += 1

            try:
                self._write_heartbeat("running")
                self._record_state("running")
                self._run_verification_pass()
                self._write_heartbeat("run_completed")
                self._record_state("run_completed", success=True)
                self.scheduler.mark_run_complete()
            except KeyboardInterrupt:
                self._record_state("cancelled")
                if self._lifecycle_event_id:
                    complete_worker_run(
                        self._lifecycle_event_id,
                        status="cancelled",
                        duration_ms=int((time.time() - self._daemon_start_time) * 1000),
                        output_summary=f"Interrupted after {run_count} runs",
                    )
                raise
            except Exception as exc:
                self._write_heartbeat("run_failed")
                self._record_state("run_failed", error=str(exc))
                emit_worker_event(
                    agent_name="verification_worker",
                    job_type="worker_run_failure",
                    status="failure",
                    error_summary=str(exc)[:500],
                    metrics={"run_number": run_count},
                )
                if self._lifecycle_event_id:
                    complete_worker_run(
                        self._lifecycle_event_id,
                        status="failure",
                        duration_ms=int((time.time() - self._daemon_start_time) * 1000),
                        error_summary=str(exc),
                    )
                raise


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Autonomous verification worker",
    )
    parser.add_argument("--config-root", type=str, default="config/")
    parser.add_argument("--mode", choices=["oneshot", "daemon"], default="oneshot")
    parser.add_argument("--runs-per-day", type=int, default=4)
    parser.add_argument("--window-start", type=str, default="08:00")
    parser.add_argument("--window-end", type=str, default="23:00")
    parser.add_argument("--timezone", type=str, default="America/Los_Angeles")
    parser.add_argument("--jitter-minutes", type=int, default=15)
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint."""
    args = parse_args()
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "verification_worker.log"

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )

    worker = AutonomousVerificationWorker(AutonomousVerificationWorkerConfig.from_args(args))
    worker.setup()

    def _shutdown_handler(signum, _frame) -> None:
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.warning(f"Received {sig_name}, shutting down.")
        worker._stop_heartbeat_thread()
        worker._write_heartbeat("shutting_down")
        worker._record_state("shutting_down")
        sys.exit(0)

    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, _shutdown_handler)
    if platform.system() == "Windows" and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _shutdown_handler)

    worker.run()


if __name__ == "__main__":
    main()
