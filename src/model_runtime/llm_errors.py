"""Typed LLM failure semantics (TC-APT-004 / LLM-HARDEN-001, plan G-03).

Before this module the LLM backend swallowed every provider exception and returned the
*source text* as if it were a translation -- a silent passthrough with no marker.  Now:

* provider failures are typed (:class:`LLMTransientError` retryable,
  :class:`LLMFatalError` not, :class:`LLMCircuitOpenError` when the breaker refuses);
* every segment yields a :class:`SegmentOutcome`; a batch with any ``failed`` outcome
  raises :class:`LLMSegmentFailure` instead of shipping same-as-source text.
"""

from __future__ import annotations

from dataclasses import dataclass

TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
FATAL_STATUS = frozenset({400, 401, 403, 404, 405, 413, 422})
TRANSIENT_NAMES = frozenset(
    {
        "TimeoutError",
        "ConnectionError",
        "ConnectionResetError",
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
        "RemoteProtocolError",
        "ReadTimeout",
        "ConnectTimeout",
    }
)
FATAL_NAMES = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "NotFoundError",
        "UnprocessableEntityError",
        "ContentFilterError",
    }
)


class LLMError(RuntimeError):
    """Base class for typed LLM failures."""


class LLMTransientError(LLMError):
    """Retryable: timeout, connection reset, 429, 5xx."""


class LLMFatalError(LLMError):
    """Not retryable: auth, bad request, not found."""


class LLMCircuitOpenError(LLMError):
    """The model's circuit breaker is open; the call was refused without hitting the provider."""


@dataclass
class SegmentOutcome:
    """Per-segment result record -- the truthful replacement for a bare ``list[str]``."""

    index: int
    text: str
    failed: bool
    reason: str | None = None
    attempts: int = 1
    model_id: str | None = None


class LLMSegmentFailure(LLMError):
    """At least one segment failed after retries; nothing was passed through silently."""

    def __init__(self, outcomes: list[SegmentOutcome], *, total: int, circuit_open: bool = False):
        self.outcomes = list(outcomes)
        self.total = total
        self.circuit_open = circuit_open
        failed = [o for o in self.outcomes if o.failed]
        reasons = sorted({(o.reason or "unknown").split(":")[0] for o in failed})
        super().__init__(
            f"{len(failed)}/{total} LLM segments failed after retries "
            f"(reasons: {', '.join(reasons)}; circuit_open={circuit_open})"
        )


def _status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "status", "http_status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def classify_exception(exc: BaseException) -> LLMError:
    """Map any provider/transport exception onto the typed hierarchy (never returns None)."""
    if isinstance(exc, LLMError):
        return exc
    name = type(exc).__name__
    status = _status_of(exc)
    message = f"{name}: {exc}"[:300]
    if isinstance(exc, LLMFatalError) or name in FATAL_NAMES or (status in FATAL_STATUS):
        return LLMFatalError(message)
    if (
        name in TRANSIENT_NAMES
        or (status in TRANSIENT_STATUS)
        or isinstance(exc, (TimeoutError, ConnectionError))
    ):
        return LLMTransientError(message)
    lowered = message.lower()
    if any(
        tok in lowered
        for tok in (
            "timeout",
            "timed out",
            "429",
            "rate limit",
            "connection",
            "temporarily",
            "overloaded",
            "502",
            "503",
            "504",
        )
    ):
        return LLMTransientError(message)
    if any(
        tok in lowered
        for tok in (
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "invalid api key",
            "invalid_request",
            "400",
        )
    ):
        return LLMFatalError(message)
    # Unknown failure class: retry (bounded) rather than give up -- but it still counts
    # against the breaker, so a persistent unknown failure trips it.
    return LLMTransientError(message)
