"""
Unit tests for source file filtering logic.

Tests the _is_translated_filename() helper function and _filter_source_files() method
to ensure correct identification of source vs translated files for blog.aspose.net pattern.
"""
import pytest
from pathlib import Path
from src.translation_engine.engine import _is_translated_filename


class TestIsTranslatedFilename:
    """Test helper function for detecting translated filenames."""

    @pytest.mark.parametrize("filename,target_langs,source_lang,expected_translated,expected_lang", [
        # Source files (should NOT be filtered - no language code)
        ("index.md", ["es", "fr"], "en", False, None),
        ("_index.md", ["es", "fr"], "en", False, None),
        ("tutorial.md", ["es", "fr", "da"], "en", False, None),
        ("README.md", ["es"], "en", False, None),
        ("post.md", ["es", "fr"], "en", False, None),

        # Translated files (should be filtered - language code present)
        ("index.es.md", ["es", "fr"], "en", True, "es"),
        ("index.fr.md", ["es", "fr"], "en", True, "fr"),
        ("tutorial.da.md", ["da"], "en", True, "da"),
        ("post.de.md", ["de", "fr"], "en", True, "de"),

        # Case insensitive matching
        ("index.ES.MD", ["es", "fr"], "en", True, "es"),
        ("tutorial.FR.MD", ["es", "fr"], "en", True, "fr"),
        ("INDEX.De.Md", ["de"], "en", True, "de"),

        # .markdown extension support
        ("tutorial.fr.markdown", ["es", "fr"], "en", True, "fr"),
        ("index.es.markdown", ["es"], "en", True, "es"),
        ("post.DE.MARKDOWN", ["de"], "en", True, "de"),

        # Double-language files (matches last language code found)
        ("index.es.da.md", ["es", "da", "fr"], "en", True, "da"),
        ("post.de.fr.md", ["de", "fr"], "en", True, "fr"),
        ("tutorial.fr.es.md", ["es", "fr"], "en", True, "es"),

        # Source language files (should NOT be filtered when source_lang matches)
        ("index.en.md", ["es", "fr"], "en", False, None),  # en is source lang, excluded

        # Edge cases: files without .md extension (should NOT match)
        ("index.es.txt", ["es"], "en", False, None),
        ("tutorial.fr.html", ["fr"], "en", False, None),

        # Files with language-like patterns but not matching (depends on _ALL_LANGUAGE_CODES)
        # Note: "business.es.md" WILL match because "es" is a valid language code
        # This is expected behavior - the pattern is .{lang}.(md|markdown)
        ("business.es.md", ["es", "fr"], "en", True, "es"),  # "es" matches
        ("design.id.md", ["id"], "en", True, "id"),  # "id" (Indonesian) matches

        # Files not in target_langs but in _ALL_LANGUAGE_CODES (should still match)
        ("index.ja.md", ["es", "fr"], "en", True, "ja"),  # ja in _ALL_LANGUAGE_CODES
        ("post.zh.md", ["es"], "en", True, "zh"),  # zh in _ALL_LANGUAGE_CODES
        ("tutorial.ar.md", ["de"], "en", True, "ar"),  # ar in _ALL_LANGUAGE_CODES
    ])
    def test_detection(self, filename, target_langs, source_lang, expected_translated, expected_lang):
        """Test detection of translated vs source filenames."""
        is_trans, detected = _is_translated_filename(filename, target_langs, source_lang=source_lang)
        assert is_trans == expected_translated, f"Failed for {filename}: expected {expected_translated}, got {is_trans}"
        assert detected == expected_lang, f"Failed for {filename}: expected lang {expected_lang}, got {detected}"

    def test_empty_target_langs(self):
        """Test with empty target_langs list (should still check _ALL_LANGUAGE_CODES)."""
        # Even with no target langs, should detect common languages from _ALL_LANGUAGE_CODES
        is_trans, lang = _is_translated_filename("index.es.md", [], "en")
        assert is_trans == True
        assert lang == "es"

    def test_source_lang_excluded(self):
        """Test that source language is excluded from filtering."""
        # File with source language code should NOT be filtered
        is_trans, lang = _is_translated_filename("index.en.md", ["es", "fr"], "en")
        assert is_trans == False
        assert lang == None

    def test_non_markdown_files(self):
        """Test that non-markdown files are not detected as translated."""
        non_md_files = [
            "index.es.txt",
            "tutorial.fr.html",
            "post.de.json",
            "readme.es",
        ]
        for filename in non_md_files:
            is_trans, lang = _is_translated_filename(filename, ["es", "fr", "de"], "en")
            assert is_trans == False, f"{filename} should not be detected as translated"
            assert lang == None

    def test_underscore_prefix(self):
        """Test Hugo special files with underscore prefix."""
        # _index files are source files unless they have language code
        is_trans, lang = _is_translated_filename("_index.md", ["es"], "en")
        assert is_trans == False

        # _index with language code should be detected
        is_trans, lang = _is_translated_filename("_index.es.md", ["es"], "en")
        assert is_trans == True
        assert lang == "es"

    def test_multiple_language_codes_in_list(self):
        """Test detection when multiple language codes are provided."""
        # Should detect the correct language from the list
        is_trans, lang = _is_translated_filename("index.pt.md", ["pt", "es", "fr"], "en")
        assert is_trans == True
        assert lang == "pt"


class TestFilterSourceFilesIntegration:
    """
    Integration tests for _filter_source_files() method.
    Tests the full method with mock site profiles and file lists.
    """

    def test_file_based_localization_filters_correctly(self, tmp_path):
        """Test filtering with file-based localization (blog.aspose.net pattern)."""
        from unittest.mock import MagicMock
        from src.translation_engine.engine import TranslationEngine
        from src.utils.config_loader import ConfigService

        # Create test files
        source_files = ["index.md", "_index.md", "tutorial.md"]
        translated_files = ["index.es.md", "index.da.md", "tutorial.fr.md", "_index.de.md"]

        all_files = []
        for f in source_files + translated_files:
            fpath = tmp_path / f
            fpath.touch()
            all_files.append(fpath)

        # Mock site profile for file-based localization
        site_profile = MagicMock()
        site_profile.output_layout.per_language_folders = False
        site_profile.default_source_lang = 'en'

        # Create engine (minimal config needed)
        config = MagicMock(spec=ConfigService)
        engine = TranslationEngine(config_service=config, tm=None, model_loader=None)

        # Filter files
        filtered = engine._filter_source_files(
            all_files,
            site_profile,
            target_langs=['es', 'da', 'fr', 'de']
        )

        # Verify: only source files included
        assert len(filtered) == len(source_files), f"Expected {len(source_files)} files, got {len(filtered)}"
        filtered_names = {f.name for f in filtered}
        assert filtered_names == set(source_files)

        # Verify: no translated files included
        for f in filtered:
            assert f.name not in translated_files

    def test_folder_based_localization_filters_correctly(self, tmp_path):
        """Test filtering with folder-based localization (/en/, /de/ pattern)."""
        from unittest.mock import MagicMock
        from src.translation_engine.engine import TranslationEngine

        # Create directory structure
        en_dir = tmp_path / "en"
        es_dir = tmp_path / "es"
        de_dir = tmp_path / "de"
        en_dir.mkdir()
        es_dir.mkdir()
        de_dir.mkdir()

        # Create source files in /en/
        source_files = [
            en_dir / "index.md",
            en_dir / "tutorial.md",
            en_dir / "posts" / "post1.md",
        ]
        (en_dir / "posts").mkdir()
        for f in source_files:
            f.touch()

        # Create translated files in /es/ and /de/
        translated_files = [
            es_dir / "index.md",
            es_dir / "tutorial.md",
            de_dir / "index.md",
        ]
        for f in translated_files:
            f.touch()

        all_files = source_files + translated_files

        # Mock site profile for folder-based localization
        site_profile = MagicMock()
        site_profile.output_layout.per_language_folders = True
        site_profile.default_source_lang = 'en'

        config = MagicMock()
        engine = TranslationEngine(config_service=config, tm=None, model_loader=None)

        # Filter files
        filtered = engine._filter_source_files(
            all_files,
            site_profile,
            target_langs=['es', 'de', 'fr']
        )

        # Verify: only source files from /en/ included
        assert len(filtered) == len(source_files)
        for f in filtered:
            assert "/en/" in str(f) or "\\en\\" in str(f)

    def test_empty_file_list(self):
        """Test filtering empty file list returns empty."""
        from unittest.mock import MagicMock
        from src.translation_engine.engine import TranslationEngine

        site_profile = MagicMock()
        site_profile.output_layout.per_language_folders = False
        site_profile.default_source_lang = 'en'

        config = MagicMock()
        engine = TranslationEngine(config_service=config, tm=None, model_loader=None)

        filtered = engine._filter_source_files([], site_profile, target_langs=['es'])
        assert filtered == []

    def test_all_source_files_no_filtering_needed(self, tmp_path):
        """Test that all source files pass through when no translated files present."""
        from unittest.mock import MagicMock
        from src.translation_engine.engine import TranslationEngine

        # Only source files
        source_files = [tmp_path / f for f in ["index.md", "tutorial.md", "post.md"]]
        for f in source_files:
            f.touch()

        site_profile = MagicMock()
        site_profile.output_layout.per_language_folders = False
        site_profile.default_source_lang = 'en'

        config = MagicMock()
        engine = TranslationEngine(config_service=config, tm=None, model_loader=None)

        filtered = engine._filter_source_files(source_files, site_profile, target_langs=['es', 'fr'])

        assert len(filtered) == len(source_files)
        assert set(filtered) == set(source_files)


class TestEdgeCases:
    """Test edge cases and unusual patterns for filtering logic."""

    def test_non_markdown_files_not_detected(self):
        """Non-markdown files should never be detected as translated."""
        from src.translation_engine.engine import _is_translated_filename

        non_md = [
            "index.es.txt",
            "tutorial.fr.html",
            "post.de.json",
            "readme.es.xml",
            "config.da.yaml",
            "data.pt.csv",
        ]

        for filename in non_md:
            is_trans, lang = _is_translated_filename(filename, ['es', 'fr', 'de', 'da', 'pt'], 'en')
            assert is_trans == False, f"{filename} should not be detected as translated"
            assert lang == None

    def test_backup_and_temporary_files(self):
        """Backup and temp files should be handled gracefully."""
        from src.translation_engine.engine import _is_translated_filename

        edge_files = [
            ("index.md.backup", False, None),  # Backup file, not translated
            ("tutorial.es.md.backup", False, None),  # Doesn't end with .md
            ("post.md.tmp", False, None),  # Temp file
            (".index.md", False, None),  # Hidden file (source)
            ("~index.md", False, None),  # Temp editor file
        ]

        for filename, expected_trans, expected_lang in edge_files:
            is_trans, lang = _is_translated_filename(filename, ['es', 'fr'], 'en')
            assert is_trans == expected_trans, f"Failed for {filename}"
            assert lang == expected_lang

    def test_double_extension_files(self):
        """Files with double extensions like .md.old should be handled."""
        from src.translation_engine.engine import _is_translated_filename

        # These should NOT match because they don't end with .md or .markdown
        assert _is_translated_filename("index.es.md.old", ['es'], 'en') == (False, None)
        assert _is_translated_filename("tutorial.fr.markdown.bak", ['fr'], 'en') == (False, None)

    def test_unusual_capitalization(self):
        """Test various capitalization patterns."""
        from src.translation_engine.engine import _is_translated_filename

        # All should match (case-insensitive)
        caps_variants = [
            ("INDEX.ES.MD", True, "es"),
            ("Index.Es.Md", True, "es"),
            ("index.ES.md", True, "es"),
            ("INDEX.es.MD", True, "es"),
            ("tutorial.FR.MARKDOWN", True, "fr"),
            ("Tutorial.Fr.Markdown", True, "fr"),
        ]

        for filename, expected_trans, expected_lang in caps_variants:
            is_trans, lang = _is_translated_filename(filename, ['es', 'fr'], 'en')
            assert is_trans == expected_trans, f"Failed for {filename}"
            assert lang == expected_lang

    def test_language_code_in_middle_of_filename(self):
        """Language codes in middle of filename (not before extension) should not match."""
        from src.translation_engine.engine import _is_translated_filename

        # These have 'es' or 'fr' in the name but not as language separator
        # IMPORTANT: These WILL match if pattern is .es. before .md
        # Our pattern is specifically \.{lang}\.(md|markdown)$

        # This WILL match - "business.es.md" has .es.md pattern
        assert _is_translated_filename("business.es.md", ['es'], 'en') == (True, 'es')

        # This will NOT match - "es" is the whole filename (no stem before .es)
        assert _is_translated_filename("es.md", ['es'], 'en') == (False, None)

        # This will NOT match - no dot before es
        assert _is_translated_filename("espanol.md", ['es'], 'en') == (False, None)

    def test_very_long_filenames(self):
        """Test filtering works with very long filenames."""
        from src.translation_engine.engine import _is_translated_filename

        long_name = "a" * 200 + ".es.md"
        is_trans, lang = _is_translated_filename(long_name, ['es'], 'en')
        assert is_trans == True
        assert lang == 'es'

        long_name_source = "a" * 200 + ".md"
        is_trans, lang = _is_translated_filename(long_name_source, ['es'], 'en')
        assert is_trans == False
        assert lang == None

    def test_special_characters_in_filename(self):
        """Test filenames with special characters."""
        from src.translation_engine.engine import _is_translated_filename

        special_files = [
            ("post-2024-01-01.md", False, None),  # Hyphens (source)
            ("post-2024-01-01.es.md", True, "es"),  # Hyphens + lang
            ("my_tutorial.md", False, None),  # Underscores
            ("my_tutorial.fr.md", True, "fr"),  # Underscores + lang
            ("hello-world.pt.md", True, "pt"),  # Hyphens + lang
        ]

        for filename, expected_trans, expected_lang in special_files:
            is_trans, lang = _is_translated_filename(filename, ['es', 'fr', 'pt'], 'en')
            assert is_trans == expected_trans, f"Failed for {filename}"
            assert lang == expected_lang

    def test_multiple_dots_in_filename(self):
        """Test filenames with multiple dots."""
        from src.translation_engine.engine import _is_translated_filename

        # Pattern should only match the LAST .{lang}.(md|markdown)
        assert _is_translated_filename("v2.0.index.es.md", ['es'], 'en') == (True, 'es')
        assert _is_translated_filename("file.v1.0.md", ['v1'], 'en') == (False, None)  # v1 not a lang
        assert _is_translated_filename("my.file.name.fr.markdown", ['fr'], 'en') == (True, 'fr')


# Observability tests (TF-06)
class TestFilteringObservability:
    """Test logging and observability for filtering operations."""

    def test_summary_logging_when_files_filtered(self, tmp_path, caplog):
        """Verify INFO log shows summary when files are filtered."""
        import logging
        from unittest.mock import MagicMock
        from src.translation_engine.engine import TranslationEngine

        # Create mixed source and translated files
        source_files = [tmp_path / f for f in ["index.md", "tutorial.md"]]
        translated_files = [tmp_path / f for f in ["index.es.md", "tutorial.fr.md", "post.de.md"]]
        for f in source_files + translated_files:
            f.touch()

        site_profile = MagicMock()
        site_profile.output_layout.per_language_folders = False
        site_profile.default_source_lang = 'en'

        config = MagicMock()
        engine = TranslationEngine(config_service=config, tm=None, model_loader=None)

        # Capture logs
        with caplog.at_level(logging.INFO):
            filtered = engine._filter_source_files(
                source_files + translated_files,
                site_profile,
                target_langs=['es', 'fr', 'de']
            )

        # Verify summary log present
        assert "Source file filtering" in caplog.text
        assert "to translate" in caplog.text
        assert "already-translated skipped" in caplog.text

        # Verify counts are correct
        assert "2 to translate" in caplog.text
        assert "3 already-translated skipped" in caplog.text

    def test_no_logging_when_no_filtering(self, tmp_path, caplog):
        """Verify no INFO log when all files are source files."""
        import logging
        from unittest.mock import MagicMock
        from src.translation_engine.engine import TranslationEngine

        # Only source files
        source_files = [tmp_path / f for f in ["index.md", "tutorial.md", "post.md"]]
        for f in source_files:
            f.touch()

        site_profile = MagicMock()
        site_profile.output_layout.per_language_folders = False
        site_profile.default_source_lang = 'en'

        config = MagicMock()
        engine = TranslationEngine(config_service=config, tm=None, model_loader=None)

        with caplog.at_level(logging.INFO):
            filtered = engine._filter_source_files(
                source_files,
                site_profile,
                target_langs=['es', 'fr']
            )

        # Should not log filtering summary when nothing filtered
        assert "Source file filtering" not in caplog.text

    def test_warning_for_high_filter_rate(self, tmp_path, caplog):
        """Verify WARNING log when unusually high percentage of files filtered."""
        import logging
        from unittest.mock import MagicMock
        from src.translation_engine.engine import TranslationEngine

        # Create scenario: 2 source files, 50 translated files (high filter rate)
        source_files = [tmp_path / f for f in ["index.md", "tutorial.md"]]
        translated_files = [tmp_path / f"file{i}.es.md" for i in range(50)]
        for f in source_files + translated_files:
            f.touch()

        site_profile = MagicMock()
        site_profile.output_layout.per_language_folders = False
        site_profile.default_source_lang = 'en'

        config = MagicMock()
        engine = TranslationEngine(config_service=config, tm=None, model_loader=None)

        with caplog.at_level(logging.WARNING):
            filtered = engine._filter_source_files(
                source_files + translated_files,
                site_profile,
                target_langs=['es']
            )

        # Verify warning present
        assert "unusually high" in caplog.text
        assert "Verify input directory" in caplog.text
        # Should show percentage
        assert "96%" in caplog.text or "95%" in caplog.text  # 50/52 ~= 96%

    def test_no_warning_for_normal_filter_rate(self, tmp_path, caplog):
        """Verify no WARNING when filter rate is normal."""
        import logging
        from unittest.mock import MagicMock
        from src.translation_engine.engine import TranslationEngine

        # Balanced: 5 source, 3 translated
        source_files = [tmp_path / f"file{i}.md" for i in range(5)]
        translated_files = [tmp_path / f"trans{i}.es.md" for i in range(3)]
        for f in source_files + translated_files:
            f.touch()

        site_profile = MagicMock()
        site_profile.output_layout.per_language_folders = False
        site_profile.default_source_lang = 'en'

        config = MagicMock()
        engine = TranslationEngine(config_service=config, tm=None, model_loader=None)

        with caplog.at_level(logging.WARNING):
            filtered = engine._filter_source_files(
                source_files + translated_files,
                site_profile,
                target_langs=['es']
            )

        # Should not warn for normal filter rate
        assert "unusually high" not in caplog.text


# Performance benchmark (optional, for TF-02)
class TestFilteringPerformance:
    """Performance tests for filtering logic (informational, not strict requirements)."""

    def test_single_file_check_performance(self):
        """Verify single file check is fast enough for production use."""
        import time

        # Check 1000 filenames - should complete quickly
        filenames = [f"file{i}.md" for i in range(500)] + [f"file{i}.es.md" for i in range(500)]
        target_langs = ["es", "fr", "de", "da"]

        start = time.perf_counter()
        for filename in filenames:
            _is_translated_filename(filename, target_langs, "en")
        duration = time.perf_counter() - start

        # Should complete in well under 1 second for 1000 files
        assert duration < 1.0, f"Filtering 1000 filenames took {duration:.3f}s, expected <1s"
        print(f"Performance: {len(filenames)} filenames checked in {duration:.3f}s ({len(filenames)/duration:.0f} files/sec)")
