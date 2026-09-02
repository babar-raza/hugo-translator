"""TC-APT-011: preservation contracts -- RTL/bidi, HTML, images, and bijective masking.

Plan section 8 requires masking/restoration to be provably bijective "under duplicate tokens,
nesting, Unicode, and RTL text", and section 15 (G-12) records that the suite had NO dedicated
RTL/bidi test file and NO dedicated HTML- or image-preservation test. These are those files'
contents: they exercise ``PlaceholderManager`` (the component whose pattern list the
``protection_fingerprint`` hashes) directly, so a regression shows up without a model.
"""

from __future__ import annotations

import pytest

from src.translation_engine.extractor.placeholder_manager import PlaceholderManager

SHORTCODES = [r"\{\{<.*?>\}\}", r"\{\{%.*?%\}\}"]
HTML = [r"<[^>]+>"]
IMAGES = [r"!\[[^\]]*\]\([^)]*\)"]
CODE = [r"`[^`]*`", r"```[\s\S]*?```"]
ASPOSE = [r"\bAspose(?:\.[A-Za-z0-9][A-Za-z0-9.]*)?\b"]

# Real bidi text: Arabic/Hebrew/Persian with embedded LTR identifiers, plus explicit
# directional marks (RLM/LRM) that must survive byte-for-byte.
ARABIC = "استخدم فئة `Workbook` من Aspose.Cells لتحميل ملف XLSX‏."
HEBREW = "‏טען את הקובץ באמצעות Aspose.Words ואז שמור אותו כ-PDF."
PERSIAN = "کلاس `Document` را از Aspose.PDF بارگذاری کنید‎."


def roundtrip(text: str, patterns: list[str]) -> tuple[str, str, dict[str, str]]:
    """protect -> restore with the translation untouched; returns (protected, restored, map)."""
    manager = PlaceholderManager()
    protected, mapping = manager.protect(text, patterns)
    restored = manager.restore(protected, mapping)
    return protected, restored, mapping


@pytest.mark.parametrize("text", [ARABIC, HEBREW, PERSIAN])
def test_rtl_text_survives_masking_roundtrip_byte_for_byte(text):
    protected, restored, mapping = roundtrip(text, CODE + ASPOSE)
    assert restored == text  # bijective over RTL + embedded LTR identifiers
    assert mapping, "identifiers inside RTL text must actually be masked"
    for original in mapping.values():
        assert original not in protected  # the identifier really left the translatable text


def test_directional_marks_are_preserved_exactly():
    for text, mark in ((ARABIC, "‏"), (PERSIAN, "‎"), (HEBREW, "‏")):
        _, restored, _ = roundtrip(text, CODE + ASPOSE)
        assert restored.count(mark) == text.count(mark)


def test_rtl_placeholders_do_not_reorder_when_translation_reflows():
    """A translator may move placeholders; restoration must still map each token to its source."""
    manager = PlaceholderManager()
    protected, mapping = manager.protect(ARABIC, CODE + ASPOSE)
    tokens = list(mapping)
    assert len(tokens) >= 2
    reordered = (
        protected.replace(tokens[0], "\x01")
        .replace(tokens[1], tokens[0])
        .replace("\x01", tokens[1])
    )
    restored = manager.restore(reordered, mapping)
    assert mapping[tokens[0]] in restored and mapping[tokens[1]] in restored


def test_html_tags_and_attributes_are_preserved():
    text = '<div class="note" data-x="a..b">Text</div> and <br/> plus <a href="../x.md">link</a>'
    protected, restored, mapping = roundtrip(text, HTML)
    assert restored == text
    assert '<div class="note" data-x="a..b">' in mapping.values()
    assert "<" not in protected.replace("{PLACEHOLDER_", "")  # every tag was masked


def test_markdown_and_html_images_are_preserved():
    text = 'See ![Aspose diagram](../img/a.png "title") and <img src="../img/b.png" alt="x">.'
    _, restored, mapping = roundtrip(text, IMAGES + HTML)
    assert restored == text
    values = list(mapping.values())
    assert any(v.startswith("![Aspose diagram](") for v in values)
    assert any(v.startswith("<img ") for v in values)


def test_duplicate_tokens_are_masked_independently_and_restored():
    text = "Use `Workbook` then `Workbook` again, and `Workbook` a third time."
    protected, restored, mapping = roundtrip(text, CODE)
    assert restored == text
    assert len(mapping) == 3  # each occurrence gets its own token
    assert len(set(mapping)) == 3 and "`Workbook`" not in protected


def test_nested_constructs_are_masked_outermost_first():
    text = "{{< note >}}Use `Aspose.Cells` inside{{< /note >}}"
    _, restored, mapping = roundtrip(text, SHORTCODES + CODE + ASPOSE)
    assert restored == text
    assert any(v.startswith("{{<") for v in mapping.values())


def test_unicode_and_emoji_survive_masking():
    text = "日本語のテキスト `Workbook` と絵文字 🎉 と Ünïcödé — em-dash."
    _, restored, _ = roundtrip(text, CODE)
    assert restored == text


def test_restoration_is_idempotent_when_nothing_matches():
    text = "Plain prose with no protected spans at all."
    protected, restored, mapping = roundtrip(text, CODE + HTML + IMAGES)
    assert protected == text and restored == text and mapping == {}


def test_invalid_pattern_does_not_corrupt_text():
    """A malformed profile regex must be inert, never a partial mask (protection_fingerprint input)."""
    text = "Aspose.Cells reads `Workbook` files."
    _, restored, mapping = roundtrip(text, [r"([unclosed"] + CODE)
    assert restored == text and "`Workbook`" in mapping.values()


def test_placeholder_tokens_are_not_themselves_maskable():
    """A source that literally contains a placeholder-shaped string must round-trip unchanged."""
    text = "Literal {PLACEHOLDER_0} in the source plus `code`."
    _, restored, _ = roundtrip(text, CODE)
    assert restored == text
    assert "{PLACEHOLDER_0}" in restored
