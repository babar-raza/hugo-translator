import json
import hashlib
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.workers.campaign_manifest import (
    CampaignManifest,
    CampaignManifestError,
    dirty_path_fingerprints,
    dirty_snapshot_fingerprint,
    receipt_fingerprint,
    sha256_file,
)
from src.workers.campaign_runner import CampaignLedger, CampaignRunner
from src.translation_engine.models import AcceptedTranslation
from src.model_runtime.llm_providers import BaseLLMProvider
from src.tm.rejected_task_queue import RejectedTaskQueue
from src.tm.retry_records import RejectedTranslationTask


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
        "knowledge_fingerprints": {},
        "target_locales": ["es", "fr"],
        "expected_source_count": 1,
        "expected_output_count": 2,
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


def test_parallel_runner_verifies_only_its_assigned_shard_paths(tmp_path, monkeypatch):
    raw = _manifest(tmp_path)
    raw["commit_policy"]["max_outputs_per_commit"] = 1
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    manifest = CampaignManifest.load(path)
    shard = list(manifest.shards(max_outputs=1))[0]
    captured = {}

    def capture_verify_environment(_manifest, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(CampaignManifest, "verify_environment", capture_verify_environment)
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=SimpleNamespace(campaign_context={}),
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(runner, "_validated_resume_receipts", lambda: {})

    runner.verify(resume=True, shard_ids=frozenset({str(shard["shard_id"])}))

    expected_sources = {source.source_path for source, _locale, _output in shard["jobs"]}
    expected_outputs = {output for _source, _locale, output in shard["jobs"]}
    assert captured["scope_sources"] == expected_sources
    assert captured["scope_outputs"] == expected_outputs
    assert captured["allow_campaign_tm_drift"] is True


def test_parallel_runner_refuses_unknown_shard_before_environment_check(tmp_path, monkeypatch):
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest(tmp_path)), encoding="utf-8")
    manifest = CampaignManifest.load(path)
    monkeypatch.setattr(
        CampaignManifest,
        "verify_environment",
        lambda _manifest, **_kwargs: pytest.fail(
            "environment check must not run for an unknown shard"
        ),
    )
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=SimpleNamespace(campaign_context={}),
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(runner, "_validated_resume_receipts", lambda: {})

    with pytest.raises(CampaignManifestError, match="unknown or already complete"):
        runner.verify(resume=True, shard_ids=frozenset({"not-a-real-shard"}))


def test_manifest_accepts_professionalize_llm_as_primary(tmp_path):
    """TC-APT-039 (plan revision 8, §6.1): the primary/escalation pair may run in
    either direction, chosen from TC-APT-006's per-language measurement."""
    raw = _manifest(tmp_path)
    raw["retry_policy"]["primary_model"] = "professionalize_llm"
    raw["retry_policy"]["llm_model"] = "m2m100_418m"
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    manifest = CampaignManifest.load(path)
    assert manifest.retry_policy["primary_model"] == "professionalize_llm"
    assert manifest.retry_policy["llm_model"] == "m2m100_418m"


def test_manifest_accepts_professionalize_only_policy(tmp_path):
    raw = _manifest(tmp_path)
    raw["retry_policy"].update(
        primary_model="professionalize_llm",
        llm_model="professionalize_llm",
        llm_escalation_mode="professionalize_only",
        llm_escalation_attempts=0,
        professionalize_only=True,
    )
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    manifest = CampaignManifest.load(path)
    assert manifest.retry_policy["professionalize_only"] is True


def test_professionalize_only_rejects_m2m_fallback(tmp_path):
    raw = _manifest(tmp_path)
    raw["retry_policy"].update(
        primary_model="professionalize_llm",
        llm_model="m2m100_418m",
        llm_escalation_mode="professionalize_only",
        llm_escalation_attempts=0,
        professionalize_only=True,
    )
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(CampaignManifestError, match="professionalize_only"):
        CampaignManifest.load(path)


def test_manifest_accepts_deferred_professionalize_queue(tmp_path):
    raw = _manifest(tmp_path)
    raw["retry_policy"]["llm_escalation_mode"] = "deferred"
    raw["retry_policy"]["llm_escalation_attempts"] = 0
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    manifest = CampaignManifest.load(path)
    assert manifest.retry_policy["llm_escalation_mode"] == "deferred"


def test_llm_call_outcomes_are_category_scoped_and_payload_free(tmp_path):
    ledger = CampaignLedger(tmp_path / "ledger", "pilot")
    for category, outcome in (("identity", "completed"), ("repair", "deferred"), ("retry", "failed")):
        ledger._append(
            ledger.root / "llm_calls.jsonl",
            {"category": category, "outcome": outcome, "candidate": "must not be surfaced"},
        )

    assert ledger.llm_call_outcomes() == {
        "identity": {"completed": 1},
        "repair": {"deferred": 1},
        "retry": {"failed": 1},
    }


def test_deferred_campaign_skips_identity_provider_call(tmp_path):
    payload = _manifest(tmp_path)
    payload["retry_policy"]["llm_escalation_mode"] = "deferred"
    payload["retry_policy"]["llm_escalation_attempts"] = 0
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=SimpleNamespace(campaign_context={}),
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )

    assert runner._llm_identity_gate() == {
        "status": "SKIPPED",
        "reason": "llm_escalation_mode=deferred",
        "cadence": "deferred",
    }


def test_verify_only_summary_has_outcomes_without_provider_or_translation(tmp_path, monkeypatch):
    payload = _manifest(tmp_path)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    engine = SimpleNamespace(campaign_context={})
    runner = CampaignRunner(
        manifest=CampaignManifest.load(manifest_path),
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(
        runner, "verify", lambda **_kwargs: {"campaign_id": "pilot", "accepted": 0, "remaining": 2}
    )

    summary = runner.run(verify_only=True)

    assert summary == {"campaign_id": "pilot", "accepted": 0, "remaining": 2}
    artifact = json.loads(runner.ledger.summary_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "VERIFIED"
    assert artifact["model_outcomes"] == {}
    assert artifact["attempt_model_outcomes"] == {}
    assert artifact["llm_call_outcomes"] == {}


def test_manifest_accepts_1_2b_m2m_for_deferred_queue(tmp_path):
    raw = _manifest(tmp_path)
    raw["retry_policy"].update(
        primary_model="m2m100_1.2b", llm_escalation_mode="deferred", llm_escalation_attempts=0
    )
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert CampaignManifest.load(path).retry_policy["primary_model"] == "m2m100_1.2b"


@pytest.mark.parametrize(
    "primary_model,llm_model",
    [
        ("m2m100_418m", "m2m100_418m"),
        ("professionalize_llm", "professionalize_llm"),
        ("m2m100_418m", "some_other_model"),
        ("some_other_model", "professionalize_llm"),
    ],
)
def test_manifest_rejects_invalid_primary_escalation_pairs(tmp_path, primary_model, llm_model):
    raw = _manifest(tmp_path)
    raw["retry_policy"]["primary_model"] = primary_model
    raw["retry_policy"]["llm_model"] = llm_model
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(CampaignManifestError):
        CampaignManifest.load(path)


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


def test_manifest_rejects_tampered_frozen_dirty_baseline(tmp_path):
    payload = _manifest(tmp_path)
    paths = {"unrelated.md": "a" * 64}
    payload["destination_baseline"] = {
        "paths": paths,
        "fingerprint": "b" * 64,
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(CampaignManifestError, match="baseline fingerprint"):
        CampaignManifest.load(path)


def test_dirty_snapshot_excludes_receipted_output_and_detects_user_change(tmp_path):
    subprocess.run(["git", "init", "-b", "pilot"], cwd=tmp_path, check=True)
    unrelated = tmp_path / "unrelated.md"
    output = tmp_path / "content/page.es.md"
    unrelated.write_text("original", encoding="utf-8")
    output.parent.mkdir(parents=True)
    output.write_text("accepted", encoding="utf-8")

    baseline = dirty_path_fingerprints(tmp_path, exclude_paths={"content/page.es.md"})
    assert baseline == {"unrelated.md": sha256_file(unrelated)}
    fingerprint = dirty_snapshot_fingerprint(baseline)

    unrelated.write_text("changed", encoding="utf-8")
    assert dirty_path_fingerprints(tmp_path, exclude_paths={"content/page.es.md"}) != baseline
    assert dirty_snapshot_fingerprint(baseline) == fingerprint


def test_direct_dirty_campaign_allows_empty_receipt_ledger(tmp_path):
    """A fresh direct campaign has no accepted outputs to exclude yet."""
    receipt_path = tmp_path / "empty-receipts.jsonl"
    receipt_path.write_text("", encoding="utf-8")

    from scripts.campaign.build_aspose_foss_pilot_manifest import _accepted_output_hashes

    assert _accepted_output_hashes(receipt_path) == {}


def test_verify_environment_preserves_frozen_dirty_destination(tmp_path):
    content_repo = tmp_path / "content"
    translator_repo = tmp_path / "translator"
    for repo in (content_repo, translator_repo):
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "pilot"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    source = content_repo / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=content_repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=content_repo, check=True)

    registry = translator_repo / "config/model_registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("models: []\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=translator_repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=translator_repo, check=True)

    unrelated = content_repo / "user-work.md"
    unrelated.write_text("keep", encoding="utf-8")
    output_relative = "content/docs.aspose.org/es/words/net/page.md"
    output = content_repo / output_relative
    output.parent.mkdir(parents=True)
    output.write_text("accepted", encoding="utf-8")
    payload = _manifest(content_repo)
    payload["content_repo_sha"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=content_repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    payload["translator_repo_sha"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=translator_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    payload["model_fingerprints"] = {"model_registry": sha256_file(registry)}
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    paths = dirty_path_fingerprints(content_repo, exclude_paths={output_relative})
    payload["destination_baseline"] = {
        "paths": paths,
        "fingerprint": dirty_snapshot_fingerprint(paths),
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)

    manifest.verify_environment(
        translator_repo=translator_repo,
        allow_existing_accepted={output_relative},
    )
    unrelated.write_text("changed", encoding="utf-8")
    with pytest.raises(CampaignManifestError, match="frozen dirty baseline drift"):
        manifest.verify_environment(
            translator_repo=translator_repo,
            allow_existing_accepted={output_relative},
        )


def _campaign_scoped_env(tmp_path: Path):
    """Shared git/manifest setup for the TC-APT-075 declared-replacement tests below."""
    content_repo = tmp_path / "content"
    translator_repo = tmp_path / "translator"
    for repo in (content_repo, translator_repo):
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "pilot"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    source = content_repo / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    # fr's output file is deliberately never created here: verify_environment's
    # per-source loop only checks a target that actually exists on disk, and
    # these tests only care about the es target. A test that needs an
    # undeclared dirty output creates fr_output itself.
    es_output = content_repo / "content/docs.aspose.org/es/words/net/page.md"
    fr_output = content_repo / "content/docs.aspose.org/fr/words/net/page.md"
    es_output.parent.mkdir(parents=True)
    fr_output.parent.mkdir(parents=True)
    es_output.write_text("committed es", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=content_repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=content_repo, check=True)

    registry = translator_repo / "config/model_registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("models: []\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=translator_repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=translator_repo, check=True)

    payload = _manifest(content_repo)
    payload["execution_policy"] = {"dirty_scope": "campaign_paths"}
    payload["content_repo_sha"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=content_repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    payload["translator_repo_sha"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=translator_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    payload["model_fingerprints"] = {"model_registry": sha256_file(registry)}
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    return content_repo, translator_repo, payload, es_output, fr_output


def test_declared_replacement_target_being_dirty_does_not_block_relaunch(tmp_path):
    """TC-APT-075: a review-rejected page's own uncommitted (dirty) output must not
    permanently block relaunching it -- mirrors the SHA-drift branch above (~line 393),
    which already excludes `declared` replacement targets from its own equivalent check.
    Reproduced the real blocker first: before this fix, this exact scenario raised
    "unreceipted campaign output is dirty" and there was no way to retrigger a
    review-rejected page at all (plan TC-APT-075, field notes 2026-09-05).
    """
    content_repo, translator_repo, payload, es_output, _fr_output = _campaign_scoped_env(tmp_path)

    # Simulate a prior review-rejected (uncommitted) draft still sitting on disk.
    es_output.write_text("rejected draft", encoding="utf-8")
    payload["sources"][0]["replace_existing"] = {
        "es": {"expected_sha256": sha256_file(es_output), "reason_code": "review_rejected_retry"}
    }

    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)

    # Non-empty but unrelated to es/fr: only present so the (irrelevant to this
    # test) TM-fingerprint check, gated on `not allow_existing_accepted`, is skipped.
    manifest.verify_environment(
        translator_repo=translator_repo,
        require_clean=True,
        allow_existing_accepted={"__unused_placeholder__"},
    )


def test_undeclared_dirty_output_still_blocks_relaunch_under_campaign_scope(tmp_path):
    """Regression guard for the fix above: an output that is dirty but NOT declared
    for replacement must still block the launch -- the fix narrows the exclusion to
    exactly the campaign's own declared targets, it does not disable the check."""
    content_repo, translator_repo, payload, es_output, fr_output = _campaign_scoped_env(tmp_path)

    # es is declared and dirty (allowed); fr is dirty but undeclared (must still block).
    es_output.write_text("rejected draft", encoding="utf-8")
    fr_output.write_text("stray uncommitted edit", encoding="utf-8")
    payload["sources"][0]["replace_existing"] = {
        "es": {"expected_sha256": sha256_file(es_output), "reason_code": "review_rejected_retry"}
    }

    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)

    with pytest.raises(CampaignManifestError, match="unreceipted campaign output is dirty"):
        manifest.verify_environment(translator_repo=translator_repo, require_clean=True)


def test_ledger_never_accepts_candidate_text(tmp_path):
    ledger = CampaignLedger(tmp_path, "pilot")
    with pytest.raises(ValueError, match="candidate text"):
        ledger.append_receipt({"output_path": "page.md", "content": "rejected translation"})
    assert not ledger.receipts_path.exists()


def test_ledger_deduplicates_identical_receipt_and_rejects_conflict(tmp_path):
    ledger = CampaignLedger(tmp_path, "pilot")
    receipt = {"output_path": "page.md", "output_sha256": "a" * 64}
    ledger.append_receipt(receipt)
    ledger.append_receipt(receipt)
    assert len(ledger.receipts_path.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(ValueError, match="conflicting"):
        ledger.append_receipt({"output_path": "page.md", "output_sha256": "b" * 64})


def test_ledger_atomic_replacement_rejects_candidate_text(tmp_path):
    ledger = CampaignLedger(tmp_path, "pilot")
    with pytest.raises(ValueError, match="candidate text"):
        ledger.replace_receipts([{"output_path": "page.md", "translated_content": "SECRET"}])
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


def test_model_outcomes_are_campaign_scoped_and_candidate_free(tmp_path):
    ledger = CampaignLedger(tmp_path, "active")
    ledger.append_receipt({"output_path": "de/page.md", "model_fingerprint": "m2m100_418m"})
    ledger.append_failure(
        source_path="source.md",
        output_path="de/page.md",
        target_lang="de",
        error="gate failed",
        gate="StructureValidator",
        model_id="m2m100_418m",
    )
    ledger._append(
        tmp_path / "heal_queue.jsonl",
        {"campaign_id": "active", "processing_model": "professionalize_llm", "status": "QUEUED"},
    )
    ledger._append(
        tmp_path / "heal_queue.jsonl",
        {"campaign_id": "old", "processing_model": "professionalize_llm", "status": "QUEUED"},
    )
    CampaignLedger(tmp_path, "historical").append_receipt(
        {"output_path": "fr/old-page.md", "model_fingerprint": "professionalize_llm"}
    )
    retry_queue = RejectedTaskQueue(tmp_path / "rejected_tasks.sqlite3")
    deferred = RejectedTranslationTask.from_mapping(
        {
            "campaign_id": "active", "site_id": "docs.aspose.org",
            "source_path": "content/en/page.md", "output_path": "content/de/page.md",
            "source_sha256": "a" * 64, "target_lang": "de",
            "failure_category": "structure", "failure_fingerprint": "fingerprint",
            "retry_budget": 2, "model_target": "professionalize_llm",
        }
    )
    task_id = retry_queue.enqueue(deferred)
    retry_queue.claim("consumer")
    retry_queue.accepted(task_id, "consumer", {"receipt_id": "retry-receipt"})

    outcomes = ledger.model_outcomes()

    assert outcomes["m2m100_418m"] == {
        "accepted": 1,
        "rejected": 1,
        "provider_error": 0,
        "queued": 0,
    }
    # The canonical SQLite task supersedes the human-facing heal-ticket row;
    # an accepted deferred retry must not remain falsely counted as queued.
    assert outcomes["professionalize_llm"]["queued"] == 0
    assert outcomes["professionalize_llm"]["accepted"] == 1
    assert ledger.retry_queue_outcomes() == [
        {
            "task_id": task_id,
            "state": "ACCEPTED",
            "attempts": 1,
            "error_code": None,
            "model_target": "professionalize_llm",
            "receipt_id": "retry-receipt",
        }
    ]


def test_attempt_model_outcomes_deduplicate_terminal_failure_rows_and_warn(tmp_path):
    ledger = CampaignLedger(tmp_path, "active")
    ledger.append_failure(
        source_path="source.md",
        output_path="de/page.md",
        target_lang="de",
        error="gate failed",
        attempt=1,
        job_id="shard::source.md::de",
        model_id="m2m100_418m",
        gate="StructureValidator",
    )
    # Audit-only duplicate suppression must not count as a second paid/model attempt.
    ledger.append_failure(
        source_path="source.md",
        output_path="de/page.md",
        target_lang="de",
        error="duplicate fingerprint",
        attempt=1,
        job_id="shard::source.md::de",
        model_id="m2m100_418m",
        gate="duplicate_retry_suppressed",
    )
    ledger.append_receipt(
        {
            "output_path": "fr/page.md",
            "model_fingerprint": "professionalize_llm",
            "attempt_model_id": "professionalize_llm",
            "campaign_attempt": 4,
        }
    )

    expected = {
        "m2m100_418m": {
            "1": {"attempted": 1, "accepted": 0, "rejected": 1, "provider_error": 0}
        },
        "professionalize_llm": {
            "4": {"attempted": 1, "accepted": 1, "rejected": 0, "provider_error": 0}
        },
    }
    assert ledger.attempt_model_outcomes() == expected
    # Re-opening the durable ledger is the resumed-campaign aggregation path.
    assert CampaignLedger(tmp_path, "active").attempt_model_outcomes() == expected
    assert ledger.zero_acceptance_recommendations(
        warning_after_attempts=1, stop_recommendation_after_attempts=2
    )["recommendations"] == [
        {
            "model_id": "m2m100_418m",
            "attempted": 1,
            "accepted": 0,
            "recommendation": "warn_and_continue",
        }
    ]


def test_attempt_model_outcomes_recommends_investigation_without_stopping(tmp_path):
    ledger = CampaignLedger(tmp_path, "active")
    for attempt in (1, 2, 3):
        ledger.append_failure(
            source_path="source.md",
            output_path=f"de/page-{attempt}.md",
            target_lang="de",
            error="provider error",
            attempt=attempt,
            job_id=f"shard::{attempt}",
            model_id="m2m100_418m",
            gate="campaign_job_exception",
        )

    report = ledger.zero_acceptance_recommendations(
        warning_after_attempts=1, stop_recommendation_after_attempts=3
    )

    assert report["recommendations"][0]["recommendation"] == "recommend_pause_and_investigate"
    assert report["recommendations"][0]["accepted"] == 0


def test_campaign_failure_metadata_uses_validator_names_without_messages():
    issue = SimpleNamespace(
        validator="SemanticSimilarityValidator",
        severity=SimpleNamespace(value="error"),
        message="SECRET REJECTED CANDIDATE",
    )
    result = SimpleNamespace(
        errors=["rejected"],
        retry_attempts=0,
        validation_result=SimpleNamespace(issues=[issue]),
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "SemanticSimilarityValidator"
    assert "validators=SemanticSimilarityValidator" in reason
    assert "SECRET" not in reason


def test_failure_metadata_records_payload_free_repetition_fingerprint():
    issue = SimpleNamespace(
        validator="RepetitionDetectorValidator",
        severity=SimpleNamespace(value="warning"),
        message="SECRET REJECTED CANDIDATE",
        location="segment_SECRET",
        details={
            "word": "SECRET",
            "frequency": 0.235294,
            "count": 4,
            "threshold": 0.20,
            "source_word_freq_ceiling": 0.08,
            "suggestion": "SECRET",
        },
    )
    result = SimpleNamespace(
        errors=[],
        retry_attempts=0,
        validation_result=SimpleNamespace(issues=[issue]),
        error="",
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    # VA-01 (TC-APT-105 audit): a WARNING-only validator must not be named in
    # `validators=` as the CAUSE of a reject.  That still holds -- see the
    # warning_only_validators= assertion below.
    #
    # Corrected 2026-09-11: VA-01's stated premise ("a WARNING-only validator
    # never actually causes a REJECT decision, Rule 1/2/5 are ERROR-driven")
    # is false under this portfolio's own configuration.  decision_engine's
    # Rule 5 reads `accept_after_max_retries` (config/validation.yaml: false)
    # and its else-branch REJECTs on exhausted retries regardless of issue
    # severity, so a warning-only result IS terminal under
    # `validation_policy: zero-defect`.  Live proof: fr and vi of
    # wave-pdftypescript-coreapi-20260911, three attempts each across both
    # models, every failure row `validators=unknown;
    # warning_only_validators=RepetitionDetectorValidator`.  Falling through to
    # the literal "pipeline" therefore threw away the only actionable signal
    # the ticket had.  The gate now names the warning validator with an
    # explicit `warning:` prefix -- distinguishable from error attribution at a
    # glance and in every root_cause_class derived from it, so VA-01's
    # anti-misattribution intent survives without the information loss.
    assert gate == "warning:RepetitionDetectorValidator"
    assert "warning_only_validators=RepetitionDetectorValidator;" in reason
    assert "RepetitionDetectorValidator:warning:word_frequency:" in reason
    assert "count=4" in reason
    assert "threshold=0.2" in reason
    assert "frequency=0.235294" in reason
    assert "payload_sha256=" in reason
    assert "SECRET" not in reason


def test_failure_metadata_records_payload_free_frontmatter_language_fingerprint():
    issue = SimpleNamespace(
        validator="FrontmatterLanguageCheck",
        severity=SimpleNamespace(value="error"),
        message="SECRET REJECTED CANDIDATE",
        location="frontmatter.description",
        details={
            "field": "description",
            "detected_lang": "en",
            "expected_lang": "hi",
            "confidence": 0.999,
            "letter_count": 100,
            "latin_letter_ratio": 0.82,
            "target_script_ratio": 0.18,
            "preview": "SECRET",
        },
    )
    result = SimpleNamespace(
        errors=["rejected"],
        retry_attempts=0,
        validation_result=SimpleNamespace(issues=[issue]),
        error="TranslationRejectedError: SECRET",
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "FrontmatterLanguageCheck"
    assert "frontmatter_language" in reason
    assert "field=description" in reason
    assert "detected_lang=en" in reason
    assert "expected_lang=hi" in reason
    assert "confidence=0.999" in reason
    assert "letter_count=100" in reason
    assert "latin_letter_ratio=0.82" in reason
    assert "target_script_ratio=0.18" in reason
    assert "SECRET" not in reason


def test_shards_are_locale_scoped_and_bounded(tmp_path):
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest(tmp_path)), encoding="utf-8")
    manifest = CampaignManifest.load(path)

    shards = list(manifest.shards(max_outputs=1))

    assert len(shards) == 2
    assert all(len(shard["jobs"]) == 1 for shard in shards)
    assert {shard["locale"] for shard in shards} == {"es", "fr"}
    assert all(shard["site_id"] == "docs.aspose.org" for shard in shards)


def test_commit_contains_only_receipted_output(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "pilot"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "campaign@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Campaign Test"],
        cwd=repo,
        check=True,
    )
    marker = repo / "baseline.txt"
    marker.write_text("baseline", encoding="utf-8")
    subprocess.run(["git", "add", "baseline.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True)

    payload = _manifest(repo)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    ledger_root = tmp_path / "ledger"
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=object(),
        translator_repo=repo,
        ledger_root=ledger_root,
    )
    relative = "content/docs.aspose.org/es/words/net/page.md"
    output = repo / relative
    output.parent.mkdir(parents=True)
    output.write_text("accepted", encoding="utf-8")
    runner.ledger.append_receipt(
        {
            "output_path": relative,
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
    )

    commit_sha = runner._commit_verified_outputs("fixture")

    assert commit_sha
    changed = subprocess.run(
        ["git", "show", "--pretty=", "--name-only", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert changed == [relative]


def test_resume_rejects_tampered_receipt_fingerprint(tmp_path):
    source = tmp_path / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    payload = _manifest(tmp_path)
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=object(),
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    output_relative = payload["sources"][0]["outputs"]["es"]
    output = tmp_path / output_relative
    output.parent.mkdir(parents=True)
    output.write_text("accepted", encoding="utf-8")
    runner.ledger.append_receipt(
        {
            "campaign_id": "pilot",
            "source_path": payload["sources"][0]["source_path"],
            "output_path": output_relative,
            "source_sha256": sha256_file(source),
            "output_sha256": sha256_file(output),
            "target_lang": "es",
            "validation_policy": "zero-defect",
            "config_fingerprint": payload["config_fingerprint"],
            "model_fingerprint": "fixture",
            "gate_results": {str(index): {"passed": True} for index in range(1, 45)},
        }
    )
    rows = runner.ledger.receipts_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(rows[0])
    tampered["model_fingerprint"] = "tampered"
    runner.ledger.receipts_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

    with pytest.raises(CampaignManifestError, match="fingerprint mismatch"):
        runner._validated_resume_receipts()


def test_resume_rejects_warn_only_gate_receipt_under_zero_defect(tmp_path):
    source = tmp_path / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    payload = _manifest(tmp_path)
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    output_relative = payload["sources"][0]["outputs"]["es"]
    output = tmp_path / output_relative
    output.parent.mkdir(parents=True)
    output.write_text("accepted", encoding="utf-8")
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=object(),
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    gate_results = {
        str(index): {"passed": True, "action": "block", "error": None} for index in range(1, 45)
    }
    gate_results["31"]["action"] = "warn"
    runner.ledger.append_receipt(
        {
            "campaign_id": "pilot",
            "source_path": payload["sources"][0]["source_path"],
            "output_path": output_relative,
            "source_sha256": sha256_file(source),
            "output_sha256": sha256_file(output),
            "target_lang": "es",
            "validation_policy": "zero-defect",
            "config_fingerprint": payload["config_fingerprint"],
            "model_fingerprint": "fixture",
            "gate_results": gate_results,
        }
    )

    with pytest.raises(CampaignManifestError, match="all-pass"):
        runner._validated_resume_receipts()


def test_receipt_fingerprint_survives_json_roundtrip_with_integer_gate_keys():
    receipt = {
        "output_path": "content/page.de.md",
        "gate_results": {index: {"passed": True} for index in range(1, 45)},
    }

    persisted = json.loads(json.dumps(receipt))

    assert receipt_fingerprint(receipt) == receipt_fingerprint(persisted)


def _init_recovery_repo(tmp_path: Path, *, extra_commit_path: str | None = None):
    repo = tmp_path / "content-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "pilot"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "campaign@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Campaign Test"],
        cwd=repo,
        check=True,
    )
    source_relative = "content/docs.aspose.org/en/words/net/page.md"
    source = repo / source_relative
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    marker = repo / "baseline.txt"
    marker.write_text("baseline", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True)
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    payload = _manifest(repo)
    payload["target_locales"] = ["es"]
    payload["expected_output_count"] = 1
    payload["content_repo_sha"] = baseline
    payload["sources"][0]["outputs"] = {"es": payload["sources"][0]["outputs"]["es"]}
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)

    output_relative = payload["sources"][0]["outputs"]["es"]
    output = repo / output_relative
    output.parent.mkdir(parents=True)
    output.write_text("accepted", encoding="utf-8")
    subprocess.run(["git", "add", output_relative], cwd=repo, check=True)
    if extra_commit_path:
        extra = repo / extra_commit_path
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("extra", encoding="utf-8")
        subprocess.run(["git", "add", extra_commit_path], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "content(locale): zero-defect shard w2:docs.aspose.org:words:net:es:1",
        ],
        cwd=repo,
        check=True,
    )
    return repo, manifest, source, output


def test_recover_receipts_revalidates_governed_commit_before_atomic_ledger(tmp_path, monkeypatch):
    repo, manifest, source, output = _init_recovery_repo(tmp_path)

    class Engine:
        def __init__(self):
            self.campaign_context = {}
            self.calls = []

        def accept_candidate_bytes(self, **kwargs):
            self.calls.append(kwargs)
            return AcceptedTranslation(
                content=kwargs["candidate_bytes"],
                source_path=kwargs["source_path"],
                output_path=kwargs["output_path"],
                source_sha256=sha256_file(source),
                output_sha256=sha256_file(output),
                target_lang="es",
                validation_policy="zero-defect",
                gate_results={
                    gate_id: {"passed": True, "action": "test", "error": None}
                    for gate_id in range(1, 45)
                },
                config_fingerprint=manifest.config_fingerprint,
                model_fingerprint="receipt-recovery:fidelity=test",
                campaign_id=manifest.campaign_id,
            )

    engine = Engine()
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=repo,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(CampaignManifest, "verify_environment", lambda self, **_kwargs: None)

    summary = runner.recover_committed_receipts()

    assert summary["accepted"] == 1
    assert len(engine.calls) == 1
    receipt = next(iter(runner.ledger.receipts().values()))
    assert len(receipt["gate_results"]) == 44
    assert receipt["receipt_recovery"]["commit_sha"]
    assert "content" not in receipt
    assert output.read_text(encoding="utf-8") == "accepted"

    resumed = runner.recover_committed_receipts()

    assert resumed["accepted"] == 1
    assert len(engine.calls) == 1


def test_recover_receipts_rejects_multifile_governed_commit_without_ledger(tmp_path):
    repo, manifest, _source, _output = _init_recovery_repo(
        tmp_path, extra_commit_path="unrelated.txt"
    )
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=SimpleNamespace(campaign_context={}),
        translator_repo=repo,
        ledger_root=tmp_path / "ledger",
    )

    with pytest.raises(CampaignManifestError, match="one-file add commit"):
        runner.recover_committed_receipts()
    assert not runner.ledger.receipts_path.exists()


def test_recover_receipts_persists_nothing_when_revalidation_fails(tmp_path, monkeypatch):
    repo, manifest, _source, output = _init_recovery_repo(tmp_path)
    engine = SimpleNamespace(
        campaign_context={},
        accept_candidate_bytes=lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("candidate rejected by fidelity")
        ),
    )
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=repo,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(CampaignManifest, "verify_environment", lambda self, **_kwargs: None)

    with pytest.raises(CampaignManifestError, match="fidelity"):
        runner.recover_committed_receipts()
    assert not runner.ledger.receipts_path.exists()
    assert output.read_text(encoding="utf-8") == "accepted"


def test_campaign_uses_three_primary_then_llm_and_logs_metadata_only(tmp_path, monkeypatch):
    source = tmp_path / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    payload = _manifest(tmp_path)
    payload["target_locales"] = ["es"]
    payload["expected_output_count"] = 1
    payload["sources"][0]["outputs"] = {"es": payload["sources"][0]["outputs"]["es"]}
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    output_relative = payload["sources"][0]["outputs"]["es"]
    output = tmp_path / output_relative

    class Engine:
        def __init__(self):
            self.campaign_context = {}
            self.calls = []
            class Provider(BaseLLMProvider):
                def initialize(self, config):
                    self._config = config

                def _generate_impl(self, system_prompt, user_text):
                    return "fixture", 2, 1

            self.provider = Provider()
            self.decision_engine = SimpleNamespace(max_retry_attempts=99)
            self.config = SimpleNamespace(get_site_profile=lambda _site: SimpleNamespace())

        def _get_output_path(self, *_args):
            return output

        def translate_file(
            self,
            site_id,
            file_path,
            target_langs,
            **_kwargs,
        ):
            assert site_id == "docs.aspose.org"
            assert file_path == source
            assert target_langs == ["es"]
            escalated = str(output.resolve()) in self._rtq_llm_output_paths
            feedback = self._campaign_retry_feedback_by_output.pop(str(output.resolve()), None)
            self.calls.append(
                (
                    escalated,
                    _kwargs.get("retry_budget_override"),
                    feedback,
                    # TC-APT-045: the model pin arrives call-scoped, never via
                    # a shared engine attribute.
                    _kwargs.get("model_id"),
                )
            )
            if _kwargs.get("model_id") == "professionalize_llm":
                self.provider.generate("system", "source")
            if len(self.calls) < 3:
                return SimpleNamespace(
                    success=False,
                    acceptance_receipts={},
                    errors=["SECRET REJECTED CANDIDATE TEXT"],
                    retry_attempts=0,
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("accepted", encoding="utf-8")
            receipt = {
                "campaign_id": "pilot",
                "source_path": str(source.resolve()),
                "output_path": str(output.resolve()),
                "source_sha256": sha256_file(source),
                "output_sha256": sha256_file(output),
                "target_lang": "es",
                "validation_policy": "zero-defect",
                "config_fingerprint": payload["config_fingerprint"],
                "model_fingerprint": "professionalize_llm",
                "gate_results": {index: {"passed": True} for index in range(1, 45)},
            }
            self.campaign_context["receipt_sink"](receipt)
            return SimpleNamespace(
                success=True,
                acceptance_receipts={"es": receipt},
                errors=[],
                retry_attempts=0,
            )

    engine = Engine()
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(
        runner,
        "verify",
        lambda **_kwargs: {**manifest.to_summary(), "accepted": 0, "remaining": 1},
    )
    monkeypatch.setattr(runner, "_commit_verified_outputs", lambda _shard: None)

    summary = runner.run()

    assert summary["status"] == "COMPLETE"
    assert summary["llm_call_outcomes"] == {"retry": {"completed": 2, "started": 2}}
    assert summary["attempt_model_outcomes"]["professionalize_llm"]["5"] == {
        "attempted": 1,
        "accepted": 1,
        "rejected": 0,
        "provider_error": 0,
    }
    assert runner.ledger.receipts()[output_relative]["campaign_attempt"] == 5
    assert runner.ledger.receipts()[output_relative]["attempt_model_id"] == "professionalize_llm"
    assert engine.calls[0] == (False, 2, None, "m2m100_418m")
    assert engine.calls[1][0:2] == (True, 0)
    assert "Regenerate the complete translation" in engine.calls[1][2]
    assert engine.calls[1][3] == "professionalize_llm"
    assert engine.calls[2][0:2] == (True, 0)
    assert "Regenerate the complete translation" in engine.calls[2][2]
    assert engine.calls[2][3] == "professionalize_llm"
    # TC-APT-045: the campaign must never create/mutate shared model state.
    assert not hasattr(engine, "model_id_override")
    assert engine.decision_engine.max_retry_attempts == 99
    failure_log = runner.ledger.failures_path.read_text(encoding="utf-8")
    assert failure_log.count("\n") == 2
    assert "SECRET REJECTED CANDIDATE TEXT" not in failure_log
    assert "translation_rejected" in failure_log


def test_campaign_suppresses_second_paid_retry_for_duplicate_candidate(tmp_path):
    """A source-based retry is audited once, then deduplicated by hash+gate."""
    source = tmp_path / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    payload = _manifest(tmp_path)
    payload["target_locales"] = ["es"]
    payload["expected_output_count"] = 1
    payload["sources"][0]["outputs"] = {"es": payload["sources"][0]["outputs"]["es"]}
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    output = tmp_path / payload["sources"][0]["outputs"]["es"]

    class Engine:
        def __init__(self):
            self.campaign_context = {}
            self.calls = []
            self.config = SimpleNamespace(get_site_profile=lambda _site: SimpleNamespace())

        def _get_output_path(self, *_args):
            return output

        def translate_file(self, _site, _source, target_langs, **kwargs):
            self.calls.append(kwargs["model_id"])
            return SimpleNamespace(
                success=False,
                acceptance_receipts={},
                errors=["rejected"],
                retry_attempts=0,
                candidate_sha256={target_langs[0]: "a" * 64},
            )

    engine = Engine()
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    shard = next(manifest.shards(resume_receipts=set(), max_outputs=1))
    accepted, _output = runner._run_campaign_job(
        shard=shard,
        source=manifest.sources[0],
        locale="es",
        expected_output=payload["sources"][0]["outputs"]["es"],
    )

    assert not accepted
    assert engine.calls == ["m2m100_418m", "professionalize_llm"]
    rows = CampaignLedger(tmp_path / "ledger", "pilot")._read_jsonl(runner.ledger.failures_path)
    assert [row["model_id"] for row in rows] == [
        "m2m100_418m",
        "professionalize_llm",
        "professionalize_llm",
    ]
    assert rows[-1]["gate"] == "duplicate_retry_suppressed"
    assert rows[-1]["candidate_sha256"] == "a" * 64


def test_campaign_parallel_jobs_share_engine_without_cross_job_state(tmp_path, monkeypatch):
    """A bounded campaign shard overlaps jobs while receipts stay per-output."""
    source = tmp_path / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    payload = _manifest(tmp_path)
    payload["target_locales"] = ["es"]
    payload["expected_source_count"] = 2
    payload["expected_output_count"] = 2
    payload["sources"][0]["outputs"] = {
        "es": payload["sources"][0]["outputs"]["es"],
    }
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    second_source = tmp_path / "content/docs.aspose.org/en/words/net/second.md"
    second_source.write_text("second source", encoding="utf-8")
    payload["sources"].append(
        {
            **payload["sources"][0],
            "source_path": "content/docs.aspose.org/en/words/net/second.md",
            "source_sha256": sha256_file(second_source),
            "outputs": {"es": "content/docs.aspose.org/es/words/net/second.md"},
        }
    )
    payload["execution_policy"] = {
        "max_parallel_jobs": 2,
        "model_sharing": "single_shared_instance",
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    outputs = {
        str(tmp_path / item["source_path"]): tmp_path / item["outputs"]["es"]
        for item in payload["sources"]
    }

    class Engine:
        def __init__(self):
            self.campaign_context = {}
            self.config = SimpleNamespace(get_site_profile=lambda _site: SimpleNamespace())
            self.active = 0
            self.peak = 0
            self.lock = threading.Lock()

        def _get_output_path(self, source_path, _locale, _profile):
            return outputs[str(source_path)]

        def translate_file(self, _site, _source, target_langs, **_kwargs):
            locale = target_langs[0]
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(0.08)
            output = outputs[str(_source)]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"accepted-{locale}", encoding="utf-8")
            receipt = {
                "campaign_id": "pilot",
                "source_path": str(_source.resolve()),
                "output_path": str(output.resolve()),
                "source_sha256": sha256_file(_source),
                "output_sha256": sha256_file(output),
                "target_lang": locale,
                "validation_policy": "zero-defect",
                "config_fingerprint": payload["config_fingerprint"],
                "model_fingerprint": "fixture",
                "gate_results": {index: {"passed": True} for index in range(1, 45)},
            }
            self.campaign_context["receipt_sink"](receipt)
            with self.lock:
                self.active -= 1
            return SimpleNamespace(success=True, acceptance_receipts={locale: receipt}, errors=[])

    engine = Engine()
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(
        runner,
        "verify",
        lambda **_kwargs: {**manifest.to_summary(), "accepted": 0, "remaining": 2},
    )
    monkeypatch.setattr(runner, "_commit_verified_outputs", lambda _shard: None)
    # TC-APT-046: this test's subject is job overlap, so it must state which side of
    # the rollback switch it exercises rather than inherit a default. The shipped
    # default is the serialized (pre-TC-APT-044) behaviour until a canary at
    # max_parallel_jobs > 1 has been reviewed.
    monkeypatch.setattr(runner, "_force_serialize", False)

    summary = runner.run()

    assert summary["status"] == "COMPLETE"
    assert engine.peak == 2
    receipts = runner.ledger.receipts()
    assert set(receipts) == {item["outputs"]["es"] for item in payload["sources"]}


def test_shard_failure_does_not_block_later_shard_commits(tmp_path, monkeypatch):
    """TC-APT-041: a shard whose job(s) exhaust every retry no longer aborts
    the whole run -- it commits whatever it did receipt (nothing here, since a
    failed job never produces one) and the loop still reaches later shards,
    which commit normally. The run still ends non-zero, but the raised error
    carries the full summary (including which shard(s) failed) instead of
    hiding it behind a mid-run traceback."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "pilot"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "campaign@example.invalid"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Campaign Test"], cwd=repo, check=True)
    marker = repo / "baseline.txt"
    marker.write_text("baseline", encoding="utf-8")
    source = repo / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    # Commit the source alongside the baseline marker so only the campaign's
    # own generated outputs show up as dirty later -- the source itself must
    # already be tracked, or _commit_verified_outputs's dirty-scope check
    # (rightly) refuses to commit anything at all.
    subprocess.run(
        ["git", "add", "baseline.txt", str(source.relative_to(repo))], cwd=repo, check=True
    )
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True)

    payload = _manifest(repo)
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    payload["commit_policy"]["max_outputs_per_commit"] = 1  # force es and fr into separate shards
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    outputs = {locale: repo / payload["sources"][0]["outputs"][locale] for locale in ("es", "fr")}

    class Engine:
        def __init__(self):
            self.campaign_context = {}
            self.config = SimpleNamespace(get_site_profile=lambda _site: SimpleNamespace())
            self.decision_engine = SimpleNamespace(max_retry_attempts=99)
            self.calls = []

        def _get_output_path(self, _source, locale, _profile):
            return outputs[locale]

        def translate_file(self, _site, _source, target_langs, **_kwargs):
            locale = target_langs[0]
            self.calls.append(locale)
            if locale == "es":
                return SimpleNamespace(
                    success=False,
                    acceptance_receipts={},
                    errors=["es rejected"],
                    retry_attempts=0,
                )
            output = outputs[locale]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"accepted-{locale}", encoding="utf-8")
            receipt = {
                "campaign_id": "pilot",
                "source_path": str(source.resolve()),
                "output_path": str(output.resolve()),
                "source_sha256": sha256_file(source),
                "output_sha256": sha256_file(output),
                "target_lang": locale,
                "validation_policy": "zero-defect",
                "config_fingerprint": payload["config_fingerprint"],
                "model_fingerprint": "fixture",
                "gate_results": {index: {"passed": True} for index in range(1, 45)},
            }
            self.campaign_context["receipt_sink"](receipt)
            return SimpleNamespace(
                success=True,
                acceptance_receipts={locale: receipt},
                errors=[],
                retry_attempts=0,
            )

    engine = Engine()
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=repo,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(
        runner,
        "verify",
        lambda **_kwargs: {**manifest.to_summary(), "accepted": 0, "remaining": 2},
    )

    summary = runner.run()

    assert summary["status"] == "PARTIAL_WITH_TICKETS"
    assert summary["accepted"] == 1
    assert summary["failed"] == 1
    assert len(summary["failed_shard_ids"]) == 1
    assert "es" in summary["failed_shard_ids"][0]

    heal_queue_path = tmp_path / "ledger" / "heal_queue.jsonl"
    tickets = [
        json.loads(line) for line in heal_queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(tickets) == 1
    assert tickets[0]["target_lang"] == "es"
    assert tickets[0]["status"] == "OPEN"
    assert tickets[0]["source_path"] == payload["sources"][0]["source_path"]

    # es never produced a receipt, so nothing es-shaped was ever committed --
    # but fr's shard still ran and still committed, proving the es failure
    # didn't abort the outer shard loop.
    assert not outputs["es"].exists()
    assert outputs["fr"].read_text(encoding="utf-8") == "accepted-fr"
    changed = subprocess.run(
        ["git", "log", "--all", "--pretty=", "--name-only"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert payload["sources"][0]["outputs"]["fr"] in changed
    assert payload["sources"][0]["outputs"]["es"] not in changed


def test_deferred_terminal_heal_ticket_enqueues_rejected_retry_task(tmp_path):
    """TC-APT-046: a deferred campaign's terminal heal ticket must also reach
    the dedicated Professionalize retry consumer's queue -- otherwise the
    consumer built in 64bb3bab has nothing feeding it in production."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "pilot"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "campaign@example.invalid"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Campaign Test"], cwd=repo, check=True)
    source = repo / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    subprocess.run(["git", "add", str(source.relative_to(repo))], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True)

    payload = _manifest(repo)
    payload["target_locales"] = ["es"]
    payload["expected_output_count"] = 1
    payload["sources"][0]["source_sha256"] = sha256_file(source)
    payload["sources"][0]["outputs"] = {"es": "content/docs.aspose.org/es/words/net/page.md"}
    payload["retry_policy"]["llm_escalation_mode"] = "deferred"
    payload["retry_policy"]["llm_escalation_attempts"] = 0
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)
    output = repo / payload["sources"][0]["outputs"]["es"]

    class Engine:
        def __init__(self):
            self.campaign_context = {}
            self.config = SimpleNamespace(get_site_profile=lambda _site: SimpleNamespace())
            self.decision_engine = SimpleNamespace(max_retry_attempts=99)

        def _get_output_path(self, _source, _locale, _profile):
            return output

        def translate_file(self, _site, _source, target_langs, **_kwargs):
            return SimpleNamespace(
                success=False,
                acceptance_receipts={},
                errors=["es rejected"],
                retry_attempts=0,
            )

    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=Engine(),
        translator_repo=repo,
        ledger_root=tmp_path / "ledger",
    )
    def monkeypatch_verify(**_kwargs):
        return {**manifest.to_summary(), "accepted": 0, "remaining": 1}

    runner.verify = monkeypatch_verify

    summary = runner.run()

    assert summary["status"] == "PARTIAL_WITH_TICKETS"
    heal_queue_path = tmp_path / "ledger" / "heal_queue.jsonl"
    tickets = [
        json.loads(line) for line in heal_queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(tickets) == 1
    assert tickets[0]["status"] == "QUEUED"

    queue = RejectedTaskQueue(tmp_path / "ledger" / "rejected_tasks.sqlite3")
    claimed = queue.claim("test-consumer")
    assert len(claimed) == 1
    _, task, _ = claimed[0]
    assert task.campaign_id == "pilot"
    assert task.source_path == payload["sources"][0]["source_path"]
    assert task.target_lang == "es"
    assert task.model_target == "professionalize_llm"
    assert task.source_sha256 == sha256_file(source)


def test_campaign_retry_feedback_accumulates_distinct_gate_instructions():
    first = CampaignRunner._retry_feedback(
        SimpleNamespace(
            validation_result=SimpleNamespace(
                issues=[
                    SimpleNamespace(
                        validator="FrontmatterLanguageCheck",
                        details={"field": "description"},
                    )
                ]
            ),
            error="",
        ),
        "hi",
    )
    combined = CampaignRunner._retry_feedback(
        SimpleNamespace(
            validation_result=SimpleNamespace(issues=[]),
            error="TC-SAS-01: link_text fingerprint",
        ),
        "hi",
        first,
    )

    assert "Translate every translatable frontmatter field" in combined
    assert "description" in combined
    assert "Translate every translatable source unit" in combined


def test_arabic_frontmatter_feedback_requires_arabic_script():
    feedback = CampaignRunner._retry_feedback(
        SimpleNamespace(
            validation_result=SimpleNamespace(
                issues=[
                    SimpleNamespace(
                        validator="FrontmatterLanguageCheck",
                        details={"field": "seoTitle"},
                    )
                ]
            ),
            error="",
        ),
        "ar",
    )

    assert "Arabic script" in feedback
    assert "seoTitle" in feedback


def test_campaign_resume_rehydrates_feedback_from_metadata(tmp_path):
    ledger = CampaignLedger(tmp_path, "campaign")
    ledger.append_failure(
        source_path="content/source.md",
        output_path="content/source.hi.md",
        target_lang="hi",
        error=(
            "translation_rejected; validators=FrontmatterLanguageCheck; "
            "field=summary; error_sha256=abc"
        ),
        gate="FrontmatterLanguageCheck",
    )

    latest = ledger.latest_failure(output_path="content/source.hi.md", target_lang="hi")
    feedback = CampaignRunner._retry_feedback_from_failure(latest, "hi")

    assert "Translate every translatable frontmatter field" in feedback
    assert "summary" in feedback


def test_greek_frontmatter_retry_names_language_and_requires_script(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\nseoTitle: Aspose.HTML FOSS for Python — CSSOM, Cascade, and Computed Styles\n---\n",
        encoding="utf-8",
    )
    failure = {
        "gate": "FrontmatterLanguageCheck",
        "reason": (
            "translation_rejected; validators=FrontmatterLanguageCheck; "
            "field=seoTitle; detected_lang=en; expected_lang=el"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "el",
        source_path=source,
    )

    assert "Greek (el), using Greek script for all ordinary prose" in feedback
    assert "preserve exactly only these source tokens" in feedback
    assert "Aspose.HTML" in feedback
    assert "CSSOM" in feedback
    assert "Cascade" in feedback
    assert "Computed" in feedback
    assert "Styles" in feedback


def test_frontmatter_feedback_has_source_derived_protection_boundary(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\n"
        "description: A tour of spreadsheet management in Aspose.Cells FOSS "
        "for Rust with worksheets, CellStyle, formulas, and XLSX files.\n"
        "---\n",
        encoding="utf-8",
    )
    result = SimpleNamespace(
        validation_result=SimpleNamespace(
            issues=[
                SimpleNamespace(
                    validator="FrontmatterLanguageCheck",
                    details={"field": "description"},
                )
            ]
        ),
        error="",
    )

    feedback = CampaignRunner._retry_feedback(result, "hi", source_path=source)

    assert "preserve exactly only these source tokens" in feedback
    assert "Aspose.Cells" in feedback
    assert "CellStyle" in feedback
    assert "XLSX" in feedback
    assert "spreadsheet" in feedback
    assert "worksheets" in feedback
    assert "formulas" in feedback


def test_sas_link_feedback_resolves_source_hash_to_lexical_boundary(tmp_path):
    source = tmp_path / "index.md"
    label = "Aspose.Cells — Enterprise Blog"
    source.write_text(
        f"Read [{label}](https://blog.aspose.com/) for more.\n",
        encoding="utf-8",
    )
    fingerprint = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
    result = SimpleNamespace(
        validation_result=SimpleNamespace(issues=[]),
        error=(
            f"TC-SAS-01: same-as-source; unit_fingerprints=link_text:{fingerprint}:{len(label)}"
        ),
    )

    feedback = CampaignRunner._retry_feedback(
        result,
        "nl",
        source_path=source,
    )

    assert "affected source link label" in feedback
    assert "Aspose.Cells" in feedback
    assert "Enterprise, Blog" in feedback
    assert "Translate all ordinary label words into Dutch (nl)" in feedback


def test_sas_link_feedback_rehydrates_from_metadata_only_failure(tmp_path):
    source = tmp_path / "index.md"
    label = "Aspose.Cells — Enterprise Blog"
    source.write_text(
        f"[{label}](https://blog.aspose.com/)\n",
        encoding="utf-8",
    )
    fingerprint = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
    failure = {
        "gate": "TC-SAS-01",
        "reason": (
            "translation_rejected; codes=TC-SAS-01; "
            f"unit_fingerprints=link_text:{fingerprint}:{len(label)}; "
            "error_sha256=abc"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "nl",
        source_path=source,
    )

    assert "Aspose.Cells" in feedback
    assert "Enterprise, Blog" in feedback


def test_sas_text_feedback_rehydrates_only_pinned_source_units(tmp_path, monkeypatch):
    source = tmp_path / "content" / "blog.aspose.org" / "product" / "index.md"
    source.parent.mkdir(parents=True)
    source_unit = "Build documents from scratch with"
    source.write_text(f"## Guide\n\n{source_unit} `DocumentBuilder`.\n", encoding="utf-8")
    fingerprint = hashlib.sha256(source_unit.encode("utf-8")).hexdigest()[:16]

    parsed = SimpleNamespace(ast=[], frontmatter={})
    monkeypatch.setattr(
        "src.translation_engine.parser.HugoParser.parse_file",
        lambda _self, _path: parsed,
    )
    monkeypatch.setattr(
        "src.translation_engine.extractor.TextUnitExtractor.extract_from_ast",
        lambda _self, _ast, frontmatter=None: SimpleNamespace(
            units=[
                SimpleNamespace(kind=SimpleNamespace(value="text"), source_text=source_unit),
                SimpleNamespace(kind=SimpleNamespace(value="text"), source_text="Other prose"),
            ]
        ),
    )
    monkeypatch.setattr(
        "src.utils.config_loader.ConfigService.get_site_profile",
        lambda _self, _site_id: SimpleNamespace(
            body=SimpleNamespace(
                ast_segmentation_strategy="adaptive",
                preserve_patterns=[],
            )
        ),
    )
    result = SimpleNamespace(
        validation_result=SimpleNamespace(issues=[]),
        error=(
            f"TC-SAS-01: same-as-source; unit_fingerprints=text:{fingerprint}:{len(source_unit)}"
        ),
    )

    feedback = CampaignRunner._retry_feedback(
        result,
        "es",
        source_path=source,
    )

    assert "affected exact English source units" in feedback
    assert source_unit in feedback
    assert "Other prose" not in feedback
    assert "Spanish (es)" in feedback
    assert "Return no unit unchanged" in feedback


def test_arabic_sas_retry_uses_translated_product_link_label(tmp_path):
    source = tmp_path / "index.md"
    label = "Aspose.Words for .NET"
    source.write_text(
        f"[{label}](https://products.aspose.org/words/net/)\n",
        encoding="utf-8",
    )
    fingerprint = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
    failure = {
        "gate": "TC-SAS-01",
        "reason": (
            "translation_rejected; codes=TC-SAS-01; "
            f"unit_fingerprints=link_text:{fingerprint}:{len(label)}; "
            "error_sha256=abc"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "ar",
        source_path=source,
    )

    assert "Aspose.Words لـ .NET" in feedback
    assert "governed target label exactly" in feedback
    assert "Translate all ordinary label words into Arabic (ar)" in feedback


def test_czech_sas_retry_uses_translated_product_link_label(tmp_path):
    source = tmp_path / "index.md"
    label = "Aspose.Words for .NET"
    source.write_text(
        f"[{label}](https://products.aspose.org/words/net/)\n",
        encoding="utf-8",
    )
    fingerprint = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
    failure = {
        "gate": "TC-SAS-01",
        "reason": (
            "translation_rejected; codes=TC-SAS-01; "
            f"unit_fingerprints=link_text:{fingerprint}:{len(label)}; "
            "error_sha256=abc"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "cs",
        source_path=source,
    )

    assert "Aspose.Words pro .NET" in feedback
    assert "governed target label exactly" in feedback


def test_product_link_terminology_covers_every_campaign_locale():
    translations = CampaignRunner._PRODUCT_LINK_LABEL_TRANSLATIONS

    assert set(translations) == set(CampaignRunner._LOCALE_NAMES)
    assert all(value != "Aspose.Words for .NET" for value in translations.values())
    assert all("Aspose.Words" in value and ".NET" in value for value in translations.values())


def test_german_github_repository_retry_uses_governed_label(tmp_path):
    source = tmp_path / "index.md"
    label = "GitHub Repository"
    source.write_text(
        f"[{label}](https://github.com/aspose-words/)\n",
        encoding="utf-8",
    )
    fingerprint = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
    failure = {
        "gate": "TC-SAS-01",
        "reason": (
            "translation_rejected; codes=TC-SAS-01; "
            f"unit_fingerprints=link_text:{fingerprint}:{len(label)}; "
            "error_sha256=abc"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "de",
        source_path=source,
    )

    assert "GitHub-Repository" in feedback
    assert "governed target label exactly" in feedback


def test_github_repository_terminology_covers_every_campaign_locale():
    translations = CampaignRunner._GITHUB_REPOSITORY_LABEL_TRANSLATIONS

    assert set(translations) == set(CampaignRunner._LOCALE_NAMES)
    assert all(value != "GitHub Repository" for value in translations.values())
    assert all("GitHub" in value for value in translations.values())


def test_failure_metadata_extracts_safe_gate_score_without_candidate_text():
    result = SimpleNamespace(
        errors=[],
        retry_attempts=0,
        validation_result=None,
        error=(
            "GATE36 FIDELITY JUDGE output.de.md: fail score=0.40; SECRET REJECTED CANDIDATE TEXT"
        ),
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "GATE36"
    assert "codes=GATE36" in reason
    assert "verdict=fail" in reason
    assert "score=0.40" in reason
    assert "SECRET" not in reason


def test_failure_metadata_preserves_safe_verification_check_only():
    issue = SimpleNamespace(
        severity="warning",
        check_name="language_detection",
        location="frontmatter.title",
        message="SECRET REJECTED CANDIDATE TEXT",
        source_text="SECRET REJECTED CANDIDATE TEXT",
        translated_text="SECRET REJECTED CANDIDATE TEXT",
        metadata={"confidence": 0.91},
    )
    result = SimpleNamespace(
        errors=[],
        retry_attempts=0,
        validation_result=None,
        verification_result=SimpleNamespace(issues=[issue]),
        error="Zero-defect verification requires zero errors and zero warnings",
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "verification:language_detection"
    assert "verification_checks=language_detection" in reason
    assert "field=title" in reason
    assert "confidence=0.91" in reason
    assert "SECRET REJECTED CANDIDATE TEXT" not in reason


def test_verification_language_feedback_uses_frontmatter_source_lexicon(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\ntitle: Spreadsheet Management in Rust with Aspose.Cells FOSS\n---\n",
        encoding="utf-8",
    )
    failure = {
        "gate": "verification:language_detection",
        "reason": (
            "translation_rejected; verification_checks=language_detection; "
            "verification_fingerprints=language_detection:error:abc:"
            "field=title:confidence=0.714284"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "ko",
        source_path=source,
    )

    assert "frontmatter field(s) title" in feedback
    assert "preserve exactly only these source tokens" in feedback
    assert "Spreadsheet" in feedback
    assert "Management" in feedback
    assert "Aspose.Cells" in feedback


def test_live_verification_enum_severity_generates_language_feedback(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\ntitle: Spreadsheet Management in Rust with Aspose.Cells FOSS\n---\n",
        encoding="utf-8",
    )
    result = SimpleNamespace(
        validation_result=SimpleNamespace(issues=[]),
        verification_result=SimpleNamespace(
            issues=[
                SimpleNamespace(
                    severity=SimpleNamespace(value="error"),
                    check_name="language_detection",
                    location="frontmatter.title",
                )
            ]
        ),
        error="",
    )

    feedback = CampaignRunner._retry_feedback(result, "cs", source_path=source)

    assert "language_detection" in feedback
    assert "frontmatter field(s) title" in feedback
    assert "Czech (cs)" in feedback


def test_dutch_language_retry_uses_unambiguous_idiomatic_title(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\ntitle: 'Deep Dive: The CSSOM in Python'\n---\n",
        encoding="utf-8",
    )
    failure = {
        "gate": "verification:language_detection",
        "reason": (
            "translation_rejected; verification_checks=language_detection; "
            "verification_fingerprints=language_detection:error:abc:"
            "field=title:confidence=0.999996"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "nl",
        source_path=source,
    )

    assert "Een grondige analyse van" in feedback
    assert "Afrikaans-like literal calque" in feedback
    assert "Dutch (nl)" in feedback


def test_czech_language_retry_uses_unambiguous_czech_title(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\ntitle: Spreadsheet Management in Rust with Aspose.Cells FOSS\n---\n",
        encoding="utf-8",
    )
    failure = {
        "gate": "verification:language_detection",
        "reason": (
            "translation_rejected; verification_checks=language_detection; "
            "verification_fingerprints=language_detection:error:abc:"
            "field=title:confidence=0.999995"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "cs",
        source_path=source,
    )

    assert "Řízení tabulek v jazyce Rust s Aspose.Cells FOSS" in feedback
    assert "Czech/Slovak-neutral" in feedback
    assert "Czech (cs)" in feedback


def test_spanish_language_retry_uses_unambiguous_spanish_title(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\ntitle: Introducing Aspose.Words FOSS for .NET\n---\n",
        encoding="utf-8",
    )
    failure = {
        "gate": "verification:language_detection",
        "reason": (
            "translation_rejected; verification_checks=language_detection; "
            "verification_fingerprints=language_detection:error:abc:"
            "field=title:confidence=0.999993"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "es",
        source_path=source,
    )

    assert "Lanzamiento de Aspose.Words FOSS para .NET" in feedback
    assert "unambiguous Spanish language signal" in feedback
    assert "Spanish (es)" in feedback


def test_romanian_frontmatter_retry_uses_unambiguous_seo_title(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\nseoTitle: Aspose.HTML FOSS for Python — CSSOM, Cascade, and Computed Styles\n---\n",
        encoding="utf-8",
    )
    failure = {
        "gate": "FrontmatterLanguageCheck",
        "reason": (
            "translation_rejected; validators=FrontmatterLanguageCheck; "
            "field=seoTitle; detected_lang=en; expected_lang=ro"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "ro",
        source_path=source,
    )

    assert "Aspose.HTML FOSS pentru Python — CSSOM, cascada și stilurile calculate" in feedback
    assert "unambiguous Romanian language signals" in feedback
    assert "Romanian (ro)" in feedback


def test_german_frontmatter_retry_uses_unambiguous_seo_title(tmp_path):
    source = tmp_path / "index.md"
    source.write_text(
        "---\nseoTitle: Aspose.Words FOSS for .NET — Open-Source Word Document Library\n---\n",
        encoding="utf-8",
    )
    failure = {
        "gate": "FrontmatterLanguageCheck",
        "reason": (
            "translation_rejected; validators=FrontmatterLanguageCheck; "
            "field=seoTitle; detected_lang=en; expected_lang=de"
        ),
    }

    feedback = CampaignRunner._retry_feedback_from_failure(
        failure,
        "de",
        source_path=source,
    )

    assert (
        "Aspose.Words FOSS für .NET — eine quelloffene Bibliothek für Word-Dokumente"
    ) in feedback
    assert "unambiguous German language signals" in feedback
    assert "German (de)" in feedback


def test_resume_feedback_accumulates_distinct_recent_failures(tmp_path):
    link_label = "Aspose.Cells Enterprise Blog"
    source = tmp_path / "index.md"
    source.write_text(
        "---\n"
        "title: Spreadsheet Management in Rust with Aspose.Cells FOSS\n"
        "summary: Manage spreadsheets with Rust.\n"
        "---\n"
        f"[{link_label}](https://blog.aspose.com/)\n",
        encoding="utf-8",
    )
    link_fingerprint = hashlib.sha256(link_label.encode("utf-8")).hexdigest()[:16]
    failures = [
        {
            "gate": "GATE36",
            "reason": "translation_rejected; codes=GATE36; verdict=fail; score=0.2",
        },
        {
            "gate": "FrontmatterLanguageCheck",
            "reason": ("translation_rejected; validators=FrontmatterLanguageCheck; field=summary"),
        },
        {
            "gate": "TC-SAS-01",
            "reason": (
                "translation_rejected; codes=TC-SAS-01; "
                f"unit_fingerprints=link_text:{link_fingerprint}:{len(link_label)}"
            ),
        },
    ]

    feedback = CampaignRunner._retry_feedback_from_failures(
        failures,
        "cs",
        source_path=source,
    )

    assert "Preserve every source claim and section" in feedback
    assert "fields detected as failing were: summary" in feedback
    assert "affected source link label" in feedback
    assert "Translate all ordinary label words into Czech (cs)" in feedback


def test_failure_metadata_extracts_exception_class_without_candidate_text():
    result = SimpleNamespace(
        errors=["rejected"],
        retry_attempts=0,
        validation_result=None,
        error="TranslationIncomplete: SECRET REJECTED CANDIDATE",
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "pipeline"
    assert "exceptions=TranslationIncomplete" in reason
    assert "SECRET" not in reason


def test_failure_metadata_promotes_rejected_write_gate_without_error_text():
    result = SimpleNamespace(
        errors=[],
        retry_attempts=0,
        validation_result=None,
        error="SECRET REJECTED CANDIDATE",
        rejection_gate_results={
            2: {"passed": True, "action": "block"},
            18: {"passed": False, "action": "block"},
        },
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "GATE18"
    assert "codes=GATE18" in reason
    assert "SECRET" not in reason


def test_gate_five_retry_feedback_requires_translated_markdown_labels():
    result = SimpleNamespace(
        validation_result=None,
        verification_result=None,
        error="GATE5: rejected candidate",
    )

    feedback = CampaignRunner._retry_feedback(result, "it")

    assert "Markdown link labels" in feedback
    assert "Italian (it)" in feedback
    assert "Preserve URLs" in feedback


def test_failure_metadata_preserves_final_acceptance_diagnostic_code():
    result = SimpleNamespace(
        validation_result=None,
        verification_result=None,
        rejection_gate_results={},
        rejection_diagnostic_code="TC-ACCEPTANCE-RECEIPT",
        error="candidate lacks an all-pass 43-gate write receipt",
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "TC-ACCEPTANCE-RECEIPT"
    assert "codes=TC-ACCEPTANCE-RECEIPT" in reason


def test_failure_metadata_preserves_only_safe_sas_unit_fingerprints():
    result = SimpleNamespace(
        errors=[],
        retry_attempts=0,
        validation_result=None,
        error=("TC-SAS-01: same-as-source; unit_fingerprints=link_text:0123456789abcdef:13"),
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "TC-SAS-01"
    assert "unit_fingerprints=link_text:0123456789abcdef:13" in reason


def test_failure_metadata_attributes_a_warning_only_reject_to_its_validator():
    """VA-01 closed over-attribution; this closes the under-attribution half.

    Under `validation_policy: zero-defect` the decision engine's Rule 5 has
    `accept_after_max_retries=False`, so it REJECTs a candidate whose only
    remaining issues are WARNING severity.  `validators` is then empty by
    design (it is ERROR-only), and the gate used to fall all the way through
    to the literal "pipeline" -- the heal ticket landed as `auto:pipeline`,
    naming nothing, even though `warning_only_validators` recorded exactly
    which validator blocked the cell.  Live cases: fr and vi of
    wave-pdftypescript-coreapi-20260911 (RepetitionDetectorValidator warning,
    count=6, threshold=5, identical error_sha256 on both).
    """
    issue = SimpleNamespace(
        validator="RepetitionDetectorValidator",
        severity=SimpleNamespace(value="warning"),
        message="SECRET REJECTED CANDIDATE",
        details={"ngram": "x", "count": 6, "threshold": 5},
        location="body",
    )
    result = SimpleNamespace(
        errors=["rejected"],
        retry_attempts=2,
        validation_result=SimpleNamespace(issues=[issue]),
        error="Translation rejected: Failed after 2 retries",
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "warning:RepetitionDetectorValidator"
    assert "validators=unknown" in reason
    assert "warning_only_validators=RepetitionDetectorValidator" in reason
    assert "SECRET REJECTED CANDIDATE" not in reason


def test_failure_metadata_still_prefers_an_error_validator_over_a_warning_one():
    """The warning fallback must never outrank real error attribution."""
    error_issue = SimpleNamespace(
        validator="StructureValidator",
        severity=SimpleNamespace(value="error"),
        message="x",
        details={"source_count": 2, "translation_count": 13},
        location="body",
    )
    warning_issue = SimpleNamespace(
        validator="LinkValidator",
        severity=SimpleNamespace(value="warning"),
        message="x",
        details={},
        location="body",
    )
    result = SimpleNamespace(
        errors=["rejected"],
        retry_attempts=0,
        validation_result=SimpleNamespace(issues=[error_issue, warning_issue]),
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "StructureValidator"
    assert "warning_only_validators=LinkValidator" in reason
