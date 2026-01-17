"""
Unit tests for OOM error detection in TranslationEngine.

OOM-01: Tests for _is_oom_error() method to ensure correct pattern matching
and debug logging for troubleshooting.
"""
import logging
from unittest.mock import Mock, patch

import pytest

from src.translation_engine import TranslationEngine


class TestOOMDetection:
    """Tests for OOM error detection in TranslationEngine."""

    @pytest.fixture
    def engine(self):
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

    def test_oom_pattern_cuda_out_of_memory(self, engine, caplog):
        """Test detection of 'cuda out of memory' pattern."""
        with caplog.at_level(logging.DEBUG):
            error = Exception("CUDA out of memory. Tried to allocate 2.00 GiB")
            assert engine._is_oom_error(error) is True
            assert "OOM detected in Engine" in caplog.text
            assert "pattern='cuda out of memory'" in caplog.text

    def test_oom_pattern_out_of_memory(self, engine, caplog):
        """Test detection of 'out of memory' pattern."""
        with caplog.at_level(logging.DEBUG):
            error = Exception("RuntimeError: Out of memory during forward pass")
            assert engine._is_oom_error(error) is True
            assert "OOM detected in Engine" in caplog.text
            assert "pattern='out of memory'" in caplog.text

    def test_oom_pattern_gpu_out_of_memory(self, engine, caplog):
        """Test detection of 'gpu out of memory during translation' pattern."""
        with caplog.at_level(logging.DEBUG):
            error = Exception("GPU out of memory during translation")
            assert engine._is_oom_error(error) is True
            assert "OOM detected in Engine" in caplog.text
            assert "pattern='gpu out of memory during translation'" in caplog.text

    def test_oom_pattern_reduce_batch_size(self, engine, caplog):
        """Test detection of 'reduce batch size' pattern."""
        with caplog.at_level(logging.DEBUG):
            error = Exception("Memory error: please reduce batch size")
            assert engine._is_oom_error(error) is True
            assert "OOM detected in Engine" in caplog.text
            assert "pattern='reduce batch size'" in caplog.text

    def test_oom_pattern_cudnn_status(self, engine, caplog):
        """Test detection of 'cudnn_status_not_enough_memory' pattern."""
        with caplog.at_level(logging.DEBUG):
            error = Exception("CUDNN_STATUS_NOT_ENOUGH_MEMORY in cuDNN operation")
            assert engine._is_oom_error(error) is True
            assert "OOM detected in Engine" in caplog.text
            assert "pattern='cudnn_status_not_enough_memory'" in caplog.text

    def test_oom_pattern_cublas_error(self, engine, caplog):
        """Test detection of 'cublas error' pattern."""
        with caplog.at_level(logging.DEBUG):
            error = Exception("cuBLAS error: insufficient memory for operation")
            assert engine._is_oom_error(error) is True
            assert "OOM detected in Engine" in caplog.text
            assert "pattern='cublas error'" in caplog.text

    def test_non_oom_error_key_error(self, engine, caplog):
        """Test that KeyError is not detected as OOM."""
        with caplog.at_level(logging.DEBUG):
            error = KeyError("missing_key")
            assert engine._is_oom_error(error) is False
            assert "NOT OOM in Engine" in caplog.text
            assert "'missing_key'" in caplog.text

    def test_non_oom_error_value_error(self, engine, caplog):
        """Test that ValueError is not detected as OOM."""
        with caplog.at_level(logging.DEBUG):
            error = ValueError("Invalid batch size: must be positive")
            assert engine._is_oom_error(error) is False
            assert "NOT OOM in Engine" in caplog.text
            assert "Invalid batch size" in caplog.text

    def test_non_oom_error_attribute_error(self, engine, caplog):
        """Test that AttributeError is not detected as OOM."""
        with caplog.at_level(logging.DEBUG):
            error = AttributeError("'NoneType' object has no attribute 'translate'")
            assert engine._is_oom_error(error) is False
            assert "NOT OOM in Engine" in caplog.text
            assert "NoneType" in caplog.text

    def test_long_error_message_truncation(self, engine, caplog):
        """Test that long non-OOM error messages are truncated in debug log."""
        with caplog.at_level(logging.DEBUG):
            long_message = "X" * 200  # 200 character error message
            error = RuntimeError(long_message)
            assert engine._is_oom_error(error) is False
            assert "NOT OOM in Engine" in caplog.text
            # Should be truncated to 150 chars + "..."
            assert "..." in caplog.text
            # Full message should NOT be in log
            assert long_message not in caplog.text

    def test_case_insensitive_matching(self, engine, caplog):
        """Test that OOM detection is case-insensitive."""
        with caplog.at_level(logging.DEBUG):
            # Mixed case
            error1 = Exception("CUDA Out Of Memory error")
            assert engine._is_oom_error(error1) is True

            # All uppercase
            error2 = Exception("OUT OF MEMORY ERROR")
            assert engine._is_oom_error(error2) is True

            # All lowercase
            error3 = Exception("cuda out of memory")
            assert engine._is_oom_error(error3) is True

    def test_pattern_in_middle_of_message(self, engine, caplog):
        """Test that patterns are detected anywhere in the error message."""
        with caplog.at_level(logging.DEBUG):
            error = Exception(
                "RuntimeError: Failed to allocate tensor: "
                "CUDA out of memory. Tried to allocate 2.00 GiB "
                "(GPU 0; 11.00 GiB total capacity; 9.50 GiB already allocated)"
            )
            assert engine._is_oom_error(error) is True
            assert "OOM detected in Engine" in caplog.text

    def test_multiple_patterns_in_message(self, engine, caplog):
        """Test that first matching pattern is logged when multiple patterns present."""
        with caplog.at_level(logging.DEBUG):
            error = Exception("CUDA out of memory. Try to reduce batch size.")
            assert engine._is_oom_error(error) is True
            assert "OOM detected in Engine" in caplog.text
            # Should match first pattern encountered (cuda out of memory)
            assert "pattern='cuda out of memory'" in caplog.text

    def test_empty_error_message(self, engine, caplog):
        """Test handling of empty error message."""
        with caplog.at_level(logging.DEBUG):
            error = Exception("")
            assert engine._is_oom_error(error) is False
            assert "NOT OOM in Engine" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
