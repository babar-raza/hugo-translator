"""
Unit tests for ModelStore and ModelManifest.

Tests:
- Path resolution for different model types
- Model presence checking
- Manifest CRUD operations
- Download plan generation
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.model_runtime.model_store import (
    ModelManifest,
    ModelNotFoundError,
    ModelStore,
)
from src.model_runtime.registry import ModelInfo, ModelRegistry


@pytest.fixture
def temp_models_dir(tmp_path):
    """Create temporary models directory."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "opus").mkdir()
    (models_dir / "ct2").mkdir()
    return models_dir


@pytest.fixture
def mock_registry():
    """Create mock registry with test models."""
    registry = Mock(spec=ModelRegistry)

    # Multilingual model
    m2m100 = ModelInfo(
        model_id="m2m100_418m",
        name="M2M100 418M",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=1600,
        min_ram_gb=4.0,
        optimal_device="cuda",
        hf_model_id="facebook/m2m100_418M",
        local_path=Path("m2m100_418M"),
    )

    # Opus bilingual model
    opus_en_fr = ModelInfo(
        model_id="opus_en_fr",
        name="Opus EN-FR",
        backend="opus",
        supported_pairs=[("en", "fr"), ("fr", "en")],
        model_size_mb=300,
        min_ram_gb=1.0,
        optimal_device="cpu",
        hf_model_id="Helsinki-NLP/opus-mt-en-fr",
        local_path=Path("opus/opus-mt-en-fr"),
    )

    # CT2 model
    ct2_model = ModelInfo(
        model_id="m2m100_418m_ct2_int8",
        name="M2M100 CT2 INT8",
        backend="ctranslate2",
        supported_pairs="all",
        model_size_mb=250,
        min_ram_gb=1.5,
        optimal_device="cpu",
        local_path=Path("ct2/m2m100_418m_int8"),
    )

    registry.models = {
        "m2m100_418m": m2m100,
        "opus_en_fr": opus_en_fr,
        "m2m100_418m_ct2_int8": ct2_model,
    }
    registry.get_model = lambda model_id: registry.models[model_id]
    registry.list_models = lambda: list(registry.models.values())
    registry.__contains__ = lambda self, model_id: model_id in registry.models

    return registry


class TestModelManifest:
    """Tests for ModelManifest."""

    def test_create_empty_manifest(self, tmp_path):
        """Test creating new empty manifest."""
        manifest_path = tmp_path / "manifest.json"
        manifest = ModelManifest(manifest_path)

        assert manifest._data["version"] == "1.0"
        assert manifest._data["models"] == []
        assert "last_updated" in manifest._data

    def test_save_and_load_manifest(self, tmp_path):
        """Test saving and loading manifest."""
        manifest_path = tmp_path / "manifest.json"
        manifest = ModelManifest(manifest_path)

        # Add entry
        manifest.add_or_update_model(
            model_id="test_model",
            local_path=Path("models/test"),
            download_source="huggingface:test/model",
            backend="huggingface",
            size_mb=100.5,
            files=[{"name": "config.json", "size_bytes": 1024, "sha256": "abc123"}],
        )

        # Save
        manifest.save()
        assert manifest_path.exists()

        # Load in new instance
        manifest2 = ModelManifest(manifest_path)
        entry = manifest2.get_model_entry("test_model")

        assert entry is not None
        assert entry["model_id"] == "test_model"
        assert entry["size_mb"] == 100.5
        assert len(entry["files"]) == 1

    def test_add_or_update_model(self, tmp_path):
        """Test adding and updating model entries."""
        manifest = ModelManifest(tmp_path / "manifest.json")

        # Add model
        manifest.add_or_update_model(
            model_id="model1",
            local_path=Path("models/model1"),
            download_source="huggingface:org/model1",
            backend="huggingface",
            size_mb=200.0,
            files=[],
        )

        assert len(manifest._data["models"]) == 1

        # Update same model
        manifest.add_or_update_model(
            model_id="model1",
            local_path=Path("models/model1_v2"),
            download_source="huggingface:org/model1",
            backend="huggingface",
            size_mb=250.0,
            files=[],
        )

        # Should replace, not duplicate
        assert len(manifest._data["models"]) == 1
        assert manifest._data["models"][0]["size_mb"] == 250.0

    def test_remove_model(self, tmp_path):
        """Test removing model from manifest."""
        manifest = ModelManifest(tmp_path / "manifest.json")

        manifest.add_or_update_model(
            "model1", Path("models/model1"), "hf:org/model1", "hf", 100, []
        )
        manifest.add_or_update_model(
            "model2", Path("models/model2"), "hf:org/model2", "hf", 200, []
        )

        assert len(manifest._data["models"]) == 2

        manifest.remove_model("model1")

        assert len(manifest._data["models"]) == 1
        assert manifest.get_model_entry("model1") is None
        assert manifest.get_model_entry("model2") is not None


class TestModelStore:
    """Tests for ModelStore."""

    def test_resolve_local_path_multilingual(self, mock_registry, temp_models_dir):
        """Test path resolution for multilingual models."""
        store = ModelStore(mock_registry, temp_models_dir)

        model_info = mock_registry.get_model("m2m100_418m")
        path = store.resolve_local_path(model_info)

        assert path == temp_models_dir / "m2m100_418M"

    def test_resolve_local_path_opus(self, mock_registry, temp_models_dir):
        """Test path resolution for Opus models."""
        store = ModelStore(mock_registry, temp_models_dir)

        model_info = mock_registry.get_model("opus_en_fr")
        path = store.resolve_local_path(model_info)

        assert path == temp_models_dir / "opus" / "opus-mt-en-fr"

    def test_resolve_local_path_ct2(self, mock_registry, temp_models_dir):
        """Test path resolution for CT2 models."""
        store = ModelStore(mock_registry, temp_models_dir)

        model_info = mock_registry.get_model("m2m100_418m_ct2_int8")
        path = store.resolve_local_path(model_info)

        assert path == temp_models_dir / "ct2" / "m2m100_418m_int8"

    def test_check_model_present_not_exists(self, mock_registry, temp_models_dir):
        """Test checking non-existent model."""
        store = ModelStore(mock_registry, temp_models_dir)

        model_info = mock_registry.get_model("m2m100_418m")
        present = store.check_model_present(model_info)

        assert present is False

    def test_check_model_present_hf_model(self, mock_registry, temp_models_dir):
        """Test checking HF model presence (requires config.json)."""
        store = ModelStore(mock_registry, temp_models_dir)

        # Create model directory with config.json
        model_path = temp_models_dir / "m2m100_418M"
        model_path.mkdir()
        (model_path / "config.json").write_text("{}")

        model_info = mock_registry.get_model("m2m100_418m")
        present = store.check_model_present(model_info)

        assert present is True

    def test_check_model_present_ct2_model(self, mock_registry, temp_models_dir):
        """Test checking CT2 model presence (requires model.bin)."""
        store = ModelStore(mock_registry, temp_models_dir)

        # Create CT2 model directory with model.bin
        model_path = temp_models_dir / "ct2" / "m2m100_418m_int8"
        model_path.mkdir(parents=True)
        (model_path / "model.bin").write_bytes(b"fake model data")

        model_info = mock_registry.get_model("m2m100_418m_ct2_int8")
        present = store.check_model_present(model_info)

        assert present is True

    def test_ensure_model_downloaded_already_present(self, mock_registry, temp_models_dir):
        """Test ensuring model when already downloaded."""
        store = ModelStore(mock_registry, temp_models_dir, allow_downloads=False)

        # Setup model as present
        model_path = temp_models_dir / "m2m100_418M"
        model_path.mkdir()
        (model_path / "config.json").write_text("{}")

        # Should return path without attempting download
        result_path = store.ensure_model_downloaded("m2m100_418m")

        assert result_path == model_path

    def test_ensure_model_downloaded_not_present_downloads_disabled(
        self, mock_registry, temp_models_dir
    ):
        """Test ensuring model when not present and downloads disabled."""
        store = ModelStore(mock_registry, temp_models_dir, allow_downloads=False)

        # Should raise ModelNotFoundError
        with pytest.raises(ModelNotFoundError) as exc_info:
            store.ensure_model_downloaded("m2m100_418m")

        assert "downloads are disabled" in str(exc_info.value).lower()

    @patch("huggingface_hub.snapshot_download")
    def test_download_model_success(self, mock_snapshot_download, mock_registry, temp_models_dir):
        """Test successful model download."""
        store = ModelStore(mock_registry, temp_models_dir, allow_downloads=True)

        # Mock download to create files
        downloaded_path = temp_models_dir / "m2m100_418M"
        downloaded_path.mkdir()
        (downloaded_path / "config.json").write_text("{}")
        mock_snapshot_download.return_value = str(downloaded_path)

        # Download model
        model_info = mock_registry.get_model("m2m100_418m")
        result_path = store._download_model(model_info, downloaded_path)

        assert result_path == downloaded_path
        mock_snapshot_download.assert_called_once()

        # Check manifest was updated
        entry = store.manifest.get_model_entry("m2m100_418m")
        assert entry is not None
        assert entry["verified"] is True

    def test_get_download_plan(self, mock_registry, temp_models_dir):
        """Test generating download plan."""
        store = ModelStore(mock_registry, temp_models_dir)

        # Mark one model as present
        model_path = temp_models_dir / "opus" / "opus-mt-en-fr"
        model_path.mkdir(parents=True)
        (model_path / "config.json").write_text("{}")

        plan = store.get_download_plan()

        assert plan["total_models"] == 3
        assert "opus_en_fr" in plan["already_present"]
        assert "m2m100_418m" in plan["needs_download"]
        assert "m2m100_418m_ct2_int8" in plan["needs_download"]
        assert plan["already_present_count"] == 1
        assert plan["needs_download_count"] == 2
        assert plan["total_size_mb"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
