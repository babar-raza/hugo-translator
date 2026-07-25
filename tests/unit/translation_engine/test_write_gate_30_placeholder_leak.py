"""
Integration tests for write gate 30 (HT-QUALITY-GATES-001 Part 22 / plan 1.1
root cause B): universal placeholder-leak detection.

By the time content reaches write_gate.py, PlaceholderManager.restore() has
already run its full multi-pass repair strategy — every corrupted SHAPE it
knows how to recognize is already gone. A literal "PLACEHOLDER_N" token
(braced or bare) surviving to this point is not a shape restore() failed to
fix; it's direct evidence restore() never ran on this content at all. The
confirmed real-world cause: a content-refresh batch written by an entirely
separate process (a git commit co-authored by OpenAI Codex) directly into
the content repository, bypassing this pipeline's protect()/restore() cycle.

Gate 30 is deliberately process-agnostic — it blocks the shape regardless of
which writer produced it. It ships as "block" from the start (not
warn-then-promote like Gates 28/29) because there is no plausible legitimate
content explanation for this exact token shape ever appearing in real Aspose
documentation, unlike a curated phrase list that needs a false-positive
check first.
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator


def _make_gate(force_accept: bool = True) -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    detector = MagicMock()
    detector.detect.return_value = ("es", 0.99)
    return WriteGateEvaluator(
        detector=detector,
        similarity_tracker=MagicMock(),
        config=config,
        force_accept=force_accept,
    )


def _source_doc(title: str, **extra_frontmatter_keys) -> MagicMock:
    doc = MagicMock()
    doc.frontmatter = {"title": title, **extra_frontmatter_keys}
    return doc


class TestGatePlaceholderLeak:
    def test_braced_token_in_frontmatter_is_flagged(self, caplog):
        """Pinned shape: a literal, un-restored {PLACEHOLDER_0} token in a
        frontmatter description field — the exact signature traced to the
        Codex-authored batch on reference.aspose.org
        (ca/pdf/net/DefaultResourcesData.md and siblings)."""
        src = "---\ntitle: DefaultResourcesData\ndescription: Config class\n---\nbody\n"
        tr = (
            "---\ntitle: DefaultResourcesData\n"
            "description: Clase {PLACEHOLDER_0} con 3 propiedades\n---\ncuerpo\n"
        )
        gate = _make_gate()
        output_path = Path(
            "/content/reference.aspose.org/es/pdf/net/DefaultResourcesData.md"
        )

        with caplog.at_level(logging.ERROR):
            result = gate.evaluate(
                tr, src, "es", output_path,
                source_doc=_source_doc("DefaultResourcesData", description="Config class"),
            )

        assert result.passed is False
        assert result.retranslate_queued is True
        assert (output_path, "es") in result.retranslate_paths
        assert any("GATE30 PLACEHOLDER LEAK" in r.message for r in caplog.records)

    def test_bare_token_in_body_is_flagged(self, caplog):
        """Bare (brace-stripped) shape — confirmed real: NLLB dropped the
        braces entirely and glued a target-language case suffix directly
        onto the digit token."""
        src = "---\ntitle: Foo\n---\nSupports `.mtl` files.\n"
        tr = "---\ntitle: Foo\n---\nTukee PLACEHOLDER_0:n muotoa.\n"
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/fi/3d/java/Foo.md")

        with caplog.at_level(logging.ERROR):
            result = gate.evaluate(
                tr, src, "fi", output_path, source_doc=_source_doc("Foo")
            )

        assert result.passed is False
        assert any("GATE30 PLACEHOLDER LEAK" in r.message for r in caplog.records)

    def test_clean_content_is_silent(self, caplog):
        src = "---\ntitle: DefaultResourcesData\ndescription: Config class\n---\nbody\n"
        tr = (
            "---\ntitle: DefaultResourcesData\n"
            "description: Clase DefaultResourcesData con 3 propiedades\n---\ncuerpo\n"
        )
        gate = _make_gate()
        output_path = Path(
            "/content/reference.aspose.org/es/pdf/net/DefaultResourcesData.md"
        )

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "es", output_path,
                source_doc=_source_doc("DefaultResourcesData", description="Config class"),
            )

        assert result.passed is True
        assert not any("GATE30" in r.message for r in caplog.records)

    def test_placeholder_text_inside_code_fence_is_ignored(self, caplog):
        """A literal PLACEHOLDER_0-shaped string inside a fenced code example
        (e.g. documenting the token format itself) is not a real leak."""
        src = "---\ntitle: Foo\n---\n```text\n# example\n```\n"
        tr = (
            "---\ntitle: Foo\n---\n"
            "```text\n# internally this becomes PLACEHOLDER_0 before restore\n```\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/es/3d/java/Foo.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(
                tr, src, "es", output_path, source_doc=_source_doc("Foo")
            )

        assert result.passed is True
        assert not any("GATE30" in r.message for r in caplog.records)
