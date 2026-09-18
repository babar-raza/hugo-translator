from types import SimpleNamespace
import pytest
from scripts.campaign.launch_parallel_campaign_shards import checkpoint_wave
from scripts.campaign.campaign_progress import current_run_progress
from src.tm.intent_spool import TMIntentSpool


def test_empty_spool_commits_only_after_drain(tmp_path, monkeypatch):
    spool = tmp_path / "spool.sqlite3"
    TMIntentSpool(spool)
    calls = []
    monkeypatch.setattr("scripts.campaign.launch_parallel_campaign_shards.subprocess.run",
                        lambda command, **kw: calls.append((command, kw)))
    args = SimpleNamespace(tm_intent_spool_path=spool, tm_repository_root=tmp_path,
                           campaign_manifest=tmp_path / "manifest.yaml", ledger_root=tmp_path)
    checkpoint_wave(args, SimpleNamespace(campaign_id="test", content_repo=tmp_path), tmp_path)
    assert len(calls) == 1
    assert calls[0][0][-3:] == ["--min-batch-size", "25", "--execute"]
    assert calls[0][1] == {"check": True, "timeout": 900}


@pytest.mark.parametrize("state", [{"CLAIMED": 1}, {"FAILED": 1}])
def test_unsafe_spool_never_commits(tmp_path, monkeypatch, state):
    monkeypatch.setattr(TMIntentSpool, "stats", lambda self: state)
    monkeypatch.setattr("scripts.campaign.launch_parallel_campaign_shards.subprocess.run",
                        lambda *a, **k: pytest.fail("unsafe checkpoint executed"))
    with pytest.raises(RuntimeError):
        checkpoint_wave(SimpleNamespace(tm_intent_spool_path=tmp_path / "spool.sqlite3"),
                        SimpleNamespace(campaign_id="test"), tmp_path)


def test_rate_uses_current_wave_not_historical_downtime():
    state = {"status": "RUNNING", "updated_at": 1000, "elapsed_seconds": 900,
             "accepted_current_run": 33, "rejected_current_run": 5}
    result = current_run_progress(state, 1010, 100000)
    assert result["rate_per_minute"] == 2.2
    assert result["rejected"] == 5
    assert current_run_progress(state, 1201, 100000)["eta_minutes"] is None
    state["status"] = "PAUSED_INFRASTRUCTURE_TIMEOUT"
    assert current_run_progress(state, 1010, 100000)["rate_per_minute"] is None


def test_shard_identity_survives_partial_and_full_resume():
    from src.workers.campaign_manifest import CampaignManifest
    sources = [SimpleNamespace(wave=0, site_id="site", family="family", platform="net",
                               source_path=f"source-{i}", outputs={"de": f"out-{i}"})
               for i in range(6)]
    manifest = SimpleNamespace(sources=sources, target_locales=["de"])
    original = list(CampaignManifest.shards(manifest, max_outputs=2))
    resumed = list(CampaignManifest.shards(manifest, max_outputs=2,
                                          resume_receipts={"out-0", "out-1", "out-2"}))
    assert [s["shard_id"] for s in resumed] == [s["shard_id"] for s in original[1:]]
    assert [j[2] for s in resumed for j in s["jobs"]] == ["out-3", "out-4", "out-5"]
