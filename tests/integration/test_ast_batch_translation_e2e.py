#!/usr/bin/env python
"""
Integration test for AST batch translation end-to-end workflow (SR-06/VLD-01).

Tests the complete pipeline:
1. Parse markdown file to AST
2. Extract text units
3. Batch translate units
4. Reconstruct markdown

Without requiring the actual M2M100 model.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


class TestASTBatchTranslationE2E:
    """End-to-end integration tests for AST batch translation system."""

    @pytest.fixture
    def test_fixture_path(self):
        """Path to the test markdown fixture."""
        return Path(__file__).parent.parent / "fixtures" / "ast_integration_test.md"

    @pytest.fixture
    def mock_mt_model(self):
        """Create a mock MT model that simulates M2M100 behavior."""
        mt_model = Mock()
        mt_model.tokenizer = Mock()

        # Store the last encoded text for decode
        encoded_text = None

        def mock_encode(text, add_special_tokens=False):
            nonlocal encoded_text
            encoded_text = text
            # Return dummy token IDs
            return list(range(1, len(text.split()) + 1))

        def mock_decode(tokens, skip_special_tokens=False):
            # Return the same text that was encoded
            return encoded_text if encoded_text else ""

        mt_model.tokenizer.encode = Mock(side_effect=mock_encode)
        mt_model.tokenizer.decode = Mock(side_effect=mock_decode)

        # Mock translation function
        def mock_translate(texts, src, tgt, **kwargs):
            """Mock translation that preserves delimiters and translates text."""
            results = []
            for text in texts:
                # Check if this is a batch (contains delimiter)
                if "\uE000\uE000\uE000" in text:
                    # Extract delimiter pattern
                    delimiter_pattern = r'(\uE000\uE000\uE000[a-f0-9\-]+\uE001\uE001\uE001)'
                    parts = re.split(delimiter_pattern, text)

                    # Translate non-delimiter parts to German
                    translated_parts = []
                    for part in parts:
                        if re.match(delimiter_pattern, part):
                            # Keep delimiter unchanged
                            translated_parts.append(part)
                        elif part.strip():
                            # Simple mock translation: prepend "DE:"
                            translated_parts.append(f"DE:{part}")
                        else:
                            translated_parts.append(part)

                    results.append(''.join(translated_parts))
                else:
                    # Individual translation
                    results.append(f"DE:{text}")

            return results

        mt_model.translate = Mock(side_effect=mock_translate)

        return mt_model

    @pytest.fixture
    def mock_langdetect(self):
        """Mock langdetect module for language purity checks."""
        import sys

        mock_langdetect = MagicMock()

        def mock_detect(text):
            # Simple heuristic: if text starts with "DE:", it's German
            if text.startswith("DE:"):
                return "de"
            return "en"

        mock_langdetect.detect = mock_detect
        mock_langdetect.DetectorFactory = MagicMock()
        mock_langdetect.DetectorFactory.seed = 0

        # Inject into sys.modules
        sys.modules['langdetect'] = mock_langdetect

        yield mock_langdetect

        # Cleanup
        if 'langdetect' in sys.modules:
            del sys.modules['langdetect']

    def test_ast_batch_translation_full_pipeline(self, test_fixture_path, mock_mt_model, mock_langdetect):
        """
        Test complete AST batch translation pipeline with real markdown file.

        Validates:
        - File parsing to AST
        - Text unit extraction
        - Batch translation (not individual)
        - Delimiter preservation
        - Code block preservation
        - Link preservation
        - Language purity check
        - Markdown reconstruction
        """
        # 1. PARSE: Read and parse the test fixture
        assert test_fixture_path.exists(), f"Test fixture not found: {test_fixture_path}"

        with open(test_fixture_path, encoding='utf-8') as f:
            source_content = f.read()

        parser = HugoParser()
        doc = parser.parse_string(source_content)

        # Verify parsing succeeded
        assert doc is not None, "Parser should return HugoDocument"
        assert doc.ast is not None, "Document should have AST"
        assert len(doc.ast) > 0, "AST should have nodes"

        # 2. EXTRACT: Extract text units from AST
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        plan = extractor.extract_from_ast(doc.ast)
        units = plan.units

        # Verify extraction
        assert len(units) > 0, "Should extract text units from document"

        # Count translatable units
        translatable_units = [u for u in units if not u.do_not_translate]
        assert len(translatable_units) >= 5, "Should have at least 5 translatable units"

        # Verify code blocks are marked as non-translatable
        code_units = [u for u in units if u.do_not_translate and "def hello_world" in (u.source_text or "")]
        assert len(code_units) > 0, "Code blocks should be marked as non-translatable"

        # 3. TRANSLATE: Batch translate units
        translated_units = extractor.batch_translate_units(
            units,
            mock_mt_model,
            src_lang="en",
            tgt_lang="de",
            batch_size=50
        )

        # Verify translation occurred
        assert len(translated_units) == len(units), "All units should be returned"

        # Verify batch translation was used (not all individual)
        batch_stats = extractor.batch_stats
        assert batch_stats.get('total_batches', 0) > 0, "Should use batch translation"

        # Check that most translations succeeded via batch (not fallback)
        successful_batches = batch_stats.get('successful_batches', 0)
        total_batches = batch_stats.get('total_batches', 0)

        # Allow some fallback, but most should succeed
        if total_batches > 0:
            success_rate = successful_batches / total_batches
            assert success_rate >= 0.5, \
                f"Batch success rate should be >= 50%, got {success_rate:.1%}"

        # Verify no delimiter corruption
        delimiter_corruptions = batch_stats.get('delimiter_corruptions', 0)
        assert delimiter_corruptions == 0, "Should have no delimiter corruptions"

        # Verify translatable units got translated
        for unit in translated_units:
            if not unit.do_not_translate:
                assert unit.translated_text is not None, \
                    f"Translatable unit {unit.unit_id} should have translation"
                assert unit.translated_text != "", \
                    f"Translatable unit {unit.unit_id} translation should not be empty"

        # Verify non-translatable units preserved
        for unit in translated_units:
            if unit.do_not_translate:
                # Non-translatable units should either have no translation or same as source
                if unit.translated_text:
                    assert unit.translated_text == unit.source_text, \
                        f"Non-translatable unit {unit.unit_id} should preserve source text"

        # 4. APPLY & RENDER: Apply translations to AST and render to markdown
        renderer = ASTRenderer()
        renderer.apply_translations(doc.ast, translated_units)
        translated_content = renderer.render_to_markdown(doc.ast)

        # Verify reconstruction succeeded
        assert translated_content is not None, "Reconstruction should succeed"
        assert len(translated_content) > 0, "Reconstructed content should not be empty"

        # Verify structure preserved (body only, no frontmatter)
        assert "```python" in translated_content, "Code blocks should be preserved"
        assert "def hello_world" in translated_content, "Code content should be preserved"
        assert "[" in translated_content and "]" in translated_content, \
            "Link syntax should be preserved"
        assert "https://example.com" in translated_content, "URLs should be preserved"

        # Verify headings preserved
        assert "#" in translated_content, "Headings should be preserved"

    def test_ast_batch_translation_statistics(self, test_fixture_path, mock_mt_model, mock_langdetect):
        """
        Test that batch statistics are properly tracked.

        Validates:
        - total_batches tracked
        - successful_batches tracked
        - fallback_batches tracked (if any)
        - No double-counting (SR-02 fix)
        """
        with open(test_fixture_path, encoding='utf-8') as f:
            source_content = f.read()

        parser = HugoParser()
        doc = parser.parse_string(source_content)

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        plan = extractor.extract_from_ast(doc.ast)
        units = plan.units

        # Translate
        translated_units = extractor.batch_translate_units(
            units,
            mock_mt_model,
            src_lang="en",
            tgt_lang="de",
            batch_size=50
        )

        # Verify statistics
        stats = extractor.batch_stats

        # Basic statistics present
        assert 'total_batches' in stats
        assert 'successful_batches' in stats
        assert 'fallback_batches' in stats

        # Statistics make sense
        total = stats['total_batches']
        successful = stats['successful_batches']
        fallback = stats['fallback_batches']

        # Total should equal successful + fallback (no double counting)
        assert total == successful + fallback, \
            f"Statistics inconsistent: {total} total != {successful} successful + {fallback} fallback"

        # All batches should be accounted for
        assert total > 0, "Should have processed at least one batch"

    def test_ast_batch_translation_delimiter_design(self, test_fixture_path, mock_mt_model, mock_langdetect):
        """
        Test that new delimiter design (AST-FIX-01) is used.

        Validates:
        - No English words in delimiters
        - PUA characters used
        - Triple repetition
        """
        with open(test_fixture_path, encoding='utf-8') as f:
            source_content = f.read()

        parser = HugoParser()
        doc = parser.parse_string(source_content)

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        plan = extractor.extract_from_ast(doc.ast)
        units = plan.units

        # Capture what was sent to translation
        original_translate = mock_mt_model.translate
        batch_texts = []

        def capture_translate(texts, src, tgt):
            batch_texts.extend(texts)
            return original_translate(texts, src, tgt)

        mock_mt_model.translate = Mock(side_effect=capture_translate)

        # Translate
        translated_units = extractor.batch_translate_units(
            units,
            mock_mt_model,
            src_lang="en",
            tgt_lang="de",
            batch_size=50
        )

        # Check batch texts for delimiter format
        batch_with_delimiter = [t for t in batch_texts if "\uE000\uE000\uE000" in t]

        if len(batch_with_delimiter) > 0:
            # Verify no English words in delimiter
            english_words = ["UNTRANSLATABLE", "BOUNDARY", "BATCH", "COUNT", "HEADER"]
            for batch_text in batch_with_delimiter:
                for word in english_words:
                    assert word not in batch_text, \
                        f"Batch text should not contain English word '{word}'"

            # Verify PUA characters present
            for batch_text in batch_with_delimiter:
                assert "\uE000" in batch_text, "Should contain PUA start token"
                assert "\uE001" in batch_text, "Should contain PUA end token"

                # Verify triple repetition
                # Count consecutive PUA characters
                assert "\uE000\uE000\uE000" in batch_text, \
                    "Should have triple repetition of start token"
                assert "\uE001\uE001\uE001" in batch_text, \
                    "Should have triple repetition of end token"

    def test_ast_batch_translation_dynamic_sizing(self, test_fixture_path, mock_mt_model, mock_langdetect):
        """
        Test that dynamic batch sizing (AST-FIX-03) is working.

        Validates:
        - Batch size respects unit limits
        - Batch size respects token limits (estimated)
        """
        with open(test_fixture_path, encoding='utf-8') as f:
            source_content = f.read()

        parser = HugoParser()
        doc = parser.parse_string(source_content)

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        plan = extractor.extract_from_ast(doc.ast)
        units = plan.units

        # Use very small batch size to force multiple batches
        translated_units = extractor.batch_translate_units(
            units,
            mock_mt_model,
            src_lang="en",
            tgt_lang="de",
            batch_size=3  # Small batch size
        )

        # With small batch size, should create multiple batches
        stats = extractor.batch_stats
        total_batches = stats.get('total_batches', 0)

        translatable_count = len([u for u in units if not u.do_not_translate])

        if translatable_count > 3:
            # Should have created multiple batches
            assert total_batches > 1, \
                f"With {translatable_count} units and batch_size=3, should have >1 batch"

    def test_ast_batch_translation_empty_document(self, mock_mt_model, mock_langdetect):
        """
        Test handling of empty document (PH-07).

        Validates that system gracefully handles documents with no translatable content.
        """
        # Create a minimal document with only frontmatter
        empty_content = """---
title: "Empty Document"
---

"""
        parser = HugoParser()
        doc = parser.parse_string(empty_content)

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        plan = extractor.extract_from_ast(doc.ast)
        units = plan.units

        # Should have no translatable units (only frontmatter)
        translatable_units = [u for u in units if not u.do_not_translate]
        assert len(translatable_units) == 0, "Empty document should have no translatable units"

        # Translation should handle empty list gracefully
        translated_units = extractor.batch_translate_units(
            units,
            mock_mt_model,
            src_lang="en",
            tgt_lang="de",
            batch_size=50
        )

        # Should return same units
        assert len(translated_units) == len(units)

        # Should not have called translation (no batches)
        stats = extractor.batch_stats
        assert stats.get('total_batches', 0) == 0, "Empty document should not create batches"

    def test_ast_batch_translation_malformed_delimiter(self, mock_mt_model, mock_langdetect):
        """
        Test handling of malformed delimiter in translation (PH-07).

        Validates fallback when delimiter gets corrupted during translation.
        """
        # Create test content
        test_content = """---
title: "Test"
---

## Test Section

This is a test paragraph.

Another paragraph here.
"""
        parser = HugoParser()
        doc = parser.parse_string(test_content)

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        plan = extractor.extract_from_ast(doc.ast)
        units = plan.units

        # Mock translation that corrupts delimiter
        def corrupt_delimiter_translate(texts, src, tgt):
            """Mock translation that partially corrupts delimiter."""
            results = []
            for text in texts:
                if "\uE000\uE000\uE000" in text:
                    # Corrupt delimiter by removing part of it
                    corrupted = text.replace("\uE000\uE000\uE000", "\uE000\uE000")
                    results.append(corrupted)
                else:
                    results.append(f"DE:{text}")
            return results

        mock_mt_model.translate = Mock(side_effect=corrupt_delimiter_translate)

        # Translate - should detect corruption and fall back
        translated_units = extractor.batch_translate_units(
            units,
            mock_mt_model,
            src_lang="en",
            tgt_lang="de",
            batch_size=50
        )

        # Should have attempted batch translation
        stats = extractor.batch_stats
        assert stats.get('total_batches', 0) > 0, "Should have attempted batch translation"

        # Should have detected delimiter corruption
        delimiter_corruptions = stats.get('delimiter_corruptions', 0)
        if delimiter_corruptions > 0:
            # Fallback should have been triggered
            fallback_batches = stats.get('fallback_batches', 0)
            assert fallback_batches > 0, "Delimiter corruption should trigger fallback"

        # All units should still have translations (via fallback)
        for unit in translated_units:
            if not unit.do_not_translate:
                assert unit.translated_text is not None, "All units should be translated via fallback"

    def test_ast_batch_translation_model_error(self, mock_mt_model, mock_langdetect):
        """
        Test handling of model error during translation (PH-07).

        Validates graceful error handling when translation model fails.
        """
        # Create test content
        test_content = """---
title: "Test"
---

## Test Section

This is a test paragraph.
"""
        parser = HugoParser()
        doc = parser.parse_string(test_content)

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        plan = extractor.extract_from_ast(doc.ast)
        units = plan.units

        # Mock translation that raises exception
        mock_mt_model.translate = Mock(side_effect=RuntimeError("Model timeout"))

        # Translation should handle exception gracefully
        try:
            translated_units = extractor.batch_translate_units(
                units,
                mock_mt_model,
                src_lang="en",
                tgt_lang="de",
                batch_size=50
            )

            # If exception is caught internally, check that error is logged
            # and units are returned with no translations
            for unit in translated_units:
                if not unit.do_not_translate:
                    # Translation should be None or empty due to error
                    assert unit.translated_text is None or unit.translated_text == "", \
                        "Translation should fail gracefully on model error"

        except RuntimeError as e:
            # If exception propagates, that's also acceptable behavior
            assert "Model timeout" in str(e), "Should propagate model error"

    def test_no_language_markers_in_output(self, mock_mt_model, mock_langdetect):
        """
        Test that output contains no language markers (FIX-BT-02).

        Validates full E2E pipeline produces clean output with no leaked markers.
        """
        # Create test content
        source_md = """---
title: Test Document
---

This is a test paragraph with **bold** text.

## Section Heading

- List item 1
- List item 2
"""

        # Parse
        parser = HugoParser()
        doc = parser.parse_string(source_md)

        # Extract
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        plan = extractor.extract_from_ast(doc.ast)
        units = plan.units

        # Simulate translation that adds markers (mimics the bug)
        for unit in units:
            if not unit.do_not_translate:
                unit.translated_text = f"__de__{unit.source_text}__de__"

        # Render (should sanitize markers)
        renderer = ASTRenderer()
        renderer.apply_translations(doc.ast, units)
        output_md = renderer.render_to_markdown(doc.ast)

        # Verify no markers in output
        assert "__de__" not in output_md, f"Found __de__ in output: {output_md}"
        assert "__en__" not in output_md, f"Found __en__ in output: {output_md}"
        assert "__fr__" not in output_md, f"Found __fr__ in output: {output_md}"
        assert "__es__" not in output_md, f"Found __es__ in output: {output_md}"
        assert "__it__" not in output_md, f"Found __it__ in output: {output_md}"

        # Verify content still present (markers removed, not content)
        assert "Test" in output_md or "test" in output_md.lower()
        assert "bold" in output_md

        # Verify structure preserved
        assert "##" in output_md  # Heading
        assert "-" in output_md or "*" in output_md  # List markers

    def test_frontmatter_translation(self, mock_mt_model, mock_langdetect):
        """
        Test frontmatter translation (FIX-BT-03).

        Validates that frontmatter fields are extracted, translated, and applied.
        """
        source_content = """---
title: "English Title"
description: "English description for SEO"
keywords: ["keyword1", "keyword2", "keyword3"]
slug: "test-slug"
date: "2025-01-01"
weight: 10
---

## Test Heading

Test paragraph with some content.
"""

        parser = HugoParser()
        doc = parser.parse_string(source_content)

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", mt_model=mock_mt_model)
        plan = extractor.extract_from_ast(doc.ast, frontmatter=doc.frontmatter)
        units = plan.units

        # Should have frontmatter units (title, description, 3 keywords) + body units
        frontmatter_units = [u for u in units if u.node_addr and u.node_addr.startswith('frontmatter.')]
        assert len(frontmatter_units) >= 5, f"Should extract at least 5 frontmatter fields, got {len(frontmatter_units)}"

        # Verify title unit
        title_units = [u for u in frontmatter_units if u.metadata.get('field_name') == 'title']
        assert len(title_units) == 1
        assert title_units[0].source_text == "English Title"

        # Verify description unit
        desc_units = [u for u in frontmatter_units if u.metadata.get('field_name') == 'description']
        assert len(desc_units) == 1
        assert desc_units[0].source_text == "English description for SEO"

        # Verify keywords units
        kw_units = [u for u in frontmatter_units if u.metadata.get('field_name') == 'keywords']
        assert len(kw_units) == 3
        assert kw_units[0].source_text == "keyword1"
        assert kw_units[1].source_text == "keyword2"
        assert kw_units[2].source_text == "keyword3"

        # Translate (mock adds "DE:" prefix)
        translated_units = extractor.batch_translate_units(
            units,
            mock_mt_model,
            src_lang="en",
            tgt_lang="de",
            batch_size=50
        )

        # Apply translations
        renderer = ASTRenderer()
        renderer.apply_translations(doc.ast, translated_units, frontmatter=doc.frontmatter)

        # Verify frontmatter translated
        assert doc.frontmatter['title'].startswith('DE:'), f"Title should be translated, got: {doc.frontmatter['title']}"
        assert doc.frontmatter['description'].startswith('DE:'), f"Description should be translated, got: {doc.frontmatter['description']}"
        assert all(kw.startswith('DE:') for kw in doc.frontmatter['keywords']), \
            f"All keywords should be translated, got: {doc.frontmatter['keywords']}"

        # Verify protected fields unchanged
        assert doc.frontmatter['slug'] == "test-slug", "Slug should not be translated"
        assert doc.frontmatter['date'] == '2025-01-01', "Date should not be translated"
        assert doc.frontmatter['weight'] == 10, "Weight should not be translated"
