"""Tests for LLMRunContext: ContextVar-based LLM call accounting."""
import threading

import pytest

from src.observability.llm_run_context import CheckpointDelta, LLMRunContext


class TestLLMRunContextAccumulation:
    def test_record_attempted_increments(self):
        ctx = LLMRunContext()
        ctx.record_attempted()
        ctx.record_attempted()
        assert ctx.attempted == 2

    def test_record_completed_increments_and_tracks_tokens(self):
        ctx = LLMRunContext()
        ctx.record_completed(100, 50)
        ctx.record_completed(200, 80)
        assert ctx.completed == 2
        assert ctx.total_input_tokens == 300
        assert ctx.total_output_tokens == 130

    def test_record_failed_increments(self):
        ctx = LLMRunContext()
        ctx.record_failed()
        assert ctx.failed == 1

    def test_record_local_failure_increments(self):
        ctx = LLMRunContext()
        ctx.record_local_failure()
        assert ctx.local_failure == 1

    def test_mixed_calls(self):
        ctx = LLMRunContext()
        ctx.record_attempted()
        ctx.record_completed(10, 20)
        ctx.record_attempted()
        ctx.record_failed()
        ctx.record_attempted()
        ctx.record_local_failure()
        assert ctx.attempted == 3
        assert ctx.completed == 1
        assert ctx.failed == 1
        assert ctx.local_failure == 1
        assert ctx.total_input_tokens == 10
        assert ctx.total_output_tokens == 20


class TestCheckpointDeltas:
    def test_first_checkpoint_returns_full_totals(self):
        ctx = LLMRunContext()
        ctx.record_attempted()
        ctx.record_completed(100, 50)
        delta = ctx.checkpoint()
        assert delta.attempted_provider_calls == 1
        assert delta.completed_provider_calls == 1
        assert delta.total_input_tokens == 100
        assert delta.total_output_tokens == 50
        assert delta.token_usage == 150
        assert delta.api_calls_count == 1

    def test_second_checkpoint_returns_only_new_calls(self):
        ctx = LLMRunContext()
        ctx.record_attempted()
        ctx.record_completed(100, 50)
        ctx.checkpoint()  # reset snapshot

        ctx.record_attempted()
        ctx.record_completed(200, 80)
        ctx.record_attempted()
        ctx.record_failed()
        delta = ctx.checkpoint()
        assert delta.attempted_provider_calls == 2
        assert delta.completed_provider_calls == 1
        assert delta.failed_provider_calls == 1
        assert delta.total_input_tokens == 200
        assert delta.total_output_tokens == 80

    def test_checkpoint_with_no_new_calls_returns_zeros(self):
        ctx = LLMRunContext()
        ctx.record_attempted()
        ctx.record_completed(10, 5)
        ctx.checkpoint()
        delta = ctx.checkpoint()
        assert delta.attempted_provider_calls == 0
        assert delta.token_usage == 0

    def test_totals_does_not_reset_checkpoint(self):
        ctx = LLMRunContext()
        ctx.record_attempted()
        ctx.record_completed(100, 50)
        totals = ctx.totals()
        assert totals.attempted_provider_calls == 1
        # checkpoint should still return full totals since totals() doesn't reset
        delta = ctx.checkpoint()
        assert delta.attempted_provider_calls == 1


class TestContextVarLifecycle:
    def test_no_context_returns_none(self):
        # Ensure clean state
        LLMRunContext.end_run()
        assert LLMRunContext.get_current() is None

    def test_start_run_sets_context(self):
        ctx = LLMRunContext.start_run()
        try:
            assert LLMRunContext.get_current() is ctx
        finally:
            LLMRunContext.end_run()

    def test_end_run_clears_context_and_returns_totals(self):
        ctx = LLMRunContext.start_run()
        ctx.record_attempted()
        ctx.record_completed(10, 5)
        totals = LLMRunContext.end_run()
        assert totals is not None
        assert totals.attempted_provider_calls == 1
        assert totals.token_usage == 15
        assert LLMRunContext.get_current() is None

    def test_end_run_without_start_returns_none(self):
        LLMRunContext.end_run()  # clear any prior state
        result = LLMRunContext.end_run()
        assert result is None

    def test_double_start_replaces_context(self):
        ctx1 = LLMRunContext.start_run()
        ctx2 = LLMRunContext.start_run()
        assert LLMRunContext.get_current() is ctx2
        assert ctx1 is not ctx2
        LLMRunContext.end_run()


class TestThreadSafety:
    def test_concurrent_recording(self):
        ctx = LLMRunContext()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    ctx.record_attempted()
                    ctx.record_completed(1, 1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert ctx.attempted == 400
        assert ctx.completed == 400
        assert ctx.total_input_tokens == 400
        assert ctx.total_output_tokens == 400


class TestCheckpointDeltaProperties:
    def test_token_usage_property(self):
        delta = CheckpointDelta(total_input_tokens=100, total_output_tokens=50)
        assert delta.token_usage == 150

    def test_api_calls_count_property(self):
        delta = CheckpointDelta(attempted_provider_calls=42)
        assert delta.api_calls_count == 42

    def test_default_values(self):
        delta = CheckpointDelta()
        assert delta.token_usage == 0
        assert delta.api_calls_count == 0
