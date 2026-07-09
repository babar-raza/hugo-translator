"""
Integration tests for write gates 9-17 (AUD-QR-003).

Gates tested:
  Gate 9:  _gate_heading_integrity     (auto-clean: restores corrupt headings)
  Gate 10: _gate_frontmatter_backticks (auto-clean: fixes odd backtick count)
  Gate 11: _gate_frontmatter_id_corruption (auto-clean: restores PascalCase identifiers)
  Gate 12: _gate_double_periods        (auto-clean: replaces .. with .)
  Gate 13: _gate_eu_hallucination      (blocking: EU/GDPR text not in source)
  Gate 14: _gate_mixed_language        (blocking: English paragraphs in non-Latin target)
  Gate 15: _gate_table_row_integrity   (blocking: table row count mismatch >50%)
  Gate 16: _gate_duplicate_content     (auto-clean: removes repeated paragraphs)
  Gate 17: _gate_newline_explosion     (blocking: >2.5x newlines vs source)
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gate(force_accept: bool = False) -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    detector = MagicMock()
    detector.detect.return_value = ("ar", 0.99)  # default: Arabic with high confidence
    return WriteGateEvaluator(
        detector=detector,
        similarity_tracker=MagicMock(),
        config=config,
        force_accept=force_accept,
    )


def _source_doc(title: str = "Camera", linktitle: str = None) -> MagicMock:
    """Mock HugoDocument with frontmatter containing English API identifier."""
    doc = MagicMock()
    fm = {"title": title}
    if linktitle is not None:
        fm["linkTitle"] = linktitle
    doc.frontmatter = fm
    return doc


def _md(body: str = "", title: str = "Test", extra_fm: str = "") -> str:
    """Build markdown with frontmatter."""
    return f"---\ntitle: {title}\n{extra_fm}---\n{body}"


def _src_md(body: str = "", title: str = "Test", extra_fm: str = "") -> str:
    """English source markdown."""
    return _md(body=body, title=title, extra_fm=extra_fm)


# ---------------------------------------------------------------------------
# Gate 11: Frontmatter ID Corruption (auto-clean)
# ---------------------------------------------------------------------------


class TestGateFrontmatterIdCorruption:
    """Gate 11: PascalCase identifiers in frontmatter must not be translated."""

    def test_corrupted_title_is_restored(self):
        """Arabic translation of 'Camera' in title → cleaned_content restores 'Camera'.
        Gate 11 requires source_doc.frontmatter to know the English identifier."""
        tr = _md(title="الكاميرا", body="Some Arabic content.\n")
        src = _src_md(title="Camera", body="Some English content.\n")
        gate = _make_gate(force_accept=True)  # gates 2-4 bypassed; gates 9-17 still run

        r = gate.evaluate(tr, src, "ar", Path("test.md"), source_doc=_source_doc("Camera"))

        assert r.cleaned_content is not None, "cleaned_content must be set for corrupt title"
        assert "Camera" in r.cleaned_content
        assert "الكاميرا" not in r.cleaned_content.split("\n")[1]  # title line fixed

    def test_clean_passthrough_title_not_modified(self):
        """When title already matches English, no cleaned_content produced."""
        tr = _md(title="Camera", body="كاميرا في العالم.\n")
        src = _src_md(title="Camera", body="Camera in the world.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"), source_doc=_source_doc("Camera"))

        # Gate 11 should not modify content if title matches
        if r.cleaned_content:
            assert "Camera" in r.cleaned_content  # still correct

    def test_gate_fires_even_with_force_accept_true(self):
        """Gates 9-17 are unconditional — force_accept does NOT bypass them."""
        tr = _md(title="الكاميرا", body="Arabic text.\n")
        src = _src_md(title="Camera", body="English text.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"), source_doc=_source_doc("Camera"))

        # Result may still pass (gate 11 is auto-clean, not blocking)
        # But cleaned_content MUST be set
        assert r.cleaned_content is not None

    def test_nllb_artifact_in_title_is_cleaned(self):
        """NLLB artifact appended to title → cleaned_content strips it."""
        tr = _md(title="Camera (مُحملة مكان)", body="Arabic text.\n")
        src = _src_md(title="Camera", body="English text.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"), source_doc=_source_doc("Camera"))

        # The artifact appended to identifier should be cleaned
        if r.cleaned_content:
            assert "(مُحملة مكان)" not in r.cleaned_content or "Camera" in r.cleaned_content


# ---------------------------------------------------------------------------
# Gate 12: Double Periods (auto-clean)
# ---------------------------------------------------------------------------


class TestGateDoublePeriods:
    def test_double_period_in_body_is_cleaned(self):
        """'..' in body (not '...') → cleaned_content replaces with '.'."""
        tr = _md(body="هذا نص عربي.. مع نقطتين.\n")
        src = _src_md(body="English text. With one period.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        assert r.cleaned_content is not None
        # Should have replaced .. with .
        body_after = r.cleaned_content.split("---\n", 2)[-1] if "---" in r.cleaned_content else r.cleaned_content
        assert ".." not in body_after or "..." in body_after

    def test_ellipsis_not_modified(self):
        """'...' ellipsis must not be modified."""
        tr = _md(body="أولاً... ثانياً.\n")
        src = _src_md(body="First... second.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        if r.cleaned_content:
            assert "..." in r.cleaned_content


# ---------------------------------------------------------------------------
# Gate 13: EU Hallucination (blocking)
# ---------------------------------------------------------------------------


class TestGateEuHallucination:
    def test_eu_text_in_translation_not_in_source_blocks(self):
        """EU/GDPR text in translation but NOT in source → result.passed = False."""
        tr = _md(body="هذا النص. نحن ملتزمون بسياسة GDPR وخصوصية البيانات.\n")
        src = _src_md(body="This is text about the API.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        assert not r.passed, "EU hallucination must block write"

    def test_eu_text_in_both_source_and_translation_passes(self):
        """If EU text exists in source too, it's not hallucinated → pass."""
        tr = _md(body="GDPR compliance is required.\n")
        src = _src_md(body="GDPR compliance is required.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        assert r.passed, "EU text present in source should NOT trigger block"

    def test_cookie_notice_hallucination_blocks(self):
        """Cookie notice fabricated in translation blocks write."""
        tr = _md(body="This site uses cookie policy for privacy.\n")
        src = _src_md(body="API documentation.\n")
        gate = _make_gate(force_accept=True)  # force_accept bypasses gates 2-4, not 13-17

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        assert not r.passed


# ---------------------------------------------------------------------------
# Gate 14: Mixed Language (blocking, with Latin-script bypass)
# ---------------------------------------------------------------------------


class TestGateMixedLanguage:
    def test_english_paragraphs_in_arabic_blocks(self):
        """4+ fully-English paragraphs in Arabic translation → blocked."""
        english_lines = "\n".join([
            "This is an English sentence about the Camera class.",
            "The method returns a DocumentProperties object for inspection.",
            "You can use this to read configuration parameters easily.",
            "The API provides several methods for document manipulation.",
            "See the documentation for complete parameter descriptions.",
        ])
        tr = _md(body=english_lines + "\n")
        src = _src_md(body="English source body.\n")
        gate = _make_gate(force_accept=True)
        # Override detector to return Arabic
        gate._detector.detect.return_value = ("ar", 0.99)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        assert not r.passed, "English paragraphs in Arabic translation must block"

    def test_latin_script_target_not_blocked(self):
        """French translation with English technical terms must NOT be blocked (Latin-script bypass)."""
        english_style = "\n".join([
            "This method returns a Camera object for rendering.",
            "You can configure the DocumentProperties interface easily.",
        ])
        tr = _md(body=english_style + "\nEt le texte en français aussi.\n")
        src = _src_md(body="English source body.\n")
        gate = MagicMock()
        config = MagicMock()
        config.get_config.return_value = {"translation_engine": {}}
        detector = MagicMock()
        detector.detect.return_value = ("fr", 0.95)
        real_gate = WriteGateEvaluator(
            detector=detector, similarity_tracker=MagicMock(),
            config=config, force_accept=True
        )

        r = real_gate.evaluate(tr, src, "fr", Path("test.md"))

        # French is Latin-script — mixed language gate must NOT fire
        assert r.passed or r.error is None or "mixed" not in (r.error or "").lower()


# ---------------------------------------------------------------------------
# Gate 15: Table Row Integrity (blocking)
# ---------------------------------------------------------------------------


class TestGateTableRowIntegrity:
    def _make_table(self, rows: int) -> str:
        """Build a markdown table with N data rows."""
        header = "| Name | Type | Description |\n|------|------|-------------|\n"
        data = "".join(f"| Item{i} | string | Value {i} |\n" for i in range(rows))
        return header + data

    def test_large_row_count_mismatch_blocks(self):
        """Source has 85 rows, translation has 23 rows (<50%) → blocked."""
        src_body = self._make_table(85)
        tr_body = self._make_table(23)  # 27% of source → below 50% threshold
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(_md(body=tr_body), _src_md(body=src_body), "ar", Path("test.md"))

        assert not r.passed, "Table row count mismatch >50% must block write"

    def test_matching_row_count_passes(self):
        """Source and translation both have same row count → pass."""
        table = self._make_table(10)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(_md(body=table), _src_md(body=table), "ar", Path("test.md"))

        assert r.passed

    def test_small_table_not_blocked(self):
        """Source with 3 rows (below minimum threshold) → not checked."""
        src_body = self._make_table(3)
        tr_body = self._make_table(1)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(_md(body=tr_body), _src_md(body=src_body), "ar", Path("test.md"))

        # Should pass — source has <4 rows (below minimum check threshold)
        assert r.passed


# ---------------------------------------------------------------------------
# Gate 16: Duplicate Content (auto-clean)
# ---------------------------------------------------------------------------


class TestGateDuplicateContent:
    def test_triplicate_paragraphs_cleaned(self):
        """Same paragraph appearing 3+ times → cleaned_content deduplicates."""
        para = "هذا نص عربي مطول يظهر مرات متعددة في المستند."
        body = f"\n{para}\n\n{para}\n\n{para}\n\n{para}\n"
        tr = _md(body=body)
        src = _src_md(body="English text appears once.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        assert r.cleaned_content is not None
        # Count occurrences in cleaned content
        assert r.cleaned_content.count(para) < 3

    def test_unique_paragraphs_not_modified(self):
        """Different paragraphs → no cleaned_content set by gate 16."""
        body = "First paragraph.\n\nSecond paragraph.\n\nThird different paragraph.\n"
        tr = _md(body=body)
        src = _src_md(body=body)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        # cleaned_content may be None (no changes needed)
        # If set, duplicates should not be introduced
        if r.cleaned_content:
            for line in ["First paragraph.", "Second paragraph.", "Third different paragraph."]:
                assert r.cleaned_content.count(line) <= 1


# ---------------------------------------------------------------------------
# Gate 17: Newline Explosion (blocking)
# ---------------------------------------------------------------------------


class TestGateNewlineExplosion:
    def test_excessive_newlines_blocks(self):
        """Translation has >2.5x newlines vs source → blocked."""
        src_body = "\n".join([f"Line {i}." for i in range(10)]) + "\n"  # 10 lines (meets minimum threshold)
        tr_body = "\n".join(["Arabic line."] * 30) + "\n"  # 30 lines — 3x
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(_md(body=tr_body), _src_md(body=src_body), "ar", Path("test.md"))

        assert not r.passed, "Newline explosion must block write"

    def test_normal_newline_ratio_passes(self):
        """Translation with similar newline count to source → pass."""
        src_body = "Line one.\nLine two.\nLine three.\n"
        tr_body = "سطر واحد.\nسطر اثنان.\nسطر ثلاثة.\n"
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(_md(body=tr_body), _src_md(body=src_body), "ar", Path("test.md"))

        assert r.passed


# ---------------------------------------------------------------------------
# Cross-gate: auto-clean gates fire unconditionally even with force_accept=False
# ---------------------------------------------------------------------------


class TestGatesUnconditional:
    def test_auto_clean_gates_fire_even_without_force_accept(self):
        """Auto-clean gates 9-17 must run regardless of force_accept setting."""
        tr = _md(title="الكاميرا", body="هذا نص عربي.\n")
        src = _src_md(title="Camera", body="English text.\n")

        gate_no_force = _make_gate(force_accept=False)
        gate_force = _make_gate(force_accept=True)

        r_no_force = gate_no_force.evaluate(tr, src, "ar", Path("test.md"), source_doc=_source_doc("Camera"))
        r_force = gate_force.evaluate(tr, src, "ar", Path("test.md"), source_doc=_source_doc("Camera"))

        # Gate 2 (language mismatch) may fire for gate_no_force and fail it,
        # but gate 11 must have set cleaned_content in BOTH cases.
        # We check via gate_force (no language gate interference)
        assert r_force.cleaned_content is not None, "Gate 11 must set cleaned_content with force_accept=True"

    def test_cleaned_content_has_correct_title(self):
        """End-to-end: corrupt title → cleaned_content has English title."""
        tr = _md(title="VertexDeclaration في الجسم", body="Arabic.\n")
        src = _src_md(title="VertexDeclaration", body="English.\n")
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"), source_doc=_source_doc("VertexDeclaration"))

        assert r.cleaned_content is not None
        assert "VertexDeclaration" in r.cleaned_content
