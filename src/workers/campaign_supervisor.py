"""OP-01: a durable supervisor for one CampaignRunner (uninterrupted, receipt-backed
batch commits).

``CampaignRunner.run(resume=, shard_ids=)`` is already a clean re-entrant unit (see
``scripts/campaign/run_gate5_batch.py``), but a one-shot CLI process gives an operator
no durable lifecycle: a crash between "jobs receipted" and "output committed" leaves
someone to manually diagnose git/ledger state before relaunching.  ``CampaignSupervisor``
wraps one ``CampaignRunner`` instance, drives it one shard at a time, writes a heartbeat
for external monitoring, and durably records which lifecycle stage each shard reached so
a fresh process resumes exactly where the last one stopped -- never re-translating
already-receipted work and never double-committing already-committed output.

Campaign work has three stages (OP-01's own vocabulary, see the plan's CO-05 mapping):

* **Receipted** -- ``CampaignLedger.append_receipt()`` durably records an all-gates-pass
  candidate.  This already happens inside ``CampaignRunner`` job execution.
* **Adopted** -- a content-repo governance step (``session_ledger.py adopt`` /
  ``candidates --format json``) that is *not implemented in this repository*: it is a
  manual runbook step against the content repo.  This module never shells out to the
  real script; it exposes ``adoption_check`` as an injectable callable or subprocess-args
  list so a deployment can wire the real command, and so tests never need the real
  content repo checked out.
* **Committed** -- ``CampaignRunner._commit_verified_outputs()``.

Lifecycle values written to the heartbeat/state files:

* ``STARTING`` -- constructed/started, has not yet inspected prior state.
* ``RUNNING_SHARD:<id>`` -- ``run_shard_jobs`` (by default ``CampaignRunner.run``) is
  translating/receipting one shard.
* ``AWAITING_ADOPTION`` -- the shard's jobs are fully receipted; ``adoption_check`` has
  not yet returned for this shard's outputs.
* ``COMMITTING`` -- the adoption check returned; the governed commit is being staged.
* ``SHARD_DONE`` -- the shard's pending output (if any) is fully committed.
* ``CRASHED_RECOVERING`` -- set while a restart is finishing receipted-but-uncommitted
  output a previous process left behind, before resuming the ordinary shard loop.
* ``DONE`` -- no shard-level work and no pending commit remains.
* ``FAILED`` -- an unrecoverable exception propagated out of the loop; re-raised after
  the heartbeat/state files are updated so it is visible to a monitor.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from src.utils.atomic_write import atomic_write
from src.utils.file_lock import FileLock, LockError

from .campaign_manifest import git_dirty_paths
from .campaign_runner import CampaignRunner

logger = logging.getLogger(__name__)

#: A callable takes the shard id and returns whatever the adoption source reports
#: (or None); a subprocess-args form is normalized into one by ``CampaignSupervisor``.
AdoptionCheck = Callable[[str], Any]
RunShardJobs = Callable[[str], None]


def _default_adoption_check(shard_id: str) -> None:
    """No-op default: no external content-repo governance call configured."""
    return None


class CampaignSupervisorError(RuntimeError):
    """Raised when a CampaignSupervisor cannot safely proceed."""


class CampaignSupervisor:
    """Drive one ``CampaignRunner`` shard-by-shard with a durable, restart-safe lifecycle.

    Construct around a real ``CampaignRunner`` and call :meth:`run` once; it loops
    until every manifest output the runner can currently see has been committed.  An
    ordinary per-file rejection is not a supervisor-level failure: ``CampaignRunner``
    already turns it into a heal ticket and continues (plan TC-APT-041), so the
    resolved next shard simply excludes that job the way ``CampaignManifest.shards``
    always has.
    """

    def __init__(
        self,
        *,
        runner: CampaignRunner,
        heartbeat_path: Path,
        state_path: Path | None = None,
        heartbeat_interval: float = 30.0,
        adoption_check: AdoptionCheck | Sequence[str] | None = None,
        run_shard_jobs: RunShardJobs | None = None,
    ) -> None:
        self.runner = runner
        self.heartbeat_path = Path(heartbeat_path)
        self.state_path = (
            Path(state_path)
            if state_path is not None
            else self.heartbeat_path.with_name(self.heartbeat_path.stem + ".state.json")
        )
        self.heartbeat_interval = heartbeat_interval
        self._adoption_check: AdoptionCheck = self._normalize_adoption_check(adoption_check)
        self._run_shard_jobs: RunShardJobs = run_shard_jobs or self._default_run_shard_jobs

        # OP-01: the runner must never auto-commit inside its own shard loop, so this
        # supervisor can durably observe (and, if interrupted, resume) the boundary
        # between "jobs receipted", "adoption checked", and "output committed". This
        # mutates only the manifest's own commit_policy *dict contents* in place --
        # CampaignManifest is a frozen dataclass, so the field itself is never
        # reassigned, and CampaignRunner's public signatures/_commit_verified_outputs
        # are used exactly as they already are.
        commit_policy = runner.manifest.commit_policy
        self._commit_enabled = bool(commit_policy.get("enabled", True))
        self._max_outputs_per_commit = int(commit_policy.get("max_outputs_per_commit", 250))
        commit_policy["enabled"] = False

        self._heartbeat_stop_event: threading.Event | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._lifecycle = "STARTING"
        self._active_shard_id: str | None = None
        self._receipts_written = 0
        self._last_commit_sha: str | None = None
        self._last_commit_at: str | None = None

    @staticmethod
    def _normalize_adoption_check(
        value: AdoptionCheck | Sequence[str] | None,
    ) -> AdoptionCheck:
        if value is None:
            return _default_adoption_check
        if callable(value):
            return value

        # A subprocess-args list, e.g. the content repo's own venv python plus
        # `session_ledger.py candidates --session-id <id> --format json`. "{shard_id}"
        # in any argument is substituted before the call. This process never touches
        # the content repo itself beyond running exactly this command.
        args = [str(part) for part in value]

        def _call(shard_id: str) -> Any:
            resolved = [part.format(shard_id=shard_id) for part in args]
            completed = subprocess.run(resolved, check=True, capture_output=True, text=True)
            text = completed.stdout.strip()
            return json.loads(text) if text else None

        return _call

    def _default_run_shard_jobs(self, shard_id: str) -> None:
        self.runner.run(resume=True, shard_ids={shard_id})

    # ---- heartbeat / durable state -----------------------------------------

    def _payload(self) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "campaign_id": self.runner.manifest.campaign_id,
            "lifecycle": self._lifecycle,
            "active_shard_id": self._active_shard_id,
            "receipts_written": self._receipts_written,
            "last_commit_sha": self._last_commit_sha,
            "last_commit_at": self._last_commit_at,
        }

    def _write_heartbeat(self) -> None:
        atomic_write(self.heartbeat_path, json.dumps(self._payload(), sort_keys=True))

    def _write_state(self) -> None:
        atomic_write(self.state_path, json.dumps(self._payload(), sort_keys=True))

    def _set_lifecycle(self, lifecycle: str, *, shard_id: str | None = None) -> None:
        self._lifecycle = lifecycle
        if shard_id is not None:
            self._active_shard_id = shard_id
        self._write_heartbeat()
        self._write_state()

    def _load_last_state(self) -> dict[str, Any] | None:
        if not self.state_path.is_file():
            return None
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def start_heartbeat_thread(self) -> None:
        """Start a daemon thread that refreshes the heartbeat file on an interval.

        Follows the start/stop daemon-thread convention used by
        ``autonomous_content_translation_worker.py`` / ``tm_improvement_worker.py``.
        """
        if self._heartbeat_thread is not None:
            return
        self._heartbeat_stop_event = threading.Event()
        stop_event = self._heartbeat_stop_event

        def _loop() -> None:
            while not stop_event.is_set():
                try:
                    self._write_heartbeat()
                except Exception as exc:  # pragma: no cover - defensive, matches worker convention
                    logger.warning("campaign supervisor heartbeat write failed: %s", exc)
                stop_event.wait(timeout=self.heartbeat_interval)

        self._heartbeat_thread = threading.Thread(
            target=_loop, name="campaign-supervisor-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def stop_heartbeat_thread(self) -> None:
        if self._heartbeat_stop_event is not None:
            self._heartbeat_stop_event.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
        self._heartbeat_thread = None
        self._heartbeat_stop_event = None

    # ---- reconciliation -----------------------------------------------------

    def _pending_commit_paths(self) -> set[str]:
        """Receipted output still dirty in git: work a previous crash left between
        "receipted" and "committed", regardless of which shard produced it or whether
        the crash happened before or after ``git add`` staged it."""
        receipts = self.runner._validated_resume_receipts()
        dirty = {Path(item).as_posix() for item in git_dirty_paths(self.runner.content_repo)}
        return dirty & set(receipts)

    def _resolve_next_shard_id(self) -> str | None:
        receipts = self.runner._validated_resume_receipts()
        shards = list(
            self.runner.manifest.shards(
                resume_receipts=set(receipts), max_outputs=self._max_outputs_per_commit
            )
        )
        return str(shards[0]["shard_id"]) if shards else None

    # ---- per-shard lifecycle steps (each independently interruptible) -------

    def _await_adoption(self, shard_id: str) -> Any:
        self._set_lifecycle("AWAITING_ADOPTION", shard_id=shard_id)
        return self._adoption_check(shard_id)

    def _commit_shard(self, shard_id: str) -> str | None:
        self._set_lifecycle("COMMITTING", shard_id=shard_id)
        if not self._commit_enabled:
            return None
        return self.runner._commit_verified_outputs(shard_id)

    def _finish_shard(self, shard_id: str) -> None:
        """Adopt then commit whatever is currently receipted-but-uncommitted.

        Safe to call more than once for the same (or a recovered) shard id: adoption
        is expected to be a read-only content-repo query, and
        ``CampaignRunner._commit_verified_outputs`` only ever stages/commits paths that
        are both receipted and still dirty, so re-running it after a partial commit
        (or after nothing changed) is a no-op rather than a duplicate commit.
        """
        self._await_adoption(shard_id)
        commit_sha = self._commit_shard(shard_id)
        if commit_sha:
            self._last_commit_sha = commit_sha
            self._last_commit_at = datetime.now(timezone.utc).isoformat()
        self._set_lifecycle("SHARD_DONE", shard_id=shard_id)

    # ---- top-level loop -------------------------------------------------------

    def run(self, *, max_iterations: int | None = None) -> dict[str, Any]:
        """Run (or resume) the wrapped campaign to completion.

        On start, reconciles against whatever this supervisor (or a prior instance
        pointed at the same heartbeat/ledger) last wrote: a receipted-but-uncommitted
        output set takes priority over starting a new shard, so a restart after any
        crash finishes the interrupted shard before doing anything else.

        Holds a supervisor-scoped lock (distinct from CampaignRunner's own
        campaign/shard locks -- no conflict with the per-shard lock the default
        ``run_shard_jobs`` acquires inside ``runner.run()``) for the whole call, so a
        second supervisor process can never work the same campaign concurrently. A
        hard-killed process releases this OS-level lock when its process handle
        closes, so a restart after any crash acquires it immediately.
        """
        lock_path = self.runner.ledger.root / "campaign-supervisor.lock"
        try:
            with FileLock(lock_path, timeout=0):
                return self._run_locked(max_iterations=max_iterations)
        except LockError as exc:
            raise CampaignSupervisorError(
                f"another CampaignSupervisor already holds {lock_path}"
            ) from exc

    def _run_locked(self, *, max_iterations: int | None) -> dict[str, Any]:
        last_state = self._load_last_state()
        if last_state and last_state.get("active_shard_id"):
            self._active_shard_id = str(last_state["active_shard_id"])

        self._set_lifecycle("STARTING")
        self.start_heartbeat_thread()
        try:
            iterations = 0
            while max_iterations is None or iterations < max_iterations:
                iterations += 1
                pending = self._pending_commit_paths()
                if pending:
                    shard_id = self._active_shard_id or "recovered"
                    self._set_lifecycle("CRASHED_RECOVERING", shard_id=shard_id)
                    self._finish_shard(shard_id)
                    continue

                shard_id = self._resolve_next_shard_id()
                if shard_id is None:
                    break

                self._set_lifecycle(f"RUNNING_SHARD:{shard_id}", shard_id=shard_id)
                self._run_shard_jobs(shard_id)
                self._receipts_written = len(self.runner._validated_resume_receipts())
                self._finish_shard(shard_id)

            self._set_lifecycle("DONE")
            return {
                "campaign_id": self.runner.manifest.campaign_id,
                "accepted": len(self.runner._validated_resume_receipts()),
                "last_commit_sha": self._last_commit_sha,
                "lifecycle": self._lifecycle,
            }
        except Exception:
            self._lifecycle = "FAILED"
            try:
                self._write_heartbeat()
                self._write_state()
            except Exception:  # pragma: no cover - best-effort only
                pass
            raise
        finally:
            self.stop_heartbeat_thread()
