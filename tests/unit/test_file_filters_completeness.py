"""TC-M5: File filter language list completeness test.

Asserts that _ALL_LANGUAGE_CODES in file_filters.py covers every language
declared in site profiles. If a new language is added to a site profile but
not to the filter set, it would be silently excluded — this test prevents that.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest
import yaml


def _load_site_profile_langs():
    """Collect all target_langs from all site profiles."""
    project_root = Path(__file__).parent.parent.parent
    profile_dir = project_root / "config" / "site_profiles"
    langs = set()
    for profile_path in profile_dir.glob("*.yaml"):
        with open(profile_path) as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            tl = data.get("target_langs", [])
            if isinstance(tl, list):
                langs.update(str(lang) for lang in tl)
    return langs


class TestFileFilterCompleteness:
    def test_all_language_codes_covers_site_profiles(self):
        """Every target_lang in site profiles must be in _ALL_LANGUAGE_CODES."""
        from src.utils.file_filters import _ALL_LANGUAGE_CODES

        site_langs = _load_site_profile_langs()
        missing = site_langs - _ALL_LANGUAGE_CODES

        assert not missing, (
            f"These language codes appear in site profiles but are missing from "
            f"_ALL_LANGUAGE_CODES in file_filters.py: {sorted(missing)}\n"
            f"Add them to prevent silent per-language-folder output exclusion."
        )

    def test_no_empty_lang_codes(self):
        """No empty or None language codes in _ALL_LANGUAGE_CODES."""
        from src.utils.file_filters import _ALL_LANGUAGE_CODES

        assert all(isinstance(lang, str) and len(lang) >= 2 for lang in _ALL_LANGUAGE_CODES), (
            "All language codes must be non-empty strings of at least 2 characters"
        )
