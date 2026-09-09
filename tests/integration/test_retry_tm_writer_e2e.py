from hashlib import sha256
from pathlib import Path

from src.tm.intent_spool import TMIntentSpool
from src.tm.l2_persistent import L2PersistentTM
from src.tm.retry_records import RejectedTranslationTask
from src.tm.rejected_task_queue import RejectedTaskQueue
from src.workers.professionalize_retry_worker import ProfessionalizeRetryWorker, build_default_validator
from src.workers.tm_intent_writer import main as writer_main
from src.workers.campaign_runner import CampaignLedger


class OfflineProvider:
    def generate(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        assert "complete Hugo document" in system_prompt
        assert user_text.replace("\r\n", "\n") == "# source\n"
        return "# translated\n", 3, 2


def test_accepted_source_retry_receipt_reaches_real_single_writer_l2(tmp_path: Path):
    source = tmp_path / "content/en/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("# source\n", encoding="utf-8")
    campaigns_root = tmp_path / "data/campaigns"
    queue = RejectedTaskQueue(campaigns_root / "rejected_tasks.sqlite3")
    spool_path = tmp_path / "intents.sqlite"
    spool = TMIntentSpool(spool_path)
    task = RejectedTranslationTask.from_mapping({
        "campaign_id": "campaign", "site_id": "docs.aspose.org",
        "source_path": "content/en/page.md", "output_path": "content/de/page.md",
        "source_sha256": sha256(source.read_bytes()).hexdigest(), "target_lang": "de",
        "failure_category": "structure", "failure_fingerprint": "f", "retry_budget": 1,
        "model_target": "professionalize_llm",
    })
    task_id = queue.enqueue(task)
    worker = ProfessionalizeRetryWorker(
        queue=queue, intent_spool=spool, provider=OfflineProvider(), repository_root=tmp_path,
        validate_document=build_default_validator(), live_mode=True,
    )

    assert worker.run_once(owner="retry")["accepted"] == 1
    receipt = queue.get(task_id)["receipt"]
    assert receipt["tm_intent_id"] and "translated" not in str(receipt)
    # The originating campaign can aggregate the terminal retry receipt
    # without reading candidate bytes or relying on process-local state.
    ledger = CampaignLedger(campaigns_root, "campaign")
    assert ledger.model_outcomes()["professionalize_llm"]["accepted"] == 1
    assert ledger.retry_queue_outcomes()[0]["receipt_id"] == receipt["receipt_id"]
    assert (tmp_path / "content/de/page.md").read_text(encoding="utf-8") == "# translated\n"
    assert writer_main([
        "--repository-root", str(tmp_path), "--spool-path", str(spool_path), "--owner", "writer", "--no-l3",
    ]) == 0
    l2 = L2PersistentTM(tmp_path / "data/tm/l2.lmdb")
    try:
        assert l2.exact_lookup(
            "docs.aspose.org", "en", "de", source.read_bytes().decode("utf-8")
        ).translation == "# translated\n"
    finally:
        l2.close()
