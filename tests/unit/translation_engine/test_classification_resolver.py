"""Tests for the i18n-first resolver (mission reference-i18n-hardening-20260725).

Covers resolve()/is_translate_eligible()/normalize_for_registry() plus the
schema extensions (variants, placeholders, context, rejected_variants) and
the production-data completeness checks (plan item A5). The legacy
classify()/lookup() behavior is covered by test_classification.py — those
tests must keep passing unchanged (categories=None is byte-identical).
"""

from __future__ import annotations

import json

import pytest
import yaml
from pydantic import ValidationError

from src.translation_engine.terminology.classification import (
    CATEGORIES_FOR_KIND,
    ProtectedTerms,
    RegistryEntry,
    TemplateStringRegistry,
    VERDICT_NOT_APPLICABLE,
    categories_for_kind,
    classify,
    get_default_registry,
    is_translate_eligible,
    resolve,
    validate_locale_file,
    validate_registry_file,
)

_HEADING_CATS = CATEGORIES_FOR_KIND["heading_text"]
_CELL_CATS = CATEGORIES_FOR_KIND["table_cell_text"]


@pytest.fixture
def resolver_registry(tmp_path):
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
                    },
                    {
                        "id": "heading.see_also",
                        "en": "See Also",
                        "category": "section_heading",
                        "status": "approved",
                        "variants": ["See also"],
                    },
                    {
                        "id": "heading.methods",
                        "en": "Methods",
                        "category": "section_heading",
                        "status": "approved",  # ja value deliberately MISSING
                    },
                    {
                        "id": "heading.properties",
                        "en": "Properties",
                        "category": "table_header",
                        "status": "pending",
                    },
                    {
                        "id": "heading.legacy",
                        "en": "Legacy",
                        "category": "section_heading",
                        "status": "deprecated",
                    },
                    {
                        "id": "heading.namespace",
                        "en": "Namespace",
                        "category": "section_heading",
                        "status": "approved",
                    },
                    {
                        "id": "heading.cafe",
                        "en": "Café",
                        "category": "section_heading",
                        "status": "approved",
                    },
                    # Same EN text, two grammatical roles, two ids (CONTEXTUAL_I18N).
                    {
                        "id": "heading.description",
                        "en": "Description",
                        "category": "section_heading",
                        "status": "approved",
                    },
                    {
                        "id": "table.header.description",
                        "en": "Description",
                        "category": "table_header",
                        "status": "approved",
                    },
                    # Context-gated enum value.
                    {
                        "id": "table.access.read",
                        "en": "Read",
                        "category": "enum_value",
                        "status": "approved",
                        "context": {"column_header": "Access"},
                    },
                    # Parameterized phrase.
                    {
                        "id": "phrase.inherits_from",
                        "en": "Inherits from: {api}.",
                        "category": "param_phrase",
                        "status": "approved",
                        "placeholders": ["api"],
                    },
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (d / "ja.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "locale": "ja",
                "translations": {
                    "heading.overview": {"value": "概要", "reviewed_by": "t"},
                    "heading.see_also": {"value": "関連情報", "reviewed_by": "t"},
                    "heading.namespace": {"value": "名前空間", "reviewed_by": "t"},
                    "heading.cafe": {"value": "カフェ", "reviewed_by": "t"},
                    "heading.legacy": {"value": "レガシー", "reviewed_by": "t"},
                    "heading.description": {"value": "説明", "reviewed_by": "t"},
                    "table.header.description": {"value": "記述", "reviewed_by": "t"},
                    "table.access.read": {"value": "読み取り", "reviewed_by": "t"},
                    "phrase.inherits_from": {
                        "value": "{api} から継承します。",
                        "reviewed_by": "t",
                    },
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return TemplateStringRegistry(d)


class TestResolvePositive:
    def test_exact_heading_hit(self, resolver_registry):
        r = resolve("Overview", "ja", categories=_HEADING_CATS, registry=resolver_registry)
        assert (r.outcome, r.value, r.entry_id) == ("table", "概要", "heading.overview")

    def test_whitespace_and_nfc_normalization(self, resolver_registry):
        assert (
            resolve(
                "  Overview  ", "ja", categories=_HEADING_CATS, registry=resolver_registry
            ).value
            == "概要"
        )
        assert (
            resolve("See  Also", "ja", categories=_HEADING_CATS, registry=resolver_registry).value
            == "関連情報"
        )
        # Decomposed input (e + combining acute) matches the NFC-composed entry.
        assert (
            resolve("Café", "ja", categories=_HEADING_CATS, registry=resolver_registry).value
            == "カフェ"
        )

    def test_trailing_colon_reattached_losslessly(self, resolver_registry):
        r = resolve("Namespace:", "ja", categories=_HEADING_CATS, registry=resolver_registry)
        assert r.outcome == "table"
        assert r.value == "名前空間:"
        r_full = resolve(
            "Namespace：", "ja", categories=_HEADING_CATS, registry=resolver_registry
        )
        assert r_full.value == "名前空間："

    def test_approved_variant_resolves(self, resolver_registry):
        r = resolve("See also", "ja", categories=_HEADING_CATS, registry=resolver_registry)
        assert (r.outcome, r.value) == ("table", "関連情報")


class TestResolveNegativeControls:
    def test_case_is_significant(self, resolver_registry):
        r = resolve("overview", "ja", categories=_HEADING_CATS, registry=resolver_registry)
        assert r.outcome == "none"

    def test_trailing_period_is_a_miss(self, resolver_registry):
        r = resolve("Overview.", "ja", categories=_HEADING_CATS, registry=resolver_registry)
        assert r.outcome == "none"

    def test_identifier_never_resolves(self, resolver_registry):
        r = resolve(
            "ImageRenderOptions", "ja", categories=_HEADING_CATS, registry=resolver_registry
        )
        assert r.outcome == "none"

    def test_empty_categories_means_ineligible_frontmatter(self, resolver_registry):
        r = resolve("Overview", "ja", categories=frozenset(), registry=resolver_registry)
        assert (r.outcome, r.reason) == ("none", "ineligible_kind")

    def test_deprecated_entry_is_absent(self, resolver_registry):
        r = resolve("Legacy", "ja", categories=_HEADING_CATS, registry=resolver_registry)
        assert r.outcome == "none"

    def test_variant_validator_rejects_non_trivial_variant(self):
        with pytest.raises(ValidationError):
            RegistryEntry(
                id="heading.see_also",
                en="See Also",
                category="section_heading",
                status="approved",
                variants=["Related Links"],
            )


class TestResolveContextAndCategories:
    def test_enum_value_requires_column_context(self, resolver_registry):
        hit = resolve(
            "Read",
            "ja",
            categories=_CELL_CATS,
            registry=resolver_registry,
            context={"column_header": "Access"},
        )
        assert (hit.outcome, hit.value) == ("table", "読み取り")
        # Same cell text without the Access column context: not served.
        miss = resolve("Read", "ja", categories=_CELL_CATS, registry=resolver_registry)
        assert miss.outcome == "none"
        # "Read" as a HEADING (method name!) is never table-resolved.
        as_heading = resolve("Read", "ja", categories=_HEADING_CATS, registry=resolver_registry)
        assert as_heading.outcome == "none"

    def test_context_match_is_case_insensitive(self, resolver_registry):
        hit = resolve(
            "Read",
            "ja",
            categories=_CELL_CATS,
            registry=resolver_registry,
            context={"column_header": "access"},
        )
        assert hit.outcome == "table"

    def test_split_ids_same_en_text_diverge_by_category(self, resolver_registry):
        as_heading = resolve(
            "Description", "ja", categories=_HEADING_CATS, registry=resolver_registry
        )
        as_cell = resolve("Description", "ja", categories=_CELL_CATS, registry=resolver_registry)
        assert as_heading.entry_id == "heading.description"
        assert as_cell.entry_id == "table.header.description"
        assert as_heading.value == "説明"
        assert as_cell.value == "記述"

    def test_categories_for_kind_accepts_enum_or_string(self):
        from src.translation_engine.extractor.text_unit import TextUnitKind

        assert categories_for_kind(TextUnitKind.HEADING_TEXT) == _HEADING_CATS
        assert categories_for_kind("heading_text") == _HEADING_CATS
        assert categories_for_kind("code_span") == frozenset()


class TestResolveFallbackAndReporting:
    def test_approved_missing_locale_falls_through_with_one_deduped_event(
        self, resolver_registry, tmp_path
    ):
        log = tmp_path / "missing.jsonl"
        for _ in range(3):
            r = resolve(
                "Methods",
                "ja",
                categories=_HEADING_CATS,
                registry=resolver_registry,
                missing_key_log_path=log,
            )
            assert (r.outcome, r.reason) == ("fallthrough", "approved_missing_locale")
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1  # deduped per (entry_id, locale)
        record = json.loads(lines[0])
        assert record["entry_id"] == "heading.methods"
        assert record["locale"] == "ja"
        assert record["status"] == "approved"

    def test_pending_entry_falls_through_without_event(self, resolver_registry, tmp_path):
        log = tmp_path / "missing.jsonl"
        r = resolve(
            "Properties",
            "ja",
            categories=_CELL_CATS,
            registry=resolver_registry,
            missing_key_log_path=log,
        )
        assert (r.outcome, r.reason) == ("fallthrough", "pending_entry")
        assert not log.exists()

    def test_classify_maps_fallthrough_to_not_applicable(self, resolver_registry, tmp_path):
        result = classify(
            "Methods",
            "ja",
            registry=resolver_registry,
            protected_terms=ProtectedTerms(tmp_path / "no_terms.yaml"),
            categories=_HEADING_CATS,
        )
        # Translate-eligible: NOT protected, NOT unresolved-logged -- the
        # ordinary TM/MT path proceeds.
        assert result.verdict == VERDICT_NOT_APPLICABLE
        assert result.reason == "i18n_approved_missing_locale"


class TestParameterizedPhrases:
    def test_substitution_inserts_identifier_verbatim(self, resolver_registry):
        r = resolve(
            "Inherits from: `MeshBuilder`.",
            "ja",
            categories=frozenset({"param_phrase"}),
            registry=resolver_registry,
        )
        assert r.outcome == "table"
        assert r.reason == "param_hit"
        assert r.value == "`MeshBuilder` から継承します。"

    def test_no_match_for_multiline_capture(self, resolver_registry):
        r = resolve(
            "Inherits from: `A`\n`B`.",
            "ja",
            categories=frozenset({"param_phrase"}),
            registry=resolver_registry,
        )
        assert r.outcome == "none"

    def test_placeholder_token_mismatch_in_locale_value_is_dropped_at_load(self, tmp_path):
        d = tmp_path / "ts"
        d.mkdir()
        (d / "_registry.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "entries": [
                        {
                            "id": "phrase.inherits_from",
                            "en": "Inherits from: {api}.",
                            "category": "param_phrase",
                            "status": "approved",
                            "placeholders": ["api"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (d / "de.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "locale": "de",
                    # {api} token translated away -- unusable, must be dropped.
                    "translations": {
                        "phrase.inherits_from": {
                            "value": "Erbt von der API.",
                            "reviewed_by": "t",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        reg = TemplateStringRegistry(d)
        assert reg.load_errors  # recorded, not silently served
        r = resolve(
            "Inherits from: `Scene`.",
            "de",
            categories=frozenset({"param_phrase"}),
            registry=reg,
        )
        assert r.outcome == "fallthrough"

    def test_registry_entry_validator_enforces_token_parity(self):
        with pytest.raises(ValidationError):
            RegistryEntry(
                id="phrase.bad",
                en="Inherits from: {api}.",
                category="param_phrase",
                status="approved",
                placeholders=["type_name"],  # != en tokens
            )


class TestIsTranslateEligible:
    def test_registry_terms_are_eligible(self, resolver_registry):
        assert is_translate_eligible("Overview", _HEADING_CATS, registry=resolver_registry)
        # Pending entries are still eligible (send to MT, never protect).
        assert is_translate_eligible("Properties", _CELL_CATS, registry=resolver_registry)
        assert is_translate_eligible("Namespace:", _HEADING_CATS, registry=resolver_registry)

    def test_category_scope_and_identifiers_are_not_eligible(self, resolver_registry):
        # enum_value never eligible under heading categories.
        assert not is_translate_eligible("Read", _HEADING_CATS, registry=resolver_registry)
        assert not is_translate_eligible(
            "ImageRenderOptions", _HEADING_CATS, registry=resolver_registry
        )
        assert not is_translate_eligible("Legacy", _HEADING_CATS, registry=resolver_registry)


class TestParamMatcherRepeatedToken:
    """reference-i18n-hardening-20260725: a template with the SAME
    placeholder token appearing twice (e.g. phrase.
    members_accessible_after_install's `{platform}` used both for "any
    {platform} application" and "for {platform} package") must compile --
    naively emitting a second `(?P<platform>...)` group raises
    `re.error: redefinition of group name`. The fix uses a backreference
    for repeat occurrences, which is also semantically correct: both
    occurrences must be the identical literal value."""

    def test_repeated_token_template_compiles_and_matches(self, tmp_path):
        d = tmp_path / "ts"
        d.mkdir()
        (d / "_registry.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "entries": [
                        {
                            "id": "phrase.repeat",
                            "en": "any {platform} app for {platform} package.",
                            "category": "param_phrase",
                            "status": "approved",
                            "placeholders": ["platform"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (d / "de.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "locale": "de",
                    "translations": {
                        "phrase.repeat": {
                            "value": "beliebige {platform}-Anwendung fuer {platform}-Paket.",
                            "reviewed_by": "t",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        reg = TemplateStringRegistry(d)
        assert reg.load_errors == []
        r = resolve(
            "any .NET app for .NET package.",
            "de",
            categories=frozenset({"param_phrase"}),
            registry=reg,
        )
        assert r.outcome == "table"
        assert r.value == "beliebige .NET-Anwendung fuer .NET-Paket."

    def test_mismatched_repeated_value_does_not_match(self, tmp_path):
        d = tmp_path / "ts"
        d.mkdir()
        (d / "_registry.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "entries": [
                        {
                            "id": "phrase.repeat",
                            "en": "any {platform} app for {platform} package.",
                            "category": "param_phrase",
                            "status": "approved",
                            "placeholders": ["platform"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        reg = TemplateStringRegistry(d)
        # Two DIFFERENT platform values in the same sentence -- must not
        # match (the backreference requires an identical literal repeat).
        r = resolve(
            "any .NET app for Java package.",
            "de",
            categories=frozenset({"param_phrase"}),
            registry=reg,
        )
        assert r.outcome != "table"


class TestProductionRegistryData:
    """Production-data checks (plan item A5): the shipped
    config/i18n/template_strings/ must load cleanly and completely for what
    it claims to serve."""

    def test_production_files_load_without_errors_and_validate(self):
        reg = get_default_registry()
        assert reg.load_errors == []
        registry_dir = reg.directory
        validate_registry_file(registry_dir / "_registry.yaml")
        for locale_file in sorted(registry_dir.glob("*.yaml")):
            if locale_file.name != "_registry.yaml":
                validate_locale_file(locale_file)

    def test_completeness_gaps_are_all_documented_adjudication_disagreements(self):
        """Not a zero-gaps assertion: mission reference-i18n-hardening-
        20260725's full-scale adjudication (36 locales x 42 entries, with
        adversarial cross-check) deliberately leaves a term PENDING for a
        given locale when two independent reviewers disagreed and neither
        was clearly right -- "never force a tie-break guess" is the
        design, not a bug (see adjudication/disagreements.md). A gap is
        only a problem if it is UNEXPLAINED; this test proves every
        completeness gap traces to a recorded disagreement, i.e. nothing
        silently fell through the cracks. resolve()'s own fallback design
        (approved+missing-locale -> fallthrough to TM/MT + a reported
        missing-key event, never silently protected or silently English)
        is what makes shipping with a documented, bounded gap set safe."""
        reg = get_default_registry()
        shipped_locales = sorted(reg.translations.keys())
        assert shipped_locales, "no locale files found next to _registry.yaml"
        gaps = reg.completeness_gaps(shipped_locales)

        pending_path = (
            reg.directory.parent.parent.parent
            / "reports"
            / "agents"
            / "reference-i18n-hardening-20260725"
            / "adjudication"
            / "pending_pairs.json"
        )
        if not pending_path.exists():
            assert gaps == []
            return
        documented = {(p["locale"], p["id"]) for p in json.loads(pending_path.read_text(encoding="utf-8"))}
        undocumented = [g for g in gaps if (g[1], g[0]) not in documented]
        assert undocumented == [], f"unexplained completeness gaps: {undocumented}"

    def test_locale_value_equals_english_only_for_deliberate_cognates(self):
        # NOT a healer-idempotency bug: the targeted healer's leakage check
        # is `value != stripped`, so a value coincidentally identical to the
        # EN term is already a correct no-op there, not a corruption signal.
        # Mission reference-i18n-hardening-20260725's full-scale adjudication
        # (36 locales) surfaced ~20 genuine cases where the correct technical
        # term IS spelled identically to English -- true Latin/international
        # cognates (fr/es/pt "Interfaces", fr "Description"/"Type"/
        # "Signature", de/nl "Name"/"Structs", ca "Constructors"/"Classes",
        # da/no "Type", da/sv "Enumeration") -- several explicitly marked
        # corpus_agreement=override, i.e. the reviewer deliberately chose
        # this form against corpus evidence, not a lazy passthrough. This
        # test only guards against an UNREVIEWED/unattributed same-as-English
        # value slipping in (missing reviewed_by), which WOULD indicate an
        # untranslated placeholder rather than a considered cognate decision.
        reg = get_default_registry()
        offenders = []
        for locale, translations in reg.translations.items():
            for entry_id, raw in translations.items():
                if not isinstance(raw, dict):
                    continue
                value = raw.get("value")
                entry = reg.entries.get(entry_id) or {}
                if (
                    value
                    and entry.get("en")
                    and value.strip() == entry["en"].strip()
                    and not raw.get("reviewed_by")
                ):
                    offenders.append((locale, entry_id, value))
        assert offenders == []
