"""TC-PORT-LLM-012: gate5 worker children must be isolated from control events
sent to the controller's own console.

Every prior mitigation (shared console, DETACHED_PROCESS, a separate minimized
console) still let the forrtl-200 window-CLOSE abort recur, because none of
them addressed the real gap: SetConsoleCtrlHandler(NULL, TRUE), installed by
start_portfolio_missing_sweep_autonomous.ps1, only suppresses CTRL_C_EVENT/
CTRL_BREAK_EVENT -- never CTRL_CLOSE_EVENT/CTRL_LOGOFF_EVENT/
CTRL_SHUTDOWN_EVENT. The real fix is a handler installed in the worker process
itself (run_gate5_batch.py, see test_run_gate5_batch_console_handler.py);
CREATE_NEW_PROCESS_GROUP here is defense in depth, asserted directly so a
future edit can't silently drop it back to 0.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

from scripts.campaign import launch_parallel_campaign_shards as launcher
from scripts.campaign.launch_parallel_campaign_shards import GPU_PRIMARY_LOCALES
from src.workers.campaign_manifest import CampaignManifest

LOCALES = ["de", "es"]


def _manifest(tmp_path: Path) -> CampaignManifest:
    payload = {
        "schema_version": 1,
        "campaign_id": "lifecycle-launcher",
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
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return CampaignManifest.load(path)


def _args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        campaign_manifest=tmp_path / "manifest.yaml",
        ledger_root=tmp_path / "campaigns",
        device="cuda",
        max_gpu_memory_percent=50,
        gpu_shard_memory_percent=50,
        progress_interval_seconds=30,
        tm_intent_spool_path=None,
        no_force_serialize=False,
        recovery_qualification=False,
        child="gate5",
    )


class _RecordingChild:
    """Stand-in for run_gate5_batch.py that records how it was spawned."""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        type(self).calls.append(kwargs)
        self._stdout = kwargs["stdout"]

    def wait(self):
        return 0

    def poll(self):
        return 0


def test_workers_get_their_own_process_group_on_windows(tmp_path, monkeypatch):
    _RecordingChild.calls = []
    manifest = _manifest(tmp_path)
    shards = list(manifest.shards(resume_receipts=set(), max_outputs=250))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.subprocess, "Popen", _RecordingChild)

    launcher._run_wave(
        groups=[shards],
        manifest=manifest,
        args=_args(tmp_path),
        gpu_locales=GPU_PRIMARY_LOCALES,
        translator_repo=tmp_path,
        config_root=tmp_path / "config",
    )

    assert _RecordingChild.calls, "no child was launched"
    flags = _RecordingChild.calls[0]["creationflags"]
    if sys.platform == "win32":
        assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
        # Explicitly not detached and not console-less: both were tried
        # historically and both still produced the forrtl-200 abort.
        assert not (flags & getattr(subprocess, "DETACHED_PROCESS", 0))
        assert not (flags & getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        assert flags == 0
