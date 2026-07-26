from pathlib import Path
import subprocess

import pytest

import scripts.campaign.build_aspose_foss_pilot_manifest as builder
from scripts.campaign.build_aspose_foss_pilot_manifest import (
    FOLDER_SURFACES,
    _config_fingerprint,
)


def _write_required_config(root: Path) -> None:
    paths = [
        Path("config/global.yaml"),
        Path("config/validation.yaml"),
        Path("config/terminology.yaml"),
        Path("config/terminology/technical_terms.yaml"),
        Path("config/site_profiles/default.yaml"),
        Path("config/site_profiles/blog.aspose.org.yaml"),
        *[
            Path("config/site_profiles") / f"{site}.yaml"
            for site, _ in FOLDER_SURFACES
        ],
    ]
    for index, relative in enumerate(paths):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"value: {index}\n", encoding="utf-8")


def test_config_fingerprint_binds_validation_and_terminology(tmp_path):
    _write_required_config(tmp_path)
    baseline = _config_fingerprint(tmp_path)

    validation = tmp_path / "config/validation.yaml"
    validation.write_text("value: changed\n", encoding="utf-8")
    after_validation = _config_fingerprint(tmp_path)

    terminology = tmp_path / "config/terminology/technical_terms.yaml"
    terminology.write_text("terms: [changed]\n", encoding="utf-8")
    after_terminology = _config_fingerprint(tmp_path)

    assert after_validation != baseline
    assert after_terminology != after_validation


def test_config_fingerprint_binds_default_profile(tmp_path):
    _write_required_config(tmp_path)
    baseline = _config_fingerprint(tmp_path)

    default_profile = tmp_path / "config/site_profiles/default.yaml"
    default_profile.write_text("value: changed\n", encoding="utf-8")

    assert _config_fingerprint(tmp_path) != baseline


def _init_git_repo(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    marker = path / "baseline.txt"
    marker.write_text("baseline", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _patch_minimal_manifest_inputs(monkeypatch, content: Path, translator: Path):
    output = "content/blog.aspose.org/words/net/page.es.md"
    source = {
        "site_id": "blog.aspose.org",
        "family": "words",
        "platform": "net",
        "source_path": "content/blog.aspose.org/words/net/page.md",
        "source_sha256": "a" * 64,
        "outputs": {"es": output},
        "wave": 1,
    }
    monkeypatch.setattr(builder, "EXPECTED_SOURCE_COUNT", 1)
    monkeypatch.setattr(builder, "EXPECTED_OUTPUT_COUNT", 1)
    monkeypatch.setattr(builder, "_folder_sources", lambda _repo: iter([source]))
    monkeypatch.setattr(builder, "_blog_sources", lambda _repo: iter([]))
    monkeypatch.setattr(builder, "_config_fingerprint", lambda _repo: "b" * 64)
    monkeypatch.setattr(builder, "_knowledge_fingerprints", lambda _repo: {})
    monkeypatch.setattr(builder, "fingerprint_files", lambda *_args: "c" * 64)
    registry = translator / "config/model_registry.yaml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("models: {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=translator, check=True)
    subprocess.run(["git", "commit", "-m", "config"], cwd=translator, check=True)
    return output


def test_manifest_repin_preserves_explicit_preoutput_baseline(tmp_path, monkeypatch):
    content = tmp_path / "content"
    translator = tmp_path / "translator"
    baseline = _init_git_repo(content)
    _init_git_repo(translator)
    output = _patch_minimal_manifest_inputs(monkeypatch, content, translator)
    target = content / output
    target.parent.mkdir(parents=True)
    target.write_text("accepted", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=content, check=True)
    subprocess.run(["git", "commit", "-m", "governed output"], cwd=content, check=True)

    manifest = builder.build_manifest(
        content_repo=content,
        translator_repo=translator,
        campaign_id="pilot",
        content_baseline_sha=baseline,
    )

    assert manifest["content_repo_sha"] == baseline


def test_manifest_repin_rejects_noncampaign_descendant_path(tmp_path, monkeypatch):
    content = tmp_path / "content"
    translator = tmp_path / "translator"
    baseline = _init_git_repo(content)
    _init_git_repo(translator)
    _patch_minimal_manifest_inputs(monkeypatch, content, translator)
    unexpected = content / "unexpected.txt"
    unexpected.write_text("drift", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=content, check=True)
    subprocess.run(["git", "commit", "-m", "drift"], cwd=content, check=True)

    with pytest.raises(RuntimeError, match="non-campaign paths"):
        builder.build_manifest(
            content_repo=content,
            translator_repo=translator,
            campaign_id="pilot",
            content_baseline_sha=baseline,
        )
