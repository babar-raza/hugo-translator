"""
LLM meaning-fidelity judge (HT-QUALITY-GATES-001 Part 22, plan 5.4 item 3).

SemanticSimilarityValidator (embedding cosine similarity) is too coarse for the
specific failure class this session's investigation found repeatedly: systematic
homonym mistranslation ("tables"->"Talibans", "core"->"Korea", "API"->"fire"),
inverted getter/method semantics, factual reversals, and hallucinated content all
read as fluent, on-topic, embeddings-close text to a sentence encoder -- the
embedding space doesn't distinguish "says something different" from "says the
opposite" when both are topically similar and grammatically fluent.

This module asks an LLM directly whether the TRANSLATION IS FAITHFUL IN MEANING
to the source -- not whether it reads naturally (that's
scripts/audit_translation_quality.py's score_naturalness_llm(), a fluency-only
rubric explicitly excluded from its own aggregate score). Provider construction
mirrors correction.py's attempt_correction() -- the only existing live code path
that constructs an LLM provider on demand for a quality-related purpose.

Fails open on any error (network, parsing, missing model): a judge that can't
render a verdict must not itself become a new source of blocked writes, matching
SemanticSimilarityValidator's and attempt_correction()'s existing conventions.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = (
    "You are a bilingual translation fidelity auditor. You check MEANING, not "
    "fluency -- a translation can read perfectly naturally and still be wrong. "
    "Specifically look for: hallucinated or fabricated content not present in "
    "the source; factual reversals (e.g. a negation flipped, 'supported' vs "
    "'not supported'); wrong-sense/homonym mistranslation (a word translated "
    "using an unrelated meaning); inverted method/API semantics (a getter "
    "described as setting or sending); omitted content; and content clearly "
    "about a different subject than the source. Do NOT flag differences in "
    "phrasing, word order, or style -- only flag actual meaning divergence. "
    "Respond with ONLY a single-line JSON object, no other text: "
    '{"score": <integer 0-10, 10=perfectly faithful, 0=completely wrong '
    'meaning>, "issues": [<short strings, empty list if none>]}'
)

_JUDGE_PROMPT_TEMPLATE = (
    "Source ({src_lang}):\n{source}\n\n"
    "Translation ({tgt_lang}):\n{translation}\n\n"
    "Respond with the JSON verdict now."
)

_MAX_CHARS = 3000  # cap per side to keep latency/cost bounded

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_LEADING_INT_RE = re.compile(r"\d+")


@dataclass
class FidelityVerdict:
    """Result of an LLM meaning-fidelity check."""

    score: float  # 0.0-1.0 (10-point LLM scale normalized)
    verdict: str  # "pass" | "warn" | "fail"
    issues: list[str] = field(default_factory=list)
    model: str = ""
    raw_response: str = ""
    parsed: bool = True  # False if the response couldn't be parsed as expected


def _classify(score: float, warn_threshold: float, fail_threshold: float) -> str:
    if score < fail_threshold:
        return "fail"
    if score < warn_threshold:
        return "warn"
    return "pass"


def _parse_response(text: str) -> tuple[float | None, list[str], bool]:
    """Parse the judge's response. Returns (score_0_to_1, issues, parsed_ok)."""
    text = (text or "").strip()
    if not text:
        return None, [], False

    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            obj = json.loads(match.group(0))
            raw_score = obj.get("score")
            if isinstance(raw_score, int | float):
                issues = obj.get("issues") or []
                if not isinstance(issues, list):
                    issues = [str(issues)]
                issues = [str(i) for i in issues][:20]  # bound
                score = max(0.0, min(10.0, float(raw_score))) / 10.0
                return score, issues, True
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Fallback: pull the first integer out (same tolerance as
    # audit_translation_quality.py's score_naturalness_llm parsing).
    int_match = _LEADING_INT_RE.search(text)
    if int_match:
        score = max(0, min(10, int(int_match.group()))) / 10.0
        return score, [], False

    return None, [], False


def judge_fidelity(
    source_text: str,
    translated_text: str,
    src_lang: str,
    tgt_lang: str,
    model_id: str = "professionalize_llm",
    warn_threshold: float = 0.7,
    fail_threshold: float = 0.5,
) -> FidelityVerdict | None:
    """Call an LLM to judge whether translated_text is faithful in MEANING to
    source_text. Returns None (fail-open) on any error -- a caller must treat
    None as "no verdict available", not as a passing verdict.
    """
    if not source_text or not translated_text:
        return None

    try:
        from ...model_runtime.llm_backend import LLMModelBackend
        from ...model_runtime.registry import ModelRegistry

        registry = ModelRegistry()
        try:
            model_info = registry.get_model(model_id)
        except KeyError:
            logger.warning("FidelityJudge: model '%s' not in registry", model_id)
            return None

        backend = LLMModelBackend(model_info, device="api")
        backend.load()
        if backend._provider is None:
            logger.warning("FidelityJudge: provider not initialized for %s", model_id)
            return None

        prompt = _JUDGE_PROMPT_TEMPLATE.format(
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            source=source_text[:_MAX_CHARS],
            translation=translated_text[:_MAX_CHARS],
        )
        response, _in_tok, _out_tok = backend._provider.generate(_JUDGE_SYSTEM_PROMPT, prompt)

    except Exception as exc:
        logger.warning("FidelityJudge: LLM call failed (%s): %s", model_id, exc)
        return None

    score, issues, parsed_ok = _parse_response(response)
    if score is None:
        logger.warning("FidelityJudge: could not parse response: %r", (response or "")[:200])
        return None

    return FidelityVerdict(
        score=score,
        verdict=_classify(score, warn_threshold, fail_threshold),
        issues=issues,
        model=model_id,
        raw_response=(response or "")[:500],
        parsed=parsed_ok,
    )
