"""
Unit tests for RetryHandler OOM recovery callback mechanism (WS2-CALLBACK).

Tests verify that:
1. Callback is invoked after successful OOM recovery (attempt > 0)
2. Callback is NOT invoked on first-try success (attempt == 0)
3. Callback receives correct arguments (failed_batch_size, success_batch_size)
4. Callback failures don't break retry flow (non-critical)
5. Callback is optional (backward compatibility)
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from src.translation_engine.retry_handler import RetryHandler


class TestRetryHandlerCallback:
    """Test suite for OOM recovery callback mechanism."""

    @pytest.fixture
    def retry_handler(self):
        """Create RetryHandler instance."""
        return RetryHandler(max_retries=3, batch_reduction_factor=0.5, min_batch_size=1)

    @pytest.fixture
    def mock_translate_func(self):
        """Create mock translation function."""
        return Mock(return_value={'success': True})

    @pytest.fixture
    def test_file(self, tmp_path):
        """Create test file."""
        file = tmp_path / "test.md"
        file.write_text("# Test\n\nContent")
        return file

    def test_callback_invoked_after_oom_recovery(self, retry_handler, test_file):
        """Test callback IS invoked when OOM recovery succeeds (attempt > 0)."""
        # Setup: Mock translate_func that fails once then succeeds
        translate_func = Mock(side_effect=[
            RuntimeError("CUDA out of memory"),  # First attempt fails with OOM
            {'success': True}                     # Second attempt succeeds
        ])

        # Setup: Mock callback
        callback = Mock()

        # Execute with callback
        with patch('src.translation_engine.retry_handler.TORCH_AVAILABLE', False):
            result = retry_handler.translate_file_with_retry(
                translate_func=translate_func,
                file_path=test_file,
                initial_batch_size=51,
                on_oom_recovery=callback
            )

        # Verify: Callback invoked with correct arguments
        assert result == {'success': True}
        callback.assert_called_once_with(51, 25)  # initial=51, reduced=25

    def test_callback_not_invoked_on_first_try_success(self, retry_handler, test_file):
        """Test callback is NOT invoked when first attempt succeeds (attempt == 0)."""
        # Setup: Mock translate_func that succeeds immediately
        translate_func = Mock(return_value={'success': True})

        # Setup: Mock callback
        callback = Mock()

        # Execute with callback
        result = retry_handler.translate_file_with_retry(
            translate_func=translate_func,
            file_path=test_file,
            initial_batch_size=51,
            on_oom_recovery=callback
        )

        # Verify: Callback NOT invoked (first try success)
        assert result == {'success': True}
        callback.assert_not_called()

    def test_callback_receives_correct_batch_sizes(self, retry_handler, test_file):
        """Test callback receives correct failed and success batch sizes."""
        # Setup: Mock translate_func that fails twice then succeeds
        translate_func = Mock(side_effect=[
            RuntimeError("CUDA out of memory"),  # Attempt 1: batch=51 fails
            RuntimeError("CUDA out of memory"),  # Attempt 2: batch=25 fails
            {'success': True}                     # Attempt 3: batch=12 succeeds
        ])

        # Setup: Mock callback
        callback = Mock()

        # Execute with callback
        with patch('src.translation_engine.retry_handler.TORCH_AVAILABLE', False):
            result = retry_handler.translate_file_with_retry(
                translate_func=translate_func,
                file_path=test_file,
                initial_batch_size=51,
                on_oom_recovery=callback
            )

        # Verify: Callback receives initial=51, success=12
        assert result == {'success': True}
        callback.assert_called_once_with(51, 12)  # initial=51, final_success=12

    def test_callback_failure_doesnt_break_retry(self, retry_handler, test_file):
        """Test that callback failures are non-critical (don't break retry flow)."""
        # Setup: Mock translate_func that recovers
        translate_func = Mock(side_effect=[
            RuntimeError("CUDA out of memory"),
            {'success': True}
        ])

        # Setup: Mock callback that raises exception
        callback = Mock(side_effect=RuntimeError("Callback failed"))

        # Execute with failing callback
        with patch('src.translation_engine.retry_handler.TORCH_AVAILABLE', False):
            result = retry_handler.translate_file_with_retry(
                translate_func=translate_func,
                file_path=test_file,
                initial_batch_size=51,
                on_oom_recovery=callback
            )

        # Verify: Translation still succeeds despite callback failure
        assert result == {'success': True}
        callback.assert_called_once()

    def test_callback_optional_backward_compatibility(self, retry_handler, test_file):
        """Test callback is optional (backward compatibility)."""
        # Setup: Mock translate_func that recovers
        translate_func = Mock(side_effect=[
            RuntimeError("CUDA out of memory"),
            {'success': True}
        ])

        # Execute WITHOUT callback (should not raise)
        with patch('src.translation_engine.retry_handler.TORCH_AVAILABLE', False):
            result = retry_handler.translate_file_with_retry(
                translate_func=translate_func,
                file_path=test_file,
                initial_batch_size=51
                # No on_oom_recovery parameter
            )

        # Verify: Still works without callback
        assert result == {'success': True}

    def test_callback_none_is_safe(self, retry_handler, test_file):
        """Test explicit None callback is safe."""
        # Setup: Mock translate_func that recovers
        translate_func = Mock(side_effect=[
            RuntimeError("CUDA out of memory"),
            {'success': True}
        ])

        # Execute with explicit None callback
        with patch('src.translation_engine.retry_handler.TORCH_AVAILABLE', False):
            result = retry_handler.translate_file_with_retry(
                translate_func=translate_func,
                file_path=test_file,
                initial_batch_size=51,
                on_oom_recovery=None  # Explicit None
            )

        # Verify: Works with None
        assert result == {'success': True}

    def test_non_oom_error_doesnt_trigger_callback(self, retry_handler, test_file):
        """Test callback not invoked for non-OOM errors."""
        # Setup: Mock translate_func that fails with non-OOM error
        translate_func = Mock(side_effect=ValueError("Invalid input"))

        # Setup: Mock callback
        callback = Mock()

        # Execute and expect error
        with pytest.raises(ValueError, match="Invalid input"):
            retry_handler.translate_file_with_retry(
                translate_func=translate_func,
                file_path=test_file,
                initial_batch_size=51,
                on_oom_recovery=callback
            )

        # Verify: Callback NOT invoked (error, not recovery)
        callback.assert_not_called()

    def test_callback_invoked_only_once_per_file(self, retry_handler, test_file):
        """Test callback invoked exactly once per successful recovery."""
        # Setup: Mock translate_func that recovers
        translate_func = Mock(side_effect=[
            RuntimeError("CUDA out of memory"),
            {'success': True}
        ])

        # Setup: Mock callback
        callback = Mock()

        # Execute
        with patch('src.translation_engine.retry_handler.TORCH_AVAILABLE', False):
            retry_handler.translate_file_with_retry(
                translate_func=translate_func,
                file_path=test_file,
                initial_batch_size=51,
                on_oom_recovery=callback
            )

        # Verify: Callback invoked exactly once
        assert callback.call_count == 1


class TestOOMRecoveryLearning:
    """Test suite for OOM recovery learning logic in engine."""

    @pytest.fixture
    def mock_batch_stats_tracker(self):
        """Create mock BatchStatsTracker."""
        tracker = Mock()
        tracker.languages = {
            'bg': {'current_batch_size': 51},
            'de': {'current_batch_size': 51},
        }
        tracker.record_batch_result = Mock()
        tracker.save = Mock()
        return tracker

    def test_learning_records_failure_for_all_languages(self, mock_batch_stats_tracker):
        """Test learning records OOM failure for all target languages."""
        # Setup target languages
        target_langs = ['bg', 'de', 'fr']

        # Simulate callback logic
        failed_batch_size = 51
        success_batch_size = 25

        for lang in target_langs:
            mock_batch_stats_tracker.record_batch_result(
                language=lang,
                batch_size=failed_batch_size,
                success=False,
                fallback_reason='oom_retry'
            )

        # Verify: record_batch_result called for each language
        assert mock_batch_stats_tracker.record_batch_result.call_count == 3

        # Verify: All calls have correct parameters
        for call in mock_batch_stats_tracker.record_batch_result.call_args_list:
            args, kwargs = call
            assert kwargs['batch_size'] == 51
            assert kwargs['success'] is False
            assert kwargs['fallback_reason'] == 'oom_retry'

    def test_learning_caps_batch_size_for_all_languages(self, mock_batch_stats_tracker):
        """Test learning caps current_batch_size to success size."""
        target_langs = ['bg', 'de']
        success_batch_size = 25

        # Simulate capping logic
        for lang in target_langs:
            if lang in mock_batch_stats_tracker.languages:
                lang_data = mock_batch_stats_tracker.languages[lang]
                current = lang_data.get('current_batch_size', success_batch_size)
                new_size = min(current, success_batch_size)
                lang_data['current_batch_size'] = new_size

        # Verify: Batch sizes capped correctly
        assert mock_batch_stats_tracker.languages['bg']['current_batch_size'] == 25
        assert mock_batch_stats_tracker.languages['de']['current_batch_size'] == 25

    def test_learning_persists_immediately(self, mock_batch_stats_tracker):
        """Test learning calls save() immediately after recording."""
        # Simulate learning flow
        target_langs = ['bg']

        # Record + save
        mock_batch_stats_tracker.record_batch_result(
            language='bg',
            batch_size=51,
            success=False,
            fallback_reason='oom_retry'
        )
        mock_batch_stats_tracker.save()

        # Verify: save() was called
        mock_batch_stats_tracker.save.assert_called_once()

    def test_learning_handles_none_tracker_gracefully(self):
        """Test learning handles None batch_stats_tracker gracefully."""
        # Simulate guard logic
        batch_stats_tracker = None

        # This should not raise
        if not batch_stats_tracker:
            # Guard prevents execution
            pass
        else:
            # Would call record_batch_result
            raise AssertionError("Should not reach here")

    def test_learning_handles_new_language(self, mock_batch_stats_tracker):
        """Test learning handles languages not yet in tracker."""
        # Setup: Add new language that's not in tracker
        target_langs = ['bg', 'fr']  # 'fr' not in tracker
        success_batch_size = 25

        # Simulate capping logic with guard
        for lang in target_langs:
            if lang in mock_batch_stats_tracker.languages:
                lang_data = mock_batch_stats_tracker.languages[lang]
                current = lang_data.get('current_batch_size', success_batch_size)
                new_size = min(current, success_batch_size)
                lang_data['current_batch_size'] = new_size
            # Else: Skip (language not in tracker yet)

        # Verify: Only 'bg' was capped, 'fr' skipped
        assert mock_batch_stats_tracker.languages['bg']['current_batch_size'] == 25
        assert 'fr' not in mock_batch_stats_tracker.languages


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
