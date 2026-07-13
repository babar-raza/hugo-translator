"""
Tests for UnitQualityScorer -- per-unit quality detection.

Each detector gets at least 2 cases: True Positive (bad unit flagged)
and True Negative (good unit not flagged).
"""
import pytest

from src.translation_engine.unit_quality_scorer import UnitQualityScorer, UnitIssue
from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit(
    source_text,
    kind=TextUnitKind.TEXT,
    translated_text=None,
    node_addr="body.para[0].text[0]",
):
    unit = TextUnit(
        unit_id=TextUnit.create_id(node_addr, source_text, kind),
        node_addr=node_addr,
        kind=kind,
        source_text=source_text,
        translated_text=translated_text,
    )
    return unit


def _score(en_text, tr_text, locale="uk", kind=TextUnitKind.TEXT):
    scorer = UnitQualityScorer(config={}, locale=locale)
    en = _unit(en_text, kind=kind, node_addr="body.para[0].text[0]")
    tr = _unit(en_text, kind=kind, translated_text=tr_text, node_addr="body.para[0].text[0]")
    tr.source_text = tr_text
    issues = scorer.score([en], [tr])
    return [i.issue_type for i in issues]


# ---------------------------------------------------------------------------
# mojibake_detector
# ---------------------------------------------------------------------------

class TestMojibakeDetector:
    def test_tp_mojibake_accented(self):
        # Ã©  is the cp1252 mojibake for the letter e-acute
        # Ã = U+00C3, copyright = U+00A9
        mojibake_text = "RÃ©sumÃ© de la classe"
        issues = _score("Resume de la classe", mojibake_text, locale="fr")
        assert "mojibake_detector" in issues

    def test_tn_clean_ukrainian(self):
        issues = _score("Getting started", "Початок роботи", locale="uk")
        assert "mojibake_detector" not in issues

    def test_tn_clean_arabic(self):
        issues = _score("Introduction", "مقدمة", locale="ar")
        assert "mojibake_detector" not in issues


# ---------------------------------------------------------------------------
# shortcode_leak_detector
# ---------------------------------------------------------------------------

class TestShortcodeLeakDetector:
    def test_tp_shortcode_in_output_not_source(self):
        issues = _score(
            "See the example below.",
            "Дивіться приклад {{< some-shortcode >}}",
            locale="uk",
        )
        assert "shortcode_leak_detector" in issues

    def test_tn_shortcode_in_both(self):
        issues = _score(
            "See {{< example >}} below.",
            "Дивіться {{< example >}} нижче.",
            locale="uk",
        )
        assert "shortcode_leak_detector" not in issues

    def test_tn_no_shortcode(self):
        issues = _score("Simple sentence.", "Проста фраза.", locale="uk")
        assert "shortcode_leak_detector" not in issues


# ---------------------------------------------------------------------------
# inline_code_integrity_detector
# ---------------------------------------------------------------------------

class TestInlineCodeIntegrityDetector:
    def test_tp_translated_code_spans(self):
        # EN has 4 inline code spans (ASCII); TR has non-ASCII in first span
        en = "Use `AssetInfo`, `Document`, `PdfSaveOptions`, and `Encoder` for processing."
        tr = "Use `محل`, `Document`, `PdfSaveOptions`, and `Encoder` for processing."
        issues = _score(en, tr, locale="uk")
        assert "inline_code_integrity_detector" in issues

    def test_tn_preserved_code_spans(self):
        en = "Use `AssetInfo`, `Document`, `PdfSaveOptions`, and `Encoder` for processing."
        tr = "Використовуйте `AssetInfo`, `Document`, `PdfSaveOptions`, та `Encoder`."
        issues = _score(en, tr, locale="uk")
        assert "inline_code_integrity_detector" not in issues

    def test_tn_fewer_than_3_spans_no_trigger(self):
        en = "Use `AssetInfo` and `Document` for processing."
        tr = "Use `محل` and `Document` for processing."
        issues = _score(en, tr, locale="uk")
        assert "inline_code_integrity_detector" not in issues


# ---------------------------------------------------------------------------
# empty_unit_detector
# ---------------------------------------------------------------------------

class TestEmptyUnitDetector:
    def test_tp_empty_output_for_long_source(self):
        # Very short output (1 char) for a long source triggers the 10% ratio check
        issues = _score(
            "This is a fairly long English sentence that should definitely be translated.",
            "X",
            locale="uk",
        )
        assert "empty_unit_detector" in issues

    def test_tn_proportional_output(self):
        issues = _score(
            "Short text.",
            "Короткий текст.",
            locale="uk",
        )
        assert "empty_unit_detector" not in issues


# ---------------------------------------------------------------------------
# hallucination_length_detector (TABLE_CELL_TEXT)
# ---------------------------------------------------------------------------

class TestHallucinationLengthDetector:
    def test_tp_3x_longer_table_cell(self):
        en_text = "Gets the value."
        # TR is 5x longer -- hallucination
        tr_text = (
            "Отримує значення. "
            "Це значення являє "
            "собою пов'язані дані "
            "для поточного об'єкта."
        )
        issues = _score(en_text, tr_text, locale="uk", kind=TextUnitKind.TABLE_CELL_TEXT)
        assert "hallucination_length_detector" in issues

    def test_tn_normal_length_table_cell(self):
        issues = _score(
            "Gets the indent level.",
            "Отримує рівень відступу.",
            locale="uk",
            kind=TextUnitKind.TABLE_CELL_TEXT,
        )
        assert "hallucination_length_detector" not in issues

    def test_tn_text_kind_not_triggered(self):
        # detector only fires on TABLE_CELL_TEXT
        en_text = "Hi."
        tr_text = (
            "Це значення являє "
            "собою дані для всіх."
        )
        issues = _score(en_text, tr_text, locale="uk", kind=TextUnitKind.TEXT)
        assert "hallucination_length_detector" not in issues


# ---------------------------------------------------------------------------
# language_purity_detector (HEADING_TEXT)
# ---------------------------------------------------------------------------

class TestLanguagePurityDetector:
    def test_tp_english_heading_in_nonlatin_locale(self):
        # "Methods" remained English in Ukrainian doc
        issues = _score(
            "Methods",
            "Methods",
            locale="uk",
            kind=TextUnitKind.HEADING_TEXT,
        )
        assert "language_purity_detector" in issues

    def test_tn_translated_heading(self):
        issues = _score(
            "Properties",
            "Властивості",
            locale="uk",
            kind=TextUnitKind.HEADING_TEXT,
        )
        assert "language_purity_detector" not in issues

    def test_tn_latin_locale_not_triggered(self):
        # Purity detector only fires for non-Latin locales
        issues = _score(
            "Getting Started",
            "Getting Started",
            locale="de",
            kind=TextUnitKind.HEADING_TEXT,
        )
        assert "language_purity_detector" not in issues


# ---------------------------------------------------------------------------
# duplicate_run_detector
# ---------------------------------------------------------------------------

class TestDuplicateRunDetector:
    def test_tp_three_identical_paragraphs(self):
        repeated = "Цей параграф повторюється."
        tr_text = "{0}\n\n{0}\n\n{0}".format(repeated)
        issues = _score("Some source text.", tr_text, locale="uk")
        assert "duplicate_run_detector" in issues

    def test_tn_two_identical_paragraphs(self):
        p = "Параграф."
        tr_text = "{0}\n\n{0}\n\nІнший параграф.".format(p)
        issues = _score("Source.", tr_text, locale="uk")
        assert "duplicate_run_detector" not in issues

    def test_tn_no_duplicates(self):
        issues = _score("Hello world.", "Привіт світ.", locale="uk")
        assert "duplicate_run_detector" not in issues


# ---------------------------------------------------------------------------
# link_path_detector
# ---------------------------------------------------------------------------

class TestLinkPathDetector:
    def test_tp_corrupted_relative_path(self):
        en_text = "See [documentation](../../guide/overview/)."
        tr_text = "Дивіться [документацію](././guide/overview/)."
        issues = _score(en_text, tr_text, locale="uk")
        assert "link_path_detector" in issues

    def test_tn_preserved_relative_path(self):
        en_text = "See [documentation](../../guide/overview/)."
        tr_text = "Дивіться [документацію](../../guide/overview/)."
        issues = _score(en_text, tr_text, locale="uk")
        assert "link_path_detector" not in issues

    def test_tn_no_relative_links(self):
        en_text = "Visit [our site](https://example.com) for more."
        tr_text = "Відвідайте [наш сайт](https://example.com)."
        issues = _score(en_text, tr_text, locale="uk")
        assert "link_path_detector" not in issues


# ---------------------------------------------------------------------------
# newline_ratio_detector
# ---------------------------------------------------------------------------

class TestNewlineRatioDetector:
    def test_tp_exploded_newlines(self):
        en_text = "Line 1\nLine 2\nLine 3\nLine 4"
        tr_text = "Рядок 1\n\n\n\n\nРядок 2\n\n\n\n\nРядок 3\n\n\n\n\nРядок 4"
        issues = _score(en_text, tr_text, locale="uk")
        assert "newline_ratio_detector" in issues

    def test_tn_normal_newline_ratio(self):
        en_text = "Line 1\nLine 2\nLine 3\nLine 4"
        tr_text = "Рядок 1\nРядок 2\nРядок 3\nРядок 4"
        issues = _score(en_text, tr_text, locale="uk")
        assert "newline_ratio_detector" not in issues

    def test_tn_too_few_source_newlines_not_triggered(self):
        en_text = "Line 1\nLine 2"
        tr_text = "Рядок 1\n\n\n\nРядок 2"
        issues = _score(en_text, tr_text, locale="uk")
        assert "newline_ratio_detector" not in issues


# ---------------------------------------------------------------------------
# LCS pairing (count mismatch)
# ---------------------------------------------------------------------------

class TestLCSPairing:
    def test_pairing_handles_count_mismatch(self):
        scorer = UnitQualityScorer(config={}, locale="uk")
        en_units = [_unit("Hello.", node_addr="body.p[{0}]".format(i)) for i in range(3)]
        tr_units = [
            _unit("Привіт.", node_addr="body.p[{0}]".format(i))
            for i in range(5)
        ]
        issues = scorer.score(en_units, tr_units)
        assert isinstance(issues, list)

    def test_pairing_handles_equal_counts(self):
        scorer = UnitQualityScorer(config={}, locale="uk")
        en_units = [_unit("Word {0}.".format(i), node_addr="body.p[{0}]".format(i)) for i in range(4)]
        tr_units = [_unit("Слово {0}.".format(i), node_addr="body.p[{0}]".format(i)) for i in range(4)]
        issues = scorer.score(en_units, tr_units)
        assert isinstance(issues, list)
