"""
Unit tests for file filtering utility.

Tests both file-based and folder-based localization filtering strategies.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from utils.file_filters import filter_source_files


class MockSiteProfile:
    """Mock site profile for testing."""

    def __init__(self, per_language_folders=False, source_lang="en"):
        self.default_source_lang = source_lang
        self.output_layout = {"per_language_folders": per_language_folders}


class TestFileBasedLocalization:
    """Tests for file-based localization (language codes in filename)."""

    def test_filters_translated_files(self):
        """Should exclude files with language codes."""
        site_profile = MockSiteProfile(per_language_folders=False)
        files = [
            Path("index.md"),
            Path("index.ro.md"),
            Path("post.md"),
            Path("post.ro.md"),
            Path("about.de.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro", "de"])

        assert Path("index.md") in result
        assert Path("post.md") in result
        assert Path("index.ro.md") not in result
        assert Path("post.ro.md") not in result
        assert Path("about.de.md") not in result
        assert len(result) == 2

    def test_includes_source_files(self):
        """Should include files without language codes."""
        site_profile = MockSiteProfile(per_language_folders=False)
        files = [
            Path("index.md"),
            Path("_index.md"),
            Path("post.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro"])

        assert len(result) == 3
        assert all(f in result for f in files)

    def test_handles_multiple_language_codes(self):
        """Should filter out all target language files."""
        site_profile = MockSiteProfile(per_language_folders=False)
        files = [
            Path("index.md"),
            Path("index.ro.md"),
            Path("index.de.md"),
            Path("index.fr.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro", "de", "fr"])

        assert len(result) == 1
        assert Path("index.md") in result


class TestFolderBasedLocalization:
    """Tests for folder-based localization (language-specific folders)."""

    def test_filters_target_language_folders(self):
        """Should exclude files in target language folders."""
        site_profile = MockSiteProfile(per_language_folders=True, source_lang="en")
        files = [
            Path("content/en/index.md"),
            Path("content/ro/index.md"),
            Path("content/de/post.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro", "de"])

        assert Path("content/en/index.md") in result
        assert Path("content/ro/index.md") not in result
        assert Path("content/de/post.md") not in result
        assert len(result) == 1

    def test_includes_source_language_folder(self):
        """Should include files in source language folder."""
        site_profile = MockSiteProfile(per_language_folders=True, source_lang="en")
        files = [
            Path("content/en/index.md"),
            Path("content/en/posts/post1.md"),
            Path("content/en/posts/post2.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro"])

        assert len(result) == 3
        assert all(f in result for f in files)

    def test_handles_windows_paths(self):
        """Should handle Windows-style path separators."""
        site_profile = MockSiteProfile(per_language_folders=True, source_lang="en")
        files = [
            Path("content\\en\\index.md"),
            Path("content\\ro\\index.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro"])

        # Should include source language folder
        assert any("en" in str(f) for f in result)
        # Should exclude target language folder
        assert not any("ro" in str(f) and "en" not in str(f) for f in result)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_file_list(self):
        """Should handle empty input gracefully."""
        site_profile = MockSiteProfile()
        result = filter_source_files([], site_profile, ["ro"])
        assert result == []

    def test_empty_target_langs(self):
        """Should return all files when no target languages specified."""
        site_profile = MockSiteProfile()
        files = [Path("index.md"), Path("index.ro.md")]

        result = filter_source_files(files, site_profile, [])

        assert len(result) == 2
        assert all(f in result for f in files)

    def test_all_files_translated(self):
        """Should return empty list when all files are translated."""
        site_profile = MockSiteProfile(per_language_folders=False)
        files = [
            Path("index.ro.md"),
            Path("post.de.md"),
            Path("about.fr.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro", "de", "fr"])

        assert len(result) == 0

    def test_no_translated_files(self):
        """Should return all files when none are translated."""
        site_profile = MockSiteProfile(per_language_folders=False)
        files = [
            Path("index.md"),
            Path("post.md"),
            Path("about.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro"])

        assert len(result) == 3


class TestErrorHandling:
    """Tests for error handling and validation."""

    def test_none_site_profile(self):
        """Should raise ValueError for None site_profile."""
        with pytest.raises(ValueError, match="site_profile cannot be None"):
            filter_source_files([Path("test.md")], None, ["ro"])

    def test_non_list_files(self):
        """Should raise TypeError for non-list files parameter."""
        site_profile = MockSiteProfile()
        with pytest.raises(TypeError, match="files must be a list"):
            filter_source_files("not a list", site_profile, ["ro"])

    def test_non_list_target_langs(self):
        """Should raise TypeError for non-list target_langs parameter."""
        site_profile = MockSiteProfile()
        with pytest.raises(TypeError, match="target_langs must be a list"):
            filter_source_files([Path("test.md")], site_profile, "ro")

    def test_handles_missing_output_layout(self):
        """Should handle site_profile without output_layout attribute."""
        site_profile = Mock()
        site_profile.output_layout = None
        site_profile.default_source_lang = "en"

        files = [Path("index.md"), Path("index.ro.md")]

        # Should not raise, defaults to file-based localization
        result = filter_source_files(files, site_profile, ["ro"])

        assert Path("index.md") in result
        assert Path("index.ro.md") not in result


class TestSpecialCharacters:
    """Tests for files with special characters in names."""

    def test_unicode_filenames(self):
        """Should handle unicode characters in filenames."""
        site_profile = MockSiteProfile(per_language_folders=False)
        files = [
            Path("test_中文.md"),
            Path("test_中文.ro.md"),
            Path("тест.md"),
            Path("тест.ro.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro"])

        assert Path("test_中文.md") in result
        assert Path("тест.md") in result
        assert Path("test_中文.ro.md") not in result
        assert Path("тест.ro.md") not in result

    def test_spaces_in_filenames(self):
        """Should handle spaces in filenames."""
        site_profile = MockSiteProfile(per_language_folders=False)
        files = [
            Path("test file.md"),
            Path("test file.ro.md"),
            Path("another test.md"),
        ]

        result = filter_source_files(files, site_profile, ["ro"])

        assert Path("test file.md") in result
        assert Path("another test.md") in result
        assert Path("test file.ro.md") not in result
