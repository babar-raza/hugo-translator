"""Evidence-only monitor for campaign-owned Windows console processes."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_WATCHED = {"conhost.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "wt.exe"}


class CampaignProcessMonitor:
    def __init__(self, *, campaign_id: str, evidence_path: Path, roots: tuple[Path, ...]):
        self.campaign_id = campaign_id
        self.evidence_path = evidence_path
        self.roots = tuple(str(root).lower() for root in roots)
        self._known: set[int] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.incident = False

    def _snapshot(self) -> dict[int, dict]:
        import psutil
        rows: dict[int, dict] = {}
        for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline", "create_time"]):
            try:
                info = proc.info
                name = str(info.get("name") or "").lower()
                if name not in _WATCHED:
                    continue
                rows[int(info["pid"])] = {
                    "pid": int(info["pid"]), "ppid": int(info.get("ppid") or 0),
                    "name": name, "command": " ".join(info.get("cmdline") or []),
                    "started_at": float(info.get("create_time") or 0),
                }
            except (psutil.Error, KeyError, TypeError):
                continue
        return rows

    def _owned(self, row: dict, all_processes: dict[int, dict]) -> bool:
        text = row["command"].lower()
        if self.campaign_id.lower() in text or any(root in text for root in self.roots):
            return True
        parent = row["ppid"]
        for _ in range(12):
            ancestor = all_processes.get(parent)
            if not ancestor:
                return False
            command = str(ancestor.get("command") or "").lower()
            if self.campaign_id.lower() in command or any(root in command for root in self.roots):
                return True
            parent = int(ancestor.get("ppid") or 0)
        return False

    def baseline(self) -> None:
        self._known = set(self._snapshot())
        self._append({"event": "baseline", "pids": sorted(self._known)})

    def _append(self, payload: dict) -> None:
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"at": datetime.now(timezone.utc).isoformat(), **payload}
        with self.evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def poll(self) -> None:
        import psutil
        watched = self._snapshot()
        all_processes = {
            int(proc.info["pid"]): {"ppid": proc.info.get("ppid"), "command": " ".join(proc.info.get("cmdline") or [])}
            for proc in psutil.process_iter(["pid", "ppid", "cmdline"])
            if proc.info.get("pid") is not None
        }
        for pid, row in watched.items():
            if pid in self._known:
                continue
            owned = self._owned(row, all_processes)
            self._append({"event": "process_created", "campaign_owned": owned, **row})
            self.incident = self.incident or owned
        self._known.update(watched)

    def start(self) -> None:
        self.baseline()
        def run() -> None:
            while not self._stop.wait(5):
                self.poll()
        self._thread = threading.Thread(target=run, name="campaign-process-monitor", daemon=True)
        self._thread.start()

    def close(self) -> bool:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=6)
        self.poll()
        return self.incident
