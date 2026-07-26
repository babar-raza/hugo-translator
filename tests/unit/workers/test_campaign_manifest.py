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
    assert dirty_path_fingerprints(
        tmp_path, exclude_paths={"content/page.es.md"}
    ) != baseline
    assert dirty_snapshot_fingerprint(baseline) == fingerprint


def test_verify_environment_preserves_frozen_dirty_destination(tmp_path):
    content_repo = tmp_path / "content"
    translator_repo = tmp_path / "translator"
    for repo in (content_repo, translator_repo):
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "pilot"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
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
        ["git", "rev-parse", "HEAD"], cwd=translator_repo, check=True, capture_output=True, text=True
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

    assert gate == "RepetitionDetectorValidator"
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
    gate_results = {str(index): {"passed": True, "action": "block", "error": None} for index in range(1, 45)}
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
                (escalated, _kwargs.get("retry_budget_override"), feedback)
            )
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
    assert engine.calls[0] == (False, 2, None)
    assert engine.calls[1][0:2] == (True, 0)
    assert "Regenerate the complete translation" in engine.calls[1][2]
    assert engine.calls[2][0:2] == (True, 0)
    assert "Regenerate the complete translation" in engine.calls[2][2]
    assert engine.decision_engine.max_retry_attempts == 99
    failure_log = runner.ledger.failures_path.read_text(encoding="utf-8")
    assert failure_log.count("\n") == 2
    assert "SECRET REJECTED CANDIDATE TEXT" not in failure_log
    assert "translation_rejected" in failure_log


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

    summary = runner.run()

    assert summary["status"] == "COMPLETE"
    assert engine.peak == 2
    receipts = runner.ledger.receipts()
    assert set(receipts) == {item["outputs"]["es"] for item in payload["sources"]}


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
        "---\n"
        "seoTitle: Aspose.HTML FOSS for Python — CSSOM, Cascade, and Computed Styles\n"
        "---\n",
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
            "TC-SAS-01: same-as-source; " f"unit_fingerprints=link_text:{fingerprint}:{len(label)}"
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


def test_failure_metadata_extracts_safe_gate_score_without_candidate_text():
    result = SimpleNamespace(
        errors=[],
        retry_attempts=0,
        validation_result=None,
        error=(
            "GATE36 FIDELITY JUDGE output.de.md: fail score=0.40; " "SECRET REJECTED CANDIDATE TEXT"
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
        "---\n" "title: Spreadsheet Management in Rust with Aspose.Cells FOSS\n" "---\n",
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


def test_failure_metadata_preserves_only_safe_sas_unit_fingerprints():
    result = SimpleNamespace(
        errors=[],
        retry_attempts=0,
        validation_result=None,
        error=("TC-SAS-01: same-as-source; " "unit_fingerprints=link_text:0123456789abcdef:13"),
    )

    gate, reason = CampaignRunner._failure_metadata(result)

    assert gate == "TC-SAS-01"
    assert "unit_fingerprints=link_text:0123456789abcdef:13" in reason
