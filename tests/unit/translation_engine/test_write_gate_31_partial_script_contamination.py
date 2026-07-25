"""
Integration tests for write gate 31 (HT-QUALITY-GATES-001 Part 22 addendum):
partial foreign-script contamination.

User-flagged, live-verified 2026-07-22: reference.aspose.org's
he/pdf/net/ColumnInfo.md came back with real Spanish phrases embedded in
otherwise-Hebrew content, on two independent, byte-identical (temperature=0.0)
live translation runs -- confirming this is a distinct, deterministic bug,
not an instance of the Phase 2 concurrency/TM fixes (which were separately
verified not to change this file's output at all). Gate 24
(_gate_description_reverted_to_english) only catches TOTAL reversion to
ASCII; this gate catches the much more common partial case that a
whole-field/whole-file dominant-language detector cannot see.

Ships "warn" (not "block") per this registry's established rollout
convention -- see the code comment on Gate 31's GATE_REGISTRY entry.
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator


def _make_gate(force_accept: bool = True, detected_lang: str = "he") -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    detector = MagicMock()
    detector.detect.return_value = (detected_lang, 0.99)
    return WriteGateEvaluator(
        detector=detector,
        similarity_tracker=MagicMock(),
        config=config,
        force_accept=force_accept,
    )


class TestGatePartialScriptContamination:
    def test_real_confirmed_spanish_in_hebrew_body_is_flagged(self, caplog):
        """Pinned case: the exact real defect found in
        reference.aspose.org/he/pdf/net/ColumnInfo.md."""
        src = "---\ntitle: ColumnInfo\n---\nColumnInfo holds layout details.\n"
        tr = (
            "---\ntitle: ColumnInfo\n---\n"
            "[מגוון] תומך בפרטים של טבלה, expuesto ColumnWidths, ColumnSpacing "
            "ו las propiedades ColumnCount para el tamaño de columna preciso.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/he/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(tr, src, "he", output_path)

        assert any("GATE31" in r.message for r in caplog.records)
        # warn-only: must never flip result.passed
        assert result.passed is True

    def test_real_confirmed_spanish_closing_link_is_flagged(self, caplog):
        """Second real confirmed instance from the same file: the closing
        'See Also' link rendered fully in Spanish instead of Hebrew."""
        src = "---\ntitle: ColumnInfo\n---\n- [Aspose.PDF for .NET — Enterprise API Reference](https://reference.aspose.com/pdf/net/)\n"
        tr = (
            "---\ntitle: ColumnInfo\n---\n"
            "- [Aspose.PDF para .NET — Referencia de API Enterprise]"
            "(https://reference.aspose.com/pdf/net/)\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/he/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "he", output_path)

        assert any("GATE31" in r.message for r in caplog.records)

    def test_clean_hebrew_content_is_silent(self, caplog):
        src = "---\ntitle: ColumnInfo\n---\nColumnInfo holds layout details.\n"
        tr = (
            "---\ntitle: ColumnInfo\n---\n"
            "ColumnInfo מחזיק פרטים על הפריסה של הטבלה.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/he/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "he", output_path)

        assert not any("GATE31" in r.message for r in caplog.records)

    def test_single_isolated_latin_word_is_not_flagged(self, caplog):
        """A single preserved brand/technical token (not a multi-word run)
        must not trigger -- this is the expected, legitimate shape for
        preserved identifiers like 'Aspose' or 'PDF'."""
        src = "---\ntitle: ColumnInfo\n---\nUses the Aspose library.\n"
        tr = "---\ntitle: ColumnInfo\n---\nמשתמש בספריית Aspose.\n"
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/he/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "he", output_path)

        assert not any("GATE31" in r.message for r in caplog.records)

    def test_latin_words_inside_code_fence_are_ignored(self, caplog):
        src = "---\ntitle: ColumnInfo\n---\n```csharp\nvar x = new Example();\n```\n"
        tr = (
            "---\ntitle: ColumnInfo\n---\n"
            "דוגמה:\n\n```csharp\nvar x = new Example here for testing purposes only;\n```\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/he/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "he", output_path)

        assert not any("GATE31" in r.message for r in caplog.records)

    def test_latin_words_inside_backtick_span_are_ignored(self, caplog):
        src = "---\ntitle: ColumnInfo\n---\nSee `Some Long Identifier Name` for details.\n"
        tr = "---\ntitle: ColumnInfo\n---\nראה `Some Long Identifier Name` לפרטים.\n"
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/he/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "he", output_path)

        assert not any("GATE31" in r.message for r in caplog.records)

    def test_url_itself_is_not_flagged_only_anchor_text_scanned(self, caplog):
        src = "---\ntitle: ColumnInfo\n---\n- [ראה כאן](https://example.com/some/long/english/path)\n"
        tr = "---\ntitle: ColumnInfo\n---\n- [ראה כאן](https://example.com/some/long/english/path)\n"
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/he/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "he", output_path)

        assert not any("GATE31" in r.message for r in caplog.records)

    def test_vietnamese_is_never_checked_despite_shared_non_latin_set(self, caplog):
        """Vietnamese ("vi") appears in the SHARED _NON_LATIN_SCRIPT_LOCALES
        constant (used by Gate 24 and others for different reasons), but
        Vietnamese IS written in Latin script (Quốc Ngữ) -- every genuine
        Vietnamese sentence contains plain-ASCII Latin words. Confirmed as a
        real false-positive source during testing (17 spurious hits on one
        real kb.aspose.org/vi file). Gate 31 must use its own locale set,
        not the shared one, and vi must never fire."""
        src = "---\ntitle: Foo\n---\nLoad 3D models with the FOSS library for Java.\n"
        tr = (
            "---\ntitle: Foo\n---\n"
            "Aspose.3D FOSS cho Java cung cấp khả năng tải mô hình 3D "
            "từ nhiều định dạng khác nhau như OBJ, STL và glTF.\n"
        )
        gate = _make_gate(detected_lang="vi")
        output_path = Path("/content/kb.aspose.org/vi/3d/java/foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "vi", output_path)

        assert not any("GATE31" in r.message for r in caplog.records)

    def test_brand_and_technical_phrases_are_not_flagged(self, caplog):
        """Confirmed real false-positive sources from a 40-file production
        sample: ordinary 2-4 word brand/technical phrases with no Romance/
        Germanic function word must not fire, even though they're technically
        multi-word Latin-script runs."""
        src = "---\ntitle: Foo\n---\nAspose.Cells FOSS for Java, from Microsoft Office to Enterprise API Reference.\n"
        tr = (
            "---\ntitle: Foo\n---\n"
            "השתמש ב-Aspose.Cells FOSS for Java, מ-Microsoft Office ל-Enterprise API Reference.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/kb.aspose.org/he/cells/java/foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "he", output_path)

        assert not any("GATE31" in r.message for r in caplog.records)

    def test_latin_script_locale_is_never_checked(self, caplog):
        """The gate must be a no-op entirely for Latin-script target locales
        (e.g. es, fr, de) -- multi-word Latin runs are the ENTIRE expected
        output there, not a defect."""
        src = "---\ntitle: ColumnInfo\n---\nColumnInfo holds layout details.\n"
        tr = "---\ntitle: ColumnInfo\n---\nColumnInfo contiene detalles del diseño de la tabla.\n"
        gate = _make_gate(detected_lang="es")
        output_path = Path("/content/reference.aspose.org/es/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "es", output_path)

        assert not any("GATE31" in r.message for r in caplog.records)
