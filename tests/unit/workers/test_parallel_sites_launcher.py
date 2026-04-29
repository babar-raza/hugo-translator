"""
Unit tests for parallel site launcher logic (src/utils/parallel_sites.py).

Verifies:
- Correct subprocess args per site
- All 4 production sites are launched
- Processes are launched in parallel (non-blocking Popen, not wait())
- Exit codes are collected correctly
- VRAM clamp logic
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

PROD_SITES = [
    "products.aspose.net",
    "docs.aspose.net",
    "kb.aspose.net",
    "blog.aspose.net",
]


def _load():
    from src.utils.parallel_sites import (
        build_site_cli_args,
        clamp_gpu_memory,
        launch_sites,
    )
    return build_site_cli_args, clamp_gpu_memory, launch_sites


# ---------------------------------------------------------------------------
# build_site_cli_args
# ---------------------------------------------------------------------------

class TestBuildSiteCliArgs:
    def test_site_flag_present(self):
        build, _, _ = _load()
        args = build("products.aspose.net")
        assert "--site" in args
        assert args[args.index("--site") + 1] == "products.aspose.net"

    def test_parallel_languages_value(self):
        build, _, _ = _load()
        args = build("products.aspose.net", parallel_languages=8)
        assert args[args.index("--parallel-languages") + 1] == "8"

    def test_auto_select_model_included_by_default(self):
        build, _, _ = _load()
        assert "--auto-select-model" in build("products.aspose.net")

    def test_auto_select_model_omitted_when_false(self):
        build, _, _ = _load()
        assert "--auto-select-model" not in build("products.aspose.net", auto_select_model=False)

    def test_dry_run_included_when_true(self):
        build, _, _ = _load()
        assert "--dry-run" in build("products.aspose.net", dry_run=True)

    def test_dry_run_absent_when_false(self):
        build, _, _ = _load()
        assert "--dry-run" not in build("products.aspose.net", dry_run=False)

    def test_all_four_site_names_produce_distinct_args(self):
        build, _, _ = _load()
        site_values = []
        for site_id in PROD_SITES:
            args = build(site_id)
            site_values.append(args[args.index("--site") + 1])
        assert site_values == PROD_SITES

    def test_cpu_device_sets_device_flag(self):
        build, _, _ = _load()
        args = build("products.aspose.net", device="cpu")
        assert "--device" in args
        assert args[args.index("--device") + 1] == "cpu"

    def test_cpu_device_omits_gpu_memory_percent(self):
        build, _, _ = _load()
        args = build("products.aspose.net", device="cpu", max_gpu_memory_percent=20)
        assert "--max-gpu-memory-percent" not in args

    def test_auto_device_does_not_set_device_flag(self):
        build, _, _ = _load()
        args = build("products.aspose.net", device="auto")
        assert "--device" not in args


# ---------------------------------------------------------------------------
# launch_sites — subprocess concurrency
# ---------------------------------------------------------------------------

class TestLaunchSites:
    def test_spawns_correct_number_of_processes(self):
        _, _, launch = _load()
        mock_proc = MagicMock(spec=subprocess.Popen)
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            procs = launch(PROD_SITES)
        assert len(procs) == len(PROD_SITES)
        assert mock_popen.call_count == len(PROD_SITES)

    def test_all_four_sites_get_their_own_subprocess(self):
        _, _, launch = _load()
        mock_proc = MagicMock(spec=subprocess.Popen)
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            launch(PROD_SITES)
        called_sites = []
        for call_args in mock_popen.call_args_list:
            cmd = call_args[0][0]
            called_sites.append(cmd[cmd.index("--site") + 1])
        assert set(called_sites) == set(PROD_SITES)

    def test_processes_launched_concurrently_not_sequentially(self):
        """launch_sites() must NOT call .wait() or .communicate() between Popen calls."""
        _, _, launch = _load()
        call_order: list[str] = []

        class TrackingPopen:
            def __init__(self, *a, **kw):
                call_order.append("popen")
                self.returncode = 0

            def wait(self, *a, **kw):
                call_order.append("wait")
                return 0

            def poll(self):
                return 0

        with patch("subprocess.Popen", side_effect=TrackingPopen):
            launch(PROD_SITES)

        popen_indices = [i for i, x in enumerate(call_order) if x == "popen"]
        wait_indices = [i for i, x in enumerate(call_order) if x == "wait"]

        # All Popen calls must precede any blocking wait
        if wait_indices:
            assert max(popen_indices) < min(wait_indices), (
                "Expected all sites to be launched before any blocking wait"
            )
        else:
            # No waits at all in launch_sites() — correct
            assert len(popen_indices) == len(PROD_SITES)

    def test_each_subprocess_gets_auto_select_model(self):
        _, _, launch = _load()
        mock_proc = MagicMock(spec=subprocess.Popen)
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            launch(PROD_SITES, auto_select_model=True)
        for call_args in mock_popen.call_args_list:
            cmd = call_args[0][0]
            assert "--auto-select-model" in cmd

    def test_exit_codes_collected_from_returned_handles(self):
        _, _, launch = _load()
        exit_sequence = [0, 0, 1, 0]  # kb.aspose.net fails
        mock_procs = []
        for code in exit_sequence:
            m = MagicMock(spec=subprocess.Popen)
            m.returncode = code
            mock_procs.append(m)
        with patch("subprocess.Popen", side_effect=mock_procs):
            procs = launch(PROD_SITES)
        assert [p.returncode for p in procs] == exit_sequence
        assert procs[2].returncode == 1  # kb failed

    def test_dry_run_passes_through_to_every_subprocess(self):
        _, _, launch = _load()
        mock_proc = MagicMock(spec=subprocess.Popen)
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            launch(PROD_SITES, dry_run=True)
        for call_args in mock_popen.call_args_list:
            cmd = call_args[0][0]
            assert "--dry-run" in cmd

    def test_single_site_spawns_one_process(self):
        _, _, launch = _load()
        mock_proc = MagicMock(spec=subprocess.Popen)
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            procs = launch(["blog.aspose.net"])
        assert len(procs) == 1
        assert mock_popen.call_count == 1


# ---------------------------------------------------------------------------
# clamp_gpu_memory
# ---------------------------------------------------------------------------

class TestClampGpuMemory:
    def test_within_budget_not_clamped(self):
        _, clamp, _ = _load()
        # 2 sites × 40% = 80% <= 85%
        assert clamp(2, 40) == 40

    def test_over_budget_is_clamped(self):
        _, clamp, _ = _load()
        # 4 sites × 50% = 200% >> 85%; floor(85/4) = 21
        assert clamp(4, 50) == 21

    def test_clamped_result_is_always_positive(self):
        _, clamp, _ = _load()
        assert clamp(10, 50) > 0

    def test_single_site_not_clamped_at_85(self):
        _, clamp, _ = _load()
        assert clamp(1, 85) == 85

    def test_four_sites_at_20_percent_is_safe(self):
        _, clamp, _ = _load()
        # 4 × 20 = 80 <= 85; no clamp needed
        assert clamp(4, 20) == 20

    def test_zero_sites_returns_requested(self):
        _, clamp, _ = _load()
        assert clamp(0, 50) == 50
