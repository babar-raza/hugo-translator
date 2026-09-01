import json
from pathlib import Path

import pytest
import yaml

from src.workers.campaign_manifest import CampaignManifest, CampaignManifestError
from src.workers.campaign_runner import CampaignLedger


def _manifest(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "campaign_id": "pilot",
        "validation_policy": "zero-defect",
        "content_repo": str(tmp_path),
        "content_repo_sha": "a" * 40,
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64,
        "target_locales": ["es", "fr"],
        "expected_source_count": 1,
        "expected_output_count": 2,
        "sources": [
            {
                "site_id": "docs.aspose.org",
                "family": "words",
                "platform": "net",
                "source_path": "content/docs.aspose.org/en/words/net/page.md",
                "source_sha256": "d" * 64,
                "wave": 2,
                "outputs": {
                    "es": "content/docs.aspose.org/es/words/net/page.md",
                    "fr": "content/docs.aspose.org/fr/words/net/page.md",
                },
            }
        ],
    }


def test_manifest_loads_and_enumerates_deterministic_jobs(tmp_path):
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest(tmp_path)), encoding="utf-8")
    manifest = CampaignManifest.load(path)
    jobs = list(manifest.jobs())
    assert len(jobs) == 2
    assert [job[1] for job in jobs] == ["es", "fr"]


def test_manifest_rejects_path_traversal(tmp_path):
    payload = _manifest(tmp_path)
    payload["sources"][0]["outputs"]["es"] = "../outside.md"
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(CampaignManifestError, match="unsafe output"):
        CampaignManifest.load(path)


def test_manifest_rejects_locale_drift(tmp_path):
    payload = _manifest(tmp_path)
    del payload["sources"][0]["outputs"]["fr"]
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(CampaignManifestError, match="output locales"):
        CampaignManifest.load(path)


def test_ledger_never_accepts_candidate_text(tmp_path):
    ledger = CampaignLedger(tmp_path, "pilot")
    with pytest.raises(ValueError, match="candidate text"):
        ledger.append_receipt(
            {"output_path": "page.md", "content": "rejected translation"}
        )
    assert not ledger.receipts_path.exists()


def test_failure_ledger_contains_metadata_only(tmp_path):
    ledger = CampaignLedger(tmp_path, "pilot")
    ledger.append_failure(
        source_path="source.md",
        output_path="es/page.md",
        target_lang="es",
        error="gate 30 failed",
    )
    row = json.loads(ledger.failures_path.read_text(encoding="utf-8"))
    assert row["reason"] == "gate 30 failed"
    assert row["gate"] == "pipeline"
    assert row["job_id"]
    assert "content" not in row


def test_shards_are_locale_scoped_and_bounded(tmp_path):
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest(tmp_path)), encoding="utf-8")
    manifest = CampaignManifest.load(path)

    shards = list(manifest.shards(max_outputs=1))

    assert len(shards) == 2
    assert all(len(shard["jobs"]) == 1 for shard in shards)
    assert {shard["locale"] for shard in shards} == {"es", "fr"}
    assert all(shard["site_id"] == "docs.aspose.org" for shard in shards)
