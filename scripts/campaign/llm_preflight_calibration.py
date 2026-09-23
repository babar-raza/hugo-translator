"""Preflight and throughput calibration for ``llm.professionalize.com`` (TC-APT-028, plan section 6.0).

Mission ``aspose-org-full-portfolio-translation-20260901``.  Runs FIRST -- before TC-APT-004's
circuit-breaker thresholds are finalized and before TC-APT-004b's qualification -- because the
registry's ``timeout_seconds: 300`` / ``max_tokens: 6000`` and any concurrency assumption were
never verified against the live service.

Everything here goes through the production wire path (``ModelRegistry`` -> ``LLMProviderConfig``
-> ``create_provider`` -> ``BaseLLMProvider.generate``) with the production system prompts, so
the numbers describe what campaigns will actually experience.

Preflight (hard stops abort qualification):
  1. the ``api_key_env`` variable resolves (logged as resolved / not resolved -- never its value)
  2. ``health_check()`` succeeds
  3. model-identity canary: fixed prompt -> response sha256, saved as the TC-APT-021 baseline;
     ``/models`` capability probe records whether a version-locked identifier is exposed
  4. representative segments (placeholder tokens, RTL, fenced code, long technical paragraph):
     well-formed, not truncated, placeholders/code preserved
  5. temperature-0 determinism: the same prompt N times -> distinct-output count

Calibration:
  1. latency p50/p95/p99 per content class (short metadata, long prose, table-heavy, placeholder-heavy)
  2. concurrency ramp (1, 2, 4, 8, 16) -> safe sustained ceiling (zero errors, bounded p95 inflation)
  3. tokens per translated source word
  4. batch packing vs single calls (latency, tokens)
  5. circuit-breaker threshold recommendation for TC-APT-004

Output: ``data/benchmark_corpus/results/professionalize_llm_calibration.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.model_runtime.llm_backend import DEFAULT_SYSTEM_PROMPT, LANGUAGE_NAMES, LLMModelBackend
from src.translation_engine.extractor.placeholder_manager import PlaceholderManager
from src.utils.atomic_write import atomic_write

DEFAULT_MODEL_ID = "professionalize_llm"
DEFAULT_OUTPUT = Path("data/benchmark_corpus/results/professionalize_llm_calibration.json")
DEFAULT_BASELINE = Path("data/runtime/llm_identity/professionalize_llm_canary_baseline.json")

#: Fixed, deterministic canary prompt (TC-APT-021) -- single source of truth lives in
#: src.model_runtime.model_identity; the baseline hash is only comparable to itself.
from src.model_runtime.model_identity import CANARY_SYSTEM, CANARY_USER  # noqa: E402

RTL_SEGMENT = "Aspose.Cells for .NET reads XLSX files. See the `Workbook` class."
CODE_SEGMENT = (
    'Load the workbook as shown:\n\n```csharp\nvar wb = new Workbook("in.xlsx");\n'
    'wb.Save("out.pdf");\n```\n\nThe fenced block above must stay unchanged.'
)
PLACEHOLDER_SOURCE = (
    'Use {{< shortcode key="value" >}} to embed the sample, then run {{% include "x.md" %}} '
    "before reading the API reference for Aspose.Words."
)
SHORT_METADATA = "Convert PDF to DOCX in C#"
TABLE_SEGMENT = (
    "| Format | Read | Write |\n|---|---|---|\n| XLSX | Yes | Yes |\n| CSV | Yes | Yes |\n"
    "| ODS | Yes | No |\n\nThe table lists supported formats."
)
LONG_PARAGRAPH_UNIT = (
    "The rendering pipeline resolves each shape's effective style by walking the inheritance "
    "chain from the slide master through the layout to the shape itself, applying theme colors "
    "and font substitutions where the target platform lacks the referenced typeface. "
)
#: Distinct technical sentences; long-prose probes cycle through these so the input is realistic
#: prose rather than one sentence repeated (a repeated sentence provoked a runaway generation to
#: the 6000-token cap on 2026-09-02 -- a real endpoint behaviour recorded in the TC-APT-028 evidence,
#: but not what campaign content looks like).
LONG_PROSE_SENTENCES = (
    LONG_PARAGRAPH_UNIT.strip(),
    "When a workbook contains external links, the loader resolves each reference lazily and "
    "records unresolved targets in the diagnostics collection instead of failing the load.",
    "Page margins are expressed in points, and the layout engine converts them to device units "
    "only at render time so that the same document produces identical output on every DPI.",
    "The converter preserves bookmarks, named destinations, and outline entries, remapping "
    "their page indices after any pages are removed or reordered by the optimisation pass.",
    "Font embedding honours the licensing flags in the OS/2 table; restricted faces are "
    "substituted with the closest metric-compatible fallback and the substitution is logged.",
    "Incremental save appends only the modified objects and a new cross-reference section, "
    "which keeps large documents fast to update but requires a full save to reclaim space.",
    "Digital signatures are validated against the embedded certificate chain, and a detached "
    "timestamp token, when present, is checked before the signing time is trusted.",
    "The mail-merge engine evaluates field codes in document order, so a field that depends on "
    "a later value must reference it through a bookmark rather than by position.",
)


def long_prose(words: int) -> str:
    """Realistic varied technical prose of roughly ``words`` words."""
    out: list[str] = []
    count = 0
    i = 0
    while count < words:
        sentence = LONG_PROSE_SENTENCES[i % len(LONG_PROSE_SENTENCES)]
        out.append(sentence)
        count += len(sentence.split())
        i += 1
    return " ".join(out)


@dataclass
class CallResult:
    ok: bool
    seconds: float
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    rate_limited: bool = False


@dataclass
class Report:
    model_id: str
    started_at: str
    preflight: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    hard_stops: list[str] = field(default_factory=list)
    recommendations: dict[str, Any] = field(default_factory=dict)
    finished_at: str = ""
    terminal_reason: str = "running"
    timed_out: bool = False
    last_progress_at: str = ""
    stage: str = "starting"

    def as_dict(self) -> dict[str, Any]:
        return {
            "taskcard": "TC-APT-028",
            "model_id": self.model_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "hard_stops": self.hard_stops,
            "preflight": self.preflight,
            "calibration": self.calibration,
            "recommendations": self.recommendations,
            "terminal_reason": self.terminal_reason,
            "timed_out": self.timed_out,
            "last_progress_at": self.last_progress_at,
            "stage": self.stage,
        }


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "n": 0}
    s = sorted(values)

    def pct(p: float) -> float:
        k = max(0, min(len(s) - 1, round(p * (len(s) - 1))))
        return round(s[k], 3)

    return {
        "p50": pct(0.50),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "n": len(s),
        "mean": round(statistics.fmean(s), 3),
    }


def _is_rate_limit(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "429" in text or "rate limit" in text or "ratelimit" in text or "too many requests" in text
    )


class LLMCalibrator:
    """Drives one provider through preflight + calibration; provider is injectable for tests."""

    def __init__(
        self,
        provider: Any,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        api_key_env: str | None = "litellm_key",
        max_tokens: int = 6000,
        model_name: str = "recommended",
        batch_prompt_builder: Callable[[str, str, int], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        long_probe_words: int = 750,
        sweep_words: tuple[int, ...] = (300, 600, 900, 1200, 1800),
    ) -> None:
        self.provider = provider
        self.model_id = model_id
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self.model_name = model_name
        self._batch_prompt = batch_prompt_builder or _default_batch_prompt
        self.long_probe_words = long_probe_words
        self.sweep_words = tuple(sweep_words)
        self._sleep = sleep
        self.report = Report(model_id=model_id, started_at=datetime.now(timezone.utc).isoformat())

    # ------------------------------------------------------------------ primitives
    def call(self, system_prompt: str, user_text: str) -> CallResult:
        t0 = time.perf_counter()
        try:
            text, in_tok, out_tok = self.provider.generate(system_prompt, user_text)
            return CallResult(True, time.perf_counter() - t0, text, in_tok, out_tok)
        except Exception as exc:  # the provider raises typed/untyped errors; record, never hide
            return CallResult(
                False,
                time.perf_counter() - t0,
                error=f"{type(exc).__name__}: {exc}"[:300],
                rate_limited=_is_rate_limit(exc),
            )

    @staticmethod
    def translation_prompt(tgt_lang: str, src_lang: str = "en") -> str:
        return DEFAULT_SYSTEM_PROMPT.format(
            src_lang_name=LANGUAGE_NAMES.get(src_lang, src_lang.upper()),
            tgt_lang_name=LANGUAGE_NAMES.get(tgt_lang, tgt_lang.upper()),
        )

    # ------------------------------------------------------------------ preflight
    def preflight(self, *, determinism_n: int = 10) -> dict[str, Any]:
        self.report.stage = "preflight"
        self.report.last_progress_at = datetime.now(timezone.utc).isoformat()
        pf: dict[str, Any] = {}
        stops = self.report.hard_stops

        # 1) key resolution (presence only)
        resolved = bool(self.api_key_env and os.environ.get(self.api_key_env))
        pf["api_key_env"] = self.api_key_env
        pf["api_key_resolved"] = resolved
        if self.api_key_env and not resolved:
            stops.append(f"api key env var {self.api_key_env!r} does not resolve")

        # 2) health check
        t0 = time.perf_counter()
        # Calibration must not consume the production retry budget.  Use one
        # direct provider attempt; production workers retain governed retries.
        try:
            generate_once = getattr(self.provider, "_generate_impl", self.provider.generate)
            text, _, _ = generate_once("Respond with exactly: OK", "Health check")
            healthy = bool(text.strip())
        except Exception:
            healthy = False
        pf["health_check"] = {"ok": healthy, "seconds": round(time.perf_counter() - t0, 3)}
        if not healthy:
            stops.append("health_check failed")
            return pf

        # 3) model identity canary + capability probe
        canary = self.call(CANARY_SYSTEM, CANARY_USER)
        pf["canary"] = {
            "ok": canary.ok,
            "response_sha256": hashlib.sha256(canary.text.encode("utf-8")).hexdigest()
            if canary.ok
            else None,
            "echo_exact": canary.ok and canary.text.strip() == CANARY_USER,
            "seconds": round(canary.seconds, 3),
            "error": canary.error or None,
        }
        if not canary.ok:
            stops.append(f"canary call failed: {canary.error}")
        pf["models_probe"] = self._models_probe()

        # 4) representative segments
        pm = PlaceholderManager()
        protected, pmap = pm.protect(PLACEHOLDER_SOURCE, [r"\{\{<.*?>\}\}", r"\{\{%.*?%\}\}"])
        # Hard-stop probe sized to ~2x the production per-call budget
        # (ast_translation_max_tokens_per_batch=512 tokens, MAX_SEGMENTS_PER_PROMPT=8):
        # the pipeline never sends a single 2,400-token paragraph, so the qualification
        # probe must not either. The ceiling sweep below records long-input behaviour.
        long_para = long_prose(self.long_probe_words)
        segments = {
            "placeholder_tokens": (protected, "de"),
            "rtl_arabic": (RTL_SEGMENT, "ar"),
            "fenced_code": (CODE_SEGMENT, "fr"),
            "long_technical_paragraph": (long_para, "es"),
        }
        seg_out: dict[str, Any] = {}
        for name, (text, lang) in segments.items():
            res = self.call(self.translation_prompt(lang), text)
            checks: dict[str, bool] = {"ok": res.ok, "non_empty": bool(res.text.strip())}
            if name == "placeholder_tokens":
                checks["placeholders_preserved"] = all(tok in res.text for tok in pmap)
            if name == "fenced_code":
                checks["fence_preserved"] = res.text.count("```") == CODE_SEGMENT.count("```")
                checks["code_line_intact"] = 'new Workbook("in.xlsx")' in res.text
            if name == "long_technical_paragraph":
                ratio = len(res.text) / max(1, len(text))
                hit_cap = res.output_tokens >= self.max_tokens
                checks["not_truncated"] = ratio >= 0.6 and not hit_cap
                checks["length_ratio"] = round(ratio, 3)  # type: ignore[assignment]
                checks["hit_max_tokens_info"] = (
                    "yes" if hit_cap else "no"
                )  # informational (non-bool)
            if name == "rtl_arabic":
                checks["has_arabic_script"] = any("؀" <= ch <= "ۿ" for ch in res.text)
                checks["identifier_kept"] = "Workbook" in res.text and "Aspose.Cells" in res.text
            seg_out[name] = {
                **checks,
                "seconds": round(res.seconds, 3),
                "input_tokens": res.input_tokens,
                "output_tokens": res.output_tokens,
                "error": res.error or None,
            }
            failed = [k for k, v in checks.items() if isinstance(v, bool) and not v]
            if failed:
                stops.append(f"representative segment {name}: {failed}")
        pf["representative_segments"] = seg_out

        # 4b) length-ceiling sweep (informational, never a hard stop): at which input size
        # does the endpoint start truncating / running to the output cap?
        sweep: list[dict[str, Any]] = []
        max_safe = 0
        for words in self.sweep_words:
            text = long_prose(words)
            res = self.call(self.translation_prompt("es"), text)
            ratio = len(res.text) / max(1, len(text)) if res.ok else 0.0
            hit_cap = res.ok and res.output_tokens >= self.max_tokens
            healthy = res.ok and ratio >= 0.6 and not hit_cap
            sweep.append(
                {
                    "words": words,
                    "ok": res.ok,
                    "seconds": round(res.seconds, 3),
                    "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "length_ratio": round(ratio, 3),
                    "hit_max_tokens": hit_cap,
                    "healthy": healthy,
                    "error": res.error or None,
                }
            )
            if healthy:
                max_safe = words
            else:
                break  # no point escalating past the first degradation
        pf["long_input_sweep"] = {"probes": sweep, "max_safe_words": max_safe}

        # 5) determinism at temperature 0
        hashes: list[str] = []
        errors = 0
        for _ in range(determinism_n):
            res = self.call(self.translation_prompt("de"), SHORT_METADATA)
            if res.ok:
                hashes.append(hashlib.sha256(res.text.strip().encode("utf-8")).hexdigest())
            else:
                errors += 1
        distinct = len(set(hashes))
        pf["determinism"] = {
            "n": determinism_n,
            "successful": len(hashes),
            "errors": errors,
            "distinct_outputs": distinct,
            "byte_identical_rate": round(
                (max(hashes.count(h) for h in set(hashes)) / len(hashes)), 3
            )
            if hashes
            else 0.0,
            "is_deterministic": distinct == 1 and errors == 0,
        }
        self.report.preflight = pf
        return pf

    def _models_probe(self) -> dict[str, Any]:
        client = getattr(self.provider, "_client", None)
        if client is None or not hasattr(client, "models"):
            return {"supported": False, "reason": "provider exposes no models endpoint"}
        try:
            listed = client.models.list(timeout=15)
            ids = sorted(str(getattr(m, "id", m)) for m in getattr(listed, "data", listed))
        except Exception as exc:
            return {"supported": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
        alias = self.model_name
        return {
            "supported": True,
            "model_ids": ids[:50],
            "count": len(ids),
            "configured_alias": alias,
            "alias_listed": alias in ids,
            "version_locked_candidates": [
                i for i in ids if i != alias and any(c.isdigit() for c in i)
            ][:20],
        }

    # ------------------------------------------------------------------ calibration
    def calibrate(
        self,
        *,
        latency_samples: int = 6,
        levels: tuple[int, ...] = (1, 2, 4, 8, 16),
        calls_per_level: int = 8,
        pack_size: int = 8,
    ) -> dict[str, Any]:
        self.report.stage = "calibration"
        self.report.last_progress_at = datetime.now(timezone.utc).isoformat()
        cal: dict[str, Any] = {}
        classes = {
            "short_metadata": SHORT_METADATA,
            "long_prose": long_prose(300),
            "table_heavy": TABLE_SEGMENT,
            "placeholder_heavy": PlaceholderManager().protect(
                PLACEHOLDER_SOURCE, [r"\{\{<.*?>\}\}", r"\{\{%.*?%\}\}"]
            )[0],
        }
        # 1) latency distribution per content class + 3) token cost
        latency: dict[str, Any] = {}
        total_in = total_out = 0
        total_words = 0
        for name, text in classes.items():
            secs: list[float] = []
            errs = 0
            for _ in range(latency_samples):
                res = self.call(self.translation_prompt("de"), text)
                if res.ok:
                    secs.append(res.seconds)
                    total_in += res.input_tokens
                    total_out += res.output_tokens
                    total_words += len(text.split())
                else:
                    errs += 1
            latency[name] = {
                **_percentiles(secs),
                "errors": errs,
                "source_words": len(text.split()),
            }
        cal["latency_by_class_seconds"] = latency
        cal["token_cost"] = {
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "source_words": total_words,
            "tokens_per_source_word": round((total_in + total_out) / total_words, 3)
            if total_words
            else None,
            "input_tokens_per_source_word": round(total_in / total_words, 3)
            if total_words
            else None,
        }

        # 2) concurrency ramp
        ramp: list[dict[str, Any]] = []
        base_p95: float | None = None
        safe = 1
        stop_reason = None
        for level in levels:
            with ThreadPoolExecutor(max_workers=level) as pool:
                results = list(
                    pool.map(
                        lambda _i: self.call(self.translation_prompt("fr"), long_prose(120)),
                        range(calls_per_level),
                    )
                )
            secs = [r.seconds for r in results if r.ok]
            errors = [r.error for r in results if not r.ok]
            rate_limited = sum(1 for r in results if r.rate_limited)
            pct = _percentiles(secs)
            if base_p95 is None and secs:
                base_p95 = pct["p95"]
            inflation = round(pct["p95"] / base_p95, 3) if (base_p95 and secs) else None
            entry = {
                "level": level,
                "calls": calls_per_level,
                "errors": len(errors),
                "rate_limited": rate_limited,
                "p95_inflation_vs_level1": inflation,
                **pct,
                "sample_errors": errors[:3],
            }
            ramp.append(entry)
            if errors or (inflation is not None and inflation > 2.0):
                stop_reason = f"level {level}: errors={len(errors)} rate_limited={rate_limited} p95_inflation={inflation}"
                break
            safe = level
        cal["concurrency_ramp"] = ramp
        cal["safe_concurrency_ceiling"] = safe
        cal["ramp_stop_reason"] = stop_reason

        # 4) batch packing efficiency
        segs = [f"{SHORT_METADATA} variant {i} for Aspose.Words" for i in range(pack_size)]
        packed_user = "\n".join(f"<<<SEG_{i + 1}>>> {s}" for i, s in enumerate(segs))
        packed = self.call(self._batch_prompt("en", "de", pack_size), packed_user)
        parsed = LLMModelBackend._parse_packed_output(packed.text, pack_size) if packed.ok else None
        singles = [self.call(self.translation_prompt("de"), s) for s in segs]
        single_secs = sum(r.seconds for r in singles)
        cal["batch_packing"] = {
            "pack_size": pack_size,
            "packed_ok": packed.ok and parsed is not None,
            "packed_seconds": round(packed.seconds, 3),
            "packed_tokens": packed.input_tokens + packed.output_tokens,
            "singles_total_seconds": round(single_secs, 3),
            "singles_total_tokens": sum(r.input_tokens + r.output_tokens for r in singles),
            "singles_errors": sum(1 for r in singles if not r.ok),
            "speedup_x": round(single_secs / packed.seconds, 2)
            if packed.ok and packed.seconds
            else None,
        }
        self.report.calibration = cal
        self.report.recommendations = self._recommend(cal)
        return cal

    # ------------------------------------------------------------- sustained (TC-APT-064)
    def sustained_ramp(
        self,
        *,
        levels: tuple[int, ...] = (16, 32, 48, 64),
        seconds_per_level: float = 450.0,
        error_rate_abort_threshold: float = 0.05,
        rate_limited_abort_threshold: float = 0.02,
    ) -> dict[str, Any]:
        """Hold N concurrent in-flight calls for a FIXED WALL-CLOCK DURATION per level.

        `calibrate()`'s concurrency ramp fires exactly `calls_per_level` calls once per
        level (a burst) -- it proves the endpoint can absorb a momentary spike, not that
        it holds up under sustained load, which is the plan's explicit distinction
        ("16 was where the burst ramp *stopped*, not a found ceiling"). Each worker here
        loops call-after-call for the full window so the level is genuinely held, not
        just touched. Escalates only while both the error rate and the rate-limited rate
        stay under threshold; a breach stops the ramp at the last level that held clean
        (plan SS0.11 item 5 abort criteria), it never forces a higher level through.
        """
        results: list[dict[str, Any]] = []
        stop_reason: str | None = None
        safe_level = 0
        for level in levels:
            deadline = time.monotonic() + seconds_per_level
            lock = threading.Lock()
            counters = {"attempted": 0, "ok": 0, "failed": 0, "rate_limited": 0}
            secs: list[float] = []
            errors: list[str] = []

            def worker() -> None:
                while time.monotonic() < deadline:
                    res = self.call(self.translation_prompt("fr"), long_prose(120))
                    with lock:
                        counters["attempted"] += 1
                        if res.ok:
                            counters["ok"] += 1
                            secs.append(res.seconds)
                        else:
                            counters["failed"] += 1
                            if res.rate_limited:
                                counters["rate_limited"] += 1
                            if len(errors) < 5:
                                errors.append(res.error)

            threads = [threading.Thread(target=worker) for _ in range(level)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            attempted = counters["attempted"]
            error_rate = round(counters["failed"] / attempted, 4) if attempted else 1.0
            rate_limited_rate = round(counters["rate_limited"] / attempted, 4) if attempted else 0.0
            entry = {
                "level": level,
                "seconds_held": seconds_per_level,
                "calls_attempted": attempted,
                "calls_ok": counters["ok"],
                "calls_failed": counters["failed"],
                "rate_limited": counters["rate_limited"],
                "error_rate": error_rate,
                "rate_limited_rate": rate_limited_rate,
                **_percentiles(secs),
                "sample_errors": errors,
            }
            results.append(entry)
            if error_rate > error_rate_abort_threshold or rate_limited_rate > rate_limited_abort_threshold:
                stop_reason = (
                    f"level {level}: error_rate={error_rate} "
                    f"rate_limited_rate={rate_limited_rate} exceeded abort threshold "
                    f"(error>{error_rate_abort_threshold} or rate_limited>{rate_limited_abort_threshold})"
                )
                break
            safe_level = level
        payload = {
            "sustained_ramp": results,
            "sustained_safe_ceiling": safe_level,
            "sustained_stop_reason": stop_reason,
        }
        self.report.calibration["sustained_ramp"] = results
        self.report.calibration["sustained_safe_ceiling"] = safe_level
        self.report.calibration["sustained_stop_reason"] = stop_reason
        # Sustained evidence supersedes the burst ramp's recommendation (plan TC-APT-064:
        # "burst calibration is not evidence of a sustained ceiling"), whether or not
        # calibrate() ran first in this invocation.
        self.report.recommendations["manifest_max_parallel_jobs_for_llm"] = safe_level
        self.report.recommendations["manifest_max_parallel_jobs_for_llm_basis"] = "sustained_ramp"
        return payload

    def _recommend(self, cal: dict[str, Any]) -> dict[str, Any]:
        ramp = cal.get("concurrency_ramp", [])
        total_calls = sum(r["calls"] for r in ramp) + sum(
            v["n"] + v["errors"] for v in cal["latency_by_class_seconds"].values()
        )
        total_errors = sum(r["errors"] for r in ramp) + sum(
            v["errors"] for v in cal["latency_by_class_seconds"].values()
        )
        observed_failure_rate = round(total_errors / total_calls, 4) if total_calls else None
        p99 = max(
            (v.get("p99", 0.0) for v in cal["latency_by_class_seconds"].values()), default=0.0
        )
        return {
            "manifest_max_parallel_jobs_for_llm": cal["safe_concurrency_ceiling"],
            "circuit_breaker": {
                "consecutive_failure_trip": 5,
                "window_calls": 20,
                "window_failure_ratio_trip": 0.5,
                "observed_baseline_failure_rate": observed_failure_rate,
                "cooldown_seconds": 60,
                "cooldown_cap_seconds": 600,
                "per_call_timeout_seconds_suggested": int(min(300, max(60, p99 * 4)))
                if p99
                else 300,
                "rationale": (
                    "observed baseline failure rate is far below the 50%/20-call window trip; "
                    "5 consecutive failures stays as the trip because a healthy endpoint showed "
                    f"{total_errors} failures in {total_calls} calibration calls"
                ),
            },
            "batch_packing_recommended": bool(cal["batch_packing"].get("packed_ok"))
            and (cal["batch_packing"].get("speedup_x") or 0) > 1.2,
        }

    # ------------------------------------------------------------------ persistence
    def finish(self, output: Path, baseline_path: Path | None) -> dict[str, Any]:
        self.report.finished_at = datetime.now(timezone.utc).isoformat()
        if self.report.terminal_reason == "running":
            self.report.terminal_reason = "completed" if not self.report.hard_stops else "failed"
        self.report.last_progress_at = self.report.finished_at
        payload = self.report.as_dict()
        atomic_write(path=output, content=json.dumps(payload, indent=2))
        canary = self.report.preflight.get("canary") or {}
        if baseline_path is not None and canary.get("ok"):
            existing = None
            if baseline_path.is_file():
                try:
                    existing = json.loads(baseline_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    existing = None
            if existing is None:
                atomic_write(
                    path=baseline_path,
                    content=json.dumps(
                        {
                            "model_id": self.model_id,
                            "configured_alias": self.model_name,
                            "canary_system": CANARY_SYSTEM,
                            "canary_user": CANARY_USER,
                            "response_sha256": canary["response_sha256"],
                            "echo_exact": canary["echo_exact"],
                            "models_probe": self.report.preflight.get("models_probe"),
                            "recorded_at": self.report.finished_at,
                        },
                        indent=2,
                    ),
                )
                payload["baseline_written"] = baseline_path.as_posix()
            else:
                payload["baseline_matches"] = (
                    existing.get("response_sha256") == canary["response_sha256"]
                )
                payload["baseline_path"] = baseline_path.as_posix()
        return payload


def _default_batch_prompt(src: str, tgt: str, n: int) -> str:
    """The production packed-batch system prompt, via LLMModelBackend (no provider needed)."""
    from src.model_runtime.registry import ModelInfo

    stub = ModelInfo(
        model_id="calibration_stub",
        name="stub",
        backend="llm",
        supported_pairs="all",
        model_size_mb=0,
        min_ram_gb=0,
        optimal_device="api",
    )
    return LLMModelBackend(stub, "api")._build_batch_system_prompt(src, tgt, n)


def build_provider(
    model_id: str, registry_path: Path, *, timeout_seconds: int | None = None
) -> tuple[Any, Any]:
    from src.model_runtime.contracts import LLMProviderConfig
    from src.model_runtime.llm_providers import create_provider
    from src.model_runtime.registry import ModelRegistry

    info = ModelRegistry(registry_path).get_model(model_id)
    config = LLMProviderConfig.from_model_info(info)
    if timeout_seconds is not None:
        config = config.model_copy(update={"timeout_seconds": int(timeout_seconds)})
    return create_provider(config), config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-028 LLM preflight + calibration")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--registry", type=Path, default=Path("config/model_registry.yaml"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--determinism-n", type=int, default=10)
    parser.add_argument("--latency-samples", type=int, default=6)
    parser.add_argument("--levels", default="1,2,4,8,16")
    parser.add_argument("--calls-per-level", type=int, default=8)
    parser.add_argument("--skip-calibration", action="store_true")
    parser.add_argument("--long-probe-words", type=int, default=750)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="per-call timeout for calibration (registry default is 300; a hung request must not stall the run)",
    )
    parser.add_argument("--sweep-words", default="300,600,900,1200,1800")
    parser.add_argument(
        "--force-calibration",
        action="store_true",
        help="collect throughput numbers even when preflight has hard stops (they stay recorded)",
    )
    parser.add_argument(
        "--sustained",
        action="store_true",
        help=(
            "TC-APT-064: after the burst ramp, hold each --sustained-levels concurrency "
            "level for --seconds-per-level continuously (not a fixed call count) -- the "
            "plan's distinction between a burst spike and a proven sustained ceiling"
        ),
    )
    parser.add_argument("--sustained-levels", default="16,32,48,64")
    parser.add_argument(
        "--seconds-per-level",
        type=float,
        default=450.0,
        help="wall-clock seconds to hold each sustained level (default 450s x 4 levels = 30 min)",
    )
    parser.add_argument("--sustained-error-rate-abort", type=float, default=0.05)
    parser.add_argument("--sustained-rate-limited-abort", type=float, default=0.02)
    args = parser.parse_args(argv)

    provider, config = build_provider(
        args.model_id, args.registry, timeout_seconds=args.timeout_seconds
    )
    cal = LLMCalibrator(
        provider,
        model_id=args.model_id,
        api_key_env=config.api_key_env,
        max_tokens=config.max_tokens,
        model_name=config.model_name,
        long_probe_words=args.long_probe_words,
        sweep_words=tuple(int(x) for x in args.sweep_words.split(",") if x.strip()),
    )
    try:
        pf = cal.preflight(determinism_n=args.determinism_n)
    except TimeoutError as exc:
        cal.report.terminal_reason = "timed_out"
        cal.report.timed_out = True
        cal.report.hard_stops.append(str(exc))
        cal.finish(args.output, args.baseline)
        return 2
    except Exception as exc:
        cal.report.terminal_reason = "failed"
        cal.report.hard_stops.append(f"{type(exc).__name__}: {exc}"[:300])
        cal.finish(args.output, args.baseline)
        raise
    print(
        json.dumps(
            {
                "preflight_hard_stops": cal.report.hard_stops,
                "determinism": pf.get("determinism"),
                "models_probe": pf.get("models_probe"),
            },
            indent=2,
            default=str,
        )
    )
    if cal.report.hard_stops and not args.force_calibration:
        cal.finish(args.output, args.baseline)
        print("PREFLIGHT HARD STOP -- calibration not run")
        return 2
    if not args.skip_calibration:
        levels = tuple(int(x) for x in args.levels.split(",") if x.strip())
        result = cal.calibrate(
            latency_samples=args.latency_samples,
            levels=levels,
            calls_per_level=args.calls_per_level,
        )
        print(
            json.dumps(
                {
                    "safe_concurrency_ceiling": result["safe_concurrency_ceiling"],
                    "ramp_stop_reason": result["ramp_stop_reason"],
                    "token_cost": result["token_cost"],
                    "batch_packing": result["batch_packing"],
                },
                indent=2,
                default=str,
            )
        )
    if args.sustained:
        sustained_levels = tuple(int(x) for x in args.sustained_levels.split(",") if x.strip())
        sresult = cal.sustained_ramp(
            levels=sustained_levels,
            seconds_per_level=args.seconds_per_level,
            error_rate_abort_threshold=args.sustained_error_rate_abort,
            rate_limited_abort_threshold=args.sustained_rate_limited_abort,
        )
        print(
            json.dumps(
                {
                    "sustained_safe_ceiling": sresult["sustained_safe_ceiling"],
                    "sustained_stop_reason": sresult["sustained_stop_reason"],
                    "sustained_ramp": sresult["sustained_ramp"],
                },
                indent=2,
                default=str,
            )
        )
    payload = cal.finish(args.output, args.baseline)
    print(
        f"report -> {args.output}; baseline: {payload.get('baseline_written') or payload.get('baseline_path')}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
