"""
Unit tests for batched multiline translation in TranslationEngine.
"""

from dataclasses import dataclass

from src.translation_engine.engine import TranslationEngine
from src.translation_engine.handlers.multiline_handler import MultilineHandler
from src.translation_engine.models import TranslationStats


@dataclass
class MockSegment:
    id: str
    source_text: str


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def translate_with_token_counts(self, texts, source_lang, target_lang):
        self.calls.append(list(texts))
        translations = [text.upper() for text in texts]
        input_tokens = sum(len(t.split()) for t in texts)
        output_tokens = sum(len(t.split()) for t in translations)
        return translations, input_tokens, output_tokens


def test_multiline_batched_calls_and_structure_preserved():
    engine = TranslationEngine.__new__(TranslationEngine)
    engine.multiline_handler = MultilineHandler()
    engine.batch_size = 4
    engine.sort_segments_by_length = False

    backend = RecordingBackend()
    segments = [
        MockSegment("s1", "- first\n- second\n- third"),
        MockSegment("s2", "> quote one\n> quote two"),
    ]
    texts = [s.source_text for s in segments]
    stats = TranslationStats()

    results = engine._translate_with_multiline_support(
        backend=backend,
        segments=segments,
        texts=texts,
        source_lang="en",
        target_lang="fr",
        stats=stats,
    )

    assert any(len(call) > 1 for call in backend.calls)
    assert results[0] == "- FIRST\n- SECOND\n- THIRD"
    assert results[1] == "> QUOTE ONE\n> QUOTE TWO"
    assert results[0].count("\n") == 2
    assert results[1].count("\n") == 1
