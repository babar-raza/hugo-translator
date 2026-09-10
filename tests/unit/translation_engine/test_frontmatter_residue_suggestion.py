"""TC-APT-108: the FrontmatterLanguageCheck issue must name its own residue.

Confirmed live on content/docs.aspose.org/en/pdf/{cpp,python}/_index.md: titles
shaped "Aspose.X FOSS for <Platform>" leave the connector word "for"
untranslated across all 3 retry attempts (professionalize_llm + 2x m2m100),
identically every time.

Root cause: the residue-comparison issue built by _check_frontmatter_language
(engine.py, TC-APT-090 branch) only ever said *which field* was untranslated
and how similar it was to the source -- never *what text* was left over. The
retry loop's only feedback-generation path that actually fires before the
"repeated identical feedback" early-stop
(file_pipeline.py:544-559) is decision_engine._generate_retry_feedback's
retry_count==1 branch, which surfaces issue.details["suggestion"] verbatim
if present (decision_engine.py:428-429) -- but nothing ever populated it for
this validator, so the model was told a field failed but never told which
word to fix.
"""

from unittest.mock import Mock

from src.translation_engine.engine import TranslationEngine


class _DummyConfigService:
    def get_config(self):
        return {
            "adaptive_batching": {"enabled": False},
            "language_detection": {"provider": "none"},
            "autonomous_recovery": {"oom_retry": {"enabled": False}},
        }


def _make_engine() -> TranslationEngine:
    return TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=False,
        enable_telemetry=False,
    )


def test_untranslated_connector_residue_is_named_in_the_suggestion():
    source = "---\ntitle: Aspose.PDF FOSS for Python\n---\n"
    translated = "---\ntitle: Aspose.PDF FOSS for Python\n---\n"

    issues = _make_engine()._check_frontmatter_language(translated, "de", source)

    assert len(issues) == 1
    assert issues[0].validator == "FrontmatterLanguageCheck"
    assert '"for"' in issues[0].details["suggestion"]


def test_the_suggestion_says_which_locale_to_translate_into():
    source = "---\ntitle: Aspose.PDF FOSS for Python\n---\n"
    translated = "---\ntitle: Aspose.PDF FOSS for Python\n---\n"

    issues = _make_engine()._check_frontmatter_language(translated, "de", source)

    assert "de" in issues[0].details["suggestion"]


def test_the_suggestion_says_preserved_tokens_must_stay_as_is():
    """The failure mode this must not cause: a model that starts re-translating
    the already-correct protected tokens (Aspose.PDF, Python) instead of just
    fixing the one leftover word."""
    source = "---\ntitle: Aspose.PDF FOSS for Python\n---\n"
    translated = "---\ntitle: Aspose.PDF FOSS for Python\n---\n"

    issues = _make_engine()._check_frontmatter_language(translated, "de", source)

    assert "preserved" in issues[0].details["suggestion"].lower()


def test_no_suggestion_key_when_the_field_is_actually_translated():
    source = "---\ntitle: Aspose.PDF FOSS for Python\n---\n"
    translated = "---\ntitle: Aspose.PDF FOSS für Python\n---\n"

    issues = _make_engine()._check_frontmatter_language(translated, "de", source)

    assert issues == []
