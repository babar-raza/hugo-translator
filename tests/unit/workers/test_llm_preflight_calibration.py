"""TC-APT-028: preflight/calibration harness logic, exercised offline with a fake provider."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import scripts.campaign.llm_preflight_calibration as cal


class FakeProvider:
    """Deterministic echo-translator; optional fault injection above a concurrency level."""

    def __init__(
        self,
        *,
        rate_limit_above: int | None = None,
        truncate_long: bool = False,
        drop_placeholders: bool = False,
        nondeterministic: bool = False,
    ):
        self.rate_limit_above = rate_limit_above
        self.truncate_long = truncate_long
        self.drop_placeholders = drop_placeholders
        self.nondeterministic = nondeterministic
        self._inflight = 0
        self._lock = threading.Lock()
        self._n = 0
        self._client = None

    def health_check(self) -> bool:
        return True

    def generate(self, system_prompt: str, user_text: str):
        with self._lock:
            self._inflight += 1
            inflight = self._inflight
            self._n += 1
            n = self._n
        try:
            time.sleep(0.01)  # hold the call so concurrent threads genuinely overlap
            if self.rate_limit_above is not None and inflight > self.rate_limit_above:
                raise RuntimeError("HTTP 429 Too Many Requests")
            if system_prompt == cal.CANARY_SYSTEM:
                return user_text, 10, 10
            if "to Arabic" in system_prompt:
                return "يقرأ Aspose.Cells for .NET ملفات XLSX. `Workbook`", 20, 20
            text = user_text
            if self.drop_placeholders:
                text = text.replace("{PLACEHOLDER_0}", "").replace("{PLACEHOLDER_1}", "")
            if self.truncate_long and len(text) > 2000:
                text = text[:500]
            if self.nondeterministic:
                text = f"{text} #{n}"
            if "<<<SEG_1>>>" in user_text:
                # packed: echo each numbered line back
                text = "\n".join(line for line in user_text.splitlines())
            words = len(user_text.split())
            return text, words * 2, words * 2
        finally:
            with self._lock:
                self._inflight -= 1


def _calibrator(provider, monkeypatch, **kw):
    monkeypatch.setenv("litellm_key", "present-but-never-printed")
    return cal.LLMCalibrator(
        provider,
        api_key_env="litellm_key",
        batch_prompt_builder=lambda s, t, n: f"batch {s}->{t} x{n}",
        sleep=lambda _s: None,
        **kw,
    )


def test_preflight_passes_on_well_behaved_provider(monkeypatch):
    c = _calibrator(FakeProvider(), monkeypatch)
    pf = c.preflight(determinism_n=4)
    assert c.report.hard_stops == []
    assert pf["api_key_resolved"] is True
    assert pf["canary"]["echo_exact"] is True and len(pf["canary"]["response_sha256"]) == 64
    assert pf["representative_segments"]["placeholder_tokens"]["placeholders_preserved"] is True
    assert pf["representative_segments"]["fenced_code"]["fence_preserved"] is True
    assert pf["determinism"] == {
        "n": 4,
        "successful": 4,
        "errors": 0,
        "distinct_outputs": 1,
        "byte_identical_rate": 1.0,
        "is_deterministic": True,
    }
    assert pf["models_probe"]["supported"] is False  # fake provider has no client


def test_preflight_hard_stops_on_missing_key_truncation_and_placeholder_loss(monkeypatch):
    monkeypatch.delenv("litellm_key", raising=False)
    c = cal.LLMCalibrator(
        FakeProvider(truncate_long=True, drop_placeholders=True),
        api_key_env="litellm_key",
        batch_prompt_builder=lambda s, t, n: "b",
    )
    c.preflight(determinism_n=2)
    stops = " | ".join(c.report.hard_stops)
    assert "does not resolve" in stops
    assert "placeholder_tokens: ['placeholders_preserved']" in stops
    assert "long_technical_paragraph: ['not_truncated']" in stops


def test_preflight_measures_nondeterminism_honestly(monkeypatch):
    c = _calibrator(FakeProvider(nondeterministic=True), monkeypatch)
    pf = c.preflight(determinism_n=5)
    assert pf["determinism"]["distinct_outputs"] == 5
    assert pf["determinism"]["is_deterministic"] is False
    assert pf["determinism"]["byte_identical_rate"] == 0.2


def test_calibration_finds_concurrency_ceiling_and_packing(monkeypatch):
    c = _calibrator(FakeProvider(rate_limit_above=4), monkeypatch)
    c.preflight(determinism_n=1)
    result = c.calibrate(latency_samples=2, levels=(1, 2, 4, 8), calls_per_level=8, pack_size=4)
    assert result["safe_concurrency_ceiling"] == 4
    assert result["ramp_stop_reason"].startswith("level 8:")
    ramp = {r["level"]: r for r in result["concurrency_ramp"]}
    assert ramp[8]["rate_limited"] >= 1 and ramp[4]["errors"] == 0
    assert result["token_cost"]["tokens_per_source_word"] == 4.0
    assert (
        result["batch_packing"]["packed_ok"] is True and result["batch_packing"]["pack_size"] == 4
    )
    rec = c.report.recommendations
    assert rec["manifest_max_parallel_jobs_for_llm"] == 4
    assert rec["circuit_breaker"]["consecutive_failure_trip"] == 5
    assert set(result["latency_by_class_seconds"]) == {
        "short_metadata",
        "long_prose",
        "table_heavy",
        "placeholder_heavy",
    }


def test_finish_writes_report_and_canary_baseline_once(monkeypatch, tmp_path: Path):
    c = _calibrator(FakeProvider(), monkeypatch)
    c.preflight(determinism_n=1)
    out = tmp_path / "cal.json"
    base = tmp_path / "baseline.json"
    payload = c.finish(out, base)
    assert payload["baseline_written"] == base.as_posix()
    saved = json.loads(base.read_text(encoding="utf-8"))
    assert saved["canary_user"] == cal.CANARY_USER and len(saved["response_sha256"]) == 64
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["taskcard"] == "TC-APT-028" and report["hard_stops"] == []
    # second run compares against the existing baseline instead of overwriting it
    c2 = _calibrator(FakeProvider(), monkeypatch)
    c2.preflight(determinism_n=1)
    payload2 = c2.finish(tmp_path / "cal2.json", base)
    assert payload2["baseline_matches"] is True


def test_percentiles_and_rate_limit_detection():
    p = cal._percentiles([0.1, 0.2, 0.3, 0.4, 1.0])
    assert p["n"] == 5 and p["p50"] == 0.3 and p["p99"] == 1.0
    assert cal._is_rate_limit(RuntimeError("Error code: 429 - rate limit exceeded"))
    assert not cal._is_rate_limit(RuntimeError("connection reset"))


@pytest.mark.parametrize("lang,name", [("de", "German"), ("zz", "ZZ")])
def test_translation_prompt_uses_production_template(lang, name):
    prompt = cal.LLMCalibrator.translation_prompt(lang)
    assert f"from English to {name}" in prompt and "Output ONLY the translation" in prompt


class TestSustainedRamp:
    """TC-APT-064: sustained_ramp() holds each level for a real duration, unlike
    calibrate()'s concurrency_ramp which fires a fixed call count once per level."""

    def test_holds_each_level_for_the_duration_and_multiple_calls_land(self, monkeypatch):
        c = _calibrator(FakeProvider(), monkeypatch)
        result = c.sustained_ramp(levels=(2, 4), seconds_per_level=0.08)

        assert result["sustained_stop_reason"] is None
        assert result["sustained_safe_ceiling"] == 4
        ramp = {r["level"]: r for r in result["sustained_ramp"]}
        # FakeProvider sleeps 0.01s/call; holding 0.08s must produce more than one
        # call per worker, proving this is a sustained hold, not a single burst.
        assert ramp[2]["calls_attempted"] > 2
        assert ramp[4]["calls_attempted"] > 4
        assert ramp[2]["error_rate"] == 0.0 and ramp[4]["error_rate"] == 0.0

    def test_aborts_at_the_last_level_that_stayed_clean(self, monkeypatch):
        c = _calibrator(FakeProvider(rate_limit_above=2), monkeypatch)
        result = c.sustained_ramp(levels=(2, 4, 8), seconds_per_level=0.08)

        assert result["sustained_safe_ceiling"] == 2
        assert result["sustained_stop_reason"].startswith("level 4:")
        ramp = {r["level"]: r for r in result["sustained_ramp"]}
        assert ramp[2]["rate_limited"] == 0
        assert ramp[4]["rate_limited"] > 0
        assert 8 not in ramp  # never attempted once level 4 breached the abort threshold

    def test_recommendation_is_set_even_without_a_prior_burst_calibrate(self, monkeypatch):
        c = _calibrator(FakeProvider(), monkeypatch)
        c.preflight(determinism_n=1)
        result = c.sustained_ramp(levels=(2,), seconds_per_level=0.05)

        assert c.report.recommendations["manifest_max_parallel_jobs_for_llm"] == result[
            "sustained_safe_ceiling"
        ]
        assert c.report.recommendations["manifest_max_parallel_jobs_for_llm_basis"] == "sustained_ramp"

    def test_sustained_result_overrides_the_burst_ramps_recommendation(self, monkeypatch):
        c = _calibrator(FakeProvider(rate_limit_above=2), monkeypatch)
        c.preflight(determinism_n=1)
        burst = c.calibrate(latency_samples=1, levels=(1, 2, 4), calls_per_level=4, pack_size=2)
        assert burst["safe_concurrency_ceiling"] == 2  # burst ceiling, pre-override

        c.sustained_ramp(levels=(2,), seconds_per_level=0.05)

        assert c.report.recommendations["manifest_max_parallel_jobs_for_llm"] == 2
        assert c.report.recommendations["manifest_max_parallel_jobs_for_llm_basis"] == "sustained_ramp"
        # calibrate()'s own findings stay on the report -- sustained only overrides the
        # final recommendation field, it doesn't erase the burst evidence.
        assert c.report.calibration["safe_concurrency_ceiling"] == 2
        assert "sustained_ramp" in c.report.calibration
