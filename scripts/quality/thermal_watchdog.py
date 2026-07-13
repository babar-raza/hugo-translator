"""Thermal watchdog for parallel GPU heal campaigns.

Polls GPU temperature every N seconds via nvidia-smi. When temperature exceeds the
kill threshold, kills the most-recently-started NLLB process (fewest done-file entries
= least GPU work lost). Optionally restarts the killed process when temperature recovers.

Usage:
    python scripts/quality/thermal_watchdog.py              # normal operation
    python scripts/quality/thermal_watchdog.py --dry-run    # discover + log without killing
    python scripts/quality/thermal_watchdog.py --self-test  # mock temp=85°C, verify flow

Config: config/global.yaml -> resource_governance -> temperature_* keys
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent.parent.parent.resolve()
LOCAL = BASE / ".local"
PY = BASE / ".venv" / "Scripts" / "python.exe"
HEAL_SCRIPT = BASE / "scripts" / "quality" / "heal_english_headings.py"
KILLED_RECORD = LOCAL / "thermal_killed.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("thermal_watchdog")


def _load_config() -> dict:
    cfg_path = BASE / "config" / "global.yaml"
    try:
        import yaml  # type: ignore
        with open(cfg_path, encoding="utf-8") as f:
            full = yaml.safe_load(f)
        return full.get("resource_governance", {})
    except Exception as exc:
        log.warning("Failed to load config/global.yaml: %s — using defaults", exc)
        return {}


def _read_gpu_temp(mock_temp: int | None = None) -> int | None:
    if mock_temp is not None:
        return mock_temp
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return int(result.stdout.strip().split("\n")[0])
    except subprocess.TimeoutExpired:
        log.error("nvidia-smi timed out after 10s")
        return None
    except Exception as exc:
        log.error("Failed to read GPU temp: %s", exc)
        return None


def _discover_pids() -> list[dict]:
    """Return list of running heal and shard processes with metadata."""
    try:
        import psutil
    except ImportError:
        log.error("psutil not available — cannot discover PIDs")
        return []

    procs: list[dict] = []

    # 1. Heal processes via *.lock files
    for lock_file in LOCAL.glob("heal_*.lock"):
        try:
            pid = int(lock_file.read_text().strip())
            proc = psutil.Process(pid)
            if not proc.is_running():
                continue
            cmdline = " ".join(proc.cmdline())
            if "heal_english_headings" not in cmdline:
                continue
            # Derive model from cmdline
            model_id = "nllb_200_1.3b"  # default assumption
            if "--model" in proc.cmdline():
                idx = proc.cmdline().index("--model")
                if idx + 1 < len(proc.cmdline()):
                    model_id = proc.cmdline()[idx + 1]
            sm_weight = 32 if "nllb" in model_id.lower() else 8
            start_time = proc.create_time()
            procs.append({
                "pid": pid,
                "source": "heal",
                "model_id": model_id,
                "sm_weight": sm_weight,
                "start_time": start_time,
                "lock_file": str(lock_file),
                "cmdline": proc.cmdline(),
            })
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass

    # 2. Shard processes via shard_registry.json
    registry_path = LOCAL / "shard_registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text())
            for pid_str, info in registry.items():
                try:
                    pid = int(pid_str)
                    proc = psutil.Process(pid)
                    if not proc.is_running():
                        continue
                    cmdline = " ".join(proc.cmdline())
                    if "unified_translate.py" not in cmdline:
                        continue
                    procs.append({
                        "pid": pid,
                        "source": "shard",
                        "model_id": info.get("model_id", "unknown"),
                        "sm_weight": info.get("sm_weight", 32),
                        "start_time": info.get("start_time", 0.0),
                        "lock_file": None,
                        "cmdline": proc.cmdline(),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    pass
        except Exception as exc:
            log.warning("Could not read shard_registry.json: %s", exc)

    return procs


def _kill_target(procs: list[dict], dry_run: bool) -> dict | None:
    """Kill the most-recently-started NLLB process. Returns killed proc dict."""
    if not procs:
        log.info("No GPU processes found — nothing to kill")
        return None

    nllb = [p for p in procs if "nllb" in p["model_id"].lower() or p["sm_weight"] >= 30]
    candidates = sorted(nllb, key=lambda p: p["start_time"], reverse=True) if nllb else \
                 sorted(procs, key=lambda p: p["sm_weight"], reverse=True)

    target = candidates[0]
    import psutil
    try:
        import time as _time
        started_str = _time.strftime("%H:%M:%S", _time.localtime(target["start_time"]))
        log.warning(
            "%sKilling PID %d (%s, sm=%d%%, started=%s)",
            "DRY-RUN: would be " if dry_run else "",
            target["pid"],
            target["model_id"],
            target["sm_weight"],
            started_str,
        )
        if not dry_run:
            psutil.Process(target["pid"]).terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        log.error("Failed to kill PID %d: %s", target["pid"], exc)
        return None

    return target


def _record_killed(proc: dict, temp: int) -> None:
    launch_args = []
    cmdline = proc.get("cmdline", [])
    if cmdline:
        # Strip interpreter and script path; keep everything after the script
        try:
            script_idx = next(
                i for i, a in enumerate(cmdline)
                if "heal_english_headings" in a or "unified_translate" in a
            )
            launch_args = cmdline[script_idx + 1:]
        except StopIteration:
            launch_args = cmdline[2:] if len(cmdline) > 2 else []

    record = {
        "killed_at_epoch": time.time(),
        "temp_at_kill": temp,
        "pid": proc["pid"],
        "model_id": proc["model_id"],
        "sm_weight": proc["sm_weight"],
        "source": proc["source"],
        "lock_file": proc.get("lock_file"),
        "launch_args": launch_args,
        "script": str(HEAL_SCRIPT) if proc["source"] == "heal" else None,
    }
    KILLED_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")
    log.info("Kill record written to %s", KILLED_RECORD)


def _has_killed_record() -> bool:
    return KILLED_RECORD.exists()


def _restart_killed_process() -> None:
    try:
        record = json.loads(KILLED_RECORD.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("Could not read kill record: %s", exc)
        return

    launch_args = record.get("launch_args", [])
    script_path = record.get("script") or str(HEAL_SCRIPT)
    model_id = record.get("model_id", "unknown")

    log.info("Auto-restarting killed process: %s %s", Path(script_path).name, " ".join(launch_args))

    log_stem = f"thermal_restart_{int(time.time())}"
    log_out = open(LOCAL / f"{log_stem}.log", "w", encoding="utf-8")
    log_err = open(LOCAL / f"{log_stem}.err", "w", encoding="utf-8")

    try:
        new_proc = subprocess.Popen(
            [str(PY), script_path] + launch_args,
            stdout=log_out,
            stderr=log_err,
            cwd=str(BASE),
        )
        log.info("Restarted PID %d (%s) — logs at .local/%s.log", new_proc.pid, model_id, log_stem)
        KILLED_RECORD.unlink(missing_ok=True)
    except Exception as exc:
        log.error("Failed to restart killed process: %s", exc)


def main(dry_run: bool = False, self_test: bool = False) -> None:
    cfg = _load_config()
    WARN = cfg.get("temperature_warn_celsius", 78)
    KILL = cfg.get("temperature_kill_celsius", 83)
    RECOVER = cfg.get("temperature_recover_celsius", 70)
    POLL = cfg.get("temperature_poll_interval_sec", 30)
    AUTO_RESTART = cfg.get("temperature_auto_restart", True)

    log.info(
        "Thermal watchdog started — warn=%d°C kill=%d°C recover=%d°C poll=%ds auto_restart=%s%s",
        WARN, KILL, RECOVER, POLL, AUTO_RESTART,
        " [DRY-RUN]" if dry_run else "",
    )

    if self_test:
        dry_run = True  # self-test always implies dry-run — never kills real processes

    mock_temp = 85 if self_test else None
    kill_cooldown = 0  # remaining poll cycles to suppress post-kill check

    while True:
        temp = _read_gpu_temp(mock_temp=mock_temp)
        if temp is None:
            time.sleep(POLL)
            continue

        procs = _discover_pids()
        if self_test:
            log.info("SELF-TEST: mock temp=%d°C, discovered %d processes", temp, len(procs))

        if kill_cooldown > 0:
            kill_cooldown -= 1
            log.info("temp=%d°C cooldown=%d procs=%d", temp, kill_cooldown, len(procs))
        elif temp >= KILL:
            target = _kill_target(procs, dry_run=dry_run)
            if target and not dry_run:
                _record_killed(target, temp)
                kill_cooldown = 2
            elif target and dry_run:
                kill_cooldown = 2
        elif temp >= WARN:
            log.warning("temp=%d°C approaching kill threshold (%d°C) procs=%d", temp, KILL, len(procs))
        else:
            log.info("temp=%d°C procs=%d", temp, len(procs))

        if AUTO_RESTART and _has_killed_record() and temp <= RECOVER:
            if not dry_run:
                _restart_killed_process()
            else:
                log.info("DRY-RUN: would restart killed process (temp=%d°C <= recover=%d°C)", temp, RECOVER)

        if self_test:
            log.info("SELF-TEST complete — exiting")
            return

        time.sleep(POLL)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GPU thermal watchdog for parallel heal campaigns")
    parser.add_argument("--dry-run", action="store_true", help="Discover and log without killing")
    parser.add_argument("--self-test", action="store_true", help="Mock 85°C temp, verify flow, exit")
    args = parser.parse_args()

    main(dry_run=args.dry_run, self_test=args.self_test)
