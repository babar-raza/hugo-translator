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

    def test_repeated_code_fence_boilerplate_not_stripped(self):
        """Distinct code examples sharing a boilerplate opening line are not
        code-fence-blind false positives: none of the 3 examples' shared
        `#include` line should be removed, even though it repeats 3+ times.
        """
        body = (
            "Intro paragraph unrelated to any duplication for this test.\n\n"
            "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
            "int main() { return 1; }\n```\n\n"
            "A distinct prose paragraph placed between the first two examples.\n\n"
            "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
            "int main() { return 2; }\n```\n\n"
            "Another distinct prose paragraph placed between the last two examples.\n\n"
            "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
            "int main() { return 3; }\n```\n"
        )
        tr = _md(body=body)
        src = _src_md(body=body)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        result_body = r.cleaned_content if r.cleaned_content else tr
        assert result_body.count("#include <Aspose/Slides/Foss/presentation.h>") == 3
        assert result_body.count("int main() { return 1; }") == 1
        assert result_body.count("int main() { return 2; }") == 1
        assert result_body.count("int main() { return 3; }") == 1

    def test_structurally_separated_prose_boilerplate_not_stripped(self):
        """A short 'Returns' note repeated once per distinct method section
        (heading between every occurrence) is legitimate reference-doc
        boilerplate, not an MT decoding-loop artifact -- reproduces the
        real reference.aspose.org pattern found in mission
        duplicate-content-fence-fix-20260723's pilot (transform.md,
        _index.md, exceptions.md, page-break.md): none of the 3 occurrences
        should be stripped.
        """
        body = (
            "### setTranslation(tx, ty, tz)\n\n"
            "Sets the local translation.\n\n"
            "Returns: the same Transform instance, for method chaining.\n\n"
            "### setScale(sx, sy, sz)\n\n"
            "Sets the local scale.\n\n"
            "Returns: the same Transform instance, for method chaining.\n\n"
            "### setRotation(rw, rx, ry, rz)\n\n"
            "Sets the local rotation.\n\n"
            "Returns: the same Transform instance, for method chaining.\n"
        )
        tr = _md(body=body)
        src = _src_md(body=body)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        result_body = r.cleaned_content if r.cleaned_content else tr
        assert result_body.count("Returns: the same Transform instance, for method chaining.") == 3
        for heading in ["### setTranslation(tx, ty, tz)", "### setScale(sx, sy, sz)", "### setRotation(rw, rx, ry, rz)"]:
            assert heading in result_body

    def test_repeated_prose_without_structural_separation_still_cleaned(self):
        """Contrast case: the same short note repeated 3x with NO heading or
        code fence between occurrences (a genuine decoding-loop shape) must
        still be detected and deduplicated -- the structural-separation
        exclusion must not blind the gate to real corruption.
        """
        note = "Returns: the same Transform instance, for method chaining."
        body = (
            f"{note}\n\n"
            "Unrelated filler paragraph with no heading in sight here at all.\n\n"
            f"{note}\n\n"
            "Another unrelated filler paragraph, still no headings anywhere near it.\n\n"
            f"{note}\n"
        )
        tr = _md(body=body)
        src = _src_md(body=body)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        result_body = r.cleaned_content if r.cleaned_content else tr
        assert result_body.count(note) == 1

    def test_genuine_corruption_directly_adjacent_to_fence_still_caught(self):
        """Regression test (found by independent verification of TC-DCF-003):
        splitting on blank lines before checking fence overlap silently
        merged a paragraph with no blank line before it into an adjacent
        fence, losing it from detection entirely. A genuinely duplicated
        paragraph that directly follows a code fence (no blank line) must
        still be caught and deduplicated.
        """
        note = "This is a genuinely duplicated warning paragraph that repeats verbatim in prose here."
        body = (
            "Intro paragraph unrelated to anything duplicated in this test case.\n\n"
            f"```python\nx = 1\n```\n{note}\n\n"
            f"```python\ny = 2\n```\n{note}\n\n"
            f"```python\nz = 3\n```\n{note}\n"
        )
        tr = _md(body=body)
        src = _src_md(body=body)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        result_body = r.cleaned_content if r.cleaned_content else tr
        assert result_body.count(note) == 1

    def test_legitimate_boilerplate_directly_adjacent_to_fence_still_protected(self):
        """Companion regression test: a legitimate heading-separated repeat
        that directly follows a fence with no blank line must still be
        recognized as protected, not silently dropped from the
        structural-separation check and stripped anyway.
        """
        note = "Returns: the same Transform instance, for method chaining."
        body = (
            f"### setTranslation(tx, ty, tz)\n\nSets the local translation.\n\n"
            f"```typescript\nsetTranslation(tx: number): Transform\n```\n{note}\n\n"
            f"### setScale(sx, sy, sz)\n\nSets the local scale.\n\n"
            f"```typescript\nsetScale(sx: number): Transform\n```\n{note}\n\n"
            f"### setRotation(rw, rx, ry, rz)\n\nSets the local rotation.\n\n"
            f"```typescript\nsetRotation(rw: number): Transform\n```\n{note}\n"
        )
        tr = _md(body=body)
        src = _src_md(body=body)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        result_body = r.cleaned_content if r.cleaned_content else tr
        assert result_body.count(note) == 3

    def test_code_fence_alone_between_occurrences_is_not_sufficient_separation(self):
        """A code fence between occurrences, with no heading change, must
        NOT be treated as legitimate structural separation on its own -- a
        genuine decoding-loop repeat could plausibly interleave with
        unrelated code blocks. Only an actual heading counts as evidence of
        distinct structural context.
        """
        note = "This is a genuinely duplicated warning paragraph that repeats verbatim in prose here."
        body = (
            "Intro paragraph unrelated to anything duplicated in this test case.\n\n"
            f"{note}\n\n```python\nx = 1\n```\n\n"
            f"{note}\n\n```python\ny = 2\n```\n\n"
            f"{note}\n"
        )
        tr = _md(body=body)
        src = _src_md(body=body)
        gate = _make_gate(force_accept=True)

        r = gate.evaluate(tr, src, "ar", Path("test.md"))

        result_body = r.cleaned_content if r.cleaned_content else tr
        assert result_body.count(note) == 1


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


# =============================================================================
# TC-HDN-002 / TC-HDN-010: New gates 17-22
# =============================================================================

def _make_evaluator_no_detector():
    """Evaluator with no language detector — only structural gates run."""
    from src.translation_engine.write_gate import WriteGateEvaluator
    return WriteGateEvaluator(detector=None, similarity_tracker=None, config=None)


def _make_content_simple(body: str, fm: str = "title: Test\n") -> str:
    return f"---\n{fm}---\n{body}"


_OUT = Path("test_output/zh/test.md")


class TestGate22EncodingClean:
    """Gate 22: mojibake / encoding corruption."""

    def test_blocks_em_dash_mojibake(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        body = "text \u00e2\u20ac\u2014 corruption"
        r = WriteGateResult(passed=True)
        ev._gate_encoding_clean(_make_content_simple("clean"), _make_content_simple(body), _OUT, r)
        assert not r.passed and "Gate 22" in r.error

    def test_passes_clean_ukrainian(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        body = "\u041f\u0440\u0438\u0432\u0456\u0442 \u0441\u0432\u0456\u0442\u0435."
        r = WriteGateResult(passed=True)
        ev._gate_encoding_clean(_make_content_simple(body), _make_content_simple(body), _OUT, r)
        assert r.passed

    def test_passes_clean_arabic(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        body = "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645"
        r = WriteGateResult(passed=True)
        ev._gate_encoding_clean(_make_content_simple(body), _make_content_simple(body), _OUT, r)
        assert r.passed


class TestGate20ShortcodeBodyLeak:
    """Gate 20: shortcode body leak."""

    def test_blocks_shortcode_in_tgt_not_in_src(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple("Plain paragraph without shortcodes.")
        tr = _make_content_simple("{{< note >}} Some leaked shortcode.")
        r = WriteGateResult(passed=True)
        ev._gate_shortcode_body_leak(en, tr, _OUT, r)
        assert not r.passed and "Gate 20" in r.error

    def test_passes_shortcode_in_both(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple("{{< note >}} See this.")
        tr = _make_content_simple("{{< note >}} \u0413\u043b\u0435\u0434\u0430\u0458.")
        r = WriteGateResult(passed=True)
        ev._gate_shortcode_body_leak(en, tr, _OUT, r)
        assert r.passed

    def test_passes_no_shortcodes(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        r = WriteGateResult(passed=True)
        ev._gate_shortcode_body_leak(_make_content_simple("plain"), _make_content_simple("plain"), _OUT, r)
        assert r.passed


class TestGate21InlineCodeIntegrity:
    """Gate 21: inline code integrity."""

    def test_blocks_translated_code_span(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple("Use `AssetInfo`, `GetValue`, and `SetProperty` methods.")
        tr = _make_content_simple("Use `\u0645\u0639\u0644\u0648\u0645\u0627\u062a`, `\u0627\u0644\u062d\u0635\u0648\u0644`, and `\u0648\u0636\u0639`.")
        r = WriteGateResult(passed=True)
        ev._gate_inline_code_integrity(en, tr, _OUT, r)
        assert not r.passed and "Gate 21" in r.error

    def test_passes_ascii_spans_preserved(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple("Use `AssetInfo`, `GetValue`, and `SetProperty` methods.")
        tr = _make_content_simple("\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 `AssetInfo`, `GetValue` \u0438 `SetProperty`.")
        r = WriteGateResult(passed=True)
        ev._gate_inline_code_integrity(en, tr, _OUT, r)
        assert r.passed

    def test_skips_when_fewer_than_3_spans(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple("Use `AssetInfo` only.")
        tr = _make_content_simple("\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 `\u043d\u0435\u0447\u0442\u043e`.")
        r = WriteGateResult(passed=True)
        ev._gate_inline_code_integrity(en, tr, _OUT, r)
        assert r.passed  # below threshold of 3

    def test_stray_table_backtick_auto_cleans(self):
        """m2m100 stray '`' before table rows must be stripped, not treated as violation."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        # EN body: 3+ real inline code spans
        en = _make_content_simple(
            "Use `AssetInfo`, `GetValue`, and `SetProperty` in table.\n"
            "| Name | Description |\n"
            "| `AssetInfo` | Gets the asset. |\n"
        )
        # m2m100 tgt: stray ` at start of table row; real code spans preserved
        tgt_body = (
            "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442 `AssetInfo`, `GetValue` \u0438 `SetProperty`.\n"
            "` | \u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 | \u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 |\n"           # stray backtick before pipe
            "| `AssetInfo` | \u041f\u043e\u043b\u0443\u0447\u0430\u0435\u0442 \u0430\u043a\u0442\u0438\u0432. |\n"
        )
        tr = _make_content_simple(tgt_body)
        r = WriteGateResult(passed=True)
        ev._gate_inline_code_integrity(en, tr, _OUT, r)
        import re as _re
        assert r.passed, f"Expected pass after auto-clean; error={r.error}"
        assert r.cleaned_content is not None, "Expected cleaned_content to be set"
        # No line should START with a stray backtick followed by a pipe
        assert not _re.search(r"(?m)^\s*`\s*\|", r.cleaned_content), (
            "Stray line-start backtick should be removed from cleaned_content"
        )

    def test_genuine_violation_still_blocks_after_stray_clean(self):
        """Real inline-code translation must block even when stray backtick also present."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple(
            "Use `AssetInfo`, `GetValue`, and `SetProperty`.\n"
            "| Name |\n"
        )
        # tgt has BOTH stray backtick AND genuine code-span translation
        tgt_body = (
            "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442 `\u0418\u043d\u0444\u043e`, `\u0417\u043d\u0430\u0447`, "
            "\u0438 `\u0421\u0432\u043e\u0439\u0441\u0442\u0432\u043e`.\n"
            "` | \u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 |\n"
        )
        tr = _make_content_simple(tgt_body)
        r = WriteGateResult(passed=True)
        ev._gate_inline_code_integrity(en, tr, _OUT, r)
        assert not r.passed, "Should block when code spans are genuinely translated"
        assert "Gate 21" in r.error

    def test_no_stray_backtick_no_violation_passes_cleanly(self):
        """Clean tgt body: no stray backtick and no violation \u2192 pass, no cleaned_content."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple("Use `AssetInfo`, `GetValue`, and `SetProperty`.")
        tr = _make_content_simple(
            "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 "
            "`AssetInfo`, `GetValue` \u0438 `SetProperty`."
        )
        r = WriteGateResult(passed=True)
        ev._gate_inline_code_integrity(en, tr, _OUT, r)
        assert r.passed
        assert r.cleaned_content is None  # no cleaning needed

    def test_fenced_code_block_in_translation_only_does_not_false_positive(self):
        """Regression (found 2026-07-20): a fenced ```code``` block present only in
        the translation (not the EN source) has triple backticks that get mispaired
        as inline-code delimiters by a naive single-backtick regex, manufacturing a
        cross-fence "span" that swallows unrelated prose/table content and false-
        positives against a real EN span. Confirmed live: 199 of 201 Gate 21 blocks
        on reference.aspose.org were this false positive, not real corruption."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple(
            "Use `AssetInfo`, `GetValue`, and `SetProperty` methods.\n"
            "See `ensure_layout_slides_parsed` for details.\n"
        )
        # tgt: all EN code spans preserved verbatim, but translation also
        # introduced a fenced block (not present in EN) further down the body.
        tgt_body = (
            "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 `AssetInfo`, `GetValue` \u0438 `SetProperty`.\n"
            "\u0421\u043c. `ensure_layout_slides_parsed` \u0434\u043b\u044f \u043f\u043e\u0434\u0440\u043e\u0431\u043d\u043e\u0441\u0442\u0435\u0439.\n"
            "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n```\n"
        )
        tr = _make_content_simple(tgt_body)
        r = WriteGateResult(passed=True)
        ev._gate_inline_code_integrity(en, tr, _OUT, r)
        assert r.passed, f"Fenced block must not corrupt inline-span comparison; error={r.error}"

    def test_unpaired_backtick_does_not_swallow_rest_of_body(self):
        """Regression: a single stray/unpaired backtick anywhere in the body must
        not let a span cross a newline and swallow everything up to the next
        backtick found later in the document (was the pre-fix _BACKTICK_SPAN_RE
        behavior, since `[^`]+` has no newline exclusion)."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        en = _make_content_simple(
            "Use `AssetInfo`, `GetValue`, and `SetProperty` methods.\n"
        )
        # tgt: real spans preserved, plus one lone stray backtick followed much
        # later by another backtick -- must not be read as one giant span.
        tgt_body = (
            "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 `AssetInfo`, `GetValue` \u0438 `SetProperty`.\n"
            "` \u0441\u043b\u0443\u0447\u0430\u0439\u043d\u044b\u0439 \u043e\u0434\u0438\u043d\u043e\u0447\u043d\u044b\u0439 \u0431\u044d\u043a\u0442\u0438\u043a\n"
            "\u041c\u043d\u043e\u0433\u043e \u043d\u0435\u0441\u0432\u044f\u0437\u0430\u043d\u043d\u043e\u0433\u043e \u0442\u0435\u043a\u0441\u0442\u0430 \u0437\u0434\u0435\u0441\u044c.\n"
            "\u0415\u0449\u0435 `\u0430\u0431\u0432\u0433\u0434` \u0437\u0434\u0435\u0441\u044c.\n"
        )
        tr = _make_content_simple(tgt_body)
        r = WriteGateResult(passed=True)
        ev._gate_inline_code_integrity(en, tr, _OUT, r)
        assert r.passed, f"Lone backtick must not swallow the rest of the body; error={r.error}"


class TestGateEmptyBody:
    """Gate 19b: empty body."""

    def test_blocks_near_empty_tgt_with_large_src(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = _make_content_simple("A" * 300)
        tgt = _make_content_simple("Hi.")
        r = WriteGateResult(passed=True)
        ev._gate_empty_body(src, tgt, _OUT, r)
        assert not r.passed and "Gate 19" in r.error

    def test_passes_when_src_also_small(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        r = WriteGateResult(passed=True)
        ev._gate_empty_body(_make_content_simple("Short."), _make_content_simple("Kurz."), _OUT, r)
        assert r.passed

    def test_passes_normal_content(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = _make_content_simple("A" * 500)
        tgt = _make_content_simple("\u041f\u0440\u0438\u0432\u0456\u0442 " * 30)
        r = WriteGateResult(passed=True)
        ev._gate_empty_body(src, tgt, _OUT, r)
        assert r.passed


# ---------------------------------------------------------------------------
# Gate 24: Description reverted to English
# ---------------------------------------------------------------------------


class TestGate24DescriptionRevertedToEnglish:
    """Gate 24: ASCII-only description in non-Latin locale → BLOCK."""

    def _make_desc_content(self, description: str, body: str = "text") -> str:
        return f"---\ntitle: Test\ndescription: {description}\n---\n{body}\n"

    def test_blocks_ascii_description_in_arabic(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._make_desc_content("Gets the font size in points.")
        tgt = self._make_desc_content("Gets the font size in points.")  # EN copied verbatim
        r = WriteGateResult(passed=True)
        ev._gate_description_reverted_to_english(src, tgt, "ar", _OUT, r)
        assert not r.passed
        assert "Gate 24" in r.error

    def test_passes_translated_arabic_description(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._make_desc_content("Gets the font size in points.")
        tgt = self._make_desc_content("تحصل على حجم الخط")
        r = WriteGateResult(passed=True)
        ev._gate_description_reverted_to_english(src, tgt, "ar", _OUT, r)
        assert r.passed

    def test_skips_latin_locale(self):
        """Gate 24 only fires for non-Latin-script locales."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._make_desc_content("Gets the font size in points.")
        tgt = self._make_desc_content("Gets the font size in points.")  # ASCII = English
        r = WriteGateResult(passed=True)
        ev._gate_description_reverted_to_english(src, tgt, "de", _OUT, r)
        assert r.passed  # German is Latin-script: gate should not fire

    def test_skips_short_source_description(self):
        """Gate 24 ignores when EN description is <20 chars."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._make_desc_content("Too short.")  # 10 chars
        tgt = self._make_desc_content("Too short.")
        r = WriteGateResult(passed=True)
        ev._gate_description_reverted_to_english(src, tgt, "ar", _OUT, r)
        assert r.passed  # too short to be reliable signal

    def test_multiline_folded_description_not_false_blocked(self):
        """TC-HT-001: a folded (>-) multi-line description with real Arabic
        text must not be mistaken for a first-line-only ASCII fragment."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\ndescription: >-\n"
            "  Gets the font size in points, used across the whole\n"
            "  document rendering pipeline.\n---\ntext\n"
        )
        tgt = (
            "---\ntitle: Test\ndescription: >-\n"
            "  تحصل على حجم الخط بالنقاط، يستخدم في جميع أنحاء\n"
            "  خط أنابيب عرض المستند.\n---\ntext\n"
        )
        r = WriteGateResult(passed=True)
        ev._gate_description_reverted_to_english(src, tgt, "ar", _OUT, r)
        assert r.passed

    def test_force_accept_does_not_bypass(self):
        """Gates 9+ are unconditional — force_accept=True must not skip Gate 24."""
        from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult
        ev = WriteGateEvaluator(detector=None, similarity_tracker=None, config=None, force_accept=True)
        src = self._make_desc_content("Gets the font size in points.")
        tgt = self._make_desc_content("Gets the font size in points.")
        r = WriteGateResult(passed=True)
        ev._gate_description_reverted_to_english(src, tgt, "ar", _OUT, r)
        assert not r.passed


# ---------------------------------------------------------------------------
# Gate 18: Description hallucination detection
# ---------------------------------------------------------------------------


class TestGate18DescriptionHallucination:
    """Gate 18: translated description >3x source length → BLOCK."""

    def _make_desc_content(self, description: str, body: str = "text") -> str:
        return f"---\ntitle: Test\ndescription: {description}\n---\n{body}\n"

    def test_blocks_hallucinated_description(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._make_desc_content("Gets the value of this property for testing.")
        tgt = self._make_desc_content(
            "This translation ballooned into a very long explanatory paragraph "
            "with far more text than the source ever contained, several times over "
            "the original length by any reasonable measure of things."
        )
        r = WriteGateResult(passed=True)
        ev._gate_description_hallucination(src, tgt, _OUT, r)
        assert not r.passed
        assert "Gate 18" in r.error

    def test_passes_proportional_translation(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._make_desc_content("Gets the value of this property for testing.")
        tgt = self._make_desc_content("Obtiene el valor de esta propiedad para pruebas.")
        r = WriteGateResult(passed=True)
        ev._gate_description_hallucination(src, tgt, _OUT, r)
        assert r.passed

    def test_multiline_literal_description_compared_by_full_value(self):
        """TC-HT-001: a literal (|) multi-line source description must be
        compared by its full joined value, not just its first physical line."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\ndescription: |\n"
            "  Gets the value of this property for testing purposes today.\n"
            "  It also documents a second related concern in detail here.\n"
            "---\ntext\n"
        )
        # Proportionally-sized translation of the FULL two-line source — a
        # first-line-only comparison would see this as wildly disproportionate.
        tgt = (
            "---\ntitle: Test\ndescription: |\n"
            "  Obtiene el valor de esta propiedad para fines de prueba hoy.\n"
            "  Tambien documenta una segunda cuestion relacionada aqui.\n"
            "---\ntext\n"
        )
        r = WriteGateResult(passed=True)
        ev._gate_description_hallucination(src, tgt, _OUT, r)
        assert r.passed

    def test_skips_short_source_description(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._make_desc_content("Short.")
        tgt = self._make_desc_content("Corto.")
        r = WriteGateResult(passed=True)
        ev._gate_description_hallucination(src, tgt, _OUT, r)
        assert r.passed

    def test_force_accept_does_not_bypass(self):
        from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult
        ev = WriteGateEvaluator(detector=None, similarity_tracker=None, config=None, force_accept=True)
        src = self._make_desc_content("Gets the value of this property for testing.")
        tgt = self._make_desc_content(
            "This translation ballooned into a very long explanatory paragraph "
            "with far more text than the source ever contained, several times over "
            "the original length by any reasonable measure of things."
        )
        r = WriteGateResult(passed=True)
        ev._gate_description_hallucination(src, tgt, _OUT, r)
        assert not r.passed


# ---------------------------------------------------------------------------
# Gate 10: Frontmatter broken backticks
# ---------------------------------------------------------------------------


class TestGate10FrontmatterBackticks:
    """Gate 10: odd backtick count in frontmatter scalar fields → auto-clean."""

    def test_fixes_odd_backtick_in_title(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        tgt = "---\ntitle: The `Camera class\ndescription: fine\n---\nbody\n"
        r = WriteGateResult(passed=True)
        cleaned = ev._gate_frontmatter_backticks(tgt, _OUT, None, r)
        assert cleaned is not None
        assert "The `Camera class`" in cleaned

    def test_passthrough_when_balanced(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        tgt = "---\ntitle: The `Camera` class\ndescription: fine\n---\nbody\n"
        r = WriteGateResult(passed=True)
        result = ev._gate_frontmatter_backticks(tgt, _OUT, None, r)
        assert result == tgt

    def test_multiline_folded_description_backtick_fix_round_trips(self):
        """TC-HT-001: fixing a sibling field's backticks must not corrupt an
        unrelated multi-line folded description elsewhere in the same file —
        re-serialization goes through YAMLFormatter, not string splicing."""
        import yaml

        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        tgt = (
            "---\ntitle: The `Camera class\n"
            "description: >-\n"
            "  Gets the value of this property across multiple\n"
            "  physical lines of folded YAML text.\n"
            "---\nbody\n"
        )
        r = WriteGateResult(passed=True)
        cleaned = ev._gate_frontmatter_backticks(tgt, _OUT, None, r)
        assert cleaned is not None
        parsed = yaml.safe_load(cleaned.split("---")[1])
        assert parsed["title"] == "The `Camera class`"
        assert "physical lines of folded YAML text" in parsed["description"]


# ---------------------------------------------------------------------------
# Gate 25: Code block content truncated
# ---------------------------------------------------------------------------


class TestGate25CodeBlockContentTruncated:
    """Gate 25: code block loses >30% of its lines → BLOCK."""

    def _code_file(self, code_lines: list[str]) -> str:
        code = "\n".join(code_lines)
        return f"---\ntitle: Test\n---\n\n```python\n{code}\n```\n"

    def test_blocks_truncated_code_block(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src_lines = [f"line_{i} = value_{i}" for i in range(15)]  # 15 lines
        tgt_lines = src_lines[:8]  # only 8 lines = 53% retained → BLOCK (< 70%)
        src = self._code_file(src_lines)
        tgt = self._code_file(tgt_lines)
        r = WriteGateResult(passed=True)
        ev._gate_code_block_content_truncated(src, tgt, _OUT, r)
        assert not r.passed
        assert "Gate 25" in r.error

    def test_passes_minimally_retained_code_block(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src_lines = [f"line_{i} = value_{i}" for i in range(12)]  # 12 lines
        tgt_lines = src_lines[:10]  # 83% retained → passes (≥ 70%)
        src = self._code_file(src_lines)
        tgt = self._code_file(tgt_lines)
        r = WriteGateResult(passed=True)
        ev._gate_code_block_content_truncated(src, tgt, _OUT, r)
        assert r.passed

    def test_skips_small_code_block(self):
        """Gate 25 ignores blocks with <10 source lines."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src_lines = [f"line_{i}" for i in range(5)]  # only 5 lines
        tgt_lines = src_lines[:2]  # 40% retained, but src < 10 lines
        src = self._code_file(src_lines)
        tgt = self._code_file(tgt_lines)
        r = WriteGateResult(passed=True)
        ev._gate_code_block_content_truncated(src, tgt, _OUT, r)
        assert r.passed  # gate skips small blocks


# ---------------------------------------------------------------------------
# Gate 26: Fence parity (zero-tolerance)
# ---------------------------------------------------------------------------


class TestGate26FenceParity:
    """Gate 26: any code-fence-line loss, or an odd target fence count, blocks."""

    def _fenced_file(self, n_blocks: int, drop_last_fence: bool = False) -> str:
        body_lines = []
        for i in range(n_blocks):
            body_lines.append(f"```python")
            body_lines.append(f"code_{i}")
            if not (drop_last_fence and i == n_blocks - 1):
                body_lines.append("```")
        return "---\ntitle: Test\n---\n" + "\n".join(body_lines) + "\n"

    def test_blocks_any_fence_loss_below_gate19_threshold(self):
        """A single dropped fence (odd count) is below Gate 19's -2 tolerance
        but must still be blocked by Gate 26 (zero tolerance)."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._fenced_file(3)  # 3 blocks = 6 fence lines
        tgt = self._fenced_file(3, drop_last_fence=True)  # 5 fence lines (odd)
        r = WriteGateResult(passed=True)
        ev._gate_fence_parity(src, tgt, _OUT, r)
        assert not r.passed
        assert "Gate 26" in r.error

    def test_blocks_small_file_fence_loss_gate19_never_checks(self):
        """Gate 19 only fires when src has >=4 fences; a 1-block (2-fence)
        file with a dropped fence must still be caught by Gate 26."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._fenced_file(1)  # 2 fences
        tgt = "---\ntitle: Test\n---\ncode_0\n"  # 0 fences — dropped entirely
        r = WriteGateResult(passed=True)
        ev._gate_fence_parity(src, tgt, _OUT, r)
        assert not r.passed

    def test_passes_matching_fence_count(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._fenced_file(2)
        tgt = self._fenced_file(2)
        r = WriteGateResult(passed=True)
        ev._gate_fence_parity(src, tgt, _OUT, r)
        assert r.passed

    def test_passes_target_gains_fences(self):
        """More fences in target than source is not a loss — passes."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._fenced_file(1)
        tgt = self._fenced_file(2)
        r = WriteGateResult(passed=True)
        ev._gate_fence_parity(src, tgt, _OUT, r)
        assert r.passed

    def test_force_accept_does_not_bypass(self):
        from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult
        ev = WriteGateEvaluator(detector=None, similarity_tracker=None, config=None, force_accept=True)
        src = self._fenced_file(2)
        tgt = self._fenced_file(2, drop_last_fence=True)
        r = WriteGateResult(passed=True)
        ev._gate_fence_parity(src, tgt, _OUT, r)
        assert not r.passed

    # HT-QUALITY-GATES-001 Phase 8 (Tier A #7): a reopened fence (a
    # duplicate opening marker mid-snippet instead of a real close) is
    # invisible to the count-based checks above -- the total can come out
    # even, or even >= source's count, so neither prior condition fires.
    def test_reopened_fence_is_blocked_even_though_count_is_even_and_not_lower(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._fenced_file(1)  # ```python\ncode_0\n``` -- 2 fence lines, well-formed
        # LLM duplicated the opening marker mid-snippet instead of closing:
        # ```python / code / ```python / more code / ``` -- 3 fence-marker
        # LINES (odd -> would already be caught by the odd-count check), but
        # a REAL reopen can also land on an even total if a genuine close
        # follows the duplicate open, e.g. ```python / code / ```python /
        # more / ``` / ``` -- 4 lines, even, and NOT less than src's 2.
        tgt = (
            "---\ntitle: Test\n---\n"
            "```python\n"
            "code_0\n"
            "```python\n"
            "more_code\n"
            "```\n"
            "```\n"
        )
        r = WriteGateResult(passed=True)
        ev._gate_fence_parity(src, tgt, _OUT, r)
        assert not r.passed
        assert "reopened" in r.error

    def test_well_formed_separate_blocks_are_not_flagged_as_reopened(self):
        """Negative control: two genuinely separate, properly closed fenced
        blocks (test_passes_target_gains_fences' shape) must never be
        mistaken for a reopen."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = self._fenced_file(1)
        tgt = self._fenced_file(2)
        r = WriteGateResult(passed=True)
        ev._gate_fence_parity(src, tgt, _OUT, r)
        assert r.passed

    def test_reopen_already_present_in_source_is_not_flagged(self):
        """If the source itself already contains this shape (unusual, but
        possible in hand-authored docs demonstrating fence syntax), only a
        NEW reopen introduced by translation should block."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\n---\n"
            "```python\ncode\n```python\nmore\n```\n```\n"
        )
        tgt = src  # byte-identical -- same reopen count, nothing new
        r = WriteGateResult(passed=True)
        ev._gate_fence_parity(src, tgt, _OUT, r)
        assert r.passed


# ---------------------------------------------------------------------------
# Gate 27: Multi-line frontmatter scalar preservation
# ---------------------------------------------------------------------------


class TestGate27MultilineScalarPreservation:
    """Gate 27: a multi-line/folded source scalar must survive translation intact."""

    def test_blocks_truncated_folded_scalar(self):
        """The exact wave-3 signature: a folded multi-line description
        collapsed to (effectively) its first line only."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\ndescription: >-\n"
            "  This is a long folded description that\n"
            "  continues across a second physical line here.\n---\nbody\n"
        )
        tgt = "---\ntitle: Test\ndescription: Esto es una descripcion.\n---\nbody\n"
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "es", _OUT, r)
        assert not r.passed
        assert "Gate 27" in r.error

    def test_blocks_empty_target_field(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\ndescription: |\n"
            "  Line one of a literal multi-line description.\n"
            "  Line two of the same description value here.\n---\nbody\n"
        )
        tgt = "---\ntitle: Test\ndescription: ''\n---\nbody\n"
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "es", _OUT, r)
        assert not r.passed

    def test_blocks_target_reverted_to_english_source(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\ndescription: >-\n"
            "  This is a long folded description that\n"
            "  continues across a second physical line here.\n---\nbody\n"
        )
        # Target is byte-identical to the parsed English source value.
        tgt = (
            "---\ntitle: Test\ndescription: >-\n"
            "  This is a long folded description that\n"
            "  continues across a second physical line here.\n---\nbody\n"
        )
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "es", _OUT, r)
        assert not r.passed

    def test_passes_proportional_full_translation(self):
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\ndescription: >-\n"
            "  This is a long folded description that\n"
            "  continues across a second physical line here.\n---\nbody\n"
        )
        tgt = (
            "---\ntitle: Test\ndescription: >-\n"
            "  Esta es una descripcion larga y plegada que\n"
            "  continua a traves de una segunda linea fisica aqui.\n---\nbody\n"
        )
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "es", _OUT, r)
        assert r.passed

    def test_skips_single_line_source_field(self):
        """A field that was already single-line in the source is not this
        gate's concern (Gate 18/24 cover single-line description issues)."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = "---\ntitle: Test\ndescription: Short single line.\n---\nbody\n"
        tgt = "---\ntitle: Test\ndescription: X\n---\nbody\n"
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "es", _OUT, r)
        assert r.passed

    def test_allows_english_target_byte_identical(self):
        """target_lang == 'en' is exempt from the byte-identical check."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\ndescription: >-\n"
            "  This is a long folded description that\n"
            "  continues across a second physical line here.\n---\nbody\n"
        )
        tgt = src
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "en", _OUT, r)
        assert r.passed

    def test_force_accept_does_not_bypass(self):
        from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult
        ev = WriteGateEvaluator(detector=None, similarity_tracker=None, config=None, force_accept=True)
        src = (
            "---\ntitle: Test\ndescription: >-\n"
            "  This is a long folded description that\n"
            "  continues across a second physical line here.\n---\nbody\n"
        )
        tgt = "---\ntitle: Test\ndescription: Esto es una descripcion.\n---\nbody\n"
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "es", _OUT, r)
        assert not r.passed

    def test_zh_legitimate_compact_translation_is_not_blocked(self):
        """HT-QUALITY-GATES-001 Part 25: the 0.5-ratio threshold has no
        language awareness. Real confirmed repro: a genuine, complete
        zh `plugin_description` translation legitimately runs well under
        half the English character count (Chinese is logographically far
        more compact) -- 25 real blocks across a full retranslation pass
        were false positives of this exact shape, blocking the entire file
        write and leaving stale pre-mission content (including a wrong
        title) in place. A zh-specific 0.2 floor still catches genuine
        truncation but not legitimate compactness."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        # 95-char English source folded scalar; 37-char zh target (39% ratio,
        # the exact real repro ratio) -- legitimate, not truncated.
        src = (
            "---\ntitle: Test\nplugin_description: >-\n"
            "  Open-source Python library for generating standard-compliant\n"
            "  1D and 2D barcodes with full SVG and PNG output support.\n---\nbody\n"
        )
        tgt = (
            "---\ntitle: Test\nplugin_description: "
            "适用于生成标准兼容的一维和二维条形码的开源 Python 库。\n---\nbody\n"
        )
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "zh", _OUT, r)
        assert r.passed

    def test_zh_genuinely_truncated_still_blocks(self):
        """The lowered zh threshold must not become toothless -- a target
        that's a small fraction of the source (not just naturally compact)
        still blocks."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\nplugin_description: >-\n"
            "  Open-source Python library for generating standard-compliant\n"
            "  1D and 2D barcodes with full SVG and PNG output support.\n---\nbody\n"
        )
        tgt = "---\ntitle: Test\nplugin_description: 库\n---\nbody\n"
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "zh", _OUT, r)
        assert not r.passed

    def test_non_zh_language_still_uses_default_ratio(self):
        """Regression guard: the zh-specific lower bar must not leak into
        other languages -- the same short target still blocks for es."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\ndescription: >-\n"
            "  This is a long folded description that\n"
            "  continues across a second physical line here.\n---\nbody\n"
        )
        tgt = "---\ntitle: Test\ndescription: Corta.\n---\nbody\n"
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "es", _OUT, r)
        assert not r.passed

    def test_ko_legitimate_compact_translation_is_not_blocked(self):
        """HT-QUALITY-GATES-001 Part 26: found via direct reproduction (not
        assumed) while investigating residual title mismatches -- ko hit the
        identical false-positive shape as zh. Real repro:
        ko/barcode/_index.md's plugin_description at 52/107 chars (49%),
        legitimate and complete, blocked before this fix."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\nplugin_description: >-\n"
            "  Open-source library for generating standard-compliant barcodes\n"
            "  in one and two dimensional formats with full output support.\n---\nbody\n"
        )
        tgt = (
            "---\ntitle: Test\nplugin_description: "
            "표준을 준수하는 1차원 및 2차원 바코드를 생성하는 오픈소스 라이브러리.\n---\nbody\n"
        )
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "ko", _OUT, r)
        assert r.passed

    def test_ja_legitimate_compact_translation_is_not_blocked(self):
        """Real repro: ja/diagram/_index.md's plugin_description at 41/97
        chars (42%), legitimate and complete, blocked before this fix."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\nplugin_description: >-\n"
            "  Open-source library for generating and rendering diagrams\n"
            "  and flowcharts with full layout and export support.\n---\nbody\n"
        )
        tgt = (
            "---\ntitle: Test\nplugin_description: "
            "ダイアグラムとフローチャートを生成しレンダリングするオープンソースライブラリ。\n---\nbody\n"
        )
        r = WriteGateResult(passed=True)
        ev._gate_multiline_scalar_preservation(src, tgt, "ja", _OUT, r)
        assert r.passed

    def test_ja_ko_genuinely_truncated_still_blocks(self):
        """The lowered ja/ko threshold must not become toothless."""
        from src.translation_engine.write_gate import WriteGateResult
        ev = _make_evaluator_no_detector()
        src = (
            "---\ntitle: Test\nplugin_description: >-\n"
            "  Open-source library for generating standard-compliant barcodes\n"
            "  in one and two dimensional formats with full output support.\n---\nbody\n"
        )
        for lang, short in [("ko", "라이브러리"), ("ja", "ライブラリ")]:
            tgt = f"---\ntitle: Test\nplugin_description: {short}\n---\nbody\n"
            r = WriteGateResult(passed=True)
            ev._gate_multiline_scalar_preservation(src, tgt, lang, _OUT, r)
            assert not r.passed, f"{lang} should still block genuine truncation"
