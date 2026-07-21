"""
HT-QUALITY-GATES-001 Part 20: fallback-to-professionalize_llm when the primary
MT model silently drops a protected span (confirmed real, not corrupting the
placeholder's shape -- restore()'s fuzzy pass already handles that -- but
dropping the token entirely and hallucinating unrelated fluent prose in its
place, with no trace to restore from).

Tests exercise SegmentTranslator._retry_dropped_placeholders_via_llm directly
-- the real method wired into the segment-translate loop in
translate_to_language(), not a reimplementation of its logic.
"""
from unittest.mock import MagicMock

from src.translation_engine.extractor.placeholder_manager import PlaceholderManager
from src.translation_engine.segment_translator import SegmentTranslator


def _make_segment(source_text: str, placeholder_map: dict[str, str]):
    seg = MagicMock()
    seg.source_text = source_text
    seg.placeholder_map = placeholder_map
    return seg


def _make_engine():
    engine = MagicMock()
    engine.placeholder_manager = PlaceholderManager()  # real instance, not a mock
    return engine


class TestDroppedPlaceholderFallback:
    def test_fallback_recovers_dropped_values(self):
        """The real confirmed scenario: primary model dropped 3/12 values;
        professionalize_llm (tested directly against the real endpoint this
        session) recovers all of them."""
        engine = _make_engine()
        fallback_backend = MagicMock()
        fallback_backend.translate.return_value = [
            "Napišite `string`, `int`, `bool`, `decimal` i `DateTime` "
            "vrijednosti s `Cell.PutValue(value)`."
        ]
        engine.model_loader.load_model.return_value = fallback_backend

        translator = SegmentTranslator(engine)
        placeholder_map = {
            "{PLACEHOLDER_0}": "`string`",
            "{PLACEHOLDER_1}": "`int`",
            "{PLACEHOLDER_2}": "`bool`",
            "{PLACEHOLDER_3}": "`decimal`",
            "{PLACEHOLDER_4}": "`DateTime`",
            "{PLACEHOLDER_5}": "`Cell.PutValue(value)`",
        }
        segment = _make_segment(
            "Write {PLACEHOLDER_0}, {PLACEHOLDER_1}, {PLACEHOLDER_2}, "
            "{PLACEHOLDER_3}, and {PLACEHOLDER_4} values with {PLACEHOLDER_5}.",
            placeholder_map,
        )
        lossy_translation = "Napišite vrijednosti s nečim čudnim."  # DateTime/Cell.PutValue dropped

        result = translator._retry_dropped_placeholders_via_llm(
            segment, lossy_translation, ["`DateTime`", "`Cell.PutValue(value)`"], "en", "hr"
        )

        engine.model_loader.load_model.assert_called_once_with("professionalize_llm")
        fallback_backend.translate.assert_called_once_with([segment.source_text], "en", "hr")
        assert "`DateTime`" in result
        assert "`Cell.PutValue(value)`" in result

    def test_fallback_also_incomplete_keeps_original(self):
        """If the LLM fallback is ALSO missing a value, don't silently ship
        its (different) lossy output -- keep the original MT translation,
        since neither is verified complete and swapping wouldn't fix anything."""
        engine = _make_engine()
        fallback_backend = MagicMock()
        fallback_backend.translate.return_value = ["Still missing DateTime here."]
        engine.model_loader.load_model.return_value = fallback_backend

        translator = SegmentTranslator(engine)
        placeholder_map = {"{PLACEHOLDER_0}": "`DateTime`"}
        segment = _make_segment("Uses {PLACEHOLDER_0} values.", placeholder_map)
        original = "Original lossy translation."

        result = translator._retry_dropped_placeholders_via_llm(
            segment, original, ["`DateTime`"], "en", "hr"
        )

        assert result == original

    def test_fallback_backend_unavailable_keeps_original(self):
        """If professionalize_llm can't be loaded (e.g. API down), degrade
        gracefully -- keep the original translation rather than raising and
        losing the whole file."""
        engine = _make_engine()
        engine.model_loader.load_model.side_effect = RuntimeError("API unreachable")

        translator = SegmentTranslator(engine)
        placeholder_map = {"{PLACEHOLDER_0}": "`DateTime`"}
        segment = _make_segment("Uses {PLACEHOLDER_0} values.", placeholder_map)
        original = "Original lossy translation."

        result = translator._retry_dropped_placeholders_via_llm(
            segment, original, ["`DateTime`"], "en", "hr"
        )

        assert result == original

    def test_translate_call_raises_keeps_original(self):
        """Network/timeout error during the fallback call itself must also
        degrade gracefully, not propagate and abort the whole file."""
        engine = _make_engine()
        fallback_backend = MagicMock()
        fallback_backend.translate.side_effect = TimeoutError("request timed out")
        engine.model_loader.load_model.return_value = fallback_backend

        translator = SegmentTranslator(engine)
        placeholder_map = {"{PLACEHOLDER_0}": "`DateTime`"}
        segment = _make_segment("Uses {PLACEHOLDER_0} values.", placeholder_map)
        original = "Original lossy translation."

        result = translator._retry_dropped_placeholders_via_llm(
            segment, original, ["`DateTime`"], "en", "hr"
        )

        assert result == original
