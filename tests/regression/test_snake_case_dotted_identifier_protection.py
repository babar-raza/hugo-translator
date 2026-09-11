"""RB-011/GluedIdentifierValidator recurrence: protect bare snake_case/dotted
module-style identifiers outside backticks (config/global.yaml body.preserve_
patterns).

Reproduced on blog.aspose.org/pdf/python/pdf-generated-in-python: the
frontmatter `description` field's prose ("...ships an aspose_pdf.generated
subpackage...") carries the module identifiers "aspose_pdf.generated" and
"aspose_pdf" with no backticks (frontmatter strings have no markdown code-span
syntax) and no PascalCase shape (Python module names are lower_snake_case), so
neither existing preserve_pattern reaches them. This field correlated with 3
distinct-locale GluedIdentifierValidator rejections (es, fa, de) on the same
campaign, tripping heal_queue.py's QU-02 per-file quarantine (>=3 locales) and
halting the rest of that page's run -- see data/summaries/fp-glued-identifier-
recurrence-pdfgeneratedpython-20260911.json.

The new pattern (`\\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?:\\.[A-Za-z0-9_]+)*\\b`)
requires at least one underscore segment -- unlike a bare dot, no portfolio
target language's prose ever contains an underscore, so it cannot false-
positive on ordinary abbreviations ("e.g.", "U.S.", "Mr. Smith") the way a
dot-only pattern would. It deliberately does NOT cover the pure-dot identifier
shape ("Workbook.save"): that shape is documented in glued_identifier_
validator.py's own docstring as gate-only-catchable model stochasticity, not a
producer bug fixable by protection alone.
"""

from src.translation_engine.extractor.placeholder_manager import PlaceholderManager
from src.utils.config_loader import get_global_config


def _protect(text: str) -> tuple[str, dict[str, str]]:
    patterns = get_global_config()["body"]["preserve_patterns"]
    pm = PlaceholderManager()
    return pm.protect(text, patterns)


class TestSnakeCaseDottedIdentifiersAreProtected:
    def test_reproduces_the_exact_failing_description_fragment(self):
        protected, placeholder_map = _protect(
            "ships an aspose_pdf.generated subpackage with a second Document"
        )
        assert "aspose_pdf.generated" not in protected
        assert "aspose_pdf.generated" in placeholder_map.values()

    def test_bare_underscore_identifier_without_a_dot(self):
        protected, placeholder_map = _protect("differ from the main aspose_pdf package")
        assert "aspose_pdf" not in protected
        assert "aspose_pdf" in placeholder_map.values()

    def test_multi_segment_dotted_module_path(self):
        protected, placeholder_map = _protect(
            "defined in text_unit_extractor.py near the top"
        )
        assert "text_unit_extractor.py" not in protected
        assert "text_unit_extractor.py" in placeholder_map.values()

    def test_snake_case_function_name(self):
        protected, placeholder_map = _protect("call load_xlsx to open the file")
        assert "load_xlsx" not in protected
        assert "load_xlsx" in placeholder_map.values()


class TestOrdinaryProseIsNotFalsePositivelyProtected:
    """Underscore-gating means dot-only abbreviations and version numbers
    must stay fully translatable."""

    def test_latin_abbreviations_stay_translatable(self):
        for sentence in (
            "e.g. the description field",
            "i.e. the module namespace",
            "released in the U.S. first",
        ):
            protected, placeholder_map = _protect(sentence)
            assert protected == sentence
            assert placeholder_map == {}

    def test_version_numbers_stay_translatable(self):
        protected, placeholder_map = _protect("requires Python 3.11 or later")
        assert protected == "requires Python 3.11 or later"
        assert placeholder_map == {}

    def test_pure_dot_identifier_is_out_of_scope_for_this_pattern(self):
        """Workbook.save has no underscore -- this pattern intentionally does
        not reach it (see module docstring); it stays gate-only-catchable."""
        protected, placeholder_map = _protect("call Workbook.save to persist it")
        assert protected == "call Workbook.save to persist it"
        assert placeholder_map == {}


class TestNoFalsePositivesOnBrandTerms:
    def test_brand_dotted_term_stays_translatable_here(self):
        # "Aspose.PDF" has no underscore, so this pattern doesn't touch it --
        # it is separately protected via terminology.yaml/RB-002, not this
        # preserve_pattern.
        protected, placeholder_map = _protect("Aspose.PDF FOSS for Python")
        assert protected == "Aspose.PDF FOSS for Python"
        assert placeholder_map == {}
