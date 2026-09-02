"""LLM-keyed circuit breakers, retry policy, fallback routing and redacted health log (TC-APT-004).

Thin configuration layer over :mod:`src.utils.circuit_breaker`:

* ``breaker_for(model_id)`` -> persisted breaker at ``<state_dir>/<model_id>.json``
  (``data/runtime/circuit_breaker/`` by default; read every wake by
  ``src/workers/mission_supervisor``);
* ``retry_policy()`` -> bounded retry (3 attempts, 2/4/8 s, +/-20 % jitter) for transient errors;
* ``fallback_model_for(model_id)`` -> the automatic reroute target (``m2m100_418m``, plan 6.1);
* ``health_log(...)`` -> ``data/runtime/llm_health/<model_id>.jsonl`` -- REDACTED: records
  whether the API key resolved, never its value (plan section 18).

All values come from ``config/global.yaml`` ``translation_engine.llm_*`` with defaults equal
to the TC-APT-028 calibration recommendation; ``configure()`` overrides them for tests.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.circuit_breaker import BreakerConfig, CircuitBreaker

DEFAULT_STATE_DIR = Path("data/runtime/circuit_breaker")
DEFAULT_HEALTH_DIR = Path("data/runtime/llm_health")
DEFAULT_FALLBACK_MODEL = "m2m100_418m"


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    backoff_seconds: tuple[float, ...] = (2.0, 4.0, 8.0)
    jitter: float = 0.2

    def delay(self, attempt_index: int, rand: float) -> float:
        """Backoff for the given zero-based attempt index; ``rand`` in [0,1)."""
        base = self.backoff_seconds[min(attempt_index, len(self.backoff_seconds) - 1)]
        return max(0.0, base * (1.0 + (rand * 2.0 - 1.0) * self.jitter))


@dataclass(frozen=True)
class LLMResilienceConfig:
    enabled: bool = True
    state_dir: Path = DEFAULT_STATE_DIR
    health_dir: Path = DEFAULT_HEALTH_DIR
    breaker: BreakerConfig = BreakerConfig()
    retry: RetryPolicy = RetryPolicy()
    fallback_model: str = DEFAULT_FALLBACK_MODEL


_override: LLMResilienceConfig | None = None
_cache: dict[str, CircuitBreaker] = {}
_cache_lock = threading.Lock()


def _raw_translation_engine() -> dict[str, Any]:
    try:
        from src.utils.config_loader import get_global_config

        return dict(get_global_config().get("translation_engine", {}) or {})
    except Exception:
        return {}


def load_config() -> LLMResilienceConfig:
    """Effective config: test override > global.yaml > defaults."""
    if _override is not None:
        return _override
    te = _raw_translation_engine()
    cb = te.get("llm_circuit_breaker") or {}
    rt = te.get("llm_retry") or {}
    breaker = BreakerConfig(
        consecutive_failure_trip=int(cb.get("consecutive_failure_trip", 5)),
        window_calls=int(cb.get("window_calls", 20)),
        window_failure_ratio_trip=float(cb.get("window_failure_ratio_trip", 0.5)),
        min_window_calls=int(cb.get("min_window_calls", 10)),
        cooldown_seconds=float(cb.get("cooldown_seconds", 60)),
        cooldown_cap_seconds=float(cb.get("cooldown_cap_seconds", 600)),
    )
    retry = RetryPolicy(
        attempts=int(rt.get("attempts", 3)),
        backoff_seconds=tuple(float(x) for x in rt.get("backoff_seconds", (2, 4, 8))),
        jitter=float(rt.get("jitter", 0.2)),
    )
    return LLMResilienceConfig(
        enabled=bool(cb.get("enabled", True)),
        state_dir=Path(
            os.environ.get("HT_CIRCUIT_BREAKER_DIR") or cb.get("state_dir", DEFAULT_STATE_DIR)
        ),
        health_dir=Path(te.get("llm_health_log_dir", DEFAULT_HEALTH_DIR)),
        breaker=breaker,
        retry=retry,
        fallback_model=str(te.get("llm_fallback_model", DEFAULT_FALLBACK_MODEL)),
    )


def configure(config: LLMResilienceConfig | None) -> None:
    """Override the effective config (tests); ``None`` restores global.yaml resolution."""
    global _override
    _override = config
    with _cache_lock:
        _cache.clear()


def breaker_for(model_id: str) -> CircuitBreaker | None:
    """The (cached) breaker for a model id, or None when breakers are disabled."""
    cfg = load_config()
    if not cfg.enabled:
        return None
    with _cache_lock:
        existing = _cache.get(model_id)
        if existing is not None and existing.state_path.parent == Path(cfg.state_dir):
            return existing
        breaker = CircuitBreaker(
            model_id, state_path=Path(cfg.state_dir) / f"{model_id}.json", config=cfg.breaker
        )
        _cache[model_id] = breaker
        return breaker


def retry_policy() -> RetryPolicy:
    return load_config().retry


def fallback_model_for(model_id: str) -> str | None:
    """Automatic reroute target for an LLM whose breaker is open (never itself)."""
    fb = load_config().fallback_model
    return None if not fb or fb == model_id else fb


def health_log(model_id: str, **fields: Any) -> None:
    """Append one redacted JSON line to ``<health_dir>/<model_id>.jsonl``.

    Callers pass ``api_key_resolved`` as a bool; a value that looks like a secret is
    refused outright so the log can never carry ``litellm_key``'s value.
    """
    cfg = load_config()
    for key, value in fields.items():
        if isinstance(value, str) and ("key" in key.lower() and len(value) > 8):
            raise ValueError(f"health_log refuses potential secret in field {key!r}")
    row = {"at": datetime.now(timezone.utc).isoformat(), "model_id": model_id, **fields}
    path = Path(cfg.health_dir) / f"{model_id}.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str) + "\n")
    except OSError:
        pass  # telemetry must never break a translation call


def breaker_states() -> dict[str, dict[str, Any]]:
    """Snapshot of every persisted breaker (for the supervisor / evidence)."""
    cfg = load_config()
    out: dict[str, dict[str, Any]] = {}
    if not Path(cfg.state_dir).is_dir():
        return out
    for path in sorted(Path(cfg.state_dir).glob("*.json")):
        out[path.stem] = CircuitBreaker(path.stem, state_path=path, config=cfg.breaker).snapshot()
    return out
