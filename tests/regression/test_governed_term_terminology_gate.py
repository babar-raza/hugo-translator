"""TC-APT-069 / RB-006: the governed term needs the terminology gate, not just a mask.

Measured on gate5-words-doc-r3 -- the first campaign run ever to carry the
"Document Object Model" preserve_pattern:

    field      fa    ar    fr     preserved
    body       EN    EN    EN     3/3   <- the mask holds here
    title      xlat  EN    EN     2/3
    summary    EN    EN    xlat   2/3
    seoTitle   xlat  xlat  xlat   0/3   <- never

The profile's preserve_pattern is not enough, and the reason is in the producer's
own docstring. segment_translator._retry_original_frontmatter_value deliberately
bypasses placeholder-wrapped frontmatter on retry -- and always under the
professionalize_llm escalation -- because a documented M2M100 failure mode is the
model copying a placeholder-bearing value back unchanged. That docstring names
the intended compensating control: "let terminology/structure/language/fidelity
gates validate its returned bytes."

The terminology gate is enabled for blog.aspose.org but reads config/terminology.
yaml, while TC-APT-069 registered the term only in the site profile's
preserve_patterns -- two disjoint lists, so the gate could not see it. seoTitle
fails 3/3 because it is the field that always retries.

These tests pin the compensating control: a translated governed term must be an
ERROR (a retry), and a preserved one must pass untouched.
"""

import pytest

from src.translation_engine.validation.terminology_preservation_validator import (
    TerminologyPreservationValidator,
)

SOURCE = "Inside the Aspose.Words FOSS for .NET Document Object Model"
TERM = "Document Object Model"


@pytest.fixture(scope="module")
def validator():
    return TerminologyPreservationValidator()


def _errors(result):
    return [
        issue
        for issue in result.issues
        if str(getattr(issue.severity, "value", issue.severity)).lower() == "error"
    ]


def test_the_governed_term_is_registered_with_the_gate(validator):
    """The whole defect was that this list and preserve_patterns were disjoint."""
    assert TERM in [t.get("term") for t in validator.exact_matches]


def test_a_translated_governed_term_is_an_error(validator):
    """seoTitle translated it in 3 of 3 locales and nothing objected."""
    translated = "Aspose.Words FOSS .NET مدل شیء سند"

    result = validator.validate(SOURCE, translated)

    assert not result.success
    assert len(_errors(result)) >= 1


def test_a_preserved_governed_term_passes(validator):
    """The body path already gets this right 3/3; it must not start failing."""
    preserved = "Aspose.Words FOSS برای .NET Document Object Model"

    result = validator.validate(SOURCE, preserved)

    assert result.success
    assert _errors(result) == []


def test_the_error_is_attributed_to_the_right_term(validator):
    """A generic failure would not tell the producer what to fix."""
    result = validator.validate(SOURCE, "Aspose.Words FOSS .NET מודל אובייקט מסמך")

    assert any(issue.details.get("term") == TERM for issue in _errors(result))


def test_a_source_without_the_term_is_unaffected(validator):
    """Neutrality: the rule must not fire on pages that never used the term."""
    source = "Install it via NuGet, or build it from source."
    result = validator.validate(source, "قم بتثبيته عبر NuGet، أو أنشئه من المصدر.")

    assert not any(issue.details.get("term") == TERM for issue in result.issues)


def test_severity_is_error_so_the_decision_is_retry(validator):
    """warning would log and accept; the point is that it must not ship.

    RB-006 treats a governed-term preservation failure as producer-side, so the
    cell must be retried rather than accepted with a note.
    """
    entry = next(t for t in validator.exact_matches if t.get("term") == TERM)

    assert entry.get("severity") == "error"
    assert entry.get("preserve_mode") == "both"
    assert entry.get("case_sensitive") is True


def test_the_lowercase_prose_form_is_not_governed(validator):
    """Only the capitalized term of art; ordinary prose usage stays translatable.

    Mirrors the same carve-out already pinned for the frontmatter signal path.
    """
    source = "Aspose.Words provides a document object model"

    result = validator.validate(source, "Aspose.Words يوفر نموذج كائن المستند")

    assert not any(issue.details.get("term") == TERM for issue in _errors(result))


def _severities(result, term):
    return [
        str(getattr(issue.severity, "value", issue.severity)).lower()
        for issue in result.issues
        if issue.details.get("term") == term
    ]


def test_partial_loss_of_the_governed_term_is_an_error(validator):
    """The defect that actually occurs: some occurrences kept, others translated.

    Measured on words-document-net, 8 of 10 locales lost SOME occurrences while
    keeping at least one. That keeps translation_count > 0, so it lands in the
    frequency-mismatch branch rather than the missing-entirely branch -- which
    defaults to a warning, which is why the gate never fired on the real defect.
    """
    source = f"{TERM} appears here. And again: {TERM}."
    partial = f"{TERM} appears here. And again: translated form."

    assert "error" in _severities(validator.validate(source, partial), TERM)


def test_full_preservation_still_passes(validator):
    source = f"{TERM} appears here. And again: {TERM}."

    assert _severities(validator.validate(source, source), TERM) == []


def test_total_loss_is_still_an_error(validator):
    """The pre-existing branch must keep working."""
    source = f"Inside the {TERM}."

    assert "error" in _severities(validator.validate(source, "Wholly translated."), TERM)


def test_other_terms_keep_the_warning_default(validator):
    """Neutrality: a legitimate restructure can change a brand's count.

    Promoting every frequency mismatch to error would reject good translations,
    so only a term that opts in via frequency_severity is tightened.
    """
    other = "Aspose"
    source = f"{other} and {other} again."
    partial = f"{other} only once."

    severities = _severities(validator.validate(source, partial), other)

    assert severities, "expected a frequency-mismatch issue for the control term"
    assert "error" not in severities


def test_only_the_governed_term_opted_in(validator):
    opted = [t.get("term") for t in validator.exact_matches if t.get("frequency_severity")]

    assert opted == [TERM]
