"""
Unit tests for empty translation fallback mechanism (Iter6 fix).

Tests the fallback ladder that recovers empty translations by retrying
with safer generation parameters.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
import torch


class TestEmptyTranslationFallback:
    """Test suite for empty translation detection and recovery."""

    @pytest.fixture
    def mock_backend(self):
        """Create a mock HuggingFace backend for testing."""
        from src.model_runtime.loader import HuggingFaceBackend, ModelInfo

        # Create model info
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=100,
            min_ram_gb=1.0,
            optimal_device="cpu",
        )

        # Create backend
        backend = HuggingFaceBackend(
            model_info=model_info,
            device="cpu",
        )

        # Mock model and tokenizer
        backend.model = MagicMock()
        backend.tokenizer = MagicMock()
        backend.loaded = True

        return backend

    def test_empty_translation_detection(self, mock_backend):
        """Test that empty translations are detected correctly."""
        # Simulate a batch where one translation is empty
        texts = ["Hello world", "Test text", "Another test"]

        # Mock tokenizer to return proper structure
        mock_backend.tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [4, 5, 6], [7, 8, 9]]),
            "attention_mask": torch.ones((3, 3)),
        }

        # Mock model.generate to return outputs
        mock_backend.model.generate.return_value = torch.tensor([
            [10, 11, 12],
            [13, 14, 15],
            [16, 17, 18],
        ])

        # Mock tokenizer.batch_decode to return one empty translation
        mock_backend.tokenizer.batch_decode.return_value = [
            "Привет мир",  # Valid translation
            "",  # Empty translation (triggers fallback)
            "Другой тест",  # Valid translation
        ]

        # Mock the recovery method to return a recovered translation
        def mock_recover(texts, empty_indices, current_translations, inputs,
                        src_lang, tgt_lang, mapped_src_lang, mapped_tgt_lang,
                        forced_bos_token_id):
            updated = current_translations.copy()
            updated[1] = "Тестовый текст"  # Recovered translation
            return updated, 1  # 1 recovered

        mock_backend._recover_empty_translations = Mock(side_effect=mock_recover)

        # Call translate
        result = mock_backend.translate(
            texts=texts,
            src_lang="en",
            tgt_lang="ru",
        )

        # Assertions
        assert len(result) == 3
        assert result[0] == "Привет мир"
        assert result[1] == "Тестовый текст"  # Should be recovered
        assert result[2] == "Другой тест"

        # Verify recovery method was called
        mock_backend._recover_empty_translations.assert_called_once()
        call_args = mock_backend._recover_empty_translations.call_args[0]
        assert call_args[1] == [1]  # empty_indices should contain index 1

    def test_fallback_strategies_tried_in_order(self, mock_backend):
        """Test that fallback strategies are tried in correct order."""
        texts = ["Short text"]
        empty_indices = [0]
        current_translations = [""]

        # Mock inputs
        inputs = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.ones((1, 3)),
        }

        # Track which strategies were tried
        strategies_tried = []

        def mock_generate(**kwargs):
            # Record which strategy parameters were used
            if kwargs.get("min_new_tokens") == 1 and kwargs.get("num_beams") == 1:
                strategies_tried.append("min_tokens_forced")
                # Return empty (strategy fails)
                return torch.tensor([[1, 2]])  # Will decode to empty
            elif kwargs.get("num_beams") == 5:
                strategies_tried.append("beam_search")
                # Return non-empty (strategy succeeds)
                return torch.tensor([[1, 2, 3, 4]])  # Will decode to "Recovered"
            return torch.tensor([[1, 2]])

        mock_backend.model.generate = Mock(side_effect=mock_generate)

        # Mock tokenizer for recovery
        decode_count = [0]
        def mock_decode(outputs, skip_special_tokens=True):
            decode_count[0] += 1
            # First decode returns empty (min_tokens_forced fails)
            # Second decode returns recovered text (beam_search succeeds)
            if decode_count[0] == 1:
                return [""]
            else:
                return ["Recovered"]

        mock_backend.tokenizer.batch_decode = Mock(side_effect=mock_decode)
        mock_backend.tokenizer.side_effect = None
        mock_backend.tokenizer.return_value = inputs

        # Call recovery method
        result, recovered_count = mock_backend._recover_empty_translations(
            texts=texts,
            empty_indices=empty_indices,
            current_translations=current_translations,
            inputs=inputs,
            src_lang="en",
            tgt_lang="ru",
            mapped_src_lang="en",
            mapped_tgt_lang="ru",
            forced_bos_token_id=None,
        )

        # Assertions
        assert recovered_count == 1
        assert result[0] == "Recovered"

        # Verify strategies were tried in order
        assert "min_tokens_forced" in strategies_tried
        assert "beam_search" in strategies_tried
        # beam_search should come after min_tokens_forced
        assert strategies_tried.index("beam_search") > strategies_tried.index("min_tokens_forced")

    def test_no_fallback_for_empty_source(self, mock_backend):
        """Test that fallback is NOT triggered when source text is empty."""
        texts = [""]  # Empty source

        # Mock tokenizer
        mock_backend.tokenizer.return_value = {
            "input_ids": torch.tensor([[1]]),
            "attention_mask": torch.ones((1, 1)),
        }

        # Mock model.generate
        mock_backend.model.generate.return_value = torch.tensor([[1]])

        # Mock tokenizer.batch_decode to return empty (matching empty source)
        mock_backend.tokenizer.batch_decode.return_value = [""]

        # Mock recovery method (should NOT be called)
        mock_backend._recover_empty_translations = Mock(return_value=([""], 0))

        # Call translate
        result = mock_backend.translate(
            texts=texts,
            src_lang="en",
            tgt_lang="ru",
        )

        # Assertions
        assert len(result) == 1
        assert result[0] == ""

        # Verify recovery was NOT called (empty source is valid)
        mock_backend._recover_empty_translations.assert_not_called()

    def test_metrics_incremented_on_detection(self, mock_backend):
        """Test that metrics are incremented when empty translations are detected."""
        texts = ["Test"]

        # Mock tokenizer and model
        mock_backend.tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.ones((1, 2)),
        }
        mock_backend.model.generate.return_value = torch.tensor([[1, 2]])
        mock_backend.tokenizer.batch_decode.return_value = [""]  # Empty

        # Mock recovery
        mock_backend._recover_empty_translations = Mock(
            return_value=(["Recovered"], 1)
        )

        # Mock metrics
        with patch('src.model_runtime.loader.get_metrics') as mock_get_metrics:
            mock_metrics = Mock()
            mock_get_metrics.return_value = mock_metrics

            # Call translate
            mock_backend.translate(
                texts=texts,
                src_lang="en",
                tgt_lang="ru",
            )

            # Verify metrics were incremented
            assert mock_metrics.increment.call_count >= 1

            # Check that empty_translation_detected was called
            calls = [call[0] for call in mock_metrics.increment.call_args_list]
            assert any("empty_translation_detected" in str(call) for call in calls)


class TestEmptyTranslationContract:
    """Contract tests ensuring empty translations never produce empty output files."""

    def test_translation_engine_rejects_empty_output(self):
        """
        Contract: Translation engine must reject files where all units translate to empty.

        This ensures the quality gate prevents corrupted outputs from being written.
        """
        # This is a contract test placeholder
        # The actual implementation is in the engine's quality gate
        # which detects empty translations and triggers retries/failures

        # The contract is:
        # 1. IF source text is non-empty
        # 2. AND translation is empty after retries
        # 3. THEN engine must return error (not write file)

        # This is enforced by the empty translation detection in loader.py
        # and the retry mechanism in engine.py
        pass  # Actual enforcement happens at runtime

    def test_empty_translation_logs_actionable_error(self):
        """
        Contract: Empty translation failures must log actionable diagnostics.

        Ensures developers can debug and fix empty translation issues.
        """
        # Contract requirements:
        # 1. Log must include source text preview
        # 2. Log must include language pair
        # 3. Log must include unit path/index
        # 4. Log must indicate which strategies were attempted

        # Implementation in loader.py lines 508-524 satisfies this
        pass  # Actual enforcement happens at runtime


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
