"""Threshold and metadata invariants for the reproducible audit sidecar."""
from __future__ import annotations

import json
import subprocess

from scripts.quality import audit_all_content as aac
from src.translation_engine.write_gate import WriteGateEvaluator


def test_audit_thresholds_match_live_gate_default_and_override():
    live = WriteGateEvaluator(detector=None, similarity_tracker=None, config=aac._CONFIG)
    assert aac.get_purity_threshold("ar") == live._get_purity_threshold("ar") == 0.06
    assert aac.get_purity_threshold("lt") == live._get_purity_threshold("lt") == 0.15


def test_metadata_contains_resolved_inputs_and_model_hash_field(tmp_path):
    output = tmp_path / "structural.jsonl"
    metadata_path = aac.write_audit_run_metadata(output, ["docs.aspose.org"])
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata_path == tmp_path / "structural.jsonl.metadata.json"
    assert metadata["schema"] == "audit_all_content_run_metadata/v1"
    assert metadata["sites"] == ["docs.aspose.org"]
    assert len(metadata["config_sha256"]) == 64
    assert metadata["audit_repository"]["sha"]
    content_repo = metadata["content_repositories"]["docs.aspose.org"]["repository"]
    # A configured content root can be an isolated pilot directory or a
    # non-Git mounted checkout. The metadata must expose that limitation
    # explicitly rather than inventing a revision.
    assert "sha" in content_repo
    assert "dirty" in content_repo
    assert "sha256" in metadata["fasttext_model"]


def test_default_threshold_surfaces_a_ten_percent_purity_issue_but_lt_override_does_not():
    translated = "\n\n".join(
        ["This is an untranslated English prose paragraph with enough ordinary words to count."]
        + ["Переведенный неанглийский абзац с достаточным количеством символов для проверки."] * 9
    )
    assert aac.check_purity(translated, "ar")[0] is True
    assert aac.check_purity(translated, "lt")[0] is False


def test_content_sha_survives_a_bounded_dirty_status_timeout(monkeypatch, tmp_path):
    def fake_run(args, **_kwargs):
        if args[1] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, stdout="known-sha\n", stderr="")
        raise subprocess.TimeoutExpired(args, 5)

    monkeypatch.setattr(aac.subprocess, "run", fake_run)
    assert aac._git_fingerprint(tmp_path) == {
        "sha": "known-sha", "dirty": None, "status_error": "TimeoutExpired"
    }
