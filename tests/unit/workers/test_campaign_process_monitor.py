from src.workers.campaign_process_monitor import CampaignProcessMonitor


def test_campaign_process_monitor_marks_ancestry_owned(tmp_path):
    monitor = CampaignProcessMonitor(
        campaign_id="campaign-x",
        evidence_path=tmp_path / "events.jsonl",
        roots=(tmp_path,),
    )
    assert monitor._owned(
        {"pid": 11, "ppid": 10, "command": "conhost.exe"},
        {10: {"ppid": 1, "command": "python run --campaign campaign-x"}},
    )


def test_campaign_process_monitor_ignores_unrelated_parent(tmp_path):
    monitor = CampaignProcessMonitor(
        campaign_id="campaign-x",
        evidence_path=tmp_path / "events.jsonl",
        roots=(tmp_path,),
    )
    assert not monitor._owned(
        {"pid": 11, "ppid": 10, "command": "conhost.exe"},
        {10: {"ppid": 1, "command": "unrelated.exe"}},
    )
