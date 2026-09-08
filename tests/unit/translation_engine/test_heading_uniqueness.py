"""Intra-document heading-translation uniqueness — detection and repair.

Regression fixture for the recurring defect confirmed on 2 source pages
(pdf-document-management-go: zh, ja; pdf-document-management-python: ja):
"Introduction" and "Getting Started" are extracted and translated as
independent units and both converge on the identical rendering.
"""

from types import SimpleNamespace

from src.translation_engine.heading_uniqueness import (
    find_duplicate_heading_translations,
)
from src.translation_engine.models import TranslationStats
from src.translation_engine.segment_translator import SegmentTranslator


def _heading_unit(source, translated, node_addr="body.0"):
    return SimpleNamespace(
        node_addr=node_addr,
        kind="heading_text",
        source_text=source,
        translated_text=translated,
        do_not_translate=False,
        metadata={},
    )


class TestFindDuplicateHeadingTranslations:
    def test_detects_two_different_headings_colliding(self):
        units = [
            _heading_unit("Introduction", "はじめに", "body.0"),
            _heading_unit("Getting Started", "はじめに", "body.1"),
        ]
        collisions = find_duplicate_heading_translations(units)
        assert len(collisions) == 1
        collision = collisions[0]
        assert collision.winner.source_text == "Introduction"
        assert [l.source_text for l in collision.losers] == ["Getting Started"]
        assert collision.shared_translation == "はじめに"

    def test_same_heading_repeated_is_not_a_collision(self):
        # The identical English heading appearing twice (e.g. two sibling
        # sections both literally named "Overview") legitimately shares one
        # translation -- not a defect.
        units = [
            _heading_unit("Overview", "Übersicht", "body.0"),
            _heading_unit("Overview", "Übersicht", "body.5"),
        ]
        assert find_duplicate_heading_translations(units) == []

    def test_distinct_translations_are_not_flagged(self):
        units = [
            _heading_unit("Introduction", "はじめに", "body.0"),
            _heading_unit("Getting Started", "使い方", "body.1"),
        ]
        assert find_duplicate_heading_translations(units) == []

    def test_non_heading_and_dnt_units_are_ignored(self):
        body_text_unit = SimpleNamespace(
            node_addr="body.0",
            kind="text",
            source_text="Introduction",
            translated_text="はじめに",
            do_not_translate=False,
            metadata={},
        )
        dnt_heading = _heading_unit("Getting Started", "はじめに", "body.1")
        dnt_heading.do_not_translate = True
        assert find_duplicate_heading_translations([body_text_unit, dnt_heading]) == []

    def test_three_way_collision_keeps_first_as_winner(self):
        units = [
            _heading_unit("Introduction", "はじめに", "body.0"),
            _heading_unit("Getting Started", "はじめに", "body.1"),
            _heading_unit("Quick Start", "はじめに", "body.2"),
        ]
        collisions = find_duplicate_heading_translations(units)
        assert len(collisions) == 1
        collision = collisions[0]
        assert collision.winner.source_text == "Introduction"
        assert {l.source_text for l in collision.losers} == {"Getting Started", "Quick Start"}


class _StubBackend:
    """Context-capable backend returning a canned repair."""

    def __init__(self, repaired_text):
        self.repaired_text = repaired_text
        self.calls = []

    def translate_with_context(self, texts, src, tgt, **kwargs):
        self.calls.append((list(texts), src, tgt, kwargs))
        return [self.repaired_text for _ in texts]


class TestRepairDuplicateHeadingTranslations:
    def _translator(self):
        engine = SimpleNamespace(model_loader=None, _model_lock=None)
        translator = SegmentTranslator.__new__(SegmentTranslator)
        translator._engine = engine
        return translator, engine

    def test_repair_replaces_losing_heading_translation(self):
        translator, engine = self._translator()
        units = [
            _heading_unit("Introduction", "はじめに", "body.0"),
            _heading_unit("Getting Started", "はじめに", "body.1"),
        ]
        backend = _StubBackend("使い方")
        repaired = translator._repair_duplicate_heading_translations(
            engine, units, backend, "en", "ja", TranslationStats()
        )
        assert repaired == 1
        assert units[1].translated_text == "使い方"
        assert units[1].metadata["heading_uniqueness_repair_sibling"] == "Introduction"
        _, _, _, kwargs = backend.calls[0]
        assert "Introduction" in kwargs["retry_feedback"]
        assert "はじめに" in kwargs["retry_feedback"]
        assert kwargs["context_hint"] == "heading_uniqueness"

    def test_repair_keeps_prior_when_retry_still_collides(self):
        translator, engine = self._translator()
        units = [
            _heading_unit("Introduction", "はじめに", "body.0"),
            _heading_unit("Getting Started", "はじめに", "body.1"),
        ]
        backend = _StubBackend("はじめに")  # retry still collides
        repaired = translator._repair_duplicate_heading_translations(
            engine, units, backend, "en", "ja", TranslationStats()
        )
        assert repaired == 0
        assert units[1].translated_text == "はじめに"

    def test_no_collisions_makes_no_backend_calls(self):
        translator, engine = self._translator()
        units = [_heading_unit("Introduction", "はじめに", "body.0")]
        backend = _StubBackend("unused")
        repaired = translator._repair_duplicate_heading_translations(
            engine, units, backend, "en", "ja", TranslationStats()
        )
        assert repaired == 0
        assert backend.calls == []
