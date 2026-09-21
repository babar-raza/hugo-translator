from scripts.campaign.launch_parallel_campaign_shards import TerminalProgressDeadline


def test_healthy_campaign_survives_many_wall_time_limits():
    deadline = TerminalProgressDeadline(0, (0, 0))
    for step in range(1, 101):
        assert not deadline.expired(step * 600, (step, 0), 900)


def test_rejected_jobs_are_terminal_progress():
    deadline = TerminalProgressDeadline(0, (0, 0))
    assert not deadline.expired(899, (0, 1), 900)
    assert not deadline.expired(1798, (0, 1), 900)
    assert deadline.expired(1799, (0, 1), 900)


def test_heartbeat_without_terminal_progress_cannot_extend_deadline():
    deadline = TerminalProgressDeadline(0, (4, 2))
    assert not deadline.expired(899, (4, 2), 900)
    assert deadline.expired(900, (4, 2), 900)


def test_disabled_deadline():
    assert not TerminalProgressDeadline(0, (0, 0)).expired(10000, (0, 0), 0)
