"""LLM model-identity drift detector (TC-APT-021, plan section 5.1 root cause 1).

``config/model_registry.yaml`` pins ``professionalize_llm`` to ``model_name: "recommended"`` --
a floating alias.  The Gate-1 capability probe (TC-APT-028, 2026-09-02) showed the endpoint's
``/models`` list exposes concrete names (``qwen3-next``, ``gpt-oss``, ...) but **no version-locked
identifier**, so a true pin is not available and prevention becomes detection:

* a fixed, deterministic canary prompt is sent before campaign work (and on a cadence);
  its response hash is compared with the calibration-time baseline;
* the alias is additionally *resolved*: the same canary is sent to each text-capable concrete
  model and the set whose answer equals the alias's answer is recorded -- a second drift signal
  that survives a canary-stable-but-model-swapped case only when the swap changes the canary;
* unexpected drift records a review item and **quarantines** the model by force-opening its
  circuit breaker, so ``ModelLoader`` reroutes to the automatic fallback (plan 6.1 / section 21:
  "drift -> fall back to m2m100_418m, open a review item, continue");
* the detector calibrates its own false-positive rate (N repeated canaries) and records it.

Files (``data/runtime/llm_identity/``): ``<model>_canary_baseline.json``,
``<model>_drift_log.jsonl``, ``review_items.jsonl``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_IDENTITY_DIR = Path("data/runtime/llm_identity")
#: Fixed canary (must never change: the baseline hash is only comparable to itself).
CANARY_SYSTEM = (
    "You are a deterministic echo service. Reply with exactly the user text, nothing else."
)
CANARY_USER = "ASPOSE-ORG-MODEL-IDENTITY-CANARY-2026-09-02 :: 7f3a9c1e :: translate nothing"
#: Concrete ids that are not text-generation models and are skipped by alias resolution.
NON_TEXT_HINTS = ("embedding", "diffusion", "-vl-", "vl-", "whisper", "tts")


@dataclass
class IdentityProbe:
    model_id: str
    response_sha256: str | None
    echo_exact: bool
    seconds: float
    error: str | None = None
    models_listed: list[str] = field(default_factory=list)
    alias_resolution: dict[str, str | None] = field(default_factory=dict)  # concrete id -> sha
    alias_matches: list[str] = field(default_factory=list)


@dataclass
class IdentityCheck:
    model_id: str
    status: str  # MATCH | DRIFT | BASELINE_MISSING | UNAVAILABLE
    baseline_sha256: str | None
    observed_sha256: str | None
    baseline_alias_matches: list[str]
    observed_alias_matches: list[str]
    checked_at: str
    detail: str = ""
    quarantined: bool = False
    review_item_id: str | None = None


def _sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def baseline_path(model_id: str, identity_dir: Path = DEFAULT_IDENTITY_DIR) -> Path:
    return identity_dir / f"{model_id}_canary_baseline.json"


def drift_log_path(model_id: str, identity_dir: Path = DEFAULT_IDENTITY_DIR) -> Path:
    return identity_dir / f"{model_id}_drift_log.jsonl"


def review_items_path(identity_dir: Path = DEFAULT_IDENTITY_DIR) -> Path:
    return identity_dir / "review_items.jsonl"


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")


# --------------------------------------------------------------------------- probing
def _text_capable(model_ids: list[str], alias: str) -> list[str]:
    out = []
    for mid in model_ids:
        low = mid.lower()
        if mid == alias or any(h in low for h in NON_TEXT_HINTS):
            continue
        out.append(mid)
    return out


def probe(provider: Any, model_id: str, *, resolve_alias: bool = True) -> IdentityProbe:
    """Send the canary through the production provider; optionally resolve the alias."""
    import time

    t0 = time.perf_counter()
    try:
        text, _, _ = provider.generate(CANARY_SYSTEM, CANARY_USER)
    except Exception as exc:
        return IdentityProbe(
            model_id,
            None,
            False,
            round(time.perf_counter() - t0, 3),
            error=f"{type(exc).__name__}: {exc}"[:200],
        )
    result = IdentityProbe(
        model_id, _sha(text), text.strip() == CANARY_USER, round(time.perf_counter() - t0, 3)
    )

    client = getattr(provider, "_client", None)
    cfg = getattr(provider, "_config", None)
    alias = getattr(cfg, "model_name", None)
    if resolve_alias and client is not None and hasattr(client, "models") and alias:
        try:
            listed = client.models.list()
            result.models_listed = sorted(
                str(getattr(m, "id", m)) for m in getattr(listed, "data", listed)
            )
        except Exception as exc:  # listing is optional evidence
            result.models_listed = [f"<list failed: {type(exc).__name__}>"]
        for concrete in _text_capable(
            [m for m in result.models_listed if not m.startswith("<")], alias
        ):
            try:
                resp = client.chat.completions.create(
                    model=concrete,
                    messages=[
                        {"role": "system", "content": CANARY_SYSTEM},
                        {"role": "user", "content": CANARY_USER},
                    ],
                    temperature=0.0,
                    max_tokens=64,
                    timeout=60,
                )
                content = resp.choices[0].message.content or ""
                result.alias_resolution[concrete] = _sha(content)
            except Exception:
                result.alias_resolution[concrete] = None
        result.alias_matches = sorted(
            k for k, v in result.alias_resolution.items() if v and v == result.response_sha256
        )
    return result


# --------------------------------------------------------------------------- baseline / check
def write_baseline(
    model_id: str,
    probe_result: IdentityProbe,
    *,
    identity_dir: Path = DEFAULT_IDENTITY_DIR,
    calibration: dict[str, Any] | None = None,
    alias: str | None = None,
) -> Path:
    path = baseline_path(model_id, identity_dir)
    payload = {
        "model_id": model_id,
        "configured_alias": alias,
        "canary_system": CANARY_SYSTEM,
        "canary_user": CANARY_USER,
        "response_sha256": probe_result.response_sha256,
        "echo_exact": probe_result.echo_exact,
        "models_listed": probe_result.models_listed,
        "alias_matches": probe_result.alias_matches,
        "alias_resolution": probe_result.alias_resolution,
        "calibration": calibration or {},
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_baseline(
    model_id: str, identity_dir: Path = DEFAULT_IDENTITY_DIR
) -> dict[str, Any] | None:
    path = baseline_path(model_id, identity_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_identity(
    provider: Any,
    model_id: str,
    *,
    identity_dir: Path = DEFAULT_IDENTITY_DIR,
    quarantine_on_drift: bool = True,
    quarantine_seconds: float = 6 * 3600,
    resolve_alias: bool = True,
) -> IdentityCheck:
    """Probe now, compare with the baseline, log, and quarantine on drift."""
    now = datetime.now(timezone.utc).isoformat()
    base = load_baseline(model_id, identity_dir)
    result = probe(provider, model_id, resolve_alias=resolve_alias)
    if base is None:
        check = IdentityCheck(
            model_id,
            "BASELINE_MISSING",
            None,
            result.response_sha256,
            [],
            result.alias_matches,
            now,
            "no baseline recorded; run --baseline first",
        )
    elif result.response_sha256 is None:
        check = IdentityCheck(
            model_id,
            "UNAVAILABLE",
            base.get("response_sha256"),
            None,
            base.get("alias_matches", []),
            [],
            now,
            result.error or "probe failed",
        )
    else:
        canary_same = result.response_sha256 == base.get("response_sha256")
        base_matches = list(base.get("alias_matches", []))
        alias_same = (
            (not base_matches)
            or (not result.alias_matches)
            or bool(set(base_matches) & set(result.alias_matches))
        )
        if canary_same and alias_same:
            status, detail = "MATCH", "canary hash and alias resolution consistent with baseline"
        else:
            reasons = []
            if not canary_same:
                reasons.append("canary response hash changed")
            if not alias_same:
                reasons.append(
                    f"alias now resolves to {result.alias_matches} (baseline {base_matches})"
                )
            status, detail = "DRIFT", "; ".join(reasons)
        check = IdentityCheck(
            model_id,
            status,
            base.get("response_sha256"),
            result.response_sha256,
            base_matches,
            result.alias_matches,
            now,
            detail,
        )

    if check.status == "DRIFT":
        item_id = f"identity-drift-{model_id}-{now.replace(':', '').replace('-', '')[:15]}"
        check.review_item_id = item_id
        _append(
            review_items_path(identity_dir),
            {
                "review_item_id": item_id,
                "kind": "model_identity_drift",
                "model_id": model_id,
                "detail": check.detail,
                "baseline_sha256": check.baseline_sha256,
                "observed_sha256": check.observed_sha256,
                "recommended_action": "re-qualify the LLM (TC-APT-004b sample) before re-baselining; until then the model is quarantined and work reroutes to the fallback",
                "at": now,
            },
        )
        if quarantine_on_drift:
            from src.model_runtime.circuit_breaker import breaker_for

            breaker = breaker_for(model_id)
            if breaker is not None:
                breaker.force_open(
                    f"model identity drift: {check.detail}", cooldown_seconds=quarantine_seconds
                )
                check.quarantined = True
    _append(
        drift_log_path(model_id, identity_dir), {**asdict(check), "probe_seconds": result.seconds}
    )
    return check


def last_check(model_id: str, identity_dir: Path = DEFAULT_IDENTITY_DIR) -> dict[str, Any] | None:
    path = drift_log_path(model_id, identity_dir)
    if not path.is_file():
        return None
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(lines[-1]) if lines else None


def should_check(
    model_id: str,
    *,
    interval_hours: float = 6.0,
    identity_dir: Path = DEFAULT_IDENTITY_DIR,
    now: datetime | None = None,
) -> bool:
    """Cadence rule (plan section 21): check before new LLM work if the interval has elapsed."""
    last = last_check(model_id, identity_dir)
    if last is None:
        return True
    try:
        checked = datetime.fromisoformat(str(last["checked_at"]))
    except (KeyError, ValueError):
        return True
    return (now or datetime.now(timezone.utc)) - checked >= timedelta(hours=interval_hours)


def calibrate_false_positive_rate(provider: Any, model_id: str, *, n: int = 20) -> dict[str, Any]:
    """Send the canary N times; the observed distinct-hash count bounds the false-positive rate."""
    hashes: list[str] = []
    errors = 0
    for _ in range(n):
        try:
            text, _, _ = provider.generate(CANARY_SYSTEM, CANARY_USER)
            hashes.append(_sha(text))
        except Exception:
            errors += 1
    distinct = len(set(hashes))
    return {
        "n": n,
        "successful": len(hashes),
        "errors": errors,
        "distinct_outputs": distinct,
        # If the same model gave k different canary hashes, a single-probe check would flag
        # drift falsely with probability ~ (1 - share of the dominant hash).
        "false_positive_rate_estimate": round(
            1.0 - (max(hashes.count(h) for h in set(hashes)) / len(hashes)), 4
        )
        if hashes
        else None,
        "false_negative_note": "unmeasurable until a real model swap is observed; mitigated by the alias-resolution second signal",
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------- CLI
def _provider_for(model_id: str, registry_path: Path):
    from src.model_runtime.contracts import LLMProviderConfig
    from src.model_runtime.llm_providers import create_provider
    from src.model_runtime.registry import ModelRegistry

    info = ModelRegistry(registry_path).get_model(model_id)
    cfg = LLMProviderConfig.from_model_info(info)
    return create_provider(cfg), cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-021 model-identity drift detector")
    parser.add_argument("--model-id", default="professionalize_llm")
    parser.add_argument("--registry", type=Path, default=Path("config/model_registry.yaml"))
    parser.add_argument("--identity-dir", type=Path, default=DEFAULT_IDENTITY_DIR)
    parser.add_argument(
        "--baseline", action="store_true", help="record/overwrite the baseline from a fresh probe"
    )
    parser.add_argument(
        "--calibrate",
        type=int,
        default=0,
        help="N repeated canaries for the false-positive estimate",
    )
    parser.add_argument(
        "--check", action="store_true", help="compare a fresh probe with the baseline"
    )
    parser.add_argument("--no-quarantine", action="store_true")
    args = parser.parse_args(argv)

    provider, cfg = _provider_for(args.model_id, args.registry)
    out: dict[str, Any] = {"model_id": args.model_id}
    if args.baseline:
        calibration = (
            calibrate_false_positive_rate(provider, args.model_id, n=args.calibrate)
            if args.calibrate
            else None
        )
        pr = probe(provider, args.model_id)
        path = write_baseline(
            args.model_id,
            pr,
            identity_dir=args.identity_dir,
            calibration=calibration,
            alias=cfg.model_name,
        )
        out["baseline"] = {
            "path": path.as_posix(),
            "response_sha256": pr.response_sha256,
            "echo_exact": pr.echo_exact,
            "alias_matches": pr.alias_matches,
            "models_listed": pr.models_listed,
            "calibration": calibration,
        }
    if args.check:
        check = check_identity(
            provider,
            args.model_id,
            identity_dir=args.identity_dir,
            quarantine_on_drift=not args.no_quarantine,
        )
        out["check"] = asdict(check)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("check", {}).get("status", "MATCH") in ("MATCH",) or not args.check else 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
