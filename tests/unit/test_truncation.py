"""
Unit tests for truncation detection (TR-02).

Tests focus on:
- Detection when output reaches max_new_tokens limit
- Warning logging with segment context
- No false positives for short content
- Metrics surfaced via stats object
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
import torch

from src.model_runtime.loader import HuggingFaceBackend
from src.model_runtime.registry import ModelInfo


@pytest.fixture
def model_info():
    """Create test model info."""
    return ModelInfo(
        model_id="test_model",
        backend="huggingface",
        hf_model_id="facebook/m2m100_418M",
        model_size_mb=1000,
        supports_languages=["en", "de", "fr"],
    )


@pytest.fixture
def mock_model_and_tokenizer():
    """Create mock model and tokenizer for testing."""
    mock_model = MagicMock()
    mock_tokenizer = MagicMock()

    # Configure tokenizer mock
    mock_tokenizer.src_lang = "en"
    mock_tokenizer.get_lang_id = MagicMock(return_value=250004)  # Mock target lang ID

    return mock_model, mock_tokenizer


class TestTruncationDetection:
    """Test truncation detection functionality."""

    def test_truncation_detected_when_output_reaches_limit(
        self, model_info, mock_model_and_tokenizer, caplog
    ):
        """Test truncation is detected when output reaches max_new_tokens."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        # Create backend
        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        # Mock tokenizer to return specific input
        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        # Mock model.generate to return output that hits the limit
        # Shape: (batch_size=1, sequence_length=512)
        # This should trigger truncation detection
        mock_outputs = torch.tensor([[100] * 512])  # Exactly 512 tokens
        mock_model.generate.return_value = mock_outputs

        # Mock batch_decode
        mock_tokenizer.batch_decode.return_value = [
            "This is a truncated translation that ends abruptly"
        ]

        # Capture logs
        with caplog.at_level(logging.WARNING):
            texts = ["A very long source text that will be truncated"]
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                texts, "en", "de"
            )

        # Verify truncation was detected
        assert backend.last_truncation_detected is True
        assert backend.truncation_count == 1

        # Verify warning was logged
        assert len(caplog.records) > 0
        warning_found = False
        for record in caplog.records:
            if "Possible truncation detected" in record.message:
                warning_found = True
                assert "output reached 512 tokens" in record.message
                assert "limit: 512" in record.message
                assert "A very long source text" in record.message
                break
        assert warning_found, "Truncation warning not found in logs"

    def test_truncation_detected_near_limit(
        self, model_info, mock_model_and_tokenizer, caplog
    ):
        """Test truncation is detected when output is within tolerance of limit."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        # Output is 509 tokens (within 5 token tolerance of 512)
        # This should still trigger truncation detection
        mock_outputs = torch.tensor([[100] * 509])
        mock_model.generate.return_value = mock_outputs

        mock_tokenizer.batch_decode.return_value = [
            "Translation that is almost at the limit"
        ]

        with caplog.at_level(logging.WARNING):
            texts = ["Source text"]
            translations, _, _ = backend.translate_with_token_counts(texts, "en", "de")

        # Verify truncation was detected (within tolerance)
        assert backend.last_truncation_detected is True
        assert backend.truncation_count == 1

    def test_no_truncation_for_short_content(
        self, model_info, mock_model_and_tokenizer, caplog
    ):
        """Test no false positive for short content well below limit."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        # Output is only 50 tokens (well below 512 limit)
        mock_outputs = torch.tensor([[100] * 50])
        mock_model.generate.return_value = mock_outputs

        mock_tokenizer.batch_decode.return_value = [
            "Short translation"
        ]

        with caplog.at_level(logging.WARNING):
            texts = ["Short source text"]
            translations, _, _ = backend.translate_with_token_counts(texts, "en", "de")

        # Verify NO truncation detected
        assert backend.last_truncation_detected is False
        assert backend.truncation_count == 0

        # Verify NO warning was logged
        for record in caplog.records:
            assert "Possible truncation detected" not in record.message

    def test_truncation_count_increments(
        self, model_info, mock_model_and_tokenizer, caplog
    ):
        """Test truncation count increments across multiple calls."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        # First call: truncated
        mock_outputs = torch.tensor([[100] * 512])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Truncated 1"]

        backend.translate_with_token_counts(["Text 1"], "en", "de")
        assert backend.truncation_count == 1

        # Second call: not truncated
        mock_outputs = torch.tensor([[100] * 50])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Short"]

        backend.translate_with_token_counts(["Text 2"], "en", "de")
        assert backend.truncation_count == 1  # No increment

        # Third call: truncated again
        mock_outputs = torch.tensor([[100] * 512])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Truncated 2"]

        backend.translate_with_token_counts(["Text 3"], "en", "de")
        assert backend.truncation_count == 2  # Incremented

    def test_truncation_warning_includes_context(
        self, model_info, mock_model_and_tokenizer, caplog
    ):
        """Test truncation warning includes source text, languages, and index."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        # Output at limit
        mock_outputs = torch.tensor([[100] * 512])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Translation"]

        with caplog.at_level(logging.WARNING):
            long_text = "A" * 200  # 200 character text
            texts = [long_text]
            backend.translate_with_token_counts(texts, "en", "fr")

        # Find the warning record
        warning_record = None
        for record in caplog.records:
            if "Possible truncation detected" in record.message:
                warning_record = record
                break

        assert warning_record is not None
        # Verify context elements in warning
        assert "output reached 512 tokens" in warning_record.message
        assert "limit: 512" in warning_record.message
        assert "Source[0]:" in warning_record.message  # Index
        assert "src_lang=en" in warning_record.message  # Source language
        assert "tgt_lang=fr" in warning_record.message  # Target language
        # Verify text preview (truncated to 100 chars + "...")
        assert "AAA" in warning_record.message
        assert "..." in warning_record.message

    def test_batch_truncation_logs_all_items(
        self, model_info, mock_model_and_tokenizer, caplog
    ):
        """Test truncation warning logs all items in batch."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        # Batch of 3 texts
        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3], [4, 5, 6], [7, 8, 9]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1], [1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        # Output at limit (shape: batch_size=3, seq_len=512)
        mock_outputs = torch.tensor([[100] * 512, [101] * 512, [102] * 512])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Trans 1", "Trans 2", "Trans 3"]

        with caplog.at_level(logging.WARNING):
            texts = ["Text one", "Text two", "Text three"]
            backend.translate_with_token_counts(texts, "en", "de")

        # Verify truncation detected once (not per item)
        assert backend.last_truncation_detected is True
        assert backend.truncation_count == 1

        # Verify warning logged for each item in batch
        warning_count = 0
        for record in caplog.records:
            if "Possible truncation detected" in record.message:
                warning_count += 1

        assert warning_count == 3  # One warning per batch item

        # Verify each warning has correct index
        warnings = [r.message for r in caplog.records if "Possible truncation" in r.message]
        assert any("Source[0]:" in w and "Text one" in w for w in warnings)
        assert any("Source[1]:" in w and "Text two" in w for w in warnings)
        assert any("Source[2]:" in w and "Text three" in w for w in warnings)

    def test_truncation_flag_reset_each_call(
        self, model_info, mock_model_and_tokenizer
    ):
        """Test truncation flag is reset for each translate call."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        # First call: truncated
        mock_outputs = torch.tensor([[100] * 512])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Truncated"]

        backend.translate_with_token_counts(["Text 1"], "en", "de")
        assert backend.last_truncation_detected is True

        # Second call: NOT truncated - flag should be reset to False
        mock_outputs = torch.tensor([[100] * 50])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Short"]

        backend.translate_with_token_counts(["Text 2"], "en", "de")
        assert backend.last_truncation_detected is False  # Reset to False

    def test_truncation_detection_initializes_correctly(self, model_info):
        """Test truncation tracking fields initialize correctly."""
        backend = HuggingFaceBackend(model_info, device="cpu")

        # Verify initial state
        assert hasattr(backend, "last_truncation_detected")
        assert hasattr(backend, "truncation_count")
        assert backend.last_truncation_detected is False
        assert backend.truncation_count == 0

    def test_long_text_preview_truncation(
        self, model_info, mock_model_and_tokenizer, caplog
    ):
        """Test long source text is truncated in warning message."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        mock_outputs = torch.tensor([[100] * 512])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Translation"]

        with caplog.at_level(logging.WARNING):
            # Create text longer than 100 chars
            long_text = "X" * 150
            backend.translate_with_token_counts([long_text], "en", "de")

        # Find warning message
        warning = None
        for record in caplog.records:
            if "Possible truncation detected" in record.message:
                warning = record.message
                break

        assert warning is not None
        # Verify text was truncated to 100 chars + "..."
        assert "XXX" in warning
        assert "..." in warning
        # Full 150-char text should NOT be in warning
        assert "X" * 150 not in warning


class TestTruncationBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_translate_method_still_works(self, model_info, mock_model_and_tokenizer):
        """Test that translate() method (without token counts) still works."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        mock_outputs = torch.tensor([[100] * 512])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Translation"]

        # Call translate() (not translate_with_token_counts)
        translations = backend.translate(["Source"], "en", "de")

        # Verify it works
        assert len(translations) == 1
        assert translations[0] == "Translation"

        # Verify truncation detection still happened
        assert backend.last_truncation_detected is True

    def test_output_format_unchanged(self, model_info, mock_model_and_tokenizer):
        """Test that translate_with_token_counts output format is unchanged."""
        mock_model, mock_tokenizer = mock_model_and_tokenizer

        backend = HuggingFaceBackend(model_info, device="cpu")
        backend.model = mock_model
        backend.tokenizer = mock_tokenizer
        backend.loaded = True

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        mock_outputs = torch.tensor([[100] * 50])
        mock_model.generate.return_value = mock_outputs
        mock_tokenizer.batch_decode.return_value = ["Translation"]

        # Call method
        result = backend.translate_with_token_counts(["Source"], "en", "de")

        # Verify output format: tuple of (translations, input_tokens, output_tokens)
        assert isinstance(result, tuple)
        assert len(result) == 3

        translations, input_tokens, output_tokens = result
        assert isinstance(translations, list)
        assert isinstance(input_tokens, int)
        assert isinstance(output_tokens, int)
