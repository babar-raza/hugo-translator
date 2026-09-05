"""TC-APT-069: a gate that only rejects makes a cell fail; instruct the retry too.

The frontmatter retry deliberately sends the UNMASKED original value to the model
(segment_translator._retry_original_frontmatter_value, and always under the LLM
escalation), so placeholder protection cannot preserve a governed term there.
Measured on gate5-words-doc-r3 across two locales:

    field      fa    fr
    seoTitle   xlat  xlat   <- deterministic
    title      xlat  EN
    summary    EN    xlat
    body       EN    EN     <- masking holds here

title and summary flip per run, which is what the retry mechanism predicts:
which fields hit retry varies per run. So the scope is the retry path, not a
per-field allowlist.

Adding the term to config/terminology.yaml made the gate reject those cells --
correct, but rejection alone just fails the cell repeatedly. The retry path
already carries an instruction channel (_RetryFeedbackModel passes
retry_feedback through to translate_with_context), and an LLM can follow an
instruction where m2m100 could not follow a placeholder. These tests pin that
the instruction is produced, is candidate-free, and does not fire otherwise.
"""

from types import SimpleNamespace

import pytest

from src.workers.campaign_runner import CampaignRunner

TERM = "Document Object Model"


def _issue(validator, details=None):
    return SimpleNamespace(validator=validator, details=details or {}, severity="error")


def _feedback(issues, target_lang="fa"):
    result = SimpleNamespace(
        validation_result=SimpleNamespace(issues=issues),
        verification_result=SimpleNamespace(issues=[]),
        error="translation_rejected",
    )
    return CampaignRunner._retry_feedback(result, target_lang)


def test_a_terminology_failure_produces_a_preservation_instruction():
    feedback = _feedback([_issue("TerminologyPreservationValidator", {"term": TERM})])

    assert TERM in feedback
    assert "without translating" in feedback


def test_the_instruction_names_every_failing_term_once():
    issues = [
        _issue("TerminologyPreservationValidator", {"term": TERM}),
        _issue("TerminologyPreservationValidator", {"term": TERM}),
        _issue("TerminologyPreservationValidator", {"term": ".NET"}),
    ]

    feedback = _feedback(issues)

    assert feedback.count(f'"{TERM}"') == 1
    assert '".NET"' in feedback


def test_it_does_not_fire_without_a_terminology_failure():
    """Neutrality: unrelated failures must not gain a terminology instruction."""
    feedback = _feedback([_issue("StructureValidator")])

    assert TERM not in feedback
    assert "governed term" not in feedback.lower()


def test_the_instruction_is_candidate_free():
    """Runbook line 62: no translated text may reach a ledger, ticket or prompt.

    Only term names, which come from config/terminology.yaml, may appear.
    """
    feedback = _feedback([_issue("TerminologyPreservationValidator", {"term": TERM})])

    for target_script_fragment in ("مدل", "شیء", "Modèle", "μοντέλο"):
        assert target_script_fragment not in feedback


def test_it_still_says_to_translate_the_surrounding_text():
    """The failure mode this must not cause: a model that preserves everything.

    An instruction to keep a term untranslated, given to a model that already
    struggles with short token-dense fields, could suppress translation of the
    whole field. The instruction says so explicitly.
    """
    feedback = _feedback([_issue("TerminologyPreservationValidator", {"term": TERM})])

    assert "Translate everything around them normally" in feedback


def test_a_term_with_no_name_is_skipped_rather_than_emitting_an_empty_quote():
    feedback = _feedback([_issue("TerminologyPreservationValidator", {})])

    assert '""' not in feedback


@pytest.mark.parametrize("reason", [
    'validators=TerminologyPreservationValidator; codes=TerminologyPreservationValidator',
    'issue_fingerprints=TerminologyPreservationValidator:error:abc123',
])
def test_the_resume_path_recognises_a_terminology_failure(reason):
    """On resume, guidance is rehydrated from persisted metadata.

    Without this the retry after a restart would carry no terminology
    instruction, silently losing the fix exactly when a campaign is resumed.
    """
    feedback = CampaignRunner._retry_feedback_from_failure(
        {"reason": reason, "gate": "TerminologyPreservationValidator"}, "fa"
    )

    assert feedback is not None
    # Case-insensitive: the named form says "these governed terms", the generic
    # resume form opens a sentence with "Governed terms".
    assert "governed term" in feedback.lower()
    assert "without translating or transliterating" in feedback
