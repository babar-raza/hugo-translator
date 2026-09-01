"""Regression coverage for entity-containing frontmatter prose.

The zero-defect Aspose pilot found that the AST extractor copied an entire
frontmatter title from English whenever spaCy recognized the embedded Aspose
brand as an organization.  The brand remains protected, while the surrounding
prose must remain a translation unit.
"""

from types import SimpleNamespace

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor


class _EntityNlp:
    def __init__(self, entity_text: str):
        self.entity_text = entity_text

    def __call__(self, _text: str):
        return SimpleNamespace(
            ents=[SimpleNamespace(label_="ORG", text=self.entity_text)]
        )


def test_embedded_organization_does_not_protect_entire_prose_unit():
    extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
    extractor._nlp = _EntityNlp("Aspose.Cells")

    assert (
        extractor._is_non_translatable(
            "Spreadsheet Management in Rust with Aspose.Cells FOSS"
        )
        is False
    )


def test_standalone_organization_remains_protected():
    extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
    extractor._nlp = _EntityNlp("Aspose.Cells")

    assert extractor._is_non_translatable("Aspose.Cells") is True
