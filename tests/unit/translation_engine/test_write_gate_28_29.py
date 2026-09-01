"""
Integration tests for write gates 28-29 (HT-QUALITY-GATES-001 TC-QG-001/005).

Gates tested:
  Gate 28: _gate_title_identity   (blocking: title drift on family/platform index pages)
  Gate 29: _gate_refusal_artifact (blocking: leaked LLM refusal/meta-commentary text)

Gate 28 shipped "warn" first, then was promoted to "block" (Part 21) once the
canary confirmed 100% title match with the RC1-RC4 fixes live and the
dropped-placeholder fallback fixed the only other residual defect found —
see HT-QUALITY-GATES-001 plan Part 16/19/21. Gate 29 followed the same
warn-then-block path (Part 22 / plan 1.6): the clean-sample false-positive
check it was waiting on came from a follow-up investigation that found 6 new
real conversational-response leaks in production, 5 of which already matched
REFUSAL_RE and shipped anyway purely because the gate only logged — negligible
false-positive risk relative to continuing to ship confirmed-broken pages.
These tests pin real, confirmed defect shapes so a future change can't
silently regress detection:
  - Gate 28's case reproduces the real title-drift found in this session's
    audit and independently re-confirmed by direct file read during
    TC-QG-005's precheck: products.aspose.org hr/cells/net/_index.md has
    title "Aspose.Cells FOSS za .NET" vs the English source's
    "Aspose.Cells FOSS for .NET".
  - Gate 29's case uses "Please provide the English text you want
    translated." — one of the confirmed production instances documented in
    scripts/quality/audit_llm_artifacts.py's discovery history (2026-07-18),
    now shared via src/translation_engine/quality/refusal_patterns.py.

Also verifies the dispatch loop's short-circuit behavior now that BOTH gates
are "block": once an earlier block gate (28) has already set
result.passed = False, a later block gate (29) in registry order is skipped
entirely by _run_content_gates()'s `if not result.passed: continue` guard —
it does not independently re-confirm the rejection. This is the same
short-circuit every other pair of block gates already has; it's tested here
explicitly because Gate 29 used to be the one gate exempt from it (as a
"warn" gate) and that exemption is what changed.
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator


def _make_gate(force_accept: bool = True) -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    detector = MagicMock()
    detector.detect.return_value = ("hr", 0.99)
    return WriteGateEvaluator(
        detector=detector,
        similarity_tracker=MagicMock(),
        config=config,
        force_accept=force_accept,
    )


def _source_doc(title: str) -> MagicMock:
    doc = MagicMock()
    doc.frontmatter = {"title": title}
    return doc


# ---------------------------------------------------------------------------
# Gate 28: title identity on family/platform index pages
# ---------------------------------------------------------------------------


class TestGateTitleIdentity:
    def test_real_hr_cells_net_title_drift_is_flagged(self, caplog):
        """Pinned case: products.aspose.org hr/cells/net — 'for .NET' → 'za .NET'."""
        src = (
            "---\ntitle: Aspose.Cells FOSS for .NET\n---\n"
            "Aspose.Cells FOSS for .NET is a free, MIT-licensed library.\n"
        )
        tr = (
            "---\ntitle: Aspose.Cells FOSS za .NET\n---\n"
            "Aspose.Cells FOSS za .NET je besplatna, MIT licencirana biblioteka.\n"
        )
        gate = _make_gate()
        output_path = Path(
            "D:/onedrive/Documents/GitHub/aspose.org/content/products.aspose.org/hr/cells/net/_index.md"
        )

        with caplog.at_level(logging.ERROR):
            result = gate.evaluate(
                tr, src, "hr", output_path, source_doc=_source_doc("Aspose.Cells FOSS for .NET")
            )

        assert result.passed is False, "Gate 28 is blocking — must reject a title drift"
        assert result.retranslate_queued is True
        assert (output_path, "hr") in result.retranslate_paths
        assert any("GATE28 TITLE DRIFT" in r.message for r in caplog.records)

    def test_matching_title_is_silent(self, caplog):
        src = "---\ntitle: Aspose.Cells FOSS for .NET\n---\nbody\n"
        tr = "---\ntitle: Aspose.Cells FOSS for .NET\n---\ntijelo\n"
        gate = _make_gate()
        output_path = Path("/content/products.aspose.org/hr/cells/net/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "hr", output_path, source_doc=_source_doc("Aspose.Cells FOSS for .NET")
            )

        assert result.passed is True
        assert not any("GATE28" in r.message for r in caplog.records)

    def test_real_sr_psd_family_root_title_drift_is_flagged(self, caplog):
        """HT-QUALITY-GATES-001: family-ROOT pages (2-level, no platform
        segment) on products.aspose.org need the same check. Reproduces the
        audit's single most severe finding: sr/psd/_index.md's title
        corrupted to "Смрт" (Serbian for "Death"). Before the
        include_family_root fix, is_family_platform_index() returned False
        for this 2-level path shape and Gate 28 never even evaluated it."""
        src = "---\ntitle: Aspose.PSD FOSS\n---\nbody\n"
        tr = "---\ntitle: Смрт\n---\ntijelo\n"
        gate = _make_gate()
        output_path = Path("/content/products.aspose.org/sr/psd/_index.md")

        with caplog.at_level(logging.ERROR):
            result = gate.evaluate(
                tr, src, "sr", output_path, source_doc=_source_doc("Aspose.PSD FOSS")
            )

        assert result.passed is False, "Gate 28 is blocking — must reject a title drift"
        assert any("GATE28 TITLE DRIFT" in r.message for r in caplog.records)

    def test_real_kb_cells_family_root_title_drift_is_flagged(self, caplog):
        """HT-QUALITY-GATES-001 Part 22: kb.aspose.org confirmed (direct
        sampling of real content) to share the identical family-root
        title-drift defect — kb hr/cells/_index.md's title corrupted to
        "Sljedeći članakFOSS" ("Next article" + "FOSS", a leaked UI string)."""
        src = "---\ntitle: Aspose.Cells FOSS\n---\nbody\n"
        tr = "---\ntitle: Sljedeći članakFOSS\n---\ntijelo\n"
        gate = _make_gate()
        output_path = Path("/content/kb.aspose.org/hr/cells/_index.md")

        with caplog.at_level(logging.ERROR):
            result = gate.evaluate(
                tr, src, "hr", output_path, source_doc=_source_doc("Aspose.Cells FOSS")
            )

        assert result.passed is False, "Gate 28 must reject this real kb.aspose.org title drift"
        assert any("GATE28 TITLE DRIFT" in r.message for r in caplog.records)

    def test_real_docs_cells_family_root_title_drift_is_flagged(self, caplog):
        """HT-QUALITY-GATES-001 Part 22: docs.aspose.org confirmed the same
        way — fr/cells/_index.md's title corrupted to "[Résumé] FOSS"
        (a leaked UI/template string)."""
        src = "---\ntitle: Aspose.Cells FOSS\n---\nbody\n"
        tr = "---\ntitle: '[Résumé] FOSS'\n---\ncorps\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/fr/cells/_index.md")

        with caplog.at_level(logging.ERROR):
            result = gate.evaluate(
                tr, src, "fr", output_path, source_doc=_source_doc("Aspose.Cells FOSS")
            )

        assert result.passed is False, "Gate 28 must reject this real docs.aspose.org title drift"
        assert any("GATE28 TITLE DRIFT" in r.message for r in caplog.records)

    def test_family_root_on_unconfirmed_site_is_not_checked(self, caplog):
        """include_family_root is scoped to sites directly confirmed to need
        it (products.aspose.org, kb.aspose.org, docs.aspose.org — Part 22).
        blog.aspose.org has a structurally different layout
        (per_language_folders: false) never investigated for this
        requirement — a family-root page there must not be flagged."""
        src = "---\ntitle: Aspose.Slides FOSS\n---\nbody\n"
        tr = "---\ntitle: Something else entirely\n---\ntijelo\n"
        gate = _make_gate()
        output_path = Path("/content/blog.aspose.org/sr/slides/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "sr", output_path, source_doc=_source_doc("Aspose.Slides FOSS")
            )

        assert result.passed is True
        assert not any("GATE28" in r.message for r in caplog.records)

    def test_non_family_platform_path_is_not_checked(self, caplog):
        """A leaf content page (4+ path segments after locale) legitimately
        translates its title — Gate 28 must not fire there."""
        src = "---\ntitle: How to Read a Workbook\n---\nbody\n"
        tr = "---\ntitle: Kako čitati radnu knjigu\n---\ntijelo\n"
        gate = _make_gate()
        output_path = Path("/content/products.aspose.org/hr/cells/net/tutorials/read/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "hr", output_path, source_doc=_source_doc("How to Read a Workbook")
            )

        assert result.passed is True
        assert not any("GATE28" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Gate 29: refusal / meta-commentary artifact leak
# ---------------------------------------------------------------------------


class TestGateRefusalArtifact:
    def test_confirmed_refusal_phrase_in_title_is_flagged_by_gate28_gate29_short_circuited(
        self, caplog
    ):
        """Pinned case: a documented confirmed production instance (see
        audit_llm_artifacts.py discovery history) — a refusal reply shipped
        as the title field. A refusal phrase replacing the title is also,
        correctly, a title-identity violation, so Gate 28 (earlier in
        registry order) rejects the file first — the dispatch loop's block
        short-circuit then means Gate 29 never runs on this file at all.
        The file is still correctly rejected either way; this test pins
        that Gate 28 alone is sufficient here and Gate 29's own log line
        does NOT additionally appear."""
        src = "---\ntitle: Aspose.PDF FOSS for Go\n---\nbody\n"
        tr = "---\ntitle: Please provide the English text you want translated.\n---\ntijelo\n"
        gate = _make_gate()
        output_path = Path("/content/products.aspose.org/hr/pdf/go/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "hr", output_path, source_doc=_source_doc("Aspose.PDF FOSS for Go")
            )

        assert result.passed is False, "Gate 28 correctly rejects this title drift"
        assert any("GATE28 TITLE DRIFT" in r.message for r in caplog.records)
        assert not any("GATE29" in r.message for r in caplog.records), (
            "Gate 29 is short-circuited once Gate 28 already failed the file"
        )

    def test_confirmed_refusal_phrase_in_body_is_flagged(self, caplog):
        """Title stays byte-identical here (Gate 28 passes) so this test
        isolates Gate 29's own blocking behavior on a body-only leak."""
        src = "---\ntitle: Aspose.PDF FOSS for Go\n---\nAdd comments via `Annotation`.\n"
        tr = (
            "---\ntitle: Aspose.PDF FOSS for Go\n---\n"
            "Ich habe keine Ahnung, was das bedeutet.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/products.aspose.org/de/pdf/go/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "de", output_path, source_doc=_source_doc("Aspose.PDF FOSS for Go")
            )

        assert result.passed is False, "Gate 29 is blocking — must reject a refusal leak"
        assert result.retranslate_queued is True
        assert (output_path, "de") in result.retranslate_paths
        assert any("GATE29 REFUSAL ARTIFACT" in r.message for r in caplog.records)

    def test_conversational_shape_leak_not_in_curated_phrase_list_is_flagged(self, caplog):
        """Real confirmed miss: this exact sentence matched NO entry in
        REFUSAL_PHRASES and shipped untouched to
        docs.aspose.org/no/email/net/developer-guide/features.md. Pins the
        new CONVERSATIONAL_SHAPE_RE layer added alongside the warn->block
        promotion specifically to close this gap."""
        src = "---\ntitle: Aspose.PDF FOSS for Go\n---\nAdd comments via `Annotation`.\n"
        tr = (
            "---\ntitle: Aspose.PDF FOSS for Go\n---\n"
            "I'm sorry, but I can't access or read any attached files. If you paste "
            "the text you'd like translated directly into the chat, I'll be happy "
            "to translate it for you.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/no/email/net/developer-guide/features.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "no", output_path, source_doc=_source_doc("Aspose.PDF FOSS for Go")
            )

        assert result.passed is False
        assert result.retranslate_queued is True
        assert any("GATE29 REFUSAL ARTIFACT" in r.message for r in caplog.records)

    def test_clean_content_is_silent(self, caplog):
        # Title kept byte-identical (per Gate 28's now-blocking rule) so this
        # test isolates Gate 29's behavior specifically.
        src = "---\ntitle: Aspose.PDF FOSS for Go\n---\nAdd comments via `Annotation`.\n"
        tr = "---\ntitle: Aspose.PDF FOSS for Go\n---\nKommentare über `Annotation` hinzufügen.\n"
        gate = _make_gate()
        output_path = Path("/content/products.aspose.org/de/pdf/go/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "de", output_path, source_doc=_source_doc("Aspose.PDF FOSS for Go")
            )

        assert result.passed is True
        assert not any("GATE29" in r.message for r in caplog.records)

    def test_refusal_text_inside_code_fence_is_ignored(self, caplog):
        """A refusal phrase inside a code fence (e.g. as a literal string in
        an example) is not real leaked content — must not be flagged."""
        # Title kept byte-identical (per Gate 28's now-blocking rule) so this
        # test isolates Gate 29's code-fence-ignoring behavior specifically.
        src = "---\ntitle: Aspose.PDF FOSS for Go\n---\n```go\n// example\n```\n"
        tr = (
            "---\ntitle: Aspose.PDF FOSS for Go\n---\n"
            "```go\n// \"Please provide the text\" is a UI string constant\n```\n"
        )
        gate = _make_gate()
        output_path = Path("/content/products.aspose.org/de/pdf/go/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "de", output_path, source_doc=_source_doc("Aspose.PDF FOSS for Go")
            )

        assert result.passed is True
        assert not any("GATE29" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Dispatch-loop short-circuit: now that Gates 28 AND 29 are both "block",
# once an earlier block gate has already rejected the file, a later block
# gate in registry order is skipped entirely
# (`if not result.passed: continue` in _run_content_gates()'s dispatch loop).
# This used to NOT apply to Gate 29 back when it was "warn" (Part 21); that
# exemption is exactly what changed when it was promoted (Part 22).
# ---------------------------------------------------------------------------


class TestBlockGateShortCircuitsLaterBlockGate:
    def test_gate28_failure_short_circuits_gate29_even_when_body_also_leaks(self, caplog):
        """Gate 28 (earlier in registry order) rejects the title drift;
        Gate 29 — now also "block" — is skipped by the short-circuit and
        never independently evaluates, even though the body also contains a
        refusal-artifact leak that would trigger it on its own. The file is
        still correctly rejected (result.passed is False) via Gate 28 alone;
        this test pins that Gate 29's own log line does not additionally
        appear, documenting the new short-circuit behavior rather than
        silently regressing to "both always fire"."""
        src = "---\ntitle: Aspose.Cells FOSS for .NET\n---\nbody\n"
        tr = (
            "---\ntitle: Please provide the English text you want translated.\n---\n"
            "Ich habe keine Ahnung, was das bedeutet.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/products.aspose.org/hr/cells/net/_index.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "hr", output_path, source_doc=_source_doc("Aspose.Cells FOSS for .NET")
            )

        assert result.passed is False, "Gate 28 is blocking — must reject this title drift"
        messages = [r.message for r in caplog.records]
        assert any("GATE28" in m for m in messages)
        assert not any("GATE29" in m for m in messages), (
            "Gate 29 is short-circuited once an earlier block gate already failed"
        )
