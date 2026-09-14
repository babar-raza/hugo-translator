"""TC-APT-047 regression guard for the process-level shard launcher.

Two invariants the plan's acceptance criterion names: GPU-bound shards never run
concurrently with each other, and the cross-process ledger never double-accepts an
output.  Both are asserted at the launcher's own selection/verification boundary so
the guard survives without a GPU or a live campaign.
"""

import json
from pathlib import Path

import yaml

import pytest

from scripts.campaign.launch_parallel_campaign_shards import (
    GPU_PRIMARY_LOCALES,
    _child_command,
    assign_shard_groups,
    duplicate_receipts,
    group_status_line,
    main,
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


def _kwargs(tmp_path: Path, child: str) -> dict:
    return dict(
        config_root=tmp_path / "config",
        campaign_manifest=tmp_path / "manifest.yaml",
        ledger_root=tmp_path / "campaigns",
        device="cuda",
        max_gpu_memory_percent=50,
        gpu_shard_memory_percent=80,
        gpu_locales=GPU_PRIMARY_LOCALES,
        child=child,
    )


@pytest.mark.parametrize("child", ["gate5", "worker"])
def test_gpu_shard_gets_its_own_vram_budget(tmp_path, child):
    manifest = _load(tmp_path)
    shards = {s["locale"]: s for s in manifest.shards(resume_receipts=set(), max_outputs=250)}
    kwargs = _kwargs(tmp_path, child)

    gpu_command = _child_command(shards=[shards["ja"]], **kwargs)
    api_command = _child_command(shards=[shards["de"]], **kwargs)

    assert gpu_command[gpu_command.index("--max-gpu-memory-percent") + 1] == "80"
    assert api_command[api_command.index("--max-gpu-memory-percent") + 1] == "50"


def test_worker_child_still_runs_the_governed_zero_defect_path(tmp_path):
    manifest = _load(tmp_path)
    shard = next(iter(manifest.shards(resume_receipts=set(), max_outputs=250)))

    command = _child_command(shards=[shard], **_kwargs(tmp_path, "worker"))

    assert command[command.index("--validation-policy") + 1] == "zero-defect"
    assert command[command.index("--campaign-shard") + 1] == shard["shard_id"]


def test_gate5_child_receives_the_ledger_root_the_parent_verifies(tmp_path):
    """The worker child has no --ledger-root flag; the gate5 child must carry it."""
    manifest = _load(tmp_path)
    shard = next(iter(manifest.shards(resume_receipts=set(), max_outputs=250)))
    kwargs = _kwargs(tmp_path, "gate5")

    command = _child_command(shards=[shard], **kwargs)

    assert command[1].endswith("run_gate5_batch.py")
    assert Path(command[command.index("--ledger-root") + 1]) == kwargs["ledger_root"]
    assert command[command.index("--shard-id") + 1] == shard["shard_id"]
    assert "--resume" in command


def test_gate5_child_carries_campaign_tm_spool_and_api_concurrency_switch(tmp_path):
    manifest = _load(tmp_path)
    shard = next(iter(manifest.shards(resume_receipts=set(), max_outputs=250)))
    spool = tmp_path / "campaign-intents.sqlite3"

    command = _child_command(
        shards=[shard],
        tm_intent_spool_path=spool,
        no_force_serialize=True,
        **_kwargs(tmp_path, "gate5"),
    )

    assert Path(command[command.index("--tm-intent-spool-path") + 1]) == spool
    assert "--no-force-serialize" in command


def test_worker_child_refuses_a_ledger_root_it_cannot_receive(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(_manifest_dict(tmp_path)), encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--campaign-manifest",
                str(manifest_path),
                "--wait",
                "--child",
                "worker",
                "--ledger-root",
                str(tmp_path / "elsewhere"),
            ]
        )

    assert "--child gate5" in str(excinfo.value)


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


def test_shard_groups_amortise_startup_across_one_child_each(tmp_path):
    """Every pending shard is handed out once, so startup is paid max_workers times."""
    manifest = _load(tmp_path)
    shards = list(manifest.shards(resume_receipts=set(), max_outputs=250))

    groups = assign_shard_groups(shards, max_workers=2)

    assert len(groups) == 2
    handed_out = [s["shard_id"] for group in groups for s in group]
    assert sorted(handed_out) == sorted(s["shard_id"] for s in shards)
    assert len(handed_out) == len(set(handed_out)), "a shard was handed to two children"


def test_all_gpu_shards_land_in_one_group(tmp_path):
    """Same process means sequential, which is how GPU shards never overlap."""
    manifest = _load(tmp_path)
    shards = list(manifest.shards(resume_receipts=set(), max_outputs=250))

    groups = assign_shard_groups(shards, max_workers=3)

    carrying_gpu = [
        group for group in groups
        if any(s["locale"] in GPU_PRIMARY_LOCALES for s in group)
    ]
    assert len(carrying_gpu) == 1
    assert sorted(s["locale"] for s in carrying_gpu[0] if s["locale"] in GPU_PRIMARY_LOCALES) == [
        "hu", "ja", "ro",
    ]


def test_group_status_line_is_bounded_for_portfolio_scale(tmp_path):
    manifest = _load(tmp_path)
    shard = next(iter(manifest.shards(resume_receipts=set(), max_outputs=250)))
    group = [dict(shard, shard_id=f"s{index}") for index in range(10_000)]

    line = group_status_line(2, group)

    assert line == "child 2: shard_count=10000 preview=s0, s1, s2, ..."
    assert len(line) < 100


def test_gpu_group_is_not_also_given_the_largest_api_share(tmp_path):
    """It carries the slow GPU work, so it gets no MORE API shards than any peer."""
    manifest = _load(tmp_path)
    shards = list(manifest.shards(resume_receipts=set(), max_outputs=250))

    groups = assign_shard_groups(shards, max_workers=2)

    def api_count(group):
        return len([s for s in group if s["locale"] not in GPU_PRIMARY_LOCALES])

    gpu_group = next(g for g in groups if any(s["locale"] in GPU_PRIMARY_LOCALES for s in g))
    others = [g for g in groups if g is not gpu_group]
    assert others, "expected more than one group"
    assert api_count(gpu_group) <= min(api_count(g) for g in others)


def test_a_group_child_gets_one_shard_id_argument_per_shard(tmp_path):
    manifest = _load(tmp_path)
    shards = list(manifest.shards(resume_receipts=set(), max_outputs=250))
    group = [s for s in shards if s["locale"] in ("de", "es")]

    command = _child_command(shards=group, **_kwargs(tmp_path, "gate5"))

    assert command.count("--shard-id") == 2
    passed = [command[i + 1] for i, token in enumerate(command) if token == "--shard-id"]
    assert sorted(passed) == sorted(s["shard_id"] for s in group)


def test_worker_child_refuses_a_group_it_cannot_run(tmp_path):
    """The legacy worker takes one --campaign-shard; dropping the rest silently is worse."""
    manifest = _load(tmp_path)
    group = list(manifest.shards(resume_receipts=set(), max_outputs=250))[:2]

    with pytest.raises(ValueError, match="one shard per process"):
        _child_command(shards=group, **_kwargs(tmp_path, "worker"))
