"""TC-06: Two-stage translate + correct for failed validations.

When validation rejects a translation, this module sends the failed output
plus the specific validation issues to an LLM and asks it to fix them.
The corrected text is then re-validated through the normal pipeline.

Config: ``correction_pass.enabled`` in global.yaml (default: false).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Prompt template — keeps the source, failed translation, and issues together
# so the LLM can make targeted fixes without re-translating from scratch.
_CORRECTION_PROMPT = """\
You are a translation quality fixer. A machine translation from {src_lang} to {tgt_lang} \
failed automated validation. Fix ONLY the issues listed below. Do NOT re-translate \
from scratch — preserve as much of the existing translation as possible.

## Source ({src_lang}):
{source_body}

## Failed Translation ({tgt_lang}):
{translated_body}

## Validation Issues:
{issues_text}

## Instructions:
- Fix each listed issue while keeping the rest of the translation unchanged.
- Output ONLY the corrected {tgt_lang} translation (no explanations, no markdown fences).
- Preserve all Hugo shortcodes, frontmatter markers, code blocks, and links exactly.
"""


def build_correction_prompt(
    source_body: str,
    translated_body: str,
    src_lang: str,
    tgt_lang: str,
    issues: list[dict[str, Any]] | list[Any],
) -> str:
    """Build the correction prompt from validation issues."""
    lines: list[str] = []
    for i, issue in enumerate(issues, 1):
        if hasattr(issue, "message"):
            # ValidationIssue object
            sev = getattr(issue, "severity", None)
            sev_str = sev.value if hasattr(sev, "value") else str(sev)
            lines.append(f"{i}. [{sev_str}] {issue.message}")
        elif isinstance(issue, dict):
            lines.append(f"{i}. [{issue.get('severity', 'error')}] {issue.get('message', str(issue))}")
        else:
            lines.append(f"{i}. {issue}")

    return _CORRECTION_PROMPT.format(
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        source_body=source_body[:8000],  # cap to avoid token overflow
        translated_body=translated_body[:8000],
        issues_text="\n".join(lines) if lines else "(no details)",
    )


def attempt_correction(
    source_body: str,
    translated_body: str,
    src_lang: str,
    tgt_lang: str,
    issues: list,
    model_id: str = "professionalize_llm",
) -> str | None:
    """Call LLM to correct a failed translation.

    Returns the corrected body text, or None if correction fails.
    """
    try:
        from ..model_runtime.registry import ModelRegistry
        from ..model_runtime.llm_backend import LLMModelBackend

        registry = ModelRegistry()
        try:
            model_info = registry.get_model(model_id)
        except KeyError:
            logger.warning("Correction pass: model '%s' not in registry", model_id)
            return None

        backend = LLMModelBackend(model_info, device="api")
        backend.load()

        prompt = build_correction_prompt(
            source_body, translated_body, src_lang, tgt_lang, issues
        )

        # Use the provider directly for a single-shot correction
        if backend._provider is None:
            logger.warning("Correction pass: provider not initialized")
            return None

        correction_system_prompt = (
            "You are a translation quality fixer. Fix only the issues listed. "
            "Output only the corrected translation text, nothing else."
        )
        response, _in_tok, _out_tok = backend._provider.generate(
            correction_system_prompt, prompt
        )
        if not response or not response.strip():
            logger.warning("Correction pass: empty response from LLM")
            return None

        corrected = response.strip()
        logger.info(
            "Correction pass produced %d chars (was %d) for %s->%s",
            len(corrected), len(translated_body), src_lang, tgt_lang,
        )
        return corrected

    except Exception as exc:
        logger.warning("Correction pass failed: %s", exc)
        return None
