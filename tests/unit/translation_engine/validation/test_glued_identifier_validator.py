"""
TC-APT-110: GluedIdentifierValidator.

Every defect case is the literal shape found by the 5-agent rubric review
(RB-004) in wave-cellsrust-quickstart-glueretrigger-20260911r2's ACCEPTED
outputs -- the 44-gate battery passed all of them, which is exactly the
hole this validator closes. Legal cases are the confirmed-correct sibling
outputs from the same page/run.
"""
import pytest

from src.translation_engine.validation.glued_identifier_validator import (
    GluedIdentifierValidator,
)

SOURCE = (
    "Create your first Excel XLSX workbook in Rust using Aspose.Cells FOSS: "
    "typed cell values, a formula with a cached result, saving with "
    "Workbook.save, and reloading with Workbook.load_xlsx."
)


@pytest.fixture()
def validator():
    return GluedIdentifierValidator()


class TestRealDefectShapes:
    def test_cs_glued_preposition_rejected(self, validator):
        translation = (
            "Vytvořte svůj první Excel XLSX sešit v Rustu pomocí Aspose.Cells "
            "FOSS: uložení pomocíWorkbook.save a načtení pomocíWorkbook.load_xlsx."
        )
        result = validator.validate(SOURCE, translation, {"target_lang": "cs"})
        assert not result.success
        glued_terms = {i.details["term"] for i in result.issues}
        assert "Workbook.save" in glued_terms
        assert "Workbook.load_xlsx" in glued_terms

    def test_pt_glued_preposition_rejected(self, validator):
        translation = "salvando comWorkbook.save e recarregando comWorkbook.load_xlsx."
        result = validator.validate(SOURCE, translation, {"target_lang": "pt"})
        assert not result.success

    def test_hu_glued_article_and_suffix_rejected(self, validator):
        translation = (
            "mentés aWorkbook.save-el, és újratöltés aWorkbook.load_xlsx-szel."
        )
        result = validator.validate(SOURCE, translation, {"target_lang": "hu"})
        assert not result.success
        sides = {(i.details["term"], i.details["side"]) for i in result.issues}
        assert ("Workbook.save", "before") in sides

    def test_ar_multiletter_word_glued_to_dotted_identifier_rejected(self, validator):
        # From the original fixretrigger ar ticket: a full Arabic word
        # ("using") glued directly onto the dotted identifier.
        translation = "حفظ باستخدامWorkbook.save وإعادة تحميل باستخدامWorkbook.load_xlsx"
        result = validator.validate(SOURCE, translation, {"target_lang": "ar"})
        assert not result.success

    def test_committed_cargo_toml_glue_shapes_rejected(self, validator):
        # Real committed defects the 13k-file sweep surfaced on
        # cells/rust/getting-started/installation.md (fa, pl) and
        # _index.md (de, ru) -- same class, already live.
        src = "Add the crate to your Cargo.toml as a git dependency."
        for translation in (
            "do swojego plikuCargo.toml jako zależność",
            "Hinzufügen des Crates zu IhrerCargo.toml bis zum Erstellen",
            "от добавления крейта в вашCargo.toml до создания",
        ):
            result = validator.validate(src, translation, {"target_lang": "xx"})
            assert not result.success, translation


class TestLegalShapes:
    def test_clean_cs_output_accepted(self, validator):
        # The actual clean generation observed in the instrumented re-run.
        translation = (
            "Vytvořte svůj první Excel XLSX sešit v Rustu s Aspose.Cells FOSS: "
            "typované hodnoty buněk, vzorec s uloženým výsledkem, ukládání "
            "pomocí Workbook.save a načítání pomocí Workbook.load_xlsx."
        )
        result = validator.validate(SOURCE, translation, {"target_lang": "cs"})
        assert result.success, [i.message for i in result.issues]

    def test_slavic_latin_inflection_of_plain_term_accepted(self, validator):
        # cs inflects Rust -> "v Rustu": plain terms are out of scope
        # precisely because this is legitimate grammar.
        translation = "Vytvořte sešit v Rustu pomocí Workbook.save."
        result = validator.validate(SOURCE, translation, {"target_lang": "cs"})
        assert result.success, [i.message for i in result.issues]

    def test_ar_single_letter_particle_attached_accepted(self, validator):
        # Arabic one-letter conjunction "و" attaches to the following word
        # by orthographic rule -- "وAspose.Cells" is correct Arabic
        # (sweep: "وWOFF2" on docs font/_index.md is committed and legal).
        translation = "استخدم Workbook.save وAspose.Cells معًا"
        result = validator.validate(SOURCE, translation, {"target_lang": "ar"})
        assert result.success, [i.message for i in result.issues]

    def test_term_inside_longer_source_token_accepted(self, validator):
        # Sweep FP class: source contains both "input.doc" and
        # "input.docx"; scanning "input.doc" inside "input.docx" must not
        # flag the trailing "x".
        src = 'Open "input.doc" or "input.docx" with Document.'
        translation = 'doc = aw.Document("input.docx")'
        result = validator.validate(src, translation, {"target_lang": "cs"})
        assert result.success, [i.message for i in result.issues]

    def test_term_embedded_in_code_ish_composite_accepted(self, validator):
        # Sweep FP class: "email_str" matching inside a translation's
        # "MapiMessage.to_email_string" -- the surrounding parts carry
        # './_' structure, so it is a code composite, not prose glue,
        # even when that exact composite is absent from the source.
        src = "Use email_str for previews."
        translation = "- MapiMessage.to_email_string"
        result = validator.validate(src, translation, {"target_lang": "es"})
        assert result.success, [i.message for i in result.issues]

    def test_hu_hyphenated_suffix_accepted(self, validator):
        # Correct Hungarian attaches case suffixes to foreign terms with a
        # hyphen -- the hyphen is a legal boundary.
        translation = "mentés a Workbook.save-el, újratöltés a Workbook.load_xlsx-szel."
        result = validator.validate(SOURCE, translation, {"target_lang": "hu"})
        assert result.success, [i.message for i in result.issues]

    def test_cjk_no_space_convention_accepted(self, validator):
        # zh writes Latin terms with no surrounding space -- correct output
        # on the SAME page/run this class was found on.
        translation = "使用Workbook.save保存并使用Workbook.load_xlsx重新加载。"
        result = validator.validate(SOURCE, translation, {"target_lang": "zh"})
        assert result.success, [i.message for i in result.issues]

    def test_punctuation_boundaries_accepted(self, validator):
        translation = "Uložení (Workbook.save), načtení: Workbook.load_xlsx."
        result = validator.validate(SOURCE, translation, {"target_lang": "cs"})
        assert result.success, [i.message for i in result.issues]

    def test_identifier_absent_from_translation_is_not_this_gates_problem(
        self, validator
    ):
        # Missing identifiers are TerminologyPreservationValidator's job;
        # this gate only judges boundaries of occurrences that exist.
        translation = "Uložení a načtení sešitu."
        result = validator.validate(SOURCE, translation, {"target_lang": "cs"})
        assert result.success

    def test_segment_of_dotted_identifier_not_extracted_as_plain_term(
        self, validator
    ):
        # "Cells" only ever appears in source inside "Aspose.Cells" -- it
        # must not be treated as a standalone plain term, so a translation
        # word containing "Cells"-like letters cannot false-positive.
        src = "Save with Aspose.Cells today."
        translation = "Уложите с Aspose.Cells сегодня."
        result = validator.validate(src, translation, {"target_lang": "ru"})
        assert result.success, [i.message for i in result.issues]
