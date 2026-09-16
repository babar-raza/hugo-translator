"""A failing gate must record WHAT mismatched, not just that something did.

words-document-net's de cell exhausted all five attempts on StructureValidator and
recorded only:

    StructureValidator:error:generic:594be013934cbba3:payload_sha256=none:numeric=none

The validator had the numbers all along -- source_count, translation_count,
source_level, translation_level, src_len, tgt_len -- but the fingerprint builder
selected numeric detail from a hardcoded allowlist that none of those keys were in,
so it discarded them. Five attempts produced no diagnosable evidence.

Only numbers and pattern-constrained tag names are added: the runbook forbids
persisting candidate-derived text in any ledger, so string detail values stay out.
"""

import re
from types import SimpleNamespace

from src.workers.campaign_runner import CampaignRunner


def _issue(validator: str, details: dict, location: str = "body.heading[3]"):
    return SimpleNamespace(
        severity="error", validator=validator, details=details, location=location
    )


def _fingerprint(issues: list) -> str:
    result = SimpleNamespace(
        validation_result=SimpleNamespace(issues=issues),
        error="translation_rejected",
        errors=[1],
        retry_attempts=0,
        verification_result=None,
    )
    _gate, reason = CampaignRunner._failure_metadata(result)
    match = re.search(r"issue_fingerprints=([^;]*)", reason)
    return match.group(1) if match else ""


def test_structure_validator_records_the_counts_that_mismatched():
    fingerprint = _fingerprint(
        [
            _issue(
                "StructureValidator",
                {"source_count": 12, "translation_count": 10, "src_tag": "ul", "tgt_tag": "ol"},
            )
        ]
    )

    assert "source_count=12" in fingerprint
    assert "translation_count=10" in fingerprint
    assert "numeric=none" not in fingerprint, "this is the opaque case that cost five attempts"


def test_structure_validator_records_which_element_mismatched():
    fingerprint = _fingerprint(
        [_issue("StructureValidator", {"src_tag": "ul", "tgt_tag": "ol"})]
    )

    assert "src_tag=ul" in fingerprint
    assert "tgt_tag=ol" in fingerprint


def test_heading_level_and_length_details_are_recorded():
    fingerprint = _fingerprint(
        [
            _issue(
                "StructureValidator",
                {"source_level": 2, "translation_level": 3, "src_len": 41, "tgt_len": 58},
            )
        ]
    )

    for expected in ("source_level=2", "translation_level=3", "src_len=41", "tgt_len=58"):
        assert expected in fingerprint, fingerprint


def test_frontmatter_language_fingerprint_is_unchanged():
    """Regression: the shape of an existing class must stay byte-identical.

    Compared against the real fingerprint recorded for words-doc's cs failure, so
    heal-ticket grouping on existing classes is unaffected.
    """
    fingerprint = _fingerprint(
        [
            _issue(
                "FrontmatterLanguageCheck",
                {
                    "field": "seoTitle",
                    "detected_lang": "ca",
                    "expected_lang": "cs",
                    "confidence": 0.999996,
                    "letter_count": 47,
                    "latin_letter_ratio": 1,
                    "target_script_ratio": 1,
                },
            )
        ]
    )

    assert fingerprint.startswith("FrontmatterLanguageCheck:error:frontmatter_language:")
    assert "field=seoTitle:detected_lang=ca:expected_lang=cs" in fingerprint
    assert "confidence=0.999996" in fingerprint
    assert "letter_count=47" in fingerprint


def test_a_tag_value_cannot_smuggle_prose_into_the_ledger():
    """The pattern constraint is the safeguard, so it is asserted directly."""
    fingerprint = _fingerprint(
        [
            _issue(
                "StructureValidator",
                {"src_tag": "There are no usage restrictions", "tgt_tag": "p"},
            )
        ]
    )

    assert "usage restrictions" not in fingerprint
    assert "tgt_tag=p" in fingerprint


def test_string_detail_values_are_not_recorded_verbatim():
    fingerprint = _fingerprint(
        [_issue("StructureValidator", {"note": "candidate text that must not persist"})]
    )

    assert "candidate text" not in fingerprint


def test_semantic_similarity_validator_records_the_measured_score():
    """TC-PORT-LLM-011: this validator's rejects fingerprinted as
    'SemanticSimilarityValidator:error:generic:...:numeric=none' -- issue_kind
    fell through to "generic" (no branch recognized this validator) and the one
    number that distinguishes a genuine semantic-drift reject from a false one,
    the measured similarity, was missing from the numeric allowlist even though
    "threshold" was already in it. ce7bcb69 fixed the same gap for the separate
    manual/forensic quarantine dump; this is the actual heal-queue write path.
    """
    fingerprint = _fingerprint(
        [_issue("SemanticSimilarityValidator", {"similarity": 0.31, "threshold": 0.4})]
    )

    assert fingerprint.startswith("SemanticSimilarityValidator:error:semantic_similarity:")
    assert "similarity=0.31" in fingerprint
    assert "threshold=0.4" in fingerprint
    assert "numeric=none" not in fingerprint


def test_semantic_similarity_validator_records_why_it_could_not_run():
    """The encoder-unavailable / embedding-call-raised paths record
    details={"exception_type": type(exc).__name__} instead of a score -- a
    class name, not candidate text, so it's safe to record and tells a human
    tool-failure apart from a genuine semantic-drift reject at a glance.
    """
    fingerprint = _fingerprint(
        [_issue("SemanticSimilarityValidator", {"exception_type": "ConnectionError"})]
    )

    assert "exception_type=ConnectionError" in fingerprint


def _rule_issue(rule: str, message: str, location: str | None):
    """Mimics src/translation_engine/models.py::ValidationIssue exactly: it has
    `severity`/`rule`/`message`/`location` and genuinely has no `validator` or
    `details` attribute at all (unlike validation/base.py::ValidationIssue,
    which segment_translator.py's own TranslationRetryableError raises never
    use). SimpleNamespace only exposes what's set here, so getattr(..., default)
    on a missing attribute is exercised for real, not simulated.
    """
    return SimpleNamespace(severity="error", rule=rule, message=message, location=location)


def test_ast_translation_empty_unit_is_not_misclassified_as_unknown():
    """TC-PORT-LLM-011: segment_translator.py's AST-empty-translation check
    raises with a models.ValidationIssue(rule="ASTTranslation", ...) -- which
    has no `validator` attribute. _failure_metadata's introspection used to
    read only `validator`, defaulting to "unknown" for every issue of this
    shape, so a real, reproducible defect (professionalize_llm returning an
    empty string for one text-run unit) fingerprinted identically to a truly
    unclassified failure and could never benefit from root-cause grouping.
    """
    fingerprint = _fingerprint(
        [
            _rule_issue(
                "ASTTranslation",
                "1 units with substantial source text returned empty translations",
                "body.blockquote[0].paragraph[0].text[1]",
            )
        ]
    )

    assert fingerprint.startswith("ASTTranslation:error:empty_translation_unit:")
    assert "generic" not in fingerprint


def test_ast_translation_gate_is_the_rule_name_not_unknown():
    result = SimpleNamespace(
        validation_result=SimpleNamespace(
            issues=[
                _rule_issue(
                    "ASTTranslation",
                    "1 units with substantial source text returned empty translations",
                    "body.blockquote[0].paragraph[0].text[1]",
                )
            ]
        ),
        error="translation_rejected",
        errors=[1],
        retry_attempts=3,
        verification_result=None,
    )
    gate, _reason = CampaignRunner._failure_metadata(result)

    assert gate == "ASTTranslation"


def test_batch_language_purity_rule_based_issue_is_not_misclassified_as_unknown():
    fingerprint = _fingerprint(
        [_rule_issue("BatchLanguagePurity", "High batch purity failure rate: 20.0%", "doc.md")]
    )

    assert fingerprint.startswith("BatchLanguagePurity:error:batch_language_purity:")


def test_exception_type_cannot_smuggle_arbitrary_text_into_the_ledger():
    fingerprint = _fingerprint(
        [
            _issue(
                "SemanticSimilarityValidator",
                {"exception_type": "candidate text that must not persist"},
            )
        ]
    )

    assert "candidate text" not in fingerprint
