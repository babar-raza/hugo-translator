"""TC-APT-031 (governed replace-existing) + TC-APT-032 (campaign-path-scoped dirty check).

Acceptance (plan section 11):
  031: (1) undeclared existing target still refused; (2) declared + matching pre-hash is replaced and
       receipted with superseded_sha256; (3) declared but drifted is refused; (4) resume/recovery accepts a
       receipted replacement / treats an untouched declared original as governed (not a recovery error).
  032: unrelated dirty paths no longer block; an unreceipted candidate still does; a changed source still
       does; HEAD movement by other sessions is tolerated when the pin is an ancestor.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.workers.campaign_manifest import (
    CampaignManifest,
    CampaignManifestError,
    sha256_file,
)
from src.workers.campaign_runner import CampaignRunner

SRC_REL = "content/docs.aspose.org/en/words/net/page.md"
OUT_REL = "content/docs.aspose.org/es/words/net/page.md"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "content-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "T")
    src = repo / SRC_REL
    src.parent.mkdir(parents=True)
    src.write_text("source text", encoding="utf-8")
    (repo / "baseline.txt").write_text("b", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo


def _payload(
    repo: Path,
    *,
    dirty_scope: str = "campaign_paths",
    replace: dict | None = None,
    tm_inputs=None,
    on_job_failure: str | None = None,
) -> dict:
    payload = {
        "schema_version": 1,
        "campaign_id": "unit",
        "validation_policy": "zero-defect",
        "content_repo": str(repo),
        "content_repo_sha": _git(repo, "rev-parse", "HEAD"),
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64,
        "knowledge_fingerprints": {},
        "target_locales": ["es"],
        "expected_source_count": 1,
        "expected_output_count": 1,
        "retry_policy": {
            "primary_model": "m2m100_418m",
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "professionalize_llm",
        },
        "commit_policy": {
            "branch": "main",
            "max_outputs_per_commit": 250,
            "push": False,
            "enabled": False,
        },
        "execution_policy": {
            "max_parallel_jobs": 1,
            "model_sharing": "single_shared_instance",
            "dirty_scope": dirty_scope,
            **({"on_job_failure": on_job_failure} if on_job_failure else {}),
        },
        "sources": [
            {
                "site_id": "docs.aspose.org",
                "family": "words",
                "platform": "net",
                "source_path": SRC_REL,
                "source_sha256": sha256_file(repo / SRC_REL),
                "wave": 0,
                "outputs": {"es": OUT_REL},
                **({"replace_existing": replace} if replace else {}),
            }
        ],
    }
    if tm_inputs is not None:
        payload["tm_fingerprint_inputs"] = tm_inputs
    return payload


def _load(tmp_path: Path, payload: dict) -> CampaignManifest:
    path = tmp_path / f"manifest-{len(list(tmp_path.iterdir()))}.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return CampaignManifest.load(path)


def _env_ok(manifest: CampaignManifest, tmp_path: Path, monkeypatch, *, accepted=None):
    """Call verify_environment with the non-git-content checks neutralised."""
    import src.workers.campaign_manifest as cm

    monkeypatch.setattr(cm, "fingerprint_files", lambda *_a, **_k: manifest.tm_fingerprint)
    translator = tmp_path / "translator"
    translator.mkdir(exist_ok=True)
    (translator / "config").mkdir(exist_ok=True)
    (translator / "config/model_registry.yaml").write_text("models: {}\n", encoding="utf-8")
    monkeypatch.setattr(cm, "sha256_file", _sha_with_registry_override(manifest, translator))
    real_git_sha = cm.git_sha
    monkeypatch.setattr(
        cm,
        "git_sha",
        lambda repo: manifest.translator_repo_sha
        if Path(repo) == translator.resolve()
        else real_git_sha(repo),
    )
    monkeypatch.setattr(cm, "git_dirty_paths", _dirty_paths_excluding(translator))
    manifest.verify_environment(
        translator_repo=translator, require_clean=True, allow_existing_accepted=accepted
    )


def _sha_with_registry_override(manifest, translator):
    import src.workers.campaign_manifest as cm

    real = cm.sha256_file

    def _sha(path: Path):
        if Path(path).resolve() == (translator / "config/model_registry.yaml").resolve():
            return manifest.model_fingerprints["model_registry"]
        return real(path)

    return _sha


def _dirty_paths_excluding(translator):
    import src.workers.campaign_manifest as cm

    real = cm.git_dirty_paths

    def _dirty(repo: Path):
        if Path(repo).resolve() == translator.resolve():
            return []
        return real(repo)

    return _dirty


# ----------------------------------------------------------------------------- TC-APT-032
def test_unrelated_dirty_paths_do_not_block_under_campaign_paths(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    (repo / "keywords").mkdir()
    (repo / "keywords/other-session.json").write_text(
        "{}", encoding="utf-8"
    )  # untracked, unrelated
    (repo / "baseline.txt").write_text(
        "edited by another session", encoding="utf-8"
    )  # modified, unrelated
    manifest = _load(tmp_path, _payload(repo))
    _env_ok(manifest, tmp_path, monkeypatch)  # no raise
    frozen = _load(tmp_path, _payload(repo, dirty_scope="frozen_baseline"))
    with pytest.raises(CampaignManifestError, match="dirty"):
        _env_ok(frozen, tmp_path, monkeypatch)


def test_unreceipted_candidate_and_changed_source_still_block(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    manifest = _load(tmp_path, _payload(repo))
    out = repo / OUT_REL
    out.parent.mkdir(parents=True)
    out.write_text("half-written candidate", encoding="utf-8")
    with pytest.raises(
        CampaignManifestError,
        match="unreceipted campaign output is dirty|unexpected existing output",
    ):
        _env_ok(manifest, tmp_path, monkeypatch)
    out.unlink()
    (repo / SRC_REL).write_text("source text CHANGED", encoding="utf-8")
    with pytest.raises(CampaignManifestError, match="source is dirty|source hash drift"):
        _env_ok(manifest, tmp_path, monkeypatch)


def test_head_movement_by_other_sessions_is_tolerated_when_pin_is_ancestor(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    manifest = _load(tmp_path, _payload(repo))
    (repo / "unrelated.md").write_text("another session's commit", encoding="utf-8")
    _git(repo, "add", "unrelated.md")
    _git(repo, "commit", "-q", "-m", "chore: other session")
    _env_ok(manifest, tmp_path, monkeypatch)  # pin is an ancestor, nothing campaign-scoped changed
    (repo / SRC_REL).write_text("source text CHANGED", encoding="utf-8")
    _git(repo, "add", SRC_REL)
    _git(repo, "commit", "-q", "-m", "docs: edit source")
    with pytest.raises(
        CampaignManifestError, match="campaign source changed since pin|source hash drift"
    ):
        _env_ok(manifest, tmp_path, monkeypatch)


def test_tm_fingerprint_inputs_from_manifest_are_honoured(tmp_path):
    repo = _repo(tmp_path)
    manifest = _load(tmp_path, _payload(repo, tm_inputs=["data/tm/l2.lmdb/data.mdb"]))
    assert manifest.tm_fingerprint_inputs == ("data/tm/l2.lmdb/data.mdb",)
    with pytest.raises(CampaignManifestError, match="dirty_scope"):
        _load(tmp_path, _payload(repo, dirty_scope="anything_goes"))


# ----------------------------------------------------------------------------- TC-APT-031
def test_undeclared_existing_target_is_still_refused(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    out.parent.mkdir(parents=True)
    out.write_text("legacy translation", encoding="utf-8")
    _git(repo, "add", OUT_REL)
    _git(repo, "commit", "-q", "-m", "legacy")
    manifest = _load(tmp_path, _payload(repo))
    with pytest.raises(CampaignManifestError, match="unexpected existing output"):
        _env_ok(manifest, tmp_path, monkeypatch)


def test_declared_drifted_target_is_refused(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    out.parent.mkdir(parents=True)
    out.write_text("legacy translation", encoding="utf-8")
    _git(repo, "add", OUT_REL)
    _git(repo, "commit", "-q", "-m", "legacy")
    stale = "0" * 64
    manifest = _load(
        tmp_path,
        _payload(
            repo, replace={"es": {"expected_sha256": stale, "reason_code": "UNKNOWN_PROVENANCE"}}
        ),
    )
    with pytest.raises(CampaignManifestError, match="declared replacement drifted"):
        _env_ok(manifest, tmp_path, monkeypatch)


def _engine_for(repo: Path, out: Path, *, accept_on_call: int = 1):
    """Fake engine: writes the output and emits a receipt through campaign_context on the Nth call."""
    src = repo / SRC_REL

    class Engine:
        def __init__(self):
            self.campaign_context = {}
            self.calls = []
            self.decision_engine = SimpleNamespace(max_retry_attempts=99)
            self.config = SimpleNamespace(get_site_profile=lambda _s: SimpleNamespace())
            self.model_id_override = None

        def _get_output_path(self, *_a):
            return out

        def translate_file(self, site_id, file_path, target_langs, **kwargs):
            self.calls.append(dict(kwargs))
            if len(self.calls) < accept_on_call:
                return SimpleNamespace(
                    success=False, acceptance_receipts={}, errors=["rejected"], retry_attempts=0
                )
            assert kwargs["force_overwrite"] is True or not out.exists()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("NEW governed translation", encoding="utf-8")
            receipt = {
                "campaign_id": "unit",
                "source_path": str(src.resolve()),
                "output_path": str(out.resolve()),
                "source_sha256": sha256_file(src),
                "output_sha256": sha256_file(out),
                "target_lang": "es",
                "validation_policy": "zero-defect",
                "config_fingerprint": "c" * 64,
                "model_fingerprint": "m2m100_418m",
                "gate_results": {i: {"passed": True} for i in range(1, 45)},
            }
            self.campaign_context["receipt_sink"](receipt)
            return SimpleNamespace(
                success=True, acceptance_receipts={"es": receipt}, errors=[], retry_attempts=0
            )

    return Engine()


def test_declared_matching_target_is_replaced_and_receipted_with_superseded_sha(
    tmp_path, monkeypatch
):
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    out.parent.mkdir(parents=True)
    out.write_text("legacy translation", encoding="utf-8")
    legacy_sha = sha256_file(out)
    manifest = _load(
        tmp_path,
        _payload(
            repo,
            replace={"es": {"expected_sha256": legacy_sha, "reason_code": "UNKNOWN_PROVENANCE"}},
        ),
    )
    engine = _engine_for(
        repo, out, accept_on_call=2
    )  # first attempt rejected: original must survive
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(
        runner, "verify", lambda **_k: {**manifest.to_summary(), "accepted": 0, "remaining": 1}
    )
    monkeypatch.setattr(runner, "_commit_verified_outputs", lambda _s: None)
    monkeypatch.setattr(runner, "_llm_identity_gate", lambda: None)
    summary = runner.run()
    assert summary["status"] == "COMPLETE"
    assert engine.calls[0]["force_overwrite"] is True and len(engine.calls) == 2
    assert out.read_text(encoding="utf-8") == "NEW governed translation"
    receipt = runner.ledger.receipts()[OUT_REL]
    assert receipt["superseded_sha256"] == legacy_sha
    assert receipt["receipt_sha256"]  # signed after the field was added


def test_declared_target_survives_a_fully_rejected_job(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    out.parent.mkdir(parents=True)
    out.write_text("legacy translation", encoding="utf-8")
    legacy_sha = sha256_file(out)
    manifest = _load(
        tmp_path,
        _payload(
            repo,
            replace={"es": {"expected_sha256": legacy_sha, "reason_code": "UNKNOWN_PROVENANCE"}},
        ),
    )
    engine = _engine_for(repo, out, accept_on_call=99)  # every attempt rejected
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(
        runner, "verify", lambda **_k: {**manifest.to_summary(), "accepted": 0, "remaining": 1}
    )
    monkeypatch.setattr(runner, "_commit_verified_outputs", lambda _s: None)
    monkeypatch.setattr(runner, "_llm_identity_gate", lambda: None)
    # TC-APT-041 (plan §11): a shard with a failed job no longer aborts mid-run,
    # and per-file rejection no longer raises by default (execution_policy.
    # on_job_failure="continue") -- it is expected Track-A traffic with a heal
    # ticket, not an infrastructure failure.
    summary = runner.run()
    assert summary["status"] == "PARTIAL_WITH_TICKETS"
    assert (
        out.read_text(encoding="utf-8") == "legacy translation"
    )  # never deleted, never overwritten


def test_on_job_failure_raise_restores_strict_all_or_nothing(tmp_path, monkeypatch):
    """TC-APT-041 (plan §11): execution_policy.on_job_failure="raise" stays
    available for a caller that deliberately wants strict all-or-nothing
    behavior (e.g. a targeted regression re-run proving a fix)."""
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    out.parent.mkdir(parents=True)
    out.write_text("legacy translation", encoding="utf-8")
    legacy_sha = sha256_file(out)
    manifest = _load(
        tmp_path,
        _payload(
            repo,
            replace={"es": {"expected_sha256": legacy_sha, "reason_code": "UNKNOWN_PROVENANCE"}},
            on_job_failure="raise",
        ),
    )
    engine = _engine_for(repo, out, accept_on_call=99)  # every attempt rejected
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(
        runner, "verify", lambda **_k: {**manifest.to_summary(), "accepted": 0, "remaining": 1}
    )
    monkeypatch.setattr(runner, "_commit_verified_outputs", lambda _s: None)
    monkeypatch.setattr(runner, "_llm_identity_gate", lambda: None)
    with pytest.raises(CampaignManifestError, match="campaign incomplete"):
        runner.run()
    assert out.read_text(encoding="utf-8") == "legacy translation"


def test_undeclared_pre_hash_drift_at_job_time_is_refused(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    out.parent.mkdir(parents=True)
    out.write_text("legacy translation", encoding="utf-8")
    legacy_sha = sha256_file(out)
    manifest = _load(
        tmp_path,
        _payload(
            repo,
            replace={"es": {"expected_sha256": legacy_sha, "reason_code": "UNKNOWN_PROVENANCE"}},
        ),
    )
    engine = _engine_for(repo, out)
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    monkeypatch.setattr(
        runner, "verify", lambda **_k: {**manifest.to_summary(), "accepted": 0, "remaining": 1}
    )
    monkeypatch.setattr(runner, "_llm_identity_gate", lambda: None)
    out.write_text(
        "edited underneath by a concurrent session", encoding="utf-8"
    )  # after verify, before the job
    with pytest.raises(CampaignManifestError, match="pre-hash drift"):
        runner.run()
    assert out.read_text(encoding="utf-8") == "edited underneath by a concurrent session"


def test_recovery_treats_untouched_declared_original_as_governed(tmp_path):
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    out.parent.mkdir(parents=True)
    out.write_text("legacy translation", encoding="utf-8")
    _git(repo, "add", OUT_REL)
    _git(repo, "commit", "-q", "-m", "content(locale): bulk handoff (not a governed shard commit)")
    legacy_sha = sha256_file(out)
    manifest = _load(
        tmp_path,
        _payload(
            repo,
            replace={"es": {"expected_sha256": legacy_sha, "reason_code": "UNKNOWN_PROVENANCE"}},
        ),
    )
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=SimpleNamespace(campaign_context={}),
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    # Before TC-APT-031 this raised "receipt recovery commit is not governed"; now the declared,
    # untouched original is simply not a recovery candidate.
    assert runner._receipt_recovery_candidates() == []
    assert runner._unreplaced_declaration(manifest.sources[0], "es", OUT_REL) is True
