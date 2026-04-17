"""
Standalone test for OOM error detection in TranslationEngine.

OOM-01: Tests for _is_oom_error() method without requiring pytest.
Run with: python test_oom_detection_standalone.py
"""
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from unittest.mock import Mock, patch

from src.translation_engine import TranslationEngine

# Configure logging to see debug output
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def create_test_engine():
    """Create a minimal TranslationEngine instance for testing."""
    mock_config = Mock()
    mock_config.load_global_config.return_value = {}

    # Mock site profile
    mock_profile = Mock()
    mock_profile.site_id = "test_site"
    mock_profile.default_source_lang = "en"
    mock_profile.default_model = "m2m100_418m"
    mock_profile.output_dir = "output"
    mock_profile.frontmatter = {}
    mock_profile.body = Mock()
    mock_profile.body.translate_markdown = True
    mock_profile.body.preserve_patterns = []
    mock_profile.body.preserve_blocks = []
    mock_profile.body.placeholder_syntax = []

    mock_config.get_site_profile.return_value = mock_profile

    with patch('src.translation_engine.engine.ModelLoader'), \
         patch('src.translation_engine.engine.TranslationMemory'), \
         patch('src.translation_engine.engine.HugoParser'), \
         patch('src.translation_engine.engine.SegmentExtractor'), \
         patch('src.translation_engine.engine.ValidationSuite'), \
         patch('src.translation_engine.engine.MarkdownReconstructor'):

        engine = TranslationEngine(
            config_service=mock_config,
            content_dir="/fake/content",
            device="cpu"
        )
        return engine


def test_oom_pattern_cuda_out_of_memory():
    """Test detection of 'cuda out of memory' pattern."""
    engine = create_test_engine()
    error = Exception("CUDA out of memory. Tried to allocate 2.00 GiB")
    result = engine._is_oom_error(error)
    assert result is True, "Should detect 'cuda out of memory' as OOM"
    logger.info("✓ test_oom_pattern_cuda_out_of_memory passed")


def test_oom_pattern_out_of_memory():
    """Test detection of 'out of memory' pattern."""
    engine = create_test_engine()
    error = Exception("RuntimeError: Out of memory during forward pass")
    result = engine._is_oom_error(error)
    assert result is True, "Should detect 'out of memory' as OOM"
    logger.info("✓ test_oom_pattern_out_of_memory passed")


def test_oom_pattern_gpu_out_of_memory():
    """Test detection of 'gpu out of memory during translation' pattern."""
    engine = create_test_engine()
    error = Exception("GPU out of memory during translation")
    result = engine._is_oom_error(error)
    assert result is True, "Should detect 'gpu out of memory during translation' as OOM"
    logger.info("✓ test_oom_pattern_gpu_out_of_memory passed")


def test_oom_pattern_reduce_batch_size():
    """Test detection of 'reduce batch size' pattern."""
    engine = create_test_engine()
    error = Exception("Memory error: please reduce batch size")
    result = engine._is_oom_error(error)
    assert result is True, "Should detect 'reduce batch size' as OOM"
    logger.info("✓ test_oom_pattern_reduce_batch_size passed")


def test_oom_pattern_cudnn_status():
    """Test detection of 'cudnn_status_not_enough_memory' pattern."""
    engine = create_test_engine()
    error = Exception("CUDNN_STATUS_NOT_ENOUGH_MEMORY in cuDNN operation")
    result = engine._is_oom_error(error)
    assert result is True, "Should detect 'cudnn_status_not_enough_memory' as OOM"
    logger.info("✓ test_oom_pattern_cudnn_status passed")


def test_oom_pattern_cublas_error():
    """Test detection of 'cublas error' pattern."""
    engine = create_test_engine()
    error = Exception("cuBLAS error: insufficient memory for operation")
    result = engine._is_oom_error(error)
    assert result is True, "Should detect 'cublas error' as OOM"
    logger.info("✓ test_oom_pattern_cublas_error passed")


def test_non_oom_error_key_error():
    """Test that KeyError is not detected as OOM."""
    engine = create_test_engine()
    error = KeyError("missing_key")
    result = engine._is_oom_error(error)
    assert result is False, "Should NOT detect KeyError as OOM"
    logger.info("✓ test_non_oom_error_key_error passed")


def test_non_oom_error_value_error():
    """Test that ValueError is not detected as OOM."""
    engine = create_test_engine()
    error = ValueError("Invalid batch size: must be positive")
    result = engine._is_oom_error(error)
    assert result is False, "Should NOT detect ValueError as OOM"
    logger.info("✓ test_non_oom_error_value_error passed")


def test_non_oom_error_attribute_error():
    """Test that AttributeError is not detected as OOM."""
    engine = create_test_engine()
    error = AttributeError("'NoneType' object has no attribute 'translate'")
    result = engine._is_oom_error(error)
    assert result is False, "Should NOT detect AttributeError as OOM"
    logger.info("✓ test_non_oom_error_attribute_error passed")


def test_case_insensitive_matching():
    """Test that OOM detection is case-insensitive."""
    engine = create_test_engine()

    # Mixed case
    error1 = Exception("CUDA Out Of Memory error")
    assert engine._is_oom_error(error1) is True, "Should detect mixed case OOM"

    # All uppercase
    error2 = Exception("OUT OF MEMORY ERROR")
    assert engine._is_oom_error(error2) is True, "Should detect uppercase OOM"

    # All lowercase
    error3 = Exception("cuda out of memory")
    assert engine._is_oom_error(error3) is True, "Should detect lowercase OOM"

    logger.info("✓ test_case_insensitive_matching passed")


def test_pattern_in_middle_of_message():
    """Test that patterns are detected anywhere in the error message."""
    engine = create_test_engine()
    error = Exception(
        "RuntimeError: Failed to allocate tensor: "
        "CUDA out of memory. Tried to allocate 2.00 GiB "
        "(GPU 0; 11.00 GiB total capacity; 9.50 GiB already allocated)"
    )
    result = engine._is_oom_error(error)
    assert result is True, "Should detect OOM pattern in middle of message"
    logger.info("✓ test_pattern_in_middle_of_message passed")


def run_all_tests():
    """Run all tests and report results."""
    tests = [
        test_oom_pattern_cuda_out_of_memory,
        test_oom_pattern_out_of_memory,
        test_oom_pattern_gpu_out_of_memory,
        test_oom_pattern_reduce_batch_size,
        test_oom_pattern_cudnn_status,
        test_oom_pattern_cublas_error,
        test_non_oom_error_key_error,
        test_non_oom_error_value_error,
        test_non_oom_error_attribute_error,
        test_case_insensitive_matching,
        test_pattern_in_middle_of_message,
    ]

    passed = 0
    failed = 0
    errors = []

    logger.info("=" * 70)
    logger.info("Running OOM Detection Tests")
    logger.info("=" * 70)

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append(f"{test_func.__name__}: {e}")
            logger.error(f"✗ {test_func.__name__} failed: {e}")
        except Exception as e:
            failed += 1
            errors.append(f"{test_func.__name__}: {e}")
            logger.error(f"✗ {test_func.__name__} error: {e}")

    logger.info("=" * 70)
    logger.info(f"Test Results: {passed} passed, {failed} failed")
    logger.info("=" * 70)

    if errors:
        logger.error("\nFailures:")
        for error in errors:
            logger.error(f"  - {error}")
        return 1
    else:
        logger.info("\n✓ All tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(run_all_tests())
