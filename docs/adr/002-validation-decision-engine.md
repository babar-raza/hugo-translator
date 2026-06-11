# ADR-002: Validation Decision Engine

- **Status:** Accepted
- **Date:** 2026-01-15
- **Decision Makers:** Translation System Team

## Context

Machine-translated content can have structural errors (broken Markdown, missing shortcodes), semantic errors (wrong terminology, language contamination), or critical errors (corrupted code blocks, broken links). The system needed an automated way to decide whether to accept, retry, or reject each translation.

Early versions used a simple threshold: if error count > N, reject. This caused two problems:
1. A single placeholder error (critical) was treated the same as three minor formatting warnings.
2. There was no retry path — translations were accepted or rejected with no chance to fix.

## Decision

Implement a rule-based Validation Decision Engine with a five-rule priority cascade:

1. **Critical validator failure → REJECT.** Placeholder errors, code block corruption, broken links, and shortcode loss are never acceptable. These validators are listed in `CRITICAL_VALIDATORS` and override all other rules.

2. **Error count >= threshold → REJECT.** Configurable `reject_on_error_count` (default 3). Prevents accumulation of non-critical errors.

3. **No errors → ACCEPT.** If only warnings or info-level issues exist and `accept_warnings` is true, accept the translation.

4. **Retryable errors + budget → RETRY.** If fixable errors exist (structure, terminology) and `retry_count < max_retry_attempts` (default 2), retry with targeted feedback from the validation issues.

5. **Exhausted retries → ACCEPT or REJECT.** If `accept_after_max_retries` is true and no critical validators are still failing, accept best-effort. Otherwise reject.

The engine receives a `ValidationResult` from the validation suite (10 validators) and emits a `DecisionResult` with the decision, reason, and optional retry feedback.

## Consequences

**Positive:**
- Critical errors never slip through regardless of retry count
- Retries are targeted — the engine generates specific feedback from validation issues
- Decision logic is centralized, testable, and configurable per deployment
- Telemetry tracks every decision for quality monitoring

**Negative:**
- Rule ordering matters — a change in priority could alter behavior
- `accept_after_max_retries=True` means some low-quality translations are accepted (by design, as best-effort)
- Static thresholds don't adapt to per-language quality differences (addressed separately in adaptive thresholds)

## References

- Implementation: `src/translation_engine/validation/decision_engine.py`
- Validation suite: `src/translation_engine/validation/validation_suite.py`
- Configuration: `config/validation.yaml` (decision_rules section)
- Original taskcards: DEC-01, DEC-02, DEC-03
- Tests: `tests/unit/validation/`, `tests/contract/test_validation_critical.py`
