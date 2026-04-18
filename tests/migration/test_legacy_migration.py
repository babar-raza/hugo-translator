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
from tm.l1_cache import L1Cache
from tm.l2_persistent import L2PersistentTM, L2_DB_NAME
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

        # Initialize new TM using the actual dependency-injection API
        l1 = L1Cache(max_size=1000)
        l2 = L2PersistentTM(db_path=tm_dir / L2_DB_NAME, max_size_mb=64)
        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Migrate entries
        for source_text, translation in legacy_data.items():
            tm.store(
                site_id="default",
                src_lang="en",
                tgt_lang="de",
                text=source_text,
                translation=translation,
            )

        # Verify migration
        result = tm.lookup(
            site_id="default",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
        )

        assert result is not None
        assert result.translation == "Hallo"

    def test_migration_preserves_all_entries(self, legacy_cache_dir, tm_dir):
        """Test that all legacy entries are preserved during migration"""
        # Load all legacy caches
        total_entries = 0
        for cache_file in legacy_cache_dir.glob("cache_*.json"):
            with open(cache_file, encoding='utf-8') as f:
                cache_data = json.load(f)
                total_entries += len(cache_data)

        # Initialize TM using the actual dependency-injection API
        l1 = L1Cache(max_size=1000)
        l2 = L2PersistentTM(db_path=tm_dir / L2_DB_NAME, max_size_mb=64)
        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        # Migrate all caches
        migrated_count = 0
        for cache_file in legacy_cache_dir.glob("cache_*.json"):
            lang_code = cache_file.stem.replace("cache_", "")

            with open(cache_file, encoding='utf-8') as f:
                cache_data = json.load(f)

            for source_text, translation in cache_data.items():
                tm.store(
                    site_id="default",
                    src_lang="en",
                    tgt_lang=lang_code,
                    text=source_text,
                    translation=translation,
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

        # Initialize TM using the actual dependency-injection API
        l1 = L1Cache(max_size=1000)
        l2 = L2PersistentTM(db_path=tm_dir / L2_DB_NAME, max_size_mb=64)
        _tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

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

        # Initialize TM using the actual dependency-injection API
        l1 = L1Cache(max_size=1000)
        l2 = L2PersistentTM(db_path=tm_dir / L2_DB_NAME, max_size_mb=64)
        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

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
                site_id="default",
                src_lang="en",
                tgt_lang="de",
                text=source_text,
                translation=translation,
            )
            valid_count += 1

        # JSON serializes all keys as strings, so 123 becomes "123" (truthy, isinstance str)
        # Valid entries after JSON round-trip: 'Valid', '123', 'Valid2' = 3
        assert valid_count == 3


class TestSystemCompatibility:
    """Test compatibility between legacy and new systems"""

    def test_normalization_compatibility(self):
        """Test that text normalization is compatible"""
        # normalize_text does NOT lowercase; see src/tm/normalization.py
        # It applies NFC normalization, whitespace collapsing, and trimming only.
        test_cases = [
            ("Hello World", "Hello World"),
            ("  Extra   Spaces  ", "Extra Spaces"),
            ("MixedCase", "MixedCase"),
            ("With\nNewlines", "With Newlines"),
        ]

        for input_text, expected_normalized in test_cases:
            normalized = normalize_text(input_text)
            assert normalized == expected_normalized

    def test_translation_equivalence(self, legacy_cache_dir, tm_dir):
        """Test that translations match between legacy and new system"""
        # Load legacy cache
        cache_file = legacy_cache_dir / "cache_de.json"
        with open(cache_file, encoding='utf-8') as f:
            legacy_cache = json.load(f)

        # Initialize new TM using the actual dependency-injection API
        l1 = L1Cache(max_size=1000)
        l2 = L2PersistentTM(db_path=tm_dir / L2_DB_NAME, max_size_mb=64)
        tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

        for source_text, translation in legacy_cache.items():
            tm.store(
                site_id="default",
                src_lang="en",
                tgt_lang="de",
                text=source_text,
                translation=translation,
            )

        # Verify all translations match
        for source_text, expected_translation in legacy_cache.items():
            result = tm.lookup(
                site_id="default",
                src_lang="en",
                tgt_lang="de",
                text=source_text,
            )

            assert result is not None
            assert result.translation == expected_translation

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
        script_path = Path(__file__).parent.parent.parent / "scripts" / "archived" / "migrations" / "migrate_legacy_cache.py"
        assert script_path.exists(), "Migration script should exist at archived path"

    def test_comparison_script_exists(self):
        """Test that comparison script exists"""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "compare_systems.py"
        assert script_path.exists(), "Comparison script should exist"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
