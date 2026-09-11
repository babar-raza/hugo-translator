"""TC-APT-014 (wave-cellsrust-quickstart-retrigger-20260911r3): four-agent
parallel rubric review of all 23 gate-accepted locales found the SAME two
defect classes recurring at the same structural position in every single
file, confirming an RB-005 producer bug rather than per-language variance:

1. The heading "### Prerequisites" and the table header cells
   "Requirement"/"Detail" were left byte-identical to English in all 23
   files. Root cause: text_unit_extractor.py's `_is_non_translatable` checks
   the i18n template-string registry first (`is_translate_eligible`) and
   only falls back to the legacy PascalCase-shape heuristic
   (`_is_technical_identifier`) when no registry entry exists -- the same
   class of bug already fixed for "Issue"/"Cause" (TC-APT-108) and
   "Encryption" (TC-APT-053). Fix: added heading.prerequisites /
   table.header.requirement / table.header.detail entries to
   config/i18n/template_strings/_registry.yaml (status=pending, no locale
   values needed -- unblocking eligibility routes the text through normal
   MT/LLM translation, the same minimal fix "Encryption" already uses with
   zero locale files of its own).

2. A DIFFERENT, more severe bug: two full list-item sentences --
   "`put_value_string` / ... / `put_value_decimal` -- typed cell setters."
   and "`display_string_value` -- the cell's display text when reading
   values back." -- were left entirely untranslated in all 23 files. Root
   cause: `_is_technical_identifier`'s snake_case check was
   `"_" in text and text.islower()`, which matches ANY text containing an
   underscore ANYWHERE with no uppercase letters at all -- not just a
   standalone snake_case identifier. A full lowercase prose sentence that
   merely *mentions* a snake_case identifier (extremely common in Rust/
   Python/Go API-reference bullet lists across the whole portfolio, not
   just this page) was silently protected and copied verbatim into every
   language. Fixed by anchoring the check to the whole string
   (`^[a-z][a-z0-9_]*$`), matching every other identifier-shape check in
   the same method; a standalone identifier unit
   ("aspose_slides_low_code", tested below) is still protected.
"""

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import list_item_node, paragraph_node, text_node
from src.translation_engine.terminology.classification import (
    categories_for_kind,
    get_default_registry,
    is_translate_eligible,
)

HEADING_CATEGORIES = categories_for_kind("heading_text")
TABLE_CELL_CATEGORIES = categories_for_kind("table_cell_text")


# --- Defect class 1: single-hump heading/table-header words -----------------


def test_prerequisites_is_now_translate_eligible_as_a_heading():
    assert is_translate_eligible("Prerequisites", HEADING_CATEGORIES) is True


def test_requirement_is_now_translate_eligible_as_a_table_header():
    assert is_translate_eligible("Requirement", TABLE_CELL_CATEGORIES) is True


def test_detail_is_now_translate_eligible_as_a_table_header():
    assert is_translate_eligible("Detail", TABLE_CELL_CATEGORIES) is True


def test_registry_entries_exist_with_the_expected_shape():
    reg = get_default_registry()
    for entry_id, expected_en, expected_category in (
        ("heading.prerequisites", "Prerequisites", "section_heading"),
        ("table.header.requirement", "Requirement", "table_header"),
        ("table.header.detail", "Detail", "table_header"),
    ):
        entry = reg.entries.get(entry_id)
        assert entry is not None, f"missing registry entry {entry_id}"
        assert entry["en"] == expected_en
        assert entry["category"] == expected_category
        assert entry["status"] != "deprecated"


def test_registry_has_no_load_errors():
    reg = get_default_registry()
    assert reg.load_errors == []


def test_description_is_still_eligible_the_same_way_it_always_was():
    """Regression control: the pre-existing table.header.description entry
    must be unaffected by this change."""
    assert is_translate_eligible("Description", TABLE_CELL_CATEGORIES) is True


# --- Defect class 2: full sentence merely mentioning a snake_case identifier


class TestSnakeCaseSentenceNoLongerProtected:
    def test_typed_cell_setters_bullet_is_now_translatable(self):
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        item = list_item_node(
            [
                text_node(
                    "`put_value_string` / `put_value_i32` / `put_value_bool` / "
                    "`put_value_decimal` — typed cell setters."
                )
            ]
        )
        item.assign_addresses("body.list[0].listitem[0]")

        plan = extractor.extract_from_ast([item])

        prose_units = [u for u in plan.units if "typed cell setters" in u.source_text]
        assert prose_units, "expected the bullet's prose text to be extracted as its own unit"
        assert prose_units[0].do_not_translate is False

    def test_display_string_value_bullet_is_now_translatable(self):
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        item = list_item_node(
            [
                text_node(
                    "`display_string_value` — the cell's display text when "
                    "reading values back."
                )
            ]
        )
        item.assign_addresses("body.list[0].listitem[0]")

        plan = extractor.extract_from_ast([item])

        prose_units = [u for u in plan.units if "display text when reading" in u.source_text]
        assert prose_units, "expected the bullet's prose text to be extracted as its own unit"
        assert prose_units[0].do_not_translate is False

    def test_standalone_snake_case_identifier_is_still_protected(self):
        """Regression control (pre-existing test_snake_case_detection case):
        a text unit that IS a snake_case identifier, with nothing else in it,
        must remain protected."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        para = paragraph_node([text_node("aspose_slides_low_code")])
        para.assign_addresses("body.paragraph[0]")

        plan = extractor.extract_from_ast([para])

        assert plan.units[0].do_not_translate is True
