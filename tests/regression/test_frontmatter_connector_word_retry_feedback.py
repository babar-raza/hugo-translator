"""TC-APT-108: title-undertranslation on "Aspose.X FOSS for <Platform>" titles.

Confirmed live (logs/debug_title_check.py, logs/debug_prompt_text.py, transient/
not committed) on content/docs.aspose.org/en/pdf/{cpp,python}/_index.md across
both professionalize_llm and m2m100_418m: the model leaves the single connector
word "for" untranslated, identically, across all three retry attempts. The
masking hypothesis (protected-term placeholders starving the model of context)
was refuted by instrumenting the actual prompt text, which is short but plain.

Root cause found by reading _frontmatter_source_guidance: its `stopwords` set
excludes "for" (and the substantive-word filter requires len >= 4), so the
retry instruction it builds never names "for" -- it falls back to the generic
"including these ordinary technical terms: all ordinary words" when "for" is
the only ordinary token, e.g. in "Aspose.PDF FOSS for Python" both neighbors
("FOSS", "Python") are classified as protected, so the model reads the whole
title as a near-fixed product-name idiom and has no explicit instruction
telling it the connector between them is still ordinary prose.
"""

from pathlib import Path
from types import SimpleNamespace

from src.workers.campaign_runner import CampaignRunner

FRONTMATTER = """---
title: Aspose.PDF FOSS for Python
description: "Python documentation for Aspose.PDF FOSS: create, edit, render."
---
body text
"""


def _issue(validator, details=None):
    return SimpleNamespace(validator=validator, details=details or {}, severity="error")


def _feedback(source_path, target_lang="de"):
    issues = [_issue("FrontmatterLanguageCheck", {"field": "title"})]
    result = SimpleNamespace(
        validation_result=SimpleNamespace(issues=issues),
        verification_result=SimpleNamespace(issues=[]),
        error="translation_rejected",
    )
    return CampaignRunner._retry_feedback(result, target_lang, source_path=source_path)


def test_a_connector_word_between_two_preserved_tokens_is_named_explicitly(tmp_path):
    source_path = tmp_path / "_index.md"
    source_path.write_text(FRONTMATTER, encoding="utf-8")

    feedback = _feedback(source_path)

    assert '"for"' in feedback


def test_the_preserved_tokens_are_still_listed_as_preserved(tmp_path):
    source_path = tmp_path / "_index.md"
    source_path.write_text(FRONTMATTER, encoding="utf-8")

    feedback = _feedback(source_path)

    assert "Aspose.PDF" in feedback
    assert "FOSS" in feedback
    assert "Python" in feedback


def test_it_does_not_fire_when_no_stopword_is_sandwiched_between_preserved_tokens(tmp_path):
    source_path = tmp_path / "_index.md"
    source_path.write_text(
        '---\ntitle: "Create and edit PDF documents"\n---\nbody\n', encoding="utf-8"
    )

    feedback = _feedback(source_path)

    assert "connector word" not in feedback.lower()


def test_it_does_not_fire_without_a_source_path():
    feedback = _feedback(None)

    assert "connector word" not in feedback.lower()
    assert '"for"' not in feedback
