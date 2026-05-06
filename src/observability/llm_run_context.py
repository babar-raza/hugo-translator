"""ContextVar-based per-run LLM call accounting.

Tracks attempted/completed/failed provider calls and token usage
within a single worker run. Supports checkpoint-based deltas for
per-content-root metrics slicing.

Thread-safe via threading.Lock.
"""
from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field

_current_context: ContextVar["LLMRunContext | None"] = ContextVar(
    "llm_run_context", default=None
)


@dataclass
class _Snapshot:
    attempted: int = 0
    completed: int = 0
    failed: int = 0
    local_failure: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CheckpointDelta:
    """Delta between two checkpoints."""
    attempted_provider_calls: int = 0
    completed_provider_calls: int = 0
    failed_provider_calls: int = 0
    local_failure_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def token_usage(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def api_calls_count(self) -> int:
        return self.attempted_provider_calls


@dataclass
class LLMRunContext:
    """Per-run LLM call counter with checkpoint support."""

    attempted: int = field(default=0, init=False)
    completed: int = field(default=0, init=False)
    failed: int = field(default=0, init=False)
    local_failure: int = field(default=0, init=False)
    total_input_tokens: int = field(default=0, init=False)
    total_output_tokens: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _checkpoint: _Snapshot = field(default_factory=_Snapshot, init=False, repr=False)

    # --- Recording methods (called from BaseLLMProvider.generate) ---

    def record_attempted(self) -> None:
        with self._lock:
            self.attempted += 1

    def record_completed(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.completed += 1
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens

    def record_failed(self) -> None:
        with self._lock:
            self.failed += 1

    def record_local_failure(self) -> None:
        with self._lock:
            self.local_failure += 1

    # --- Checkpoint for per-content-root deltas ---

    def checkpoint(self) -> CheckpointDelta:
        """Return delta since last checkpoint and reset the snapshot."""
        with self._lock:
            delta = CheckpointDelta(
                attempted_provider_calls=self.attempted - self._checkpoint.attempted,
                completed_provider_calls=self.completed - self._checkpoint.completed,
                failed_provider_calls=self.failed - self._checkpoint.failed,
                local_failure_calls=self.local_failure - self._checkpoint.local_failure,
                total_input_tokens=self.total_input_tokens - self._checkpoint.input_tokens,
                total_output_tokens=self.total_output_tokens - self._checkpoint.output_tokens,
            )
            self._checkpoint = _Snapshot(
                attempted=self.attempted,
                completed=self.completed,
                failed=self.failed,
                local_failure=self.local_failure,
                input_tokens=self.total_input_tokens,
                output_tokens=self.total_output_tokens,
            )
            return delta

    def totals(self) -> CheckpointDelta:
        """Return cumulative totals (does not reset checkpoint)."""
        with self._lock:
            return CheckpointDelta(
                attempted_provider_calls=self.attempted,
                completed_provider_calls=self.completed,
                failed_provider_calls=self.failed,
                local_failure_calls=self.local_failure,
                total_input_tokens=self.total_input_tokens,
                total_output_tokens=self.total_output_tokens,
            )

    # --- ContextVar lifecycle ---

    @staticmethod
    def start_run() -> "LLMRunContext":
        """Create a new context and set it as the current ContextVar value."""
        ctx = LLMRunContext()
        _current_context.set(ctx)
        return ctx

    @staticmethod
    def end_run() -> CheckpointDelta | None:
        """End the current run, clear the ContextVar, return final totals."""
        ctx = _current_context.get(None)
        if ctx is None:
            return None
        totals = ctx.totals()
        _current_context.set(None)
        return totals

    @staticmethod
    def get_current() -> "LLMRunContext | None":
        """Get the current context, or None if no run is active."""
        return _current_context.get(None)
