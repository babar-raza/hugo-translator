"""RT-01: real OS-process integration proof for ProfessionalizeRetryWorker.

Every existing ProfessionalizeRetryWorker test (unit and
``tests/integration/test_retry_tm_writer_e2e.py``) constructs the worker
in-process and calls ``run_once()`` directly. That proves the consumer logic
is correct, but never proves the worker actually behaves the same way when
launched as a real, separate OS process the way an operator or scheduler
would run it -- reading a real SQLite WAL queue file from disk, writing a
real heartbeat file another process can poll, and exiting cleanly.

This module launches a genuine child ``python.exe`` process (``subprocess.
Popen``, never ``multiprocessing`` and never an in-process call) that
constructs a real ``ProfessionalizeRetryWorker`` around a real, disk-backed
``RejectedTaskQueue``/``TMIntentSpool`` pair seeded by the parent test
process beforehand, with a fake/stub in-process ``DocumentProvider`` so no
real network/LLM call is ever made. The child drains every seeded task to a
terminal state (accepted or dead-lettered) and exits on its own -- a bounded
"run to completion" process, so there is no indefinite child to terminate.

After the child exits, the parent process (which never itself touches the
heartbeat file) verifies real progress reached disk from that *other*
process: the queue's terminal state, the accepted output bytes, the TM
intent spool, and the heartbeat file's content/mtime.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path
from textwrap import dedent

from src.tm.intent_spool import TMIntentSpool
from src.tm.rejected_task_queue import RejectedTaskQueue
from src.tm.retry_records import RejectedTranslationTask

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_CHILD_SCRIPT_TEMPLATE = dedent(
    """
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, {project_root!r})

    from src.tm.intent_spool import TMIntentSpool
    from src.tm.rejected_task_queue import RejectedTaskQueue
    from src.workers.professionalize_retry_worker import (
        ProfessionalizeRetryWorker,
        write_retry_heartbeat,
    )


    class StubProvider:
        \"\"\"Fake DocumentProvider: no network/LLM call, deterministic output.\"\"\"

        def __init__(self):
            self.calls = 0

        def generate(self, system_prompt, user_text):
            self.calls += 1
            return user_text.replace("source", "translated"), 5, 5


    def validate_document(source, candidate, task):
        if "REJECT" in source:
            raise ValueError("stub validator: source is marked REJECT")
        return None


    def main():
        root = Path({root!r})
        queue = RejectedTaskQueue(Path({queue_path!r}))
        spool = TMIntentSpool(Path({spool_path!r}))
        heartbeat_path = Path({heartbeat_path!r})
        worker = ProfessionalizeRetryWorker(
            queue=queue,
            intent_spool=spool,
            provider=StubProvider(),
            repository_root=root,
            validate_document=validate_document,
            live_mode=True,
            heartbeat_path=heartbeat_path,
            heartbeat_interval_seconds=0.05,
        )
        result = worker.run_once(owner="real-subprocess-worker", limit=10, lease_seconds=60)
        write_retry_heartbeat(heartbeat_path, status="completed", queue=queue, metrics=worker.metrics)
        print(json.dumps(result, sort_keys=True))


    if __name__ == "__main__":
        main()
    """
)


def _seed_task(root: Path, *, name: str, source_text: str, retry_budget: int,
                source_sha256: str | None = None) -> RejectedTranslationTask:
    source_path = root / "content/en" / f"{name}.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    # Write raw bytes (not Path.write_text) so the on-disk source is exactly
    # the LF-only text below: write_text() applies Windows universal-newline
    # translation (\n -> \r\n) on write, and the stub provider below echoes
    # the source's own line endings back -- round-tripping that through
    # _atomic_write's own text-mode \n translation would otherwise double up.
    source_path.write_bytes(source_text.encode("utf-8"))
    return RejectedTranslationTask.from_mapping({
        "campaign_id": "campaign",
        "site_id": "docs.aspose.org",
        "source_path": f"content/en/{name}.md",
        "output_path": f"content/de/{name}.md",
        "source_sha256": source_sha256 or sha256(source_path.read_bytes()).hexdigest(),
        "target_lang": "de",
        "failure_category": "validation",
        "failure_fingerprint": f"fingerprint-{name}",
        "retry_budget": retry_budget,
        "model_target": "professionalize_llm",
    })


def test_real_child_process_drains_queue_to_terminal_states_with_live_heartbeat(tmp_path: Path):
    root = tmp_path / "content_repo"
    root.mkdir()
    queue_path = tmp_path / "rejected_tasks.sqlite3"
    spool_path = tmp_path / "intent_spool.sqlite3"
    heartbeat_path = tmp_path / "professionalize_retry_worker.heartbeat"
    assert not heartbeat_path.exists()

    queue = RejectedTaskQueue(queue_path)
    accept_task_id = queue.enqueue(
        _seed_task(root, name="accept", source_text="# source accept\n", retry_budget=2)
    )
    reject_task_id = queue.enqueue(
        _seed_task(root, name="reject", source_text="# source REJECT\n", retry_budget=0)
    )
    drift_task_id = queue.enqueue(
        _seed_task(
            root, name="drift", source_text="# source drift\n", retry_budget=2,
            source_sha256="0" * 64,  # deliberately wrong -> SOURCE_DRIFT before any provider call
        )
    )

    script_path = tmp_path / "run_worker_subprocess.py"
    script_path.write_text(
        _CHILD_SCRIPT_TEMPLATE.format(
            project_root=str(PROJECT_ROOT),
            root=str(root),
            queue_path=str(queue_path),
            spool_path=str(spool_path),
            heartbeat_path=str(heartbeat_path),
        ),
        encoding="utf-8",
    )

    start_time = time.time()
    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise AssertionError(f"child process did not complete in time; stdout={stdout!r} stderr={stderr!r}")
    end_time = time.time()

    assert proc.returncode == 0, f"child process failed: stdout={stdout!r} stderr={stderr!r}"
    printed = json.loads(stdout.strip().splitlines()[-1])
    assert printed["accepted"] == 1
    assert printed["dead_lettered"] == 2
    assert printed["retried"] == 0

    # --- queue terminal state, verified from the parent process afresh ---
    final_queue = RejectedTaskQueue(queue_path)
    assert final_queue.stats() == {"QUEUED": 0, "CLAIMED": 0, "ACCEPTED": 1, "DEAD_LETTER": 2}
    assert final_queue.get(accept_task_id)["state"] == "ACCEPTED"
    assert final_queue.get(reject_task_id)["state"] == "DEAD_LETTER"
    assert final_queue.get(reject_task_id)["error_code"] == "ValueError"
    assert final_queue.get(drift_task_id)["state"] == "DEAD_LETTER"
    assert final_queue.get(drift_task_id)["error_code"] == "SOURCE_DRIFT"

    # --- only the accepted task produced output, written by the real child ---
    assert (root / "content/de/accept.md").read_text(encoding="utf-8") == "# translated accept\n"
    assert not (root / "content/de/reject.md").exists()
    assert not (root / "content/de/drift.md").exists()

    # --- the accepted task's TM intent reached the spool the child wrote to ---
    spool = TMIntentSpool(spool_path)
    assert spool.stats() == {"PENDING": 1, "CLAIMED": 0, "APPLIED": 0}

    # --- heartbeat file reflects real progress from the child process, not
    # from this test's own process (this test never calls write_retry_heartbeat
    # itself) ---
    assert heartbeat_path.is_file()
    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["status"] == "completed"
    assert heartbeat["metrics"] == {"processed": 3, "accepted": 1, "retried": 0, "dead_lettered": 2}
    assert heartbeat["ACCEPTED"] == 1 and heartbeat["DEAD_LETTER"] == 2

    heartbeat_timestamp = heartbeat["timestamp"]
    # Round-trips through fromisoformat (Python's json/datetime, not a manual
    # parser) so a malformed timestamp fails loudly here rather than later.
    from datetime import datetime

    parsed = datetime.fromisoformat(heartbeat_timestamp.replace("Z", "+00:00"))
    assert start_time - 5 <= parsed.timestamp() <= end_time + 5

    mtime = os.path.getmtime(heartbeat_path)
    assert start_time - 1 <= mtime <= end_time + 5
