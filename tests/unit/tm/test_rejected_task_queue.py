from pathlib import Path

from src.tm.rejected_task_queue import RejectedTaskQueue
from src.tm.retry_records import RejectedTranslationTask


def _task() -> RejectedTranslationTask:
    return RejectedTranslationTask.from_mapping({
        "campaign_id": "campaign", "site_id": "docs.aspose.org",
        "source_path": "content/en/page.md", "output_path": "content/de/page.md",
        "source_sha256": "a" * 64, "target_lang": "de",
        "failure_category": "validation", "failure_fingerprint": "fingerprint",
        "retry_budget": 2, "model_target": "professionalize_llm",
    })


def test_health_reports_active_age_and_expired_claim_without_task_payload(tmp_path: Path):
    queue = RejectedTaskQueue(tmp_path / "retry.sqlite")
    queue.enqueue(_task())
    claimed = queue.claim("worker", lease_seconds=1)
    assert len(claimed) == 1
    health = queue.health(now=10**11)
    assert health["CLAIMED"] == 1
    assert health["expired_claims"] == 1
    assert health["oldest_active_age_seconds"] is not None
    assert "content" not in str(health)


def test_operator_dead_letter_preserves_terminal_receipt_immutability(tmp_path: Path):
    queue = RejectedTaskQueue(tmp_path / "retry.sqlite")
    task_id = queue.enqueue(_task())
    queue.operator_dead_letter(task_id, "operator_cancelled")
    assert queue.get(task_id)["state"] == "DEAD_LETTER"
    try:
        queue.operator_dead_letter(task_id, "again")
    except RuntimeError as exc:
        assert "already terminal" in str(exc)
    else:  # pragma: no cover - makes the terminal invariant explicit
        raise AssertionError("terminal task must not be rewritten")


def test_reconcile_requeues_only_expired_claims(tmp_path: Path):
    queue = RejectedTaskQueue(tmp_path / "retry.sqlite")
    task_id = queue.enqueue(_task())
    queue.claim("crashed", lease_seconds=1)
    assert queue.requeue_expired_claims(now=10**11) == 1
    assert queue.get(task_id)["state"] == "QUEUED"
