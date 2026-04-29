"""
Path-equivalence guard test.

These vectors represent the expected path mapping contract between the
translation engine's _get_output_path() and the verification script's
inline replica functions (_output_path_blog, _output_path_folder).

If the engine output-path logic or verification script changes, audit
both implementations and update this contract intentionally.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath

import pytest

# ---------------------------------------------------------------------------
# Import the verify script functions without package installation
# ---------------------------------------------------------------------------

_VERIFY_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_incremental_behavior.py"


def _load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_incremental", str(_VERIFY_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Contract vectors
# ---------------------------------------------------------------------------

# Folder layout: per_language_folders = true
# Engine replaces first /en/ path segment with /{lang}/
# Verify script replaces first "en" path component with lang
FOLDER_CASES = [
    # (content_root, source, lang, expected_output)
    (
        PurePosixPath("/content/site"),
        PurePosixPath("/content/site/en/page.md"),
        "de",
        PurePosixPath("/content/site/de/page.md"),
    ),
    (
        PurePosixPath("/content/site"),
        PurePosixPath("/content/site/en/sub/deep.md"),
        "ar",
        PurePosixPath("/content/site/ar/sub/deep.md"),
    ),
    (
        PurePosixPath("/content/site"),
        PurePosixPath("/content/site/en/enable/page.md"),
        "zh",
        PurePosixPath("/content/site/zh/enable/page.md"),
    ),
]

# Blog layout: per_language_folders = false, pattern = {filename}.{lang}{ext}
# Engine uses format string: source.parent / pattern.format(filename=stem, lang=lang, ext=suffix)
# Verify script uses: source.parent / f"{source.stem}.{lang}{source.suffix}"
BLOG_CASES = [
    # (source, lang, expected_output)
    (
        PurePosixPath("/content/blog/index.md"),
        "de",
        PurePosixPath("/content/blog/index.de.md"),
    ),
    (
        PurePosixPath("/content/blog/tutorial.md"),
        "ar",
        PurePosixPath("/content/blog/tutorial.ar.md"),
    ),
    (
        PurePosixPath("/content/blog/_index.md"),
        "zh",
        PurePosixPath("/content/blog/_index.zh.md"),
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFolderLayoutPathEquivalence:
    @pytest.fixture(autouse=True)
    def _load(self):
        mod = _load_verify_module()
        self.output_path_folder = mod._output_path_folder

    @pytest.mark.parametrize("content_root,source,lang,expected", FOLDER_CASES,
                             ids=["simple", "nested", "en_in_subfolder"])
    def test_folder_path_matches_contract(self, content_root, source, lang, expected):
        # The verify script uses pathlib Path (not PurePosixPath), so convert
        result = self.output_path_folder(Path(source), lang, Path(content_root))
        assert PurePosixPath(result) == expected


class TestBlogLayoutPathEquivalence:
    @pytest.fixture(autouse=True)
    def _load(self):
        mod = _load_verify_module()
        self.output_path_blog = mod._output_path_blog

    @pytest.mark.parametrize("source,lang,expected", BLOG_CASES,
                             ids=["index", "tutorial", "underscore_index"])
    def test_blog_path_matches_contract(self, source, lang, expected):
        result = self.output_path_blog(Path(source), lang)
        assert PurePosixPath(result) == expected
