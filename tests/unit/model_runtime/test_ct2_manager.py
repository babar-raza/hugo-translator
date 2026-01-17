"""
Unit tests for CT2 Conversion Manager.

Tests CT2 conversion workflow including:
- Path conventions
- Registry and manifest updates
- Model validation
- Conversion planning
"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.model_runtime.ct2_manager import CT2ConversionManager, CT2ConversionResult
from src.model_runtime.registry import ModelInfo, ModelRegistry
from src.model_runtime.model_store import ModelManifest


@pytest.fixture
def temp_models_dir():
    """Create temporary models directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        models_dir = Path(tmpdir) / "models"
        models_dir.mkdir(parents=True)
        yield models_dir


@pytest.fixture
def sample_model_info():
    """Create sample source model info."""
    return ModelInfo(
        model_id="m2m100_418m",
        name="M2M100 418M",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=1600,
        min_ram_gb=4,
        optimal_device="cuda",
        parameters=418000000,
        license="MIT",
        hf_model_id="facebook/m2m100_418M",
        description="Multilingual model",
    )


@pytest.fixture
def mock_registry(sample_model_info):
    """Create mock registry."""
    registry = Mock(spec=ModelRegistry)
    registry.get_model = Mock(return_value=sample_model_info)
    registry.list_models = Mock(return_value=[sample_model_info])
    registry.register_model = Mock()
    registry.models = {sample_model_info.model_id: sample_model_info}
    return registry


@pytest.fixture
def mock_manifest(temp_models_dir):
    """Create mock manifest."""
    manifest = Mock(spec=ModelManifest)
    manifest.manifest_path = temp_models_dir / "model_manifest.json"
    manifest.get_model_entry = Mock(return_value=None)
    manifest.add_or_update_model = Mock()
    manifest.save = Mock()
    return manifest


@pytest.fixture
def ct2_manager(mock_registry, temp_models_dir, mock_manifest):
    """Create CT2ConversionManager instance."""
    manager = CT2ConversionManager(
        registry=mock_registry,
        models_dir=temp_models_dir,
        manifest_path=temp_models_dir / "model_manifest.json",
    )
    manager.manifest = mock_manifest
    return manager


class TestCT2PathConventions:
    """Test CT2 path convention methods."""

    def test_get_ct2_path(self, ct2_manager):
        """Test CT2 path generation follows convention."""
        path = ct2_manager.get_ct2_path("m2m100_418m", "int8")

        assert path.name == "m2m100_418m__int8"
        assert "ct2" in path.parts
        assert path.parent == ct2_manager.ct2_dir

    def test_get_ct2_model_id(self, ct2_manager):
        """Test CT2 model ID generation."""
        model_id = ct2_manager.get_ct2_model_id("m2m100_418m", "int8")

        assert model_id == "m2m100_418m__int8_ct2"
        assert "__int8" in model_id
        assert model_id.endswith("_ct2")

    def test_path_conventions_for_different_quantizations(self, ct2_manager):
        """Test path conventions for different quantizations."""
        int8_path = ct2_manager.get_ct2_path("test_model", "int8")
        float16_path = ct2_manager.get_ct2_path("test_model", "float16")

        assert int8_path != float16_path
        assert "int8" in int8_path.name
        assert "float16" in float16_path.name


class TestCT2ConversionManager:
    """Test CT2ConversionManager core functionality."""

    @patch("src.model_runtime.ct2_manager.CT2ConversionPipeline")
    def test_ensure_ct2_already_exists(self, mock_pipeline_class, ct2_manager, temp_models_dir):
        """Test ensure_ct2 when model already exists and is valid."""
        # Setup
        ct2_path = ct2_manager.get_ct2_path("m2m100_418m", "int8")
        ct2_path.mkdir(parents=True, exist_ok=True)
        (ct2_path / "model.bin").touch()

        mock_pipeline = Mock()
        mock_pipeline.validate_ct2_model = Mock(return_value=True)
        ct2_manager.pipeline = mock_pipeline

        # Execute
        result = ct2_manager.ensure_ct2("m2m100_418m", "int8", "cpu", force=False)

        # Verify
        assert result.success is True
        assert result.model_id == "m2m100_418m__int8_ct2"
        assert result.output_path == ct2_path
        mock_pipeline.convert_model.assert_not_called()

    @patch("src.model_runtime.ct2_manager.CT2ConversionPipeline")
    def test_ensure_ct2_source_model_not_found(self, mock_pipeline_class, ct2_manager):
        """Test ensure_ct2 when source model not in registry."""
        # Setup
        ct2_manager.registry.get_model = Mock(return_value=None)

        # Execute
        result = ct2_manager.ensure_ct2("nonexistent_model", "int8", "cpu")

        # Verify
        assert result.success is False
        assert "not found in registry" in result.error

    @patch("src.model_runtime.ct2_manager.CT2ConversionPipeline")
    def test_ensure_ct2_successful_conversion(
        self, mock_pipeline_class, ct2_manager, temp_models_dir, sample_model_info
    ):
        """Test successful CT2 conversion."""
        # Setup source model directory
        source_path = temp_models_dir / "m2m100_418M"
        source_path.mkdir(parents=True)
        (source_path / "pytorch_model.bin").touch()

        # Mock manifest to return source path
        ct2_manager.manifest.get_model_entry = Mock(
            return_value={"local_path": str(source_path)}
        )

        # Mock pipeline
        mock_pipeline = Mock()
        mock_pipeline.convert_model = Mock(return_value=True)
        mock_pipeline.validate_ct2_model = Mock(return_value=True)
        ct2_manager.pipeline = mock_pipeline

        # Execute
        result = ct2_manager.ensure_ct2("m2m100_418m", "int8", "cpu")

        # Verify
        assert result.success is True
        assert result.quantization == "int8"
        mock_pipeline.convert_model.assert_called_once()
        ct2_manager.manifest.add_or_update_model.assert_called_once()
        ct2_manager.registry.register_model.assert_called_once()

    def test_get_source_model_path_from_manifest(self, ct2_manager, sample_model_info, temp_models_dir):
        """Test getting source model path from manifest."""
        # Setup
        source_path = temp_models_dir / "test_model"
        source_path.mkdir(parents=True)

        ct2_manager.manifest.get_model_entry = Mock(
            return_value={"local_path": str(source_path)}
        )

        # Execute
        result = ct2_manager._get_source_model_path(sample_model_info)

        # Verify
        assert result == source_path

    def test_get_source_model_path_from_local_path(self, ct2_manager, sample_model_info, temp_models_dir):
        """Test getting source model path from registry local_path."""
        # Setup
        source_path = temp_models_dir / "test_model"
        source_path.mkdir(parents=True)
        sample_model_info.local_path = source_path

        ct2_manager.manifest.get_model_entry = Mock(return_value=None)

        # Execute
        result = ct2_manager._get_source_model_path(sample_model_info)

        # Verify
        assert result == source_path


class TestCT2RegistryUpdates:
    """Test registry update functionality."""

    def test_update_registry_creates_ct2_entry(self, ct2_manager, sample_model_info, temp_models_dir):
        """Test that registry is updated with CT2 model entry."""
        # Setup
        ct2_path = temp_models_dir / "ct2" / "test__int8"
        ct2_path.mkdir(parents=True)

        # Execute
        ct2_manager._update_registry(
            ct2_model_id="test__int8_ct2",
            ct2_path=ct2_path,
            source_model=sample_model_info,
            size_mb=500.0,
            quantization="int8",
            device_target="cpu",
        )

        # Verify
        ct2_manager.registry.register_model.assert_called_once()
        call_args = ct2_manager.registry.register_model.call_args[0][0]

        assert call_args.model_id == "test__int8_ct2"
        assert call_args.backend == "ctranslate2"
        assert call_args.optimal_device == "cpu"
        assert call_args.supported_pairs == sample_model_info.supported_pairs

    def test_update_registry_inherits_language_pairs(self, ct2_manager, temp_models_dir):
        """Test that CT2 model inherits language pairs from source."""
        # Setup
        source_model = ModelInfo(
            model_id="opus_en_fr",
            name="Opus EN-FR",
            backend="opus",
            supported_pairs=[("en", "fr"), ("fr", "en")],
            model_size_mb=200,
            min_ram_gb=2,
            optimal_device="cpu",
        )

        ct2_path = temp_models_dir / "ct2" / "opus_en_fr__int8"
        ct2_path.mkdir(parents=True)

        # Execute
        ct2_manager._update_registry(
            ct2_model_id="opus_en_fr__int8_ct2",
            ct2_path=ct2_path,
            source_model=source_model,
            size_mb=60.0,
            quantization="int8",
            device_target="cpu",
        )

        # Verify
        call_args = ct2_manager.registry.register_model.call_args[0][0]
        assert call_args.supported_pairs == [("en", "fr"), ("fr", "en")]

    def test_update_registry_reduces_ram_requirement(self, ct2_manager, sample_model_info, temp_models_dir):
        """Test that CT2 model has reduced RAM requirement (60% of original)."""
        # Setup
        ct2_path = temp_models_dir / "ct2" / "test__int8"
        ct2_path.mkdir(parents=True)

        original_ram = sample_model_info.min_ram_gb

        # Execute
        ct2_manager._update_registry(
            ct2_model_id="test__int8_ct2",
            ct2_path=ct2_path,
            source_model=sample_model_info,
            size_mb=500.0,
            quantization="int8",
            device_target="cpu",
        )

        # Verify
        call_args = ct2_manager.registry.register_model.call_args[0][0]
        assert call_args.min_ram_gb == original_ram * 0.6


class TestCT2ManifestUpdates:
    """Test manifest update functionality."""

    def test_update_manifest_adds_entry(self, ct2_manager, sample_model_info, temp_models_dir):
        """Test that manifest is updated with CT2 model entry."""
        # Setup
        ct2_path = temp_models_dir / "ct2" / "test__int8"
        ct2_path.mkdir(parents=True)
        (ct2_path / "model.bin").write_bytes(b"fake model data")
        (ct2_path / "config.json").write_bytes(b"{}")

        # Execute
        ct2_manager._update_manifest(
            ct2_model_id="test__int8_ct2",
            ct2_path=ct2_path,
            source_model=sample_model_info,
            size_mb=500.0,
            quantization="int8",
        )

        # Verify
        ct2_manager.manifest.add_or_update_model.assert_called_once()
        call_kwargs = ct2_manager.manifest.add_or_update_model.call_args[1]

        assert call_kwargs["model_id"] == "test__int8_ct2"
        assert call_kwargs["backend"] == "ctranslate2"
        assert "ct2_conversion:" in call_kwargs["download_source"]
        assert len(call_kwargs["files"]) == 2  # model.bin + config.json

        ct2_manager.manifest.save.assert_called_once()


class TestCT2ListingAndPlanning:
    """Test CT2 model listing and conversion planning."""

    def test_list_ct2_models(self, ct2_manager):
        """Test listing CT2 models."""
        # Setup
        ct2_manager.pipeline.validate_ct2_model = Mock(return_value=False)

        # Execute
        ct2_models = ct2_manager.list_ct2_models()

        # Verify
        assert len(ct2_models) > 0
        for model_id, exists, path in ct2_models:
            assert "__int8_ct2" in model_id or "__float16_ct2" in model_id

    def test_plan_conversion(self, ct2_manager, sample_model_info, temp_models_dir):
        """Test conversion planning."""
        # Setup source model
        source_path = temp_models_dir / "m2m100_418M"
        source_path.mkdir(parents=True)
        ct2_manager.manifest.get_model_entry = Mock(
            return_value={"local_path": str(source_path)}
        )

        # Execute
        plans = ct2_manager.plan_conversion(["m2m100_418m"], quantization="int8")

        # Verify
        assert len(plans) == 1
        plan = plans[0]
        assert plan["model_id"] == "m2m100_418m"
        assert plan["status"] == "needs_conversion"
        assert plan["quantization"] == "int8"
        assert "estimated_size_mb" in plan

    def test_plan_conversion_missing_source(self, ct2_manager):
        """Test conversion planning when source model not downloaded."""
        # Setup
        ct2_manager.manifest.get_model_entry = Mock(return_value=None)

        # Execute
        plans = ct2_manager.plan_conversion(["m2m100_418m"], quantization="int8")

        # Verify
        assert len(plans) == 1
        plan = plans[0]
        assert plan["status"] == "error"
        assert "not downloaded" in plan["error"]


class TestCT2ConversionResult:
    """Test CT2ConversionResult dataclass."""

    def test_conversion_result_success(self):
        """Test successful conversion result."""
        result = CT2ConversionResult(
            model_id="m2m100_418m__int8_ct2",
            source_model_id="m2m100_418m",
            output_path=Path("/models/ct2/m2m100_418m__int8"),
            quantization="int8",
            size_mb=480.0,
            success=True,
        )

        assert result.success is True
        assert result.error is None
        assert result.quantization == "int8"

    def test_conversion_result_failure(self):
        """Test failed conversion result."""
        result = CT2ConversionResult(
            model_id="m2m100_418m__int8_ct2",
            source_model_id="m2m100_418m",
            output_path=Path("/models/ct2/m2m100_418m__int8"),
            quantization="int8",
            size_mb=0.0,
            success=False,
            error="Conversion failed",
        )

        assert result.success is False
        assert result.error == "Conversion failed"
