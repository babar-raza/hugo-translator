"""TC-APT-021: model-identity drift detector (baseline, MATCH/DRIFT, quarantine, cadence, FP calibration)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.model_runtime import circuit_breaker as cbmod
from src.model_runtime import model_identity as mi
from src.utils.circuit_breaker import BreakerConfig


class FakeClient:
    """Mimics the openai client surface used by alias resolution."""

    def __init__(self, models: list[str], answers: dict[str, str]):
        self._models = models
        self._answers = answers
        self.models = SimpleNamespace(
            list=lambda: SimpleNamespace(data=[SimpleNamespace(id=m) for m in self._models])
        )
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.calls: list[str] = []

    def _create(self, *, model, messages, temperature, max_tokens, timeout):
        self.calls.append(model)
        if model not in self._answers:
            raise RuntimeError("no such model")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._answers[model]))]
        )


class FakeProvider:
    def __init__(
        self,
        alias_answer: str,
        *,
        models=None,
        answers=None,
        fail: bool = False,
        alias="recommended",
        vary=False,
    ):
        self.alias_answer = alias_answer
        self.fail = fail
        self.vary = vary
        self._n = 0
        self._config = SimpleNamespace(model_name=alias, model_id="professionalize_llm")
        self._client = FakeClient(models or [], answers or {}) if models is not None else None

    def generate(self, system_prompt, user_text):
        if self.fail:
            raise TimeoutError("down")
        self._n += 1
        text = self.alias_answer if not self.vary else f"{self.alias_answer}#{self._n % 3}"
        return text, 1, 1


@pytest.fixture()
def identity_dir(tmp_path: Path):
    cbmod.configure(
        cbmod.LLMResilienceConfig(
            state_dir=tmp_path / "cb", health_dir=tmp_path / "health", breaker=BreakerConfig()
        )
    )
    yield tmp_path / "identity"
    cbmod.configure(None)


MODELS = [
    "recommended",
    "qwen3-next",
    "gpt-oss",
    "qwen3-embedding-8b",
    "stable-diffusion-3.5-large",
    "Qwen2.5-VL-7B",
]


def test_probe_resolves_alias_to_matching_concrete_models(identity_dir):
    p = FakeProvider(
        mi.CANARY_USER,
        models=MODELS,
        answers={"qwen3-next": mi.CANARY_USER, "gpt-oss": "something else"},
    )
    pr = mi.probe(p, "professionalize_llm")
    assert pr.echo_exact and pr.alias_matches == ["qwen3-next"]
    # non-text models are never probed
    assert set(p._client.calls) == {"qwen3-next", "gpt-oss"}
    assert pr.alias_resolution["gpt-oss"] != pr.response_sha256


def test_baseline_then_match(identity_dir):
    p = FakeProvider(mi.CANARY_USER, models=MODELS, answers={"qwen3-next": mi.CANARY_USER})
    path = mi.write_baseline(
        "professionalize_llm",
        mi.probe(p, "professionalize_llm"),
        identity_dir=identity_dir,
        alias="recommended",
    )
    assert json.loads(path.read_text(encoding="utf-8"))["alias_matches"] == ["qwen3-next"]
    check = mi.check_identity(p, "professionalize_llm", identity_dir=identity_dir)
    assert check.status == "MATCH" and check.quarantined is False
    assert mi.last_check("professionalize_llm", identity_dir)["status"] == "MATCH"


def test_canary_change_is_drift_records_review_item_and_quarantines(identity_dir):
    base = FakeProvider(mi.CANARY_USER, models=MODELS, answers={"qwen3-next": mi.CANARY_USER})
    mi.write_baseline(
        "professionalize_llm", mi.probe(base, "professionalize_llm"), identity_dir=identity_dir
    )
    drifted = FakeProvider(
        "A DIFFERENT MODEL ANSWERS", models=MODELS, answers={"gpt-oss": "A DIFFERENT MODEL ANSWERS"}
    )
    check = mi.check_identity(
        drifted, "professionalize_llm", identity_dir=identity_dir, quarantine_seconds=120
    )
    assert check.status == "DRIFT" and "canary response hash changed" in check.detail
    assert check.quarantined is True and check.review_item_id
    items = [
        json.loads(l)
        for l in mi.review_items_path(identity_dir).read_text(encoding="utf-8").splitlines()
    ]
    assert (
        items[-1]["kind"] == "model_identity_drift"
        and items[-1]["review_item_id"] == check.review_item_id
    )
    breaker = cbmod.breaker_for("professionalize_llm")
    assert breaker.is_open() and breaker.snapshot()["cooldown_seconds"] == 120.0
    assert "identity drift" in breaker.snapshot()["last_failure_reason"]


def test_alias_resolution_change_alone_is_drift(identity_dir):
    base = FakeProvider(
        mi.CANARY_USER, models=MODELS, answers={"qwen3-next": mi.CANARY_USER, "gpt-oss": "x"}
    )
    mi.write_baseline(
        "professionalize_llm", mi.probe(base, "professionalize_llm"), identity_dir=identity_dir
    )
    swapped = FakeProvider(
        mi.CANARY_USER, models=MODELS, answers={"qwen3-next": "y", "gpt-oss": mi.CANARY_USER}
    )
    check = mi.check_identity(
        swapped, "professionalize_llm", identity_dir=identity_dir, quarantine_on_drift=False
    )
    assert check.status == "DRIFT" and "alias now resolves to ['gpt-oss']" in check.detail
    assert check.quarantined is False


def test_unavailable_and_missing_baseline_statuses(identity_dir):
    down = FakeProvider(mi.CANARY_USER, fail=True)
    assert (
        mi.check_identity(down, "professionalize_llm", identity_dir=identity_dir).status
        == "BASELINE_MISSING"
    )
    mi.write_baseline(
        "professionalize_llm",
        mi.probe(FakeProvider(mi.CANARY_USER), "professionalize_llm"),
        identity_dir=identity_dir,
    )
    check = mi.check_identity(down, "professionalize_llm", identity_dir=identity_dir)
    assert check.status == "UNAVAILABLE" and check.quarantined is False


def test_should_check_cadence(identity_dir):
    assert mi.should_check("professionalize_llm", identity_dir=identity_dir) is True
    p = FakeProvider(mi.CANARY_USER)
    mi.write_baseline(
        "professionalize_llm", mi.probe(p, "professionalize_llm"), identity_dir=identity_dir
    )
    mi.check_identity(p, "professionalize_llm", identity_dir=identity_dir)
    assert (
        mi.should_check("professionalize_llm", interval_hours=6, identity_dir=identity_dir) is False
    )
    later = datetime.now(timezone.utc) + timedelta(hours=7)
    assert (
        mi.should_check(
            "professionalize_llm", interval_hours=6, identity_dir=identity_dir, now=later
        )
        is True
    )


def test_false_positive_calibration_is_measured_not_assumed():
    stable = mi.calibrate_false_positive_rate(FakeProvider(mi.CANARY_USER), "m", n=10)
    assert stable["distinct_outputs"] == 1 and stable["false_positive_rate_estimate"] == 0.0
    noisy = mi.calibrate_false_positive_rate(FakeProvider(mi.CANARY_USER, vary=True), "m", n=9)
    assert noisy["distinct_outputs"] == 3 and noisy["false_positive_rate_estimate"] > 0.5
