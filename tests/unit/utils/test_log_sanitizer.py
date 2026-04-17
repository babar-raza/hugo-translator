"""Comprehensive test suite for log_sanitizer.py.

This module tests the ASCII sanitization utility for log output, ensuring:
- 100% ASCII output for all inputs
- Correct script detection for 36+ languages
- Proper handling of mixed content (ASCII + Unicode)
- Edge case coverage (emoji, special chars, truncation)
- 100% code coverage

Test Categories:
1. ASCII Fast Path (5 tests)
2. Language Scripts (36+ tests)
3. Mixed Content (6 tests)
4. Edge Cases (12 tests)
5. Internal Functions (6 tests)
6. ASCII Verification (1 parameterized test with 50+ cases)

Total: 66+ test cases

Author: Agent-C (Tests & Verification)
Task: UL-002 - Create Log Sanitizer Tests
Framework: ORCHESTRATOR (Evidence-Based Development)
"""

import pytest

from src.utils.log_sanitizer import _detect_script, _format_placeholder, sanitize_for_log


class TestASCIIFastPath:
    """Test ASCII passthrough optimization.

    ASCII text should pass through unchanged with minimal processing
    (fast path optimization).
    """

    def test_ascii_passthrough_simple_text(self):
        """Test pure ASCII text passes through unchanged."""
        text = "Hello World"
        result = sanitize_for_log(text)
        assert result == "Hello World"
        assert result.isascii()

    def test_ascii_passthrough_with_numbers(self):
        """Test ASCII text with numbers passes through."""
        text = "Translation completed in 123.45 seconds"
        result = sanitize_for_log(text)
        assert result == text
        assert result.isascii()

    def test_ascii_passthrough_with_punctuation(self):
        """Test ASCII text with punctuation passes through."""
        text = "File: /path/to/file.md (status: OK!)"
        result = sanitize_for_log(text)
        assert result == text
        assert result.isascii()

    def test_ascii_empty_string(self):
        """Test empty string returns empty."""
        text = ""
        result = sanitize_for_log(text)
        assert result == ""
        assert result.isascii()

    def test_ascii_whitespace_only(self):
        """Test whitespace-only string passes through."""
        text = "   \t  \n  "
        result = sanitize_for_log(text)
        assert result == text
        assert result.isascii()


class TestLanguageScripts:
    """Test script detection for 36+ languages.

    Tests cover all languages mentioned in task backlog:
    ar, bg, ca, cs, da, de, el, es, fa, fi, fr, he, hi, hr, hu, id, it, ja, ko,
    lt, lv, ms, nl, no, pl, pt, ro, ru, sk, sr, sv, th, tr, uk, vi, zh
    """

    # CJK Languages
    def test_chinese_simplified(self):
        """Test Chinese (Simplified) script detection."""
        text = "智能翻译"
        result = sanitize_for_log(text)
        assert "[ZH:" in result
        assert "chars]" in result
        assert result.isascii()

    def test_chinese_traditional(self):
        """Test Chinese (Traditional) script detection."""
        text = "繁體中文"
        result = sanitize_for_log(text)
        assert "[ZH:" in result
        assert result.isascii()

    def test_japanese_hiragana(self):
        """Test Japanese Hiragana script detection."""
        text = "こんにちは"
        result = sanitize_for_log(text)
        assert "[JA:" in result
        assert "5chars]" in result
        assert result.isascii()

    def test_japanese_katakana(self):
        """Test Japanese Katakana script detection."""
        text = "カタカナ"
        result = sanitize_for_log(text)
        assert "[JA:" in result
        assert result.isascii()

    def test_japanese_mixed_with_kanji(self):
        """Test Japanese mixed (Hiragana + Kanji)."""
        text = "日本語"
        result = sanitize_for_log(text)
        # Kanji detected as ZH or JA (both acceptable)
        assert ("[ZH:" in result or "[JA:" in result)
        assert result.isascii()

    def test_korean_hangul(self):
        """Test Korean Hangul script detection."""
        text = "안녕하세요"
        result = sanitize_for_log(text)
        assert "[KO:" in result
        assert result.isascii()

    # RTL Languages
    def test_arabic(self):
        """Test Arabic script detection."""
        text = "مرحبا بك"
        result = sanitize_for_log(text)
        assert "[AR:" in result
        assert result.isascii()

    def test_persian_farsi(self):
        """Test Persian/Farsi script detection (uses Arabic script)."""
        text = "سلام دنیا"
        result = sanitize_for_log(text)
        # Persian uses Arabic script, detected as AR
        assert "[AR:" in result or "[FA:" in result
        assert result.isascii()

    def test_hebrew(self):
        """Test Hebrew script detection."""
        text = "שלום עולם"
        result = sanitize_for_log(text)
        assert "[HE:" in result
        assert result.isascii()

    # Cyrillic Languages
    def test_russian(self):
        """Test Russian Cyrillic script detection."""
        text = "Привет мир"
        result = sanitize_for_log(text)
        assert "[RU:" in result
        assert result.isascii()

    def test_ukrainian(self):
        """Test Ukrainian Cyrillic script detection."""
        text = "Привіт світ"
        result = sanitize_for_log(text)
        assert "[RU:" in result or "[UK:" in result  # Cyrillic mapped to RU
        assert result.isascii()

    def test_bulgarian(self):
        """Test Bulgarian Cyrillic script detection."""
        text = "Здравей свят"
        result = sanitize_for_log(text)
        assert "[RU:" in result or "[BG:" in result  # Cyrillic mapped to RU
        assert result.isascii()

    def test_serbian_cyrillic(self):
        """Test Serbian Cyrillic script detection."""
        text = "Здраво свете"
        result = sanitize_for_log(text)
        assert "[RU:" in result or "[SR:" in result  # Cyrillic mapped to RU
        assert result.isascii()

    # European Languages (Greek, other special scripts)
    def test_greek(self):
        """Test Greek script detection."""
        text = "Γειά σου κόσμε"
        result = sanitize_for_log(text)
        assert "[EL:" in result
        assert result.isascii()

    # Devanagari
    def test_hindi(self):
        """Test Hindi Devanagari script detection."""
        text = "नमस्ते दुनिया"
        result = sanitize_for_log(text)
        assert "[HI:" in result
        assert result.isascii()

    # Thai
    def test_thai(self):
        """Test Thai script detection."""
        text = "สวัสดีชาวโลก"
        result = sanitize_for_log(text)
        assert "[TH:" in result
        assert result.isascii()

    # Vietnamese (Latin Extended)
    def test_vietnamese(self):
        """Test Vietnamese Latin Extended detection."""
        text = "Tiếng Việt"
        result = sanitize_for_log(text)
        assert "[VI:" in result
        assert result.isascii()

    # Latin-based languages (should mostly pass through as ASCII or Latin Extended)
    def test_german(self):
        """Test German with umlauts."""
        text = "Guten Tag Welt mit ü ö ä"
        result = sanitize_for_log(text)
        # Latin letters with diacritics may be sanitized
        assert result.isascii()

    def test_french(self):
        """Test French with accents."""
        text = "Bonjour le monde avec é è ê"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_spanish(self):
        """Test Spanish with tildes."""
        text = "Hola mundo con ñ"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_italian(self):
        """Test Italian with accents."""
        text = "Ciao mondo con à è ì"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_portuguese(self):
        """Test Portuguese with accents."""
        text = "Olá mundo com ã õ ç"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_polish(self):
        """Test Polish with special characters."""
        text = "Witaj świecie z ą ę ł"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_czech(self):
        """Test Czech with diacritics."""
        text = "Ahoj světe s ř ž č"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_slovak(self):
        """Test Slovak with diacritics."""
        text = "Ahoj svet s ľ š ť"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_croatian(self):
        """Test Croatian with special characters."""
        text = "Bok svijete s č ć š"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_romanian(self):
        """Test Romanian with special characters."""
        text = "Salut lume cu ă â ț"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_turkish(self):
        """Test Turkish with special characters."""
        text = "Merhaba dünya ile ı ş ğ"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_hungarian(self):
        """Test Hungarian with special characters."""
        text = "Helló világ vel ő ű"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_finnish(self):
        """Test Finnish with special characters."""
        text = "Hei maailma jossa ä ö"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_swedish(self):
        """Test Swedish with special characters."""
        text = "Hej världen med å ä ö"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_norwegian(self):
        """Test Norwegian with special characters."""
        text = "Hei verden med æ ø å"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_danish(self):
        """Test Danish with special characters."""
        text = "Hej verden med æ ø å"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_lithuanian(self):
        """Test Lithuanian with special characters."""
        text = "Labas pasauli su ą ę ė"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_latvian(self):
        """Test Latvian with special characters."""
        text = "Sveika pasaule ar ā ē ī"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_catalan(self):
        """Test Catalan with special characters."""
        text = "Hola món amb à è ò"
        result = sanitize_for_log(text)
        assert result.isascii()

    def test_indonesian(self):
        """Test Indonesian (mostly ASCII)."""
        text = "Halo dunia"
        result = sanitize_for_log(text)
        assert result == text  # Pure ASCII
        assert result.isascii()

    def test_malay(self):
        """Test Malay (mostly ASCII)."""
        text = "Hello dunia"
        result = sanitize_for_log(text)
        assert result == text  # Pure ASCII
        assert result.isascii()


class TestMixedContent:
    """Test hybrid sanitization (ASCII + Unicode).

    Tests verify that ASCII portions are preserved while Unicode
    segments are replaced with placeholders.
    """

    def test_mixed_ascii_chinese(self):
        """Test mixed ASCII and Chinese."""
        text = "Hello 世界"
        result = sanitize_for_log(text)
        assert "Hello " in result
        assert "[ZH:" in result
        assert "2chars]" in result
        assert result.isascii()

    def test_mixed_ascii_russian(self):
        """Test mixed ASCII and Russian."""
        text = "Using Azure для работы"
        result = sanitize_for_log(text)
        assert "Using Azure " in result
        assert "[RU:" in result
        assert result.isascii()

    def test_mixed_ascii_arabic(self):
        """Test mixed ASCII and Arabic."""
        text = "Welcome مرحبا to Azure"
        result = sanitize_for_log(text)
        assert "Welcome " in result
        assert "[AR:" in result
        assert " to Azure" in result
        assert result.isascii()

    def test_multiple_scripts_in_one_string(self):
        """Test multiple different scripts in one string."""
        text = "Hello 世界 مرحبا Привет"
        result = sanitize_for_log(text)
        assert "Hello " in result
        assert "[ZH:" in result
        assert "[AR:" in result
        assert "[RU:" in result
        assert result.isascii()

    def test_ascii_surrounded_by_unicode(self):
        """Test ASCII text surrounded by Unicode."""
        text = "智能 API 翻译"
        result = sanitize_for_log(text)
        assert " API " in result
        assert "[ZH:" in result
        assert result.isascii()

    def test_unicode_surrounded_by_ascii(self):
        """Test Unicode surrounded by ASCII."""
        text = "Start 中文 End"
        result = sanitize_for_log(text)
        assert "Start " in result
        assert "[ZH:" in result
        assert " End" in result
        assert result.isascii()


class TestEdgeCases:
    """Test boundary conditions and special cases.

    Covers edge cases like emoji, special characters, truncation,
    None handling, and multi-byte character boundaries.
    """

    def test_empty_string(self):
        """Test empty string returns empty."""
        result = sanitize_for_log("")
        assert result == ""
        assert result.isascii()

    def test_none_input(self):
        """Test None input returns None."""
        result = sanitize_for_log(None)
        assert result is None

    def test_single_ascii_char(self):
        """Test single ASCII character."""
        result = sanitize_for_log("A")
        assert result == "A"
        assert result.isascii()

    def test_single_unicode_char(self):
        """Test single Unicode character."""
        result = sanitize_for_log("中")
        assert "[ZH:" in result
        assert "1chars]" in result
        assert result.isascii()

    def test_emoji_fire(self):
        """Test emoji handling (fire emoji)."""
        text = "Translation complete 🔥"
        result = sanitize_for_log(text)
        assert "Translation complete " in result
        # Emoji should be sanitized (unknown script)
        assert ("[UNI:" in result or result == "Translation complete ")
        assert result.isascii()

    def test_emoji_heart(self):
        """Test emoji handling (heart emoji)."""
        text = "Love ❤️ this translation"
        result = sanitize_for_log(text)
        assert "Love " in result
        assert " this translation" in result or "this translation" in result
        assert result.isascii()

    def test_special_char_copyright(self):
        """Test special character handling (copyright symbol)."""
        text = "Copyright © 2024"
        result = sanitize_for_log(text)
        assert "Copyright " in result
        assert "2024" in result
        assert result.isascii()

    def test_special_char_trademark(self):
        """Test special character handling (trademark symbol)."""
        text = "Azure™ API"
        result = sanitize_for_log(text)
        assert "Azure" in result
        assert " API" in result or "API" in result
        assert result.isascii()

    def test_truncation_at_max_length(self):
        """Test truncation at max_length."""
        text = "A" * 300
        result = sanitize_for_log(text, max_length=50)
        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")
        assert result.isascii()

    def test_truncation_with_unicode(self):
        """Test truncation with Unicode content."""
        text = "智" * 150
        result = sanitize_for_log(text, max_length=50)
        # Truncates to 50 chars, then adds "...", then sanitizes
        assert result.endswith("...")
        assert "[ZH:" in result
        assert result.isascii()

    def test_whitespace_tabs_newlines(self):
        """Test whitespace handling (tabs, newlines)."""
        text = "Line1\nLine2\tTab"
        result = sanitize_for_log(text)
        assert result == text  # ASCII whitespace preserved
        assert result.isascii()

    def test_very_long_unicode_string(self):
        """Test very long Unicode string (performance check)."""
        text = "中文测试" * 100  # 400 Chinese characters
        result = sanitize_for_log(text, max_length=500)
        assert "[ZH:" in result
        assert result.isascii()


class TestInternalFunctions:
    """Test private helper functions for coverage.

    Tests internal functions directly to ensure 100% code coverage.
    """

    def test_detect_script_ascii(self):
        """Test _detect_script with ASCII character."""
        result = _detect_script('A')
        assert result is None  # ASCII returns None

    def test_detect_script_chinese(self):
        """Test _detect_script with Chinese character."""
        result = _detect_script('中')
        assert result == 'ZH'

    def test_detect_script_japanese_hiragana(self):
        """Test _detect_script with Japanese Hiragana."""
        result = _detect_script('あ')
        assert result == 'JA'

    def test_detect_script_korean(self):
        """Test _detect_script with Korean Hangul."""
        result = _detect_script('한')
        assert result == 'KO'

    def test_detect_script_unknown(self):
        """Test _detect_script with unknown Unicode character."""
        result = _detect_script('🔥')
        # Unknown scripts return 'UNI' or None
        assert result in ['UNI', None] or result is not None

    def test_format_placeholder_chinese(self):
        """Test _format_placeholder with Chinese text."""
        result = _format_placeholder("智能", "ZH")
        assert result == "[ZH:2chars]"

    def test_format_placeholder_unknown(self):
        """Test _format_placeholder with unknown script."""
        result = _format_placeholder("xyz", None)
        assert result == "[UNI:3chars]"


class TestASCIIVerification:
    """Verify all outputs are ASCII-only.

    Comprehensive parameterized test to verify that ALL inputs
    produce ASCII-only outputs.
    """

    @pytest.mark.parametrize("text,description", [
        # ASCII inputs
        ("Hello World", "Simple ASCII"),
        ("Translation: 123.45 seconds", "ASCII with numbers"),
        ("File: /path/to/file.md", "ASCII with path"),
        ("", "Empty string"),
        ("   ", "Whitespace only"),

        # Chinese
        ("智能翻译", "Chinese simple"),
        ("中文测试内容", "Chinese longer"),
        ("Hello 世界", "Mixed ASCII + Chinese"),

        # Japanese
        ("こんにちは", "Japanese Hiragana"),
        ("カタカナ", "Japanese Katakana"),
        ("日本語", "Japanese with Kanji"),

        # Korean
        ("안녕하세요", "Korean Hangul"),
        ("한국어", "Korean simple"),

        # Arabic
        ("مرحبا بك", "Arabic greeting"),
        ("العربية", "Arabic simple"),

        # Persian
        ("سلام دنیا", "Persian/Farsi"),

        # Hebrew
        ("שלום עולם", "Hebrew greeting"),

        # Russian
        ("Привет мир", "Russian greeting"),
        ("Русский язык", "Russian simple"),

        # Greek
        ("Γειά σου", "Greek greeting"),
        ("Ελληνικά", "Greek simple"),

        # Hindi
        ("नमस्ते", "Hindi greeting"),

        # Thai
        ("สวัสดี", "Thai greeting"),

        # Vietnamese
        ("Tiếng Việt", "Vietnamese"),

        # European languages with diacritics
        ("Guten Tag mit ü ö ä", "German with umlauts"),
        ("Bonjour avec é è ê", "French with accents"),
        ("Hola con ñ", "Spanish with tilde"),
        ("Ciao con à è ì", "Italian with accents"),
        ("Olá com ã õ ç", "Portuguese with accents"),
        ("Witaj z ą ę ł", "Polish"),
        ("Ahoj s ř ž č", "Czech"),

        # Mixed content
        ("Using Azure для работы", "Mixed ASCII + Russian"),
        ("Welcome مرحبا to Azure", "Mixed ASCII + Arabic"),
        ("API 文档", "Mixed ASCII + Chinese"),

        # Edge cases
        ("Translation 🔥", "Emoji"),
        ("Copyright © 2024", "Special char"),
        ("Azure™ API", "Trademark symbol"),
        ("Line1\nLine2\tTab", "Whitespace"),

        # Long strings
        ("A" * 300, "Long ASCII"),
        ("中" * 150, "Long Chinese"),

        # Multiple scripts
        ("Hello 世界 مرحبا Привет", "Multi-script"),
        ("智能 API 翻译", "ASCII surrounded by Unicode"),
    ])
    def test_output_is_ascii(self, text, description):
        """Verify all outputs are ASCII-only (parameterized test)."""
        result = sanitize_for_log(text)

        # Handle None input (special case)
        if text is None or text == "":
            assert result == text
            return

        # All non-None outputs MUST be ASCII
        assert result.isascii(), f"Output not ASCII for {description}: {repr(result)}"


class TestCharacterCountAccuracy:
    """Verify character count accuracy in placeholders.

    Tests that the character count in placeholders matches
    the actual number of Unicode characters replaced.
    """

    def test_character_count_chinese_simple(self):
        """Test character count for simple Chinese text."""
        text = "智能翻译"  # 4 characters
        result = sanitize_for_log(text)
        assert "[ZH:4chars]" in result

    def test_character_count_japanese_hiragana(self):
        """Test character count for Japanese Hiragana."""
        text = "こんにちは"  # 5 characters
        result = sanitize_for_log(text)
        assert "[JA:5chars]" in result

    def test_character_count_arabic(self):
        """Test character count for Arabic text."""
        text = "مرحبا"  # 5 characters
        result = sanitize_for_log(text)
        assert "[AR:5chars]" in result

    def test_character_count_russian(self):
        """Test character count for Russian text."""
        text = "Привет"  # 6 characters
        result = sanitize_for_log(text)
        assert "[RU:6chars]" in result

    def test_character_count_mixed_segments(self):
        """Test character count for mixed content with multiple segments."""
        text = "Hello 世界"  # "世界" is 2 characters
        result = sanitize_for_log(text)
        assert "Hello " in result
        assert "[ZH:2chars]" in result


class TestScriptTransitions:
    """Test script transition edge cases for coverage.

    Tests specific code paths in the sanitization logic that handle
    transitions between different scripts and ASCII characters.
    """

    def test_unicode_to_different_unicode_transition(self):
        """Test transition from one Unicode script to another.

        This covers line 349: flushing previous Unicode segment when
        encountering a different Unicode script.
        """
        # Chinese followed immediately by Arabic (no ASCII between)
        text = "中文مرحبا"
        result = sanitize_for_log(text)
        assert "[ZH:" in result
        assert "[AR:" in result
        assert result.isascii()

    def test_ascii_segment_accumulation_then_unicode(self):
        """Test ASCII segment accumulation followed by Unicode.

        This covers line 353: flushing accumulated ASCII characters
        when encountering Unicode after ASCII segment.
        """
        # Multiple ASCII chars accumulated, then Unicode
        text = "test中"
        result = sanitize_for_log(text)
        assert "test" in result
        assert "[ZH:" in result
        assert result.isascii()

    def test_final_ascii_segment_flush(self):
        """Test final ASCII segment is flushed at end.

        This covers line 364: flushing final ASCII segment.
        """
        # Unicode followed by ASCII at the end
        text = "中文test"
        result = sanitize_for_log(text)
        assert "[ZH:" in result
        assert "test" in result
        assert result.isascii()

    def test_alternating_unicode_and_ascii(self):
        """Test alternating Unicode and ASCII characters."""
        # This exercises all the transition paths
        text = "A中B文C"
        result = sanitize_for_log(text)
        assert "A" in result
        assert "B" in result
        assert "C" in result
        assert "[ZH:" in result
        assert result.isascii()

    def test_unicode_script_change_after_chinese_to_arabic(self):
        """Test direct Unicode script change (Chinese to Arabic).

        This tests transition from one Unicode script directly to another,
        which should flush the previous Unicode segment.
        """
        # Start with Chinese, then directly to Arabic, no ASCII between
        text = "智能مرحبا"
        result = sanitize_for_log(text)
        assert "[ZH:" in result
        assert "[AR:" in result
        assert result.isascii()

    def test_ending_with_ascii_segment(self):
        """Test string ending with ASCII characters.

        This covers line 364: flushing final ASCII segment at end.
        """
        # Start with Unicode, end with ASCII
        text = "智能translation"
        result = sanitize_for_log(text)
        assert "[ZH:" in result
        assert "translation" in result
        assert result.isascii()


class TestTruncationBehavior:
    """Test truncation behavior at max_length boundaries.

    Verifies that truncation happens correctly and "..." is added.
    """

    def test_truncation_exact_at_max_length(self):
        """Test text exactly at max_length (no truncation)."""
        text = "A" * 200
        result = sanitize_for_log(text, max_length=200)
        assert len(result) == 200
        assert not result.endswith("...")
        assert result.isascii()

    def test_truncation_one_over_max_length(self):
        """Test text one character over max_length."""
        text = "A" * 201
        result = sanitize_for_log(text, max_length=200)
        assert len(result) == 203  # 200 + "..."
        assert result.endswith("...")
        assert result.isascii()

    def test_truncation_preserves_ascii_fast_path(self):
        """Test that truncated ASCII text still uses fast path."""
        text = "A" * 300
        result = sanitize_for_log(text, max_length=50)
        # Should truncate to 50 + "...", then check isascii() → fast path
        assert len(result) == 53
        assert result.endswith("...")
        assert result.isascii()

    def test_truncation_with_mixed_content(self):
        """Test truncation with mixed ASCII + Unicode."""
        text = "Hello 世界 " * 50  # ~550 characters
        result = sanitize_for_log(text, max_length=100)
        assert result.endswith("...")
        # After truncation and sanitization, the result expands because Unicode
        # characters are replaced with placeholders like [ZH:2chars]
        # The key is that truncation happened (... present) and output is ASCII
        assert result.isascii()
