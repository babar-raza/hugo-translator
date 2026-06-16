"""Unit tests for FileTranslationPipeline (TC-TEST-02).

Tests retry loop, feedback guard, MT retry guard (TC-BUGFIX-B),
correction pass, and TM buffer lifecycle.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.translation_engine.exceptions import TranslationRejectedError
from src.translation_engine.file_pipeline import (
    FileTranslationPipeline,
    LanguageResult,
    LanguageTranslationContext,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(
    validation_enabled=False,
    review_cache=None,
    force_accept=False,
):
    """Build a mock engine with the minimum attributes FileTranslationPipeline needs."""
    engine = MagicMock()
    engine._review_cache = review_cache
    engine._force_accept = force_accept
    engine.enable_verification = False
    engine.enable_verification_fix = False
    engine._check_shutdown.return_value = False
    engine.dry_run = False
    engine.enable_content_hash = False
    engine.metadata_tracker = None
    engine.production_ingestor = None
    engine.similarity_tracker = None

    # Validation
    if validation_enabled:
        engine.validation_suite = MagicMock()
        engine.decision_engine = MagicMock()
    else:
        engine.validation_suite = None
        engine.decision_engine = None

    # Config
    engine.config.get_config.return_value = {}

    # _translate_to_language returns translated content
    engine._translate_to_language.return_value = "---\ntitle: Test\n---\nTranslated body"

    # Write gate
    from src.translation_engine.write_gate import WriteGateResult

    engine._write_gate = MagicMock()
    engine._write_gate.evaluate.return_value = WriteGateResult(passed=True)

    # _get_output_path returns the expected output path (must match ctx.output_paths_cache)
    engine._get_output_path.return_value = Path("/tmp/test_de.md")

    # _write_output succeeds
    engine._write_output.return_value = True

    # Parser for frontmatter check
    engine._check_frontmatter_language.return_value = []

    # Retry metrics (must match structure expected by pipeline)
    engine._retry_metrics = {
        "retry_attempts": [],
        "retry_durations_ms": [],
        "retry_reasons": {},
    }
    engine._retry_metrics_lock = MagicMock()

    return engine


def _make_ctx(**overrides):
    file_path = overrides.get("file_path", Path("/tmp/test.md"))
    output_path = overrides.get("output_path", Path("/tmp/test_de.md"))
    target_lang = overrides.get("target_lang", "de")

    doc = overrides.pop("doc", None)
    if doc is None:
        doc = MagicMock()
        doc.source_path = file_path
        doc.file_path = file_path

    defaults = dict(
        site_id="test.site",
        site_profile=MagicMock(),
        doc=doc,
        segments=[MagicMock()],
        content="---\ntitle: Test\n---\nSource body",
        source_lang="en",
        target_lang=target_lang,
        output_path=output_path,
        file_path=file_path,
        force=False,
        should_validate=False,
        should_verify=False,
        should_fix=False,
        max_retry_attempts=2,
        output_paths_cache={target_lang: output_path},
        llm_model_override=None,
    )
    defaults.update(overrides)
    return LanguageTranslationContext(**defaults)


def _make_result():
    """Create a mock TranslationResult with stats."""
    result = MagicMock()
    result.stats = MagicMock()
    result.stats.model_used = None
    result.stats.validation_retried = 0
    result.stats.ast_missing_nodes = 0
    result.stats.validation_warnings = 0
    result.stats.words_translated = 0
    result.stats.total_segments = 0
    result.stats.translated_segments = 0
    result.stats.tm_hits = 0
    result.translated_languages = []
    result.skipped_languages = []
    result.failed_languages = []
    result.errors = []
    result.stats.languages_translated = 0
    result.stats.languages_skipped = 0
    return result


# ---------------------------------------------------------------------------
# Basic pipeline flow
# ---------------------------------------------------------------------------


class TestBasicPipelineFlow:
    def test_success_without_validation(self):
        """No validation → translate once → write → success."""
        engine = _make_engine()
        pipeline = FileTranslationPipeline(engine)
        ctx = _make_ctx()
        result = _make_result()

        lang_result = pipeline.translate_language(ctx, result)
        assert lang_result.success
        assert lang_result.retry_count == 0
        engine._translate_to_language.assert_called_once()
        engine._write_output.assert_called_once()

    def test_write_gate_failure_blocks_write(self):
        """Write gate returns passed=False → no file written, failure result."""
        from src.translation_engine.write_gate import WriteGateResult

        engine = _make_engine()
        engine._write_gate.evaluate.return_value = WriteGateResult(
            passed=False, error="Language mismatch"
        )
        pipeline = FileTranslationPipeline(engine)
        ctx = _make_ctx()
        result = _make_result()

        lang_result = pipeline.translate_language(ctx, result)
        assert not lang_result.success
        engine._write_output.assert_not_called()

    def test_tm_buffer_flushed_on_success(self):
        """TM write buffer entries are stored to TM after successful write."""
        engine = _make_engine()

        # Simulate translate_to_language adding to the buffer
        def add_to_buffer(*args, **kwargs):
            buf = kwargs.get("tm_write_buffer", [])
            buf.append({"key": "val"})
            return "---\ntitle: Test\n---\nTranslated"

        engine._translate_to_language.side_effect = add_to_buffer
        pipeline = FileTranslationPipeline(engine)
        ctx = _make_ctx()
        result = _make_result()

        lang_result = pipeline.translate_language(ctx, result)
        assert lang_result.success
        # TM store called for the buffer entry
        engine.tm.store.assert_called()


# ---------------------------------------------------------------------------
# Retry and feedback guard
# ---------------------------------------------------------------------------


class TestRetryAndFeedbackGuard:
    def test_retry_on_validation_retry_decision(self):
        """RETRY decision → retry with feedback → second attempt succeeds."""
        from src.translation_engine.validation.post_translation_validator import (
            ValidationDecision as PostValidationDecision,
        )

        engine = _make_engine(validation_enabled=True)

        # First call: RETRY, second call: ACCEPT
        decision_mock_retry = MagicMock()
        decision_mock_retry.decision = PostValidationDecision.RETRY
        decision_mock_retry.retry_feedback = "Fix the headings"
        decision_mock_retry.decision_reason = "Structure issues"

        decision_mock_accept = MagicMock()
        decision_mock_accept.decision = PostValidationDecision.ACCEPT

        engine.decision_engine.make_decision.side_effect = [
            decision_mock_retry,
            decision_mock_accept,
        ]

        # Validation result with different validators each time
        vr1 = MagicMock()
        issue1 = MagicMock()
        issue1.validator = "heading_check"
        issue1.severity = MagicMock()
        issue1.severity.value = "error"
        vr1.issues = [issue1]
        vr1.error_count = 1
        vr1.warning_count = 0

        vr2 = MagicMock()
        vr2.issues = []
        vr2.error_count = 0
        vr2.warning_count = 0

        engine.validation_suite.validate_aggregated.side_effect = [vr1, vr2]

        pipeline = FileTranslationPipeline(engine)
        ctx = _make_ctx(should_validate=True, max_retry_attempts=2)
        result = _make_result()
        result.stats.model_used = "llm_gpt4"  # LLM backend (not MT)

        lang_result = pipeline.translate_language(ctx, result)
        assert lang_result.success
        # translate_to_language called twice (initial + 1 retry)
        assert engine._translate_to_language.call_count == 2

    def test_repeated_feedback_guard_triggers_rejection(self):
        """Same validators on consecutive retries → early rejection (BUG-5)."""
        from src.translation_engine.validation.post_translation_validator import (
            ValidationDecision as PostValidationDecision,
        )

        engine = _make_engine(validation_enabled=True)

        # Both retries return same RETRY with same validator
        decision_retry = MagicMock()
        decision_retry.decision = PostValidationDecision.RETRY
        decision_retry.retry_feedback = "Fix placeholders"
        decision_retry.decision_reason = "Placeholder issues"

        engine.decision_engine.make_decision.return_value = decision_retry

        issue = MagicMock()
        issue.validator = "placeholder_check"
        issue.severity = MagicMock()
        issue.severity.value = "error"

        vr = MagicMock()
        vr.issues = [issue]
        vr.error_count = 1
        vr.warning_count = 0
        engine.validation_suite.validate_aggregated.return_value = vr

        pipeline = FileTranslationPipeline(engine)
        ctx = _make_ctx(should_validate=True, max_retry_attempts=3)
        result = _make_result()
        result.stats.model_used = "llm_gpt4"

        lang_result = pipeline.translate_language(ctx, result)
        # Should fail due to repeated feedback guard (not max retries)
        assert not lang_result.success
        # Should NOT have exhausted all 3 retries — guard triggers on 2nd attempt
        assert engine._translate_to_language.call_count <= 3


# ---------------------------------------------------------------------------
# TC-BUGFIX-B: MT retry guard
# ---------------------------------------------------------------------------


class TestMTRetryGuard:
    def test_mt_backend_retry_escalates_to_reject(self):
        """MT backend on RETRY decision → immediate rejection (no futile retry)."""
        from src.translation_engine.validation.post_translation_validator import (
            ValidationDecision as PostValidationDecision,
        )

        engine = _make_engine(validation_enabled=True)

        decision_retry = MagicMock()
        decision_retry.decision = PostValidationDecision.RETRY
        decision_retry.retry_feedback = "Fix terminology"
        decision_retry.decision_reason = "Terminology issues"
        engine.decision_engine.make_decision.return_value = decision_retry

        vr = MagicMock()
        vr.issues = []
        vr.error_count = 1
        vr.warning_count = 0
        engine.validation_suite.validate_aggregated.return_value = vr

        pipeline = FileTranslationPipeline(engine)
        ctx = _make_ctx(should_validate=True, max_retry_attempts=3)
        result = _make_result()
        result.stats.model_used = "m2m100_418M"  # MT backend (not LLM)

        lang_result = pipeline.translate_language(ctx, result)
        assert not lang_result.success
        # Only 1 translation call — no futile retry
        assert engine._translate_to_language.call_count == 1

    def test_llm_backend_retry_allowed(self):
        """LLM backend on RETRY → normal retry (not blocked by MT guard)."""
        from src.translation_engine.validation.post_translation_validator import (
            ValidationDecision as PostValidationDecision,
        )

        engine = _make_engine(validation_enabled=True)

        decision_retry = MagicMock()
        decision_retry.decision = PostValidationDecision.RETRY
        decision_retry.retry_feedback = "Fix terminology"
        decision_retry.decision_reason = "Terminology issues"

        decision_accept = MagicMock()
        decision_accept.decision = PostValidationDecision.ACCEPT

        engine.decision_engine.make_decision.side_effect = [
            decision_retry,
            decision_accept,
        ]

        vr1 = MagicMock()
        issue = MagicMock()
        issue.validator = "term_check"
        issue.severity = MagicMock()
        issue.severity.value = "error"
        vr1.issues = [issue]
        vr1.error_count = 1
        vr1.warning_count = 0

        vr2 = MagicMock()
        vr2.issues = []
        vr2.error_count = 0
        vr2.warning_count = 0

        engine.validation_suite.validate_aggregated.side_effect = [vr1, vr2]

        pipeline = FileTranslationPipeline(engine)
        ctx = _make_ctx(should_validate=True, max_retry_attempts=3)
        result = _make_result()
        result.stats.model_used = "llm_gpt4"

        lang_result = pipeline.translate_language(ctx, result)
        assert lang_result.success
        assert engine._translate_to_language.call_count == 2


# ---------------------------------------------------------------------------
# LanguageResult dataclass
# ---------------------------------------------------------------------------


class TestLanguageResult:
    def test_default_values(self):
        r = LanguageResult(success=True)
        assert r.success
        assert r.error is None
        assert r.retry_count == 0
        assert not r.overwrite_blocked
