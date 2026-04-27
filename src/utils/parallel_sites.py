"""
parallel_sites.py

Thin helper for launching multiple site translation subprocesses in parallel.
Called by scripts/run_parallel_sites.ps1 (via site-discovery one-liner) and
tested by tests/unit/workers/test_parallel_sites_launcher.py.

No ML dependencies — stdlib only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def build_site_cli_args(
    site_id: str,
    parallel_languages: int = 4,
    max_gpu_memory_percent: int = 20,
    auto_select_model: bool = True,
    log_level: str = "INFO",
    dry_run: bool = False,
    device: str = "auto",
) -> list[str]:
    """Build the CLI argument list for one site subprocess."""
    args = [
        sys.executable, "-m", "src.cli",
        "--site", site_id,
        "--parallel-languages", str(parallel_languages),
        "--log-level", log_level,
    ]
    if auto_select_model:
        args.append("--auto-select-model")
    if device != "auto":
        args.extend(["--device", device])
    if max_gpu_memory_percent > 0 and device != "cpu":
        args.extend(["--max-gpu-memory-percent", str(max_gpu_memory_percent)])
    if dry_run:
        args.append("--dry-run")
    return args


def clamp_gpu_memory(
    n_sites: int,
    requested_percent: int,
    budget_percent: int = 85,
) -> int:
    """Return the safe per-process GPU memory cap for n concurrent sites.

    Ensures n_sites * result <= budget_percent of total VRAM.
    RTX 4090 baseline: floor(85 / 4) = 21% per site ≈ 5 GB — safe for M2M100.
    """
    if n_sites <= 0:
        return requested_percent
    max_safe = budget_percent // n_sites
    return min(requested_percent, max_safe)


def launch_sites(
    sites: list[str],
    parallel_languages: int = 4,
    max_gpu_memory_percent: int = 20,
    auto_select_model: bool = True,
    log_level: str = "INFO",
    dry_run: bool = False,
    device: str = "auto",
    log_dir: Path | None = None,
) -> list[subprocess.Popen]:
    """Launch one subprocess per site in parallel (non-blocking).

    Returns the list of Popen handles so the caller can wait on them.
    All processes are started before any blocking wait occurs.
    """
    processes: list[subprocess.Popen] = []
    for site_id in sites:
        cmd = build_site_cli_args(
            site_id=site_id,
            parallel_languages=parallel_languages,
            max_gpu_memory_percent=max_gpu_memory_percent,
            auto_select_model=auto_select_model,
            log_level=log_level,
            dry_run=dry_run,
            device=device,
        )
        stdout_dest = subprocess.DEVNULL
        stderr_dest = subprocess.DEVNULL
        if log_dir is not None:
            stdout_dest = open(log_dir / f"{site_id}.log", "w", encoding="utf-8")
            stderr_dest = open(log_dir / f"{site_id}.err", "w", encoding="utf-8")

        proc = subprocess.Popen(cmd, stdout=stdout_dest, stderr=stderr_dest)
        processes.append(proc)
    return processes
