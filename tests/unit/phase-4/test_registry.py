"""
Unit tests for Model Registry.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.model_runtime import HardwareInfo, ModelInfo, ModelRegistry


@pytest.fixture
def sample_registry_yaml():
    """Create sample registry YAML content."""
    return """
models:
  - model_id: test_model_small
    name: "Test Model Small"
    backend: huggingface
    supported_pairs: all
    model_size_mb: 300
    min_ram_gb: 2
    optimal_device: cpu
    parameters: 100000000
    license: MIT
    hf_model_id: test/model-small
    description: "Small test model"

  - model_id: test_model_large
    name: "Test Model Large"
    backend: ctranslate2
    supported_pairs: all
    model_size_mb: 2000
    min_ram_gb: 8
    optimal_device: cuda
    parameters: 1000000000
    license: Apache-2.0
    description: "Large test model"

  - model_id: test_en_fr
    name: "Test English-French"
    backend: huggingface
    supported_pairs:
      - ["en", "fr"]
      - ["fr", "en"]
    model_size_mb: 200
    min_ram_gb: 1
    optimal_device: cpu
    parameters: 50000000
    license: CC-BY-4.0
    hf_model_id: test/en-fr
"""


@pytest.fixture
def temp_registry_file(sample_registry_yaml):
    """Create temporary registry file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(sample_registry_yaml)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def registry(temp_registry_file):
    """Create ModelRegistry instance."""
    return ModelRegistry(temp_registry_file)


class TestModelInfo:
    """Test ModelInfo dataclass."""

    def test_model_info_creation(self):
        """Test creating ModelInfo."""
        info = ModelInfo(
            model_id="test_model",
            name="Test Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=500,
            min_ram_gb=4,
            optimal_device="cuda",
            parameters=100000000,
            license="MIT",
        )

        assert info.model_id == "test_model"
        assert info.name == "Test Model"
        assert info.backend == "huggingface"
        assert info.supported_pairs == "all"

    def test_model_info_to_dict(self):
        """Test ModelInfo serialization."""
        info = ModelInfo(
            model_id="test_model",
            name="Test Model",
            backend="huggingface",
            supported_pairs=[("en", "fr")],
            model_size_mb=500,
            min_ram_gb=4,
            optimal_device="cuda",
        )

        info_dict = info.to_dict()
        assert isinstance(info_dict, dict)
        assert info_dict["model_id"] == "test_model"
        assert info_dict["backend"] == "huggingface"

    def test_model_info_from_dict(self):
        """Test ModelInfo deserialization."""
        data = {
            "model_id": "test_model",
            "name": "Test Model",
            "backend": "huggingface",
            "supported_pairs": "all",
            "model_size_mb": 500,
            "min_ram_gb": 4,
            "optimal_device": "cuda",
            "parameters": 100000000,
            "license": "MIT",
        }

        info = ModelInfo.from_dict(data)
        assert info.model_id == "test_model"
        assert info.parameters == 100000000


class TestModelRegistry:
    """Test ModelRegistry functionality."""

    def test_registry_initialization(self, temp_registry_file):
        """Test creating ModelRegistry."""
        registry = ModelRegistry(temp_registry_file)
        assert registry is not None
        assert len(registry) > 0

    def test_registry_loads_models(self, registry):
        """Test that registry loads models from YAML."""
        assert len(registry) == 3
        assert "test_model_small" in registry
        assert "test_model_large" in registry
        assert "test_en_fr" in registry

    def test_registry_file_not_found(self):
        """Test error when registry file not found."""
        with pytest.raises(FileNotFoundError):
            ModelRegistry("nonexistent.yaml")

    def test_list_models_all(self, registry):
        """Test listing all models."""
        models = registry.list_models()
        assert len(models) == 3

    def test_list_models_filter_by_lang_pair(self, registry):
        """Test filtering models by language pair."""
        # All models support en->fr (all or specific)
        models = registry.list_models(lang_pair=("en", "fr"))
        assert len(models) >= 1

        # Only specialized model supports en->fr specifically
        specialized = [m for m in models if m.model_id == "test_en_fr"]
        assert len(specialized) == 1

    def test_list_models_unsupported_pair(self, registry):
        """Test filtering with unsupported language pair."""
        models = registry.list_models(lang_pair=("zh", "ja"))
        # Only models with "all" support should match
        assert all(m.supported_pairs == "all" for m in models)

    def test_get_model(self, registry):
        """Test getting specific model."""
        model = registry.get_model("test_model_small")
        assert model.model_id == "test_model_small"
        assert model.name == "Test Model Small"
        assert model.backend == "huggingface"

    def test_get_model_not_found(self, registry):
        """Test error when model not found."""
        with pytest.raises(KeyError):
            registry.get_model("nonexistent_model")

    def test_register_model(self, registry):
        """Test adding new model dynamically."""
        new_model = ModelInfo(
            model_id="new_model",
            name="New Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=400,
            min_ram_gb=3,
            optimal_device="cpu",
        )

        initial_count = len(registry)
        registry.register_model(new_model)

        assert len(registry) == initial_count + 1
        assert "new_model" in registry
        assert registry.get_model("new_model").name == "New Model"

    def test_unregister_model(self, registry):
        """Test removing model from registry."""
        initial_count = len(registry)
        registry.unregister_model("test_model_small")

        assert len(registry) == initial_count - 1
        assert "test_model_small" not in registry

    def test_unregister_model_not_found(self, registry):
        """Test error when unregistering nonexistent model."""
        with pytest.raises(KeyError):
            registry.unregister_model("nonexistent_model")


class TestModelRecommendation:
    """Test model recommendation logic."""

    def test_recommend_model_cpu(self, registry):
        """Test recommendation for CPU hardware."""
        hardware = HardwareInfo(
            cpu_count=4,
            total_ram_gb=8,
            has_cuda=False,
            has_mps=False,
            recommended_device="cpu",
        )

        model = registry.recommend_model("en", "fr", hardware)
        assert model is not None
        # Should recommend smaller model for CPU
        assert model.model_size_mb <= 2000

    def test_recommend_model_gpu(self, registry):
        """Test recommendation for GPU hardware."""
        hardware = HardwareInfo(
            cpu_count=8,
            total_ram_gb=16,
            has_cuda=True,
            cuda_devices=[{"total_memory_gb": 8}],
            recommended_device="cuda",
        )

        model = registry.recommend_model("en", "fr", hardware)
        assert model is not None

    def test_recommend_model_prefer_quality(self, registry):
        """Test recommendation preferring quality."""
        hardware = HardwareInfo(
            cpu_count=8,
            total_ram_gb=16,
            has_cuda=True,
            recommended_device="cuda",
        )

        model = registry.recommend_model("en", "fr", hardware, prefer_quality=True)
        assert model is not None
        # With prefer_quality, should lean towards larger models
        # (if hardware supports it)

    def test_recommend_model_insufficient_ram(self, registry):
        """Test recommendation with insufficient RAM."""
        hardware = HardwareInfo(
            cpu_count=2,
            total_ram_gb=1.5,  # Very low RAM
            has_cuda=False,
            recommended_device="cpu",
        )

        model = registry.recommend_model("en", "fr", hardware)
        # Should return smallest model even if not ideal
        assert model is not None

    def test_recommend_model_unsupported_pair(self, registry):
        """Test recommendation for unsupported language pair."""
        hardware = HardwareInfo(
            cpu_count=4,
            total_ram_gb=8,
            has_cuda=False,
            recommended_device="cpu",
        )

        # Language pair not in specialized models
        with pytest.raises(ValueError):
            # Remove all "all" models temporarily to test
            all_models = [m for m in registry.models.values() if m.supported_pairs == "all"]
            for m in all_models:
                registry.unregister_model(m.model_id)

            registry.recommend_model("aa", "bb", hardware)


class TestRegistryPersistence:
    """Test registry save/load functionality."""

    def test_save_registry(self, registry):
        """Test saving registry to file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = Path(f.name)

        try:
            registry.save_registry(temp_path)
            assert temp_path.exists()

            # Verify content
            with open(temp_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            assert "models" in data
            assert len(data["models"]) == len(registry)

        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_save_and_reload(self, registry):
        """Test save and reload cycle."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = Path(f.name)

        try:
            # Add a new model
            new_model = ModelInfo(
                model_id="temp_model",
                name="Temp Model",
                backend="huggingface",
                supported_pairs="all",
                model_size_mb=100,
                min_ram_gb=1,
                optimal_device="cpu",
            )
            registry.register_model(new_model)

            # Save
            registry.save_registry(temp_path)

            # Reload
            registry2 = ModelRegistry(temp_path)
            assert len(registry2) == len(registry)
            assert "temp_model" in registry2

        finally:
            if temp_path.exists():
                temp_path.unlink()


class TestDeviceAwareSelection:
    """Test device-aware model selection (CT2 automation)."""

    def test_cuda_can_select_cpu_optimized_models(self, registry):
        """Test that CUDA device can select CPU-optimized models (e.g., CT2 int8)."""
        # Add a CPU-optimized CT2 model
        ct2_model = ModelInfo(
            model_id="m2m100_418m__int8_ct2",
            name="M2M100 418M CT2 INT8",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=480,
            min_ram_gb=2,
            optimal_device="cpu",  # Optimized for CPU
            parameters=418000000,
        )
        registry.register_model(ct2_model)

        # CUDA hardware
        hardware_cuda = HardwareInfo(
            cpu_count=8,
            total_ram_gb=16,
            has_cuda=True,
            cuda_devices=[{"total_memory_gb": 8}],
            recommended_device="cuda",
        )

        # Should be able to select CT2 model even though optimal_device is CPU
        model = registry.recommend_model("en", "fr", hardware_cuda)
        assert model is not None
        # CT2 should be eligible (not filtered out by device mismatch)

    def test_optimal_device_affects_scoring_not_filtering(self, registry):
        """Test that optimal_device affects scoring but doesn't exclude models."""
        # Add models with different optimal devices
        cpu_model = ModelInfo(
            model_id="model_cpu",
            name="CPU Model",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=500,
            min_ram_gb=2,
            optimal_device="cpu",
            parameters=400000000,
        )

        cuda_model = ModelInfo(
            model_id="model_cuda",
            name="CUDA Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=1500,
            min_ram_gb=4,
            optimal_device="cuda",
            parameters=600000000,
        )

        registry.register_model(cpu_model)
        registry.register_model(cuda_model)

        # CUDA hardware - should prefer CUDA-optimized model (higher score)
        hardware_cuda = HardwareInfo(
            cpu_count=8,
            total_ram_gb=16,
            has_cuda=True,
            recommended_device="cuda",
        )

        model = registry.recommend_model("zh", "ja", hardware_cuda)
        # Should prefer model_cuda due to device match bonus
        assert model.optimal_device == "cuda"

    def test_ram_filtering_still_applies(self, registry):
        """Test that RAM requirements still filter models."""
        # Add high-RAM model
        high_ram_model = ModelInfo(
            model_id="large_model",
            name="Large Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=5000,
            min_ram_gb=32,  # Requires 32GB RAM
            optimal_device="cuda",
            parameters=2000000000,
        )
        registry.register_model(high_ram_model)

        # Low RAM hardware
        hardware_low_ram = HardwareInfo(
            cpu_count=8,
            total_ram_gb=8,  # Only 8GB RAM
            has_cuda=True,
            recommended_device="cuda",
        )

        model = registry.recommend_model("en", "fr", hardware_low_ram)
        # Should NOT select high_ram_model (RAM requirement not met)
        assert model.min_ram_gb <= 8

    def test_ct2_models_eligible_for_benchmark(self, registry):
        """Test that CT2 models can be selected for CUDA benchmarking."""
        # Add CT2 model optimized for CPU but runnable on CUDA
        ct2_model = ModelInfo(
            model_id="nllb__int8_ct2",
            name="NLLB CT2 INT8",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=600,
            min_ram_gb=3,
            optimal_device="cpu",
            parameters=600000000,
        )
        registry.register_model(ct2_model)

        # CUDA hardware for benchmarking
        hardware_cuda = HardwareInfo(
            cpu_count=8,
            total_ram_gb=16,
            has_cuda=True,
            recommended_device="cuda",
        )

        # CT2 model should be eligible for selection on CUDA
        # (even though optimal_device is CPU)
        models = registry.list_models()
        ct2_models = [m for m in models if m.backend == "ctranslate2"]

        # Verify CT2 models can be scored for CUDA hardware
        for model in ct2_models:
            if model.min_ram_gb <= hardware_cuda.total_ram_gb:
                score = registry._score_model(model, hardware_cuda, prefer_quality=False)
                assert score is not None  # Model can be scored
                # Device mismatch results in lower score, but not exclusion


class TestRealRegistry:
    """Test with actual registry file."""

    def test_load_real_registry(self):
        """Test loading the actual model_registry.yaml."""
        registry_path = Path("config/model_registry.yaml")

        if not registry_path.exists():
            pytest.skip("Real registry file not found")

        registry = ModelRegistry(registry_path)
        assert len(registry) > 0

        # Check that we have some expected models
        models = registry.list_models()
        model_ids = [m.model_id for m in models]

        # Should have M2M100 models
        assert any("m2m100" in mid for mid in model_ids)

    def test_real_registry_recommendation(self):
        """Test recommendation with real registry."""
        registry_path = Path("config/model_registry.yaml")

        if not registry_path.exists():
            pytest.skip("Real registry file not found")

        registry = ModelRegistry(registry_path)

        # Test CPU recommendation
        hardware_cpu = HardwareInfo(
            cpu_count=4,
            total_ram_gb=8,
            has_cuda=False,
            recommended_device="cpu",
        )

        model = registry.recommend_model("en", "fr", hardware_cpu)
        assert model is not None
        print(f"CPU recommendation: {model.name}")

        # Test GPU recommendation
        hardware_gpu = HardwareInfo(
            cpu_count=8,
            total_ram_gb=16,
            has_cuda=True,
            recommended_device="cuda",
        )

        model_gpu = registry.recommend_model("en", "fr", hardware_gpu)
        assert model_gpu is not None
        print(f"GPU recommendation: {model_gpu.name}")
