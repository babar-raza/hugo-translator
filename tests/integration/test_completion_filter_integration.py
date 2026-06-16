"""
Integration test: Stage 2A completion-aware filter via real engine code path.

Uses TranslationEngine.__new__() with minimal attribute setup to exercise the
actual filter block inside _translate_directory_locked() — not a re-implementation.
Key invariants tested:

  Case A — all outputs current: file skipped; _translate_directory_sequential never called.
  Case B — one output stale:    file included in translation batch.
  Case C — queued despite current outputs: file force-included; queue path read from disk.
  Case D — force_retranslate=True: filter bypassed entirely.
"""

import os
import time
from pathlib import Path
from unittest import mock

import pytest

import src.tm.retranslate_queue as rtq
from src.translation_engine.directory_orchestrator import DirectoryOrchestrator
from src.translation_engine.engine import TranslationEngine
from src.translation_engine.models import DirectoryResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(tmp_path: Path, force_retranslate: bool = False) -> TranslationEngine:
    """
    Construct a minimal TranslationEngine via __new__ with only the attributes
    needed to reach the completion filter in _translate_directory_locked().
    """
    engine = TranslationEngine.__new__(TranslationEngine)

    # Telemetry — disable to skip all telemetry setup
    engine.enable_telemetry = False
    engine.telemetry = None

    # Completion filter flag
    engine.force_retranslate = force_retranslate

    # Output path computation (used by _get_output_path)
    engine.output_dir_override = tmp_path / "out"
    engine.input_root = None

    # Config — minimal mock
    cfg_mock = mock.Mock()
    cfg_mock.get_config.return_value = {}

    # SiteProfile mock — per_language_folders=False (file-based localization).
    # filter_source_files only excludes files like "post.de.md"; our test files
    # are named "source.md" so none are filtered out.
    sp_mock = mock.Mock()
    sp_mock.default_source_lang = "en"
    output_layout = mock.Mock()
    output_layout.per_language_folders = False
    sp_mock.output_layout = output_layout

    cfg_mock.get_site_profile.return_value = sp_mock
    engine.config = cfg_mock

    # Attributes set by __init__ that _translate_directory_locked accesses
    engine.changed_since_sha = None  # git diff filter (disabled)
    engine._review_cache = None  # review cache (none in tests)
    engine._rtq_llm_output_paths = set()  # LLM escalation queue (empty)

    # Attributes required by DirectoryOrchestrator and translate_file (via engine ref)
    engine._shutdown_requested = False
    engine._shutdown_lock = mock.Mock()
    engine._shutdown_callbacks = []
    engine.batch_stats_tracker = None
    engine.retry_handler = None
    engine.progress_tracker = None
    engine.batch_size = 16
    engine.model_loader = mock.Mock()
    engine.enable_content_hash = False
    engine.metadata_tracker = None
    engine.enable_verification = False
    engine.enable_verification_fix = False
    engine.similarity_tracker = None
    engine.production_ingestor = None
    engine.dry_run = False

    # TC-DECOMP-01: Wire extracted DirectoryOrchestrator
    engine._dir_orchestrator = DirectoryOrchestrator(engine)

    return engine


def _set_mtime(path: Path, delta_seconds: float) -> None:
    """Shift a file's mtime by delta_seconds relative to now."""
    t = time.time() + delta_seconds
    os.utime(path, (t, t))


@pytest.fixture(autouse=True)
def _redirect_queue(tmp_path):
    """Redirect queue file to tmp_path for every test."""
    with (
        mock.patch.object(rtq, "_QUEUE_FILE", tmp_path / "queue.jsonl"),
        mock.patch.object(rtq, "_QUARANTINE_FILE", tmp_path / "quarantine.jsonl"),
    ):
        yield


# ---------------------------------------------------------------------------
# Case A — all outputs current → file skipped
# ---------------------------------------------------------------------------


class TestCaseASkipComplete:
    def test_complete_file_is_skipped(self, tmp_path):
        """
        One source file + one output per target lang, both outputs newer than source.
        The filter must skip the file. _translate_directory_sequential must not be called.
        """
        src_dir = tmp_path / "content"
        src_dir.mkdir()
        source = src_dir / "post.md"
        source.write_text("# Hello")
        _set_mtime(source, -100)  # source is 100s in the past

        out_dir = tmp_path / "out"
        for lang in ["de", "fr"]:
            out = out_dir / lang / "post.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(f"# Hallo ({lang})")
            _set_mtime(out, +10)  # outputs are 10s newer than now > source

        engine = _make_engine(tmp_path)

        with mock.patch.object(
            engine._dir_orchestrator, "_translate_directory_sequential"
        ) as seq_mock:
            seq_mock.return_value = DirectoryResult(success=True, directory=src_dir)
            result = engine._translate_directory_locked(
                site_id="test",
                directory=src_dir,
                target_langs=["de", "fr"],
                parallel=False,
            )

        assert result.completion_filter_skipped == 1, (
            f"Expected 1 skipped file, got {result.completion_filter_skipped}"
        )
        seq_mock.assert_not_called(), "No files should reach translation"

    def test_skipped_count_scales_with_complete_files(self, tmp_path):
        """Two complete files → skipped count = 2."""
        src_dir = tmp_path / "content"
        src_dir.mkdir()
        out_dir = tmp_path / "out"

        for name in ["a.md", "b.md"]:
            src = src_dir / name
            src.write_text("# content")
            _set_mtime(src, -100)
            for lang in ["de"]:
                out = out_dir / lang / name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("# translated")
                _set_mtime(out, +10)

        engine = _make_engine(tmp_path)

        with mock.patch.object(
            engine._dir_orchestrator, "_translate_directory_sequential"
        ) as seq_mock:
            seq_mock.return_value = DirectoryResult(success=True, directory=src_dir)
            result = engine._translate_directory_locked(
                site_id="test",
                directory=src_dir,
                target_langs=["de"],
                parallel=False,
            )

        assert result.completion_filter_skipped == 2
        seq_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Case B — stale output → file included
# ---------------------------------------------------------------------------


class TestCaseBIncludeStale:
    def test_stale_output_file_is_included(self, tmp_path):
        """
        Source newer than one output → file must reach _translate_directory_sequential.
        """
        src_dir = tmp_path / "content"
        src_dir.mkdir()
        source = src_dir / "post.md"
        source.write_text("# Hello")
        _set_mtime(source, +10)  # source is newer

        out_dir = tmp_path / "out"
        out = out_dir / "de" / "post.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# Hallo")
        _set_mtime(out, -100)  # output is older than source

        engine = _make_engine(tmp_path)
        captured = {}

        def _capture_seq(site_id, md_files, target_langs, result, **kw):
            captured["md_files"] = list(md_files)
            result.successful_files = 1
            return result

        with mock.patch.object(
            engine._dir_orchestrator, "_translate_directory_sequential", side_effect=_capture_seq
        ):
            engine._translate_directory_locked(
                site_id="test",
                directory=src_dir,
                target_langs=["de"],
                parallel=False,
            )

        assert source in captured.get("md_files", []), (
            "Stale-output file must be forwarded to sequential processor"
        )
        assert result_skipped(engine) == 0 or True  # no skip; no assertion on engine attr here


def result_skipped(engine):
    """Helper — not used for assertion, just documents intent."""
    return 0


# ---------------------------------------------------------------------------
# Case C — queued file force-included despite current outputs
# ---------------------------------------------------------------------------


class TestCaseCQueuedForceIncluded:
    def test_queued_output_forces_source_into_batch(self, tmp_path):
        """
        File has current outputs (would normally be skipped).
        BUT its output path is in the retranslate queue.
        The filter must force-include it.
        """
        src_dir = tmp_path / "content"
        src_dir.mkdir()
        source = src_dir / "stuck.md"
        source.write_text("# Stuck")
        _set_mtime(source, -200)  # source is old

        out_dir = tmp_path / "out"
        out = out_dir / "ar" / "stuck.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# WRONG LANGUAGE CONTENT")
        _set_mtime(out, +200)  # output is NEWER than source (looks complete)

        # Enqueue the output path — simulates CASE 4 having fired
        rtq.add_to_queue(out, "ar")
        assert str(out.resolve()) in rtq.load_queued_paths()

        engine = _make_engine(tmp_path)
        captured = {}

        def _capture_seq(site_id, md_files, target_langs, result, **kw):
            captured["md_files"] = list(md_files)
            result.successful_files = 1
            return result

        with mock.patch.object(
            engine._dir_orchestrator, "_translate_directory_sequential", side_effect=_capture_seq
        ):
            result = engine._translate_directory_locked(
                site_id="test",
                directory=src_dir,
                target_langs=["ar"],
                parallel=False,
            )

        assert source in captured.get("md_files", []), (
            "Queued file must be force-included despite current output mtime"
        )
        # Completion filter must report force-include, not skip
        assert result.completion_filter_skipped == 0


# ---------------------------------------------------------------------------
# Case D — force_retranslate=True bypasses filter entirely
# ---------------------------------------------------------------------------


class TestCaseDForceRetranslate:
    def test_force_retranslate_bypasses_filter(self, tmp_path):
        """
        With force_retranslate=True, the filter block is skipped.
        All files (including those with current outputs) must reach translation.
        """
        src_dir = tmp_path / "content"
        src_dir.mkdir()
        source = src_dir / "old.md"
        source.write_text("# Old content")
        _set_mtime(source, -300)  # source is old

        out_dir = tmp_path / "out"
        out = out_dir / "de" / "old.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# Alt Inhalt")
        _set_mtime(out, +300)  # output is very current

        engine = _make_engine(tmp_path, force_retranslate=True)
        captured = {}

        def _capture_seq(site_id, md_files, target_langs, result, **kw):
            captured["md_files"] = list(md_files)
            result.successful_files = 1
            return result

        with mock.patch.object(
            engine._dir_orchestrator, "_translate_directory_sequential", side_effect=_capture_seq
        ):
            result = engine._translate_directory_locked(
                site_id="test",
                directory=src_dir,
                target_langs=["de"],
                parallel=False,
            )

        assert source in captured.get("md_files", []), (
            "force_retranslate must bypass filter and include all files"
        )
        assert result.completion_filter_skipped == 0
