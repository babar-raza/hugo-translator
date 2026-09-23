"""Durable single-controller loop for the Professionalize-only portfolio campaign."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.utils.atomic_write import atomic_write
from src.utils.file_lock import FileLock
from src.utils.windows_process import hidden_python_executable, hidden_subprocess_kwargs
from src.workers.campaign_manifest import CampaignManifest
from src.workers.campaign_process_monitor import CampaignProcessMonitor


def boot_id() -> str:
    import psutil

    return f"{int(psutil.boot_time())}"


class Controller:
    def __init__(self, args):
        self.a = args
        self.stop = False
        self.child = None
        self.session = str(uuid.uuid4())
        self.manifest = CampaignManifest.load(args.manifest)
        self.root = args.ledger_root / self.manifest.campaign_id
        self.state = self.root / "controller_state.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "controller.log"
        self.lock = FileLock(self.root / "controller.lock", timeout=0)
        self.pause_path = self.root / "pause.requested"

    def write(self, status, reason=None, **extra):
        payload = {
            "schema": 1,
            "status": status,
            "reason": reason,
            "session_id": self.session,
            "pid": os.getpid(),
            "boot_id": boot_id(),
            "updated_at": time.time(),
            "last_progress_at": time.time(),
            **extra,
        }
        atomic_write(
            self.state,
            json.dumps(payload, indent=2, sort_keys=True),
            fsync=True,
            create_parents=True,
        )

    def _classify_wave_exit(self, code: int) -> tuple[str, str, bool]:
        """Return status, durable reason, and whether bounded retry is safe."""
        try:
            detail = self.log_path.read_text(encoding="utf-8", errors="replace")[-4000:].lower()
        except OSError:
            detail = ""
        if "lacks qualified professionalize concurrency evidence" in detail or "throughput release" in detail:
            return "PAUSED_QUALIFICATION_REQUIRED", "qualification_required", False
        if "duplicate acceptance receipt" in detail or "manifest" in detail and "changed" in detail:
            return "PAUSED_DATA_INTEGRITY", "manifest_or_receipt_integrity", False
        if "campaign_owned_terminal_process" in detail:
            return "PAUSED_CONSOLE_INCIDENT", "campaign_owned_terminal_process", False
        if any(token in detail for token in ("429", "rate limit", "timeout", "connection", "circuit")):
            return "RETRY_BACKOFF", f"provider_wave_exit_{code}", True
        return "PAUSED_DATA_INTEGRITY", f"unclassified_wave_exit_{code}", False

    def on_signal(self, signum, _frame):
        self.stop = True
        self.write("STOPPING", f"signal_{signum}")
        if self.child and self.child.poll() is None:
            self._stop_child_tree()

    def _stop_child_tree(self):
        """Stop the owned launcher and every worker it created."""
        if not self.child or self.child.poll() is not None:
            return
        if sys.platform == "win32":
            try:
                self.child.send_signal(signal.CTRL_BREAK_EVENT)
                self.child.wait(timeout=90)
                return
            except (OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    ["taskkill.exe", "/PID", str(self.child.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
        else:
            self.child.terminate()
        try:
            self.child.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=30)

    def _wait_for_wave(self):
        while self.child and self.child.poll() is None:
            self.write("RUNNING", command="bounded_wave", child_pid=self.child.pid)
            time.sleep(15)
        return self.child.returncode if self.child else 1

    def _active_shard_locks(self):
        active = []
        for path in self.root.glob("shard-*.lock"):
            probe = FileLock(path, timeout=0)
            if probe.acquire(blocking=False):
                probe.release()
            else:
                active.append(path.name)
        return active

    def _adopt_orphan_wave(self):
        """Wait for durable workers left by an interrupted prior controller."""
        while not self.stop:
            active = self._active_shard_locks()
            if not active:
                return
            self.write("RUNNING", "adopting_orphan_wave", active_shard_locks=len(active))
            time.sleep(15)

    def _recover_stale_claim(self):
        """Reclaim only after OS evidence proves the prior launcher is gone."""
        import psutil

        from src.workers import work_claims

        key = f"family:{self.root.name}"
        path = self.a.ledger_root / "claims.jsonl"
        claim = work_claims.active_claim(key, claims_path=path)
        if not claim or claim["session_id"] == self.session:
            return
        probe = FileLock(self.root / "parallel-launcher.lock", timeout=0)
        if not probe.acquire(blocking=False):
            return
        try:
            for proc in psutil.process_iter(["pid", "cmdline"]):
                command = " ".join(proc.info.get("cmdline") or [])
                if claim["session_id"] in command and "launch_parallel_campaign_shards" in command:
                    return
            if not self._active_shard_locks():
                work_claims.release_claim(key, claim["session_id"], claims_path=path)
        finally:
            probe.release()

    def run(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self.on_signal)
        if not self.lock.acquire(blocking=False):
            return 75
        content_root = Path(self.manifest.content_repo) / "content"
        if not content_root.is_dir():
            self.write("FAILED", f"content_root_missing:{content_root}")
            return 78
        primary_model = str(self.manifest.retry_policy.get("primary_model", ""))
        if primary_model != "professionalize_llm":
            self.write("FAILED", f"provider_policy:{primary_model}")
            return 78
        self.write("STARTING")
        merge = [
            hidden_python_executable(),
            str(self.a.runtime / "scripts/campaign/merge_campaign_journals.py"),
            "--campaign-id",
            self.root.name,
            "--ledger-root",
            str(self.a.ledger_root),
        ]
        while not self.stop:
            if self.pause_path.exists():
                self.write("PAUSED", "pause_requested")
                return 0
            self._adopt_orphan_wave()
            if self.stop:
                break
            self._recover_stale_claim()
            subprocess.run(merge, check=True, timeout=300, **hidden_subprocess_kwargs())
            cmd = [
                hidden_python_executable(),
                "-u",
                str(self.a.runtime / "scripts/campaign/launch_parallel_campaign_shards.py"),
                "--campaign-manifest",
                str(self.a.manifest),
                "--ledger-root",
                str(self.a.ledger_root),
                "--child",
                "gate5",
                "--max-workers",
                "8",
                "--wait",
                "--device",
                "cpu",
                "--no-force-serialize",
                "--checkpoint-wave-shards",
                "64",
                "--tm-repository-root",
                str(self.a.control),
                "--tm-intent-spool-path",
                str(self.a.spool),
                "--session-id",
                self.session,
                "--watchdog-state",
                str(self.root / "watchdog_state.json"),
            ]
            if self.a.release:
                cmd += ["--throughput-release", str(self.a.release)]
            self.write("RUNNING", command="bounded_wave")
            with self.log_path.open("a", encoding="utf-8", buffering=1) as log:
                log.write(
                    f"{datetime.now(timezone.utc).isoformat()} launching bounded wave session={self.session}\n"
                )
                child_env = os.environ.copy()
                child_env["ASPOSE_ORG_CONTENT"] = str(Path(self.manifest.content_repo) / "content")
                child_env["CUDA_VISIBLE_DEVICES"] = "-1"
                child_env["OMP_NUM_THREADS"] = "1"
                child_env["MKL_NUM_THREADS"] = "1"
                child_env["PYTHONPATH"] = os.pathsep.join(
                    [str(self.a.runtime), str(self.a.control), child_env.get("PYTHONPATH", "")]
                ).rstrip(os.pathsep)
                monitor = CampaignProcessMonitor(
                    campaign_id=self.root.name,
                    evidence_path=self.root / "evidence" / "terminal-processes.jsonl",
                    roots=(self.a.runtime, self.a.control),
                )
                monitor.start()
                self.child = subprocess.Popen(
                    cmd,
                    cwd=self.a.control,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=child_env,
                    **hidden_subprocess_kwargs(new_process_group=True),
                )
                code = self._wait_for_wave()
                terminal_incident = monitor.close()
            self.child = None
            if self.stop:
                self.write("INTERRUPTED", "controller_signal")
                return 130
            if terminal_incident:
                self.pause_path.touch(exist_ok=True)
                self.write("PAUSED_CONSOLE_INCIDENT", "campaign_owned_terminal_process")
                return 2
            if self.pause_path.exists():
                self.write("PAUSED_OPERATOR", "pause_requested_after_wave")
                return 0
            if code:
                status, reason, retry = self._classify_wave_exit(code)
                self.write(status, reason, next_retry_at=time.time() + self.a.retry_seconds if retry else None)
                if not retry:
                    self.pause_path.touch(exist_ok=True)
                    return code
                time.sleep(self.a.retry_seconds)
                continue
            progress = subprocess.check_output(
                [
                    hidden_python_executable(),
                    str(self.a.runtime / "scripts/campaign/campaign_progress.py"),
                    "--manifest",
                    str(self.a.manifest),
                    "--ledger-root",
                    str(self.a.ledger_root),
                    "--spool",
                    str(self.a.spool),
                ],
                cwd=self.a.control,
                text=True,
                **hidden_subprocess_kwargs(),
            )
            remaining = int(json.loads(progress)["remaining"])
            self.write("RUNNING", remaining=remaining)
            if remaining == 0:
                self.write("COMPLETE", remaining=0)
                return 0
        return 130


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--control", type=Path, required=True)
    p.add_argument("--ledger-root", type=Path, required=True)
    p.add_argument("--spool", type=Path, required=True)
    p.add_argument("--release", type=Path)
    p.add_argument("--retry-seconds", type=int, default=120)
    a = p.parse_args()
    a.manifest = a.manifest.resolve()
    a.runtime = a.runtime.resolve()
    a.control = a.control.resolve()
    a.ledger_root = a.ledger_root.resolve()
    a.spool = a.spool.resolve()
    controller = Controller(a)
    try:
        return controller.run()
    except BaseException as e:
        try:
            controller.write("FAILED", f"{type(e).__name__}: {e}"[:500])
        except Exception:
            pass
        raise
    finally:
        try:
            controller.lock.release()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
