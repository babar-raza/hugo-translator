"""A failed shard wave must name the cause, not just say "Incomplete campaign shards".

On 2026-09-05 three consecutive launch failures (an LMDB map-size mismatch, then a
dirty unreceipted output) each cost a full wake to diagnose, because the launcher
gave the children no output destination and reported only which shards were
incomplete. These tests pin that a child's output is captured and that a failing
child's tail is surfaced.
"""

from pathlib import Path
from types import SimpleNamespace

import yaml

from scripts.campaign import launch_parallel_campaign_shards as launcher
from scripts.campaign.launch_parallel_campaign_shards import GPU_PRIMARY_LOCALES
from src.workers.campaign_manifest import CampaignManifest

LOCALES = ["de", "es", "hu"]
CHILD_OUTPUT = "boom: the real cause nobody could see"


def _manifest(tmp_path: Path) -> CampaignManifest:
    payload = {
        "schema_version": 1,
        "campaign_id": "diag-launcher",
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
        "commit_policy": {"branch": "main", "max_outputs_per_commit": 250, "push": False},
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
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return CampaignManifest.load(path)


def _args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        campaign_manifest=tmp_path / "manifest.yaml",
        ledger_root=tmp_path / "campaigns",
        device="cuda",
        max_gpu_memory_percent=50,
        gpu_shard_memory_percent=50,
        child="gate5",
    )


class _FailingChild:
    """Stand-in for run_gate5_batch.py that dies after printing a diagnostic."""

    def __init__(self, *args, **kwargs):
        stream = kwargs["stdout"]
        stream.write(CHILD_OUTPUT + "\n")
        stream.flush()

    def wait(self):
        return 1


def _run_one_failing_wave(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    shards = list(manifest.shards(resume_receipts=set(), max_outputs=250))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.subprocess, "Popen", _FailingChild)

    status = launcher._run_wave(
        groups=[shards[:2]],
        manifest=manifest,
        args=_args(tmp_path),
        gpu_locales=GPU_PRIMARY_LOCALES,
        translator_repo=tmp_path,
        config_root=tmp_path / "config",
    )
    return manifest, status


def test_child_output_is_written_to_a_per_child_log(tmp_path, monkeypatch):
    manifest, _status = _run_one_failing_wave(tmp_path, monkeypatch)

    log_path = tmp_path / "logs" / f"{manifest.campaign_id}_child0.log"
    assert log_path.is_file(), "child output had nowhere to go"
    assert CHILD_OUTPUT in log_path.read_text(encoding="utf-8")


def test_a_failing_child_has_its_tail_surfaced(tmp_path, monkeypatch, capsys):
    _manifest_obj, status = _run_one_failing_wave(tmp_path, monkeypatch)

    err = capsys.readouterr().err
    assert status == 1
    assert CHILD_OUTPUT in err, f"cause was not surfaced; stderr was:\n{err}"
    assert "child 0 exited 1" in err


def test_incomplete_shards_report_points_at_the_logs(tmp_path, monkeypatch, capsys):
    _manifest_obj, _status = _run_one_failing_wave(tmp_path, monkeypatch)

    err = capsys.readouterr().err
    assert "Incomplete campaign shards" in err
    assert "child logs:" in err, "the incomplete report must say where to look"
