"""Real multiprocess crash-boundary proof for TM-02's single-writer TM boundary.

Uses actual OS processes (``multiprocessing.Process``) -- never threads, never
mocks -- against temp-dir-only SQLite/LMDB/FAISS stores.  Nothing here ever
touches ``data/tm/`` or ``data/campaigns/``: those are live production paths
with an active campaign process running against them, and every store built
below lives under pytest's ``tmp_path``.

Two properties are proven:

1. ``TMIntentSpool.enqueue()`` is safe under real concurrent OS-process
   writers, including one that is killed (``SIGKILL``/``TerminateProcess``)
   mid-stream: every intent it durably committed before death survives, and
   none is lost or duplicated (test 1).
2. ``TMIntentWriter.run_once()`` saves the L3 FAISS index once per batch, so a
   writer crash between an intent's ``spool.complete()`` and that trailing
   ``save_index()`` leaves the spool/L2 believing an L3 update landed when it
   was actually only ever held in the dead process's memory. This is a real,
   reproducible gap -- normal draining never revisits an APPLIED intent, so
   without repair the entry is permanently missing from L3.
   ``TMIntentWriter.reconcile_l3()`` is the crash-boundary reconciliation
   logic that detects and repairs exactly that gap, without duplicating any
   entry L3 already has (test 2).
"""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

from src.tm.intent_spool import TMIntentSpool, TMIntentWriter
from src.tm.l2_persistent import L2PersistentTM
from src.tm.l3_semantic import L3SemanticTM

_POLL_INTERVAL_SECONDS = 0.002
_POLL_TIMEOUT_SECONDS = 30


def _enqueue_many(spool_path: str, worker_id: int, count: int, progress_path: str) -> None:
    """Real OS process target: durably enqueue ``count`` distinct intents.

    Progress is recorded after every committed write so a killer process can
    learn exactly how many landed before termination -- the ground truth the
    test compares the spool's post-mortem state against.
    """
    spool = TMIntentSpool(Path(spool_path))
    for i in range(count):
        spool.enqueue(
            {
                "site_id": "docs.aspose.org",
                "src_lang": "en",
                "tgt_lang": "de",
                "text": f"producer-{worker_id}-text-{i}",
                "translation": f"producer-{worker_id}-ziel-{i}",
            }
        )
        Path(progress_path).write_text(str(i + 1), encoding="utf-8")


def _wait_for_progress(progress_path: Path, *, at_least: int = 1, less_than: int | None = None) -> int:
    """Poll a progress file until it reports a value in the desired range."""
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    last = 0
    while time.monotonic() < deadline:
        try:
            last = int(progress_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            last = 0
        if last >= at_least and (less_than is None or last < less_than):
            return last
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise AssertionError(
        f"progress file {progress_path} never reached [{at_least}, {less_than}); last={last}"
    )


def test_concurrent_producer_processes_crash_mid_stream_no_lost_or_duplicate_intents(
    tmp_path: Path,
):
    spool_path = tmp_path / "intents.sqlite3"

    normal_count = 15
    crash_count = 500  # large enough that a kill reliably lands mid-stream
    progress_normal = [tmp_path / f"progress_normal_{i}.txt" for i in range(2)]
    progress_crash = tmp_path / "progress_crash.txt"

    normal_procs = [
        multiprocessing.Process(
            target=_enqueue_many,
            args=(str(spool_path), worker_id, normal_count, str(progress_normal[worker_id])),
        )
        for worker_id in range(2)
    ]
    crash_worker_id = 99
    crash_proc = multiprocessing.Process(
        target=_enqueue_many,
        args=(str(spool_path), crash_worker_id, crash_count, str(progress_crash)),
    )

    for proc in normal_procs:
        proc.start()
    crash_proc.start()
    try:
        _wait_for_progress(progress_crash, at_least=1, less_than=crash_count)
    finally:
        # Real crash: SIGKILL/TerminateProcess, no chance to run cleanup code.
        # This can land anywhere, including between a committed enqueue() and
        # the progress-file write that records it -- so the file is only used
        # to time the kill, never as the post-mortem source of truth below.
        crash_proc.kill()
        crash_proc.join(timeout=10)
    assert not crash_proc.is_alive()

    for proc in normal_procs:
        proc.join(timeout=30)
        assert not proc.is_alive()
        assert proc.exitcode == 0

    # Ground truth comes from the spool itself, not the crashed process's own
    # bookkeeping: every intent it durably committed is a real, distinct row
    # (enqueue() is a single autocommit INSERT), so its indices must form a
    # gap-free prefix 0..k-1 with no loss and no duplication -- regardless of
    # exactly which statement the kill landed on.
    spool = TMIntentSpool(spool_path)
    stats_before_inspection = spool.stats()  # claim() below mutates state, so snapshot first
    all_pending = spool.claim("verify", limit=10**6, lease_seconds=300)
    pending_texts = [intent["text"] for intent in all_pending]
    assert len(pending_texts) == len(set(pending_texts))  # no duplicates

    crash_prefix = f"producer-{crash_worker_id}-text-"
    crashed_indices = sorted(
        int(text[len(crash_prefix):]) for text in pending_texts if text.startswith(crash_prefix)
    )
    committed_by_crashed = len(crashed_indices)
    assert 0 < committed_by_crashed < crash_count, (
        "test is only meaningful if the kill landed mid-stream; "
        f"got {committed_by_crashed}/{crash_count}"
    )
    assert crashed_indices == list(range(committed_by_crashed)), (
        "no lost intent: the crashed producer's committed writes must form "
        "a gap-free prefix, not a sparse subset"
    )

    expected_total = 2 * normal_count + committed_by_crashed
    assert stats_before_inspection == {"PENDING": expected_total, "CLAIMED": 0, "APPLIED": 0}
    assert len(pending_texts) == expected_total

    for worker_id in range(2):
        for i in range(normal_count):
            assert f"producer-{worker_id}-text-{i}" in pending_texts


def _writer_run_once(spool_path: str, l2_path: str, l3_path: str, owner: str, limit: int) -> None:
    """Real OS process target: drains the spool through the single-writer
    boundary against real temp-dir LMDB + FAISS stores."""
    spool = TMIntentSpool(Path(spool_path))
    l2 = L2PersistentTM(Path(l2_path))
    l3 = L3SemanticTM(Path(l3_path), use_gpu=False)
    try:
        TMIntentWriter(spool, l2, l3).run_once(owner=owner, limit=limit, lease_seconds=300)
    finally:
        l2.close()


def test_writer_process_crash_mid_batch_then_reconciliation_recovers_l3_without_duplicates(
    tmp_path: Path,
):
    spool_path = tmp_path / "intents.sqlite3"
    l2_path = tmp_path / "l2.lmdb"
    l3_path = tmp_path / "l3_index"

    total = 120
    spool = TMIntentSpool(spool_path)
    for i in range(total):
        spool.enqueue(
            {
                "site_id": "docs.aspose.org",
                "src_lang": "en",
                "tgt_lang": "de",
                "text": f"crash-boundary-text-{i}",
                "translation": f"crash-boundary-ziel-{i}",
            }
        )
    assert spool.stats()["PENDING"] == total

    # Real OS process: claims all `total` intents in one run_once() batch and
    # is killed mid-loop, well before it ever reaches the batch's single
    # trailing save_index() call.
    writer_proc = multiprocessing.Process(
        target=_writer_run_once,
        args=(str(spool_path), str(l2_path), str(l3_path), "crashed-writer", total),
    )
    writer_proc.start()
    # Generous timeout: this waits out real process-startup + model-loading
    # latency (torch/sentence-transformers import, CPU embedding model load),
    # which varies with system load -- not the per-intent apply rate.
    deadline = time.monotonic() + 120
    observed_progress = 0
    while time.monotonic() < deadline:
        observed_progress = spool.stats()["APPLIED"]
        if 0 < observed_progress < total:
            break
        if not writer_proc.is_alive():
            break  # exited on its own -- fail fast below with the exit code
        time.sleep(_POLL_INTERVAL_SECONDS)
    assert 0 < observed_progress < total, (
        f"writer crash test requires an intermediate state; observed applied={observed_progress}/{total}, "
        f"writer_proc.exitcode={writer_proc.exitcode}"
    )
    # Real crash: SIGKILL/TerminateProcess, no chance to run cleanup code
    # (the `finally: l2.close()` in _writer_run_once never executes).
    writer_proc.kill()
    writer_proc.join(timeout=15)
    assert not writer_proc.is_alive()

    # Ground truth after the crash: read the ACTUAL final count now that the
    # process is confirmed dead -- it can (and does) advance past whatever
    # value the poll loop last observed before the kill signal landed. The
    # spool durably believes exactly `applied_before_kill` intents are
    # APPLIED, but the dead process's in-memory FAISS additions for every one
    # of them were never saved -- run_once() only calls save_index() once,
    # after its whole loop finishes.
    applied_before_kill = spool.stats()["APPLIED"]
    assert 0 < applied_before_kill < total, (
        f"writer crash test requires an intermediate state; final applied={applied_before_kill}/{total}"
    )
    l3_after_crash = L3SemanticTM(l3_path, use_gpu=False)
    assert len(l3_after_crash) == 0, (
        "demonstrates the crash-boundary gap: a batch-ending save_index() "
        "means a mid-batch kill loses every L3 write from that run, even "
        "though the spool and L2 already durably reflect them"
    )
    l2_after_crash = L2PersistentTM(l2_path)
    try:
        # L2 writes ARE durable per-intent, and happen (in the loop body)
        # before that intent's spool.complete() call -- so at most one
        # further "in-flight" intent can have reached L2 without the spool
        # yet marking it APPLIED (the kill can land between the two calls).
        # L2 count is therefore applied_before_kill or one more, never less.
        assert applied_before_kill <= len(l2_after_crash) <= applied_before_kill + 1
    finally:
        l2_after_crash.close()

    # Recover the leftover CLAIMED work (owned by the now-dead process) the
    # way an operator would, then finish draining normally.
    spool.requeue_expired_claims(now=time.time() + 10**6)
    fresh_l2 = L2PersistentTM(l2_path)
    fresh_l3 = L3SemanticTM(l3_path, use_gpu=False)
    writer = TMIntentWriter(spool, fresh_l2, fresh_l3)
    try:
        result = writer.run_once(owner="recovery-writer", limit=total, lease_seconds=300)
        assert result["applied"] == total - applied_before_kill
        assert spool.stats() == {"PENDING": 0, "CLAIMED": 0, "APPLIED": total}
        # The second batch's own trailing save_index() only covers what IT
        # applied -- the first batch's crash-orphaned entries are still gone.
        assert len(fresh_l3) == total - applied_before_kill
        assert len(fresh_l2) == total

        # This is the crash-boundary reconciliation logic: repair L3 for
        # every intent the spool already marked APPLIED but which is
        # missing from the freshly (re)loaded L3 index.
        reconcile_result = writer.reconcile_l3()
        assert reconcile_result == {"checked": total, "repaired": applied_before_kill}
    finally:
        fresh_l2.close()

    final_l3 = L3SemanticTM(l3_path, use_gpu=False)
    assert len(final_l3) == total, "reconciliation must restore every lost entry with no duplicates"
    final_l2 = L2PersistentTM(l2_path)
    try:
        assert len(final_l2) == total
        for i in (0, applied_before_kill - 1, applied_before_kill, total - 1):
            entry = final_l2.exact_lookup(
                "docs.aspose.org", "en", "de", f"crash-boundary-text-{i}"
            )
            assert entry is not None
            assert entry.translation == f"crash-boundary-ziel-{i}"

        # The repaired vector is not just counted -- it is actually retrievable.
        matches = final_l3.semantic_search(
            site_id="docs.aspose.org",
            src_lang="en",
            tgt_lang="de",
            query_text="crash-boundary-text-0",
            k=1,
            threshold=0.0,
        )
        assert matches and matches[0].translation == "crash-boundary-ziel-0"

        # Re-running reconciliation again must be a safe no-op (idempotent).
        idempotent_writer = TMIntentWriter(spool, final_l2, final_l3)
        assert idempotent_writer.reconcile_l3() == {"checked": total, "repaired": 0}
        assert len(final_l3) == total
    finally:
        final_l2.close()
