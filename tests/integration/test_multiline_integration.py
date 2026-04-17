"""
Integration tests for multiline structure preservation in translation pipeline.

MSP-02: Tests that the MultilineHandler is properly integrated into the
TranslationEngine and preserves structure during translation.
"""

import sys
from unittest.mock import Mock

sys.path.insert(0, '.')

from src.translation_engine.handlers.multiline_handler import MultilineHandler
from src.translation_engine.models import TranslationStats


class MockBackend:
    """Mock translation backend for testing."""

    def __init__(self, translate_fn=None):
        """
        Initialize mock backend.

        Args:
            translate_fn: Optional custom translation function.
                         Default: uppercase transformation.
        """
        self.translate_fn = translate_fn or (lambda texts, src, tgt: [t.upper() for t in texts])
        self.call_count = 0
        self.calls = []

    def translate(self, texts, source_lang, target_lang):
        """Mock translate method."""
        self.call_count += 1
        self.calls.append(texts)
        return self.translate_fn(texts, source_lang, target_lang)

    def translate_with_token_counts(self, texts, source_lang, target_lang):
        """Mock translate with token counts."""
        self.call_count += 1
        self.calls.append(texts)
        result = self.translate_fn(texts, source_lang, target_lang)
        # Estimate tokens
        input_tokens = sum(len(t.split()) for t in texts)
        output_tokens = sum(len(t.split()) for t in result)
        return result, input_tokens, output_tokens


class MockSegment:
    """Mock segment for testing."""

    def __init__(self, id, source_text):
        self.id = id
        self.source_text = source_text
        self.context = None
        self.placeholder_map = {}


class TestMultilineIntegration:
    """Tests for multiline handler integration in translation engine."""

    def test_multiline_detection(self):
        """Verify multiline content is detected correctly."""
        handler = MultilineHandler()

        # Multiline content
        assert handler.is_multiline("line1\nline2") is True
        assert handler.is_multiline("line1\\nline2") is True

        # Single line content
        assert handler.is_multiline("single line") is False
        assert handler.is_multiline("") is False

    def test_engine_translate_with_multiline_support_method(self):
        """Test the _translate_with_multiline_support method directly."""
        from src.translation_engine.engine import TranslationEngine

        # Create mock dependencies
        mock_config = Mock()
        mock_tm = Mock()
        mock_model_loader = Mock()

        # Create engine (partially - just enough to test the method)
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.multiline_handler = MultilineHandler()
        engine.placeholder_manager = Mock()

        # Create mock backend
        backend = MockBackend()

        # Create segments - mix of single and multiline
        segments = [
            MockSegment("seg1", "single line text"),
            MockSegment("seg2", "line1\nline2\nline3"),
            MockSegment("seg3", "another single"),
            MockSegment("seg4", "- Bullet 1\n- Bullet 2"),
        ]

        texts = [s.source_text for s in segments]
        stats = TranslationStats()

        # Call the method
        results = engine._translate_with_multiline_support(
            backend=backend,
            segments=segments,
            texts=texts,
            source_lang="en",
            target_lang="bg",
            stats=stats,
        )

        # Verify results
        assert len(results) == 4

        # Single line texts should be uppercase (batch translated)
        assert results[0] == "SINGLE LINE TEXT"
        assert results[2] == "ANOTHER SINGLE"

        # Multiline texts should preserve structure
        assert results[1] == "LINE1\nLINE2\nLINE3"
        assert results[3] == "- BULLET 1\n- BULLET 2"

        # Verify newlines preserved
        assert results[1].count('\n') == 2
        assert results[3].count('\n') == 1

    def test_bullet_structure_preservation(self):
        """Test that bullet list structure is preserved."""
        from src.translation_engine.engine import TranslationEngine

        engine = TranslationEngine.__new__(TranslationEngine)
        engine.multiline_handler = MultilineHandler()
        engine.placeholder_manager = Mock()

        backend = MockBackend()

        # Aspose-style bullet content
        source = """-   Add the plugin to your project
-   Execute the conversion with:
    -   Input file
    -   Target format
    -   Output destination"""

        segments = [MockSegment("bullet_seg", source)]
        stats = TranslationStats()

        results = engine._translate_with_multiline_support(
            backend=backend,
            segments=segments,
            texts=[source],
            source_lang="en",
            target_lang="bg",
            stats=stats,
        )

        result = results[0]

        # Verify structure
        lines = result.split('\n')
        assert len(lines) == 5, f"Expected 5 lines, got {len(lines)}"

        # Verify indentation preserved
        assert lines[0].startswith("-   ")
        assert lines[2].startswith("    -   ")
        assert lines[3].startswith("    -   ")
        assert lines[4].startswith("    -   ")

    def test_empty_lines_preserved(self):
        """Test that empty lines are preserved in multiline content."""
        from src.translation_engine.engine import TranslationEngine

        engine = TranslationEngine.__new__(TranslationEngine)
        engine.multiline_handler = MultilineHandler()
        engine.placeholder_manager = Mock()

        backend = MockBackend()

        source = "Paragraph 1\n\nParagraph 2"

        segments = [MockSegment("para_seg", source)]
        stats = TranslationStats()

        results = engine._translate_with_multiline_support(
            backend=backend,
            segments=segments,
            texts=[source],
            source_lang="en",
            target_lang="bg",
            stats=stats,
        )

        result = results[0]

        # Verify empty line preserved
        assert "\n\n" in result
        lines = result.split('\n')
        assert len(lines) == 3
        assert lines[1] == ""  # Empty line

    def test_mixed_single_and_multiline(self):
        """Test processing of mixed single and multiline segments."""
        from src.translation_engine.engine import TranslationEngine

        engine = TranslationEngine.__new__(TranslationEngine)
        engine.multiline_handler = MultilineHandler()
        engine.placeholder_manager = Mock()

        backend = MockBackend()

        segments = [
            MockSegment("s1", "Title"),
            MockSegment("s2", "- Item 1\n- Item 2"),
            MockSegment("s3", "Description"),
            MockSegment("s4", "Para 1\n\nPara 2"),
            MockSegment("s5", "Footer"),
        ]

        stats = TranslationStats()

        results = engine._translate_with_multiline_support(
            backend=backend,
            segments=segments,
            texts=[s.source_text for s in segments],
            source_lang="en",
            target_lang="bg",
            stats=stats,
        )

        # All results should be present
        assert len(results) == 5

        # Single-line should be uppercase
        assert results[0] == "TITLE"
        assert results[2] == "DESCRIPTION"
        assert results[4] == "FOOTER"

        # Multiline should preserve structure
        assert results[1] == "- ITEM 1\n- ITEM 2"
        assert results[3] == "PARA 1\n\nPARA 2"


class TestMultilineHandlerDirectly:
    """Direct tests for MultilineHandler."""

    def test_key_metric_newline_preservation(self):
        """
        Key acceptance criterion: EN 5 newlines -> BG 5 newlines.

        This is the main metric from the bug report.
        """
        handler = MultilineHandler()

        # Source with 5 newlines (6 lines)
        source = "line1\nline2\nline3\nline4\nline5\nline6"

        def mock_translate(text):
            return text.upper()

        result = handler.translate(source, mock_translate)

        source_newlines = source.count('\n')
        result_newlines = result.translated_text.count('\n')

        assert source_newlines == 5
        assert result_newlines == 5
        assert result.structure_preserved is True
        assert result.line_count_source == 6
        assert result.line_count_translated == 6

    def test_real_world_aspose_content(self):
        """Test with actual Aspose content_left structure."""
        handler = MultilineHandler()

        source = """-   Add the Aspose.Slides plugin to your .NET project from NuGet.
-   Execute the conversion operation with parameters for:
    -   Input presentation file or stream
    -   Target format (PPTX, ODP, POTX, PPSX, etc.)
    -   Output destination (file or memory stream)"""

        def mock_translate(text):
            # Simulate Bulgarian translation (just prefix for test)
            return f"БГ: {text}"

        result = handler.translate(source, mock_translate)

        # Verify structure preserved
        assert result.structure_preserved is True
        assert result.line_count_source == 5
        assert result.line_count_translated == 5

        # Verify bullets and indentation
        lines = result.translated_text.split('\n')
        assert lines[0].startswith("-   БГ:")
        assert lines[2].startswith("    -   БГ:")


if __name__ == "__main__":
    # Run basic tests without pytest
    print("Running multiline integration tests...")

    tests = TestMultilineIntegration()
    tests.test_multiline_detection()
    print("PASS: test_multiline_detection")

    tests.test_engine_translate_with_multiline_support_method()
    print("PASS: test_engine_translate_with_multiline_support_method")

    tests.test_bullet_structure_preservation()
    print("PASS: test_bullet_structure_preservation")

    tests.test_empty_lines_preserved()
    print("PASS: test_empty_lines_preserved")

    tests.test_mixed_single_and_multiline()
    print("PASS: test_mixed_single_and_multiline")

    handler_tests = TestMultilineHandlerDirectly()
    handler_tests.test_key_metric_newline_preservation()
    print("PASS: test_key_metric_newline_preservation")

    handler_tests.test_real_world_aspose_content()
    print("PASS: test_real_world_aspose_content")

    print("\n=== ALL INTEGRATION TESTS PASSED ===")
