"""
Unit tests for GPU optimizer.

Tests batch size calculation based on VRAM, model size, and precision.
"""
from unittest.mock import Mock, patch

import pytest

from src.model_runtime.gpu_optimizer import GPUConfig, GPUOptimizer


class TestGPUOptimizer:
    """Test suite for GPUOptimizer."""

    def test_infer_model_size_600m(self):
        """Test model size inference for 600M models."""
        optimizer = GPUOptimizer()

        # Various 600M naming patterns
        assert optimizer._infer_model_size("facebook/nllb-200-distilled-600M") == "600M"
        assert optimizer._infer_model_size("nllb-200-600M") == "600M"
        assert optimizer._infer_model_size("model-600m") == "600M"

    def test_infer_model_size_1_3b(self):
        """Test model size inference for 1.3B models."""
        optimizer = GPUOptimizer()

        assert optimizer._infer_model_size("facebook/nllb-200-1.3B") == "1.3B"
        assert optimizer._infer_model_size("nllb-200-13B") == "1.3B"
        assert optimizer._infer_model_size("model-1.3b") == "1.3B"

    def test_infer_model_size_3_3b(self):
        """Test model size inference for 3.3B models."""
        optimizer = GPUOptimizer()

        assert optimizer._infer_model_size("facebook/nllb-200-3.3B") == "3.3B"
        assert optimizer._infer_model_size("nllb-200-33B") == "3.3B"
        assert optimizer._infer_model_size("model-3.3b") == "3.3B"

    def test_infer_model_size_unknown_defaults_to_largest(self):
        """Test that unknown model names default to largest (3.3B)."""
        optimizer = GPUOptimizer()

        assert optimizer._infer_model_size("some-unknown-model") == "3.3B"
        assert optimizer._infer_model_size(None) == "3.3B"

    def test_clamp_batch_size_within_bounds(self):
        """Test batch size clamping within valid range."""
        optimizer = GPUOptimizer()

        assert optimizer._clamp_batch_size(10) == 10
        assert optimizer._clamp_batch_size(32) == 32

    def test_clamp_batch_size_below_minimum(self):
        """Test batch size clamping when below minimum."""
        optimizer = GPUOptimizer()

        assert optimizer._clamp_batch_size(0) == optimizer.MIN_BATCH_SIZE
        assert optimizer._clamp_batch_size(-5) == optimizer.MIN_BATCH_SIZE

    def test_clamp_batch_size_above_maximum(self):
        """Test batch size clamping when above maximum."""
        optimizer = GPUOptimizer()

        assert optimizer._clamp_batch_size(100) == optimizer.MAX_BATCH_SIZE
        assert optimizer._clamp_batch_size(200) == optimizer.MAX_BATCH_SIZE

    def test_estimate_vram_usage_600m_fp16(self):
        """Test VRAM estimation for 600M model with FP16."""
        optimizer = GPUOptimizer()

        # 600M FP16: base=1200MB, per_item=25MB, reserved=500MB
        # batch_size=10: 1200 + 500 + (25 * 10) = 1950MB
        vram = optimizer._estimate_vram_usage(
            model_size="600M",
            precision="fp16",
            batch_size=10,
        )

        expected = 1200 + 500 + (25 * 10)
        assert vram == expected

    def test_estimate_vram_usage_3_3b_fp16(self):
        """Test VRAM estimation for 3.3B model with FP16."""
        optimizer = GPUOptimizer()

        # 3.3B FP16: base=6600MB, per_item=75MB, reserved=500MB
        # batch_size=16: 6600 + 500 + (75 * 16) = 8300MB
        vram = optimizer._estimate_vram_usage(
            model_size="3.3B",
            precision="fp16",
            batch_size=16,
        )

        expected = 6600 + 500 + (75 * 16)
        assert vram == expected

    def test_estimate_vram_usage_3_3b_int8(self):
        """Test VRAM estimation for 3.3B model with INT8."""
        optimizer = GPUOptimizer()

        # 3.3B INT8: base=3300MB, per_item=35MB, reserved=500MB
        # batch_size=20: 3300 + 500 + (35 * 20) = 4500MB
        vram = optimizer._estimate_vram_usage(
            model_size="3.3B",
            precision="int8",
            batch_size=20,
        )

        expected = 3300 + 500 + (35 * 20)
        assert vram == expected

    def test_compute_batch_size_600m_fp16_8gb(self):
        """Test batch size computation for 600M FP16 on 8GB GPU."""
        optimizer = GPUOptimizer(target_utilization=0.85)

        # 8GB = 8192MB
        # Target: 8192 * 0.85 = 6963MB
        # Base: 1200MB, Reserved: 500MB
        # Available for batch: 6963 - 1200 - 500 = 5263MB
        # Per item: 25MB
        # Optimal batch: 5263 / 25 = 210 -> clamped to MAX_BATCH_SIZE (64)
        batch_size = optimizer._compute_batch_size(
            total_vram_mb=8192,
            model_size="600M",
            precision="fp16",
        )

        assert batch_size == optimizer.MAX_BATCH_SIZE

    def test_compute_batch_size_3_3b_fp16_8gb(self):
        """Test batch size computation for 3.3B FP16 on 8GB GPU."""
        optimizer = GPUOptimizer(target_utilization=0.85)

        # 8GB = 8192MB
        # Target: 8192 * 0.85 = 6963MB
        # Base: 6600MB, Reserved: 500MB
        # Available for batch: 6963 - 6600 - 500 = -137MB (negative!)
        # Should return MIN_BATCH_SIZE
        batch_size = optimizer._compute_batch_size(
            total_vram_mb=8192,
            model_size="3.3B",
            precision="fp16",
        )

        assert batch_size == optimizer.MIN_BATCH_SIZE

    def test_compute_batch_size_3_3b_fp16_24gb(self):
        """Test batch size computation for 3.3B FP16 on 24GB GPU."""
        optimizer = GPUOptimizer(target_utilization=0.85)

        # 24GB = 24576MB
        # Target: 24576 * 0.85 = 20890MB
        # Base: 6600MB, Reserved: 500MB
        # Available for batch: 20890 - 6600 - 500 = 13790MB
        # Per item: 75MB
        # Optimal batch: 13790 / 75 = 183 -> clamped to MAX_BATCH_SIZE (64)
        batch_size = optimizer._compute_batch_size(
            total_vram_mb=24576,
            model_size="3.3B",
            precision="fp16",
        )

        assert batch_size == optimizer.MAX_BATCH_SIZE

    def test_compute_batch_size_3_3b_fp16_12gb(self):
        """Test batch size computation for 3.3B FP16 on 12GB GPU (typical case)."""
        optimizer = GPUOptimizer(target_utilization=0.85)

        # 12GB = 12288MB
        # Target: 12288 * 0.85 = 10445MB
        # Base: 6600MB, Reserved: 500MB
        # Available for batch: 10445 - 6600 - 500 = 3345MB
        # Per item: 75MB
        # Optimal batch: 3345 / 75 = 44.6 -> 44
        batch_size = optimizer._compute_batch_size(
            total_vram_mb=12288,
            model_size="3.3B",
            precision="fp16",
        )

        assert batch_size == 44

    def test_compute_batch_size_respects_custom_target_utilization(self):
        """Test that custom target utilization is respected."""
        # 90% utilization
        optimizer_90 = GPUOptimizer(target_utilization=0.90)

        # 70% utilization
        optimizer_70 = GPUOptimizer(target_utilization=0.70)

        # Same GPU and model
        total_vram_mb = 12288
        model_size = "3.3B"
        precision = "fp16"

        batch_90 = optimizer_90._compute_batch_size(total_vram_mb, model_size, precision)
        batch_70 = optimizer_70._compute_batch_size(total_vram_mb, model_size, precision)

        # Higher utilization should allow larger batch
        assert batch_90 > batch_70

    @patch('src.model_runtime.gpu_optimizer.torch')
    def test_optimize_success(self, mock_torch):
        """Test successful optimization flow."""
        # Mock CUDA availability
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1

        # Mock GPU properties
        mock_props = Mock()
        mock_props.total_memory = 12 * 1024 * 1024 * 1024  # 12GB in bytes
        mock_props.name = "NVIDIA GeForce RTX 3060"
        mock_torch.cuda.get_device_properties.return_value = mock_props

        optimizer = GPUOptimizer(
            model_name="facebook/nllb-200-3.3B",
            precision="fp16",
            target_utilization=0.85,
        )

        config = optimizer.optimize()

        # Verify config
        assert isinstance(config, GPUConfig)
        assert config.batch_size > 0
        assert config.device == "cuda:0"
        assert config.total_vram_mb == 12288
        assert 0 < config.estimated_vram_mb <= config.total_vram_mb
        assert config.target_utilization == 0.85

    @patch('src.model_runtime.gpu_optimizer.torch')
    def test_optimize_cuda_not_available(self, mock_torch):
        """Test optimization fails gracefully when CUDA unavailable."""
        mock_torch.cuda.is_available.return_value = False

        optimizer = GPUOptimizer()

        with pytest.raises(RuntimeError, match="CUDA not available"):
            optimizer.optimize()

    @patch('src.model_runtime.gpu_optimizer.torch')
    def test_optimize_invalid_device_id(self, mock_torch):
        """Test optimization fails with invalid device ID."""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1

        optimizer = GPUOptimizer(device_id=5)  # Only 1 GPU available

        with pytest.raises(RuntimeError, match="Invalid device ID"):
            optimizer.optimize()

    @patch('src.model_runtime.gpu_optimizer.torch')
    def test_optimize_with_batch_size_override(self, mock_torch):
        """Test that batch size override is respected."""
        # Mock CUDA
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1

        mock_props = Mock()
        mock_props.total_memory = 12 * 1024 * 1024 * 1024
        mock_props.name = "Test GPU"
        mock_torch.cuda.get_device_properties.return_value = mock_props

        # Override to specific batch size
        optimizer = GPUOptimizer(
            model_name="facebook/nllb-200-3.3B",
            batch_size_override=8,
        )

        config = optimizer.optimize()

        # Should use override
        assert config.batch_size == 8

    @patch('src.model_runtime.gpu_optimizer.torch')
    def test_optimize_multi_gpu(self, mock_torch):
        """Test optimization with multi-GPU setup."""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 4

        mock_props = Mock()
        mock_props.total_memory = 24 * 1024 * 1024 * 1024  # 24GB
        mock_props.name = "NVIDIA A100"
        mock_torch.cuda.get_device_properties.return_value = mock_props

        # Target GPU 2
        optimizer = GPUOptimizer(device_id=2)

        config = optimizer.optimize()

        # Should target correct device
        assert config.device == "cuda:2"
        mock_torch.cuda.get_device_properties.assert_called_with(2)

    def test_target_utilization_bounds(self):
        """Test that target utilization is clamped to safe bounds."""
        # Too low
        optimizer_low = GPUOptimizer(target_utilization=0.1)
        assert optimizer_low.target_utilization == 0.5  # Clamped to min

        # Too high
        optimizer_high = GPUOptimizer(target_utilization=0.99)
        assert optimizer_high.target_utilization == 0.95  # Clamped to max

        # Valid
        optimizer_valid = GPUOptimizer(target_utilization=0.85)
        assert optimizer_valid.target_utilization == 0.85

    def test_precision_variants(self):
        """Test batch size varies correctly with precision."""
        optimizer = GPUOptimizer(target_utilization=0.85)

        total_vram_mb = 12288
        model_size = "3.3B"

        # FP32 uses more memory -> smaller batch
        batch_fp32 = optimizer._compute_batch_size(total_vram_mb, model_size, "fp32")

        # FP16 uses less -> larger batch
        batch_fp16 = optimizer._compute_batch_size(total_vram_mb, model_size, "fp16")

        # INT8 uses least -> largest batch
        batch_int8 = optimizer._compute_batch_size(total_vram_mb, model_size, "int8")

        assert batch_fp32 < batch_fp16 < batch_int8


class TestGPUConfigDataclass:
    """Test GPUConfig dataclass."""

    def test_gpu_config_initialization(self):
        """Test GPUConfig can be initialized with all fields."""
        config = GPUConfig(
            batch_size=32,
            device="cuda:0",
            estimated_vram_mb=8500.0,
            total_vram_mb=12288.0,
            target_utilization=0.85,
        )

        assert config.batch_size == 32
        assert config.device == "cuda:0"
        assert config.estimated_vram_mb == 8500.0
        assert config.total_vram_mb == 12288.0
        assert config.target_utilization == 0.85

    def test_gpu_config_utilization_calculation(self):
        """Test that we can calculate actual utilization from config."""
        config = GPUConfig(
            batch_size=44,
            device="cuda:0",
            estimated_vram_mb=10445.0,
            total_vram_mb=12288.0,
            target_utilization=0.85,
        )

        actual_utilization = config.estimated_vram_mb / config.total_vram_mb
        assert abs(actual_utilization - 0.85) < 0.01  # Within 1%
