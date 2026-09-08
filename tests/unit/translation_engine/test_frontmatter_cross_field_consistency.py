"""TC-APT-042: cross-field frontmatter consistency — detection and repair.

Regression fixtures for the recurring defect class observed on
introducing-words-foss-net and introducing-pdf-foss-typescript: near-duplicate
frontmatter fields (description/summary) share a source phrase and one field
leaves it in English while the sibling translates it.
"""

from types import SimpleNamespace

from src.translation_engine.frontmatter_consistency import (
    find_cross_field_residuals,
)
from src.translation_engine.models import TranslationStats
from src.translation_engine.segment_translator import SegmentTranslator


def _fm_unit(field, source, translated, do_not_translate=False):
    return SimpleNamespace(
        node_addr=f"frontmatter.{field}",
        source_text=source,
        translated_text=translated,
        do_not_translate=do_not_translate,
        metadata={"field_name": field, "original_text": source},
    )


SOURCE_DESC = (
    "Aspose.PDF FOSS for TypeScript is a MIT-licensed, zero-dependency library "
    "for creating and editing PDF documents."
)
SOURCE_SUMM = (
    "A MIT-licensed, zero-dependency library for creating and editing PDF "
    "documents in TypeScript."
)
# Czech-style renderings: description translated the shared phrase, summary kept it.
GOOD_DESC = (
    "Aspose.PDF FOSS pro TypeScript je knihovna s licencí MIT bez závislostí "
    "pro vytváření a úpravu dokumentů PDF."
)
BAD_SUMM = (
    "MIT-licensed, zero-dependency knihovna pro vytváření a úpravu dokumentů "
    "PDF v TypeScriptu."
)


class TestFindCrossFieldResiduals:
    def test_detects_asymmetric_untranslated_shared_phrase(self):
        units = [
            _fm_unit("description", SOURCE_DESC, GOOD_DESC),
            _fm_unit("summary", SOURCE_SUMM, BAD_SUMM),
        ]
        residuals = find_cross_field_residuals(units)
        assert len(residuals) == 1
        residual = residuals[0]
        assert residual.field_name == "summary"
        assert residual.sibling_field == "description"
        assert "MIT-licensed, zero-dependency" in residual.phrase

    def test_symmetric_protected_terms_are_not_flagged(self):
        # Brand tokens legitimately stay verbatim in BOTH fields.
        units = [
            _fm_unit(
                "description",
                "Aspose.PDF FOSS for TypeScript makes PDF creation easy.",
                "Aspose.PDF FOSS for TypeScript usnadňuje tvorbu PDF.",
            ),
            _fm_unit(
                "summary",
                "Aspose.PDF FOSS for TypeScript creates PDF files.",
                "Aspose.PDF FOSS for TypeScript vytváří soubory PDF.",
            ),
        ]
        assert find_cross_field_residuals(units) == []

    def test_fully_translated_fields_are_not_flagged(self):
        units = [
            _fm_unit("description", SOURCE_DESC, GOOD_DESC),
            _fm_unit(
                "summary",
                SOURCE_SUMM,
                "Knihovna s licencí MIT bez závislostí pro vytváření a úpravu "
                "dokumentů PDF v TypeScriptu.",
            ),
        ]
        assert find_cross_field_residuals(units) == []

    def test_single_token_compound_residual_is_flagged(self):
        # Live case (gate5-pdf-foss-cpp-r2, el): description translates the
        # licence phrase, summary strands ONLY the one-token compound.
        units = [
            _fm_unit(
                "description",
                "A free, MIT-licensed C++20 library for editing PDF documents.",
                "Μια δωρεάν βιβλιοθήκη C++20 με άδεια MIT για επεξεργασία εγγράφων PDF.",
            ),
            _fm_unit(
                "summary",
                "A free, MIT-licensed C++20 library for editing PDF documents quickly.",
                "Μια δωρεάν, MIT-licensed βιβλιοθήκη C++20 για γρήγορη επεξεργασία εγγράφων PDF.",
            ),
        ]
        residuals = find_cross_field_residuals(units)
        assert len(residuals) == 1
        assert residuals[0].field_name == "summary"
        assert residuals[0].phrase == "MIT-licensed"

    def test_bare_acronym_is_not_flagged_as_single_token(self):
        # "MIT" alone (no lowercase word component) must never qualify.
        units = [
            _fm_unit(
                "description",
                "Uses the MIT licence for the library.",
                "Χρησιμοποιεί την άδεια MIT για τη βιβλιοθήκη.",
            ),
            _fm_unit(
                "summary",
                "Uses the MIT licence for this library today.",
                "Χρησιμοποιεί σήμερα την άδεια MIT για αυτή τη βιβλιοθήκη.",
            ),
        ]
        assert find_cross_field_residuals(units) == []

    def test_short_function_word_overlap_is_not_flagged(self):
        units = [
            _fm_unit("description", "Learn more for the web today.", "Weitere Infos for the web."),
            _fm_unit("summary", "Read this for the web now.", "Lesen Sie dies für das Web."),
        ]
        assert find_cross_field_residuals(units) == []

    def test_short_two_token_technical_phrase_residual_is_flagged(self):
        # Live case (wave16, pdf-document-management-go, fr/nl/sv/...): title
        # leaves the whole "HTML Export, Layers, and Tagged PDF" tail in English
        # while seoTitle translates the same phrase pair. Each qualifying run
        # is only 2 tokens (e.g. "Tagged PDF" = 9 alpha chars), below the old
        # 12-alpha 2-token floor -- both "HTML Export" and "Tagged PDF" fell
        # through the gap between the 2-token and 3-token qualification bands.
        title_src = "Document Management in Go: HTML Export, Layers, and Tagged PDF"
        title_fr = "Gestion de documents en Go: HTML Export, Layers, and Tagged PDF"
        seo_src = "Aspose.PDF FOSS for Go — HTML Export, Layers & Tagged PDF Guide"
        seo_fr = "Aspose.PDF FOSS pour Go — Guide d'Export, Calques et PDF balisé"
        units = [
            _fm_unit("title", title_src, title_fr),
            _fm_unit("seoTitle", seo_src, seo_fr),
        ]
        residuals = find_cross_field_residuals(units)
        phrases = {r.phrase for r in residuals}
        assert residuals, "expected at least one residual on the title field"
        assert all(r.field_name == "title" for r in residuals)
        assert any("Tagged PDF" in p or "HTML Export" in p for p in phrases)

    def test_non_frontmatter_and_dnt_units_are_ignored(self):
        body_unit = SimpleNamespace(
            node_addr="body.0",
            source_text=SOURCE_DESC,
            translated_text=SOURCE_DESC,
            do_not_translate=False,
            metadata={},
        )
        dnt_unit = _fm_unit("summary", SOURCE_SUMM, SOURCE_SUMM, do_not_translate=True)
        translated = _fm_unit("description", SOURCE_DESC, GOOD_DESC)
        assert find_cross_field_residuals([body_unit, dnt_unit, translated]) == []


class _StubBackend:
    """Context-capable backend returning a canned repair."""

    def __init__(self, repaired_text):
        self.repaired_text = repaired_text
        self.calls = []

    def translate_with_context(self, texts, src, tgt, **kwargs):
        self.calls.append((list(texts), src, tgt, kwargs))
        return [self.repaired_text for _ in texts]


class TestRepairCrossFieldResiduals:
    def _translator(self):
        engine = SimpleNamespace(model_loader=None, _model_lock=None)
        translator = SegmentTranslator.__new__(SegmentTranslator)
        translator._engine = engine
        return translator, engine

    def test_repair_replaces_residual_translation(self):
        translator, engine = self._translator()
        units = [
            _fm_unit("description", SOURCE_DESC, GOOD_DESC),
            _fm_unit("summary", SOURCE_SUMM, BAD_SUMM),
        ]
        backend = _StubBackend(
            "Knihovna s licencí MIT bez závislostí pro vytváření a úpravu "
            "dokumentů PDF v TypeScriptu."
        )
        repaired = translator._repair_cross_field_frontmatter_residuals(
            engine, units, backend, "en", "cs", TranslationStats()
        )
        assert repaired == 1
        assert "MIT-licensed" not in units[1].translated_text
        assert units[1].metadata["cross_field_repair_sibling"] == "description"
        # The retry prompt must name the residual phrase and the sibling rendering.
        _, _, _, kwargs = backend.calls[0]
        assert "MIT-licensed, zero-dependency" in kwargs["retry_feedback"]
        assert kwargs["context_hint"] == "frontmatter_summary"

    def test_repair_keeps_prior_candidate_when_residual_survives(self):
        translator, engine = self._translator()
        units = [
            _fm_unit("description", SOURCE_DESC, GOOD_DESC),
            _fm_unit("summary", SOURCE_SUMM, BAD_SUMM),
        ]
        backend = _StubBackend(BAD_SUMM)  # retry still contains the English phrase
        repaired = translator._repair_cross_field_frontmatter_residuals(
            engine, units, backend, "en", "cs", TranslationStats()
        )
        assert repaired == 0
        assert units[1].translated_text == BAD_SUMM

    def test_no_context_capable_backend_skips_quietly(self):
        translator, engine = self._translator()

        class _FailingLoader:
            def load_model(self, model_id):
                raise RuntimeError("provider down")

        engine.model_loader = _FailingLoader()

        class _Lock:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        engine._model_lock = _Lock()
        units = [
            _fm_unit("description", SOURCE_DESC, GOOD_DESC),
            _fm_unit("summary", SOURCE_SUMM, BAD_SUMM),
        ]
        plain_backend = SimpleNamespace()  # no translate_with_context
        repaired = translator._repair_cross_field_frontmatter_residuals(
            engine, units, plain_backend, "en", "cs", TranslationStats()
        )
        assert repaired == 0
        assert units[1].translated_text == BAD_SUMM

    def test_no_residuals_makes_no_backend_calls(self):
        translator, engine = self._translator()
        units = [_fm_unit("description", SOURCE_DESC, GOOD_DESC)]
        backend = _StubBackend("unused")
        repaired = translator._repair_cross_field_frontmatter_residuals(
            engine, units, backend, "en", "cs", TranslationStats()
        )
        assert repaired == 0
        assert backend.calls == []
