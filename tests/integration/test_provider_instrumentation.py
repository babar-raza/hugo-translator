"""Integration tests: ContextVar accumulates across provider calls."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from src.observability.llm_run_context import LLMRunContext


class TestProviderInstrumentation:
    def test_contextvar_accumulates_across_calls(self):
        """LLMRunContext accumulates token counts across multiple generate() calls."""
        ctx = LLMRunContext.start_run()
        try:
            # Simulate 3 successful calls
            ctx.record_attempted()
            ctx.record_completed(100, 50)
            ctx.record_attempted()
            ctx.record_completed(200, 100)
            ctx.record_attempted()
            ctx.record_completed(150, 75)

            delta = ctx.checkpoint()
            assert delta.api_calls_count == 3
            assert delta.token_usage == 100 + 50 + 200 + 100 + 150 + 75  # 675
        finally:
            LLMRunContext.end_run()

    def test_failed_call_increments_counter(self):
        ctx = LLMRunContext.start_run()
        try:
            ctx.record_attempted()
            ctx.record_failed()
            ctx.record_attempted()
            ctx.record_completed(100, 50)

            delta = ctx.checkpoint()
            assert delta.attempted_provider_calls == 2
            assert delta.completed_provider_calls == 1
            assert delta.failed_provider_calls == 1
            assert delta.api_calls_count == 2
            assert delta.token_usage == 150
        finally:
            LLMRunContext.end_run()

    def test_checkpoint_delta_resets(self):
        ctx = LLMRunContext.start_run()
        try:
            ctx.record_attempted()
            ctx.record_completed(100, 50)
            d1 = ctx.checkpoint()
            assert d1.api_calls_count == 1

            ctx.record_attempted()
            ctx.record_completed(200, 100)
            d2 = ctx.checkpoint()
            assert d2.api_calls_count == 1  # Only the delta since last checkpoint
            assert d2.token_usage == 300
        finally:
            LLMRunContext.end_run()

    def test_base_provider_instruments_calls(self):
        """BaseLLMProvider.generate() instruments via LLMRunContext."""
        from src.model_runtime.llm_providers import BaseLLMProvider

        # Create a concrete subclass for testing
        class TestProvider(BaseLLMProvider):
            def initialize(self, config):
                pass

            def _generate_impl(self, system_prompt, user_text):
                return ("result", 100, 50)

        provider = TestProvider()
        ctx = LLMRunContext.start_run()
        try:
            result = provider.generate("sys", "user")
            assert result == ("result", 100, 50)
            delta = ctx.checkpoint()
            assert delta.attempted_provider_calls == 1
            assert delta.completed_provider_calls == 1
            assert delta.token_usage == 150
        finally:
            LLMRunContext.end_run()


class TestCorrectionTwoArgFix:
    def test_correction_uses_two_arg_generate(self):
        """correction.py calls generate(system_prompt, user_text), not generate(prompt)."""
        import inspect
        from src.translation_engine import correction
        src = inspect.getsource(correction.attempt_correction)
        # Must have 2-arg call pattern (system_prompt, prompt)
        assert "correction_system_prompt" in src
        assert "backend._provider.generate(" in src
