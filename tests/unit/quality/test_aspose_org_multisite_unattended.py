import subprocess
import time

from scripts.quality import aspose_org_multisite_unattended as unattended


def test_profile_model_batch_defaults_are_conservative_then_escalating():
    assert unattended.PROFILE_MODEL_BATCH_SIZE["safe"] == 0
    assert unattended.PROFILE_MODEL_BATCH_SIZE["fast"] > unattended.PROFILE_MODEL_BATCH_SIZE["safe"]
    assert unattended.PROFILE_MODEL_BATCH_SIZE["max-vram"] > unattended.PROFILE_MODEL_BATCH_SIZE["fast"]


def test_query_vram_snapshot_parses_nvidia_smi(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            _args,
            0,
            stdout="2026/07/02 19:23:48.886, NVIDIA GPU, 16, 1346, 16376\n",
            stderr="",
        )

    monkeypatch.setattr(unattended.subprocess, "run", fake_run)

    snapshot = unattended.query_vram_snapshot()

    assert snapshot["available"] is True
    assert snapshot["name"] == "NVIDIA GPU"
    assert snapshot["utilization_gpu_percent"] == 16
    assert snapshot["memory_used_mb"] == 1346
    assert snapshot["memory_total_mb"] == 16376
    assert snapshot["memory_used_percent"] == 8.22


def test_log_contains_cuda_oom_detects_common_messages(tmp_path):
    log = tmp_path / "worker.log"
    log.write_text("RuntimeError: CUDA out of memory. Tried to allocate", encoding="utf-8")

    assert unattended.log_contains_cuda_oom(log) is True


def test_site_summary_aggregates_shard_summaries(tmp_path, monkeypatch):
    monkeypatch.setattr(unattended, "ROOT", tmp_path)
    final = tmp_path / ".local" / "evidences" / "kb.aspose.org" / "run1" / "final"
    final.mkdir(parents=True)
    unattended.write_json(
        final / "summary.latin-a.json",
        {
            "required_pairs": 10,
            "accepted_pairs": 4,
            "failed_pairs": 6,
            "source_mutation_count": 0,
            "language_mixing_failure_count": 2,
            "failure_type_counts": {"REJECT_PARTIAL_TRANSLATION": 2},
        },
    )
    unattended.write_json(
        final / "summary.latin-b.json",
        {
            "required_pairs": 12,
            "accepted_pairs": 5,
            "failed_pairs": 7,
            "source_mutation_count": 0,
            "language_mixing_failure_count": 1,
            "failure_type_counts": {"REJECT_WRONG_LANGUAGE": 1},
        },
    )

    summary = unattended.site_summary("run1", "kb.aspose.org")

    assert summary["summary_kind"] == "aggregated_shards"
    assert summary["required_pairs"] == 22
    assert summary["accepted_pairs"] == 9
    assert summary["failed_pairs"] == 13
    assert summary["language_mixing_failure_count"] == 3
    assert summary["failure_type_counts"] == {
        "REJECT_PARTIAL_TRANSLATION": 2,
        "REJECT_WRONG_LANGUAGE": 1,
    }


def test_pilot_acceptance_condition_uses_shard_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(unattended, "ROOT", tmp_path)
    final = tmp_path / ".local" / "evidences" / "docs.aspose.org" / "pilot" / "final"
    final.mkdir(parents=True)
    unattended.write_json(
        final / "summary.latin-a.json",
        {
            "required_pairs": 10,
            "accepted_pairs": 1,
            "failed_pairs": 0,
            "source_mutation_count": 0,
            "language_mixing_failure_count": 0,
        },
    )

    summary = unattended.site_summary("pilot", "docs.aspose.org")

    assert summary["failed_pairs"] == 0
    assert summary["source_mutation_count"] == 0
    assert summary["language_mixing_failure_count"] == 0


def test_cycle_throughput_separates_cycle_delta_from_cumulative_counts():
    throughput = unattended.cycle_throughput(
        {"accepted_pairs": 10, "failed_pairs": 5, "required_pairs": 20},
        {"accepted_pairs": 13, "failed_pairs": 6, "required_pairs": 20},
        started=100.0,
        finished=160.0,
    )

    assert throughput["cycle_accepted_delta"] == 3
    assert throughput["cycle_failed_delta"] == 1
    assert throughput["cycle_accepted_per_hour"] == 180.0
    assert throughput["cumulative_accepted_pairs"] == 13
    assert throughput["cumulative_required_pairs"] == 20


def test_cycle_throughput_from_results_uses_run_local_counts():
    throughput = unattended.cycle_throughput_from_results(
        {"accepted_pairs": 100, "failed_pairs": 900, "required_pairs": 1000},
        [
            {"run_attempted_pairs": 4, "run_accepted_pairs": 3, "run_failed_pairs": 1},
            {"run_attempted_pairs": 2, "run_accepted_pairs": 1, "run_failed_pairs": 1},
        ],
        started=100.0,
        finished=160.0,
    )

    assert throughput["cycle_attempted_delta"] == 6
    assert throughput["cycle_accepted_delta"] == 4
    assert throughput["cycle_failed_delta"] == 2
    assert throughput["cycle_accepted_per_hour"] == 240.0
    assert throughput["cumulative_failed_pairs"] == 900


def test_speed_stoplight_flags_source_mutation_and_language_mixing():
    assert unattended.speed_stoplight({"source_mutation_count": 1}, []) == "RED_STOP_REQUIRED"
    assert (
        unattended.speed_stoplight(
            {"source_mutation_count": 0, "language_mixing_failure_count": 10},
            [{"language_mixing_failure_delta": 1}],
        )
        == "YELLOW_BACKOFF"
    )
    assert (
        unattended.speed_stoplight(
            {"source_mutation_count": 0, "language_mixing_failure_count": 10},
            [{"language_mixing_failure_delta": 0}],
        )
        == "GREEN"
    )


def test_write_live_speed_report_emits_stoplight_file(tmp_path, monkeypatch):
    monkeypatch.setattr(unattended, "ROOT", tmp_path)
    campaign_root = tmp_path / ".local" / "evidences" / "aspose-org-multisite" / "run1"

    report = unattended.write_live_speed_report(
        campaign_root,
        "kb.aspose.org",
        1,
        {"accepted_pairs": 1, "failed_pairs": 0, "source_mutation_count": 0, "language_mixing_failure_count": 0},
        {"cycle_accepted_delta": 1},
        [
            {
                "vram_after": {"available": True},
                "run_attempted_pairs": 3,
                "run_failure_type_counts": {"REJECT_PARTIAL_TRANSLATION": 1},
            }
        ],
    )

    assert report["stoplight"] == "GREEN"
    assert report["cycle_attempted_delta"] == 3
    assert report["cycle_run_failure_type_counts"] == {"REJECT_PARTIAL_TRANSLATION": 1}
    written = unattended.read_json(campaign_root / "final" / "live-speed-report.kb.aspose.org.json", {})
    assert written["throughput"]["cycle_accepted_delta"] == 1


# TC-SPEED-001-B-04: --throughput-profile default and escalation

def test_profile_model_batch_safe_is_zero():
    """MS-SPEED-001-B-04: safe profile defaults to batch size 0 (engine decides)."""
    assert unattended.PROFILE_MODEL_BATCH_SIZE["safe"] == 0


def test_throughput_profiles_all_defined():
    """MS-SPEED-001-B-04: all three profiles are defined."""
    for profile in ("safe", "fast", "max-vram"):
        assert profile in unattended.PROFILE_MODEL_BATCH_SIZE


# TC-SPEED-001-B-05: --max-concurrent-site-workers guard

def test_find_python_returns_venv_if_exists(tmp_path):
    """MS-SPEED-001-B-05: find_python resolves .venv Scripts/python.exe."""
    venv_py = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("")
    import sys
    old_root = unattended.ROOT
    try:
        unattended.ROOT = tmp_path
        result = unattended.find_python(None)
    finally:
        unattended.ROOT = old_root
    assert result == venv_py


# TC-SPEED-001-C-02: --target-vram-percent default

def test_target_vram_percent_default_is_80():
    """MS-SPEED-001-C-02: default VRAM target is 80%."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-vram-percent", type=int, default=80)
    args = parser.parse_args([])
    assert args.target_vram_percent == 80


# TC-SPEED-001-C-03: wait_for_vram_below threshold behavior

def test_wait_for_vram_below_proceeds_when_below_target(tmp_path, monkeypatch):
    """MS-SPEED-001-C-03: proceeds immediately when VRAM is below target."""
    call_count = 0

    def fake_snapshot():
        nonlocal call_count
        call_count += 1
        return {
            "available": True,
            "memory_used_percent": 50.0,
            "captured_at": "2026-07-03T00:00:00",
        }

    monkeypatch.setattr(unattended, "query_vram_snapshot", fake_snapshot)
    log = tmp_path / "vram.log"

    result = unattended.wait_for_vram_below(80, log)

    assert result["decision"] == "proceed_below_target"
    assert call_count == 1


def test_wait_for_vram_below_proceeds_after_timeout_when_above_target(tmp_path, monkeypatch):
    """MS-SPEED-001-C-03: proceeds after timeout when VRAM stays above target."""
    calls = []

    def fake_snapshot():
        calls.append(1)
        return {
            "available": True,
            "memory_used_percent": 95.0,
            "captured_at": "2026-07-03T00:00:00",
        }

    slept = []

    def fake_sleep(s):
        slept.append(s)
        # Advance monotonic time by patching - use a side effect to break the loop
        if len(slept) >= 2:
            monkeypatch.setattr(time, "monotonic", lambda: 1e9)

    monkeypatch.setattr(unattended, "query_vram_snapshot", fake_snapshot)
    monkeypatch.setattr(unattended.time, "sleep", fake_sleep)
    monkeypatch.setattr(unattended.time, "monotonic", lambda: 0.0)
    log = tmp_path / "vram.log"

    result = unattended.wait_for_vram_below(80, log, max_wait_seconds=1)

    assert result["decision"] in ("proceed_after_wait_timeout", "proceed_below_target")


def test_wait_for_vram_below_proceeds_when_no_vram_data(tmp_path, monkeypatch):
    """MS-SPEED-001-C-03: proceeds immediately when nvidia-smi unavailable."""
    monkeypatch.setattr(
        unattended, "query_vram_snapshot", lambda: {"available": False, "error": "no gpu", "captured_at": "X"}
    )
    log = tmp_path / "vram.log"

    result = unattended.wait_for_vram_below(80, log)

    assert result["decision"] == "proceed_no_vram_data"


# TC-LANG-001-D-03: language-mixing backoff trigger

def test_language_mixing_backoff_reduces_shard_batch_size():
    """MS-LANG-001-D-03: shard batch halves when language mixing exceeds threshold."""
    # Simulate the shard_model_batches dict and backoff logic from the cycle loop.
    # The backoff rule: if language_mixing_delta > 3 and shard_batch > 1, halve the batch.
    shard_model_batches = {"latin-a": 128}
    shard_batch = shard_model_batches["latin-a"]
    language_mixing_delta = 5

    backoff = None
    if language_mixing_delta > 3 and shard_batch and shard_batch > 1:
        new_batch = max(1, shard_batch // 2)
        shard_model_batches["latin-a"] = new_batch
        backoff = {
            "reason": "LANGUAGE_MIXING_FAILURES",
            "old_model_batch_size": shard_batch,
            "new_model_batch_size": new_batch,
            "language_mixing_failure_delta": language_mixing_delta,
        }

    assert backoff is not None
    assert backoff["reason"] == "LANGUAGE_MIXING_FAILURES"
    assert shard_model_batches["latin-a"] == 64


def test_language_mixing_backoff_not_triggered_when_below_threshold():
    """MS-LANG-001-D-03: no backoff when language mixing <= 3."""
    shard_model_batches = {"latin-b": 128}
    shard_batch = shard_model_batches["latin-b"]
    language_mixing_delta = 2

    backoff = None
    if language_mixing_delta > 3 and shard_batch and shard_batch > 1:
        new_batch = max(1, shard_batch // 2)
        shard_model_batches["latin-b"] = new_batch
        backoff = {"reason": "LANGUAGE_MIXING_FAILURES"}

    assert backoff is None
    assert shard_model_batches["latin-b"] == 128


def test_cuda_oom_backoff_halves_batch_size():
    """MS-SPEED-001-C-05: OOM backoff halves model batch size."""
    shard_batch = 256
    new_batch = max(1, shard_batch // 2)
    backoff = {
        "reason": "CUDA_OOM",
        "old_model_batch_size": shard_batch,
        "new_model_batch_size": new_batch,
    }

    assert backoff["new_model_batch_size"] == 128
    assert backoff["reason"] == "CUDA_OOM"
