from types import SimpleNamespace

from src.translation_engine.handlers.multiline_handler import MultilineHandler
from src.translation_engine.segment_translator import SegmentTranslator
from src.translation_engine.models import TranslationStats


class FakeBackend:
    def translate(self, texts, source_lang, target_lang):
        return [f"[{target_lang}] {text}" for text in texts]


class ProductTitleEchoBackend:
    def translate(self, texts, source_lang, target_lang):
        out = []
        for text in texts:
            if text == "Aspose.Cells FOSS - Open Source C++ Spreadsheet Library":
                out.append(text)
            elif text == "Open Source C++ Spreadsheet Library":
                out.append("Biblioteca de planilhas C++ de codigo aberto")
            else:
                out.append(f"[{target_lang}] {text}")
        return out


def test_unchanged_product_identity_title_retries_translatable_suffix():
    engine = SimpleNamespace(
        batch_size=8,
        sort_segments_by_length=False,
        multiline_handler=MultilineHandler(),
    )
    translator = SegmentTranslator(engine)
    source = "Aspose.Cells FOSS - Open Source C++ Spreadsheet Library"
    segment = SimpleNamespace(source_text=source, id="seg1")

    result = translator._translate_with_multiline_support(
        ProductTitleEchoBackend(), [segment], [source], "en", "pt", TranslationStats()
    )

    assert result == ["Aspose.Cells FOSS - Biblioteca de planilhas C++ de codigo aberto"]


def test_fenced_code_prose_chunks_translate_prose_and_preserve_code():
    translator = SegmentTranslator(SimpleNamespace())
    source = (
        "Add the Maven dependency, then call `Scene.fromFile(\"model.obj\")`.\n\n"
        "```xml\n"
        "<dependency>\n"
        "  <groupId>com.aspose</groupId>\n"
        "</dependency>\n"
        "```\n\n"
        "Then save the scene.\n\n"
        "```java\n"
        "scene.save(\"model.gltf\");\n"
        "```\n"
    )

    result = translator._translate_fenced_code_prose_chunks(
        FakeBackend(), source, "en", "ar", TranslationStats()
    )

    assert '[ar] Add the Maven dependency' in result
    assert '[ar] Then save the scene.' in result
    assert "```xml\n<dependency>\n  <groupId>com.aspose</groupId>\n</dependency>\n```" in result
    assert '```java\nscene.save("model.gltf");\n```' in result


def test_multiline_unchanged_fenced_code_segment_retries_as_chunks():
    engine = SimpleNamespace(
        batch_size=8,
        sort_segments_by_length=False,
        multiline_handler=MultilineHandler(),
    )
    translator = SegmentTranslator(engine)
    source = (
        "Install the package.\n\n"
        "```java\n"
        "scene.save(\"model.gltf\");\n"
        "```\n"
    )
    segment = SimpleNamespace(source_text=source, id="seg1")

    result = translator._translate_with_multiline_support(
        FakeBackend(), [segment], [source], "en", "ca", TranslationStats()
    )

    assert len(result) == 1
    assert "[ca] Install the package." in result[0]
    assert '```java\nscene.save("model.gltf");\n```' in result[0]


def test_multiline_protected_fenced_code_placeholder_translates_surrounding_prose():
    engine = SimpleNamespace(
        batch_size=8,
        sort_segments_by_length=False,
        multiline_handler=MultilineHandler(),
    )
    translator = SegmentTranslator(engine)
    protected = 'Install the package.\n\n{PLACEHOLDER_0}\n\nThen save the scene.'
    segment = SimpleNamespace(
        source_text=protected,
        id="seg1",
        placeholder_map={"{PLACEHOLDER_0}": '```java\nscene.save("model.gltf");\n```'},
    )

    result = translator._translate_with_multiline_support(
        FakeBackend(), [segment], [protected], "en", "ar", TranslationStats()
    )

    assert len(result) == 1
    assert "[ar] Install the package." in result[0]
    assert "[ar] Then save the scene." in result[0]
    assert "{PLACEHOLDER_0}" in result[0]
    assert "scene.save" not in result[0]
