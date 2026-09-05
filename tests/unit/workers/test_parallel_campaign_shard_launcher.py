"""TC-APT-047 regression guard for the process-level shard launcher.

Two invariants the plan's acceptance criterion names: GPU-bound shards never run
concurrently with each other, and the cross-process ledger never double-accepts an
output.  Both are asserted at the launcher's own selection/verification boundary so
the guard survives without a GPU or a live campaign.
"""

import json
from pathlib import Path

import yaml

from scripts.campaign.launch_parallel_campaign_shards import (
    GPU_PRIMARY_LOCALES,
    _child_command,
    duplicate_receipts,
    partition_by_device,
    select_pending_shards,
)
from src.workers.campaign_manifest import CampaignManifest

LOCALES = ["de", "es", "hu", "ja", "ro"]


def _manifest_dict(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "campaign_id": "shard-launcher",
        "validation_policy": "zero-defect",
        "content_repo": str(tmp_path),
        "content_repo_sha": "a" * 40,
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64,
        "knowledge_fingerprints": {},
        "target_locales": list(LOCALES),
        "expected_source_count": 1,
        "expected_output_count": len(LOCALES),
        "retry_policy": {
            "primary_model": "professionalize_llm",
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "m2m100_418m",
        },
        "commit_policy": {
            "branch": "main",
            "max_outputs_per_commit": 250,
            "push": False,
        },
        "sources": [
            {
                "site_id": "blog.aspose.org",
                "family": "pdf",
                "platform": "cpp",
                "source_path": "content/blog.aspose.org/pdf/cpp/page/index.md",
                "source_sha256": "d" * 64,
                "wave": 0,
                "outputs": {
                    locale: f"content/blog.aspose.org/pdf/cpp/page/index.{locale}.md"
                    for locale in LOCALES
                },
            }
        ],
    }


def _load(tmp_path: Path) -> CampaignManifest:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest_dict(tmp_path)), encoding="utf-8")
    return CampaignManifest.load(path)


def test_partition_splits_gpu_bound_locales_from_api_bound(tmp_path):
    manifest = _load(tmp_path)
    shards = list(manifest.shards(resume_receipts=set(), max_outputs=250))
    gpu_bound, api_bound = partition_by_device(shards, GPU_PRIMARY_LOCALES)

    assert sorted(shard["locale"] for shard in gpu_bound) == ["hu", "ja", "ro"]
    assert sorted(shard["locale"] for shard in api_bound) == ["de", "es"]


def test_at_most_one_gpu_bound_shard_is_launched_per_wave(tmp_path):
    manifest = _load(tmp_path)
    ledger_root = tmp_path / "campaigns"

    selected = select_pending_shards(manifest, ledger_root, max_workers=4)

    gpu_selected = [s for s in selected if s["locale"] in GPU_PRIMARY_LOCALES]
    assert len(gpu_selected) == 1, "two GPU shards would contend for the same VRAM"
    # One GPU-bound shard plus every admissible API-bound shard, capped at max_workers.
    assert len(selected) == 3
    # The remaining slots go to API-bound shards, not to idle capacity.
    assert sorted(s["locale"] for s in selected if s["locale"] not in GPU_PRIMARY_LOCALES) == [
        "de",
        "es",
    ]


def test_selection_skips_shards_that_already_have_receipts(tmp_path):
    manifest = _load(tmp_path)
    ledger_root = tmp_path / "campaigns"
    campaign_dir = ledger_root / manifest.campaign_id
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "acceptance_receipts.jsonl").write_text(
        json.dumps(
            {"output_path": "content/blog.aspose.org/pdf/cpp/page/index.hu.md"},
        )
        + "\n",
        encoding="utf-8",
    )

    selected = select_pending_shards(manifest, ledger_root, max_workers=4)

    assert "hu" not in {s["locale"] for s in selected}
    # ja is the next GPU-bound shard and is still admissible on its own.
    assert [s["locale"] for s in selected if s["locale"] in GPU_PRIMARY_LOCALES] == ["ja"]


def test_gpu_shard_gets_its_own_vram_budget(tmp_path):
    manifest = _load(tmp_path)
    shards = {s["locale"]: s for s in manifest.shards(resume_receipts=set(), max_outputs=250)}
    kwargs = dict(
        config_root=tmp_path / "config",
        campaign_manifest=tmp_path / "manifest.yaml",
        device="cuda",
        max_gpu_memory_percent=50,
        gpu_shard_memory_percent=80,
        gpu_locales=GPU_PRIMARY_LOCALES,
    )

    gpu_command = _child_command(shard=shards["ja"], **kwargs)
    api_command = _child_command(shard=shards["de"], **kwargs)

    assert gpu_command[gpu_command.index("--max-gpu-memory-percent") + 1] == "80"
    assert api_command[api_command.index("--max-gpu-memory-percent") + 1] == "50"
    # Every child still runs the governed zero-defect campaign path.
    for command in (gpu_command, api_command):
        assert "--validation-policy" in command
        assert command[command.index("--validation-policy") + 1] == "zero-defect"
        assert command[command.index("--campaign-shard") + 1]


def test_duplicate_receipts_reports_a_double_accept(tmp_path):
    ledger_root = tmp_path / "campaigns"
    campaign_dir = ledger_root / "shard-launcher"
    campaign_dir.mkdir(parents=True)
    output = "content/blog.aspose.org/pdf/cpp/page/index.de.md"
    (campaign_dir / "acceptance_receipts.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"output_path": output, "target_lang": "de"}),
                json.dumps({"output_path": output, "target_lang": "de"}),
                json.dumps({"output_path": output.replace(".de.", ".es."), "target_lang": "es"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert duplicate_receipts(ledger_root, "shard-launcher") == {output: 2}


def test_duplicate_receipts_is_empty_for_a_clean_ledger(tmp_path):
    ledger_root = tmp_path / "campaigns"
    campaign_dir = ledger_root / "shard-launcher"
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "acceptance_receipts.jsonl").write_text(
        "\n".join(
            json.dumps({"output_path": f"content/x/index.{locale}.md"}) for locale in LOCALES
        )
        + "\n",
        encoding="utf-8",
    )

    assert duplicate_receipts(ledger_root, "shard-launcher") == {}
    assert duplicate_receipts(ledger_root, "no-such-campaign") == {}
