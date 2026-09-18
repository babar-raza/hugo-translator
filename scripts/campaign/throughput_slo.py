"""Deterministic throughput SLO and capacity-budget evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class ThroughputPolicy:
    target_outputs_per_hour: float = 600.0
    max_eta_minutes: float = 1440.0
    max_provider_calls_per_hour: float = 3600.0
    min_rate_per_hour: float = 60.0


def evaluate_throughput(
    *,
    accepted: int,
    remaining: int,
    elapsed_seconds: float,
    provider_calls: int = 0,
    policy: ThroughputPolicy = ThroughputPolicy(),
) -> dict[str, object]:
    """Return auditable rate, ETA, budget, and SLO status.

    A zero/negative elapsed interval is explicitly non-passing.  The function is
    pure so callers can use it for live status and offline deterministic tests.
    """
    elapsed_hours = max(float(elapsed_seconds), 0.0) / 3600.0
    rate = (max(int(accepted), 0) / elapsed_hours) if elapsed_hours > 0 else 0.0
    eta_minutes = (max(int(remaining), 0) * 60.0 / rate) if rate > 0 else None
    calls_per_hour = (max(int(provider_calls), 0) / elapsed_hours) if elapsed_hours > 0 else 0.0
    accepted_target = rate >= policy.target_outputs_per_hour
    eta_ok = eta_minutes is not None and eta_minutes <= policy.max_eta_minutes
    floor_ok = rate >= policy.min_rate_per_hour
    provider_budget_ok = calls_per_hour <= policy.max_provider_calls_per_hour
    passed = bool(accepted_target and eta_ok and floor_ok and provider_budget_ok)
    return {
        "accepted_outputs_per_hour": round(rate, 3),
        "target_outputs_per_hour": policy.target_outputs_per_hour,
        "eta_minutes": round(eta_minutes, 1) if eta_minutes is not None else None,
        "max_eta_minutes": policy.max_eta_minutes,
        "provider_calls_per_hour": round(calls_per_hour, 3),
        "max_provider_calls_per_hour": policy.max_provider_calls_per_hour,
        "min_rate_per_hour": policy.min_rate_per_hour,
        "collapse": bool(elapsed_hours > 0 and rate < policy.min_rate_per_hour),
        "passed": passed,
        "reasons": [
            reason
            for reason, ok in (
                ("below_target_rate", accepted_target),
                ("eta_exceeds_budget", eta_ok),
                ("throughput_collapse", floor_ok),
                ("provider_call_budget_exceeded", provider_budget_ok),
            )
            if not ok
        ],
        "required_calls_for_remaining": ceil(max(int(remaining), 0)),
    }
