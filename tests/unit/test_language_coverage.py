"""Tests for language coverage validation."""
import tempfile
from pathlib import Path
import yaml
import pytest
from src.benchmarking.language_coverage import check_language_coverage, CoverageReport


def test_full_coverage_with_multilingual_model(tmp_path):
    """Test that multilingual model covers all languages."""
    registry = tmp_path / "registry.yaml"
    languages = tmp_path / "languages.yaml"

    registry.write_text(yaml.dump({
        "models": [
            {"model_id": "m2m100", "supported_pairs": "all"}
        ]
    }))

    languages.write_text(yaml.dump({
        "languages": [
            {"iso_code": "fr", "name": "French"},
            {"iso_code": "de", "name": "German"}
        ]
    }))

    report = check_language_coverage(str(registry), str(languages))

    assert report.total_languages == 2
    assert len(report.covered_languages) == 2
    assert len(report.missing_languages) == 0
    assert report.coverage_percentage == 100.0
    assert report.is_complete()
    assert "m2m100" in report.models_per_language["fr"]
    assert "m2m100" in report.models_per_language["de"]


def test_partial_coverage_with_specialized_models(tmp_path):
    """Test coverage with specialized models."""
    registry = tmp_path / "registry.yaml"
    languages = tmp_path / "languages.yaml"

    registry.write_text(yaml.dump({
        "models": [
            {
                "model_id": "opus_en_fr",
                "supported_pairs": [["en", "fr"]]
            }
        ]
    }))

    languages.write_text(yaml.dump({
        "languages": [
            {"iso_code": "fr", "name": "French"},
            {"iso_code": "de", "name": "German"}
        ]
    }))

    report = check_language_coverage(str(registry), str(languages))

    assert report.total_languages == 2
    assert "fr" in report.covered_languages
    assert "de" in report.missing_languages
    assert report.coverage_percentage == 50.0
    assert not report.is_complete()


def test_no_coverage(tmp_path):
    """Test when no models cover any languages."""
    registry = tmp_path / "registry.yaml"
    languages = tmp_path / "languages.yaml"

    registry.write_text(yaml.dump({"models": []}))

    languages.write_text(yaml.dump({
        "languages": [
            {"iso_code": "fr", "name": "French"},
            {"iso_code": "de", "name": "German"}
        ]
    }))

    report = check_language_coverage(str(registry), str(languages))

    assert report.total_languages == 2
    assert len(report.covered_languages) == 0
    assert len(report.missing_languages) == 2
    assert report.coverage_percentage == 0.0
    assert not report.is_complete()


def test_coverage_report_to_dict(tmp_path):
    """Test serialization of coverage report."""
    registry = tmp_path / "registry.yaml"
    languages = tmp_path / "languages.yaml"

    registry.write_text(yaml.dump({
        "models": [
            {"model_id": "m2m100", "supported_pairs": "all"}
        ]
    }))

    languages.write_text(yaml.dump({
        "languages": [
            {"iso_code": "fr", "name": "French"}
        ]
    }))

    report = check_language_coverage(str(registry), str(languages))
    report_dict = report.to_dict()

    assert report_dict["total"] == 1
    assert "fr" in report_dict["covered"]
    assert len(report_dict["missing"]) == 0
    assert report_dict["coverage_pct"] == 100.0
    assert "fr" in report_dict["models_per_language"]


def test_mixed_multilingual_and_specialized(tmp_path):
    """Test combination of multilingual and specialized models."""
    registry = tmp_path / "registry.yaml"
    languages = tmp_path / "languages.yaml"

    registry.write_text(yaml.dump({
        "models": [
            {"model_id": "m2m100", "supported_pairs": "all"},
            {"model_id": "opus_en_de", "supported_pairs": [["en", "de"]]}
        ]
    }))

    languages.write_text(yaml.dump({
        "languages": [
            {"iso_code": "fr", "name": "French"},
            {"iso_code": "de", "name": "German"}
        ]
    }))

    report = check_language_coverage(str(registry), str(languages))

    assert report.total_languages == 2
    assert len(report.covered_languages) == 2
    assert len(report.missing_languages) == 0
    assert report.coverage_percentage == 100.0
    # German should have both models
    assert len(report.models_per_language["de"]) == 2
    assert "m2m100" in report.models_per_language["de"]
    assert "opus_en_de" in report.models_per_language["de"]
    # French should only have multilingual
    assert len(report.models_per_language["fr"]) == 1
    assert "m2m100" in report.models_per_language["fr"]
