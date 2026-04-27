"""
TC-16: Unit tests for _write_run_metrics().

Verifies:
- Writes JSON to data/metrics/ when enabled
- JSON contains required keys: run_id, site_id, timestamp, files_translated,
  tm_hit_rates, retranslate_queue_size, validation_failures
- timestamp uses UTC ISO format (no deprecation warning)
- Does not raise on failure (non-fatal)
- Respects metrics.enabled=false gate
"""
import json
import warnings
from datetime import timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_worker():
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
    )
    w = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
    w._run_new_files = {"blog.aspose.net": 5}
    return w


def _make_config_service(enabled=True, output_dir=None):
    cs = MagicMock()
    cfg = {"metrics": {"enabled": enabled, "write_per_run_summary": True}}
    if output_dir:
        cfg["metrics"]["output_dir"] = output_dir
    cs.get_config.return_value = cfg
    return cs


def _fake_stats_summary():
    return {
        "translations": {"total": 10, "success": 8, "failed": 2},
        "tm": {"lookups": 20, "l1_hits": 5, "l2_hits": 3, "l3_hits": 2, "misses": 10, "hit_rate": 0.5},
        "performance": {},
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_write_run_metrics_creates_json(tmp_path):
    """File is written and contains all required keys."""
    worker = _make_worker()
    worker.config_service = _make_config_service(output_dir=str(tmp_path))

    mock_mc = MagicMock()
    mock_mc.get_stats_summary.return_value = _fake_stats_summary()

    with patch("src.observability.metrics.get_metrics", return_value=mock_mc), \
         patch("src.tm.retranslate_queue.load_queued_paths", return_value={"a", "b"}):
        worker._write_run_metrics(site_id="blog.aspose.net", run_id="run-123")

    files = list(tmp_path.glob("run_*.json"))
    assert len(files) == 1, f"Expected one JSON file, got {len(files)}"

    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["run_id"] == "run-123"
    assert data["site_id"] == "blog.aspose.net"
    assert "timestamp" in data
    assert data["files_translated"] == 5
    assert data["retranslate_queue_size"] == 2
    assert "tm_hit_rates" in data
    assert "validation_failures" in data


def test_write_run_metrics_no_deprecated_datetime_warning(tmp_path):
    """datetime.utcnow() must not be used — no DeprecationWarning."""
    worker = _make_worker()
    worker.config_service = _make_config_service(output_dir=str(tmp_path))

    mock_mc = MagicMock()
    mock_mc.get_stats_summary.return_value = _fake_stats_summary()

    with warnings.catch_warnings(record=True) as caught, \
         patch("src.observability.metrics.get_metrics", return_value=mock_mc), \
         patch("src.tm.retranslate_queue.load_queued_paths", return_value=set()):
        warnings.simplefilter("always")
        worker._write_run_metrics(site_id="blog.aspose.net", run_id="run-456")

    deprecation_msgs = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    utcnow_warnings = [m for m in deprecation_msgs if "utcnow" in m.lower()]
    assert not utcnow_warnings, f"datetime.utcnow() DeprecationWarning found: {utcnow_warnings}"


def test_write_run_metrics_timestamp_is_utc_aware(tmp_path):
    """Timestamp string should be parseable as UTC ISO 8601."""
    from datetime import datetime
    worker = _make_worker()
    worker.config_service = _make_config_service(output_dir=str(tmp_path))

    mock_mc = MagicMock()
    mock_mc.get_stats_summary.return_value = _fake_stats_summary()

    with patch("src.observability.metrics.get_metrics", return_value=mock_mc), \
         patch("src.tm.retranslate_queue.load_queued_paths", return_value=set()):
        worker._write_run_metrics(site_id="blog.aspose.net", run_id="run-789")

    files = list(tmp_path.glob("run_*.json"))
    data = json.loads(files[0].read_text(encoding="utf-8"))
    ts = data["timestamp"]
    # Must be parseable and have timezone info
    dt = datetime.fromisoformat(ts)
    assert dt.tzinfo is not None, "Timestamp must be timezone-aware"


# ---------------------------------------------------------------------------
# Gate: disabled
# ---------------------------------------------------------------------------

def test_write_run_metrics_disabled_by_config(tmp_path):
    worker = _make_worker()
    worker.config_service = _make_config_service(enabled=False, output_dir=str(tmp_path))

    with patch("src.observability.metrics.get_metrics") as mock_get:
        worker._write_run_metrics(site_id="blog.aspose.net", run_id="run-x")

    mock_get.assert_not_called()
    assert list(tmp_path.glob("*.json")) == []


# ---------------------------------------------------------------------------
# Failure modes — must never raise
# ---------------------------------------------------------------------------

def test_write_run_metrics_exception_does_not_propagate(tmp_path):
    """Exception in MetricsCollector must not crash the worker."""
    worker = _make_worker()
    worker.config_service = _make_config_service(output_dir=str(tmp_path))

    with patch("src.observability.metrics.get_metrics", side_effect=RuntimeError("metrics down")):
        # Must not raise
        worker._write_run_metrics(site_id="blog.aspose.net", run_id="run-err")


def test_write_run_metrics_queue_error_still_writes(tmp_path):
    """retranslate_queue error is handled; file is still written with -1 queue size."""
    worker = _make_worker()
    worker.config_service = _make_config_service(output_dir=str(tmp_path))

    mock_mc = MagicMock()
    mock_mc.get_stats_summary.return_value = _fake_stats_summary()

    with patch("src.observability.metrics.get_metrics", return_value=mock_mc), \
         patch("src.tm.retranslate_queue.load_queued_paths", side_effect=OSError("disk error")):
        worker._write_run_metrics(site_id="blog.aspose.net", run_id="run-qerr")

    files = list(tmp_path.glob("run_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["retranslate_queue_size"] == -1
