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
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from src.tm.normalization import normalize_text

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_DIR = _REPO_ROOT / "config" / "i18n" / "template_strings"
DEFAULT_TERMINOLOGY_YAML = _REPO_ROOT / "config" / "terminology.yaml"
DEFAULT_DISCOVERY_LOG = _REPO_ROOT / "data" / "discovery" / "unresolved_terms.jsonl"
DEFAULT_MISSING_KEY_LOG = _REPO_ROOT / "data" / "discovery" / "i18n_missing_keys.jsonl"

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

_VALID_CATEGORIES = {"section_heading", "table_header", "enum_value", "param_phrase"}
_VALID_STATUSES = {"approved", "pending", "deprecated"}
_VALID_CORPUS_AGREEMENT = {"agree", "override", "no_corpus_evidence"}

# Parameterized-phrase token syntax: lowercase snake_case, e.g. {api}, {n}.
_PLACEHOLDER_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Extracts {token} occurrences from an `en` template / locale value.
_TEMPLATE_TOKEN_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
# Captured span for one placeholder during substitution: no newlines, capped
# length, non-greedy — inserted verbatim (never translated, never formatted).
_PARAM_CAPTURE = r"(\S[^\n]{0,118}?)"

# Unit-kind → registry categories eligible for i18n resolution. Keys are the
# TextUnitKind *values* (plain strings — callers may hold either the enum or a
# raw string; use categories_for_kind() which normalizes). Frontmatter units
# are deliberately ineligible this mission: reference titles/descriptions are
# real content, and field-context keys don't exist yet — a future opt-in via
# site profile is a data change, not a design change.
CATEGORIES_FOR_KIND: dict[str, frozenset[str]] = {
    "heading_text": frozenset({"section_heading", "table_header"}),
    # Table cells may hold header tokens or enum-ish values (Read/Write under
    # an Access column) — but never section headings.
    "table_cell_text": frozenset({"table_header", "enum_value"}),
    # A bare TEXT leaf's container is unknown — allow label categories but
    # NEVER enum_value, so "Read"/"Write" inside prose can't table-resolve.
    "text": frozenset({"section_heading", "table_header"}),
}


def categories_for_kind(kind: object) -> frozenset[str]:
    """Eligible registry categories for a text-unit kind (enum or string).
    Unknown kinds (code spans, link text, image alt, …) get an empty set —
    ineligible for i18n resolution."""
    value = getattr(kind, "value", kind)
    return CATEGORIES_FOR_KIND.get(str(value), frozenset())


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
    # Approved trivial variants of `en` (case / trailing-colon only) that
    # resolve to the same entry — validated below so a genuinely different
    # string can never be smuggled in as a "variant" (that would be a
    # duplicate key in disguise).
    variants: list[str] = Field(default_factory=list)
    # Parameterized phrases (category=param_phrase): `en` holds the template
    # ("Inherits from: {api}."), placeholders lists its tokens.
    placeholders: list[str] = Field(default_factory=list)
    # Context requirement (enum_value only): e.g. {column_header: Access}
    # gates resolution on the unit's table-column context, separating
    # Read/Write-as-access-value from Read/Write-as-method-name.
    context: dict[str, str] | None = None

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

    @model_validator(mode="after")
    def _cross_field_rules(self) -> "RegistryEntry":
        for variant in self.variants:
            if variant.rstrip(":：").casefold() != self.en.rstrip(":：").casefold():
                raise ValueError(
                    f"variant {variant!r} of entry {self.id!r} differs from en "
                    f"{self.en!r} by more than case/trailing-colon — that is a "
                    f"new string, not a variant; give it its own entry"
                )
        if self.placeholders:
            if self.category != "param_phrase":
                raise ValueError(
                    f"entry {self.id!r} has placeholders but category "
                    f"{self.category!r}; placeholders require category=param_phrase"
                )
            for token in self.placeholders:
                if not _PLACEHOLDER_TOKEN_RE.match(token):
                    raise ValueError(
                        f"entry {self.id!r} placeholder {token!r} is not lower_snake_case"
                    )
            en_tokens = set(_TEMPLATE_TOKEN_RE.findall(self.en))
            if en_tokens != set(self.placeholders):
                raise ValueError(
                    f"entry {self.id!r}: en-template tokens {sorted(en_tokens)} != "
                    f"declared placeholders {sorted(self.placeholders)}"
                )
        elif self.category == "param_phrase":
            raise ValueError(f"entry {self.id!r} is param_phrase but declares no placeholders")
        if self.context is not None:
            if self.category != "enum_value":
                raise ValueError(
                    f"entry {self.id!r} has a context requirement but category "
                    f"{self.category!r}; context is only valid on enum_value entries"
                )
            unknown = set(self.context) - {"column_header"}
            if unknown:
                raise ValueError(
                    f"entry {self.id!r} has unsupported context key(s) {sorted(unknown)}"
                )
        return self


class RegistryFile(BaseModel):
    schema_version: int
    entries: list[RegistryEntry] = Field(default_factory=list)


class LocaleTranslationEntry(BaseModel):
    value: str
    reviewed_by: str
    reviewed_at: str | None = None
    evidence_count: int = 0
    # Known-wrong corpus forms for this (entry, locale), recorded at
    # adjudication time — consumed by targeted content healing and by the TM
    # rejected-variant correction rule.
    rejected_variants: list[str] = Field(default_factory=list)
    # Whether the reviewed value agreed with the corpus-majority form,
    # overrode it (es "Revisión" case), or had no corpus evidence at all.
    corpus_agreement: str | None = None

    @field_validator("corpus_agreement")
    @classmethod
    def _valid_agreement(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_CORPUS_AGREEMENT:
            raise ValueError(
                f"corpus_agreement must be one of {sorted(_VALID_CORPUS_AGREEMENT)}, got {v!r}"
            )
        return v


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


def normalize_for_registry(text: str) -> str:
    """Registry-lookup normalization: NFC + whitespace-collapse + trim,
    CASE-PRESERVING (reuses the TM layer's :func:`normalize_text` — one
    normalization SSOT). Case-sensitivity is deliberate: Title Case is the
    label-vs-identifier signal ("Value" the column header vs "value" an HTML
    attribute), and folding it would invite identifier collisions."""
    return normalize_text(text)


class TemplateStringRegistry:
    """Loads ``_registry.yaml`` + every per-locale file in the same directory."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else DEFAULT_REGISTRY_DIR
        self.entries: dict[str, dict] = {}
        self.by_en_text: dict[str, str] = {}
        # Normalized en/variant text -> entry ids in registry-file order.
        # A list, not a single id: context-split entries (e.g. a future
        # heading.description vs table.header.description) legitimately share
        # one EN text and are disambiguated by category at resolve() time.
        self.by_norm_en: dict[str, list[str]] = {}
        self.translations: dict[str, dict[str, dict]] = {}
        # Ids of param_phrase entries, registry order (compiled lazily).
        self.param_entry_ids: list[str] = []
        self._param_matchers: dict[str, re.Pattern] | None = None
        # Non-fatal data problems found at load time. The live path must not
        # crash on bad data, so problems are recorded here and surfaced by
        # tests/audit (which assert this is empty for production data).
        self.load_errors: list[str] = []
        # Missing-key dedup, per registry instance: get_default_registry()
        # is process-cached, so this is effectively per-process dedup.
        self._missing_key_seen: set[tuple[str, str]] = set()
        self._load()

    def _load(self) -> None:
        registry_path = self.directory / "_registry.yaml"
        if registry_path.exists():
            data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
            for entry in data.get("entries", []) or []:
                entry_id = entry["id"]
                self.entries[entry_id] = entry
                # First entry wins (deterministic); split entries sharing an
                # EN text are served via by_norm_en + category scoping.
                self.by_en_text.setdefault(entry["en"], entry_id)
                for key_text in [entry["en"], *(entry.get("variants") or [])]:
                    norm = normalize_for_registry(key_text)
                    ids = self.by_norm_en.setdefault(norm, [])
                    same_category_dup = any(
                        self.entries[eid].get("category") == entry.get("category")
                        for eid in ids
                    )
                    if same_category_dup:
                        self.load_errors.append(
                            f"registry collision: {entry_id!r} duplicates normalized "
                            f"text {norm!r} within category {entry.get('category')!r}"
                        )
                        continue
                    ids.append(entry_id)
                if entry.get("placeholders"):
                    self.param_entry_ids.append(entry_id)
        if not self.directory.exists():
            return
        for locale_file in sorted(self.directory.glob("*.yaml")):
            if locale_file.name == "_registry.yaml":
                continue
            locale = locale_file.stem
            data = yaml.safe_load(locale_file.read_text(encoding="utf-8")) or {}
            translations = data.get("translations", {}) or {}
            # Param-phrase token parity: a locale value whose {token} set
            # doesn't match the entry's placeholders can't be substituted
            # safely — drop it (fall through to TM/MT) and record the error.
            for entry_id in list(translations.keys()):
                entry = self.entries.get(entry_id)
                if not entry or not entry.get("placeholders"):
                    continue
                raw = translations[entry_id]
                value = raw.get("value") if isinstance(raw, dict) else raw
                locale_tokens = set(_TEMPLATE_TOKEN_RE.findall(value or ""))
                if locale_tokens != set(entry["placeholders"]):
                    self.load_errors.append(
                        f"{locale}/{entry_id}: locale-template tokens "
                        f"{sorted(locale_tokens)} != placeholders "
                        f"{sorted(entry['placeholders'])} — value dropped"
                    )
                    del translations[entry_id]
            self.translations[locale] = translations

    def _param_matcher(self, entry_id: str) -> re.Pattern | None:
        """Compiled anchored matcher for a param_phrase entry's en template.
        A token repeated in the template (e.g.
        phrase.members_accessible_after_install's ``{platform}`` appearing
        twice) gets a capturing group on its FIRST occurrence and a
        backreference (`(?P=token)`) on every subsequent one -- both must
        match the identical literal text, which is also the semantically
        correct behavior for a repeated token (the same value both times)."""
        if self._param_matchers is None:
            self._param_matchers = {}
            for pid in self.param_entry_ids:
                entry = self.entries[pid]
                try:
                    pattern = ""
                    pos = 0
                    seen_tokens: set[str] = set()
                    for m in _TEMPLATE_TOKEN_RE.finditer(entry["en"]):
                        pattern += re.escape(entry["en"][pos : m.start()])
                        token = m.group(1)
                        if token in seen_tokens:
                            pattern += f"(?P={token})"
                        else:
                            pattern += f"(?P<{token}>{_PARAM_CAPTURE[1:-1]})"
                            seen_tokens.add(token)
                        pos = m.end()
                    pattern += re.escape(entry["en"][pos:])
                    self._param_matchers[pid] = re.compile(f"^{pattern}$")
                except re.error as exc:
                    self.load_errors.append(f"param matcher for {pid!r} failed: {exc}")
        return self._param_matchers.get(entry_id)

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

    def rejected_variants_for_text(self, text: str, locale: str) -> list[str]:
        """Known-wrong corpus forms recorded for ``text``'s registry entry in
        ``locale`` (adjudication provenance) — consumed by targeted content
        healing (scripts/quality/heal_english_headings_dictionary.py
        ``--mode targeted``) to decide whether an existing translated
        heading is a confirmed defect (safe to overwrite) versus merely a
        different, still-acceptable rendering (left alone)."""
        entry_id = self.by_en_text.get(text)
        if entry_id is None:
            return []
        raw = (self.translations.get(locale) or {}).get(entry_id)
        if not isinstance(raw, dict):
            return []
        return list(raw.get("rejected_variants") or [])

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
# i18n-first resolver (mission reference-i18n-hardening-20260725)
# ---------------------------------------------------------------------------


def _log_missing_key(
    entry_id: str,
    en: str,
    locale: str,
    status: str,
    *,
    file: str | None,
    context: str | None,
    log_path: Path | None,
) -> None:
    path = Path(log_path) if log_path else DEFAULT_MISSING_KEY_LOG
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entry_id": entry_id,
            "en": en,
            "locale": locale,
            "status": status,
            "file": file,
            "context": context,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:  # pragma: no cover - reporting must never block translation
        pass


@dataclass
class ResolvedString:
    """Outcome of an i18n-first lookup.

    - ``table``: use ``value`` directly; skip TM and MT entirely.
    - ``fallthrough``: a registry entry EXISTS for this text but cannot serve
      this locale yet (approved-but-missing-locale, or still pending) — the
      text is translate-ELIGIBLE: proceed to TM/MT, never protect it as an
      identifier, and never silently keep English on i18n's account.
    - ``none``: no registry entry — the caller's legacy logic decides.
    """

    outcome: str  # "table" | "fallthrough" | "none"
    value: str | None = None
    entry_id: str | None = None
    status: str | None = None
    reason: str = ""


def resolve(
    text: str,
    locale: str,
    *,
    categories: frozenset[str] | None = None,
    registry: TemplateStringRegistry | None = None,
    file: str | None = None,
    context: dict[str, str] | None = None,
    missing_key_log_path: Path | None = None,
) -> ResolvedString:
    """i18n-first lookup for a short string: normalized-but-lossless matching
    (NFC, whitespace-collapse, case-SENSITIVE, trailing-colon reattachment),
    category scoping by unit kind, context-gated enum values, deterministic
    fallback, and deduplicated missing-key reporting. Never raises.

    ``categories=None`` means "no category filter" (legacy classify()
    behavior); pass ``categories_for_kind(unit.kind)`` on kind-aware paths.
    An empty ``categories`` frozenset means ineligible (e.g. frontmatter) —
    always ``none``.
    """
    try:
        reg = registry if registry is not None else get_default_registry()
        stripped = text.strip()
        if not stripped or len(stripped) > 200:
            return ResolvedString("none", reason="empty_or_oversized")
        if categories is not None and not categories:
            return ResolvedString("none", reason="ineligible_kind")

        norm = normalize_for_registry(stripped)
        colon_suffix = ""
        candidate_ids = reg.by_norm_en.get(norm)
        if candidate_ids is None and norm and norm[-1] in (":", "："):
            stem = norm[:-1].rstrip()
            stem_ids = reg.by_norm_en.get(stem)
            if stem_ids is not None:
                candidate_ids = stem_ids
                colon_suffix = norm[-1]

        best_fallthrough: ResolvedString | None = None
        for entry_id in candidate_ids or []:
            entry = reg.entries.get(entry_id) or {}
            status = entry.get("status")
            if status == "deprecated":
                continue
            if categories is not None and entry.get("category") not in categories:
                continue
            required_context = entry.get("context") or {}
            if required_context:
                got = {k: (context or {}).get(k, "") for k in required_context}
                if any(
                    (got.get(k) or "").strip().casefold() != v.strip().casefold()
                    for k, v in required_context.items()
                ):
                    continue
            locale_raw = (reg.translations.get(locale) or {}).get(entry_id)
            locale_value = (
                locale_raw.get("value") if isinstance(locale_raw, dict) else locale_raw
            )
            if status == "approved" and locale_value:
                return ResolvedString(
                    "table",
                    value=locale_value + colon_suffix,
                    entry_id=entry_id,
                    status=status,
                    reason="table_hit",
                )
            if status == "approved" and not locale_value:
                key = (entry_id, locale)
                if key not in reg._missing_key_seen:
                    reg._missing_key_seen.add(key)
                    _log_missing_key(
                        entry_id,
                        entry.get("en", ""),
                        locale,
                        status,
                        file=file,
                        context=str(context) if context else None,
                        log_path=missing_key_log_path,
                    )
                best_fallthrough = best_fallthrough or ResolvedString(
                    "fallthrough",
                    entry_id=entry_id,
                    status=status,
                    reason="approved_missing_locale",
                )
            elif status == "pending":
                best_fallthrough = best_fallthrough or ResolvedString(
                    "fallthrough",
                    entry_id=entry_id,
                    status=status,
                    reason="pending_entry",
                )
        if best_fallthrough is not None:
            return best_fallthrough

        # Parameterized phrases: attempted only after an exact miss, only if
        # any exist, and only where the kind allows them.
        if reg.param_entry_ids and (categories is None or "param_phrase" in categories):
            for entry_id in reg.param_entry_ids:
                entry = reg.entries[entry_id]
                if entry.get("status") == "deprecated":
                    continue
                matcher = reg._param_matcher(entry_id)
                m = matcher.match(stripped) if matcher else None
                if not m:
                    continue
                locale_raw = (reg.translations.get(locale) or {}).get(entry_id)
                locale_value = (
                    locale_raw.get("value") if isinstance(locale_raw, dict) else locale_raw
                )
                if entry.get("status") == "approved" and locale_value:
                    substituted = locale_value
                    for token, captured in m.groupdict().items():
                        # Literal replacement, never str.format — captured
                        # identifiers are inserted verbatim, untranslated.
                        substituted = substituted.replace("{" + token + "}", captured)
                    return ResolvedString(
                        "table",
                        value=substituted,
                        entry_id=entry_id,
                        status="approved",
                        reason="param_hit",
                    )
                if entry.get("status") == "approved" and not locale_value:
                    key = (entry_id, locale)
                    if key not in reg._missing_key_seen:
                        reg._missing_key_seen.add(key)
                        _log_missing_key(
                            entry_id,
                            entry.get("en", ""),
                            locale,
                            "approved",
                            file=file,
                            context=str(context) if context else None,
                            log_path=missing_key_log_path,
                        )
                return ResolvedString(
                    "fallthrough",
                    entry_id=entry_id,
                    status=entry.get("status"),
                    reason="param_entry_not_servable",
                )

        return ResolvedString("none", reason="no_entry")
    except Exception:  # pragma: no cover - resolver must never block extraction
        return ResolvedString("none", reason="resolver_error")


def is_translate_eligible(
    text: str,
    categories: frozenset[str] | None = None,
    *,
    registry: TemplateStringRegistry | None = None,
) -> bool:
    """Cheap check: does a non-deprecated registry entry exist for this text
    under the allowed categories (regardless of locale coverage)? True means
    "this is a known template string — send it to the translation path, never
    protect it as an identifier." Replaces the extractor's hardcoded
    _API_HEADING_TERMS/_ALWAYS_TRANSLATE_WORDS override sets."""
    try:
        reg = registry if registry is not None else get_default_registry()
        stripped = text.strip()
        if not stripped:
            return False
        norm = normalize_for_registry(stripped)
        candidate_ids = reg.by_norm_en.get(norm)
        if candidate_ids is None and norm and norm[-1] in (":", "："):
            candidate_ids = reg.by_norm_en.get(norm[:-1].rstrip())
        for entry_id in candidate_ids or []:
            entry = reg.entries.get(entry_id) or {}
            if entry.get("status") == "deprecated":
                continue
            if categories is not None and entry.get("category") not in categories:
                continue
            # Context-gated entries (enum values) still count as eligible for
            # the kinds that allow their category; the resolve()-time context
            # check decides whether the VALUE is served.
            return True
        return False
    except Exception:  # pragma: no cover
        return False


@lru_cache(maxsize=4)
def _cached_registry(directory: str) -> TemplateStringRegistry:
    return TemplateStringRegistry(Path(directory))


def get_default_registry(directory: Path | None = None) -> TemplateStringRegistry:
    """Process-cached registry — the extractor previously re-read all 14+
    YAML files once per file per language; every live-path consumer should
    use this instead of constructing TemplateStringRegistry directly."""
    return _cached_registry(str(directory or DEFAULT_REGISTRY_DIR))


@lru_cache(maxsize=4)
def _cached_protected_terms(path: str) -> ProtectedTerms:
    return ProtectedTerms(Path(path))


def get_default_protected_terms(path: Path | None = None) -> ProtectedTerms:
    return _cached_protected_terms(str(path or DEFAULT_TERMINOLOGY_YAML))


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
    categories: frozenset[str] | None = None,
    unit_context: dict[str, str] | None = None,
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
    if categories is None:
        # Legacy path: exact-strip lookup, byte-identical to the shipped
        # behavior for existing consumers (Gate 9 adjacency, tm cleanup,
        # should_protect_as_identifier).
        table_value = reg.lookup(text_stripped, locale)
        if table_value is not None:
            return ClassificationResult(VERDICT_TABLE, value=table_value, reason="table_hit")
    else:
        resolved = resolve(
            text_stripped,
            locale,
            categories=categories,
            registry=reg,
            file=file,
            context=unit_context,
        )
        if resolved.outcome == "table":
            return ClassificationResult(VERDICT_TABLE, value=resolved.value, reason=resolved.reason)
        if resolved.outcome == "fallthrough":
            # A known template string not yet servable in this locale:
            # translate-eligible (TM/MT), never identifier-protected, and
            # never a discovery-log event (it's known, just unadjudicated
            # or missing a reviewed locale value — already reported via the
            # missing-key log when approved).
            return ClassificationResult(
                VERDICT_NOT_APPLICABLE, reason=f"i18n_{resolved.reason}"
            )

    if _MULTI_HUMP_RE.match(text_stripped):
        return ClassificationResult(VERDICT_PROTECT, reason="multi_hump_identifier_shape")

    if not _SINGLE_HUMP_RE.match(text_stripped):
        return ClassificationResult(VERDICT_NOT_APPLICABLE, reason="not_identifier_shaped")

    prot = protected_terms if protected_terms is not None else ProtectedTerms()
    if text_stripped in prot:
        return ClassificationResult(VERDICT_PROTECT, reason="protected_terms_hit")

    log_unresolved_fn(text_stripped, locale, file=file, context=context, log_path=log_path)
    return ClassificationResult(VERDICT_UNRESOLVED, reason="unresolved_single_hump_default_protect")


def should_protect_as_identifier(
    text: str,
    locale: str,
    *,
    registry: TemplateStringRegistry | None = None,
    protected_terms: ProtectedTerms | None = None,
) -> bool:
    """Thin boolean wrapper around :func:`classify` for callers that only
    need a yes/no "is this an identifier that must not be translated"
    answer — e.g. write_gate.py's frontmatter-id-corruption gate and
    tm_surgical_cleanup.py's Rule 1 (mission heading-i18n-governance-20260723,
    TC-HT-I18N-004 completion).

    Both ``protect`` (confident multi-hump shape, or a single-hump word
    explicitly listed in ``config/terminology.yaml``) and ``unresolved``
    (a first-sighting single-hump word, safer-default-protect direction)
    map to ``True`` here — from these callers' point of view both mean
    "treat as an identifier, restore/preserve the English source." Only a
    ``translate_via_table`` hit (a reviewed, approved translation) or
    ``not_applicable`` (not identifier-shaped at all) map to ``False``.

    Verified against this module's own golden cases before use elsewhere:
    ``should_protect_as_identifier("Camera", "ar")`` is ``True`` (unresolved
    single-hump default-protect — "Camera" isn't in terminology.yaml today,
    but the safer direction still holds); ``should_protect_as_identifier(
    "Overview", "ar")`` is ``False`` (a reviewed table hit).
    """
    result = classify(text, locale, registry=registry, protected_terms=protected_terms)
    return result.verdict in (VERDICT_PROTECT, VERDICT_UNRESOLVED)
