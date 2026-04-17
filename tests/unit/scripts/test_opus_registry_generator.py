"""
Unit tests for Opus registry generator.

Tests:
- Opus model entry generation
- supported_pairs correctness for bilingual models
- local_path generation according to spec
"""
# Import the generator functions
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.generate_opus_registry import (
    generate_opus_model_entry,
    load_target_languages,
)


class TestOpusRegistryGenerator:
    """Tests for Opus registry generation."""

    def test_generate_opus_entry_basic(self):
        """Test generating basic Opus model entry."""
        entry = generate_opus_model_entry(
            src_lang="en",
            tgt_lang="fr",
            check_online=False
        )

        assert entry is not None
        assert entry["model_id"] == "opus_en_fr"
        assert entry["hf_model_id"] == "Helsinki-NLP/opus-mt-en-fr"
        assert entry["backend"] == "opus"
        assert entry["local_path"] == "models/opus/opus-mt-en-fr"

    def test_generate_opus_entry_supported_pairs(self):
        """Test that supported_pairs includes both directions."""
        entry = generate_opus_model_entry("en", "de", check_online=False)

        assert entry["supported_pairs"] == [["en", "de"], ["de", "en"]]

    def test_generate_opus_entry_defaults(self):
        """Test default values for Opus models."""
        entry = generate_opus_model_entry("en", "es", check_online=False)

        # Opus models should have consistent defaults
        assert entry["model_size_mb"] == 300
        assert entry["min_ram_gb"] == 1.0
        assert entry["optimal_device"] == "cpu"
        assert entry["license"] == "CC-BY-4.0"
        assert entry["parameters"] == 77000000

    @patch("scripts.generate_opus_registry.model_info")
    def test_generate_opus_entry_online_check_exists(self, mock_model_info):
        """Test online check when model exists."""
        # Mock successful model info retrieval
        mock_model_info.return_value = Mock()

        entry = generate_opus_model_entry("en", "fr", check_online=True)

        assert entry["available"] is True
        assert "verified on HuggingFace Hub" in entry["description"]
        mock_model_info.assert_called_once_with("Helsinki-NLP/opus-mt-en-fr", timeout=10)

    @patch("scripts.generate_opus_registry.model_info")
    def test_generate_opus_entry_online_check_not_exists(self, mock_model_info):
        """Test online check when model doesn't exist."""
        # Mock 404 error
        mock_model_info.side_effect = Exception("404: Model not found")

        entry = generate_opus_model_entry("en", "xyz", check_online=True)

        # Should return entry marked as unavailable
        assert entry["available"] is False
        assert "UNAVAILABLE" in entry["description"]
        assert entry["model_size_mb"] == 0

    def test_load_target_languages(self, tmp_path):
        """Test loading target languages from YAML."""
        # Create mock config file
        config_path = tmp_path / "target_languages.yaml"
        config_path.write_text("""
version: "1.0"
languages:
  - iso_code: ar
    name: Arabic
  - iso_code: fr
    name: French
  - iso_code: de
    name: German
""")

        langs = load_target_languages(config_path)

        assert langs == ["ar", "fr", "de"]

    def test_generate_multiple_languages(self):
        """Test generating entries for multiple languages."""
        languages = ["fr", "de", "es", "ja"]
        entries = []

        for lang in languages:
            entry = generate_opus_model_entry("en", lang, check_online=False)
            entries.append(entry)

        # All entries should have correct structure
        assert len(entries) == 4

        for i, lang in enumerate(languages):
            entry = entries[i]
            assert entry["model_id"] == f"opus_en_{lang}"
            assert entry["supported_pairs"] == [["en", lang], [lang, "en"]]
            assert entry["hf_model_id"] == f"Helsinki-NLP/opus-mt-en-{lang}"


class TestDiscoverHfCacheModels:
    """Tests for discover_hf_cache_models.py improvements."""

    def test_parse_opus_language_pair(self):
        """Test parsing Opus language pairs."""
        from scripts.discover_hf_cache_models import _parse_opus_language_pair

        # Valid Opus models
        assert _parse_opus_language_pair("Helsinki-NLP/opus-mt-en-fr") == ("en", "fr")
        assert _parse_opus_language_pair("Helsinki-NLP/opus-mt-de-en") == ("de", "en")
        assert _parse_opus_language_pair("Helsinki-NLP/opus-mt-en-es") == ("en", "es")

        # Non-Opus models
        assert _parse_opus_language_pair("facebook/m2m100_418M") is None
        assert _parse_opus_language_pair("facebook/nllb-200-600M") is None

        # Invalid Opus patterns
        assert _parse_opus_language_pair("Helsinki-NLP/opus-mt-invalid") is None

    def test_compute_directory_size(self, tmp_path):
        """Test directory size computation."""
        from scripts.discover_hf_cache_models import _compute_directory_size_mb

        # Create test directory with files
        test_dir = tmp_path / "test_model"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_bytes(b"x" * 1024 * 1024)  # 1 MB
        (test_dir / "file2.txt").write_bytes(b"x" * 2 * 1024 * 1024)  # 2 MB

        size_mb = _compute_directory_size_mb(test_dir)

        assert 2.9 < size_mb < 3.1  # Allow small rounding error

    def test_check_model_in_organized_layout(self, tmp_path):
        """Test checking for models in organized layout."""
        from scripts.discover_hf_cache_models import _check_model_in_organized_layout

        # Create Opus model in organized layout
        opus_path = tmp_path / "opus" / "opus-mt-en-fr"
        opus_path.mkdir(parents=True)
        (opus_path / "config.json").write_text("{}")

        result = _check_model_in_organized_layout(
            "Helsinki-NLP/opus-mt-en-fr",
            models_dir=tmp_path
        )

        assert result == opus_path

        # Non-existent model
        result2 = _check_model_in_organized_layout(
            "Helsinki-NLP/opus-mt-en-de",
            models_dir=tmp_path
        )

        assert result2 is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
