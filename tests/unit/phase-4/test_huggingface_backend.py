"""
Unit tests for HuggingFaceBackend precision modes (T104: federated-splashing-panda).
"""
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.model_runtime import HuggingFaceBackend, ModelInfo


@pytest.fixture
def sample_model_info():
    """Create sample ModelInfo."""
    return ModelInfo(
        model_id="test_model",
        name="Test Model",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=300,
        min_ram_gb=2,
        optimal_device="cpu",
        parameters=100000000,
        hf_model_id="test/model",
    )


class TestHuggingFaceBackendPrecisionModes:
    """Test HuggingFaceBackend precision mode handling (T104)."""

    def test_backend_fp32_on_cpu(self, sample_model_info):
        """Test FP32 precision on CPU."""
        backend = HuggingFaceBackend(
            sample_model_info, "cpu", use_fp16=False, use_int8=False
        )
        assert backend.use_fp16 is False
        assert backend.use_int8 is False

    def test_backend_fp16_on_cuda(self, sample_model_info):
        """Test FP16 precision on CUDA."""
        backend = HuggingFaceBackend(
            sample_model_info, "cuda", use_fp16=True, use_int8=False
        )
        assert backend.use_fp16 is True
        assert backend.use_int8 is False

    def test_backend_int8_on_cpu(self, sample_model_info):
        """Test INT8 quantization on CPU."""
        backend = HuggingFaceBackend(
            sample_model_info, "cpu", use_fp16=False, use_int8=True
        )
        assert backend.use_int8 is True
        assert backend.use_fp16 is False  # INT8 disables FP16

    def test_backend_auto_mode_cuda_uses_fp16(self, sample_model_info):
        """Test auto mode on CUDA defaults to FP16."""
        backend = HuggingFaceBackend(
            sample_model_info, "cuda", use_fp16=None, use_int8=False
        )
        assert backend.use_fp16 is True  # Auto-enabled for CUDA
        assert backend.use_int8 is False

    def test_backend_auto_mode_cpu_uses_fp32(self, sample_model_info):
        """Test auto mode on CPU defaults to FP32."""
        backend = HuggingFaceBackend(
            sample_model_info, "cpu", use_fp16=None, use_int8=False
        )
        assert backend.use_fp16 is False  # Auto-disabled for CPU
        assert backend.use_int8 is False

    def test_backend_int8_overrides_fp16(self, sample_model_info):
        """Test that INT8 takes precedence over FP16."""
        # Even if use_fp16=True, INT8 should override it
        backend = HuggingFaceBackend(
            sample_model_info, "cuda", use_fp16=True, use_int8=True
        )
        assert backend.use_int8 is True
        assert backend.use_fp16 is False  # INT8 forces FP16 off

    def test_backend_fp16_forced_on_cpu_disabled(self, sample_model_info):
        """Test FP16 forced on CPU is disabled (FP16 requires CUDA)."""
        backend = HuggingFaceBackend(
            sample_model_info, "cpu", use_fp16=True, use_int8=False
        )
        # FP16 should be disabled on CPU even if use_fp16=True
        assert backend.use_fp16 is False

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    def test_load_fp32_on_cpu(
        self, mock_model_class, mock_tokenizer_class, sample_model_info
    ):
        """Test loading with FP32 precision on CPU."""
        # Setup mocks
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        # Create backend and load
        backend = HuggingFaceBackend(
            sample_model_info, "cpu", use_fp16=False, use_int8=False
        )
        backend.load()

        # Verify FP32 loading (no torch_dtype specified)
        mock_model_class.from_pretrained.assert_called_once()
        call_args = mock_model_class.from_pretrained.call_args
        assert "torch_dtype" not in call_args[1]  # FP32 doesn't specify dtype

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    @patch("torch.cuda.is_available", return_value=True)
    def test_load_fp16_on_cuda(
        self, mock_cuda, mock_model_class, mock_tokenizer_class, sample_model_info
    ):
        """Test loading with FP16 precision on CUDA."""
        # Setup mocks
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        # Mock torch.float16
        with patch("torch.float16", "float16_mock"):
            # Create backend and load
            backend = HuggingFaceBackend(
                sample_model_info, "cuda", use_fp16=True, use_int8=False
            )
            backend.load()

            # Verify FP16 loading (torch_dtype=torch.float16)
            mock_model_class.from_pretrained.assert_called_once()
            call_kwargs = mock_model_class.from_pretrained.call_args[1]
            assert "torch_dtype" in call_kwargs

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    @patch("torch.quantization.quantize_dynamic")
    def test_load_int8_on_cpu(
        self,
        mock_quantize,
        mock_model_class,
        mock_tokenizer_class,
        sample_model_info,
    ):
        """Test loading with INT8 quantization on CPU."""
        # Setup mocks
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_quantized_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model
        mock_quantize.return_value = mock_quantized_model

        # Create backend and load
        backend = HuggingFaceBackend(
            sample_model_info, "cpu", use_fp16=False, use_int8=True
        )
        backend.load()

        # Verify FP32 loading first
        mock_model_class.from_pretrained.assert_called_once()

        # Verify quantization was applied
        mock_quantize.assert_called_once()
        assert backend.model == mock_quantized_model

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    @patch("torch.cuda.is_available", return_value=True)
    def test_auto_mode_on_cuda_loads_fp16(
        self, mock_cuda, mock_model_class, mock_tokenizer_class, sample_model_info
    ):
        """Test auto mode on CUDA loads FP16."""
        # Setup mocks
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        # Mock torch.float16
        with patch("torch.float16", "float16_mock"):
            # Create backend with auto mode (use_fp16=None)
            backend = HuggingFaceBackend(
                sample_model_info, "cuda", use_fp16=None, use_int8=False
            )
            assert backend.use_fp16 is True  # Auto-enabled for CUDA

            backend.load()

            # Verify FP16 loading
            mock_model_class.from_pretrained.assert_called_once()
            call_kwargs = mock_model_class.from_pretrained.call_args[1]
            assert "torch_dtype" in call_kwargs

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    def test_auto_mode_on_cpu_loads_fp32(
        self, mock_model_class, mock_tokenizer_class, sample_model_info
    ):
        """Test auto mode on CPU loads FP32."""
        # Setup mocks
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        # Create backend with auto mode (use_fp16=None)
        backend = HuggingFaceBackend(
            sample_model_info, "cpu", use_fp16=None, use_int8=False
        )
        assert backend.use_fp16 is False  # Auto-disabled for CPU

        backend.load()

        # Verify FP32 loading (no torch_dtype)
        mock_model_class.from_pretrained.assert_called_once()
        call_args = mock_model_class.from_pretrained.call_args
        assert "torch_dtype" not in call_args[1]
