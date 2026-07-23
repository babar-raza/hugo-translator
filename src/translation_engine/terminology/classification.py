"""Canonical protected-identifier / template-string classifier.

Mission: heading-i18n-governance-20260723 (successor to HT-QUALITY-GATES-001,
plan file C:\\Users\\prora\\.claude\\plans\\glittery-waddling-moth.md, taskcards
TC-HT-I18N-001/004/005/006).

This module is the single source of truth for "should this single/multi-word
capitalized text be translated via the i18n template-string table, protected
as an identifier, or left to the caller's own logic" — replacing five
previously-divergent, independently-maintained regex/allow-list copies
(text_unit_extractor.py's `_is_technical_identifier`, write_gate.py's two
`_IDENTIFIER_RE` sites, tm_surgical_cleanup.py's copy, and
terminology/discovery.py's `pascal_case` pattern).

Key design decision (see plan §1's prior-art finding): multi-hump PascalCase
(2+ segments, e.g. ``ImageRenderOptions``) is unambiguous and is protected by
shape alone. Single-hump capitalized words (``Overview``, ``Body``) are NOT
decided by shape — a single-hump-only regex was already tried both tightened
(2+ humps required) and loosened (1+ humps) in this codebase's history and
reverted each time, because shape alone cannot distinguish a common English
word used as a heading from one used as a real class name. Single-hump words
are resolved exclusively via the two curated sources below (the i18n table
and the protected-terms config); an unresolved single-hump word defaults to
"protect" (the safer failure direction) and is logged for later curation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml
from pydantic import BaseModel, Field, field_validator

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_DIR = _REPO_ROOT / "config" / "i18n" / "template_strings"
DEFAULT_TERMINOLOGY_YAML = _REPO_ROOT / "config" / "terminology.yaml"
DEFAULT_DISCOVERY_LOG = _REPO_ROOT / "data" / "discovery" / "unresolved_terms.jsonl"

# Unambiguous multi-hump PascalCase identifier shape (2+ segments) — matches
# the pattern write_gate.py's language-purity exclusion (line ~2698)
# independently already trusts for the same purpose.
_MULTI_HUMP_RE = re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+$")
# Single capitalized word (no spaces/punctuation) — the genuinely ambiguous
# shape this module never decides by regex alone.
_SINGLE_HUMP_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")

VERDICT_TABLE = "translate_via_table"
VERDICT_PROTECT = "protect"
VERDICT_UNRESOLVED = "unresolved"
VERDICT_NOT_APPLICABLE = "not_applicable"

_VALID_CATEGORIES = {"section_heading", "table_header", "enum_value"}
_VALID_STATUSES = {"approved", "pending", "deprecated"}


# ---------------------------------------------------------------------------
# Schema / validation (TC-HT-I18N-001 required_implementation)
# ---------------------------------------------------------------------------


class RegistryEntry(BaseModel):
    id: str
    en: str
    category: str
    status: str
    first_seen_incident: str | None = None
    evidence_count: int = 0

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        if v not in _VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(_VALID_CATEGORIES)}, got {v!r}")
        return v

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}, got {v!r}")
        return v


class RegistryFile(BaseModel):
    schema_version: int
    entries: list[RegistryEntry] = Field(default_factory=list)


class LocaleTranslationEntry(BaseModel):
    value: str
    reviewed_by: str
    reviewed_at: str | None = None
    evidence_count: int = 0


class LocaleFile(BaseModel):
    schema_version: int
    locale: str
    translations: dict[str, LocaleTranslationEntry] = Field(default_factory=dict)


def validate_registry_file(path: Path) -> RegistryFile:
    """Raise pydantic.ValidationError on a malformed registry file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return RegistryFile.model_validate(data)


def validate_locale_file(path: Path) -> LocaleFile:
    """Raise pydantic.ValidationError on a malformed locale file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return LocaleFile.model_validate(data)


# ---------------------------------------------------------------------------
# Registry + protected-terms loading
# ---------------------------------------------------------------------------


class TemplateStringRegistry:
    """Loads ``_registry.yaml`` + every per-locale file in the same directory."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else DEFAULT_REGISTRY_DIR
        self.entries: dict[str, dict] = {}
        self.by_en_text: dict[str, str] = {}
        self.translations: dict[str, dict[str, dict]] = {}
        self._load()

    def _load(self) -> None:
        registry_path = self.directory / "_registry.yaml"
        if registry_path.exists():
            data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
            for entry in data.get("entries", []) or []:
                self.entries[entry["id"]] = entry
                self.by_en_text[entry["en"]] = entry["id"]
        if not self.directory.exists():
            return
        for locale_file in sorted(self.directory.glob("*.yaml")):
            if locale_file.name == "_registry.yaml":
                continue
            locale = locale_file.stem
            data = yaml.safe_load(locale_file.read_text(encoding="utf-8")) or {}
            self.translations[locale] = data.get("translations", {}) or {}

    def lookup(self, text: str, locale: str) -> str | None:
        """Return the approved translation for ``text`` in ``locale``, or None."""
        entry_id = self.by_en_text.get(text)
        if entry_id is None:
            return None
        entry = self.entries.get(entry_id)
        if not entry or entry.get("status") != "approved":
            return None
        locale_map = self.translations.get(locale, {})
        value = locale_map.get(entry_id)
        if value is None:
            return None
        return value.get("value") if isinstance(value, dict) else value

    def completeness_gaps(self, locales: list[str]) -> list[tuple[str, str]]:
        """Return (id, locale) pairs for every *approved* entry missing a
        translation in a locale that should have one — the completeness lint
        required by TC-HT-I18N-001/003."""
        gaps: list[tuple[str, str]] = []
        for entry_id, entry in self.entries.items():
            if entry.get("status") != "approved":
                continue
            for locale in locales:
                locale_map = self.translations.get(locale, {})
                if entry_id not in locale_map or not locale_map[entry_id]:
                    gaps.append((entry_id, locale))
        return gaps


class ProtectedTerms:
    """Loads ``config/terminology.yaml``'s ``global.exact_matches`` as a
    protected-term set (the single canonical "never translate" source —
    ``config/terminology/protected_terms.yaml`` is a dead, unloaded path and
    is intentionally NOT read here)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DEFAULT_TERMINOLOGY_YAML
        self.terms: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        for entry in (data.get("global", {}) or {}).get("exact_matches", []) or []:
            term = entry.get("term")
            if term:
                self.terms.add(term)

    def __contains__(self, text: str) -> bool:
        return text in self.terms


# ---------------------------------------------------------------------------
# Discovery log (TC-HT-I18N-005's core emission, exercised standalone here)
# ---------------------------------------------------------------------------


def _default_log_unresolved(
    term: str,
    locale: str,
    *,
    file: str | None,
    context: str | None,
    log_path: Path | None,
) -> None:
    path = Path(log_path) if log_path else DEFAULT_DISCOVERY_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"term": term, "locale": locale, "file": file, "context": context}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Classification result + entry point
# ---------------------------------------------------------------------------


@dataclass
class ClassificationResult:
    verdict: str
    value: str | None = None
    reason: str = ""


def classify(
    text: str,
    locale: str,
    *,
    registry: TemplateStringRegistry | None = None,
    protected_terms: ProtectedTerms | None = None,
    file: str | None = None,
    context: str | None = None,
    log_path: Path | None = None,
    log_unresolved_fn: Callable[..., None] = _default_log_unresolved,
) -> ClassificationResult:
    """Classify a single text unit for translation-vs-protection purposes.

    Returns a :class:`ClassificationResult` with one of four verdicts:

    - ``translate_via_table``: an approved i18n template-string hit for this
      locale — use ``result.value`` directly, skip MT and TM entirely. Checked
      FIRST, ahead of any shape heuristic: a reviewed table entry is the most
      specific signal available and isn't restricted to single-word text —
      mining real corpus data (TC-HT-I18N-002) found many high-repetition
      MULTI-WORD phrase headings too (e.g. "Common Issues and Fixes", "API
      Reference Summary"), which are never identifier-shaped (no real class
      name has spaces) but are exactly the same "closed, repeated template
      string" problem this module exists to solve.
    - ``protect``: a confident multi-hump identifier, or a single-hump word
      found in the protected-terms config — never send to the model.
    - ``unresolved``: a single-hump capitalized word with no table entry and
      no protected-terms entry — a first-sighting; defaults to the same
      "do not translate" behavior as ``protect`` (the safer failure
      direction) and is appended to the discovery log for later curation.
    - ``not_applicable``: ``text`` has no table entry and isn't
      single/multi-hump capitalized-word shaped either (contains spaces,
      punctuation, lowercase start, etc., AND no reviewed table entry exists
      for it yet) — this classifier has nothing to say; the caller's
      existing logic (terminology dict, signature detection, ordinary MT
      path, ...) continues to apply unchanged. Not logged — logging every
      non-heading text unit encountered across the whole corpus would drown
      the discovery log in noise for a case this module was never meant to
      adjudicate.
    """
    text_stripped = text.strip()

    reg = registry if registry is not None else TemplateStringRegistry()
    table_value = reg.lookup(text_stripped, locale)
    if table_value is not None:
        return ClassificationResult(VERDICT_TABLE, value=table_value, reason="table_hit")

    if _MULTI_HUMP_RE.match(text_stripped):
        return ClassificationResult(VERDICT_PROTECT, reason="multi_hump_identifier_shape")

    if not _SINGLE_HUMP_RE.match(text_stripped):
        return ClassificationResult(VERDICT_NOT_APPLICABLE, reason="not_identifier_shaped")

    prot = protected_terms if protected_terms is not None else ProtectedTerms()
    if text_stripped in prot:
        return ClassificationResult(VERDICT_PROTECT, reason="protected_terms_hit")

    log_unresolved_fn(text_stripped, locale, file=file, context=context, log_path=log_path)
    return ClassificationResult(VERDICT_UNRESOLVED, reason="unresolved_single_hump_default_protect")
