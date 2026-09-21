"""TC-PORT-LLM-009: a heal ticket / advisory-hold-skip record is best-effort
observability, not a correctness-critical write -- losing one is recoverable
(the next attempt on this cell regenerates it). Confirmed live under a real
4-worker soak: enough jobs hit the QU-02/QU-38 quarantine-refresh branches in
the same burst (a heavily-contaminated candidate pool) that one thread's
FileLock(ledger-process.lock, timeout=30) exceeded 30s, raised LockError, and
-- uncaught -- crashed the entire worker process via the ThreadPoolExecutor
future, losing every other job still in flight on the other 3 threads, not
just this one ticket write.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from src.utils.file_lock import FileLock, LockError
from src.workers.campaign_runner import CampaignLedger, CampaignRunner


def _make_runner(tmp_path):
    campaigns_root = tmp_path / "campaigns"
    campaigns_root.mkdir()
    ledger = CampaignLedger(campaigns_root / "gate5-stub", "gate5-stub")

    runner = CampaignRunner.__new__(CampaignRunner)
    runner.ledger = ledger
    runner.manifest = SimpleNamespace(
        campaign_id="gate5-stub",
        retry_policy={"llm_escalation_mode": "immediate"},
    )
    return runner


def test_a_lock_timeout_writing_a_heal_ticket_does_not_crash_the_job(tmp_path):
    runner = _make_runner(tmp_path)
    source = SimpleNamespace(source_path="content/blog.aspose.org/pdf/go/index.md")

    with patch.object(CampaignLedger, "_append", side_effect=LockError("Failed to acquire lock after 30.0s: x")):
        runner._append_heal_ticket(
            shard={"shard_id": "s0", "site_id": "blog.aspose.org"},
            source=source,
            locale="ja",
            expected_output="content/blog.aspose.org/pdf/go/index.ja.md",
        )
    # No exception propagated -- that is the entire point of this test.


def test_a_lock_timeout_writing_an_advisory_hold_skip_does_not_crash_the_job(tmp_path):
    runner = _make_runner(tmp_path)
    source = SimpleNamespace(source_path="content/blog.aspose.org/pdf/go/index.md")

    with patch.object(CampaignLedger, "_append", side_effect=LockError("Failed to acquire lock after 30.0s: x")):
        runner._append_advisory_hold_skip(
            shard={"shard_id": "s0", "site_id": "blog.aspose.org"},
            source=source,
            locale="ja",
            hold={"reason": "investigating", "expiry": None, "created_at": None},
        )
    # No exception propagated -- that is the entire point of this test.


def test_a_lock_timeout_writing_the_summary_does_not_crash_the_run(tmp_path):
    """A third, distinct call site hitting the exact same pattern -- found
    during a real 4-worker soak confirming run, after the heal-ticket and
    advisory-hold-skip fixes above already landed. write_summary is called
    repeatedly through _run_locked (progress checkpoints, not just the final
    summary), so this path is hit far more often than the heal-ticket path
    and crashed the whole worker process the same way."""
    campaigns_root = tmp_path / "campaigns"
    campaigns_root.mkdir()
    ledger = CampaignLedger(campaigns_root / "gate5-stub", "gate5-stub")

    with patch.object(
        FileLock, "__enter__", side_effect=LockError("Failed to acquire lock after 30.0s: x")
    ):
        ledger.write_summary({"accepted": 1, "status": "PARTIAL_WITH_TICKETS"})
    # No exception propagated -- that is the entire point of this test.


def test_summary_is_still_written_when_the_lock_is_free(tmp_path):
    campaigns_root = tmp_path / "campaigns"
    campaigns_root.mkdir()
    ledger = CampaignLedger(campaigns_root / "gate5-stub", "gate5-stub")

    ledger.write_summary({"accepted": 1, "status": "PARTIAL_WITH_TICKETS"})

    assert ledger.summary_path.is_file()
    assert json.loads(ledger.summary_path.read_text(encoding="utf-8"))["accepted"] == 1


def test_a_heal_ticket_is_still_written_when_the_lock_is_free(tmp_path):
    """Regression guard: the try/except must not swallow the real write on
    the (overwhelmingly common) non-contended path."""
    runner = _make_runner(tmp_path)
    source = SimpleNamespace(source_path="content/blog.aspose.org/pdf/go/index.md")

    runner._append_heal_ticket(
        shard={"shard_id": "s0", "site_id": "blog.aspose.org"},
        source=source,
        locale="ja",
        expected_output="content/blog.aspose.org/pdf/go/index.ja.md",
    )

    heal_queue_path = runner.ledger.root.parent / "heal_queue.jsonl"
    assert heal_queue_path.is_file()
    assert "content/blog.aspose.org/pdf/go/index.md" in heal_queue_path.read_text(encoding="utf-8")
