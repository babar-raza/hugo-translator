"""Regression control for the english_headings_nonlatin incident
(mission heading-i18n-governance-20260723, taskcard TC-HT-I18N-006).

Three layers:
1. A golden list run against the REAL production
   config/i18n/template_strings/ + config/terminology.yaml (not a fixture) —
   catches drift in the actual shipped data, not just the classifier code.
2. An end-to-end TextUnitExtractor test proving the i18n short-circuit
   actually bypasses translation for a table hit (the strongest possible
   guarantee: not "output looks right" but "this code path cannot vary").
3. A single-source-of-truth lint: fails if a second copy of the identifier
   regex/allow-list appears outside classification.py. As of TC-HT-I18N-004's
   completion pass, write_gate.py, tm_surgical_cleanup.py,
   heal_english_headings.py, and surgical_retranslate.py are all unified --
   only text_unit_extractor.py remains, a deliberately-deferred exception
   with a named, evidence-backed reason (see _KNOWN_DEFERRED_DUPLICATES).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.terminology.classification import (
    VERDICT_PROTECT,
    VERDICT_TABLE,
    ProtectedTerms,
    TemplateStringRegistry,
    classify,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 1. Golden list against the real, shipped production data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def production_registry():
    return TemplateStringRegistry(REPO_ROOT / "config" / "i18n" / "template_strings")


@pytest.fixture(scope="module")
def production_protected_terms():
    return ProtectedTerms(REPO_ROOT / "config" / "terminology.yaml")


GOLDEN_HEADINGS = [
    # (text, locale, expected_value) -- must resolve via the i18n table.
    ("Overview", "ja", "概要"),
    ("Overview", "zh", "概述"),
    ("Overview", "ru", "Обзор"),
    ("Properties", "uk", "Властивості"),  # genuinely Ukrainian, not Russian-contaminated
    ("Methods", "ar", "الطرق"),
    ("See Also", "he", "ראה גם"),
]

GOLDEN_IDENTIFIERS = [
    # Real identifiers this classifier must never translate, regardless of
    # locale -- multi-hump PascalCase is protected by shape alone.
    "ImageRenderOptions",
    "ColladaSaveOptions",
    "GltfSaveOptions",
]


class TestGoldenListAgainstProductionData:
    @pytest.mark.parametrize("text,locale,expected", GOLDEN_HEADINGS)
    def test_known_heading_resolves_via_table(
        self, text, locale, expected, production_registry, production_protected_terms
    ):
        result = classify(
            text, locale, registry=production_registry, protected_terms=production_protected_terms
        )
        assert result.verdict == VERDICT_TABLE
        assert result.value == expected

    @pytest.mark.parametrize("identifier", GOLDEN_IDENTIFIERS)
    def test_multi_hump_identifier_always_protected(
        self, identifier, production_registry, production_protected_terms
    ):
        # Locale is irrelevant here -- shape alone decides multi-hump identifiers.
        result = classify(
            identifier,
            "ja",
            registry=production_registry,
            protected_terms=production_protected_terms,
        )
        assert result.verdict == VERDICT_PROTECT
        assert result.reason == "multi_hump_identifier_shape"


# ---------------------------------------------------------------------------
# 2. End-to-end: the extractor really bypasses the model for a table hit
# ---------------------------------------------------------------------------


def _heading_node(text: str, node_addr: str = "heading[0]") -> ASTNode:
    text_child = ASTNode(type=NodeType.TEXT, raw=text, node_addr=f"{node_addr}.text[0]")
    return ASTNode(type=NodeType.HEADING, children=[text_child], node_addr=node_addr)


class TestExtractorBypassesTheModel:
    def test_table_hit_heading_is_preresolved_not_sent_to_mt(self):
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", target_lang="ja")
        units: list = []
        extractor._extract_full_sentence(_heading_node("Overview"), units)

        assert len(units) == 1
        unit = units[0]
        assert unit.do_not_translate is True
        assert unit.translated_text == "概要"

        # This is the actual guarantee: batch_translate_units()/segment_translator's
        # existing "already has translated_text" skip (built for LLM-prefilled
        # units) means this unit is excluded from get_translatable_units() and
        # from the units MT would ever see -- not by convention, by construction.
        from src.translation_engine.extractor.text_unit import BodyTranslationPlan

        plan = BodyTranslationPlan(ast=[], units=units, ast_fingerprint="test")
        assert unit not in plan.get_translatable_units()
        units_needing_mt = [
            u for u in plan.units if not u.do_not_translate and not u.translated_text
        ]
        assert units_needing_mt == []

    def test_no_target_lang_disables_table_lookup_entirely(self):
        # Backward compatibility: a caller that never passes target_lang
        # (target_lang=None, the default) must see unchanged prior behavior --
        # no table lookup attempted at all.
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        units: list = []
        extractor._extract_full_sentence(_heading_node("Overview"), units)

        assert len(units) == 1
        assert units[0].translated_text is None

    def test_real_identifier_heading_is_not_preresolved(self):
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", target_lang="ja")
        units: list = []
        extractor._extract_full_sentence(_heading_node("ImageRenderOptions"), units)

        assert len(units) == 1
        unit = units[0]
        assert unit.translated_text is None
        assert unit.do_not_translate is True  # protected by the existing PascalCase heuristic


class TestExtractorDiscoveryLogging:
    """TC-HT-I18N-005: an unresolved single-hump word flowing through the
    REAL extractor path (not just classify() in isolation) must append
    exactly one discovery-log line with locale + context populated."""

    def test_unresolved_word_logged_with_locale_and_context(self, tmp_path, monkeypatch):
        import src.translation_engine.terminology.classification as classification_module

        log_path = tmp_path / "unresolved.jsonl"
        monkeypatch.setattr(classification_module, "DEFAULT_DISCOVERY_LOG", log_path)

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", target_lang="uk")
        units: list = []
        extractor._extract_full_sentence(_heading_node("Prerequisites"), units)

        assert units[0].translated_text is None
        assert units[0].do_not_translate is True  # default-protect direction
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        import json

        record = json.loads(lines[0])
        assert record["term"] == "Prerequisites"
        assert record["locale"] == "uk"
        assert record["context"] == "heading[0]"


# ---------------------------------------------------------------------------
# 3. Single-source-of-truth lint
# ---------------------------------------------------------------------------

_IDENTIFIER_REGEX_SHAPES = [
    re.compile(r"\^\[A-Z\]\[a-zA-Z0-9_\.\]\+\$"),  # the retired write_gate.py / tm_surgical_cleanup.py shape
    # Fingerprint of the actual hardcoded 20-term list itself (three
    # consecutive literal entries, tolerant of the newline/indentation
    # variants the four original copies used) -- NOT a name-based check
    # like `_API_HEADING_TERMS = frozenset(...)`, because every one of
    # those four files now legitimately assigns a registry-derived set to a
    # variable of that same name (TC-HT-I18N-004 completion); a name-based
    # regex would false-positive on the fix itself. This only fires if
    # someone re-pastes the literal list somewhere new.
    re.compile(r'"Description",\s*"Returns",\s*"Parameters"'),
]

_CANONICAL_MODULE = REPO_ROOT / "src" / "translation_engine" / "terminology" / "classification.py"

# As of TC-HT-I18N-004's completion pass, all four previously-duplicated
# OFFLINE copies (write_gate.py's two _IDENTIFIER_RE sites,
# tm_surgical_cleanup.py's Rule 1 + Rule 3, heal_english_headings.py's and
# surgical_retranslate.py's _API_HEADING_TERMS) were unified to read from
# the canonical TemplateStringRegistry instead of a locally-hardcoded
# literal.
#
# text_unit_extractor.py deliberately remains: its own _API_HEADING_TERMS
# (39 terms) and _ALWAYS_TRANSLATE_WORDS (6 terms: Read, Write, Execute,
# Create, Delete, Update) gate `_is_non_translatable` on the hottest live
# code path in the system (evaluated per text unit on every translation
# call). _API_HEADING_TERMS alone is a safe registry subset, but
# _ALWAYS_TRANSLATE_WORDS is NOT: "Execute"/"Create"/"Delete"/"Update" have
# no registry entry at all today, so a same-pass swap would silently drop
# them back through the over-broad PascalCase heuristic -- reintroducing
# this exact mission's root-cause bug for those four words. Fixing this
# safely means first backfilling those 4 terms into the registry (a
# TC-HT-I18N-003-style data-completeness step), which is out of scope for
# this mechanical dedup pass and deliberately deferred rather than risked
# un-scoped on the live hot path.
_KNOWN_DEFERRED_DUPLICATES = {
    REPO_ROOT / "src" / "translation_engine" / "extractor" / "text_unit_extractor.py",
}


def _files_with_duplicate_shape() -> set[Path]:
    hits = set()
    for path in (REPO_ROOT / "src").rglob("*.py"):
        if path == _CANONICAL_MODULE:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(rx.search(text) for rx in _IDENTIFIER_REGEX_SHAPES):
            hits.add(path)
    for path in (REPO_ROOT / "scripts").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(rx.search(text) for rx in _IDENTIFIER_REGEX_SHAPES):
            hits.add(path)
    return hits


class TestSingleSourceOfTruthLint:
    def test_no_unexpected_new_duplicate_identifier_regex(self):
        """This is the mechanical guardrail against 'fixed in one place, still
        broken in the other four' (plan §1's structural-weakness finding).
        It does NOT require zero duplicates today -- text_unit_extractor.py's
        holdout is a deliberately deferred, explicitly justified exception
        (see _KNOWN_DEFERRED_DUPLICATES's comment) -- but it DOES fail if a
        *new, unexpected* duplicate appears anywhere else, which is the
        regression this guards against."""
        hits = _files_with_duplicate_shape()
        unexpected = hits - _KNOWN_DEFERRED_DUPLICATES
        assert unexpected == set(), (
            f"New identifier-regex duplicate(s) found outside the canonical "
            f"module and the known-deferred list: {sorted(str(p) for p in unexpected)}. "
            f"Either import from classification.py instead, or add to "
            f"_KNOWN_DEFERRED_DUPLICATES with a reason if this is intentional."
        )

    def test_offline_tool_duplicates_are_fully_eliminated(self):
        """TC-HT-I18N-004 completion (was previously xfail(strict=True) --
        now a real, hard assertion): write_gate.py (both sites),
        tm_surgical_cleanup.py (Rule 1 and Rule 3), heal_english_headings.py,
        and surgical_retranslate.py no longer carry a hardcoded duplicate of
        the identifier-shape regex or the heading-term list -- all four now
        read from the canonical TemplateStringRegistry. text_unit_extractor.py
        is the one remaining, deliberately-deferred holdout (see
        _KNOWN_DEFERRED_DUPLICATES's comment on why it's higher-risk than a
        same-pass mechanical dedup). Asserting equality (not emptiness)
        against that named set means a future fix there -- or a fresh,
        unrelated duplicate appearing -- both require deliberately touching
        this test, rather than either silently passing or silently going
        unnoticed."""
        hits = _files_with_duplicate_shape()
        assert hits == _KNOWN_DEFERRED_DUPLICATES, (
            f"Expected exactly the known-deferred holdout "
            f"{sorted(str(p) for p in _KNOWN_DEFERRED_DUPLICATES)}, got "
            f"{sorted(str(p) for p in hits)}. If text_unit_extractor.py has "
            f"just been fixed, update _KNOWN_DEFERRED_DUPLICATES too. If this "
            f"is a new duplicate, remove it instead."
        )
