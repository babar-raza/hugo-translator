"""Provider probe + per-language / content-class comparison on the mission corpus (TC-APT-006).

Mission ``aspose-org-full-portfolio-translation-20260901``, plan section 6 / 6.1.

Runs the segment corpus (``build_mission_benchmark_corpus.py``) through the production
backends -- ``professionalize_llm`` via ``LLMModelBackend`` (packed prompts, hardened provider)
and ``m2m100_418m`` via the HuggingFace backend -- for every approved locale, and scores each
(model, language, domain) cell with content-free metrics:

  errors, empty_rate, same_as_source_rate, lang_match_rate (langdetect),
  identifier_preservation_rate (Aspose.X / CamelCase / backtick spans / shortcodes / HTML tags),
  length_ratio_median, seconds, tokens.

Health probes: ``BaseLLMProvider.health_check()`` for the LLM; model load + one-segment
translation for m2m100_418m.  Output: ``data/benchmark_corpus/results/mission_provider_comparison.json``
-- the comparison that feeds TC-APT-004b's qualification sample.  No translated text is stored.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.utils.atomic_write import atomic_write

DEFAULT_SEGMENTS = Path("data/benchmark_corpus/aspose_org_mission_segments.json")
DEFAULT_OUTPUT = Path("data/benchmark_corpus/results/mission_provider_comparison.json")
DEFAULT_CALIBRATION = Path("data/benchmark_corpus/results/professionalize_llm_calibration.json")
APPROVED_LOCALES = (
    "ar", "cs", "de", "el", "es", "fa", "fr", "he", "hi", "hu", "id", "it", "ja",
    "ko", "nl", "pl", "pt", "ro", "ru", "sv", "th", "tr", "uk", "vi", "zh",
)  # fmt: skip
LANGDETECT_ALIASES = {
    "zh-cn": "zh",
    "zh-tw": "zh",
    "nb": "no",
    "he": "he",
    "iw": "he",
    "id": "id",
    "in": "id",
}

_IDENT_RE = re.compile(
    r"Aspose\.[A-Za-z0-9.]+|\b(?:[A-Z][a-z0-9]+){2,}\b|`[^`]+`|\{\{[<%].*?[>%]\}\}|<[a-zA-Z][^>]*>"
)


def identifiers(text: str) -> list[str]:
    return _IDENT_RE.findall(text)


def detect_lang(text: str) -> str | None:
    try:
        import langdetect

        langdetect.DetectorFactory.seed = 0
        code = langdetect.detect(text)
        return LANGDETECT_ALIASES.get(code, code.split("-")[0])
    except Exception:
        return None


def score_pair(source: str, target: str, tgt_lang: str) -> dict[str, Any]:
    """Content-free metrics for one (source, translation) pair."""
    src_ids = identifiers(source)
    preserved = all(tok in target for tok in src_ids) if src_ids else True
    detected = detect_lang(target) if target.strip() else None
    ratio = len(target) / max(1, len(source))
    return {
        "empty": not target.strip(),
        "same_as_source": target.strip() == source.strip(),
        "lang_match": detected == tgt_lang if detected else False,
        "detected": detected,
        "identifiers_total": len(src_ids),
        "identifiers_preserved": preserved,
        "length_ratio": round(ratio, 3),
    }


def aggregate(cells: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(cells)
    if n == 0:
        return {"n": 0}
    ok = [c for c in cells if not c.get("error")]
    ratios = [c["length_ratio"] for c in ok if not c["empty"]]
    ident_cells = [c for c in ok if c["identifiers_total"]]
    return {
        "n": n,
        "errors": n - len(ok),
        "empty_rate": round(sum(1 for c in ok if c["empty"]) / max(1, len(ok)), 3),
        "same_as_source_rate": round(
            sum(1 for c in ok if c["same_as_source"]) / max(1, len(ok)), 3
        ),
        "lang_match_rate": round(sum(1 for c in ok if c["lang_match"]) / max(1, len(ok)), 3),
        "identifier_preservation_rate": round(
            sum(1 for c in ident_cells if c["identifiers_preserved"]) / len(ident_cells), 3
        )
        if ident_cells
        else None,
        "length_ratio_median": round(statistics.median(ratios), 3) if ratios else None,
        "seconds": round(sum(c.get("seconds", 0.0) for c in cells), 1),
        "input_tokens": sum(c.get("input_tokens", 0) for c in cells),
        "output_tokens": sum(c.get("output_tokens", 0) for c in cells),
    }


class Comparison:
    """Drives translate-fns over (lang x batches) and aggregates per model/lang/domain."""

    def __init__(self, segments: list[dict[str, Any]], langs: tuple[str, ...]) -> None:
        self.segments = segments
        self.langs = langs
        self.cells: dict[str, list[dict[str, Any]]] = defaultdict(list)  # model -> cells

    def run_model(
        self,
        model_id: str,
        translate: Callable[[list[str], str], tuple[list[str], int, int]],
        *,
        batch_size: int,
        concurrency: int = 1,
    ) -> dict[str, Any]:
        """``translate(texts, tgt_lang) -> (translations, in_tokens, out_tokens)``; exceptions become error cells."""
        t0 = time.perf_counter()
        batches = [
            (lang, self.segments[i : i + batch_size])
            for lang in self.langs
            for i in range(0, len(self.segments), batch_size)
        ]

        def work(item):
            lang, segs = item
            texts = [s["text_en"] for s in segs]
            started = time.perf_counter()
            try:
                out, in_tok, out_tok = translate(texts, lang)
            except Exception as exc:
                secs = time.perf_counter() - started
                return [
                    {
                        "model": model_id,
                        "lang": lang,
                        "domain": s["domain"],
                        "id": s["id"],
                        "error": f"{type(exc).__name__}: {exc}"[:160],
                        "seconds": secs / len(segs),
                    }
                    for s in segs
                ]
            secs = time.perf_counter() - started
            rows = []
            for s, tr in zip(segs, out):
                rows.append(
                    {
                        "model": model_id,
                        "lang": lang,
                        "domain": s["domain"],
                        "id": s["id"],
                        **score_pair(s["text_en"], tr or "", lang),
                        "seconds": secs / len(segs),
                        "input_tokens": in_tok // max(1, len(segs)),
                        "output_tokens": out_tok // max(1, len(segs)),
                    }
                )
            return rows

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            for rows in pool.map(work, batches):
                self.cells[model_id].extend(rows)
        return {
            "model": model_id,
            "cells": len(self.cells[model_id]),
            "seconds": round(time.perf_counter() - t0, 1),
        }

    def report(self) -> dict[str, Any]:
        out: dict[str, Any] = {"models": {}}
        for model_id, cells in self.cells.items():
            by_lang: dict[str, list] = defaultdict(list)
            by_domain: dict[str, list] = defaultdict(list)
            for c in cells:
                by_lang[c["lang"]].append(c)
                by_domain[c["domain"]].append(c)
            out["models"][model_id] = {
                "overall": aggregate(cells),
                "by_lang": {k: aggregate(v) for k, v in sorted(by_lang.items())},
                "by_domain": {k: aggregate(v) for k, v in sorted(by_domain.items())},
            }
        out["per_lang_verdict"] = self._verdicts(out["models"])
        return out

    @staticmethod
    def _verdicts(models: dict[str, Any]) -> dict[str, Any]:
        """Per language: which model has the higher quality proxy (lang match, identifiers, not same-as-source)."""
        verdict: dict[str, Any] = {}
        ids = list(models)
        if len(ids) < 2:
            return verdict
        langs = sorted({lang for m in ids for lang in models[m]["by_lang"]})
        for lang in langs:
            scores = {}
            for m in ids:
                a = models[m]["by_lang"].get(lang) or {}
                if not a or a.get("n", 0) == 0:
                    continue
                ident = a.get("identifier_preservation_rate")
                scores[m] = round(
                    a["lang_match_rate"]
                    - a["same_as_source_rate"]
                    - a["empty_rate"]
                    + (ident if ident is not None else 0.0)
                    - (a["errors"] / a["n"]),
                    3,
                )
            if scores:
                best = max(scores, key=scores.get)
                verdict[lang] = {"scores": scores, "better": best}
        return verdict


# ----------------------------------------------------------------------------- production backends
def production_backends(model_ids: list[str]):
    from src.model_runtime.loader import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.utils.config_loader import get_global_config

    registry = ModelRegistry("config/model_registry.yaml")
    loader = ModelLoader(registry, config=get_global_config())
    out = {}
    for mid in model_ids:
        t0 = time.perf_counter()
        backend = loader.load_model(mid)
        out[mid] = (backend, round(time.perf_counter() - t0, 1))
    return out


def health_probes(backends: dict[str, tuple[Any, float]]) -> dict[str, Any]:
    probes: dict[str, Any] = {}
    for mid, (backend, load_s) in backends.items():
        entry: dict[str, Any] = {"load_seconds": load_s, "backend": type(backend).__name__}
        provider = getattr(backend, "_provider", None)
        if provider is not None and hasattr(provider, "health_check"):
            t0 = time.perf_counter()
            entry["health_check"] = bool(provider.health_check())
            entry["health_seconds"] = round(time.perf_counter() - t0, 3)
        else:
            t0 = time.perf_counter()
            try:
                out, _, _ = backend.translate_with_token_counts(
                    ["Convert PDF to DOCX in C#"], "en", "de"
                )
                entry["health_check"] = bool(out and out[0].strip())
                entry["device"] = getattr(backend, "device", None)
            except Exception as exc:
                entry["health_check"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"[:160]
            entry["health_seconds"] = round(time.perf_counter() - t0, 3)
        probes[mid] = entry
    return probes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-006 provider probe + comparison")
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--models", default="professionalize_llm,m2m100_418m")
    parser.add_argument("--langs", default=",".join(APPROVED_LOCALES))
    parser.add_argument("--max-segments", type=int, default=0, help="0 = all")
    parser.add_argument("--llm-batch", type=int, default=8)
    parser.add_argument("--mt-batch", type=int, default=16)
    parser.add_argument(
        "--llm-concurrency",
        type=int,
        default=0,
        help="0 = read safe ceiling from the calibration report (fallback 1)",
    )
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    args = parser.parse_args(argv)

    segments = json.loads(args.segments.read_text(encoding="utf-8"))
    if args.max_segments:
        segments = segments[: args.max_segments]
    langs = tuple(x.strip() for x in args.langs.split(",") if x.strip())
    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    concurrency = args.llm_concurrency
    if concurrency <= 0:
        concurrency = 1
        if args.calibration.is_file():
            try:
                concurrency = int(
                    json.loads(args.calibration.read_text(encoding="utf-8"))["calibration"][
                        "safe_concurrency_ceiling"
                    ]
                )
            except Exception:
                concurrency = 1

    started = datetime.now(timezone.utc).isoformat()
    backends = production_backends(model_ids)
    probes = health_probes(backends)
    print(
        json.dumps(
            {
                "health_probes": probes,
                "segments": len(segments),
                "langs": len(langs),
                "llm_concurrency": concurrency,
            },
            indent=2,
            default=str,
        ),
        flush=True,
    )

    comp = Comparison(segments, langs)
    runs = []
    for mid, (backend, _) in backends.items():
        is_llm = getattr(backend, "_provider", None) is not None

        def _translate(texts, lang, _b=backend):
            return _b.translate_with_token_counts(texts, "en", lang)

        runs.append(
            comp.run_model(
                mid,
                _translate,
                batch_size=args.llm_batch if is_llm else args.mt_batch,
                concurrency=concurrency if is_llm else 1,
            )
        )
        print(json.dumps(runs[-1]), flush=True)
    report = {
        "taskcard": "TC-APT-006",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "segments": len(segments),
        "langs": list(langs),
        "llm_concurrency": concurrency,
        "health_probes": probes,
        "runs": runs,
        **comp.report(),
    }
    atomic_write(path=args.output, content=json.dumps(report, indent=2))
    for mid, m in report["models"].items():
        print(mid, json.dumps(m["overall"]))
    better = defaultdict(int)
    for v in report["per_lang_verdict"].values():
        better[v["better"]] += 1
    print("per-language verdicts:", dict(better), "->", args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
