"""
job_processor.process_job() must re-validate a job's (potentially stale)
target_langs snapshot against the live site profile before executing it.

A TranslationJob enqueued before a locale was retired from a site's active
profile carries a frozen target_langs list from creation time. Without
re-validation, draining that job later would resurrect the retired locale
even though every other enforcement layer (SiteProfile validator, CLI,
engine) now rejects it. bg is used as the negative-control retired locale
throughout the Aspose.org locale-policy test suite.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.orchestrator.models import JobType, TranslationJob
from src.workers.job_processor import JobProcessor


def _make_processor(site_profile_target_langs: list[str]) -> JobProcessor:
    processor = JobProcessor.__new__(JobProcessor)
    processor.config_service = MagicMock()
    processor.config_service.get_site_profile.return_value = SimpleNamespace(
        target_langs=site_profile_target_langs
    )
    processor.engine = MagicMock()
    processor.engine.translate_file.return_value = {"status": "success"}
    processor.queue = MagicMock()
    processor.jobs_processed = 0
    processor.jobs_succeeded = 0
    processor.jobs_failed = 0
    return processor


def test_stale_retired_locale_dropped_before_translate_file_is_called():
    # Job snapshot frozen back when the site's profile still had 36 locales.
    stale_job = TranslationJob(
        job_id="job-1",
        job_type=JobType.FILE,
        site_id="docs.aspose.org",
        target_langs=["de", "fr", "bg", "hr"],  # bg, hr since retired
        input_paths=[Path("fake.md")],
    )
    live_target_langs = ["de", "fr", "es"]  # current, already-trimmed profile
    processor = _make_processor(live_target_langs)

    processor.process_job(stale_job)

    assert processor.engine.translate_file.called
    call_kwargs = processor.engine.translate_file.call_args.kwargs
    assert call_kwargs["target_langs"] == ["de", "fr"]
    assert "bg" not in call_kwargs["target_langs"]
    assert "hr" not in call_kwargs["target_langs"]


def test_all_stale_langs_still_live_passes_through_unchanged():
    stale_job = TranslationJob(
        job_id="job-2",
        job_type=JobType.FILE,
        site_id="docs.aspose.org",
        target_langs=["de", "fr"],
        input_paths=[Path("fake.md")],
    )
    processor = _make_processor(["de", "fr", "es"])

    processor.process_job(stale_job)

    call_kwargs = processor.engine.translate_file.call_args.kwargs
    assert call_kwargs["target_langs"] == ["de", "fr"]
