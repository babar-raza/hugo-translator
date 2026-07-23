"""
Unit tests for src/utils/content_discovery.py -- the canonical, config-driven
content discovery module that replaces hand-rolled per-script site/locale
enumeration logic across the audit/quality script family.
"""
from pathlib import Path

from src.utils.content_discovery import (
    ALL_LANGUAGE_CODES,
    discover_source_files,
    is_translated_filename,
    iter_bundle_family_platform_index,
    iter_locale_pairs,
    resolve_source_root,
    resolve_translated_path,
)
from src.utils.models import BodyRules, OutputLayout, SiteProfile


def make_profile(
    per_language_folders: bool,
    pattern: str,
    target_langs=None,
    default_source_lang: str = "en",
) -> SiteProfile:
    return SiteProfile(
        site_id="example.test",
        content_roots=["."],
        default_source_lang=default_source_lang,
        target_langs=target_langs or ["fr", "es", "ja"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(
            per_language_folders=per_language_folders, pattern=pattern
        ),
    )


# ---------------------------------------------------------------------------
# is_translated_filename
# ---------------------------------------------------------------------------

class TestIsTranslatedFilename:
    def test_basic_translated_file(self):
        is_translated, lang = is_translated_filename("index.es.md", ["es", "fr"])
        assert is_translated is True
        assert lang == "es"

    def test_source_file_not_translated(self):
        is_translated, lang = is_translated_filename("index.md", ["es", "fr"])
        assert is_translated is False
        assert lang is None

    def test_case_insensitive(self):
        is_translated, lang = is_translated_filename("index.ES.MD", ["es", "fr"])
        assert is_translated is True
        assert lang == "es"

    def test_markdown_extension(self):
        is_translated, _ = is_translated_filename("tutorial.fr.markdown", ["fr"])
        assert is_translated is True

    def test_double_suffix_matches_last(self):
        # index.es.da.md -> matches trailing .da.md
        is_translated, lang = is_translated_filename(
            "index.es.da.md", ["es", "da"]
        )
        assert is_translated is True
        assert lang == "da"

    def test_junk_suffix_not_treated_as_locale(self):
        """A stray backup/temp file must NOT be misclassified as a translation.

        This is the concrete divergence case found during investigation: at
        least one duplicated ad hoc implementation used a bare `[a-z]{2,3}`
        regex with no whitelist, which WOULD misclassify this as locale "bak".
        The whitelist-based approach here must not.
        """
        is_translated, lang = is_translated_filename("index.bak.md", ["es", "fr"])
        assert is_translated is False
        assert lang is None

    def test_unconfigured_region_code_not_matched(self):
        """A region-coded filename not present in target_langs or the known
        codes list must not match -- another confirmed divergence case."""
        is_translated, lang = is_translated_filename("index.pt-br.md", ["es", "fr"])
        assert is_translated is False
        assert lang is None

    def test_source_lang_excluded(self):
        # en is the source language; index.en.md should not count as translated
        is_translated, _ = is_translated_filename("index.en.md", ["es", "fr"], source_lang="en")
        assert is_translated is False

    def test_known_code_not_in_target_langs_still_matches(self):
        # "de" is in the canonical ALL_LANGUAGE_CODES set even if this site's
        # target_langs doesn't include it -- matches production behavior.
        assert "de" in ALL_LANGUAGE_CODES
        is_translated, lang = is_translated_filename("index.de.md", ["es", "fr"])
        assert is_translated is True
        assert lang == "de"


# ---------------------------------------------------------------------------
# resolve_translated_path
# ---------------------------------------------------------------------------

class TestResolveTranslatedPath:
    def test_per_language_folders_forward_slash(self):
        profile = make_profile(True, "{lang}/{path}")
        source = Path("/content/site/en/guide.md")
        result = resolve_translated_path(profile, source, "fr")
        assert result == Path("/content/site/fr/guide.md")

    def test_per_language_folders_trailing_no_separator(self):
        profile = make_profile(True, "{lang}/{path}")
        source = Path("/content/site/en")
        result = resolve_translated_path(profile, source, "fr")
        assert str(result).endswith("fr")

    def test_file_suffix_pattern_filename_ext(self):
        """The blog.aspose.org / blog.aspose.net / www.aspose.org convention."""
        profile = make_profile(False, "{filename}.{lang}{ext}")
        source = Path("/content/blog/cells/net/slug/index.md")
        result = resolve_translated_path(profile, source, "fr")
        assert result == Path("/content/blog/cells/net/slug/index.fr.md")

    def test_file_suffix_pattern_path_stem(self):
        """The www.aspose.net convention -- a distinct placeholder name
        (`path_stem` instead of `filename`) that the original engine.py
        implementation did not supply, which would have raised KeyError."""
        profile = make_profile(False, "{path_stem}.{lang}.md")
        source = Path("/content/www/about/index.md")
        result = resolve_translated_path(profile, source, "de")
        assert result == Path("/content/www/about/index.de.md")

    def test_file_suffix_preserves_directory(self):
        profile = make_profile(False, "{filename}.{lang}{ext}")
        source = Path("/content/blog/archive.md")
        result = resolve_translated_path(profile, source, "ja")
        assert result.parent == source.parent
        assert result.name == "archive.ja.md"


# ---------------------------------------------------------------------------
# discover_source_files
# ---------------------------------------------------------------------------

class TestDiscoverSourceFiles:
    def test_per_language_folders_layout(self, tmp_path):
        profile = make_profile(True, "{lang}/{path}")
        en_dir = tmp_path / "en"
        en_dir.mkdir()
        (en_dir / "index.md").write_text("hello")
        (en_dir / "guide.md").write_text("world")
        (tmp_path / "fr").mkdir()
        (tmp_path / "fr" / "index.md").write_text("bonjour")

        files = discover_source_files(profile, tmp_path)
        names = sorted(f.name for f in files)
        assert names == ["guide.md", "index.md"]
        assert all(f.parent == en_dir for f in files)

    def test_file_suffix_layout_excludes_translations(self, tmp_path):
        profile = make_profile(False, "{filename}.{lang}{ext}", target_langs=["fr", "es"])
        (tmp_path / "index.md").write_text("hello")
        (tmp_path / "index.fr.md").write_text("bonjour")
        (tmp_path / "index.es.md").write_text("hola")
        (tmp_path / "archive.md").write_text("archive")

        files = discover_source_files(profile, tmp_path)
        names = sorted(f.name for f in files)
        assert names == ["archive.md", "index.md"]

    def test_file_suffix_layout_missing_root_returns_empty(self, tmp_path):
        profile = make_profile(False, "{filename}.{lang}{ext}")
        result = discover_source_files(profile, tmp_path / "does-not-exist")
        assert result == []

    def test_per_language_folders_missing_source_root_returns_empty(self, tmp_path):
        profile = make_profile(True, "{lang}/{path}")
        result = discover_source_files(profile, tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# iter_locale_pairs
# ---------------------------------------------------------------------------

class TestIterLocalePairs:
    def test_file_suffix_layout_pairs(self, tmp_path):
        profile = make_profile(False, "{filename}.{lang}{ext}", target_langs=["fr", "es"])
        (tmp_path / "index.md").write_text("hello")

        pairs = list(iter_locale_pairs(profile, tmp_path))
        assert len(pairs) == 2
        locales = {locale for _, locale, _ in pairs}
        assert locales == {"fr", "es"}
        for source, locale, expected in pairs:
            assert source.name == "index.md"
            assert expected.name == f"index.{locale}.md"

    def test_per_language_folders_pairs(self, tmp_path):
        profile = make_profile(True, "{lang}/{path}", target_langs=["fr"])
        en_dir = tmp_path / "en"
        en_dir.mkdir()
        (en_dir / "index.md").write_text("hello")

        pairs = list(iter_locale_pairs(profile, tmp_path))
        assert len(pairs) == 1
        source, locale, expected = pairs[0]
        assert locale == "fr"
        assert expected == tmp_path / "fr" / "index.md"


# ---------------------------------------------------------------------------
# resolve_source_root
# ---------------------------------------------------------------------------

class TestResolveSourceRoot:
    def test_per_language_folders_uses_source_lang_subdir(self, tmp_path):
        profile = make_profile(True, "{lang}/{path}")
        assert resolve_source_root(profile, tmp_path) == tmp_path / "en"

    def test_file_suffix_uses_content_root_directly(self, tmp_path):
        profile = make_profile(False, "{filename}.{lang}{ext}")
        assert resolve_source_root(profile, tmp_path) == tmp_path


# ---------------------------------------------------------------------------
# iter_bundle_family_platform_index
# ---------------------------------------------------------------------------

class TestIterBundleFamilyPlatformIndex:
    def test_matches_family_platform_index(self, tmp_path):
        (tmp_path / "cells" / "net").mkdir(parents=True)
        (tmp_path / "cells" / "net" / "_index.md").write_text("index")
        (tmp_path / "cells" / "net" / "other.md").write_text("not index")
        (tmp_path / "words" / "java").mkdir(parents=True)
        (tmp_path / "words" / "java" / "_index.md").write_text("index")

        results = sorted(iter_bundle_family_platform_index(tmp_path))
        assert len(results) == 2
        assert all(p.name == "_index.md" for p in results)

    def test_missing_root_yields_nothing(self, tmp_path):
        results = list(iter_bundle_family_platform_index(tmp_path / "missing"))
        assert results == []
