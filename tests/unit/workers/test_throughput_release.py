import json
from pathlib import Path

import pytest

from src.workers.throughput_release import ThroughputReleaseError, verify_release


def _write_release(tmp_path: Path, phase: str = "canary16") -> tuple[Path, Path]:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("campaign_id: test\n", encoding="utf-8")
    import hashlib

    payload = {
        "campaign_id": "test", "phase": phase, "runtime_sha": "a" * 40,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "processes": 4, "max_parallel_jobs": 4 if phase == "canary16" else 1,
        "fleet_llm_slots": 16 if phase == "canary16" else 4,
        "force_serialize": phase == "baseline", "approved": phase != "baseline",
        "evidence_path": "evidence.json" if phase != "baseline" else "",
    }
    release = tmp_path / "release.json"
    release.write_text(json.dumps(payload), encoding="utf-8")
    return release, manifest


def test_release_binds_runtime_and_manifest(tmp_path):
    release, manifest = _write_release(tmp_path)
    result = verify_release(release, campaign_id="test", runtime_sha="a" * 40, manifest_path=manifest)
    assert result.phase == "canary16"
    assert result.max_parallel_jobs == 4


@pytest.mark.parametrize("kind", ["runtime", "manifest"])
def test_release_refuses_revision_drift(tmp_path, kind):
    release, manifest = _write_release(tmp_path, "baseline")
    if kind == "runtime":
        with pytest.raises(ThroughputReleaseError, match="runtime SHA"):
            verify_release(release, campaign_id="test", runtime_sha="b" * 40, manifest_path=manifest)
    else:
        manifest.write_text("campaign_id: changed\n", encoding="utf-8")
        with pytest.raises(ThroughputReleaseError, match="manifest bytes"):
            verify_release(release, campaign_id="test", runtime_sha="a" * 40, manifest_path=manifest)


def test_unapproved_parallel_release_is_rejected(tmp_path):
    release, manifest = _write_release(tmp_path)
    data = json.loads(release.read_text(encoding="utf-8"))
    data["approved"] = False
    release.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ThroughputReleaseError, match="approved"):
        verify_release(release, campaign_id="test", runtime_sha="a" * 40, manifest_path=manifest)
