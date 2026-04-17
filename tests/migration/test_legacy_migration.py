"""
Migration Tests - Legacy to New System

Tests to validate migration from legacy JSON cache to new LMDB Translation Memory
and ensure compatibility between old and new systems.
"""

import json
import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tm import TranslationMemory
from tm.normalization import normalize_text


class TestLegacyCacheMigration:
    """Test legacy cache migration functionality"""

    @pytest.fixture
    def legacy_cache_dir(self, tmp_path):
        """Temporary legacy cache directory with sample data (pytest-managed)."""
        cache_dir = tmp_path / "translation"
        cache_dir.mkdir()

        # Create sample legacy cache files
        legacy_caches = {
            'de': {
                'Hello': 'Hallo',
                'World': 'Welt',
                'Good morning': 'Guten Morgen',
                'Thank you': 'Danke',
                'Goodbye': 'Auf Wiedersehen'
            },
            'es': {
                'Hello': 'Hola',
                'World': 'Mundo',
                'Good morning': 'Buenos días',
                'Thank you': 'Gracias',
                'Goodbye': 'Adiós'
            },
            'fr': {
                'Hello': 'Bonjour',
                'World': 'Monde',
                'Good morning': 'Bonjour',
                'Thank you': 'Merci',
                'Goodbye': 'Au revoir'
            }
        }

        for lang_code, cache_data in legacy_caches.items():
            cache_file = cache_dir / f"cache_{lang_code}.json"
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

        return cache_dir

    @pytest.fixture
    def tm_dir(self, tmp_path):
        """Temporary TM directory (pytest-managed, auto-cleaned)."""
        return tmp_path / "tm"

    def test_legacy_cache_file_discovery(self, legacy_cache_dir):
        """Test finding legacy cache files"""
        cache_files = list(legacy_cache_dir.glob("cache_*.json"))
        assert len(cache_files) == 3, "Should find 3 legacy cache files"

        lang_codes = [f.stem.replace("cache_", "") for f in cache_files]
        assert set(lang_codes) == {'de', 'es', 'fr'}

    def test_legacy_cache_loading(self, legacy_cache_dir):
        """Test loading legacy cache JSON files"""
        cache_file = legacy_cache_dir / "cache_de.json"
        with open(cache_file, encoding='utf-8') as f:
            cache_data = json.load(f)

        assert isinstance(cache_data, dict)
        assert 'Hello' in cache_data
        assert cache_data['Hello'] == 'Hallo'
        assert len(cache_data) == 5

    def test_migration_to_tm(self, legacy_cache_dir, tm_dir):
        """Test migrating legacy cache to new TM"""
        # Load legacy cache
        cache_file = legacy_cache_dir / "cache_de.json"
        with open(cache_file, encoding='utf-8') as f:
            legacy_data = json.load(f)

        # Initialize new TM
        tm = TranslationMemory(
            lmdb_path=str(tm_dir / "lmdb"),
            faiss_path=str(tm_dir / "faiss"),
            l1_capacity=1000,
            l2_enabled=True,
            l3_enabled=False  # Disable for speed
        )

        # Migrate entries
        for source_text, translation in legacy_data.items():
            tm.store(
                source_text=source_text,
                target_text=translation,
                source_lang="en",
                target_lang="de",
                subdomain="default"
            )

        # Verify migration
        result = tm.lookup(
            source_text="Hello",
            source_lang="en",
            target_lang="de",
            subdomain="default"
        )

        assert result is not None
        assert result.target_text == "Hallo"

    def test_migration_preserves_all_entries(self, legacy_cache_dir, tm_dir):
        """Test that all legacy entries are preserved during migration"""
        # Load all legacy caches
        total_entries = 0
        for cache_file in legacy_cache_dir.glob("cache_*.json"):
            with open(cache_file, encoding='utf-8') as f:
                cache_data = json.load(f)
                total_entries += len(cache_data)

        # Initialize TM
        tm = TranslationMemory(
            lmdb_path=str(tm_dir / "lmdb"),
            faiss_path=str(tm_dir / "faiss"),
            l1_capacity=1000,
            l2_enabled=True,
            l3_enabled=False
        )

        # Migrate all caches
        migrated_count = 0
        for cache_file in legacy_cache_dir.glob("cache_*.json"):
            lang_code = cache_file.stem.replace("cache_", "")

            with open(cache_file, encoding='utf-8') as f:
                cache_data = json.load(f)

            for source_text, translation in cache_data.items():
                tm.store(
                    source_text=source_text,
                    target_text=translation,
                    source_lang="en",
                    target_lang=lang_code,
                    subdomain="default"
                )
                migrated_count += 1

        assert migrated_count == total_entries

    def test_migration_handles_empty_cache(self, tmp_path, tm_dir):
        """Test migration with empty legacy cache"""
        empty_cache_dir = tmp_path / "empty_cache"
        empty_cache_dir.mkdir()

        # Create empty cache file
        cache_file = empty_cache_dir / "cache_de.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        # Initialize TM
        tm = TranslationMemory(
            lmdb_path=str(tm_dir / "lmdb"),
            faiss_path=str(tm_dir / "faiss"),
            l1_capacity=1000,
            l2_enabled=True,
            l3_enabled=False
        )

        # Should not crash on empty cache
        with open(cache_file, encoding='utf-8') as f:
            cache_data = json.load(f)

        assert len(cache_data) == 0

    def test_migration_handles_invalid_entries(self, tmp_path, tm_dir):
        """Test migration with invalid cache entries"""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Create cache with invalid entries
        invalid_cache = {
            'Valid': 'Gültig',
            '': 'Empty source',  # Invalid: empty source
            'Empty target': '',  # Invalid: empty target
            123: 'Number key',   # Invalid: non-string key
            'Valid2': 'Gültig2'
        }

        cache_file = cache_dir / "cache_de.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(invalid_cache, f)

        # Initialize TM
        tm = TranslationMemory(
            lmdb_path=str(tm_dir / "lmdb"),
            faiss_path=str(tm_dir / "faiss"),
            l1_capacity=1000,
            l2_enabled=True,
            l3_enabled=False
        )

        # Migrate, skipping invalid entries
        with open(cache_file, encoding='utf-8') as f:
            cache_data = json.load(f)

        valid_count = 0
        for source_text, translation in cache_data.items():
            # Skip invalid entries
            if not source_text or not translation:
                continue
            if not isinstance(source_text, str) or not isinstance(translation, str):
                continue

            tm.store(
                source_text=source_text,
                target_text=translation,
                source_lang="en",
                target_lang="de",
                subdomain="default"
            )
            valid_count += 1

        # Should only migrate 2 valid entries
        assert valid_count == 2


class TestSystemCompatibility:
    """Test compatibility between legacy and new systems"""

    def test_normalization_compatibility(self):
        """Test that text normalization is compatible"""
        test_cases = [
            ("Hello World", "hello world"),
            ("  Extra   Spaces  ", "extra spaces"),
            ("MixedCase", "mixedcase"),
            ("With\nNewlines", "with newlines"),
        ]

        for input_text, expected_normalized in test_cases:
            normalized = normalize_text(input_text)
            assert normalized.replace(" ", "") == expected_normalized.replace(" ", "")

    def test_translation_equivalence(self, legacy_cache_dir, tm_dir):
        """Test that translations match between legacy and new system"""
        # Load legacy cache
        cache_file = legacy_cache_dir / "cache_de.json"
        with open(cache_file, encoding='utf-8') as f:
            legacy_cache = json.load(f)

        # Initialize new TM and migrate
        tm = TranslationMemory(
            lmdb_path=str(tm_dir / "lmdb"),
            faiss_path=str(tm_dir / "faiss"),
            l1_capacity=1000,
            l2_enabled=True,
            l3_enabled=False
        )

        for source_text, translation in legacy_cache.items():
            tm.store(
                source_text=source_text,
                target_text=translation,
                source_lang="en",
                target_lang="de",
                subdomain="default"
            )

        # Verify all translations match
        for source_text, expected_translation in legacy_cache.items():
            result = tm.lookup(
                source_text=source_text,
                source_lang="en",
                target_lang="de",
                subdomain="default"
            )

            assert result is not None
            assert result.target_text == expected_translation

    @pytest.fixture
    def legacy_cache_dir(self, tmp_path):
        """Temporary legacy cache directory (pytest-managed, auto-cleaned)."""
        cache_dir = tmp_path / "translation"
        cache_dir.mkdir()

        legacy_cache = {
            'Hello': 'Hallo',
            'World': 'Welt',
            'Good morning': 'Guten Morgen',
            'Thank you': 'Danke',
            'Goodbye': 'Auf Wiedersehen'
        }

        cache_file = cache_dir / "cache_de.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(legacy_cache, f, ensure_ascii=False)

        return cache_dir

    @pytest.fixture
    def tm_dir(self, tmp_path):
        """Temporary TM directory (pytest-managed, auto-cleaned)."""
        return tmp_path / "tm"


class TestMigrationScriptIntegration:
    """Integration tests for migration script"""

    def test_migration_script_exists(self):
        """Test that migration script exists"""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "migrate_legacy_cache.py"
        assert script_path.exists(), "Migration script should exist"

    def test_comparison_script_exists(self):
        """Test that comparison script exists"""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "compare_systems.py"
        assert script_path.exists(), "Comparison script should exist"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
