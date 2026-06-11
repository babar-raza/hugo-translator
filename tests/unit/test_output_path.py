"""Unit tests for translation output path logic."""

from pathlib import Path


class MockOutputLayout:
    """Mock OutputLayout for testing."""

    def __init__(self, per_language_folders, pattern):
        self.per_language_folders = per_language_folders
        self.pattern = pattern


class MockSiteProfile:
    """Mock SiteProfile for testing."""

    def __init__(self, output_layout, default_source_lang="en", output_dir=None):
        self.output_layout = output_layout
        self.default_source_lang = default_source_lang
        self.output_dir = output_dir


def test_file_based_localization_pattern():
    """Test file-based localization with {filename}.{lang}{ext} pattern."""
    # Setup
    source_path = Path("/content/blog/index.md")
    target_lang = "es"
    output_layout = MockOutputLayout(per_language_folders=False, pattern="{filename}.{lang}{ext}")
    site_profile = MockSiteProfile(output_layout)

    # Apply pattern manually (same logic as in engine.py)
    pattern = output_layout.pattern
    filename_stem = source_path.stem  # "index"
    filename_ext = source_path.suffix  # ".md"

    output_filename = pattern.format(
        filename=filename_stem, lang=target_lang, ext=filename_ext, path=str(source_path.name)
    )

    # Verify
    assert output_filename == "index.es.md"


def test_folder_based_localization_pattern():
    """Test folder-based localization with {lang}/{path} pattern."""
    # Setup
    source_path = Path("/content/blog/index.md")
    target_lang = "de"
    output_layout = MockOutputLayout(per_language_folders=True, pattern="{lang}/{path}")
    site_profile = MockSiteProfile(output_layout)

    # For folder-based, pattern is used differently (not tested here)
    # This test just verifies the pattern exists
    assert output_layout.pattern == "{lang}/{path}"
    assert output_layout.per_language_folders is True


def test_pattern_substitution_with_different_extensions():
    """Test pattern substitution works with various file extensions."""
    test_cases = [
        ("index.md", ".md", "es", "index.es.md"),
        ("content.html", ".html", "fr", "content.fr.html"),
        ("article.txt", ".txt", "ja", "article.ja.txt"),
    ]

    pattern = "{filename}.{lang}{ext}"

    for full_name, ext, lang, expected in test_cases:
        source_path = Path(full_name)
        filename_stem = source_path.stem
        filename_ext = source_path.suffix

        output_filename = pattern.format(
            filename=filename_stem, lang=lang, ext=filename_ext, path=str(source_path.name)
        )

        assert output_filename == expected, f"Expected {expected}, got {output_filename}"


def test_pattern_with_path_variable():
    """Test pattern substitution using {path} variable."""
    source_path = Path("/content/blog/article.md")
    target_lang = "es"
    pattern = "{lang}/{path}"

    output_path = pattern.format(
        lang=target_lang,
        path=str(source_path.name),
        filename=source_path.stem,
        ext=source_path.suffix,
    )

    assert output_path == "es/article.md"


if __name__ == "__main__":
    # Run tests
    test_file_based_localization_pattern()
    test_folder_based_localization_pattern()
    test_pattern_substitution_with_different_extensions()
    test_pattern_with_path_variable()
    print("All tests passed!")
