import hashlib
import json

import pytest

from scripts.campaign.merge_campaign_journals import merge
from src.workers.campaign_runner import CampaignLedger


def receipt(output: str, digest: str = "a" * 64) -> dict:
    return {"output_path": output, "output_sha256": digest, "receipt_sha256": digest}


def test_workers_write_exclusive_journals_and_reads_aggregate(tmp_path):
    first = CampaignLedger(tmp_path, "campaign", "worker-00")
    second = CampaignLedger(tmp_path, "campaign", "worker-01")
    first.append_receipt(receipt("content/a.md"))
    second.append_receipt(receipt("content/b.md", "b" * 64))
    assert first._process_lock_path != second._process_lock_path
    assert set(CampaignLedger(tmp_path, "campaign").receipts()) == {"content/a.md", "content/b.md"}


def test_merge_is_deterministic_and_archives_partitions(tmp_path):
    CampaignLedger(tmp_path, "campaign", "worker-01").append_receipt(receipt("content/b.md", "b" * 64))
    CampaignLedger(tmp_path, "campaign", "worker-00").append_receipt(receipt("content/a.md"))
    result = merge(tmp_path / "campaign")
    rows = [json.loads(line) for line in (tmp_path / "campaign" / "acceptance_receipts.jsonl").read_text().splitlines()]
    assert result["receipts_added"] == 2
    assert [row["output_path"] for row in rows] == ["content/a.md", "content/b.md"]
    assert not (tmp_path / "campaign" / "journals").exists() or not list((tmp_path / "campaign" / "journals").iterdir())


def test_conflicting_partition_receipts_fail_closed(tmp_path):
    CampaignLedger(tmp_path, "campaign", "worker-00").append_receipt(receipt("content/a.md"))
    CampaignLedger(tmp_path, "campaign", "worker-01").append_receipt(receipt("content/a.md", "b" * 64))
    with pytest.raises((RuntimeError, ValueError), match="conflicting"):
        merge(tmp_path / "campaign")


def test_new_worker_sees_merged_receipts_without_writing_canonical(tmp_path):
    CampaignLedger(tmp_path, "campaign", "worker-00").append_receipt(receipt("content/a.md"))
    merge(tmp_path / "campaign")
    canonical = tmp_path / "campaign" / "acceptance_receipts.jsonl"
    before = canonical.read_bytes()
    resumed = CampaignLedger(tmp_path, "campaign", "worker-07")
    assert "content/a.md" in resumed.receipts()
    resumed.append_receipt(receipt("content/b.md", "b" * 64))
    assert canonical.read_bytes() == before
    assert set(resumed.receipts()) == {"content/a.md", "content/b.md"}
