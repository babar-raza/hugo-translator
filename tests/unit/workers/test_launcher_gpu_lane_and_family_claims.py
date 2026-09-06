"""TC-APT-094: K-launcher fan-out with real cross-process enforcement.

Two gaps TC-APT-047 left open, closed here:
1. GPU exclusivity only ever covered shards within ONE launcher's own
   manifest. Two launcher processes on DIFFERENT campaign manifests had no
   shared view of GPU use and could each run a hu/ja/ro shard at once.
2. `work_claims.py` (TC-APT-056) was built, tested, and imported by nothing --
   two sessions could start a launcher for the same family concurrently.
"""

from pathlib import Path

import yaml

from scripts.campaign import launch_parallel_campaign_shards as launcher
from scripts.campaign.launch_parallel_campaign_shards import (
    GPU_PRIMARY_LOCALES,
    gpu_lane_lock_path,
    main,
    partition_for_wave,
    select_pending_shards,
    try_acquire_gpu_lane,
)
from src.utils.file_lock import FileLock
from src.workers import work_claims
from src.workers.campaign_manifest import CampaignManifest

LOCALES = ["de", "es", "hu", "ja", "ro"]


def _manifest_dict(tmp_path: Path, campaign_id: str) -> dict:
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
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


def _load(tmp_path: Path, campaign_id: str = "shard-launcher") -> CampaignManifest:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest_dict(tmp_path, campaign_id)), encoding="utf-8")
    return CampaignManifest.load(path)


class TestTryAcquireGpuLane:
    def test_succeeds_when_the_lane_is_free(self, tmp_path):
        ledger_root = tmp_path / "campaigns"
        lock = try_acquire_gpu_lane(ledger_root)
        assert lock is not None
        lock.release()

    def test_fails_while_externally_held(self, tmp_path):
        """Proves this is a real cross-process lock, not an in-process flag."""
        ledger_root = tmp_path / "campaigns"
        external = FileLock(gpu_lane_lock_path(ledger_root), timeout=0)
        external.acquire()
        try:
            assert try_acquire_gpu_lane(ledger_root) is None
        finally:
            external.release()

        # Once released, another launcher can acquire it.
        lock = try_acquire_gpu_lane(ledger_root)
        assert lock is not None
        lock.release()

    def test_lane_is_shared_across_different_campaigns_under_one_ledger_root(self, tmp_path):
        """The whole point: NOT per-campaign, unlike parallel-launcher.lock."""
        ledger_root = tmp_path / "campaigns"
        held_by_campaign_a = try_acquire_gpu_lane(ledger_root)
        assert held_by_campaign_a is not None
        try:
            # A second, unrelated campaign's launcher must also be refused.
            assert try_acquire_gpu_lane(ledger_root) is None
        finally:
            held_by_campaign_a.release()


class TestPartitionForWave:
    def test_lane_available_keeps_everything(self, tmp_path):
        manifest = _load(tmp_path)
        pending = list(manifest.shards(resume_receipts=set(), max_outputs=250))
        result = partition_for_wave(pending, GPU_PRIMARY_LOCALES, gpu_lane_available=True)
        assert result == pending

    def test_lane_unavailable_strips_gpu_bound_shards(self, tmp_path):
        manifest = _load(tmp_path)
        pending = list(manifest.shards(resume_receipts=set(), max_outputs=250))
        result = partition_for_wave(pending, GPU_PRIMARY_LOCALES, gpu_lane_available=False)
        assert sorted(s["locale"] for s in result) == ["de", "es"]


class TestSelectPendingShardsRespectsTheLane:
    def test_lane_unavailable_yields_api_bound_only(self, tmp_path):
        manifest = _load(tmp_path)
        ledger_root = tmp_path / "campaigns"

        selected = select_pending_shards(
            manifest, ledger_root, max_workers=4, gpu_lane_available=False
        )

        assert sorted(s["locale"] for s in selected) == ["de", "es"]


def _run_dry(tmp_path, campaign_id="shard-launcher", session_id=None):
    _load(tmp_path, campaign_id)
    argv = [
        "--campaign-manifest",
        str(tmp_path / "manifest.yaml"),
        "--ledger-root",
        str(tmp_path / "campaigns"),
        "--wait",
        "--dry-run",
    ]
    if session_id is not None:
        argv += ["--session-id", session_id]
    return main(argv)


class TestMainDefersGpuWorkWhenTheLaneIsHeld:
    def test_dry_run_excludes_gpu_bound_shards_and_reports_deferral(self, tmp_path, capsys):
        ledger_root = tmp_path / "campaigns"
        external = FileLock(gpu_lane_lock_path(ledger_root), timeout=0)
        external.acquire()
        try:
            status = _run_dry(tmp_path)
        finally:
            external.release()

        out = capsys.readouterr().out
        assert status == 0
        assert "deferring 3 GPU-bound shard(s)" in out
        for gpu_locale in GPU_PRIMARY_LOCALES:
            assert f":{gpu_locale}:" not in out

    def test_dry_run_includes_gpu_bound_shards_when_the_lane_is_free(self, tmp_path, capsys):
        status = _run_dry(tmp_path)
        out = capsys.readouterr().out

        assert status == 0
        assert "deferring" not in out
        # assign_shard_groups puts every GPU-bound shard in ONE group (sequential
        # by construction, TC-APT-047), so all of them are admitted in one wave.
        assert all(f":{locale}:" in out for locale in GPU_PRIMARY_LOCALES)


class TestMainRequiresTheFamilyClaim:
    def test_refuses_to_start_when_another_session_holds_the_family_claim(self, tmp_path, capsys):
        _load(tmp_path, "shard-launcher")
        claims_path = tmp_path / "campaigns" / "claims.jsonl"
        assert work_claims.acquire_claim(
            "family:shard-launcher", "other-session", claims_path=claims_path
        )

        status = _run_dry(tmp_path, session_id="this-session")

        assert status == 1
        assert "family:shard-launcher" in capsys.readouterr().err

    def test_proceeds_and_releases_the_claim_when_unclaimed(self, tmp_path):
        status = _run_dry(tmp_path, session_id="this-session")
        claims_path = tmp_path / "campaigns" / "claims.jsonl"

        assert status == 0
        assert work_claims.active_claim("family:shard-launcher", claims_path=claims_path) is None

    def test_the_same_session_can_restart_its_own_claim(self, tmp_path):
        """A launcher relaunched by the same session (e.g. after a --drain pass) is not
        locked out by its own prior claim."""
        _load(tmp_path, "shard-launcher")
        claims_path = tmp_path / "campaigns" / "claims.jsonl"
        work_claims.acquire_claim("family:shard-launcher", "this-session", claims_path=claims_path)

        status = _run_dry(tmp_path, session_id="this-session")

        assert status == 0
