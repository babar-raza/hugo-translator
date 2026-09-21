"""TC-APT-004 / LLM-HARDEN-001 regression (plan G-03): a provider failure is never a silent passthrough.

Forces provider exceptions through the real ``BaseLLMProvider.generate`` wrapper and the real
``LLMModelBackend`` segment paths and asserts:

* the job fails loudly (``LLMSegmentFailure``), never shipping same-as-source text;
* transient errors are retried with bounded backoff, fatal ones are not;
* the circuit breaker trips, refuses calls while open, half-opens after cooldown, closes on a probe;
* ``ModelLoader.load_model`` reroutes an LLM whose breaker is open to the automatic fallback;
* the health log records only whether the key resolved, never its value.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.model_runtime import circuit_breaker as cbmod
from src.model_runtime import llm_providers
from src.model_runtime.contracts import LLMProviderConfig
from src.model_runtime.llm_backend import LLMModelBackend
from src.model_runtime.llm_errors import (
    LLMCircuitOpenError,
    LLMFatalError,
    LLMSegmentFailure,
    LLMTransientError,
    classify_exception,
)
from src.model_runtime.registry import ModelInfo
from src.utils.circuit_breaker import BreakerConfig

SECRET = "sk-present-but-never-logged-0123456789"


class FlakyProvider(llm_providers.BaseLLMProvider):
    """Scriptable provider: ``script`` is a list of exceptions or (text, in, out) tuples."""

    def __init__(self, script):
        super().__init__()
        self.script = list(script)
        self.calls = 0

    def initialize(self, config):
        self._config = config

    def _generate_impl(self, system_prompt, user_text):
        self.calls += 1
        item = self.script.pop(0) if self.script else ("ok", 1, 1)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch):
    """Isolated breaker/health dirs, zero sleep, deterministic jitter, fake clock."""
    clock = {"now": 1_000_000.0}
    cfg = cbmod.LLMResilienceConfig(
        enabled=True,
        state_dir=tmp_path / "cb",
        health_dir=tmp_path / "health",
        breaker=BreakerConfig(
            consecutive_failure_trip=5,
            window_calls=20,
            cooldown_seconds=60,
            cooldown_cap_seconds=600,
        ),
        retry=cbmod.RetryPolicy(attempts=3, backoff_seconds=(2.0, 4.0, 8.0), jitter=0.2),
        fallback_model="m2m100_418m",
    )
    cbmod.configure(cfg)
    sleeps: list[float] = []
    monkeypatch.setattr(llm_providers, "_sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(llm_providers, "_rand", lambda: 0.5)  # jitter factor exactly 1.0
    monkeypatch.setattr(llm_providers, "_clock", lambda: clock["now"])
    monkeypatch.setenv("litellm_key", SECRET)
    cbmod.breaker_for("professionalize_llm")._clock = lambda: clock["now"]
    yield {"cfg": cfg, "sleeps": sleeps, "clock": clock, "tmp": tmp_path}
    cbmod.configure(None)


def _config(model_id="professionalize_llm"):
    return LLMProviderConfig(
        provider="openai_compatible",
        model_name="recommended",
        base_url="https://x/v1",
        api_key_env="litellm_key",
        model_id=model_id,
    )


def _provider(script, model_id="professionalize_llm"):
    p = FlakyProvider(script)
    p.initialize(_config(model_id))
    return p


def _backend(provider):
    info = ModelInfo(
        model_id="professionalize_llm",
        name="p",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="api",
        provider="openai_compatible",
        model_name="recommended",
        base_url="https://x/v1",
        api_key_env="litellm_key",
    )
    backend = LLMModelBackend(info, device="api")
    backend.loaded = True
    backend._provider = provider
    return backend


# ----------------------------------------------------------------------------- semantics
def test_provider_failure_raises_instead_of_shipping_source(isolated):
    backend = _backend(_provider([TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")]))
    with pytest.raises(LLMSegmentFailure) as exc:
        backend.translate_with_token_counts(["Hello world"], "en", "de")
    failure = exc.value
    assert failure.total == 1 and failure.outcomes[0].failed is True
    assert "Hello world" not in [
        o.text for o in failure.outcomes if o.failed
    ]  # never the source text
    assert backend.last_segment_outcomes[0].reason.startswith("LLMTransientError")


def test_translate_never_returns_source_on_failure(isolated):
    backend = _backend(_provider([RuntimeError("boom")] * 3))
    with pytest.raises(LLMSegmentFailure):
        backend.translate(["Hello"], "en", "fr")


def test_transient_errors_retry_with_backoff_then_succeed(isolated):
    provider = _provider([TimeoutError("t1"), ConnectionError("c2"), ("Hallo Welt", 5, 3)])
    backend = _backend(provider)
    out, inp, outp = backend.translate_with_token_counts(["Hello world"], "en", "de")
    assert out == ["Hallo Welt"] and (inp, outp) == (5, 3)
    assert provider.calls == 3
    assert isolated["sleeps"] == [2.0, 4.0]  # bounded backoff, jitter factor pinned to 1.0
    assert backend.last_segment_outcomes[0].failed is False


def test_fatal_error_is_not_retried(isolated):
    class AuthenticationError(Exception):
        status_code = 401

    provider = _provider([AuthenticationError("bad key")])
    with pytest.raises(LLMFatalError):
        provider.generate("sys", "user")
    assert provider.calls == 1 and isolated["sleeps"] == []


def test_packed_batch_failure_falls_back_to_single_then_fails_loudly(isolated):
    # 3 attempts for the packed call + 3 per single segment (2 segments) = 9 transport faults
    backend = _backend(_provider([TimeoutError("x")] * 9))
    with pytest.raises(LLMSegmentFailure) as exc:
        backend.translate_with_token_counts(["One", "Two"], "en", "de")
    assert exc.value.total == 2 and all(o.failed for o in exc.value.outcomes)


# ----------------------------------------------------------------------------- breaker
def test_breaker_trips_after_five_consecutive_failures_and_refuses(isolated):
    provider = _provider([TimeoutError("t")] * 100)
    for _ in range(5):
        with pytest.raises(LLMTransientError):
            provider.generate("sys", "user")  # 3 attempts each = 15 transport calls
    assert provider.calls == 15
    breaker = cbmod.breaker_for("professionalize_llm")
    assert breaker.is_open() is True
    with pytest.raises(LLMCircuitOpenError):
        provider.generate("sys", "user")
    assert provider.calls == 15  # refused without touching the provider
    state = json.loads(
        (isolated["tmp"] / "cb" / "professionalize_llm.json").read_text(encoding="utf-8")
    )
    assert state["state"] == "open" and state["trips"] == 1 and state["cooldown_seconds"] == 60.0


def test_breaker_half_opens_after_cooldown_and_closes_on_probe_success(isolated):
    provider = _provider([TimeoutError("t")] * 15 + [("ok", 1, 1), ("ok", 1, 1)])
    for _ in range(5):
        with pytest.raises(LLMTransientError):
            provider.generate("s", "u")
    breaker = cbmod.breaker_for("professionalize_llm")
    isolated["clock"]["now"] += 61  # cooldown elapsed -> half-open -> one probe admitted
    assert breaker.is_open() is False
    assert provider.generate("s", "u")[0] == "ok"
    assert breaker.state.value == "closed"


def test_breaker_reopen_doubles_cooldown_up_to_cap(isolated):
    breaker = cbmod.breaker_for("professionalize_llm")
    for _ in range(5):
        breaker.record_failure("f")
    assert breaker.snapshot()["cooldown_seconds"] == 60.0
    for expected in (120.0, 240.0, 480.0, 600.0, 600.0):
        isolated["clock"]["now"] += breaker.snapshot()["cooldown_seconds"] + 1
        assert breaker.allow_request() is True  # the half-open probe
        breaker.record_failure("probe failed")
        assert breaker.snapshot()["state"] == "open"
        assert breaker.snapshot()["cooldown_seconds"] == expected


def test_health_check_returns_false_while_open_without_calling_provider(isolated):
    provider = _provider([TimeoutError("t")] * 15)
    for _ in range(5):
        with pytest.raises(LLMTransientError):
            provider.generate("s", "u")
    calls = provider.calls
    assert provider.health_check() is False
    assert provider.calls == calls


# ----------------------------------------------------------------------------- reroute
def test_loader_reroutes_open_llm_to_fallback_and_records_it(isolated, monkeypatch):
    from src.model_runtime.loader import ModelLoader

    breaker = cbmod.breaker_for("professionalize_llm")
    for _ in range(5):
        breaker.record_failure("outage")
    assert breaker.is_open()

    llm_info = ModelInfo(
        model_id="professionalize_llm",
        name="p",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="api",
    )
    mt_info = ModelInfo(
        model_id="m2m100_418m",
        name="m",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="cuda",
    )
    registry = Mock()
    registry.get_model.side_effect = lambda mid: {
        "professionalize_llm": llm_info,
        "m2m100_418m": mt_info,
    }[mid]
    loader = ModelLoader(registry, config={})
    created: list[str] = []

    def _create(info, device):
        created.append(info.model_id)
        return Mock(name=f"backend:{info.model_id}", model_info=info, load=lambda: None)

    monkeypatch.setattr(loader, "_create_backend", _create)
    backend = loader.load_model("professionalize_llm")
    assert created == ["m2m100_418m"]  # the LLM backend was never instantiated
    assert backend.model_info.model_id == "m2m100_418m"
    assert loader.last_reroute == {
        "from": "professionalize_llm",
        "to": "m2m100_418m",
        "reason": "circuit_open",
    }
    health = (isolated["tmp"] / "health" / "professionalize_llm.jsonl").read_text(encoding="utf-8")
    assert '"event": "rerouted"' in health


def test_loader_does_not_reroute_when_breaker_closed(isolated, monkeypatch):
    from src.model_runtime.loader import ModelLoader

    llm_info = ModelInfo(
        model_id="professionalize_llm",
        name="p",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="api",
    )
    registry = Mock()
    registry.get_model.return_value = llm_info
    loader = ModelLoader(registry, config={})
    monkeypatch.setattr(
        loader, "_create_backend", lambda info, device: Mock(model_info=info, load=lambda: None)
    )
    assert loader.load_model("professionalize_llm").model_info.model_id == "professionalize_llm"
    assert loader.last_reroute is None


# ----------------------------------------------------------------------------- telemetry
def test_health_log_is_redacted(isolated):
    provider = _provider([TimeoutError("t"), ("ok", 2, 2)])
    assert provider.generate("s", "u")[0] == "ok"
    log = (isolated["tmp"] / "health" / "professionalize_llm.jsonl").read_text(encoding="utf-8")
    assert SECRET not in log
    rows = [json.loads(line) for line in log.splitlines()]
    assert (
        rows[-1]["ok"] is True and rows[-1]["api_key_resolved"] is True and rows[-1]["attempt"] == 2
    )
    assert rows[0]["ok"] is False and rows[0]["error_kind"] == "LLMTransientError"
    with pytest.raises(ValueError):
        cbmod.health_log("professionalize_llm", api_key=SECRET)


def test_classify_exception_taxonomy():
    class RateLimitError(Exception):
        status_code = 429

    class BadRequestError(Exception):
        status_code = 400

    assert isinstance(classify_exception(RateLimitError("slow down")), LLMTransientError)
    assert isinstance(classify_exception(BadRequestError("nope")), LLMFatalError)
    assert isinstance(classify_exception(TimeoutError()), LLMTransientError)
    assert isinstance(
        classify_exception(RuntimeError("weird")), LLMTransientError
    )  # unknown -> bounded retry
    assert isinstance(classify_exception(LLMFatalError("x")), LLMFatalError)
