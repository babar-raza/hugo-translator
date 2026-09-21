"""OP-01: unit coverage for CampaignSupervisor's lifecycle, heartbeat, reconciliation,
and adoption-check plumbing in a single process (no crash simulation -- see
``tests/integration/test_campaign_supervisor_crash_recovery.py`` for real
process-interruption recovery proof).

Follows the disposable-repository convention from
``tests/unit/workers/test_campaign_manifest.py`` (tmp_path + real ``git init`` +
``CampaignRunner(translation_engine=object(), ...)``): OP-01 is about supervising
receipt-backed batch commits, not translation correctness, so these tests seed
receipts/output files directly rather than faking a full TranslationEngine.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from src.workers.campaign_manifest import CampaignManifest, sha256_file
from src.workers.campaign_runner import CampaignRunner
from src.workers.campaign_supervisor import CampaignSupervisor


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "pilot"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "campaign@example.invalid"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Campaign Test"], cwd=path, check=True, capture_output=True
    )


def _manifest_payload(content_repo: Path, locales=("es", "fr")) -> dict:
    source = content_repo / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("source content", encoding="utf-8")
    return {
        "schema_version": 1,
        "campaign_id": "pilot",
        "validation_policy": "zero-defect",
        "content_repo": str(content_repo),
        "content_repo_sha": "a" * 40,
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64,
        "knowledge_fingerprints": {},
        "target_locales": list(locales),
        "expected_source_count": 1,
        "expected_output_count": len(locales),
        "retry_policy": {
            "primary_model": "m2m100_418m",
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "professionalize_llm",
        },
        "commit_policy": {
            "branch": "pilot",
            "max_outputs_per_commit": 250,
            "push": False,
        },
        "sources": [
            {
                "site_id": "docs.aspose.org",
                "family": "words",
                "platform": "net",
                "source_path": "content/docs.aspose.org/en/words/net/page.md",
                "source_sha256": sha256_file(source),
                "wave": 2,
                "outputs": {
                    locale: f"content/docs.aspose.org/{locale}/words/net/page.md"
                    for locale in locales
                },
            }
        ],
    }


def _build_runner(tmp_path: Path, locales=("es", "fr")) -> CampaignRunner:
    content_repo = tmp_path / "content"
    _init_repo(content_repo)
    payload = _manifest_payload(content_repo, locales=locales)
    marker = content_repo / "baseline.txt"
    marker.write_text("baseline", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=content_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"], cwd=content_repo, check=True, capture_output=True
    )
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    return CampaignRunner(
        manifest=manifest,
        translation_engine=object(),
        translator_repo=tmp_path / "translator",
        ledger_root=tmp_path / "ledger",
    )


def _write_accepted_receipt(runner: CampaignRunner, locale: str, relative: str) -> None:
    """Seed a fully valid, all-44-gates-pass receipt the way an accepted job would --
    matches ``test_resume_rejects_tampered_receipt_fingerprint``'s construction."""
    source = runner.manifest.sources[0]
    output = runner.content_repo / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"accepted {locale} content", encoding="utf-8")
    runner.ledger.append_receipt(
        {
            "campaign_id": runner.manifest.campaign_id,
            "source_path": source.source_path,
            "output_path": relative,
            "source_sha256": source.source_sha256,
            "output_sha256": sha256_file(output),
            "target_lang": locale,
            "validation_policy": "zero-defect",
            "config_fingerprint": runner.manifest.config_fingerprint,
            "model_fingerprint": "fixture",
            "gate_results": {str(index): {"passed": True} for index in range(1, 45)},
        }
    )


def _fake_run_shard_jobs(runner: CampaignRunner):
    def _run(shard_id: str) -> None:
        shards = {
            str(shard["shard_id"]): shard
            for shard in runner.manifest.shards(
                resume_receipts=set(runner._validated_resume_receipts()), max_outputs=1
            )
        }
        shard = shards[shard_id]
        for _source, locale, expected_output in shard["jobs"]:
            _write_accepted_receipt(runner, locale, expected_output)

    return _run


def test_init_disables_runner_auto_commit_without_touching_other_policy(tmp_path):
    runner = _build_runner(tmp_path)
    assert runner.manifest.commit_policy.get("enabled", True) is True
    CampaignSupervisor(runner=runner, heartbeat_path=tmp_path / "hb.json")
    assert runner.manifest.commit_policy["enabled"] is False
    # Everything else in commit_policy is preserved unchanged.
    assert runner.manifest.commit_policy["branch"] == "pilot"
    assert runner.manifest.commit_policy["max_outputs_per_commit"] == 250


def test_default_run_shard_jobs_delegates_to_runner_run(tmp_path):
    """Production wiring: absent an injected fake, a shard is executed via exactly
    ``runner.run(resume=True, shard_ids={shard_id})`` -- the re-entrant call shape
    OP-01's research identified as correct."""
    runner = _build_runner(tmp_path)
    calls = []
    runner.run = lambda **kwargs: calls.append(kwargs)  # type: ignore[method-assign]
    supervisor = CampaignSupervisor(runner=runner, heartbeat_path=tmp_path / "hb.json")
    supervisor._default_run_shard_jobs("shard-x")
    assert calls == [{"resume": True, "shard_ids": {"shard-x"}}]


def test_adoption_check_normalizes_subprocess_args_and_substitutes_shard_id(tmp_path):
    runner = _build_runner(tmp_path)
    supervisor = CampaignSupervisor(
        runner=runner,
        heartbeat_path=tmp_path / "hb.json",
        adoption_check=[
            sys.executable,
            "-c",
            "import json, sys; print(json.dumps(sys.argv[1]))",
            "{shard_id}",
        ],
    )
    result = supervisor._adoption_check("shard-42")
    assert result == "shard-42"


def test_adoption_check_defaults_to_noop(tmp_path):
    runner = _build_runner(tmp_path)
    supervisor = CampaignSupervisor(runner=runner, heartbeat_path=tmp_path / "hb.json")
    assert supervisor._adoption_check("shard-1") is None


def test_pending_commit_paths_detects_receipted_dirty_output(tmp_path):
    runner = _build_runner(tmp_path)
    supervisor = CampaignSupervisor(runner=runner, heartbeat_path=tmp_path / "hb.json")
    assert supervisor._pending_commit_paths() == set()

    _write_accepted_receipt(runner, "es", "content/docs.aspose.org/es/words/net/page.md")
    assert supervisor._pending_commit_paths() == {"content/docs.aspose.org/es/words/net/page.md"}

    supervisor._commit_shard("shard-fixture")
    assert supervisor._pending_commit_paths() == set()


def test_run_progresses_through_two_shards_and_writes_lifecycle_heartbeats(tmp_path):
    runner = _build_runner(tmp_path, locales=("es", "fr"))
    heartbeat_path = tmp_path / "logs" / "supervisor.heartbeat"
    state_path = tmp_path / "logs" / "supervisor.state.json"
    seen_lifecycles: list[str] = []
    adopted_shards: list[str] = []

    def _adoption_check(shard_id: str):
        adopted_shards.append(shard_id)
        return {"adopted": [shard_id]}

    supervisor = CampaignSupervisor(
        runner=runner,
        heartbeat_path=heartbeat_path,
        state_path=state_path,
        adoption_check=_adoption_check,
        run_shard_jobs=_fake_run_shard_jobs(runner),
    )
    original_set_lifecycle = supervisor._set_lifecycle

    def _recording_set_lifecycle(lifecycle, **kwargs):
        seen_lifecycles.append(lifecycle)
        return original_set_lifecycle(lifecycle, **kwargs)

    supervisor._set_lifecycle = _recording_set_lifecycle  # type: ignore[method-assign]

    result = supervisor.run()

    assert result["accepted"] == 2
    assert result["lifecycle"] == "DONE"
    assert len(adopted_shards) == 2
    # Both shards actually progressed through every named lifecycle stage.
    assert seen_lifecycles[0] == "STARTING"
    assert seen_lifecycles[-1] == "DONE"
    for stage in ("AWAITING_ADOPTION", "COMMITTING", "SHARD_DONE"):
        assert seen_lifecycles.count(stage) == 2
    assert sum(1 for entry in seen_lifecycles if entry.startswith("RUNNING_SHARD:")) == 2

    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["lifecycle"] == "DONE"
    assert heartbeat["receipts_written"] == 2
    assert heartbeat["last_commit_sha"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    # Heartbeat and state are written moments apart (each stamps its own
    # datetime.now()), so compare everything except the timestamp itself.
    assert {k: v for k, v in state.items() if k != "timestamp"} == {
        k: v for k, v in heartbeat.items() if k != "timestamp"
    }

    # Governed commit actually happened: two commits beyond the baseline, one per shard.
    log = subprocess.run(
        ["git", "log", "--pretty=%s"],
        cwd=runner.content_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert len(log) == 3  # baseline + es shard + fr shard
    assert all(line.startswith("content(words/net):") for line in log[:2])
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=runner.content_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""


def test_run_is_idempotent_when_already_complete(tmp_path):
    """A second .run() call on an already-fully-committed campaign is a clean no-op
    DONE -- exactly the shape a restarted supervisor takes once nothing remains."""
    runner = _build_runner(tmp_path, locales=("es",))
    supervisor = CampaignSupervisor(
        runner=runner,
        heartbeat_path=tmp_path / "hb.json",
        run_shard_jobs=_fake_run_shard_jobs(runner),
    )
    first = supervisor.run()
    assert first["accepted"] == 1

    second_runner = CampaignRunner(
        manifest=CampaignManifest.load(tmp_path / "manifest.yaml"),
        translation_engine=object(),
        translator_repo=tmp_path / "translator",
        ledger_root=tmp_path / "ledger",
    )
    second_supervisor = CampaignSupervisor(
        runner=second_runner,
        heartbeat_path=tmp_path / "hb.json",
        run_shard_jobs=_fake_run_shard_jobs(second_runner),
    )
    second = second_supervisor.run()
    assert second["accepted"] == 1
    assert second["last_commit_sha"] is None  # nothing new to commit

    log = subprocess.run(
        ["git", "log", "--pretty=%s"],
        cwd=runner.content_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert len(log) == 2  # baseline + the one shard commit, never duplicated


def test_run_reraises_and_marks_failed_on_unexpected_exception(tmp_path):
    runner = _build_runner(tmp_path, locales=("es",))

    def _boom(shard_id: str) -> None:
        raise RuntimeError("simulated unexpected failure")

    supervisor = CampaignSupervisor(
        runner=runner, heartbeat_path=tmp_path / "hb.json", run_shard_jobs=_boom
    )
    with pytest.raises(RuntimeError, match="simulated unexpected failure"):
        supervisor.run()
    heartbeat = json.loads((tmp_path / "hb.json").read_text(encoding="utf-8"))
    assert heartbeat["lifecycle"] == "FAILED"
