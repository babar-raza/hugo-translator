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

import hashlib
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
    "A token such as <PRESERVED_CODE_BLOCK_1> represents an identical governed "
    "code block on both sides and is not an omission. "
    "Respond with ONLY a single-line JSON object, no other text: "
    '{"score": <integer 0-10, 10=perfectly faithful, 0=completely wrong '
    'meaning>, "issues": [<short strings, empty list if none>]}'
)

_JUDGE_PROMPT_TEMPLATE = (
    "Source ({src_lang}):\n{source}\n\n"
    "Translation ({tgt_lang}):\n{translation}\n\n"
    "Respond with the JSON verdict now."
)

_MAX_CHARS = 24000

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_LEADING_INT_RE = re.compile(r"\d+")
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+")


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


def _replace_fenced_code(text: str) -> str:
    """Replace fenced-code payloads with aligned structural markers."""
    output: list[str] = []
    fence_char = ""
    block_index = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        marker = ""
        if stripped.startswith("```"):
            marker = "```"
        elif stripped.startswith("~~~"):
            marker = "~~~"
        if marker:
            if not fence_char:
                fence_char = marker
                block_index += 1
                output.append(f"<PRESERVED_CODE_BLOCK_{block_index}>")
            elif marker == fence_char:
                fence_char = ""
            continue
        if not fence_char:
            output.append(line)
    return "\n".join(output)


def _sections(text: str) -> list[str]:
    starts = [match.start() for match in _HEADING_RE.finditer(text)]
    if not starts:
        return [text] if text.strip() else []
    boundaries = [0, *starts, len(text)]
    sections = [
        text[boundaries[index] : boundaries[index + 1]].strip()
        for index in range(len(boundaries) - 1)
    ]
    return [section for section in sections if section]


def _aligned_fidelity_chunks(
    source_text: str,
    translated_text: str,
    max_chars: int = _MAX_CHARS,
) -> list[tuple[str, str]] | None:
    """Create complete, heading-aligned judge chunks without asymmetric truncation."""
    source = _replace_fenced_code(source_text)
    target = _replace_fenced_code(translated_text)
    if len(source) <= max_chars and len(target) <= max_chars:
        return [(source, target)]

    source_sections = _sections(source)
    target_sections = _sections(target)
    if len(source_sections) != len(target_sections):
        return None

    chunks: list[tuple[str, str]] = []
    current_source: list[str] = []
    current_target: list[str] = []
    source_length = 0
    target_length = 0
    for source_section, target_section in zip(
        source_sections, target_sections, strict=True
    ):
        if len(source_section) > max_chars or len(target_section) > max_chars:
            return None
        separator = 2 if current_source else 0
        would_overflow = (
            source_length + separator + len(source_section) > max_chars
            or target_length + separator + len(target_section) > max_chars
        )
        if would_overflow:
            chunks.append(("\n\n".join(current_source), "\n\n".join(current_target)))
            current_source = []
            current_target = []
            source_length = 0
            target_length = 0
            separator = 0
        current_source.append(source_section)
        current_target.append(target_section)
        source_length += separator + len(source_section)
        target_length += separator + len(target_section)
    if current_source:
        chunks.append(("\n\n".join(current_source), "\n\n".join(current_target)))
    return chunks or None


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

        chunks = _aligned_fidelity_chunks(source_text, translated_text)
        if chunks is None:
            logger.warning(
                "FidelityJudge: content could not be aligned into bounded chunks "
                "(source_length=%d target_length=%d)",
                len(source_text),
                len(translated_text),
            )
            return None

        chunk_scores: list[float] = []
        all_issues: list[str] = []
        response_hashes: list[str] = []
        all_parsed = True
        for index, (source_chunk, target_chunk) in enumerate(chunks, start=1):
            prompt = _JUDGE_PROMPT_TEMPLATE.format(
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                source=source_chunk,
                translation=target_chunk,
            )
            response, _in_tok, _out_tok = backend._provider.generate(
                _JUDGE_SYSTEM_PROMPT, prompt
            )
            score, issues, parsed_ok = _parse_response(response)
            if score is None:
                logger.warning(
                    "FidelityJudge: could not parse response "
                    "(chunk=%d response_length=%d response_sha256=%s)",
                    index,
                    len(response or ""),
                    hashlib.sha256((response or "").encode("utf-8")).hexdigest(),
                )
                return None
            chunk_scores.append(score)
            all_issues.extend(f"chunk {index}: {issue}" for issue in issues)
            response_hashes.append(
                hashlib.sha256((response or "").encode("utf-8")).hexdigest()
            )
            all_parsed = all_parsed and parsed_ok

    except Exception as exc:
        logger.warning("FidelityJudge: LLM call failed (%s): %s", model_id, exc)
        return None

    score = min(chunk_scores)
    return FidelityVerdict(
        score=score,
        verdict=_classify(score, warn_threshold, fail_threshold),
        issues=all_issues[:20],
        model=model_id,
        raw_response="sha256:" + ",".join(response_hashes),
        parsed=all_parsed,
    )
