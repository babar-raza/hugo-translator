import logging
from types import SimpleNamespace

from src.translation_engine.extractor.same_as_source_resolution import classify_unit
from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter
from src.translation_engine.segment_translator import (
    _allow_legacy_ast_fallback,
    _effective_same_as_source_tolerance,
    _has_translatable_residue,
    _is_reviewed_identical_translation,
    _same_as_source_fingerprints,
    _unapplied_frontmatter_keys,
)
from src.workers.autonomous_content_translation_worker import (
    _CampaignMetadataOnlyLogFilter,
)


def test_zero_defect_same_as_source_tolerance_is_always_zero():
    assert _effective_same_as_source_tolerance(0.10, "zero-defect") == 0.0
    assert _effective_same_as_source_tolerance(0.03, "zero-defect") == 0.0
    assert _effective_same_as_source_tolerance(0.10, "standard") == 0.10


def test_zero_defect_prohibits_legacy_ast_fallback():
    assert _allow_legacy_ast_fallback("zero-defect") is False
    assert _allow_legacy_ast_fallback("standard") is True


def test_reviewed_identical_translation_is_locale_scoped():
    assert _is_reviewed_identical_translation("Introduction", "fr")
    assert _is_reviewed_identical_translation(" INTRODUCTION ", "fr")
    assert _is_reviewed_identical_translation("conditions.", "fr")
    assert not _is_reviewed_identical_translation("Introduction", "es")
    assert not _is_reviewed_identical_translation("conditions.", "de")
    assert not _is_reviewed_identical_translation("Getting Started", "fr")
    # TC-SAS-01 cognate blind spot: "Annotations" is spelled identically in
    # French; it hard-failed the identical heading on two source pages.
    assert _is_reviewed_identical_translation("Annotations", "fr")
    assert not _is_reviewed_identical_translation("Annotations", "de")


def test_same_as_source_diagnostics_are_hashes_not_payloads():
    unit = type(
        "Unit",
        (),
        {"kind": "link_text", "source_text": "SECRET SOURCE UNIT"},
    )()

    metadata = _same_as_source_fingerprints([unit])

    assert metadata.startswith("link_text:")
    assert metadata.endswith(":18")
    assert "SECRET" not in metadata


def test_sas_masks_governed_format_in_malformed_table_fragment():
    """TC-SAS-01 regression for format-support's recorded 17-char unit.

    The source has an interrupted table, so this row is parsed as text rather
    than a TABLE_CELL_TEXT.  The registered glTF identifier and table syntax
    leave no human-language residue to translate.
    """
    assert not _has_translatable_residue("| \u2014 | | glTF    |", [])


def test_sas_does_not_mask_real_prose_adjacent_to_governed_format():
    assert _has_translatable_residue("Use glTF for this interactive scene.", [])


def test_shared_sas_classifier_allows_only_governed_identical_text():
    governed = SimpleNamespace(source_text="| — | | glTF    |", do_not_translate=False)
    prose = SimpleNamespace(
        source_text="Use glTF for this interactive scene.", do_not_translate=False
    )
    protected = SimpleNamespace(source_text="{{< shortcode >}}", do_not_translate=True)

    assert classify_unit(governed, target_lang="de", preserve_patterns=[])[0] == "allowed_identical"
    assert classify_unit(protected, target_lang="de", preserve_patterns=[])[0] == "allowed_identical"
    assert classify_unit(prose, target_lang="de", preserve_patterns=[])[0] == "requires_translation"


def test_duplicate_frontmatter_segments_accept_the_rendered_authoritative_value():
    expected = {"summary": ["duplicate stale value", "authoritative value"]}
    assert (
        _unapplied_frontmatter_keys(
            expected,
            {"summary": "authoritative value"},
            YAMLFormatter(),
        )
        == []
    )


def test_unapplied_frontmatter_field_is_reported_without_candidate_text():
    expected = {"summary": ["secret rejected candidate"]}
    assert _unapplied_frontmatter_keys(expected, {"summary": "source"}, YAMLFormatter()) == [
        "summary"
    ]


def test_frontmatter_application_check_precedes_governed_scalar_cleanup():
    frontmatter = {"summary": "translated summary#"}
    expected = {"summary": ["translated summary#"]}
    formatter = YAMLFormatter()

    assert _unapplied_frontmatter_keys(expected, frontmatter, formatter) == []
    formatter.format_frontmatter(frontmatter)
    assert _unapplied_frontmatter_keys(expected, frontmatter, formatter) == ["summary"]


def test_campaign_log_filter_replaces_message_and_traceback_payloads():
    record = logging.LogRecord(
        "translator.candidate",
        logging.ERROR,
        __file__,
        1,
        "rejected candidate text: %s",
        ("highly sensitive payload",),
        (ValueError, ValueError("candidate in exception"), None),
        "translate",
    )
    assert _CampaignMetadataOnlyLogFilter().filter(record)
    rendered = record.getMessage()
    assert rendered.startswith("campaign_event ")
    assert "sensitive" not in rendered
    assert "candidate in exception" not in rendered
    assert record.exc_info is None
