"""TC-06 / TC-C5B: Two-stage translate + correct for correctable validation failures.

When validation rejects a translation, this module checks whether the issues are
correctable (LLM can plausibly fix them) before making an API call.  Structural
failures (shortcode loss, code block count, YAML parse, frontmatter integrity,
wrong-language purity) are in the BYPASS list — the LLM cannot reliably fix them
and attempting correction wastes credits and risks further corruption.

Config: ``correction_pass.enabled`` in global.yaml (default: false).

TC-C5B fix 2026-06-11 (ethereal-sauteeing-brook sprint 2):
  Added _BYPASS_VALIDATORS allowlist and _all_issues_bypass_correction() guard.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Validators whose issues must NOT trigger LLM correction.
# These represent structural or language-identity failures that an LLM cannot
# reliably repair — attempting correction wastes API credits and risks producing
# output that fails the same checks again (or fails new checks).
#
# Validator names must match ValidationIssue.validator values emitted by each class:
#   ShortcodePreservationValidator — shortcode loss/hallucination (structural)
#   StructureValidator             — code block count, heading, link structure (structural)
#   YamlValidator                  — YAML parse errors (structural)
#   FrontmatterIntegrityValidator  — frontmatter key/type corruption (structural)
#   LanguageConsistencyValidator   — wrong-language content (purity; LLM is wrong tool)
_BYPASS_VALIDATORS: frozenset[str] = frozenset({
    "ShortcodePreservationValidator",
    "StructureValidator",
    "YAMLValidator",
    "FrontmatterIntegrityValidator",
    "LanguageConsistencyValidator",
})


def _all_issues_bypass_correction(issues: list) -> bool:
    """Return True if every issue in the list is in the bypass set.

    If ALL issues are bypass-type, there is nothing the LLM can fix — skip the call.
    If ANY issue is correctable (not in the bypass set), proceed with correction.
    An empty issues list also bypasses (nothing to correct).
    """
    if not issues:
        return True
    for issue in issues:
        if isinstance(issue, dict):
            validator = issue.get("validator", "")
        else:
            validator = getattr(issue, "validator", "")
        if validator not in _BYPASS_VALIDATORS:
            return False  # Found a correctable issue — do not bypass
    return True  # All issues are bypass-type

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
            lines.append(
                f"{i}. [{issue.get('severity', 'error')}] {issue.get('message', str(issue))}"
            )
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

    Returns the corrected body text, or None if correction should not be attempted
    (bypass) or if the LLM call fails.

    TC-C5B: structural and purity failures are bypassed before the LLM call.
    Only correctable issues (placeholder leaks, length anomalies, repetitions, etc.)
    proceed to the LLM.
    """
    # TC-C5B: Bypass check — skip correction entirely if all issues are structural/purity
    if _all_issues_bypass_correction(issues):
        _bypass_validators = {
            (getattr(i, "validator", None) or i.get("validator", "?") if isinstance(i, dict) else "?")
            for i in issues
        }
        logger.info(
            "Correction pass bypassed for %s->%s: all issues are structural/purity (%s)",
            src_lang, tgt_lang, ", ".join(sorted(_bypass_validators)) or "empty",
        )
        return None

    try:
        from ..model_runtime.llm_backend import LLMModelBackend
        from ..model_runtime.registry import ModelRegistry

        registry = ModelRegistry()
        try:
            model_info = registry.get_model(model_id)
        except KeyError:
            logger.warning("Correction pass: model '%s' not in registry", model_id)
            return None

        backend = LLMModelBackend(model_info, device="api")
        backend.load()

        prompt = build_correction_prompt(source_body, translated_body, src_lang, tgt_lang, issues)

        # Use the provider directly for a single-shot correction
        if backend._provider is None:
            logger.warning("Correction pass: provider not initialized")
            return None

        correction_system_prompt = (
            "You are a translation quality fixer. Fix only the issues listed. "
            "Output only the corrected translation text, nothing else."
        )
        response, _in_tok, _out_tok = backend._provider.generate(correction_system_prompt, prompt)
        if not response or not response.strip():
            logger.warning("Correction pass: empty response from LLM")
            return None

        corrected = response.strip()
        logger.info(
            "Correction pass produced %d chars (was %d) for %s->%s",
            len(corrected),
            len(translated_body),
            src_lang,
            tgt_lang,
        )
        return corrected

    except Exception as exc:
        logger.warning("Correction pass failed: %s", exc)
        return None
