"""
Integration tests for write gates 34-35 (HT-QUALITY-GATES-001 Part 22 /
plan 5.2 items 1-2): detection symmetry for the single most prevalent
defect found this session -- a systemically dropped trailing section
(confirmed across all 5 sites, almost always "See Also"/"Related
Resources"/an Enterprise-link block).

Both ship "warn" per this registry's established rollout convention.
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


class TestGateHeadingDeficit:
    def test_matching_heading_count_is_silent(self, caplog):
        src = "---\ntitle: Foo\n---\n## Overview\nbody\n## See Also\nlink\n"
        tr = "---\ntitle: Foo\n---\n## Übersicht\nkörper\n## Siehe auch\nlink\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/cells/net/foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE34" in r.message for r in caplog.records)

    def test_dropped_trailing_heading_is_flagged(self, caplog):
        """Pinned real shape: a translation that drops the final section
        entirely, confirmed across all 5 sites this session."""
        src = "---\ntitle: Foo\n---\n## Overview\nbody\n## See Also\nlink\n"
        tr = "---\ntitle: Foo\n---\n## Übersicht\nkörper\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/cells/net/foo.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(tr, src, "de", output_path)

        assert result.passed is True  # warn-only
        assert any("GATE34 HEADING DEFICIT" in r.message for r in caplog.records)

    def test_more_headings_in_translation_is_silent(self, caplog):
        """A surplus (already Gate 7's job) must not also trip the deficit
        gate -- these are complementary, not overlapping, checks."""
        src = "---\ntitle: Foo\n---\n## Overview\nbody\n"
        tr = "---\ntitle: Foo\n---\n## Übersicht\nkörper\n## Extra\nmehr\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/cells/net/foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE34" in r.message for r in caplog.records)

    def test_no_headings_in_source_is_silent(self, caplog):
        src = "---\ntitle: Foo\n---\nJust a plain paragraph, no headings.\n"
        tr = "---\ntitle: Foo\n---\nNur ein Absatz, keine Überschriften.\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/cells/net/foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE34" in r.message for r in caplog.records)


class TestGateDroppedTrailingLink:
    def test_surviving_url_is_silent(self, caplog):
        src = (
            "---\ntitle: Foo\n---\n## Overview\nbody\n"
            "## See Also\n- [Aspose.Cells — Enterprise Knowledge Base]"
            "(https://kb.aspose.com/cells/)\n"
        )
        tr = (
            "---\ntitle: Foo\n---\n## Übersicht\nkörper\n"
            "## Siehe auch\n- [Aspose.Cells — Wissensdatenbank]"
            "(https://kb.aspose.com/cells/)\n"
        )
        gate = _make_gate()
        output_path = Path("/content/kb.aspose.org/de/cells/foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE35" in r.message for r in caplog.records)

    def test_dropped_link_section_is_flagged(self, caplog):
        """Pinned real shape: the entire trailing See Also/Enterprise link
        section is missing -- the exact, most-prevalent defect found this
        session, now with a language-agnostic detection signal."""
        src = (
            "---\ntitle: Foo\n---\n## Overview\nbody\n"
            "## See Also\n- [Aspose.Cells — Enterprise Knowledge Base]"
            "(https://kb.aspose.com/cells/)\n"
        )
        tr = "---\ntitle: Foo\n---\n## Übersicht\nkörper\n"
        gate = _make_gate()
        output_path = Path("/content/kb.aspose.org/de/cells/foo.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(tr, src, "de", output_path)

        assert result.passed is True  # warn-only
        assert any("GATE35 DROPPED TRAILING LINK" in r.message for r in caplog.records)

    def test_last_section_without_links_is_out_of_scope(self, caplog):
        """The gate only fires when the LAST section is link-shaped -- a
        dropped final section with prose content (not this gate's
        detection signature) must not false-flag here; that's Gate 34's
        job via the count check."""
        src = "---\ntitle: Foo\n---\n## Overview\nbody\n## Notes\nSome closing prose, no links.\n"
        tr = "---\ntitle: Foo\n---\n## Übersicht\nkörper\n"
        gate = _make_gate()
        output_path = Path("/content/docs.aspose.org/de/cells/net/foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE35" in r.message for r in caplog.records)

    def test_url_moved_elsewhere_in_body_still_counts_as_present(self, caplog):
        """The check is deliberately whole-body, not position-scoped -- if
        the same URL legitimately appears anywhere in the translation
        (e.g. reflowed differently), that's good enough; this gate only
        cares whether the link survived, not exactly where."""
        src = (
            "---\ntitle: Foo\n---\n## Overview\nbody\n"
            "## See Also\n- [X](https://kb.aspose.com/cells/)\n"
        )
        tr = (
            "---\ntitle: Foo\n---\n"
            "## Übersicht\nSiehe [hier](https://kb.aspose.com/cells/) für mehr.\nkörper\n"
        )
        gate = _make_gate()
        output_path = Path("/content/kb.aspose.org/de/cells/foo.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "de", output_path)

        assert not any("GATE35" in r.message for r in caplog.records)
