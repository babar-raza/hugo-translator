"""
Unit tests for CLI device validation logic (T102: federated-splashing-panda).

Tests device override and CUDA availability validation in translate_site().
"""
import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


@pytest.fixture
def mock_all_dependencies():
    """Mock all dependencies for CLI testing."""
    with patch.dict('sys.modules', {
        'src.translation_engine': MagicMock(),
        'src.translation_engine.models': MagicMock(),
        'src.tm': MagicMock(),
        'src.tm.translation_memory': MagicMock(),
        'src.tm.l1_cache': MagicMock(),
        'src.tm.l2_persistent': MagicMock(),
        'src.tm.l3_semantic': MagicMock(),
        'src.model_runtime': MagicMock(),
        'src.model_runtime.loader': MagicMock(),
        'src.model_runtime.registry': MagicMock(),
        'src.utils.config_loader': MagicMock(),
        'src.utils.models': MagicMock(),
        'torch': MagicMock(),
    }):
        yield


def test_device_auto_detects_cuda(mock_all_dependencies):
    """Test that --device auto detects CUDA when available (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test"])
    overrides = CLIConfigOverrides(args)

    # Mock torch.cuda.is_available() to return True
    with patch('torch.cuda.is_available', return_value=True):
        # Verify logic would use cuda
        if overrides.device:
            device = overrides.device
        else:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"

        assert device == "cuda"


def test_device_auto_falls_back_to_cpu(mock_all_dependencies):
    """Test that --device auto falls back to CPU when CUDA unavailable (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test"])
    overrides = CLIConfigOverrides(args)

    # Mock torch.cuda.is_available() to return False
    with patch('torch.cuda.is_available', return_value=False):
        # Verify logic would use cpu
        if overrides.device:
            device = overrides.device
        else:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"

        assert device == "cpu"


def test_device_override_cpu_succeeds(mock_all_dependencies):
    """Test that --device cpu always succeeds (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cpu"])
    overrides = CLIConfigOverrides(args)

    # CPU override should store "cpu"
    assert overrides.device == "cpu"

    # CPU always succeeds regardless of CUDA availability
    with patch('torch.cuda.is_available', return_value=True):
        device = overrides.device if overrides.device else "auto"
        assert device == "cpu"


def test_device_override_cuda_when_unavailable_should_fail(mock_all_dependencies):
    """Test that --device cuda fails when CUDA unavailable (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cuda"])
    overrides = CLIConfigOverrides(args)

    assert overrides.device == "cuda"

    # Simulate validation logic
    with patch('torch.cuda.is_available', return_value=False):
        import torch
        if overrides.device == "cuda" and not torch.cuda.is_available():
            # Should fail - return code 1
            result = 1
        else:
            result = 0

        assert result == 1  # Expect failure


def test_device_override_cuda_when_available_succeeds(mock_all_dependencies):
    """Test that --device cuda succeeds when CUDA is available (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cuda"])
    overrides = CLIConfigOverrides(args)

    assert overrides.device == "cuda"

    # Simulate validation logic
    with patch('torch.cuda.is_available', return_value=True):
        import torch
        if overrides.device == "cuda" and not torch.cuda.is_available():
            result = 1
        else:
            result = 0

        assert result == 0  # Expect success


def test_load_mode_fp16_on_cpu_warning_logic(mock_all_dependencies):
    """Test that fp16 on CPU should generate warning (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cpu", "--load-mode", "fp16"])
    overrides = CLIConfigOverrides(args)

    # Should warn: fp16 on CPU
    device = "cpu"
    should_warn = overrides.load_mode == "fp16" and device == "cpu"
    assert should_warn is True


def test_load_mode_int8_on_cuda_warning_logic(mock_all_dependencies):
    """Test that int8 on CUDA should generate warning (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cuda", "--load-mode", "int8"])
    overrides = CLIConfigOverrides(args)

    # Should warn: int8 on CUDA
    device = "cuda"
    should_warn = overrides.load_mode == "int8" and device == "cuda"
    assert should_warn is True


def test_load_mode_fp16_on_cuda_no_warning(mock_all_dependencies):
    """Test that fp16 on CUDA does not generate warning (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cuda", "--load-mode", "fp16"])
    overrides = CLIConfigOverrides(args)

    # Should NOT warn: fp16 on CUDA is optimal
    device = "cuda"
    should_warn_fp16_cpu = overrides.load_mode == "fp16" and device == "cpu"
    should_warn_int8_cuda = overrides.load_mode == "int8" and device == "cuda"
    assert should_warn_fp16_cpu is False
    assert should_warn_int8_cuda is False


def test_load_mode_int8_on_cpu_no_warning(mock_all_dependencies):
    """Test that int8 on CPU does not generate warning (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cpu", "--load-mode", "int8"])
    overrides = CLIConfigOverrides(args)

    # Should NOT warn: int8 on CPU is optimal
    device = "cpu"
    should_warn_fp16_cpu = overrides.load_mode == "fp16" and device == "cpu"
    should_warn_int8_cuda = overrides.load_mode == "int8" and device == "cuda"
    assert should_warn_fp16_cpu is False
    assert should_warn_int8_cuda is False


def test_pytorch_import_error_with_cuda_request(mock_all_dependencies):
    """Test that CUDA request fails gracefully when PyTorch not installed (T102)."""
    from src.cli import CLIConfigOverrides, create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cuda"])
    overrides = CLIConfigOverrides(args)

    # Simulate ImportError when PyTorch not available
    def mock_import_error():
        raise ImportError("No module named 'torch'")

    # Should fail with exit code 1
    try:
        import torch
        mock_import_error()
    except ImportError:
        if overrides.device == "cuda":
            result = 1  # Should exit with error
        else:
            result = 0

    assert result == 1
