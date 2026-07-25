"""
Integration tests for write gates 32-33 (HT-QUALITY-GATES-001 Part 22 /
plan 5.1 items 8-9): content-hash staleness and brand-token presence.

Both ship "warn" per this registry's established rollout convention (see
Gate 28/29's history in write_gate.py) -- neither has had a canary/
clean-sample pass yet.
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator


def _make_gate(force_accept: bool = True) -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    detector = MagicMock()
    detector.detect.return_value = ("de", 0.99)
    return WriteGateEvaluator(
        detector=detector,
        similarity_tracker=MagicMock(),
        config=config,
        force_accept=force_accept,
    )


class TestGateContentHashStaleness:
    def test_matching_hash_is_silent(self, caplog):
        src = (
            "---\ntitle: ColumnInfo\n"
            "provenance:\n  content_hash: abc123\n---\nbody\n"
        )
        tr = (
            "---\ntitle: ColumnInfo\n"
            "provenance:\n  content_hash: abc123\n---\nkörper\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE32" in r.message for r in caplog.records)

    def test_mismatched_hash_is_flagged(self, caplog):
        """Pinned real shape: reference.aspose.org/de/words/python/Document.md
        -- stale translation states a factually wrong method/property count
        directly traceable to a stale provenance.content_hash."""
        src = (
            "---\ntitle: Document\n"
            "provenance:\n  content_hash: newhash456\n---\n"
            "Document class with 2 methods and 13 properties.\n"
        )
        tr = (
            "---\ntitle: Document\n"
            "provenance:\n  content_hash: oldhash123\n---\n"
            "Document-Klasse mit 3 Methoden und 1 Eigenschaft.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/de/words/python/Document.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(tr, src, "de", output_path)

        assert result.passed is True  # warn-only
        assert any("GATE32 CONTENT HASH STALE" in r.message for r in caplog.records)

    def test_missing_provenance_in_either_file_is_silent(self, caplog):
        src = "---\ntitle: Foo\n---\nbody\n"
        tr = "---\ntitle: Foo\n---\nkörper\n"
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/de/pdf/net/Foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE32" in r.message for r in caplog.records)


class TestGateBrandTokenPresence:
    def test_aspose_present_in_both_is_silent(self, caplog):
        src = "---\ntitle: Aspose.Words FOSS\n---\nbody\n"
        tr = "---\ntitle: Aspose.Words FOSS для .NET\n---\nтело\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/ru/words/_index.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "ru", output_path)

        assert not any("GATE33" in r.message for r in caplog.records)

    def test_aspose_dropped_from_title_is_flagged(self, caplog):
        """Pinned real shape: docs.aspose.org/ar/words/_index.md --
        title: Aspose.Words FOSS -> '"أفترض" كلمات (فوس)' (brand name
        mistranslated as "I suppose/assume" via phonetic collision)."""
        src = "---\ntitle: Aspose.Words FOSS\n---\nbody\n"
        tr = '---\ntitle: \'"أفترض" كلمات (فوس)\'\n---\nمتن\n'
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/ar/words/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(tr, src, "ar", output_path)

        assert result.passed is True  # warn-only
        assert any("GATE33 BRAND TOKEN MISSING" in r.message for r in caplog.records)

    def test_aspose_absent_from_en_source_is_silent(self, caplog):
        """The check only fires when EN itself has 'Aspose' in the field --
        a page whose EN title legitimately has no brand token must not
        trigger just because the translation also lacks it."""
        src = "---\ntitle: Getting Started\n---\nbody\n"
        tr = "---\ntitle: Erste Schritte\n---\nkörper\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/words/getting-started.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE33" in r.message for r in caplog.records)

    def test_case_insensitive_match(self, caplog):
        src = "---\ntitle: ASPOSE.PDF FOSS\n---\nbody\n"
        tr = "---\ntitle: aspose.pdf FOSS für .NET\n---\nkörper\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/pdf/_index.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE33" in r.message for r in caplog.records)

    def test_head_title_dropped_brand_token_is_flagged(self, caplog):
        """Independent-verification test-gap finding: every existing test in
        this class used `title` only, even though the gate also checks
        `head_title`/`seoTitle` -- neither was ever actually exercised."""
        src = "---\ntitle: Getting Started\nhead_title: Aspose.PDF for Java\n---\nbody\n"
        tr = "---\ntitle: Erste Schritte\nhead_title: PDF für Java\n---\nkörper\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/pdf/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(tr, src, "de", output_path)

        assert result.passed is True  # warn-only
        assert any("GATE33 BRAND TOKEN MISSING" in r.message for r in caplog.records)

    def test_seotitle_dropped_brand_token_is_flagged(self, caplog):
        src = "---\ntitle: Getting Started\nseoTitle: Aspose.PDF for Java\n---\nbody\n"
        tr = "---\ntitle: Erste Schritte\nseoTitle: PDF für Java\n---\nkörper\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/pdf/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(tr, src, "de", output_path)

        assert result.passed is True  # warn-only
        assert any("GATE33 BRAND TOKEN MISSING" in r.message for r in caplog.records)
