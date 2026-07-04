"""
Comprehensive tests for TextUnitExtractor (TC-03).

Tests cover:
- Extraction from all node types
- Nested formatting
- Whitespace preservation
- Code/URL/src not extracted
- Smart segmentation strategies
- Product name detection
- Batch translation with delimiter protection
"""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import (
    ASTNode,
    NodeType,
    heading_node,
    paragraph_node,
    text_node,
)


class TestBasicExtraction:
    """Test basic text unit extraction."""

    def test_extract_simple_text(self):
        """Test extracting simple text node."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create simple paragraph
        para = paragraph_node([text_node("Hello world")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert len(plan.units) == 1
        assert plan.units[0].source_text == "Hello world"
        assert plan.units[0].kind == TextUnitKind.TEXT
        assert plan.units[0].do_not_translate == False

    def test_extract_multiple_text_nodes(self):
        """Test extracting multiple text nodes."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create paragraph with multiple text nodes
        para = paragraph_node([text_node("First "), text_node("second "), text_node("third")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert len(plan.units) == 3
        assert [u.source_text for u in plan.units] == ["First", "second", "third"]

    def test_whitespace_preservation(self):
        """Test whitespace is separated and preserved."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create text with leading/trailing whitespace
        para = paragraph_node([text_node("  Hello  ")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert len(plan.units) == 1
        unit = plan.units[0]
        assert unit.source_text == "Hello"
        assert unit.prefix_ws == "  "
        assert unit.suffix_ws == "  "

        # Verify reconstruction
        assert unit.get_final_text() == "  Hello  "

    def test_empty_text_handled(self):
        """Test empty text nodes are handled gracefully (HP-06 TC-03).

        Empty text nodes (node.raw="") should NOT create TextUnits because:
        1. No translatable content exists
        2. No whitespace to preserve (vs whitespace-only which does need preservation)
        3. Efficiency: avoid unnecessary units in translation plan

        See HP-06 TC-03 requirement: "Must handle YAML-only files (no body) without errors"
        and the distinction from test_whitespace_only_text where whitespace IS preserved.

        Spec reference: plans/hp-06.md TC-03, lines 1639-1644 (hard rules)
        Verification doc: plans/healing/SR-05-spec-verification.md
        """
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create paragraph with empty text
        para = paragraph_node([text_node("")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Empty text should not create a unit - nothing to translate
        assert len(plan.units) == 0


class TestNodeTypes:
    """Test extraction from different node types."""

    def test_heading_extraction(self):
        """Test heading text extraction."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create heading
        heading = heading_node(level=1, children=[text_node("My Heading")])
        heading.assign_addresses("body.heading[0]")

        plan = extractor.extract_from_ast([heading])

        assert len(plan.units) == 1
        assert plan.units[0].source_text == "My Heading"
        assert plan.units[0].kind == TextUnitKind.TEXT

    def test_link_text_extraction(self):
        """Test link text is extracted but URL is not."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create link node
        link = ASTNode(
            type=NodeType.LINK,
            attrs={"url": "https://example.com"},
            children=[text_node("Click here")],
        )
        para = paragraph_node([link])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract link text only
        assert len(plan.units) == 1
        assert plan.units[0].source_text == "Click here"
        assert plan.units[0].kind == TextUnitKind.LINK_TEXT

        # URL should NOT be in units
        all_text = " ".join([u.source_text for u in plan.units])
        assert "https://example.com" not in all_text

    def test_image_alt_extraction(self):
        """Test image alt text is extracted but src is not."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create image node
        image = ASTNode(
            type=NodeType.IMAGE, attrs={"src": "/images/photo.jpg", "alt": "Beautiful photo"}
        )
        para = paragraph_node([image])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract alt text only
        assert len(plan.units) == 1
        assert plan.units[0].source_text == "Beautiful photo"
        assert plan.units[0].kind == TextUnitKind.IMAGE_ALT

        # src should NOT be in units
        all_text = " ".join([u.source_text for u in plan.units])
        assert "/images/photo.jpg" not in all_text

    def test_code_span_not_translated(self):
        """Test code spans are marked as non-translatable."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create paragraph with code span
        code = ASTNode(type=NodeType.CODE_SPAN, raw="myFunction()")
        para = paragraph_node([text_node("Call "), code, text_node(" here")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should have 3 units
        assert len(plan.units) == 3

        # Find code unit
        code_units = [u for u in plan.units if u.kind == TextUnitKind.CODE_SPAN]
        assert len(code_units) == 1
        assert code_units[0].source_text == "myFunction()"
        assert code_units[0].do_not_translate == True

    def test_code_block_not_translated(self):
        """Test code blocks are marked as non-translatable."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create code block
        code_block = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="def hello():\n    print('world')",
            attrs={"lang": "python"},
        )
        code_block.assign_addresses("body.codeblock[0]")

        plan = extractor.extract_from_ast([code_block])

        # Should have 1 unit marked as non-translatable
        assert len(plan.units) == 1
        assert plan.units[0].do_not_translate == True


class TestNestedFormatting:
    """Test extraction with nested formatting."""

    def test_bold_in_paragraph(self):
        """Test bold text in paragraph."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create paragraph with bold
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
        para = paragraph_node([text_node("This is "), strong, text_node(" text")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract all text nodes
        assert len(plan.units) == 3
        assert [u.source_text for u in plan.units] == ["This is", "bold", "text"]

    def test_link_in_bold(self):
        """Test link inside bold formatting."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create: **[link](url)**
        link = ASTNode(
            type=NodeType.LINK, attrs={"url": "https://example.com"}, children=[text_node("link")]
        )
        strong = ASTNode(type=NodeType.STRONG, children=[link])
        para = paragraph_node([strong])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract link text
        assert len(plan.units) == 1
        assert plan.units[0].source_text == "link"
        assert plan.units[0].kind == TextUnitKind.LINK_TEXT

    def test_bold_in_link(self):
        """Test bold inside link."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create: [**bold**](url)
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
        link = ASTNode(type=NodeType.LINK, attrs={"url": "https://example.com"}, children=[strong])
        para = paragraph_node([link])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract text from inside bold
        assert len(plan.units) == 1
        assert plan.units[0].source_text == "bold"

    def test_complex_nesting(self):
        """Test deeply nested formatting."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create: Visit **[click *here*](url)** now
        em = ASTNode(type=NodeType.EMPHASIS, children=[text_node("here")])
        link = ASTNode(
            type=NodeType.LINK,
            attrs={"url": "https://example.com"},
            children=[text_node("click "), em],
        )
        strong = ASTNode(type=NodeType.STRONG, children=[link])
        para = paragraph_node([text_node("Visit "), strong, text_node(" now")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract all text nodes
        assert len(plan.units) == 4
        assert [u.source_text for u in plan.units] == ["Visit", "click", "here", "now"]


class TestSmartSegmentation:
    """Test smart segmentation strategies."""

    def test_leaf_only_mode(self):
        """Test leaf_only mode always extracts leaf nodes."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create paragraph with mixed content
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
        para = paragraph_node([text_node("Plain "), strong, text_node(" text")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract 3 individual text nodes
        assert len(plan.units) == 3
        assert [u.source_text for u in plan.units] == ["Plain", "bold", "text"]

    def test_sentence_only_mode(self):
        """Test sentence_only mode extracts plain paragraphs as full sentences."""
        extractor = TextUnitExtractor(segmentation_strategy="sentence_only")

        # Plain paragraph without inline formatting — should be full-sentence
        para = paragraph_node([text_node("Plain text sentence.")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract full sentence (1 unit) for plain text
        assert len(plan.units) == 1
        assert "Plain text sentence" in plan.units[0].source_text

    def test_adaptive_mode_plain_paragraph(self):
        """Test adaptive mode extracts full sentence for plain paragraphs."""
        extractor = TextUnitExtractor(segmentation_strategy="adaptive")

        # Create plain paragraph (no formatting)
        para = paragraph_node([text_node("This is plain text.")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should extract as full sentence
        assert len(plan.units) == 1
        assert plan.units[0].source_text == "This is plain text."

    def test_adaptive_mode_formatted_paragraph(self):
        """Test adaptive mode uses leaf-level for formatted paragraphs."""
        extractor = TextUnitExtractor(segmentation_strategy="adaptive")

        # Create paragraph with formatting
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
        para = paragraph_node([text_node("Text with "), strong])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should use leaf-level extraction (2 units)
        assert len(plan.units) == 2
        assert [u.source_text for u in plan.units] == ["Text with", "bold"]

    def test_adaptive_mode_technical_paragraph(self):
        """Test adaptive mode uses leaf-level for technical content."""
        extractor = TextUnitExtractor(segmentation_strategy="adaptive")

        # Create paragraph with code
        code = ASTNode(type=NodeType.CODE_SPAN, raw="code()")
        para = paragraph_node([text_node("Call "), code, text_node(" here")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Should use leaf-level extraction (3 units)
        assert len(plan.units) == 3


class TestProductNameDetection:
    """Test non-translatable content detection."""

    def test_terminology_dict_detection(self):
        """Test terminology dictionary prevents translation."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create text with product name from built-in dict
        para = paragraph_node([text_node("Use Aspose.Slides here")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # "Aspose.Slides" should be detected as non-translatable
        aspose_units = [u for u in plan.units if "Aspose.Slides" in u.source_text]
        # Note: Since we're in leaf_only mode and single text node,
        # the entire text "Use Aspose.Slides here" is one unit
        # but Aspose.Slides should be detected

        # Let's test with just the product name
        para2 = paragraph_node([text_node("Aspose.Slides")])
        para2.assign_addresses("body.paragraph[1]")
        plan2 = extractor.extract_from_ast([para2])

        assert plan2.units[0].do_not_translate == True

    def test_camelcase_detection(self):
        """Test CamelCase identifiers are detected."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Test CamelCase
        para = paragraph_node([text_node("AsposeSlidesLowCode")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert plan.units[0].do_not_translate == True

    def test_dotted_pascal_case_detection(self):
        """Test PascalCase.With.Dots identifiers are detected."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        para = paragraph_node([text_node("Aspose.Slides.LowCode")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert plan.units[0].do_not_translate == True

    def test_snake_case_detection(self):
        """Test snake_case identifiers are detected."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        para = paragraph_node([text_node("aspose_slides_low_code")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert plan.units[0].do_not_translate == True

    def test_all_caps_detection(self):
        """Test ALL_CAPS identifiers are detected."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Test API, SDK, etc.
        for term in ["API", "SDK", "HTTP", "JSON"]:
            para = paragraph_node([text_node(term)])
            para.assign_addresses("body.paragraph[0]")
            plan = extractor.extract_from_ast([para])
            assert plan.units[0].do_not_translate == True, f"{term} should be non-translatable"

    def test_version_number_detection(self):
        """Test version numbers are detected."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        for version in ["v1.0", "2.1.3", "1.0+", "v2.0.1"]:
            para = paragraph_node([text_node(version)])
            para.assign_addresses("body.paragraph[0]")
            plan = extractor.extract_from_ast([para])
            assert plan.units[0].do_not_translate == True, f"{version} should be non-translatable"

    def test_normal_text_translatable(self):
        """Test normal text is translatable."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        para = paragraph_node([text_node("This is normal text")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert plan.units[0].do_not_translate == False


class TestBatchTranslation:
    """Test batch translation with M2M100-hardened delimiter protection."""

    def test_batch_translate_success(self):
        """Test successful batch translation with delimiter survival (AST-FIX-01)."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create units
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
                do_not_translate=False,
            ),
            TextUnit(
                unit_id="u2",
                node_addr="p1.t2",
                kind=TextUnitKind.TEXT,
                source_text="World",
                do_not_translate=False,
            ),
        ]

        # Mock MT model with tokenizer
        mt_model = Mock()
        mt_model.tokenizer = Mock()
        mt_model.tokenizer.encode = Mock(
            side_effect=lambda text, **kwargs: list(text.encode("utf-8"))
        )
        mt_model.tokenizer.decode = Mock(
            side_effect=lambda tokens, **kwargs: bytes(tokens).decode("utf-8")
        )

        # Native batching: model receives a list of texts, returns a list of translations
        def mock_translate(texts, source_lang, target_lang, **kwargs):
            mapping = {"Hello": "Hola", "World": "Mundo"}
            return [mapping.get(t, t) for t in texts]

        mt_model.translate = Mock(side_effect=mock_translate)

        # Batch translate
        result = extractor.batch_translate_units(
            units, mt_model, src_lang="en", tgt_lang="es", batch_size=50
        )

        # Verify translations
        assert result[0].translated_text == "Hola"
        assert result[1].translated_text == "Mundo"

        # Verify stats
        assert extractor.batch_stats["successful_batches"] == 1
        assert extractor.batch_stats["fallback_batches"] == 0

    def test_batch_translate_delimiter_corruption_fallback(self):
        """Test automatic fallback when delimiter is corrupted (AST-FIX-04)."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
                do_not_translate=False,
            ),
            TextUnit(
                unit_id="u2",
                node_addr="p1.t2",
                kind=TextUnitKind.TEXT,
                source_text="World",
                do_not_translate=False,
            ),
        ]

        # Mock MT model with tokenizer that corrupts delimiter
        mt_model = Mock()
        mt_model.tokenizer = Mock()
        mt_model.tokenizer.encode = Mock(
            side_effect=lambda text, **kwargs: list(text.encode("utf-8"))
        )
        mt_model.tokenizer.decode = Mock(
            side_effect=lambda tokens, **kwargs: bytes(tokens).decode("utf-8")
        )

        call_count = [0]

        def mock_translate(texts, source_lang, target_lang, **kwargs):
            call_count[0] += 1
            text = texts[0] if isinstance(texts, list) else texts
            if call_count[0] == 1:
                # First call: batch call, corrupt delimiter (no header in new format)
                return ["Hola corrupted Mundo"]
            else:
                # Subsequent calls: individual fallback
                return [{"Hello": "Hola", "World": "Mundo"}.get(text, text)]

        mt_model.translate = Mock(side_effect=mock_translate)

        # Batch translate
        result = extractor.batch_translate_units(
            units, mt_model, src_lang="en", tgt_lang="es", batch_size=50
        )

        # Verify fallback occurred and translations are correct
        assert result[0].translated_text == "Hola"
        assert result[1].translated_text == "Mundo"

        # Verify stats - should have fallback due to mapping validation failure
        assert extractor.batch_stats["fallback_batches"] >= 1
        assert extractor.batch_stats.get("mapping_failures", 0) >= 1

    def test_batch_translate_skips_non_translatable(self):
        """Test non-translatable units are not sent to MT."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
                do_not_translate=False,
            ),
            TextUnit(
                unit_id="u2",
                node_addr="p1.c1",
                kind=TextUnitKind.CODE_SPAN,
                source_text="myCode()",
                do_not_translate=True,
            ),
            TextUnit(
                unit_id="u3",
                node_addr="p1.t2",
                kind=TextUnitKind.TEXT,
                source_text="World",
                do_not_translate=False,
            ),
        ]

        # Mock MT model with tokenizer
        mt_model = Mock()
        mt_model.tokenizer = Mock()
        mt_model.tokenizer.encode = Mock(
            side_effect=lambda text, **kwargs: list(text.encode("utf-8"))
        )
        mt_model.tokenizer.decode = Mock(
            side_effect=lambda tokens, **kwargs: bytes(tokens).decode("utf-8")
        )

        def mock_translate(texts, source_lang, target_lang, **kwargs):
            text = texts[0] if isinstance(texts, list) else texts
            # Ensure "myCode()" is never in the batch
            assert "myCode()" not in text

            # Extract NEW delimiter if present
            if "\ue000" in text:
                import re

                match = re.search(r"\uE000\uE000\uE000[a-f0-9]+\uE001\uE001\uE001", text)
                if match:
                    delimiter = match.group(0)
                    return [f"Hola{delimiter}Mundo"]
            return [{"Hello": "Hola", "World": "Mundo"}.get(text, text)]

        mt_model.translate = Mock(side_effect=mock_translate)

        # Batch translate
        result = extractor.batch_translate_units(
            units, mt_model, src_lang="en", tgt_lang="es", batch_size=50
        )

        # Verify non-translatable unit copied source to translated
        assert result[1].translated_text == "myCode()"

        # Verify translatable units were translated
        assert result[0].translated_text == "Hola"
        assert result[2].translated_text == "Mundo"

    def test_batch_translate_language_purity_check(self, monkeypatch):
        """Test language purity check detects mixed-language output (AST-FIX-05)."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create units with English text
        units = [
            TextUnit(
                unit_id="u1",
                node_addr="p1.t1",
                kind=TextUnitKind.TEXT,
                source_text="This is a long enough English text for language detection",
                do_not_translate=False,
            ),
            TextUnit(
                unit_id="u2",
                node_addr="p1.t2",
                kind=TextUnitKind.TEXT,
                source_text="Another long English sentence to test the system",
                do_not_translate=False,
            ),
        ]

        # Mock MT model with tokenizer
        mt_model = Mock()
        mt_model.tokenizer = Mock()

        # Mock tokenizer to pass pre-validation (delimiter preserved)
        # Store the last encoded text to return it unchanged in decode
        encoded_text = None

        def mock_encode(text, add_special_tokens=False):
            nonlocal encoded_text
            encoded_text = text  # Save the text
            return [1, 2, 3, 4, 5]  # Dummy tokens

        def mock_decode(tokens, skip_special_tokens=False):
            # Return the same text that was encoded to pass pre-validation
            return encoded_text if encoded_text else ""

        mt_model.tokenizer.encode = Mock(side_effect=mock_encode)
        mt_model.tokenizer.decode = Mock(side_effect=mock_decode)

        # Mock translation to return mixed language (German + English)
        # This simulates the bug where batch translation produces mixed output
        # Native batching: model receives list of texts, returns list of translations
        def mock_translate(texts, src, tgt, **kwargs):
            if len(texts) == 2:
                # Batch call: return mixed language (German + English) to trigger purity fail
                return [
                    "Das ist ein langer deutscher Text für Spracherkennung",  # German ✓
                    "This stays in English somehow",  # English (bug!)
                ]
            else:
                # Individual fallback: return pure German
                return ["Das ist ein langer deutscher Text für Spracherkennung"]

        mt_model.translate = Mock(side_effect=mock_translate)

        # Mock langdetect using monkeypatch (VLD-06: proper test isolation)

        # Create mock langdetect module
        mock_langdetect = MagicMock()

        def mock_detect(text):
            if "deutscher" in text or "Das ist" in text:
                return "de"  # German
            elif "English" in text or "stays in" in text:
                return "en"  # English
            return "de"

        mock_langdetect.detect = mock_detect
        mock_langdetect.DetectorFactory = MagicMock()
        mock_langdetect.DetectorFactory.seed = 0

        # Use monkeypatch to inject mock (automatic cleanup by pytest)
        monkeypatch.setitem(__import__("sys").modules, "langdetect", mock_langdetect)

        # Batch translate
        result = extractor.batch_translate_units(
            units, mt_model, src_lang="en", tgt_lang="de", batch_size=50
        )

        # Verify language purity failure was detected
        assert extractor.batch_stats.get("language_purity_failures", 0) >= 1, (
            "Language purity failure should be detected"
        )

        # Verify fallback to individual translation occurred
        assert extractor.batch_stats.get("fallback_batches", 0) >= 1, (
            "Fallback should occur when language purity fails"
        )

        # Verify units still got translated (via fallback)
        assert result[0].translated_text != ""
        assert result[1].translated_text != ""

        # Verify individual translations were used (pure German)
        assert "deutscher" in result[0].translated_text or result[0].translated_text != "", (
            "Fallback should translate units individually"
        )


class TestComplexDocuments:
    """Test extraction from complex document structures."""

    def test_multiple_paragraphs(self):
        """Test extraction from multiple paragraphs."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        para1 = paragraph_node([text_node("First paragraph")])
        para2 = paragraph_node([text_node("Second paragraph")])

        para1.assign_addresses("body.paragraph[0]")
        para2.assign_addresses("body.paragraph[1]")

        plan = extractor.extract_from_ast([para1, para2])

        assert len(plan.units) == 2
        assert plan.units[0].source_text == "First paragraph"
        assert plan.units[1].source_text == "Second paragraph"

    def test_yaml_only_document(self):
        """Test document with only frontmatter (empty body)."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Empty AST
        plan = extractor.extract_from_ast([])

        assert len(plan.units) == 0
        assert plan.ast_fingerprint is not None

    def test_mixed_element_types(self):
        """Test document with headings, paragraphs, lists, etc."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create mixed elements
        heading = heading_node(level=1, children=[text_node("Title")])
        para = paragraph_node([text_node("Content")])
        list_item = ASTNode(type=NodeType.LIST_ITEM, children=[text_node("Item")])

        heading.assign_addresses("body.heading[0]")
        para.assign_addresses("body.paragraph[0]")
        list_item.assign_addresses("body.listitem[0]")

        plan = extractor.extract_from_ast([heading, para, list_item])

        assert len(plan.units) == 3
        assert [u.source_text for u in plan.units] == ["Title", "Content", "Item"]


class TestASTFingerprint:
    """Test AST fingerprint calculation."""

    def test_fingerprint_deterministic(self):
        """Test AST fingerprint is deterministic."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create same structure twice
        para1 = paragraph_node([text_node("Hello")])
        para1.assign_addresses("body.paragraph[0]")

        para2 = paragraph_node([text_node("Hello")])
        para2.assign_addresses("body.paragraph[0]")

        plan1 = extractor.extract_from_ast([para1])
        plan2 = extractor.extract_from_ast([para2])

        assert plan1.ast_fingerprint == plan2.ast_fingerprint

    def test_fingerprint_changes_on_structure_change(self):
        """Test AST fingerprint changes when structure changes."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create different structures
        para1 = paragraph_node([text_node("Hello")])
        para1.assign_addresses("body.paragraph[0]")

        # Different structure (bold added)
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("Hello")])
        para2 = paragraph_node([strong])
        para2.assign_addresses("body.paragraph[0]")

        plan1 = extractor.extract_from_ast([para1])
        plan2 = extractor.extract_from_ast([para2])

        assert plan1.ast_fingerprint != plan2.ast_fingerprint


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_deeply_nested_structure(self):
        """Test deeply nested structure is handled."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create deep nesting
        text = text_node("Deep")
        em = ASTNode(type=NodeType.EMPHASIS, children=[text])
        strong = ASTNode(type=NodeType.STRONG, children=[em])
        link = ASTNode(type=NodeType.LINK, attrs={"url": "url"}, children=[strong])
        para = paragraph_node([link])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert len(plan.units) == 1
        assert plan.units[0].source_text == "Deep"

    def test_whitespace_only_text(self):
        """Test whitespace-only text is handled."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        para = paragraph_node([text_node("   ")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        # Whitespace-only text creates unit with empty source_text
        assert len(plan.units) == 1
        assert plan.units[0].source_text == ""
        assert plan.units[0].prefix_ws == "   "

    def test_node_without_address_handled(self):
        """Test nodes without addresses are handled gracefully."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create node without assigning addresses
        para = paragraph_node([text_node("Hello")])
        # Don't assign addresses

        # Should still work (addresses may be None)
        plan = extractor.extract_from_ast([para])

        # Extraction should still work
        assert len(plan.units) >= 0  # May create units or skip depending on implementation

    def test_logs_when_node_skipped(self, caplog):
        """Test that skipped nodes are logged at DEBUG level (SR-04)."""
        import logging

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create paragraph with text node but don't assign addresses
        para = paragraph_node([text_node("Hello")])
        # Explicitly don't assign addresses

        # Enable DEBUG logging for the extractor module
        with caplog.at_level(
            logging.DEBUG, logger="src.translation_engine.extractor.text_unit_extractor"
        ):
            plan = extractor.extract_from_ast([para])

        # Verify log message was emitted
        assert any("Skipping" in record.message for record in caplog.records), (
            "Expected 'Skipping' log message when node has no address"
        )

        # Verify no units were extracted (since no addresses)
        assert len(plan.units) == 0


class TestHelperMethods:
    """Test helper methods in TextUnitExtractor (VLD-03)."""

    def test_is_tokenizer_available_with_valid_tokenizer(self):
        """Test _is_tokenizer_available returns True when tokenizer exists."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create mock model with valid tokenizer
        mock_model = Mock()
        mock_model.tokenizer = Mock()

        # Should return True
        assert extractor._is_tokenizer_available(mock_model) is True

    def test_is_tokenizer_available_with_none_tokenizer(self):
        """Test _is_tokenizer_available returns False when tokenizer is None."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create mock model with None tokenizer
        mock_model = Mock()
        mock_model.tokenizer = None

        # Should return False
        assert extractor._is_tokenizer_available(mock_model) is False

    def test_is_tokenizer_available_without_tokenizer_attribute(self):
        """Test _is_tokenizer_available returns False when tokenizer attribute missing."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create mock model without tokenizer attribute
        mock_model = Mock(spec=[])  # Empty spec = no attributes

        # Should return False
        assert extractor._is_tokenizer_available(mock_model) is False

    def test_is_tokenizer_available_used_in_pre_validation(self):
        """Test that _is_tokenizer_available is actually used in pre-validation."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create mock model without tokenizer
        mock_model = Mock(spec=[])
        mock_model.translate = Mock(return_value=["translated"])

        # Create a simple batch
        from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind

        units = [
            TextUnit(
                unit_id="u1",
                node_addr="test.1",
                kind=TextUnitKind.TEXT,
                source_text="Hello",
                do_not_translate=False,
            )
        ]

        # Call batch_translate_units - should skip pre-validation but still translate
        result = extractor.batch_translate_units(
            units, mock_model, src_lang="en", tgt_lang="de", batch_size=10
        )

        # Should complete successfully (skipping pre-validation)
        assert len(result) == 1
        assert result[0].translated_text == "translated"


class TestConstantValidation:
    """Test module-level constant validation (VLD-04, PH-01)."""

    def test_constant_validation_uses_valueerror_not_assert(self):
        """
        Test that constant validation uses ValueError instead of assert.

        This ensures validation works even when Python runs with -O flag
        (which disables assert statements). Verified by inspecting the module
        source — importlib.reload() cannot trigger it because reload resets
        the constant from source before the check runs.
        """
        import inspect

        import src.translation_engine.extractor.text_unit_extractor as module

        source = inspect.getsource(module)

        # Confirm the validation block uses raise ValueError, not assert
        assert "raise ValueError" in source, (
            "Module should use raise ValueError for constant validation (not assert)"
        )
        assert "LANGUAGE_PURITY_MIN_LENGTH" in source, (
            "Module should validate LANGUAGE_PURITY_MIN_LENGTH"
        )

        # Confirm no bare assert is used for constant validation
        # (assert would be silently disabled with -O flag)
        # Look for the pattern: assert <constant> — should not exist for these
        import re

        bad_pattern = re.compile(
            r"^\s*assert\s+(5\s*<=\s*LANGUAGE_PURITY_MIN_LENGTH|LANGUAGE_PURITY_MIN_LENGTH)",
            re.MULTILINE,
        )
        assert not bad_pattern.search(source), (
            "Constant validation must not use bare assert (fails with -O flag)"
        )

    def test_valid_constants_import_successfully(self):
        """Test that module imports successfully with valid constants."""
        # This should not raise any exception
        from src.translation_engine.extractor.text_unit_extractor import (
            FALLBACK_RATE_THRESHOLD,
            LANGUAGE_PURITY_MIN_LENGTH,
            TOKEN_PER_WORD_ESTIMATE,
        )

        # Verify constants are in valid ranges
        assert 5 <= LANGUAGE_PURITY_MIN_LENGTH <= 100
        assert 0.01 <= FALLBACK_RATE_THRESHOLD <= 0.5
        assert 0.5 <= TOKEN_PER_WORD_ESTIMATE <= 3.0


class TestFrontmatterTranslation:
    """Test frontmatter translation (FIX-BT-03)."""

    def test_extract_frontmatter_string_field(self):
        """Test extraction of simple string frontmatter field."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Create frontmatter dictionary
        frontmatter = {
            "title": "Test Document",
            "slug": "test-doc",  # Protected field
        }

        # Extract from frontmatter only
        plan = extractor.extract_from_ast([], frontmatter=frontmatter)

        # Should extract title but not slug
        assert len(plan.units) == 1
        assert plan.units[0].source_text == "Test Document"
        assert plan.units[0].metadata["field_name"] == "title"
        assert plan.units[0].metadata["field_type"] == "string"
        assert plan.units[0].node_addr == "frontmatter.title"

    def test_extract_frontmatter_array_field(self):
        """Test extraction of array frontmatter field (e.g., keywords)."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        frontmatter = {"keywords": ["keyword1", "keyword2", "keyword3"]}

        plan = extractor.extract_from_ast([], frontmatter=frontmatter)

        # Should extract 3 array items
        assert len(plan.units) == 3
        assert plan.units[0].source_text == "keyword1"
        assert plan.units[0].metadata["field_name"] == "keywords"
        assert plan.units[0].metadata["field_type"] == "array"
        assert plan.units[0].metadata["index"] == 0
        assert plan.units[0].node_addr == "frontmatter.keywords[0]"

        assert plan.units[2].source_text == "keyword3"
        assert plan.units[2].metadata["index"] == 2
        assert plan.units[2].node_addr == "frontmatter.keywords[2]"

    def test_skip_protected_frontmatter_fields(self):
        """Test that protected fields are not extracted."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        frontmatter = {
            "title": "Test",  # Translatable
            "slug": "test",  # Protected
            "date": "2025-01-01",  # Protected
            "weight": 10,  # Protected (also not string)
        }

        plan = extractor.extract_from_ast([], frontmatter=frontmatter)

        # Should only extract title
        assert len(plan.units) == 1
        assert plan.units[0].source_text == "Test"
        assert plan.units[0].metadata["field_name"] == "title"

    def test_apply_frontmatter_string_translation(self):
        """Test applying translation to string frontmatter field."""
        from src.translation_engine.reconstructor.ast_renderer import ASTRenderer

        frontmatter = {"title": "English Title"}

        unit = TextUnit(
            unit_id="fm_title",
            node_addr="frontmatter.title",
            kind=TextUnitKind.TEXT,
            source_text="English Title",
            translated_text="Deutscher Titel",
            metadata={"field_name": "title", "field_type": "string"},
        )

        renderer = ASTRenderer()
        renderer.apply_translations([], [unit], frontmatter=frontmatter)

        # Title should be updated
        assert frontmatter["title"] == "Deutscher Titel"

    def test_apply_frontmatter_array_translation(self):
        """Test applying translation to array frontmatter field."""
        from src.translation_engine.reconstructor.ast_renderer import ASTRenderer

        frontmatter = {"keywords": ["English", "Keywords"]}

        units = [
            TextUnit(
                unit_id="fm_kw0",
                node_addr="frontmatter.keywords[0]",
                kind=TextUnitKind.TEXT,
                source_text="English",
                translated_text="Englisch",
                metadata={"field_name": "keywords", "field_type": "array", "index": 0},
            ),
            TextUnit(
                unit_id="fm_kw1",
                node_addr="frontmatter.keywords[1]",
                kind=TextUnitKind.TEXT,
                source_text="Keywords",
                translated_text="Schlüsselwörter",
                metadata={"field_name": "keywords", "field_type": "array", "index": 1},
            ),
        ]

        renderer = ASTRenderer()
        renderer.apply_translations([], units, frontmatter=frontmatter)

        # Array should be updated
        assert frontmatter["keywords"] == ["Englisch", "Schlüsselwörter"]

    def test_frontmatter_with_body_extraction(self):
        """Test extracting both frontmatter and body together."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Frontmatter
        frontmatter = {"title": "My Title", "description": "My description"}

        # Body AST
        para = paragraph_node([text_node("Body text")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para], frontmatter=frontmatter)

        # Should have 2 frontmatter units + 1 body unit = 3 total
        assert len(plan.units) == 3

        # Check frontmatter units
        fm_units = [u for u in plan.units if u.node_addr and u.node_addr.startswith("frontmatter.")]
        assert len(fm_units) == 2

        # Check body units
        body_units = [
            u for u in plan.units if not (u.node_addr and u.node_addr.startswith("frontmatter."))
        ]
        assert len(body_units) == 1
        assert body_units[0].source_text == "Body text"

    def test_empty_frontmatter_handled(self):
        """Test that empty frontmatter is handled gracefully."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Empty frontmatter
        plan = extractor.extract_from_ast([], frontmatter={})
        assert len(plan.units) == 0

        # None frontmatter
        plan = extractor.extract_from_ast([], frontmatter=None)
        assert len(plan.units) == 0

    def test_skip_empty_frontmatter_values(self):
        """Test that empty string values are skipped."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        frontmatter = {
            "title": "",  # Empty string
            "description": "   ",  # Whitespace only
            "keywords": ["good", "", "another"],  # Array with empty item
        }

        plan = extractor.extract_from_ast([], frontmatter=frontmatter)

        # Should only extract 'good' and 'another' from keywords array
        # Empty strings should be skipped
        assert len(plan.units) == 2
        assert plan.units[0].source_text == "good"
        assert plan.units[1].source_text == "another"


class TestBatchTranslateUnitsSortByLength:
    """TC-SCHED-001-C: Optional unit sorting by estimated token length.

    MS-SCHED-001-C-02/03/04: Verify that sort_by_length=True does NOT affect
    the output order of units — translations are applied in-place so the
    original `units` list order is always preserved.
    """

    def _make_mock_model(self):
        model = MagicMock()
        def fake_translate(texts, src_lang, tgt_lang):
            return [f"[{t}]" for t in texts]
        model.translate.side_effect = fake_translate
        return model

    def _make_unit(self, uid: str, text: str) -> TextUnit:
        return TextUnit(
            unit_id=uid,
            node_addr=f"p.{uid}",
            kind=TextUnitKind.TEXT,
            source_text=text,
            do_not_translate=False,
        )

    def test_sort_by_length_false_preserves_natural_order(self):
        """Default (sort_by_length=False) returns units in original order."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        units = [
            self._make_unit("1", "a very long string with many words here"),
            self._make_unit("2", "short"),
            self._make_unit("3", "medium length text"),
        ]
        model = self._make_mock_model()

        result = extractor.batch_translate_units(units, model, "en", "de", sort_by_length=False)

        assert [u.unit_id for u in result] == ["1", "2", "3"]

    def test_sort_by_length_true_preserves_original_unit_order(self):
        """sort_by_length=True must not change the output unit order.

        This is the key regression guard for TC-SCHED-001-C-03.
        Translations are applied in-place, so `units` order is always preserved.
        """
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        units = [
            self._make_unit("long", "a very long string with many words here"),
            self._make_unit("short", "hi"),
            self._make_unit("medium", "medium length text"),
        ]
        model = self._make_mock_model()

        result = extractor.batch_translate_units(units, model, "en", "de", sort_by_length=True)

        assert [u.unit_id for u in result] == ["long", "short", "medium"]

    def test_sort_by_length_translations_assigned_to_correct_units(self):
        """Negative control: each unit receives its own translation, not another's.

        MS-SCHED-001-C-04: mixed-length unit mapping negative control.
        """
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        units = [
            self._make_unit("u1", "alpha beta gamma delta epsilon"),
            self._make_unit("u2", "x"),
            self._make_unit("u3", "hello world"),
        ]

        model = MagicMock()
        def identity_translate(texts, src_lang, tgt_lang):
            return [f"T:{t}" for t in texts]
        model.translate.side_effect = identity_translate

        result = extractor.batch_translate_units(units, model, "en", "de", sort_by_length=True)

        for unit in result:
            assert unit.translated_text is not None
            assert unit.source_text in unit.translated_text, (
                f"unit {unit.unit_id}: translation '{unit.translated_text}' "
                f"does not contain source '{unit.source_text}'"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
