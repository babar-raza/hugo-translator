"""
TC-RBTW-007/008: Model Family Smoke Test Runner
================================================
Tests each available model family with a single short sentence.
Proves models are loaded from registry local_path, not re-downloaded.

Rules:
- Do NOT copy, move, or download model files.
- Do NOT write translated output to production content.
- Do NOT run without per-operation timeouts.
- Stop after 3 consecutive failures in the same family.
- sentence-transformers are classified as non-translation models — not tested for translation.

Usage:
    python scripts/smoke_test_model_families.py

Output:
    data/evidence/rbtw/model_family_smoke_results.json
"""

import json
import os
import signal
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
EVIDENCE_DIR = PROJECT_ROOT / "data" / "evidence" / "rbtw"
PYTHONPATH_EXTRA = "C:/Users/prora/AppData/Roaming/Python/Python313/site-packages"
if PYTHONPATH_EXTRA not in sys.path:
    sys.path.insert(0, PYTHONPATH_EXTRA)

MODEL_SELECTION_TIMEOUT = 30   # seconds
MODEL_LOAD_TIMEOUT = 120       # seconds
TRANSLATION_TIMEOUT = 30       # seconds
MAX_CONSECUTIVE_FAILURES = 3

# Test sentence — short, ASCII-safe, meaningful for translation quality check
TEST_SENTENCE = "The document was saved successfully."

# ---------------------------------------------------------------------------
# Timeout helper (Windows-compatible: uses threading event)
# ---------------------------------------------------------------------------
class TimeoutError(Exception):
    pass

class _TimeoutThread(threading.Thread):
    def __init__(self, fn, timeout_secs, result_holder):
        super().__init__(daemon=True)
        self._fn = fn
        self._timeout = timeout_secs
        self._result = result_holder

    def run(self):
        try:
            self._result["value"] = self._fn()
            self._result["done"] = True
        except Exception as e:
            self._result["error"] = e
            self._result["done"] = True

def run_with_timeout(fn, timeout_secs, label="operation"):
    result = {"value": None, "error": None, "done": False}
    t = _TimeoutThread(fn, timeout_secs, result)
    t.start()
    t.join(timeout_secs)
    if not result["done"]:
        raise TimeoutError(f"{label} timed out after {timeout_secs}s")
    if result["error"]:
        raise result["error"]
    return result["value"]

# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------
def load_combined_registry():
    from src.model_runtime.registry import ModelRegistry
    paths = [
        PROJECT_ROOT / "config" / "model_registry.yaml",
        PROJECT_ROOT / "config" / "model_registry.discovered.yaml",
    ]
    existing = [p for p in paths if p.exists()]
    if not existing:
        raise FileNotFoundError("No registry files found")
    return ModelRegistry(existing)

# ---------------------------------------------------------------------------
# Smoke test for a single model
# ---------------------------------------------------------------------------
def smoke_test_model(model_id: str, src_lang: str, tgt_lang: str, registry) -> dict:
    """
    Load a model from registry and translate one sentence.
    Returns a result dict with all evidence fields.
    """
    result = {
        "model_id": model_id,
        "src_lang": src_lang,
        "tgt_lang": tgt_lang,
        "status": "NOT_RUN",
        "origin": "discovered" if model_id.startswith("disc_") else "curated",
        "backend": None,
        "local_path": None,
        "local_path_exists": None,
        "backend_load_status": None,
        "translation_status": None,
        "output": None,
        "duration_ms": None,
        "error_type": None,
        "error_message": None,
        "fallback_used": False,
        "fallback_reason": None,
        "token_usage": None,
        "api_calls_count": None,
    }

    # Get model info
    try:
        model_info = registry.get_model(model_id)
        result["backend"] = model_info.backend
        result["local_path"] = str(model_info.local_path) if model_info.local_path else None
        result["local_path_exists"] = (
            model_info.local_path.exists() if model_info.local_path else False
        )
    except Exception as e:
        result["status"] = "SKIP"
        result["error_type"] = "registry_lookup_failed"
        result["error_message"] = str(e)
        return result

    # Skip non-translation backends silently
    if model_info.backend in ("llm", "local_llm"):
        result["status"] = "SKIP"
        result["error_type"] = None
        result["error_message"] = f"LLM backend ({model_info.backend}) — no local translate, skipping"
        return result

    t0 = time.time()

    # Load model
    try:
        from src.model_runtime.loader import ModelLoader
        raw_config = {}  # minimal config for smoke test

        def _load():
            loader = ModelLoader(registry=registry, device="cpu", config=raw_config)
            return loader.load_model(model_id)

        backend_obj = run_with_timeout(_load, MODEL_LOAD_TIMEOUT, f"load {model_id}")
        result["backend_load_status"] = "OK"
    except TimeoutError as e:
        result["status"] = "FAIL"
        result["backend_load_status"] = "TIMEOUT"
        result["error_type"] = "model_load_timeout"
        result["error_message"] = str(e)
        result["duration_ms"] = int((time.time() - t0) * 1000)
        return result
    except Exception as e:
        result["status"] = "FAIL"
        result["backend_load_status"] = "ERROR"
        result["error_type"] = type(e).__name__
        result["error_message"] = str(e)
        result["duration_ms"] = int((time.time() - t0) * 1000)
        return result

    # Translate
    try:
        def _translate():
            return backend_obj.translate(
                TEST_SENTENCE, src_lang=src_lang, tgt_lang=tgt_lang
            )

        output = run_with_timeout(_translate, TRANSLATION_TIMEOUT, f"translate {model_id}")
        result["translation_status"] = "OK"
        result["output"] = str(output).strip() if output else None

        if not result["output"]:
            result["status"] = "FAIL"
            result["translation_status"] = "EMPTY_OUTPUT"
            result["error_type"] = "empty_translation_output"
            result["error_message"] = "Backend returned empty translation"
        else:
            result["status"] = "PASS"
    except TimeoutError as e:
        result["status"] = "FAIL"
        result["translation_status"] = "TIMEOUT"
        result["error_type"] = "translation_timeout"
        result["error_message"] = str(e)
    except Exception as e:
        result["status"] = "FAIL"
        result["translation_status"] = "ERROR"
        result["error_type"] = type(e).__name__
        result["error_message"] = str(e)

    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result


# ---------------------------------------------------------------------------
# Family test plans
# ---------------------------------------------------------------------------
FAMILY_TESTS = [
    # (family_label, model_ids_to_try, src, tgt, is_translation_model)
    {
        "family": "OPUS",
        "description": "Helsinki-NLP OPUS-MT seq2seq translation model (HF Marian)",
        # disc_tra_helsinki_nlp_opus_mt_en_fr: HF format, 862MB, en->fr verified
        # disc_ct2_en_fr_ct2_int8: CT2 int8, 76MB, en->fr verified (fallback)
        "candidates": [
            "disc_tra_helsinki_nlp_opus_mt_en_fr",
            "disc_ct2_en_fr_ct2_int8",
        ],
        "src": "en", "tgt": "fr",
        "is_translation_model": True,
        "skip_if_path_missing": True,
    },
    {
        "family": "M2M100",
        "description": "Facebook M2M100 multilingual translation model (HF)",
        # disc_tra_m2m100_418m_hf: HF format, 1.9GB, pytorch_model.bin verified
        "candidates": ["disc_tra_m2m100_418m_hf", "m2m100_418m"],
        "src": "en", "tgt": "de",
        "is_translation_model": True,
        "skip_if_path_missing": True,
    },
    {
        "family": "NLLB",
        "description": "Meta NLLB multilingual translation model",
        "candidates": ["nllb_200_600m", "nllb_200_1.3b"],
        "src": "en", "tgt": "es",
        "is_translation_model": True,
        "skip_if_path_missing": True,
    },
    {
        "family": "Ollama",
        "description": "Ollama LLM-based translation via API",
        "candidates": ["ollama_gemma3_12b", "ollama_qwen3_14b"],
        "src": "en", "tgt": "fr",
        "is_translation_model": True,
        "skip_if_backend_in": ["llm", "local_llm"],
    },
    {
        "family": "CTranslate2",
        "description": "CTranslate2 quantized translation model",
        "candidates": ["m2m100_418m_ct2"],
        "src": "en", "tgt": "fr",
        "is_translation_model": True,
        "skip_if_path_missing": True,
    },
    {
        "family": "GGUF",
        "description": "GGUF format model (requires llama.cpp backend)",
        "candidates": [],
        "src": "en", "tgt": "fr",
        "is_translation_model": True,
        "skip_reason": "No GGUF models registered in current registry",
    },
    {
        "family": "SentenceTransformers",
        "description": "Sentence embedding models — classification only, NOT translation models",
        "candidates": [
            "disc_tra_sentence_transformers_all_minilm_l6_v2",
            "disc_tra_sentence_transformers_paraphrase_multilingual_minilm_l12_v2",
        ],
        "src": "en", "tgt": "fr",
        "is_translation_model": False,
        "skip_reason": (
            "sentence-transformers produce embeddings, not translations. "
            "Classified as non-translation model. Correctly excluded from translation pipeline."
        ),
    },
]


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------
def main():
    print(f"\n{'='*70}")
    print("MODEL FAMILY SMOKE TEST RUNNER")
    print(f"Test sentence: '{TEST_SENTENCE}'")
    print(f"Model-load timeout: {MODEL_LOAD_TIMEOUT}s | Translate timeout: {TRANSLATION_TIMEOUT}s")
    print(f"{'='*70}\n")

    registry = load_combined_registry()
    print(f"Registry loaded: {len(registry)} models total\n")

    all_results = []
    run_id = f"smoke_{int(time.time())}"

    for plan in FAMILY_TESTS:
        family = plan["family"]
        print(f"--- {family} ---")
        print(f"  {plan['description']}")

        # Fixed skip: no candidates, or explicit skip_reason
        if plan.get("skip_reason") or not plan.get("candidates"):
            reason = plan.get("skip_reason", "no_candidates_in_registry")
            print(f"  SKIP: {reason}")
            all_results.append({
                "family": family,
                "status": "SKIP",
                "skip_reason": reason,
                "is_translation_model": plan["is_translation_model"],
                "candidates_tried": [],
            })
            continue

        consecutive_failures = 0
        family_result = {
            "family": family,
            "status": "NOT_RUN",
            "is_translation_model": plan["is_translation_model"],
            "candidates_tried": [],
        }

        for model_id in plan["candidates"]:
            # Check if model is in registry
            if model_id not in registry:
                print(f"  [{model_id}] NOT IN REGISTRY — skip")
                family_result["candidates_tried"].append({
                    "model_id": model_id,
                    "status": "SKIP",
                    "reason": "not_in_registry",
                })
                continue

            model_info = registry.get_model(model_id)

            # Skip if path explicitly missing and plan says so
            if plan.get("skip_if_path_missing"):
                if not model_info.local_path or not model_info.local_path.exists():
                    print(f"  [{model_id}] local_path missing — skip")
                    family_result["candidates_tried"].append({
                        "model_id": model_id,
                        "status": "SKIP",
                        "reason": "local_path_missing",
                        "local_path": str(model_info.local_path) if model_info.local_path else None,
                    })
                    continue

            # Skip if backend is LLM type
            if plan.get("skip_if_backend_in") and model_info.backend in plan["skip_if_backend_in"]:
                print(f"  [{model_id}] backend={model_info.backend} — skip (LLM, needs API endpoint)")
                family_result["candidates_tried"].append({
                    "model_id": model_id,
                    "status": "SKIP",
                    "reason": f"backend_{model_info.backend}_requires_api",
                })
                continue

            # Non-translation model — classify only
            if not plan["is_translation_model"]:
                lp = str(model_info.local_path) if model_info.local_path else None
                lp_exists = model_info.local_path.exists() if model_info.local_path else False
                print(f"  [{model_id}] CLASSIFIED as non-translation (embedding model)")
                print(f"    backend={model_info.backend} local_path_exists={lp_exists}")
                family_result["candidates_tried"].append({
                    "model_id": model_id,
                    "status": "CLASSIFIED_NOT_TRANSLATION",
                    "backend": model_info.backend,
                    "local_path": lp,
                    "local_path_exists": lp_exists,
                    "classification": "sentence_embedding_not_suitable_for_translation",
                })
                family_result["status"] = "CLASSIFIED"
                continue

            # Run smoke test
            print(f"  [{model_id}] testing (src={plan['src']} tgt={plan['tgt']}) ...")
            r = smoke_test_model(model_id, plan["src"], plan["tgt"], registry)
            family_result["candidates_tried"].append(r)

            if r["status"] == "PASS":
                print(f"    PASS  output='{r['output'][:60]}...' duration={r['duration_ms']}ms")
                print(f"    local_path_exists={r['local_path_exists']} origin={r['origin']}")
                family_result["status"] = "PASS"
                consecutive_failures = 0
                break  # One passing test is enough for a family
            elif r["status"] == "SKIP":
                print(f"    SKIP  {r['error_message']}")
            else:
                print(f"    FAIL  {r['error_type']}: {r['error_message'][:80]}")
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"  HARD STOP: {consecutive_failures} consecutive failures in {family}")
                    family_result["status"] = "FAIL_HARD_STOP"
                    break

        if family_result["status"] == "NOT_RUN":
            tried = family_result["candidates_tried"]
            if not tried:
                family_result["status"] = "SKIP"
                family_result["skip_reason"] = "no_candidates_tried"
            elif all(c.get("status") in ("SKIP", "CLASSIFIED_NOT_TRANSLATION") for c in tried):
                family_result["status"] = "SKIP"
                family_result["skip_reason"] = "all_candidates_skipped"
            elif any(c.get("status") == "FAIL" for c in tried):
                family_result["status"] = "FAIL"

        all_results.append(family_result)

    # Summary
    print(f"\n{'='*70}")
    print("SMOKE TEST SUMMARY")
    print(f"{'='*70}")
    for r in all_results:
        fam = r["family"]
        st = r["status"]
        print(f"  {fam:<22} {st}")

    pass_ct = sum(1 for r in all_results if r["status"] == "PASS")
    skip_ct = sum(1 for r in all_results if r["status"] in ("SKIP", "CLASSIFIED"))
    fail_ct = sum(1 for r in all_results if r["status"] in ("FAIL", "FAIL_HARD_STOP"))
    print(f"\nPASS={pass_ct} SKIP/CLASSIFIED={skip_ct} FAIL={fail_ct}")

    # Write evidence
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE_DIR / "model_family_smoke_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "agent_name": "hugo-translator",
            "test_sentence": TEST_SENTENCE,
            "model_selection_timeout_s": MODEL_SELECTION_TIMEOUT,
            "model_load_timeout_s": MODEL_LOAD_TIMEOUT,
            "translation_timeout_s": TRANSLATION_TIMEOUT,
            "registry_total_models": len(registry),
            "pass": pass_ct,
            "skip": skip_ct,
            "fail": fail_ct,
            "results": all_results,
        }, f, indent=2, default=str)
    print(f"\nEvidence written: {out}")
    return 0 if fail_ct == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
