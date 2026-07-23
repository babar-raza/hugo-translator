"""
Regression guard: TranslationEngine._get_output_path() and
SweepScheduler._get_target_path() must agree, since both now delegate to the
same shared src/utils/content_discovery.resolve_translated_path(). Before
this fix, scheduler.py had its own, independently broken implementation
(a no-op `else: pass` for per_language_folders=False, and a separate
content_roots-relative-path bug for per_language_folders=True with nested
paths) -- this test exists so a future edit that re-diverges the two is
caught immediately rather than silently drifting again.
"""
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from src.orchestrator.scheduler import SweepScheduler
from src.translation_engine.engine import TranslationEngine
from src.utils.models import BodyRules, OutputLayout, SiteProfile


def make_profile(per_language_folders: bool, pattern: str, target_langs=None) -> SiteProfile:
    return SiteProfile(
        site_id="consistency.test",
        content_roots=["/content/consistency.test"],
        default_source_lang="en",
        target_langs=target_langs or ["fr", "es", "ja"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(per_language_folders=per_language_folders, pattern=pattern),
    )


PROFILE_MATRIX = [
    make_profile(True, "{lang}/{path}"),
    make_profile(False, "{filename}.{lang}{ext}"),
    make_profile(False, "{path_stem}.{lang}.md"),
]

PATH_MATRIX = [
    Path("/content/consistency.test/en/guide.md"),
    Path("/content/consistency.test/en/cells/net/_index.md"),
    Path("/content/consistency.test/cells/net/slug/index.md"),
    Path("/content/consistency.test/archive.md"),
]

LANGS = ["fr", "es", "ja"]


def _engine_output_path(profile: SiteProfile, source_path: Path, target_lang: str) -> Path:
    engine = TranslationEngine(
        config_service=MagicMock(), tm=MagicMock(), model_loader=MagicMock()
    )
    return engine._get_output_path(source_path, target_lang, profile)


def _scheduler_target_path(profile: SiteProfile, source_path: Path, target_lang: str) -> Path:
    config_service = Mock()
    config_service.list_sites.return_value = [profile.site_id]
    config_service.get_site_profile.return_value = profile
    scheduler = SweepScheduler(
        config_service=config_service, job_enqueue_callback=Mock()
    )
    return scheduler._get_target_path(source_path, target_lang, profile)


@pytest.mark.parametrize("profile", PROFILE_MATRIX)
@pytest.mark.parametrize("source_path", PATH_MATRIX)
@pytest.mark.parametrize("target_lang", LANGS)
def test_engine_and_scheduler_agree(profile, source_path, target_lang):
    engine_result = _engine_output_path(profile, source_path, target_lang)
    scheduler_result = _scheduler_target_path(profile, source_path, target_lang)
    assert engine_result == scheduler_result, (
        f"engine/scheduler disagree for profile(per_language_folders="
        f"{profile.output_layout.per_language_folders}, pattern="
        f"{profile.output_layout.pattern!r}), source={source_path}, "
        f"lang={target_lang}: engine={engine_result} scheduler={scheduler_result}"
    )
