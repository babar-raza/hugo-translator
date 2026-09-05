"""TC-APT-040 (Devanagari/CJK half): FIX-C must not double native terminals.

The reconstructor's punctuation-preserve repair appended the source's ASCII
terminal whenever the translation didn't literally end with it. A Hindi
sentence ending with the danda, a Japanese/Chinese sentence ending with the
ideographic full stop, or a Chinese label ending with the fullwidth colon all
"lack" the ASCII char by that test — producing the recurring danda+period,
fullwidth-stop+period, and fullwidth-colon+colon artifacts (11+ per page in
hi/ja/zh on introducing-pdf-foss-cpp, plus one earlier page).
"""

from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


def _render(source: str, translated: str) -> str:
    renderer = ASTRenderer.__new__(ASTRenderer)
    return renderer._preserve_punctuation(source, translated, "", "")


class TestNativeTerminalsAreNotDoubled:
    def test_devanagari_danda_satisfies_source_period(self):
        assert _render("This is a sentence.", "यह एक वाक्य है।") == "यह एक वाक्य है।"

    def test_ideographic_full_stop_satisfies_source_period(self):
        assert _render("This is a sentence.", "これは文です。") == "これは文です。"
        assert _render("This is a sentence.", "这是一个句子。") == "这是一个句子。"

    def test_fullwidth_colon_satisfies_source_colon(self):
        assert _render("Install the module:", "安装模块：") == "安装模块："

    def test_fullwidth_exclamation_and_question(self):
        assert _render("Really?", "本当に？") == "本当に？"
        assert _render("Go!", "行け！") == "行け！"

    def test_arabic_question_mark_satisfies_source_question(self):
        assert _render("Why?", "لماذا؟") == "لماذا؟"


class TestGenuineDropsAreStillRestored:
    def test_missing_ascii_period_is_still_appended(self):
        assert _render("This is a sentence.", "Dies ist ein Satz") == "Dies ist ein Satz."

    def test_missing_colon_is_still_appended(self):
        assert _render("Install the module:", "Installieren Sie das Modul") == (
            "Installieren Sie das Modul:"
        )

    def test_matching_ascii_terminal_is_untouched(self):
        assert _render("This is a sentence.", "Dies ist ein Satz.") == "Dies ist ein Satz."
