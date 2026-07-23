"""Tests for the canonical classifier (TC-HT-I18N-001/005).

Mission heading-i18n-governance-20260723. See
src/translation_engine/terminology/classification.py's module docstring and
plan file glittery-waddling-moth.md §1/§7 for the incident this closes.
"""

from __future__ import annotations

import json

import pytest
import yaml
from pydantic import ValidationError

from src.translation_engine.terminology.classification import (
    ProtectedTerms,
    TemplateStringRegistry,
    VERDICT_NOT_APPLICABLE,
    VERDICT_PROTECT,
    VERDICT_TABLE,
    VERDICT_UNRESOLVED,
    classify,
    validate_locale_file,
    validate_registry_file,
)


@pytest.fixture
def registry_dir(tmp_path):
    d = tmp_path / "template_strings"
    d.mkdir()
    (d / "_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "id": "heading.overview",
                        "en": "Overview",
                        "category": "section_heading",
                        "status": "approved",
                        "evidence_count": 13622,
                    },
                    {
                        "id": "heading.properties",
                        "en": "Properties",
                        "category": "table_header",
                        "status": "pending",
                        "evidence_count": 6500,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (d / "ja.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "locale": "ja",
                "translations": {
                    "heading.overview": {
                        "value": "概要",
                        "reviewed_by": "agent:terminology-reviewer",
                        "evidence_count": 456,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (d / "zh.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "locale": "zh", "translations": {}}),
        encoding="utf-8",
    )
    return d


@pytest.fixture
def protected_terms_file(tmp_path):
    p = tmp_path / "terminology.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "global": {
                    "exact_matches": [
                        {"term": "Aspose", "category": "company_name"},
                        {"term": "Body", "category": "api_type"},
                        {"term": "Cell", "category": "api_type"},
                        {"term": "Camera", "category": "api_type"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def registry(registry_dir):
    return TemplateStringRegistry(registry_dir)


@pytest.fixture
def protected(protected_terms_file):
    return ProtectedTerms(protected_terms_file)


def _classify(text, locale, registry, protected, log_calls):
    def _capture(term, loc, *, file, context, log_path):
        log_calls.append((term, loc, file, context))

    return classify(
        text,
        locale,
        registry=registry,
        protected_terms=protected,
        log_unresolved_fn=_capture,
    )


class TestGoldenList:
    """The 10-item golden list from TC-HT-I18N-001's acceptance_criteria."""

    def test_table_hit_translates(self, registry, protected):
        log_calls = []
        result = _classify("Overview", "ja", registry, protected, log_calls)
        assert result.verdict == VERDICT_TABLE
        assert result.value == "概要"
        assert log_calls == []

    def test_pending_entry_is_not_a_table_hit(self, registry, protected):
        # "Properties" is status: pending in the fixture registry — must NOT
        # be treated as translate_via_table even though it's a registry id.
        log_calls = []
        result = _classify("Properties", "ja", registry, protected, log_calls)
        assert result.verdict != VERDICT_TABLE

    def test_missing_locale_translation_falls_through(self, registry, protected):
        # "Overview" is approved but zh.yaml has no translation for it yet.
        log_calls = []
        result = _classify("Overview", "zh", registry, protected, log_calls)
        assert result.verdict != VERDICT_TABLE

    @pytest.mark.parametrize("identifier", ["Body", "Cell", "Camera"])
    def test_known_single_hump_identifiers_stay_protected(self, identifier, registry, protected):
        log_calls = []
        result = _classify(identifier, "ja", registry, protected, log_calls)
        assert result.verdict == VERDICT_PROTECT
        assert result.reason == "protected_terms_hit"
        assert log_calls == []

    def test_multi_hump_identifier_protected_by_shape_alone(self, registry, protected):
        log_calls = []
        result = _classify("ImageRenderOptions", "ja", registry, protected, log_calls)
        assert result.verdict == VERDICT_PROTECT
        assert result.reason == "multi_hump_identifier_shape"
        assert log_calls == []

    def test_unseen_single_hump_word_is_unresolved_and_logged(self, registry, protected):
        log_calls = []
        result = _classify("Values", "ja", registry, protected, log_calls)
        assert result.verdict == VERDICT_UNRESOLVED
        assert log_calls == [("Values", "ja", None, None)]

    def test_not_identifier_shaped_text_is_not_applicable(self, registry, protected):
        log_calls = []
        result = _classify("this is ordinary prose.", "ja", registry, protected, log_calls)
        assert result.verdict == VERDICT_NOT_APPLICABLE
        assert log_calls == []

    def test_lowercase_start_is_not_applicable(self, registry, protected):
        log_calls = []
        result = _classify("overview", "ja", registry, protected, log_calls)
        assert result.verdict == VERDICT_NOT_APPLICABLE


class TestDiscoveryLog:
    def test_appends_one_line_with_expected_fields(self, registry, protected, tmp_path):
        log_path = tmp_path / "unresolved_terms.jsonl"
        classify(
            "Prerequisites",
            "uk",
            registry=registry,
            protected_terms=protected,
            file="reference.aspose.org/uk/pdf/net/Document.md",
            context="## Prerequisites",
            log_path=log_path,
        )
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record == {
            "term": "Prerequisites",
            "locale": "uk",
            "file": "reference.aspose.org/uk/pdf/net/Document.md",
            "context": "## Prerequisites",
        }

    def test_log_is_append_only_across_two_runs(self, registry, protected, tmp_path):
        log_path = tmp_path / "unresolved_terms.jsonl"
        classify(
            "Prerequisites", "uk", registry=registry, protected_terms=protected, log_path=log_path
        )
        classify("Steps", "uk", registry=registry, protected_terms=protected, log_path=log_path)
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["term"] == "Prerequisites"
        assert json.loads(lines[1])["term"] == "Steps"


class TestSchemaValidation:
    def test_valid_registry_file_parses(self, registry_dir):
        parsed = validate_registry_file(registry_dir / "_registry.yaml")
        assert parsed.schema_version == 1
        assert len(parsed.entries) == 2

    def test_valid_locale_file_parses(self, registry_dir):
        parsed = validate_locale_file(registry_dir / "ja.yaml")
        assert parsed.locale == "ja"
        assert "heading.overview" in parsed.translations

    def test_malformed_registry_category_rejected(self, tmp_path):
        bad = tmp_path / "bad_registry.yaml"
        bad.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "entries": [
                        {
                            "id": "heading.x",
                            "en": "X",
                            "category": "not_a_real_category",
                            "status": "approved",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            validate_registry_file(bad)

    def test_malformed_locale_file_missing_required_field_rejected(self, tmp_path):
        bad = tmp_path / "bad_locale.yaml"
        bad.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "locale": "ja",
                    # "value" missing inside the translation entry
                    "translations": {"heading.overview": {"reviewed_by": "agent:x"}},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            validate_locale_file(bad)


class TestCompletenessLint:
    def test_flags_approved_entry_missing_a_locale(self, registry):
        gaps = registry.completeness_gaps(["ja", "zh"])
        # "Overview" is approved and has ja but not zh -> exactly one gap.
        assert ("heading.overview", "zh") in gaps
        assert ("heading.overview", "ja") not in gaps

    def test_pending_entries_are_not_flagged(self, registry):
        gaps = registry.completeness_gaps(["ja", "zh"])
        assert not any(g[0] == "heading.properties" for g in gaps)
