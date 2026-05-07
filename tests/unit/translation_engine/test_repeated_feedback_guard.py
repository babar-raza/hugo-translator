"""
Tests for the repeated feedback guard added to engine.py RETRY handler.

The guard detects when the same error validators fire on consecutive retries,
indicating the LLM cannot resolve the issue, and fails the file early rather
than exhausting all max_retry_attempts with futile API calls.

This specifically addresses the Arabic-script-in-Danish LLM generation issue
observed during P3 pilot (2026-05-07): the LLM generated Arabic characters
when translating Document AI content to Danish, and repeated correction
prompts did not resolve the issue.
"""
from __future__ import annotations

import unittest


class TestRepeatedFeedbackGuard(unittest.TestCase):
    """Unit tests for the _prev_retry_validators guard logic (extracted for isolation)."""

    def _run_guard(
        self,
        prev_validators: "frozenset | None",
        current_issue_validators: list[str],
        current_issue_severities: list[str],
    ) -> tuple[bool, frozenset]:
        """
        Reproduce the guard logic added to engine.py RETRY handler.

        Returns (should_fail_early, new_prev_validators).
        """
        try:
            _current_validators = frozenset(
                (v, s)
                for v, s in zip(current_issue_validators, current_issue_severities)
                if s == "error"
            )
        except Exception:
            _current_validators = frozenset()

        should_fail_early = (
            prev_validators is not None
            and bool(_current_validators)
            and _current_validators == prev_validators
        )

        return should_fail_early, _current_validators

    def test_same_validators_on_second_retry_triggers_early_fail(self):
        """Same error validators on retry 1 and retry 2 -> fail early."""
        validators = ["LanguageConsistencyValidator"]
        severities = ["error"]

        # First retry: no prev_validators yet
        fail_early, prev = self._run_guard(None, validators, severities)
        self.assertFalse(fail_early)
        self.assertEqual(prev, frozenset({("LanguageConsistencyValidator", "error")}))

        # Second retry: same validators -> should fail early
        fail_early, _ = self._run_guard(prev, validators, severities)
        self.assertTrue(fail_early)

    def test_different_validators_on_second_retry_does_not_fail_early(self):
        """Different validators on consecutive retries -> keep retrying."""
        fail_early, prev = self._run_guard(
            None, ["LanguageConsistencyValidator"], ["error"]
        )
        self.assertFalse(fail_early)

        fail_early, _ = self._run_guard(prev, ["CompletenessValidator"], ["error"])
        self.assertFalse(fail_early)

    def test_no_errors_in_current_does_not_trigger_guard(self):
        """If current issue set has no errors (only warnings), guard is skipped."""
        prev = frozenset({("LanguageConsistencyValidator", "error")})

        # Current: only warnings (severity != error)
        fail_early, _ = self._run_guard(prev, ["SomeValidator"], ["warning"])
        self.assertFalse(fail_early)

    def test_first_retry_never_fails_early(self):
        """Guard never triggers on the first retry (prev is None)."""
        fail_early, _ = self._run_guard(
            None, ["LanguageConsistencyValidator"], ["error"]
        )
        self.assertFalse(fail_early)

    def test_multiple_validators_same_set_triggers_guard(self):
        """Multiple validators forming the same set on consecutive retries -> fail early."""
        validators = ["LanguageConsistencyValidator", "PlaceholderValidator"]
        severities = ["error", "error"]

        fail_early, prev = self._run_guard(None, validators, severities)
        self.assertFalse(fail_early)

        fail_early, _ = self._run_guard(prev, validators, severities)
        self.assertTrue(fail_early)

    def test_partial_set_overlap_does_not_trigger_guard(self):
        """Partially overlapping validator sets -> guard does NOT trigger (must be identical)."""
        fail_early, prev = self._run_guard(
            None,
            ["LanguageConsistencyValidator", "PlaceholderValidator"],
            ["error", "error"],
        )
        self.assertFalse(fail_early)

        # Only one of the two validators fires next time -> different set
        fail_early, _ = self._run_guard(prev, ["LanguageConsistencyValidator"], ["error"])
        self.assertFalse(fail_early)

    def test_error_vs_warning_same_validator_are_different_keys(self):
        """Error and warning from same validator are treated as different keys in the frozenset."""
        prev = frozenset({("LanguageConsistencyValidator", "error")})

        # Current: same validator but warning severity -> different key
        fail_early, _ = self._run_guard(
            prev, ["LanguageConsistencyValidator"], ["warning"]
        )
        self.assertFalse(fail_early)

    def test_empty_prev_is_treated_as_none(self):
        """Empty frozenset as prev_validators -> guard does not trigger."""
        prev = frozenset()
        # prev is not None but is falsy -> condition requires current and prev both non-empty
        fail_early, _ = self._run_guard(
            prev, ["LanguageConsistencyValidator"], ["error"]
        )
        # prev is not None but empty frozenset != non-empty frozenset -> no fail
        self.assertFalse(fail_early)


if __name__ == "__main__":
    unittest.main()
