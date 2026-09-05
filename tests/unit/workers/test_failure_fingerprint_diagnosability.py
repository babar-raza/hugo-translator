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
