"""TC-APT-108 (wave-cellsrust-go-t1a): "Issue" and "Cause" table-header cells
were left untranslated in every reviewed locale (25/25) while the sibling
"Fix" header in the same row translated correctly.

Root cause: text_unit_extractor.py's `_is_non_translatable` checks the i18n
template-string registry first (`is_translate_eligible`) and only falls back
to the legacy PascalCase-shape heuristic (`_is_technical_identifier`) when no
registry entry exists. "Issue" (5 letters) and "Cause" (5 letters) both
match that heuristic's single-hump pattern (capital + 3+ lowercase) with no
registry entry to short-circuit it first, so they were classified
do_not_translate=True and copied verbatim into every locale -- exactly the
same shape as real API identifiers like "Workbook", which the heuristic is
designed to protect. "Fix" (2 lowercase chars after the capital) falls below
the heuristic's floor and was never protected, which is why it alone
translated correctly.

Fix: added table.header.issue / table.header.cause entries to
config/i18n/template_strings/_registry.yaml (category=table_header,
status=pending) plus a value for each of the 25 mission target locales.
This is the same curated-registry mechanism that already protects
"Description" from the identical heuristic (config/i18n/template_strings/
_registry.yaml: table.header.description) -- these tests confirm the
mechanism resolves for the two new entries the same way.
"""

from src.translation_engine.terminology.classification import (
    categories_for_kind,
    get_default_registry,
    is_translate_eligible,
)

TABLE_CELL_CATEGORIES = categories_for_kind("table_cell_text")


def test_issue_is_now_translate_eligible_as_a_table_header():
    assert is_translate_eligible("Issue", TABLE_CELL_CATEGORIES) is True


def test_cause_is_now_translate_eligible_as_a_table_header():
    assert is_translate_eligible("Cause", TABLE_CELL_CATEGORIES) is True


def test_issue_and_cause_are_not_eligible_outside_table_header_categories():
    """The registry entries are category=table_header -- they must not make
    "Issue"/"Cause" translate-eligible in unrelated contexts (e.g. as an
    enum_value-only category set), which would be a different, unintended
    behavior change."""
    enum_only = frozenset({"enum_value"})
    assert is_translate_eligible("Issue", enum_only) is False
    assert is_translate_eligible("Cause", enum_only) is False


def test_registry_entries_exist_with_the_expected_shape():
    reg = get_default_registry()
    for entry_id, expected_en in (
        ("table.header.issue", "Issue"),
        ("table.header.cause", "Cause"),
    ):
        entry = reg.entries.get(entry_id)
        assert entry is not None, f"missing registry entry {entry_id}"
        assert entry["en"] == expected_en
        assert entry["category"] == "table_header"
        assert entry["status"] != "deprecated"


def test_all_25_mission_locales_have_a_value_for_both_entries():
    reg = get_default_registry()
    mission_locales = [
        "ar", "cs", "de", "el", "es", "fa", "fr", "he", "hi", "hu",
        "id", "it", "ja", "ko", "nl", "pl", "pt", "ro", "ru", "sv",
        "th", "tr", "uk", "vi", "zh",
    ]
    for locale in mission_locales:
        locale_table = reg.translations.get(locale, {})
        for entry_id in ("table.header.issue", "table.header.cause"):
            entry = locale_table.get(entry_id)
            assert entry is not None, f"{locale} has no entry for {entry_id}"
            assert entry.get("value"), f"{locale}/{entry_id} has an empty value"


def test_registry_has_no_load_errors():
    """Guards against a malformed YAML entry (schema violation, param-phrase
    token mismatch, etc.) silently degrading to 'entry dropped' rather than
    failing the test suite."""
    reg = get_default_registry()
    assert reg.load_errors == []


def test_the_sibling_fix_header_still_falls_through_unaffected():
    """Regression control: "Fix" was never protected in the first place
    (too short to match the legacy heuristic) -- confirm this fix didn't
    change that."""
    assert is_translate_eligible("Fix", TABLE_CELL_CATEGORIES) is False


def test_description_is_still_eligible_the_same_way_it_always_was():
    """Regression control: the pre-existing table.header.description entry
    must be unaffected by this change."""
    assert is_translate_eligible("Description", TABLE_CELL_CATEGORIES) is True
