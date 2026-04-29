"""
TC-14: Unit tests for _run_post_contamination_scan().

Verifies:
- Scans only the translated site's content_root (--repo flag)
- Does NOT use --profiles-dir
- Queues contaminated files from JSON output
- Returns silently on subprocess failure (never blocks worker)
- Returns early if content_root doesn't exist
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_worker():
    """Create a minimal worker-like object with the method under test."""
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
    )
    return AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)


def _make_config_service(enabled=True):
    cs = MagicMock()
    cs.get_config.return_value = {"auto_scan_contamination": enabled}
    return cs


# ---------------------------------------------------------------------------
# Happy path — contaminated files are queued
# ---------------------------------------------------------------------------

def test_scan_uses_repo_not_profiles_dir(tmp_path):
    """--repo <content_root> must be in the subprocess command."""
    worker = _make_worker()
    worker.config_service = _make_config_service()

    scan_data = {"files": [], "contaminated_count": 0}
    json_file = tmp_path / "scan_out.json"
    json_file.write_text(json.dumps(scan_data), encoding="utf-8")

    captured_cmd = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        # Simulate scan writing its output JSON (already exists via json_file above,
        # but NamedTemporaryFile uses a different path, so just write to the requested path)
        output_idx = cmd.index("--json-output") + 1
        Path(cmd[output_idx]).write_text(json.dumps(scan_data), encoding="utf-8")
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        return r

    with patch("subprocess.run", side_effect=fake_run), \
         patch("src.tm.retranslate_queue.add_to_queue") as _mock_q:
        worker._run_post_contamination_scan(site_id="blog.aspose.net", content_root=tmp_path)

    assert "--repo" in captured_cmd, "Must pass --repo to scan script"
    assert str(tmp_path) in captured_cmd, "Must pass content_root as --repo value"
    assert "--profiles-dir" not in captured_cmd, "Must NOT use --profiles-dir"
    _mock_q.assert_not_called()  # nothing contaminated


def test_scan_queues_contaminated_files(tmp_path):
    """Contaminated files found by scan are added to the retranslate queue."""
    worker = _make_worker()
    worker.config_service = _make_config_service()

    contaminated = [
        {"file_path": "/content/index.ar.md", "target_lang": "ar"},
        {"file_path": "/content/index.hi.md", "target_lang": "hi"},
    ]
    scan_data = {"files": contaminated, "contaminated_count": 2}

    def fake_run(cmd, **kwargs):
        output_idx = cmd.index("--json-output") + 1
        Path(cmd[output_idx]).write_text(json.dumps(scan_data), encoding="utf-8")
        r = MagicMock()
        r.returncode = 1  # exit 1 = issues found (normal)
        r.stderr = ""
        return r

    with patch("subprocess.run", side_effect=fake_run), \
         patch("src.tm.retranslate_queue.add_to_queue") as mock_add:
        worker._run_post_contamination_scan(site_id="docs", content_root=tmp_path)

    assert mock_add.call_count == 2
    call_paths = {call.args[1] for call in mock_add.call_args_list}
    assert "ar" in call_paths
    assert "hi" in call_paths


# ---------------------------------------------------------------------------
# Guard paths — method must never block the worker
# ---------------------------------------------------------------------------

def test_scan_disabled_by_config(tmp_path):
    worker = _make_worker()
    worker.config_service = _make_config_service(enabled=False)

    with patch("subprocess.run") as mock_run:
        worker._run_post_contamination_scan(site_id="blog.aspose.net", content_root=tmp_path)

    mock_run.assert_not_called()


def test_scan_missing_content_root(tmp_path):
    """Non-existent content_root → return immediately, no subprocess."""
    worker = _make_worker()
    worker.config_service = _make_config_service()
    non_existent = tmp_path / "does_not_exist"

    with patch("subprocess.run") as mock_run:
        worker._run_post_contamination_scan(site_id="blog.aspose.net", content_root=non_existent)

    mock_run.assert_not_called()


def test_scan_subprocess_exception_does_not_propagate(tmp_path):
    """Subprocess OSError must not propagate — worker must not crash."""
    worker = _make_worker()
    worker.config_service = _make_config_service()

    with patch("subprocess.run", side_effect=OSError("process failed")):
        # Must not raise
        worker._run_post_contamination_scan(site_id="blog.aspose.net", content_root=tmp_path)


def test_scan_timeout_does_not_propagate(tmp_path):
    """Subprocess timeout must not propagate."""
    import subprocess
    worker = _make_worker()
    worker.config_service = _make_config_service()

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=180)):
        worker._run_post_contamination_scan(site_id="blog.aspose.net", content_root=tmp_path)


def test_scan_invalid_json_does_not_propagate(tmp_path):
    """Corrupted JSON output must not propagate."""
    worker = _make_worker()
    worker.config_service = _make_config_service()

    def fake_run(cmd, **kwargs):
        output_idx = cmd.index("--json-output") + 1
        Path(cmd[output_idx]).write_text("NOT VALID JSON", encoding="utf-8")
        r = MagicMock()
        r.returncode = 1
        r.stderr = ""
        return r

    with patch("subprocess.run", side_effect=fake_run):
        worker._run_post_contamination_scan(site_id="blog.aspose.net", content_root=tmp_path)
