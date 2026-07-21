r"""Regression test for the digit-prefixed heading bug (found 2026-07-19).

_is_technical_identifier()'s "version number" pattern
(r"^v?\d+\.?\d*[\.\+\-]?") had no end anchor, so re.match only required the
text to START with a digit -- headings like "3D Model Inspection and
Validation" or "2D Visual Effects" satisfied it on the leading digit alone
and were marked non-translatable, shipping the English heading in every
locale on every site using AST body reconstruction (blog, reference, docs,
kb.aspose.org all have use_ast_body_reconstruction: true). Confirmed live on
blog.aspose.org/slides/cpp/slides-visual-effects-cpp (34/36 locales) and
docs.aspose.org/3d/python/developer-guide/format-support.md (## 3MF Format
untranslated in fr while sibling OBJ/STL/glTF/FBX headings translated fine).
"""
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor


class TestDigitPrefixedHeadingsAreTranslatable:
    def setup_method(self):
        self.extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

    def test_digit_prefixed_heading_is_translatable(self):
        """The core regression: a heading merely starting with a digit must
        not be treated as a version number / non-translatable identifier."""
        assert self.extractor._is_technical_identifier("3D Model Inspection and Validation") is False
        assert self.extractor._is_technical_identifier("2D Visual Effects") is False
        assert self.extractor._is_technical_identifier("3MF to glTF (Manufacturing to Visualization)") is False
        assert self.extractor._is_technical_identifier("3MF (3D Manufacturing Format)") is False
        assert self.extractor._is_technical_identifier("3MF Format") is False

    def test_genuine_version_numbers_still_non_translatable(self):
        """The fix must not regress the pattern's actual intended purpose."""
        assert self.extractor._is_technical_identifier("v1.2") is True
        assert self.extractor._is_technical_identifier("1.2.3") is True
        assert self.extractor._is_technical_identifier("2.0+") is True
        assert self.extractor._is_technical_identifier("2.0-") is True
        assert self.extractor._is_technical_identifier("5") is True

    def test_non_translatable_via_full_pipeline(self):
        """End-to-end via _is_non_translatable(), which is what the AST
        extractor actually calls when deciding whether to translate a
        heading unit."""
        assert self.extractor._is_non_translatable("3D Model Inspection and Validation") is False
        assert self.extractor._is_non_translatable("v2.1") is True
