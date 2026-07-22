"""Unit tests for WriteGateEvaluator (TC-TEST-01).

Tests gates 2-8 in isolation:
  Gate 2: Language detection mismatch (B-7.1)
  Gate 3: Overwrite protection (B-7.4)
  Gate 4: File purity (B-7.5)
  Gate 5: Soft contamination queue (TC-MLD-01)
  Gate 6: Code block count
  Gate 7: Heading surplus / TITLE hallucination
  Gate 8: YAML frontmatter structural (RC-5/RC-6)
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evaluator(detector=None, similarity_tracker=None, config=None, force_accept=False):
    if config is None:
        config = MagicMock()
        config.get_config.return_value = {"translation_engine": {}}
    return WriteGateEvaluator(
        detector=detector,
        similarity_tracker=similarity_tracker,
        config=config,
        force_accept=force_accept,
    )


def _make_detector(lang="de", confidence=0.95):
    """Return a mock detector that always returns (lang, confidence)."""
    d = MagicMock()
    d.detect.return_value = (lang, confidence)
    return d


def _md(body="Hallo Welt.", fm_keys=None):
    """Build minimal markdown with optional frontmatter keys."""
    if fm_keys is None:
        fm_keys = {"title": "Test"}
    fm = "\n".join(f"{k}: {v}" for k, v in fm_keys.items())
    return f"---\n{fm}\n---\n{body}"


# ---------------------------------------------------------------------------
# Gate 2: Language mismatch (B-7.1)
# ---------------------------------------------------------------------------


class TestGateLanguageMismatch:
    def test_pass_when_detected_matches_target(self):
        gate = _make_evaluator(detector=_make_detector("de", 0.95))
        r = gate.evaluate(_md(), "", "de", Path("test.md"))
        assert r.passed

    def test_fail_when_detected_differs_high_confidence(self):
        gate = _make_evaluator(detector=_make_detector("en", 0.90))
        r = gate.evaluate(_md(), "", "de", Path("test.md"))
        assert not r.passed
        assert "mismatch" in r.error.lower()

    def test_pass_when_confidence_below_threshold(self):
        gate = _make_evaluator(detector=_make_detector("en", 0.60))
        r = gate.evaluate(_md(), "", "de", Path("test.md"))
        assert r.passed

    def test_pass_when_force_accept(self):
        gate = _make_evaluator(detector=_make_detector("en", 0.95), force_accept=True)
        r = gate.evaluate(_md(), "", "de", Path("test.md"))
        assert r.passed

    def test_force_accept_bypasses_final_purity_for_governed_verifier(self):
        detector = _make_detector("en", 0.95)
        gate = _make_evaluator(detector=detector, force_accept=True)
        body = "This is a long English paragraph that would normally fail for a German target language."

        r = gate.evaluate(_md(body), _md("source"), "de", Path("test.md"))

        assert r.passed
        assert r._purity_result["reason"].startswith("Skipped by force_accept")

    def test_pass_when_similar_languages(self):
        tracker = MagicMock()
        tracker.are_similar.return_value = True
        gate = _make_evaluator(detector=_make_detector("bs", 0.90), similarity_tracker=tracker)
        r = gate.evaluate(_md(), "", "hr", Path("test.md"))
        assert r.passed


# ---------------------------------------------------------------------------
# Gate 3: Overwrite protection (B-7.4)
# ---------------------------------------------------------------------------


class TestGateOverwriteProtection:
    def test_pass_when_no_existing_file(self, tmp_path):
        gate = _make_evaluator(detector=_make_detector("de", 0.95))
        out = tmp_path / "new.md"
        r = gate.evaluate(_md(), "", "de", out)
        assert r.passed

    def test_block_case1_existing_correct_new_wrong(self, tmp_path):
        """CASE 1: existing is correct target lang, new is wrong."""
        out = tmp_path / "existing.md"
        out.write_text("existing content", encoding="utf-8")

        det = MagicMock()
        # First call: new content detection (gate 2: lang matches so passes)
        # But overwrite gate detects differently:
        # detect calls: gate2(new_content), gate3(new_content), gate3(existing)
        det.detect.side_effect = [
            ("de", 0.95),  # gate 2: new content → matches target, passes
            ("en", 0.90),  # gate 3: new content → wrong lang
            ("de", 0.92),  # gate 3: existing content → correct lang
        ]
        gate = _make_evaluator(detector=det)
        r = gate.evaluate(_md(), "", "de", out)
        assert not r.passed
        assert "overwrite" in r.error.lower() or "blocked" in r.error.lower()

    def test_case4_both_wrong_queues_retranslate(self, tmp_path):
        """CASE 4: both existing and new are wrong language → block + queue."""
        out = tmp_path / "existing.md"
        out.write_text("existing content", encoding="utf-8")

        det = MagicMock()
        det.detect.side_effect = [
            ("de", 0.95),  # gate 2: matches target
            ("fr", 0.90),  # gate 3: new content wrong
            ("es", 0.88),  # gate 3: existing content also wrong
        ]
        gate = _make_evaluator(detector=det)
        r = gate.evaluate(_md(), "", "de", out)
        assert not r.passed
        assert r.retranslate_queued
        assert len(r.retranslate_paths) == 1

    def test_case4_new_detected_as_similar_language_allows_healing_overwrite(self, tmp_path):
        """HT-QUALITY-GATES-001 Part 25: CASE 1 already checked are_similar()
        before treating a detected-language mismatch as real; CASE 4 never
        did, despite the same reasoning applying. Real confirmed repro:
        ms (Malay) retranslation output, genuinely correct, gets detected as
        `id` (Indonesian) -- an already-configured similarity pair
        (config/global.yaml's malay_indonesian group). Existing was stale
        (also detected wrong). Without the fix this blocks forever, leaving
        the old wrong content (and its wrong title) in place no matter how
        many times you retranslate."""
        out = tmp_path / "existing.md"
        out.write_text("existing content", encoding="utf-8")

        scripted = iter([
            ("ms", 0.95),  # gate 2: matches target, passes
            ("id", 0.90),  # gate 3: new content detected as Indonesian
            ("id", 0.88),  # gate 3: existing content also detected as Indonesian
        ])
        det = MagicMock()
        # Any calls beyond the scripted 3 (e.g. downstream purity gates, once
        # CASE 4 no longer blocks) fall back to a plain target-language match.
        det.detect.side_effect = lambda *a, **k: next(scripted, ("ms", 0.95))
        tracker = MagicMock()
        tracker.are_similar.side_effect = lambda a, b: {a, b} == {"ms", "id"}
        gate = _make_evaluator(detector=det, similarity_tracker=tracker)

        r = gate.evaluate(_md(), "", "ms", out)

        assert r.passed, "similarity-adjusted CASE 4 must allow the healing overwrite"
        assert not r.retranslate_queued

    def test_case4_unrelated_languages_still_blocks_even_with_tracker(self, tmp_path):
        """Regression guard: the similarity-tracker fix must not make CASE 4
        toothless -- genuinely unrelated languages still block."""
        out = tmp_path / "existing.md"
        out.write_text("existing content", encoding="utf-8")

        det = MagicMock()
        det.detect.side_effect = [
            ("de", 0.95),
            ("fr", 0.90),
            ("es", 0.88),
        ]
        tracker = MagicMock()
        tracker.are_similar.return_value = False
        gate = _make_evaluator(detector=det, similarity_tracker=tracker)

        r = gate.evaluate(_md(), "", "de", out)

        assert not r.passed
        assert r.retranslate_queued


# ---------------------------------------------------------------------------
# Gate 6: Code block count
# ---------------------------------------------------------------------------


class TestGateCodeBlock:
    def test_pass_when_counts_match(self):
        src = _md("```python\ncode\n```\n\ntext")
        tgt = _md("```python\ncode\n```\n\ntext translated")
        gate = _make_evaluator()  # no detector needed for structural gates
        r = gate.evaluate(tgt, src, "de", Path("test.md"))
        assert r.passed

    def test_fail_when_code_blocks_lost(self):
        src = _md("```python\ncode\n```\n\ntext")
        tgt = _md("text without code")
        gate = _make_evaluator()
        r = gate.evaluate(tgt, src, "de", Path("test.md"))
        assert not r.passed
        assert "code block" in r.error.lower()

    def test_pass_when_source_has_no_code_blocks(self):
        src = _md("just text")
        tgt = _md("just translated text")
        gate = _make_evaluator()
        r = gate.evaluate(tgt, src, "de", Path("test.md"))
        assert r.passed


# ---------------------------------------------------------------------------
# Gate 7: Heading surplus / TITLE hallucination
# ---------------------------------------------------------------------------


class TestGateHeadingSurplus:
    def test_fail_when_too_many_headings(self):
        src = _md("# One\ntext")
        tgt = _md("# One\n# Two\n# Three\n# Four\ntext")
        gate = _make_evaluator()
        r = gate.evaluate(tgt, src, "de", Path("test.md"))
        assert not r.passed
        assert "heading" in r.error.lower()

    def test_pass_when_heading_surplus_below_threshold(self):
        src = _md("# One\n# Two\ntext")
        tgt = _md("# One\n# Two\n# Three\ntext")
        gate = _make_evaluator()
        r = gate.evaluate(tgt, src, "de", Path("test.md"))
        assert r.passed

    def test_code_comments_inside_fence_not_counted_as_headings(self):
        """Regression (found 2026-07-20): '# comment' is Python's comment marker
        and C/C++'s preprocessor-directive marker, both common inside ```code```
        fences. The un-fence-aware count previously miscounted every such line as
        a heading, producing a false heading-surplus block on reference.aspose.org
        files whose only real change was a translated code example."""
        src = _md("## Real Heading\ntext\n```python\nx = 1\n```\n")
        tgt = _md(
            "## Real Heading\ntext\n"
            "```python\n"
            "# Create a new workbook\n"
            "# Set a cell value\n"
            "# Set a formula\n"
            "x = 1\n"
            "```\n"
        )
        gate = _make_evaluator()
        r = gate.evaluate(tgt, src, "de", Path("test.md"))
        assert r.passed, f"Code comments must not inflate heading count; error={r.error}"

    def test_fail_on_title_hallucination(self):
        src = _md("Normal content here")
        tgt = _md("TITLE: Some hallucinated title\nMore content")
        gate = _make_evaluator()
        r = gate.evaluate(tgt, src, "de", Path("test.md"))
        assert not r.passed
        assert "TITLE" in r.error


# ---------------------------------------------------------------------------
# Gate 8: YAML frontmatter structural (RC-5/RC-6)
# ---------------------------------------------------------------------------


class TestGateYamlFrontmatter:
    def test_pass_valid_frontmatter(self):
        src_doc = MagicMock()
        src_doc.frontmatter = {"title": "Test", "description": "Desc"}
        tgt = "---\ntitle: Test DE\ndescription: Desc DE\n---\nbody"
        gate = _make_evaluator()
        r = gate.evaluate(tgt, "", "de", Path("test.md"), source_doc=src_doc)
        assert r.passed

    def test_fail_missing_frontmatter_delimiters(self):
        src_doc = MagicMock()
        src_doc.frontmatter = {"title": "Test"}
        tgt = "no frontmatter here\njust body"
        gate = _make_evaluator()
        r = gate.evaluate(tgt, "", "de", Path("test.md"), source_doc=src_doc)
        assert not r.passed
        assert r.clear_tm_buffer
        assert "frontmatter" in r.error.lower()

    def test_fail_mismatched_keys(self):
        src_doc = MagicMock()
        src_doc.frontmatter = {"title": "Test", "description": "Desc"}
        tgt = "---\ntitle: Test DE\nextra_key: bad\n---\nbody"
        gate = _make_evaluator()
        r = gate.evaluate(tgt, "", "de", Path("test.md"), source_doc=src_doc)
        assert not r.passed
        assert r.quarantine_content is not None


# ---------------------------------------------------------------------------
# WriteGateResult dataclass
# ---------------------------------------------------------------------------


class TestWriteGateResult:
    def test_default_passed(self):
        r = WriteGateResult(passed=True)
        assert r.passed
        assert r.error is None
        assert not r.overwrite_blocked
        assert not r.contamination_queued
        assert r.retranslate_paths == []
        assert not r.clear_tm_buffer
