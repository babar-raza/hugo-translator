"""Unit tests for scripts/campaign/invalidate_stale_campaign_receipts.py.

Covers a real defect found live 2026-09-17: a receipt whose committed output
file was later removed OR modified by ANOTHER session's own governance (this
is a real, shared, multi-session content repo -- both a Deletion Governance
Record removing a stale shadow page, and a separate peer session's legitimate
frontmatter fix, hit the same code path in one session) made every future
unattended startup crash with an unhandled ValueError -- "Stale receipt
recovery failed." blocked the operator's real elevated run. Neither case is a
config-policy question this script exists to answer; both must be dropped as
orphaned, never queued for retranslation (which would overwrite another
session's already-governed change) and never a hard stop.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from scripts.campaign.invalidate_stale_campaign_receipts import main


def _manifest(tmp_path: Path, content_repo: Path) -> dict[str, Any]:
    return {
        "campaign_id": "test-campaign",
        "config_fingerprint": "current-config",
        "content_repo": str(content_repo),
        "sources": [
            {
                "source_path": "content/site/family/platform/page/index.md",
                "outputs": {"fa": "content/site/family/platform/page/index.fa.md"},
            }
        ],
    }


def _receipt(output_path: str, sha256: str, config_fingerprint: str = "current-config") -> dict[str, Any]:
    row = {
        "output_path": output_path,
        "output_sha256": sha256,
        "config_fingerprint": config_fingerprint,
    }
    from src.workers.campaign_manifest import receipt_fingerprint

    row["receipt_sha256"] = receipt_fingerprint(row)
    return row


def test_a_receipt_whose_output_file_no_longer_exists_is_dropped_not_crashed(tmp_path):
    content_repo = tmp_path / "content_repo"
    content_repo.mkdir()
    manifest_dict = _manifest(tmp_path, content_repo)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest_dict), encoding="utf-8")

    # The receipted output file does NOT exist -- e.g. another session's
    # governed deletion removed it after this campaign committed it.
    receipt = _receipt("content/site/family/platform/page/index.fa.md", "a" * 64)
    ledger_dir = tmp_path / "ledger" / "test-campaign"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "acceptance_receipts.jsonl").write_text(
        json.dumps(receipt) + "\n", encoding="utf-8"
    )

    code = main([
        "--manifest", str(manifest_path),
        "--ledger-root", str(tmp_path / "ledger"),
        "--execute",
    ])
    assert code == 0

    # Dropped from the active receipts file -- never re-included.
    remaining = (ledger_dir / "acceptance_receipts.jsonl").read_text(encoding="utf-8")
    assert remaining.strip() == ""

    # Recorded as evidence, not silently discarded.
    orphaned = [
        json.loads(line)
        for line in (ledger_dir / "orphaned_receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(orphaned) == 1
    assert orphaned[0]["reason"] == "receipted_output_missing_from_content_repo"
    assert orphaned[0]["prior_receipt"]["output_path"] == receipt["output_path"]

    # Never queued for retranslation -- that would resurrect a file another
    # governance process deliberately removed.
    rewritten_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert "replace_existing" not in rewritten_manifest["sources"][0]


def test_a_receipt_whose_output_exists_but_has_different_content_is_also_dropped(tmp_path):
    """A real second case (2026-09-17, same investigation): a peer session's
    own legitimate content fix (stripping a deploy-breaking frontmatter
    field) changed a file this campaign had a receipt for. Not corruption,
    not a config-policy question -- drop the stale receipt like a missing
    file, never overwrite another session's already-governed change.
    """
    content_repo = tmp_path / "content_repo"
    output_path = content_repo / "content/site/family/platform/page/index.fa.md"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("a peer session's legitimate edit", encoding="utf-8", newline="")

    manifest_dict = _manifest(tmp_path, content_repo)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest_dict), encoding="utf-8")

    receipt = _receipt("content/site/family/platform/page/index.fa.md", "a" * 64)
    ledger_dir = tmp_path / "ledger" / "test-campaign"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "acceptance_receipts.jsonl").write_text(
        json.dumps(receipt) + "\n", encoding="utf-8"
    )

    code = main([
        "--manifest", str(manifest_path),
        "--ledger-root", str(tmp_path / "ledger"),
        "--execute",
    ])
    assert code == 0

    remaining = (ledger_dir / "acceptance_receipts.jsonl").read_text(encoding="utf-8")
    assert remaining.strip() == ""
    orphaned = [
        json.loads(line)
        for line in (ledger_dir / "orphaned_receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(orphaned) == 1
    rewritten_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert "replace_existing" not in rewritten_manifest["sources"][0]


def test_a_receipt_under_an_old_config_fingerprint_is_still_queued_for_retranslation(tmp_path):
    content_repo = tmp_path / "content_repo"
    output_path = content_repo / "content/site/family/platform/page/index.fa.md"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("real content", encoding="utf-8", newline="")
    sha = hashlib.sha256(b"real content").hexdigest()

    manifest_dict = _manifest(tmp_path, content_repo)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest_dict), encoding="utf-8")

    receipt = _receipt(
        "content/site/family/platform/page/index.fa.md", sha, config_fingerprint="old-config"
    )
    ledger_dir = tmp_path / "ledger" / "test-campaign"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "acceptance_receipts.jsonl").write_text(
        json.dumps(receipt) + "\n", encoding="utf-8"
    )

    code = main([
        "--manifest", str(manifest_path),
        "--ledger-root", str(tmp_path / "ledger"),
        "--execute",
    ])
    assert code == 0

    rewritten_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert rewritten_manifest["sources"][0]["replace_existing"]["fa"]["expected_sha256"] == sha
