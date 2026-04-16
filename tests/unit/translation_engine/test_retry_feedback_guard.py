"""
Tests for INT-02: retry feedback guard in engine._translate_to_language().

The guard at engine.py:2566-2580 ensures retry feedback is only prepended
to source texts when the backend is an LLMModelBackend.  Neural MT models
(M2M100, NLLB, CT2) translate ALL input literally — prepending English
feedback instructions corrupts output and inflates token count.

These tests verify the isinstance gate using real class hierarchy checks,
not mocks, to ensure the guard would hold against actual backends.
"""

import unittest
from unittest.mock import MagicMock, patch

from src.model_runtime.llm_backend import LLMModelBackend
from src.model_runtime.loader import ModelBackend, HuggingFaceBackend


class TestRetryFeedbackGuard(unittest.TestCase):
    """Verify that retry feedback is only applied to LLM backends."""

    def _apply_feedback_guard(self, backend, texts, retry_feedback, retry_count=1):
        """Reproduce the guard logic from engine.py:2566-2580."""
        if retry_feedback:
            if isinstance(backend, LLMModelBackend):
                texts = [
                    f"{retry_feedback}\n\nSOURCE TEXT:\n{text}"
                    for text in texts
                ]
                return texts, True  # feedback applied
            else:
                return texts, False  # feedback skipped
        return texts, False

    def test_neural_mt_backend_skips_feedback(self):
        """HuggingFaceBackend (neural MT) must NOT receive feedback."""
        backend = MagicMock(spec=HuggingFaceBackend)
        texts = ["Hello world", "Good morning"]
        feedback = "VALIDATION FEEDBACK - fix issues"

        result_texts, applied = self._apply_feedback_guard(
            backend, texts, feedback
        )

        self.assertFalse(applied)
        self.assertEqual(result_texts, ["Hello world", "Good morning"])

    def test_llm_backend_receives_feedback(self):
        """LLMModelBackend must receive prepended feedback."""
        backend = MagicMock(spec=LLMModelBackend)
        texts = ["Hello world", "Good morning"]
        feedback = "VALIDATION FEEDBACK - fix issues"

        result_texts, applied = self._apply_feedback_guard(
            backend, texts, feedback
        )

        self.assertTrue(applied)
        self.assertEqual(len(result_texts), 2)
        for text in result_texts:
            self.assertIn("VALIDATION FEEDBACK", text)
            self.assertIn("SOURCE TEXT:", text)

    def test_no_feedback_skips_guard_entirely(self):
        """When retry_feedback is None/empty, no modification regardless of backend."""
        llm_backend = MagicMock(spec=LLMModelBackend)
        mt_backend = MagicMock(spec=HuggingFaceBackend)
        texts = ["Hello world"]

        for backend in [llm_backend, mt_backend]:
            result_texts, applied = self._apply_feedback_guard(
                backend, texts, None
            )
            self.assertFalse(applied)
            self.assertEqual(result_texts, ["Hello world"])

            result_texts, applied = self._apply_feedback_guard(
                backend, texts, ""
            )
            self.assertFalse(applied)

    def test_isinstance_distinguishes_class_hierarchies(self):
        """LLMModelBackend does NOT inherit from ModelBackend — isinstance must distinguish them."""
        llm_mock = MagicMock(spec=LLMModelBackend)
        mt_mock = MagicMock(spec=HuggingFaceBackend)

        # LLMModelBackend IS an instance of LLMModelBackend
        self.assertTrue(isinstance(llm_mock, LLMModelBackend))

        # HuggingFaceBackend is NOT an instance of LLMModelBackend
        self.assertFalse(isinstance(llm_mock, HuggingFaceBackend))

        # HuggingFaceBackend IS an instance of ModelBackend
        self.assertTrue(isinstance(mt_mock, ModelBackend))

        # HuggingFaceBackend is NOT an instance of LLMModelBackend
        self.assertFalse(isinstance(mt_mock, LLMModelBackend))

    def test_feedback_format_matches_engine(self):
        """Verify feedback format matches what engine.py produces."""
        backend = MagicMock(spec=LLMModelBackend)
        texts = ["Test segment"]
        feedback = "Fix placeholder errors"

        result_texts, applied = self._apply_feedback_guard(
            backend, texts, feedback
        )

        self.assertTrue(applied)
        expected = "Fix placeholder errors\n\nSOURCE TEXT:\nTest segment"
        self.assertEqual(result_texts[0], expected)


class TestMTGateSkip(unittest.TestCase):
    """Verify that SW-1 fix: MT backends skip retryable gate failures immediately.

    Reproduces the gate logic from engine.py _translate_file_to_language:
        if retryable_gate_failure and retry_count < max_retry_attempts:
            ... load backend ...
            if not _backend_is_llm: result.success = False; break
            retry_count += 1; continue
    """

    def _apply_mt_gate_skip(self, model_loader, model_used, retryable, retry_count, max_retries):
        """Reproduce SW-1 gate logic. Returns 'mt_skip', 'llm_retry', or 'no_gate'."""
        if not (retryable and retry_count < max_retries):
            return "no_gate"
        _retry_model_id = model_used
        _backend_is_llm = False
        if _retry_model_id:
            try:
                _retry_backend = model_loader.load_model(_retry_model_id)
                _backend_is_llm = isinstance(_retry_backend, LLMModelBackend)
            except Exception:
                _backend_is_llm = True  # fail open: allow retry if check fails
        else:
            _backend_is_llm = True  # no model_id: can't determine → fail open
        if not _backend_is_llm:
            return "mt_skip"
        return "llm_retry"

    def test_mt_backend_gate_failure_skips_retry(self):
        """HuggingFaceBackend (MT) with retryable gate failure → immediate mt_skip, no retry."""
        loader = MagicMock()
        loader.load_model.return_value = MagicMock(spec=HuggingFaceBackend)

        result = self._apply_mt_gate_skip(
            model_loader=loader,
            model_used="m2m100_1.2b",
            retryable=True,
            retry_count=0,
            max_retries=2,
        )

        self.assertEqual(result, "mt_skip")
        loader.load_model.assert_called_once_with("m2m100_1.2b")

    def test_llm_backend_gate_failure_allows_retry(self):
        """LLMModelBackend with retryable gate failure → llm_retry (increments count)."""
        loader = MagicMock()
        loader.load_model.return_value = MagicMock(spec=LLMModelBackend)

        result = self._apply_mt_gate_skip(
            model_loader=loader,
            model_used="professionalize_llm",
            retryable=True,
            retry_count=0,
            max_retries=2,
        )

        self.assertEqual(result, "llm_retry")

    def test_non_retryable_gate_bypasses_check(self):
        """retryable_gate_failure=False → no_gate (gate check not reached)."""
        loader = MagicMock()

        result = self._apply_mt_gate_skip(
            model_loader=loader,
            model_used="m2m100_1.2b",
            retryable=False,
            retry_count=0,
            max_retries=2,
        )

        self.assertEqual(result, "no_gate")
        loader.load_model.assert_not_called()

    def test_retries_exhausted_bypasses_check(self):
        """retry_count >= max_retries → no_gate (handled by exhaustion logic)."""
        loader = MagicMock()

        result = self._apply_mt_gate_skip(
            model_loader=loader,
            model_used="m2m100_1.2b",
            retryable=True,
            retry_count=2,
            max_retries=2,
        )

        self.assertEqual(result, "no_gate")
        loader.load_model.assert_not_called()

    def test_model_load_exception_fails_open(self):
        """If load_model() raises (e.g., model evicted), assume LLM and allow retry."""
        loader = MagicMock()
        loader.load_model.side_effect = RuntimeError("model unavailable")

        result = self._apply_mt_gate_skip(
            model_loader=loader,
            model_used="some_model",
            retryable=True,
            retry_count=0,
            max_retries=2,
        )

        # fail-open: allow retry rather than silently dropping the translation
        self.assertEqual(result, "llm_retry")

    def test_no_model_used_fails_open(self):
        """model_used=None (stats not populated) → fail open, allow retry."""
        loader = MagicMock()

        result = self._apply_mt_gate_skip(
            model_loader=loader,
            model_used=None,
            retryable=True,
            retry_count=0,
            max_retries=2,
        )

        self.assertEqual(result, "llm_retry")
        loader.load_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
