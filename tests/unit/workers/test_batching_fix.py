"""
Verify the chunked commit batching fix (files_per_commit + per-site deadline).

Scenarios:
  A) files_per_commit=20, 45 files  -> 3 chunks (20+20+5)
  B) files_per_commit=0 (legacy)    -> single pass, 1 commit
  C) deadline fires after chunk 0   -> stops after 1 chunk
  D) config values load from global.yaml
  E) per-site limit overrides global --max-seconds-per-run
"""
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Stub heavy ML deps so the import is fast (same pattern as test_content_worker_vram.py)
def _ensure_stubs():
    for mod in ("ctranslate2", "transformers", "sentence_transformers", "faiss", "lmdb", "pytz"):
        sys.modules.setdefault(mod, types.ModuleType(mod))
    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        cuda_stub = types.ModuleType("torch.cuda")
        cuda_stub.is_available = MagicMock(return_value=True)
        cuda_stub.empty_cache = MagicMock()
        torch_stub.cuda = cuda_stub
        sys.modules["torch"] = torch_stub
        sys.modules["torch.cuda"] = cuda_stub


_ensure_stubs()


def _make_dir_result(total_files, successful_files=None, translated_segments=None):
    r = MagicMock()
    r.total_files = total_files
    r.successful_files = successful_files if successful_files is not None else total_files
    r.failed_files = total_files - r.successful_files
    r.file_results = []
    if translated_segments is not None:
        r.aggregate_stats.translated_segments = translated_segments
    return r


def _make_worker(files_per_commit, max_seconds_per_run=None):
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
        AutonomousWorkerConfig,
    )
    cfg = AutonomousWorkerConfig(max_seconds_per_run=max_seconds_per_run)
    worker = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
    worker.config = cfg
    worker._run_start = None
    worker.invocation_id = "test-uuid"

    cs = MagicMock()
    cs.resolve_content_root.side_effect = lambda p: Path(p)
    cs.get_config.return_value = {
        "git_commit": {"files_per_commit": files_per_commit},
        "autonomous_content_translation": {"execution": {"per_site_limits": {}}},
    }
    sp = MagicMock()
    sp.max_seconds_per_run = None
    cs.get_site_profile.return_value = sp
    worker.config_service = cs
    worker.translation_engine = MagicMock()
    return worker


def _run(worker, batch_idx=1):
    worker._run_new_files = {}
    worker._run_skipped = {}
    worker._run_failed = {}
    worker._translate_content_root("test.site", "/fake/dir", ["fr", "de"], batch_idx=batch_idx)


@pytest.fixture(autouse=True)
def _patch_path_exists():
    with patch.object(Path, "exists", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _patch_timeout_guard():
    with patch("src.workers.autonomous_content_translation_worker.timeout_guard") as mock_tg:
        mock_tg.return_value.__enter__ = lambda s: s
        mock_tg.return_value.__exit__ = MagicMock(return_value=False)
        yield


# ── A ──────────────────────────────────────────────────────────────────────
def test_chunked_45_files_produces_3_commits():
    """45 files with chunk size 20 → 3 translate calls and 3 commits."""
    worker = _make_worker(files_per_commit=20)
    worker.translation_engine.translate_directory.side_effect = [
        _make_dir_result(20),
        _make_dir_result(20),
        _make_dir_result(5),
    ]

    with patch("src.workers.autonomous_content_translation_worker.auto_commit_translations",
               return_value=True) as mock_commit:
        _run(worker, batch_idx=1)

    assert worker.translation_engine.translate_directory.call_count == 3
    assert mock_commit.call_count == 3

    # max_files=20 in every call
    for c in worker.translation_engine.translate_directory.call_args_list:
        assert c.kwargs["max_files"] == 20

    # run_id includes chunk suffix
    run_ids = [c.kwargs["run_id"] for c in mock_commit.call_args_list]
    assert run_ids == [
        "test-uuid:test.site:batch-1-chunk-0",
        "test-uuid:test.site:batch-1-chunk-1",
        "test-uuid:test.site:batch-1-chunk-2",
    ]


# ── B ──────────────────────────────────────────────────────────────────────
def test_legacy_single_pass_unchanged():
    """files_per_commit=0 keeps original behavior: 1 translate call, 1 commit, no chunk suffix."""
    worker_b = _make_worker(files_per_commit=0)
    worker_b.translation_engine.translate_directory.return_value = _make_dir_result(100)

    with patch("src.workers.autonomous_content_translation_worker.auto_commit_translations",
               return_value=True) as mock_commit_b:
        _run(worker_b, batch_idx=2)

    assert worker_b.translation_engine.translate_directory.call_count == 1
    assert mock_commit_b.call_count == 1
    run_id = mock_commit_b.call_args.kwargs["run_id"]
    assert "chunk" not in run_id
    assert worker_b.translation_engine.translate_directory.call_args.kwargs["max_files"] == 0


# ── C: deadline fires on 2nd chunk pre-check ─────────────────────────────
def test_deadline_stops_loop_between_chunks():
    """Deadline fires on the 2nd iteration's pre-check → only 1 chunk processed.

    run_deadline = _run_start + max_seconds - 300 = 0 + 1000 - 300 = 700.
    We mock time.time() so calls 1–2 return 600 (< 700 = before deadline) and
    call 3+ returns 800 (>= 700 = deadline expired).
      call 1: remaining = deadline - time.time()  → positive, proceed
      call 2: 1st chunk pre-check                 → before deadline, proceed
      call 3: 2nd chunk pre-check                 → past deadline, return
    """
    import src.workers.autonomous_content_translation_worker as wmod

    T = 0.0
    worker_c = _make_worker(files_per_commit=20, max_seconds_per_run=1000)
    worker_c._run_start = T  # deadline = T + 700

    n = [0]
    def _fake_time():
        n[0] += 1
        return T + 600 if n[0] < 3 else T + 800  # calls 1-2 before deadline, call 3+ after

    # Guard: if the loop somehow runs a 2nd translate call, raise to fail fast
    worker_c.translation_engine.translate_directory.side_effect = [
        _make_dir_result(20),
        RuntimeError("translate_directory called 2nd time — deadline check did not fire"),
    ]

    with patch.object(wmod.time, "time", side_effect=_fake_time), \
         patch("src.workers.autonomous_content_translation_worker.auto_commit_translations",
               return_value=True) as mock_commit_c:
        _run(worker_c, batch_idx=3)

    assert worker_c.translation_engine.translate_directory.call_count == 1
    assert mock_commit_c.call_count == 1


# ── D ──────────────────────────────────────────────────────────────────────
def test_production_config_values():
    """global.yaml has the expected files_per_commit."""
    from src.utils.config_loader import ConfigService
    cs = ConfigService("config/")
    raw = cs.get_config()

    fpc = raw.get("git_commit", {}).get("files_per_commit")
    assert fpc == 25, f"Expected files_per_commit=25, got {fpc}"

    # per_site_limits key exists (may be empty after reference.aspose.net pilot removal)
    assert isinstance(
        raw.get("autonomous_content_translation", {})
        .get("execution", {})
        .get("per_site_limits", {}),
        dict,
    )


# ── E: per-site limit is applied when available ────────────────────────────
def test_per_site_limit_overrides_global():
    """Worker picks up per_site_limits from config rather than global max_seconds_per_run."""
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
        AutonomousWorkerConfig,
    )
    cfg = AutonomousWorkerConfig(max_seconds_per_run=3600)  # global = 1h
    worker = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
    worker.config = cfg
    worker._run_start = time.time()
    worker.invocation_id = "test-uuid"

    cs = MagicMock()
    cs.resolve_content_root.side_effect = lambda p: Path(p)
    cs.get_config.return_value = {
        "git_commit": {"files_per_commit": 0},
        "autonomous_content_translation": {
            "execution": {
                "per_site_limits": {
                    "reference.aspose.net": {"max_seconds_per_run": 28800}  # 8h override
                }
            }
        },
    }
    sp = MagicMock()
    sp.max_seconds_per_run = None
    cs.get_site_profile.return_value = sp
    worker.config_service = cs
    worker.translation_engine = MagicMock()
    worker.translation_engine.translate_directory.return_value = _make_dir_result(5)

    captured_deadline = []

    def capture_translate(**kwargs):
        captured_deadline.append(kwargs.get("run_deadline"))
        return _make_dir_result(5)

    worker.translation_engine.translate_directory.side_effect = capture_translate

    with patch("src.workers.autonomous_content_translation_worker.auto_commit_translations",
               return_value=True):
        # Use "reference.aspose.net" to match the per_site_limits key
        worker._run_new_files = {}
        worker._run_skipped = {}
        worker._run_failed = {}
        worker._translate_content_root(
            "reference.aspose.net", "/fake/dir", ["fr", "de"], batch_idx=1
        )

    # The deadline should be based on 28800s (8h), not 3600s (1h)
    assert captured_deadline, "translate_directory was not called"
    deadline = captured_deadline[0]
    assert deadline is not None
    # Expected deadline ≈ run_start + 28800 - 300 = run_start + 28500
    # Global deadline would be run_start + 3600 - 300 = run_start + 3300
    elapsed_to_deadline = deadline - worker._run_start
    assert elapsed_to_deadline > 20000, (
        f"Deadline should reflect 8h override, got {elapsed_to_deadline:.0f}s from run_start"
    )


# ── F: all-done chunk advances offset then terminates on empty next chunk ──────
def test_all_skipped_chunk_advances_offset_and_terminates():
    """An all-done chunk (translated_segments==0) must advance chunk_offset so the
    next call asks for a different slice.  When that next call returns total_files==0
    (no more source files past the offset), the loop terminates cleanly.

    This replaces the old no-progress guard (removed when skip_first was added):
    the loop now terminates via total_files==0 / total_files<chunk_size, not by
    detecting zero translation work.
    """
    worker = _make_worker(files_per_commit=20)
    worker.translation_engine.translate_directory.side_effect = [
        _make_dir_result(20, translated_segments=0),  # chunk 0: all done, advance offset
        _make_dir_result(0),                          # chunk 1: no files at offset 20 → break
    ]

    with patch("src.workers.autonomous_content_translation_worker.auto_commit_translations",
               return_value=True) as mock_commit:
        _run(worker, batch_idx=1)

    # Two translate calls: chunk 0 (advance) and chunk 1 (empty → break)
    assert worker.translation_engine.translate_directory.call_count == 2
    # Only chunk 0 triggers a commit (chunk 1 has 0 files → successful_files=0)
    assert mock_commit.call_count == 1
    # Verify skip_first advanced correctly
    calls = worker.translation_engine.translate_directory.call_args_list
    assert calls[0].kwargs["skip_first"] == 0
    assert calls[1].kwargs["skip_first"] == 20


# ── G: skip_first offset advances by total_files each chunk ────────────────────
def test_offset_advances_across_chunks():
    """skip_first must increase by result.total_files on every iteration so each
    chunk selects a different slice of source files."""
    worker = _make_worker(files_per_commit=20)
    worker.translation_engine.translate_directory.side_effect = [
        _make_dir_result(20, translated_segments=5),  # chunk 0: 5 new translations
        _make_dir_result(20, translated_segments=3),  # chunk 1: 3 new translations
        _make_dir_result(7,  translated_segments=0),  # chunk 2: final partial → break
    ]

    with patch("src.workers.autonomous_content_translation_worker.auto_commit_translations",
               return_value=True):
        _run(worker, batch_idx=1)

    calls = worker.translation_engine.translate_directory.call_args_list
    assert len(calls) == 3
    assert calls[0].kwargs["skip_first"] == 0
    assert calls[1].kwargs["skip_first"] == 20
    assert calls[2].kwargs["skip_first"] == 40


# ── H: BUG-2 fix — _run_new_files accumulates successful_files after translation ──
def test_run_new_files_populated_after_chunked_translation():
    """BUG-2 fix: _run_new_files[site_id] must equal sum of successful_files
    across all chunks after _translate_content_root completes (chunked mode).

    Pre-fix: _run_new_files was never written → always {} → sum()=0 →
    last_success_ts was never advanced → health monitoring showed 'never succeeded'.
    """
    worker = _make_worker(files_per_commit=20)
    worker.translation_engine.translate_directory.side_effect = [
        _make_dir_result(total_files=20, successful_files=18),  # chunk 0: 18 ok, 2 failed
        _make_dir_result(total_files=5,  successful_files=5),   # chunk 1: final, all ok
    ]

    with patch("src.workers.autonomous_content_translation_worker.auto_commit_translations",
               return_value=True):
        _run(worker, batch_idx=1)

    # BUG-2 FIX: site key must exist and hold the correct total
    assert "test.site" in worker._run_new_files, "_run_new_files must be keyed by site_id"
    assert worker._run_new_files["test.site"] == 23, (
        f"Expected 18+5=23 successful files, got {worker._run_new_files.get('test.site')}"
    )
    # Ensure _run_total_new would be > 0 (so last_success_ts gets written)
    assert sum(worker._run_new_files.values()) > 0


def test_run_new_files_populated_after_legacy_translation():
    """BUG-2 fix: _run_new_files[site_id] must be set in legacy (single-pass) mode."""
    worker = _make_worker(files_per_commit=0)
    worker.translation_engine.translate_directory.return_value = _make_dir_result(
        total_files=50, successful_files=47
    )

    with patch("src.workers.autonomous_content_translation_worker.auto_commit_translations",
               return_value=True):
        _run(worker, batch_idx=1)

    assert "test.site" in worker._run_new_files
    assert worker._run_new_files["test.site"] == 47


def test_translate_directory_accepts_skip_first():
    """Verify engine signature accepts skip_first (chunked commit contract)."""
    import inspect

    from src.translation_engine.engine import TranslationEngine
    sig = inspect.signature(TranslationEngine.translate_directory)
    assert "skip_first" in sig.parameters, (
        "translate_directory must accept skip_first for chunked commit mode"
    )


def test_execute_translation_run_initializes_run_start_and_run_new_files():
    """BUG-2 fix: _execute_translation_run() must initialize _run_new_files={}
    and _run_start=float so deadline enforcement and health tracking work correctly.
    """
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
        AutonomousWorkerConfig,
    )
    cfg = AutonomousWorkerConfig()
    worker = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
    worker.config = cfg
    worker.invocation_id = "test-init-uuid"

    cs = MagicMock()
    cs.list_sites.return_value = []  # no sites → _execute_translation_run returns immediately
    worker.config_service = cs
    worker.translation_engine = MagicMock()

    # Before the call, attributes don't exist
    assert not hasattr(worker, "_run_new_files") or worker._run_new_files != {}
    assert not hasattr(worker, "_run_start")

    worker._execute_translation_run()

    # After the call, both must be set
    assert hasattr(worker, "_run_new_files"), "_run_new_files must be initialized"
    assert worker._run_new_files == {}, "No sites processed → still empty dict"
    assert hasattr(worker, "_run_start"), "_run_start must be initialized"
    assert isinstance(worker._run_start, float), "_run_start must be a float timestamp"
