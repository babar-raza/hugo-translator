"""Tests for tm_surgical_cleanup.py's Rule 4 (TC-HT-I18N-008): correcting
TM entries cached as an untranslated i18n-table passthrough."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "quality"))
sys.path.insert(0, str(REPO_ROOT))

import pytest
import yaml

from src.tm.l2_persistent import TranslationEntry
from src.translation_engine.terminology.classification import TemplateStringRegistry
from scripts.quality.tm_surgical_cleanup import is_corrupt_entry


@pytest.fixture
def registry(tmp_path):
    d = tmp_path / "template_strings"
    d.mkdir()
    (d / "_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "id": "heading.overview",
                        "en": "Overview",
                        "category": "section_heading",
                        "status": "approved",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (d / "ja.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "locale": "ja",
                "translations": {
                    "heading.overview": {"value": "概要", "reviewed_by": "agent:x"}
                },
            }
        ),
        encoding="utf-8",
    )
    return TemplateStringRegistry(d)


def _entry(source_text, translation, tgt_lang="ja"):
    return TranslationEntry(
        source_text=source_text,
        translation=translation,
        site_id="reference.aspose.org",
        src_lang="en",
        tgt_lang=tgt_lang,
    )


class TestRule4HeadingPassthrough:
    def test_untranslated_passthrough_flagged_for_correction(self, registry):
        entry = _entry("Overview", "Overview")  # passthrough: never translated
        corrupt, reason, action = is_corrupt_entry(entry, registry=registry)
        assert corrupt is True
        assert reason == "heading_untranslated_passthrough"
        assert action == "correct"

    def test_already_correct_translation_is_clean(self, registry):
        entry = _entry("Overview", "概要")  # already correct
        corrupt, _, _ = is_corrupt_entry(entry, registry=registry)
        assert corrupt is False

    def test_no_registry_entry_not_flagged_by_rule4(self, registry):
        # "Prerequisites" isn't in the (fixture) registry at all.
        entry = _entry("Prerequisites", "Prerequisites")
        corrupt, _, _ = is_corrupt_entry(entry, registry=registry)
        assert corrupt is False

    def test_no_registry_passed_preserves_prior_behavior(self):
        # Backward compatibility: existing callers that never pass a
        # registry (registry=None, the default) must see unchanged
        # behavior -- Rule 4 never fires.
        entry = _entry("Overview", "Overview")
        corrupt, _, _ = is_corrupt_entry(entry)
        assert corrupt is False

    def test_locale_without_a_translation_not_flagged(self, registry):
        entry = _entry("Overview", "Overview", tgt_lang="zh")  # no zh entry in fixture
        corrupt, _, _ = is_corrupt_entry(entry, registry=registry)
        assert corrupt is False
