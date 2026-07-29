"""
Write gate evaluation for translation engine.

Extracted from TranslationEngine.translate_file() gates 2-8:
  Gate 2: Language detection mismatch (B-7.1)
  Gate 3: Overwrite protection (B-7.4, 4 CASEs)
  Gate 4: Final file purity (B-7.5)
  Gate 5: Soft contamination queue (TC-MLD-01)
  Gate 6: Code block count gate
  Gate 7: Heading surplus / TITLE hallucination
  Gate 8: YAML frontmatter structural (RC-5/RC-6)

Gate 1 (VA-03 verification) stays in the retry pipeline because it
uses `continue` to re-enter the retry loop — not a pure pass/fail gate.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..utils.models import FrontmatterMode
from .extractor.text_unit_extractor import is_family_platform_index
from .fence_spans import count_fence_open_reopens, get_fence_char_spans, strip_fenced
from .parser.hugo_parser import HugoParser
from .quality.inline_code_repair import find_inline_code_mismatches
from .quality.refusal_patterns import CONVERSATIONAL_SHAPE_RE, REFUSAL_RE
from .reconstructor.yaml_formatter import YAMLFormatter
from .terminology.classification import TemplateStringRegistry, should_protect_as_identifier

if TYPE_CHECKING:
    from ..utils.config_loader import ConfigService
    from .language_detection.fasttext_detector import FastTextDetector
    from .language_detection.similarity_tracker import SimilarityTracker

logger = logging.getLogger(__name__)

# TC-HT-001: shared parser instance for frontmatter-field extraction. Parses
# full YAML scalars (folded/literal/multi-line) instead of first-line regex,
# which was the root cause of the 2026-07-12 wave-3 description-truncation bug.
_fm_parser = HugoParser()


def _get_frontmatter_field(content: str, field_name: str) -> str | None:
    """Return the full string value of a frontmatter field, or None."""
    split = _fm_parser._split_frontmatter(content)
    if split is None:
        return None
    data = _fm_parser._parse_yaml_content(split[0])
    if not isinstance(data, dict):
        return None
    value = data.get(field_name)
    return value if isinstance(value, str) else None


def _get_nested_frontmatter_field(content: str, *path: str) -> str | None:
    """Return a nested frontmatter string value (e.g. provenance.content_hash),
    or None if any segment of the path is missing or not a string leaf.
    """
    split = _fm_parser._split_frontmatter(content)
    if split is None:
        return None
    data = _fm_parser._parse_yaml_content(split[0])
    if not isinstance(data, dict):
        return None
    node: Any = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, str) else None


def _get_frontmatter_list_field(content: str, field_name: str) -> list[str] | None:
    """Return a frontmatter field's value as a list of strings, or None if
    the field is absent or not a list of strings (e.g. `keywords:`)."""
    split = _fm_parser._split_frontmatter(content)
    if split is None:
        return None
    data = _fm_parser._parse_yaml_content(split[0])
    if not isinstance(data, dict):
        return None
    value = data.get(field_name)
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, str)]


def _build_language_detection_text(content: str, site_profile: Any = None) -> str:
    """Text used for language-detection gates, with deliberately
    passthrough (`mode: passthrough`) frontmatter field values removed.

    HT-QUALITY-GATES-001 Part 26: confirmed real via direct reproduction --
    `testimonialswrapper.tmessage` (a genuine customer quote, deliberately
    left in its original language by site-profile design) is long enough to
    bias FastText's whole-file language classification toward the source
    language, even when every actually-translatable field is correctly
    translated. This made CASE 1/CASE 4 overwrite-protection block
    legitimate hr/sr retranslations indefinitely, leaving stale pre-mission
    content (and its wrong title) in place. Detection-only: the text
    actually written to disk is never touched by this function.
    """
    if site_profile is None or not getattr(site_profile, "frontmatter", None):
        return content

    split = _fm_parser._split_frontmatter(content)
    if split is None:
        return content
    data = _fm_parser._parse_yaml_content(split[0])
    if not isinstance(data, dict):
        return content

    detection_text = content
    for key, rule in site_profile.frontmatter.items():
        if getattr(rule, "mode", None) != FrontmatterMode.PASSTHROUGH:
            continue
        value = YAMLFormatter.get_nested_value(data, key)
        # Only strip substantial values -- short passthrough fields (e.g. a
        # URL, an enable flag rendered as text) aren't what biases detection.
        if isinstance(value, str) and len(value) >= 30:
            detection_text = detection_text.replace(value, "")
    return detection_text


# Gate 22: mojibake / encoding corruption patterns
_MOJIBAKE_GATE_RE = re.compile(r"\u00e2\u20ac|\u00c3\u00a9|\u00c3\u00a8|\u00c3\u00bc|\u00c3\u00b6")

# Gate 20: shortcode leak patterns
_SHORTCODE_GATE_RE = re.compile(r"\{\{[<%]")

# Gate 17 (inline code integrity) helper
# Excludes newlines: an inline code span never crosses a line in markdown, and
# without this a single stray/unpaired backtick anywhere in the body would let
# the span swallow everything up to the next backtick -- including whole
# paragraphs or table rows -- producing garbage "spans" for pairing below.
_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")
# m2m100 inserts a stray `` ` `` before table rows (e.g. "` | Чтение | …").
# Matches only at line-start followed by optional space + pipe — unambiguous artifact.
_STRAY_TABLE_BACKTICK_RE = re.compile(r"(?m)^\s*`(\s*\|)")
# Fenced code blocks (```...```) must be excluded before extracting inline
# (single-backtick) spans -- otherwise the three backticks of a fence get
# paired up across the fence boundary as if they were inline code, corrupting
# both the span count and content for every span that follows. Fenced blocks
# have their own dedicated check (Gate 19/_gate_code_fence_count).
_FENCED_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)

# Gate 30: universal placeholder-leak detection. Mirrors
# PlaceholderManager.extract_placeholders()'s own pattern exactly (braces
# optional -- the MT model can strip them entirely, confirmed directly) so
# the write-time check and the extraction-time check can't drift apart.
_PLACEHOLDER_LEAK_RE = re.compile(r"\{?PLACEHOLDER_\d+\}?")

# Gate 24: description reverted to English (non-Latin locales only)
_NON_LATIN_SCRIPT_LOCALES = frozenset(
    {
        "ar",
        "bg",
        "el",
        "fa",
        "he",
        "hi",
        "ja",
        "ko",
        "ru",
        "th",
        "uk",
        "vi",
        "zh",
    }
)

# Gate 31: partial foreign-script contamination. Gate 24 above only catches
# TOTAL reversion (the whole description field is ASCII-only); this catches
# the more common, more insidious partial case -- a handful of foreign-
# language words mixed into otherwise-correct non-Latin prose, which a
# whole-field/whole-file dominant-language detector (FastText) simply
# doesn't see, since most of the text is still the right language.
#
# A first version matched any run of 2+ consecutive Latin-alphabetic words
# and was FAR too noisy in practice: a 40-file sample of real production
# content flagged 39/40 files. Two root causes, both fixed below:
#   1. Vietnamese ("vi") was included via the shared _NON_LATIN_SCRIPT_LOCALES
#      set, but Vietnamese IS written in Latin script (Quốc Ngữ, with
#      diacritics) -- every Vietnamese sentence contains plain-ASCII Latin
#      words ("cho", "la", "trong", "sau khi"...), so the premise doesn't
#      apply to it at all. This gate uses its own locale set, not the shared
#      one (which serves other purposes, e.g. FastText grouping, where
#      including "vi" may be intentional for different reasons).
#   2. Ordinary 2-4 word Latin BRAND/technical phrases are extremely common
#      and legitimate in this corpus ("PDF FOSS", "Microsoft Office",
#      "Enterprise API Reference", ".NET Framework") -- these are not
#      leaked prose, they're preserved product names.
# The fix: require the matched run to also contain at least one common
# Spanish/French/German/Italian/Portuguese grammatical function word
# (de/la/las/el/para/und/der/pour/avec/...). Real leaked PROSE reliably
# contains these (confirmed against the real example: "las propiedades
# ColumnCount para el", "de columna preciso", and "Referencia de API
# Enterprise" all matched; only the one non-prose case, "expuesto
# ColumnWidths" -- a verb next to a bare identifier, no function word --
# would now be missed, an acceptable precision/recall tradeoff given the
# 39/40 false-positive rate the naive version had). Brand/technical phrases
# never contain these particles, so they no longer match.
_GATE31_NON_LATIN_LOCALES = frozenset(
    {
        "ar",
        "bg",
        "el",
        "fa",
        "he",
        "hi",
        "ja",
        "ko",
        "ru",
        "th",
        "uk",
        "zh",
    }
)
_LATIN_WORD_RUN_RE = re.compile(r"\b[A-Za-z]{2,}(?:[ \t]+[A-Za-z]{2,}){1,}\b")
_ROMANCE_GERMANIC_FUNCTION_WORDS = frozenset(
    {
        "de",
        "la",
        "las",
        "el",
        "los",
        "con",
        "para",
        "que",
        "una",
        "uno",
        "des",
        "le",
        "les",
        "un",
        "dans",
        "avec",
        "pour",
        "sur",
        "und",
        "der",
        "die",
        "das",
        "dem",
        "den",
        "für",
    }
)
# Markdown link syntax: strip the (url) part but keep the [visible text] --
# the anchor text is real page content and must still be scanned.
_MARKDOWN_LINK_URL_RE = re.compile(r"\]\([^)]*\)")
_BARE_URL_RE = re.compile(r"https?://\S+")

# Gates 34-35: detection symmetry for the systemically dropped trailing
# section (almost always "See Also"/"Related Resources", almost always
# just links -- see the GATE_REGISTRY comment on these two entries).
# Captures the URL itself (unlike _MARKDOWN_LINK_URL_RE above, which only
# matches for stripping) -- URLs are language-invariant, so they're the one
# language-agnostic proxy for "is this same section still present" that
# works regardless of target locale, unlike heading TEXT (which is
# correctly translated and therefore never string-matches EN).
_MARKDOWN_LINK_CAPTURE_RE = re.compile(r"\]\((https?://[^)\s]+)\)")
_TOP_HEADING_RE = re.compile(r"^##\s+.+$", re.MULTILINE)

# HT-QUALITY-GATES-001 Phase 8 (F1/F3): canonical mapping from gate id to
# the issue-type string a finding is reported under, shared by every
# producer (scripts/quality/audit_all_content.py's sweep) and consumer
# (scripts/quality/unit_heal.py's healer) of gate-derived findings. Before
# this, the two would have had to independently invent and keep in sync a
# gate-id-to-name mapping -- exactly the kind of drift that let Gates
# 29-35's findings reach a queue under names UnitQualityScorer's fixed
# vocabulary could never match (root cause RC2 of the Phase 7 "no
# detector" reconnaissance documented in the Phase 7 plan).
GATE_ISSUE_NAMES: dict[int, str] = {
    26: "code_fence_dropped",
    29: "refusal_artifact_gate29",
    30: "placeholder_leak_gate30",
    31: "partial_script_contamination_gate31",
    32: "content_hash_stale_gate32",
    33: "brand_token_missing_gate33",
    34: "heading_deficit_gate34",
    35: "dropped_trailing_link_gate35",
}


def gate_issue_name(gate_id: int, method_name: str) -> str:
    """Canonical issue-type string for a gate id. Any gate id not in
    GATE_ISSUE_NAMES (36+, or any future registry entry) gets a predictable
    ``gate{id}_{method}`` fallback name requiring no manual registration."""
    if gate_id in GATE_ISSUE_NAMES:
        return GATE_ISSUE_NAMES[gate_id]
    return f"gate{gate_id}_{method_name.removeprefix('_gate_')}"


def gate_id_from_issue_name(issue_name: str) -> int | None:
    """Reverse of gate_issue_name(): given an issue-type string, return the
    gate id that produces it, or None if it doesn't match any known gate
    name (curated or fallback-pattern)."""
    for gate_id, name in GATE_ISSUE_NAMES.items():
        if name == issue_name:
            return gate_id
    if issue_name.startswith("gate"):
        digits = ""
        for ch in issue_name[4:]:
            if not ch.isdigit():
                break
            digits += ch
        if digits:
            return int(digits)
    return None


# Gate 25: code block content truncated
_CODE_BLOCK_CONTENT_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

# Gate 37: TM-collision cross-context metadata contamination -- see
# scripts/quality/audit_tm_collision.py, whose BACKTICK_ID_RE this mirrors.
_BACKTICK_ID_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")

# Gate 39: en-dash/em-dash numeric-range collapse (e.g. "18-22" -> "1822").
# ‒ figure dash, – en dash, — em dash -- and a plain hyphen,
# since the same collapse can happen to an ASCII-hyphen range too.
_DIGIT_DASH_DIGIT_RE = re.compile(r"\b(\d{1,4})[‒–—-](\d{1,4})\b")
_DIGIT_RUN_RE = re.compile(r"\d+")

# Gate 41: homoglyph substitution in code spans/identifiers. Curated
# Cyrillic/Greek confusables that visually resemble ASCII Latin letters --
# no homoglyph/confusable-character detection existed anywhere in this
# codebase before this gate (repo-wide grep for "homoglyph"/"confusable"
# returned zero matches).
_HOMOGLYPH_TO_ASCII: dict[str, str] = {
    # Cyrillic lowercase
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "ѕ": "s",
    "і": "i",
    "ј": "j",
    "ԁ": "d",
    "ԛ": "q",
    "ѡ": "w",
    # Cyrillic uppercase
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    # Greek uppercase
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    # Greek lowercase
    "ο": "o",
}
_HOMOGLYPH_CHARS_RE = re.compile("[" + "".join(_HOMOGLYPH_TO_ASCII.keys()) + "]")
_INLINE_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")


@dataclass
class WriteGateResult:
    """Result of write gate evaluation."""

    passed: bool
    error: str | None = None
    overwrite_blocked: bool = False
    contamination_queued: bool = False
    retranslate_queued: bool = False
    # Paths to queue for retranslation (CASE 4, soft contamination, etc.)
    retranslate_paths: list[tuple[Path, str]] = field(default_factory=list)
    # Whether TM buffer should be cleared (purity/YAML gate failure)
    clear_tm_buffer: bool = False
    # Quarantine info for YAML gate failures
    quarantine_content: str | None = None
    quarantine_error: str | None = None
    # Auto-clean gates (9-12, 16) set this; file_pipeline.py writes this instead of original
    cleaned_content: str | None = None
    # Per-gate metadata only; rejected candidate text is deliberately excluded.
    gate_results: dict[int, dict[str, Any]] = field(default_factory=dict)


class WriteGateEvaluator:
    """Evaluates whether a translated file should be written to disk.

    Pure evaluator — no side effects (no file writes, no TM mutations).
    Returns a WriteGateResult that the caller uses to decide next steps.

    Adding a new gate:
    1. Add an entry to GATE_REGISTRY (gate_id, method_name, category, action).
    2. Implement the method.
    3. ``_verify_gate_registry()`` will assert the method exists at startup.

    ``action`` values:
    - ``"block"``      — set ``result.passed = False`` on failure (gate returns None).
    - ``"auto_clean"`` — return modified content string; evaluator applies it to ``working``.
    - ``"warn"``       — log but never set result.passed = False.
    - ``"early_return"`` — block AND return immediately from evaluate() (gates 2-8).
    - ``"no_op"``      — always passes; used for soft/informational gates (gate 5).

    Rollout / promotion convention (HT-QUALITY-GATES-001 Phase 8, F5 —
    established by Gates 28/29's history, not new machinery): every new
    content gate ships as ``"warn"`` first — a "warn" gate runs against a
    disposable, discarded WriteGateResult (see ``_run_content_gates``), so a
    bug in a brand-new gate can never accidentally start blocking
    production writes. Promotion to ``"block"`` is a direct edit to this
    registry (not a config flag) once a clean-sample false-positive check
    has run — search this file for "TC-QG-001/005" (Gate 28) and "Part 22"
    (Gate 29) for the two real promotions and the evidence that justified
    each. Record the promotion's evidence in a comment on the registry row
    itself (as those two do), not only in a commit message — the registry
    is the durable, in-repo record of why a gate is trusted to block.
    A gate that will never have a mechanical false-positive check (e.g. one
    whose only failure mode is a hard structural fact, like a placeholder
    token literally present) may ship straight to ``"block"`` — see Gate 30's
    own registry comment for that reasoning.
    """

    # Authoritative list of all gates in execution order.
    # Entries: (gate_id, method_name, category, action)
    #
    # Gates 2-8 are "early_return" — they are called explicitly in evaluate()
    # because they have special early-exit logic and non-uniform signatures
    # (some need `detector`, `source_doc`, `force_overwrite`, `target_lang`).
    # Gates 9-22 are content quality gates driven by the loop in
    # _run_content_gates(); adding a new entry here + implementing the method
    # is sufficient to wire it in.
    GATE_REGISTRY: list[tuple[int, str, str, str]] = [
        # id   method                             category       action
        (2, "_gate_language_mismatch", "structural", "early_return"),
        (3, "_gate_overwrite_protection", "safety", "early_return"),
        (4, "_gate_file_purity", "content", "early_return"),
        (5, "_gate_soft_contamination", "content", "no_op"),
        (6, "_gate_code_block", "structural", "early_return"),
        (7, "_gate_heading_surplus", "structural", "early_return"),
        (8, "_gate_yaml_frontmatter", "structural", "early_return"),
        (9, "_gate_heading_integrity", "content", "auto_clean"),
        (10, "_gate_frontmatter_backticks", "content", "auto_clean"),
        (11, "_gate_frontmatter_id_corruption", "content", "auto_clean"),
        (12, "_gate_double_periods", "cosmetic", "auto_clean"),
        (13, "_gate_eu_hallucination", "content", "block"),
        (14, "_gate_mixed_language", "content", "block"),
        (15, "_gate_table_row_integrity", "structural", "block"),
        (16, "_gate_duplicate_content", "content", "auto_clean"),
        (17, "_gate_newline_explosion", "structural", "block"),
        (18, "_gate_description_hallucination", "content", "block"),
        (19, "_gate_code_fence_count", "structural", "block"),
        (20, "_gate_empty_body", "content", "block"),
        (21, "_gate_shortcode_body_leak", "structural", "block"),
        # HT-INLINE-CODE-001 TC-ICR-005: was registered "auto_clean" despite
        # its implementation being a hard block (result.passed = False) --
        # _verify_gate_registry() only checked the method existed, never
        # that its behavior matched the declared action. Re-registered as
        # "block" to match reality; see _run_content_gates()'s dispatch for
        # what actually differs (short-circuit skip once an earlier block
        # gate has already failed -- previously this gate ran regardless
        # and could silently overwrite an earlier gate's result.error).
        (22, "_gate_inline_code_integrity", "content", "block"),
        (23, "_gate_encoding_clean", "structural", "block"),
        (24, "_gate_description_reverted_to_english", "content", "block"),
        (25, "_gate_code_block_content_truncated", "structural", "block"),
        (26, "_gate_fence_parity", "structural", "block"),
        (27, "_gate_multiline_scalar_preservation", "content", "block"),
        # HT-QUALITY-GATES-001 TC-QG-001/005: Gate 28 promoted to "block" after
        # the canary (Part 19) confirmed 100% title match with the RC1-RC4
        # fixes live, and the dropped-placeholder fallback (Part 20/21) fixed
        # the only other residual defect found.
        (28, "_gate_title_identity", "content", "block"),
        # HT-QUALITY-GATES-001 Part 22 (1.6): Gate 29 promoted from "warn" to
        # "block". The clean-sample false-positive check this promotion was
        # waiting on: a follow-up investigation searched production content
        # and found 6 new real LLM conversational-response-as-translation
        # leaks, 5 of which ALREADY matched REFUSAL_RE and were shipped
        # anyway purely because this gate only logged. There is no legitimate
        # Aspose product/API documentation content that matches these
        # patterns (curated from confirmed real leaks, not guessed), so
        # blocking carries negligible false-positive risk relative to
        # continuing to ship confirmed-broken pages. No auto-fix path exists
        # for a refusal leak (nothing to auto-clean it into), so a hit routes
        # into the same retranslate-queue mechanism as Gate 28 (see
        # _gate_refusal_artifact below) rather than an auto_clean action.
        (29, "_gate_refusal_artifact", "content", "block"),
        # HT-QUALITY-GATES-001 Part 22 (1.1 root cause B): universal
        # placeholder-leak gate. A literal "PLACEHOLDER_N" token (braced or
        # bare) reaching this point means restore() was never called on this
        # content at all -- PlaceholderManager.restore()'s own passes already
        # remove every corrupted/garbled shape it can recognize, so a
        # surviving literal token is not a shape restore() failed to fix, it's
        # evidence restore() never ran. Confirmed root cause: a batch authored
        # by an entirely separate process (Codex) writing directly into the
        # content repo, bypassing this pipeline. This gate is deliberately
        # process-agnostic -- it blocks the shape regardless of which writer
        # produced it, closing this codebase's own exposure even though it
        # can't compel an external writer to route through it (Part 7).
        (30, "_gate_placeholder_leak", "content", "block"),
        # HT-QUALITY-GATES-001 Part 22 addendum (user-flagged, live-verified
        # 2026-07-22): partial foreign-script contamination -- a Hebrew
        # translation with Spanish phrases mixed into otherwise-correct
        # prose, confirmed via a deterministic (temperature=0.0) live
        # re-translation that reproduced byte-identically both before and
        # after the Phase 2 concurrency fixes, proving this is a distinct
        # bug, not an instance of anything already fixed. Ships "warn" per
        # this registry's established convention (see Gate 28/29's history
        # just above) -- a 2+-word Latin run could plausibly be a
        # legitimately-preserved multi-word technical phrase (".NET
        # Framework"), so this needs a clean-sample false-positive check
        # before it's trusted to block.
        (31, "_gate_partial_script_contamination", "content", "warn"),
        # HT-QUALITY-GATES-001 Part 22 (plan 5.1 items 8-9). Both ship "warn"
        # per this registry's established rollout convention -- neither has
        # had a canary/clean-sample pass yet. Staleness in particular is
        # diagnostic rather than a guarantee the current content is wrong
        # (EN can change without invalidating an existing translation), so
        # it's intentionally not framed as a hard block even after a canary.
        (32, "_gate_content_hash_staleness", "content", "warn"),
        (33, "_gate_brand_token_presence", "content", "warn"),
        # HT-QUALITY-GATES-001 Part 22 (plan 5.2 items 1-2): detection
        # symmetry for the single most prevalent defect found this session
        # -- a systemically dropped trailing section (almost always "See
        # Also"/"Related Resources"/an Enterprise link block), confirmed
        # across every one of the 5 sites. Gate 7 above only fires on
        # heading SURPLUS (tgt_hd >= src_hd + 3); nothing in the 29-gate
        # registry ever fired on a deficit, so this exact bug class was
        # permanently undetectable even after any upstream fix landed. Both
        # ship "warn" (new gates, established convention) pending a canary.
        (34, "_gate_heading_deficit", "structural", "warn"),
        (35, "_gate_dropped_trailing_link", "structural", "warn"),
        # HT-QUALITY-GATES-001 Part 22 (plan 5.4 items 3+5): the highest-
        # priority workstream in the whole plan -- a real LLM meaning-fidelity
        # judge, not embedding cosine similarity (SemanticSimilarityValidator
        # is too coarse for homonym/inverted-semantics/factual-reversal
        # failures that read as fluent, on-topic text). Registered as
        # "auto_clean" (not "warn"/"block") because it must always be able to
        # write the `translation_fidelity` frontmatter field for high-risk
        # files regardless of enforcement mode -- shadow-vs-enforce is a
        # config flag (translation_engine.fidelity_judge.enforce, default
        # false) read inside the gate itself, not the registry action, so the
        # verdict gets recorded from day one even while it can't yet block.
        # Only runs the actual LLM call for high-risk-tier files (see
        # _gate36_is_high_risk) -- this is the synchronous half of Part 5.4
        # item 4's tiered coverage; everything else is the periodic/sampled
        # audit tier (scripts/audit_translation_quality.py).
        (36, "_gate_fidelity_judge", "content", "auto_clean"),
        # HT-QUALITY-GATES-001 Phase 8 (Tier C #12): real-time port of the
        # already-proven scripts/quality/audit_tm_collision.py detector.
        # Ships "warn" per this registry's rollout convention (see the
        # class docstring's "Rollout / promotion convention" section) --
        # no clean-sample false-positive check has run yet for the
        # write-gate context specifically, even though the underlying
        # logic is already validated against the historical corpus by the
        # standalone script.
        (37, "_gate_tm_collision", "content", "warn"),
        # HT-QUALITY-GATES-001 Phase 8 (Tier A #14): new detector, ships
        # "warn" pending a clean-sample false-positive check (see the
        # class docstring's "Rollout / promotion convention" section).
        (38, "_gate_prose_before_code_dropped", "structural", "warn"),
        # HT-QUALITY-GATES-001 Phase 8 (Tier A #8): new detector, ships
        # "warn" pending a clean-sample false-positive check.
        (39, "_gate_dash_range_collapsed", "content", "warn"),
        # HT-QUALITY-GATES-001 Phase 8 (Tier A #10): new detector, ships
        # "warn" pending a clean-sample false-positive check.
        (40, "_gate_seo_metadata_corruption", "content", "warn"),
        # HT-QUALITY-GATES-001 Phase 8 (Tier A #4): new detector, ships
        # "warn" pending a clean-sample false-positive check.
        (41, "_gate_homoglyph_in_code", "content", "warn"),
        # HT-QUALITY-GATES-001 Phase 8 (Tier A #1): new detector, ships
        # "warn" pending a clean-sample false-positive check. Requires a
        # real detector to have any effect -- see the method's docstring.
        (42, "_gate_whole_page_language_mismatch", "content", "warn"),
        # HT-QUALITY-GATES-001 Phase 8 (Tier A #5): new detector, ships
        # "warn" pending a clean-sample false-positive check.
        (43, "_gate_block_scalar_key_leak", "content", "warn"),
        # Independent-verification finding (HT-QUALITY-GATES-001 Phase 8):
        # no SEO field anywhere had length/SERP-convention awareness. Ships
        # "warn" pending a clean-sample false-positive check.
        (44, "_gate_seo_length_sanity", "content", "warn"),
    ]

    def __init__(
        self,
        detector: FastTextDetector | None,
        similarity_tracker: SimilarityTracker | None,
        config: ConfigService | None,
        force_accept: bool = False,
        validation_policy: str = "standard",
    ) -> None:
        self._detector = detector
        self._similarity_tracker = similarity_tracker
        self._config = config
        self._force_accept = force_accept
        self._validation_policy = validation_policy
        self._zero_defect = validation_policy == "zero-defect"
        if self._zero_defect and force_accept:
            raise ValueError("zero-defect policy prohibits force_accept")
        # Mission heading-i18n-governance-20260723 (TC-HT-I18N-004
        # completion): loaded once per evaluator instance, not per gate
        # call -- shared by Gate 9 (heading-term coverage) and Gate 11
        # (frontmatter-id-corruption) below.
        self._template_registry = TemplateStringRegistry()
        self._verify_gate_registry()

    def _verify_gate_registry(self) -> None:
        """Assert every GATE_REGISTRY entry has a corresponding method."""
        missing = [
            (gate_id, method)
            for gate_id, method, _, _ in self.GATE_REGISTRY
            if not hasattr(self, method)
        ]
        if missing:
            raise AttributeError(
                f"WriteGateEvaluator: GATE_REGISTRY references missing method(s): {missing}"
            )

    def evaluate(
        self,
        translated_content: str,
        source_content: str,
        target_lang: str,
        output_path: Path,
        source_doc: Any = None,
        force_overwrite: bool = False,
        site_profile: Any = None,
        translation_stats: Any = None,
    ) -> WriteGateResult:
        """Run gates 2-8 on translated content.

        Args:
            translated_content: The full translated markdown.
            source_content: The original source markdown.
            target_lang: Expected target language code.
            output_path: Where the file would be written.
            source_doc: Parsed HugoDocument (for frontmatter key check).
            site_profile: Site profile (for passthrough-aware language
                detection -- see _build_language_detection_text). Optional;
                gates degrade to raw-content detection if omitted.
            translation_stats: Optional TranslationStats for this file (HT-
                QUALITY-GATES-001 Part 22, plan 5.4 item 4) -- used by Gate 36
                to check llm_units_translated for high-risk-tier classification
                without re-deriving it from frontmatter. Optional; Gate 36
                degrades to site/depth-only classification if omitted.

        Returns:
            WriteGateResult indicating pass/fail and any side-effect requests.
        """
        result = WriteGateResult(passed=True)
        detector = self._detector

        if detector is None:
            if self._zero_defect:
                result.passed = False
                result.error = "Gate 2 unavailable: language detector is required"
                result.gate_results[2] = {
                    "passed": False,
                    "action": "early_return",
                    "error": result.error,
                }
                return result
            logger.warning(
                "Language detector unavailable, skipping language validation for %s",
                output_path.name,
            )
            # Still run structural gates (code block, heading, YAML)
            self._gate_code_block(source_content, translated_content, output_path, result)
            if result.passed:
                self._gate_heading_surplus(source_content, translated_content, output_path, result)
            if result.passed:
                self._gate_yaml_frontmatter(
                    translated_content, output_path, target_lang, source_doc, result
                )
            working = self._run_content_gates(
                source_content,
                translated_content,
                target_lang,
                output_path,
                source_doc,
                result,
                translation_stats=translation_stats,
            )
            if working != translated_content:
                result.cleaned_content = working
            return result

        # HT-QUALITY-GATES-001 Part 26: strip deliberately-passthrough
        # frontmatter values (e.g. an untranslated customer testimonial
        # quote) before language detection -- see
        # _build_language_detection_text's docstring for the confirmed real
        # defect this fixes. Detection-only: `translated_content` itself
        # (what actually gets written) is untouched.
        _detection_text = _build_language_detection_text(translated_content, site_profile)

        # Gate 2: Language detection mismatch (B-7.1)
        self._gate_language_mismatch(_detection_text, target_lang, output_path, detector, result)
        if not result.passed:
            return result

        # Gate 3: Overwrite protection (B-7.4, 4 CASEs)
        self._gate_overwrite_protection(
            _detection_text,
            target_lang,
            output_path,
            detector,
            result,
            force_overwrite=force_overwrite,
            site_profile=site_profile,
        )
        if not result.passed:
            return result

        # Gate 4: Final file purity (B-7.5)
        self._gate_file_purity(translated_content, target_lang, output_path, detector, result)
        if not result.passed:
            return result

        # Gate 5: Soft contamination queue (TC-MLD-01) — does NOT block
        self._gate_soft_contamination(target_lang, output_path, result)
        if not result.passed:
            return result

        # Gate 6: Code block count
        self._gate_code_block(source_content, translated_content, output_path, result)
        if not result.passed:
            return result

        # Gate 7: Heading surplus / TITLE hallucination
        self._gate_heading_surplus(source_content, translated_content, output_path, result)
        if not result.passed:
            return result

        # Gate 8: YAML frontmatter structural (RC-5/RC-6)
        self._gate_yaml_frontmatter(
            translated_content, output_path, target_lang, source_doc, result
        )

        # ------------------------------------------------------------------
        # Gates 9+: Content quality gates — run UNCONDITIONALLY regardless
        # of force_accept. Driven by GATE_REGISTRY entries with action
        # "auto_clean" or "block". See _run_content_gates() for dispatch logic.
        # ------------------------------------------------------------------
        working = self._run_content_gates(
            source_content,
            translated_content,
            target_lang,
            output_path,
            source_doc,
            result,
            translation_stats=translation_stats,
        )
        if working != translated_content:
            result.cleaned_content = working

        if result.passed and self._zero_defect:
            for gate_id in range(2, 9):
                result.gate_results.setdefault(
                    gate_id,
                    {
                        "passed": True,
                        "action": "no_op" if gate_id == 5 else "early_return",
                        "error": None,
                    },
                )

        return result

    def evaluate_zero_defect(
        self,
        *,
        translated_content: str,
        source_content: str,
        target_lang: str,
        output_path: Path,
        source_doc: Any = None,
        force_overwrite: bool = False,
        site_profile: Any = None,
        translation_stats: Any = None,
        max_clean_rounds: int = 3,
    ) -> WriteGateResult:
        """Run fail-closed gates to a fixed point and return a final receipt."""
        if not self._zero_defect:
            raise RuntimeError("evaluate_zero_defect requires zero-defect policy")

        working = translated_content
        for _round in range(max_clean_rounds):
            result = self.evaluate(
                translated_content=working,
                source_content=source_content,
                target_lang=target_lang,
                output_path=output_path,
                source_doc=source_doc,
                force_overwrite=force_overwrite,
                site_profile=site_profile,
                translation_stats=translation_stats,
            )
            if not result.passed:
                return result
            cleaned = result.cleaned_content if result.cleaned_content is not None else working
            if cleaned == working:
                expected = {gate_id for gate_id, *_ in self.GATE_REGISTRY}
                missing = sorted(expected - set(result.gate_results))
                if missing:
                    result.passed = False
                    result.error = f"Zero-defect receipt missing gates: {missing}"
                    return result
                result.cleaned_content = working
                return result
            working = cleaned

        return WriteGateResult(
            passed=False,
            error=f"Auto-clean gates did not converge after {max_clean_rounds} rounds",
        )

    # ------------------------------------------------------------------
    # Gate 2: Language mismatch (B-7.1)
    # ------------------------------------------------------------------

    def _gate_language_mismatch(
        self,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        detector: FastTextDetector,
        result: WriteGateResult,
    ) -> None:
        if self._force_accept:
            return

        try:
            detected_lang, confidence = detector.detect(translated_content)
        except Exception as e:
            if self._zero_defect:
                result.passed = False
                result.error = f"Language detection unavailable: {e}"
                return
            logger.warning(f"Language detection uncertain: {e}")
            return  # Uncertain → allow write

        if detected_lang != target_lang and confidence > 0.80:
            is_similar = False
            if self._similarity_tracker:
                is_similar = self._similarity_tracker.are_similar(target_lang, detected_lang)

            if not is_similar:
                result.passed = False
                result.error = (
                    f"Language mismatch: detected {detected_lang}, expected {target_lang}"
                )
                logger.error(
                    f"WRITE BLOCKED: Content language mismatch! "
                    f"Expected: {target_lang}, Detected: {detected_lang} ({confidence:.2%}). "
                    f"Refusing to write wrong-language content to {output_path.name}."
                )
                # Check if existing file is correct (OW-01 extension)
                self._check_existing_for_ow01(target_lang, output_path, detector, result)
            else:
                logger.warning(
                    f"Language mismatch detected but allowing due to learned similarity: "
                    f"{target_lang} <-> {detected_lang} ({confidence:.2%})"
                )

    # ------------------------------------------------------------------
    # Gate 3: Overwrite protection (B-7.4)
    # ------------------------------------------------------------------

    def _gate_overwrite_protection(
        self,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        detector: FastTextDetector,
        result: WriteGateResult,
        force_overwrite: bool = False,
        site_profile: Any = None,
    ) -> None:
        if self._force_accept:
            return
        if not output_path.exists():
            return

        try:
            detected_lang, confidence = detector.detect(translated_content)
        except Exception as exc:
            if self._zero_defect:
                result.passed = False
                result.error = f"Overwrite gate language detection unavailable: {exc}"
            return

        try:
            existing_content = output_path.read_text(encoding="utf-8")
            # HT-QUALITY-GATES-001 Part 26: strip the same passthrough
            # content from the EXISTING file before detecting it, for the
            # same reason as the new content (see
            # _build_language_detection_text) -- an old file's untranslated
            # testimonial quote shouldn't bias its detected language either.
            existing_detection_text = _build_language_detection_text(existing_content, site_profile)
            existing_lang, existing_conf = detector.detect(existing_detection_text)
        except OSError as e:
            if self._zero_defect:
                result.passed = False
                result.error = f"Could not read existing output for overwrite gate: {e}"
                return
            logger.warning(f"Could not read existing file for comparison (allowing write): {e}")
            return
        except ValueError as e:
            if self._zero_defect:
                result.passed = False
                result.error = f"Existing output language detection unavailable: {e}"
                return
            logger.warning(f"Existing file language detection uncertain (allowing write): {e}")
            return

        # CASE 1: Existing correct, new wrong → BLOCK
        _case1_similar = False
        if self._similarity_tracker:
            _case1_similar = self._similarity_tracker.are_similar(target_lang, detected_lang)
        if existing_lang == target_lang and detected_lang != target_lang and not _case1_similar:
            result.passed = False
            result.error = f"Blocked overwrite: existing={existing_lang}, new={detected_lang}"
            logger.error(
                f"OVERWRITE BLOCKED: Existing file is correct {target_lang} "
                f"({existing_conf:.2%}), new content is wrong {detected_lang} "
                f"({confidence:.2%}). Refusing to replace good file with bad translation."
            )
            return

        # CASE 2: Both correct but existing higher quality → BLOCK
        # Skip when force_overwrite=True (e.g. heal runs targeting confirmed bad files)
        if (
            not force_overwrite
            and existing_lang == target_lang
            and detected_lang == target_lang
            and existing_conf > confidence + 0.05
        ):
            result.passed = False
            result.error = "Blocked overwrite: existing quality higher"
            logger.warning(
                f"OVERWRITE BLOCKED: Existing file has higher quality "
                f"({existing_lang} {existing_conf:.2%}) than new translation "
                f"({detected_lang} {confidence:.2%}). Keeping existing."
            )
            return

        # CASE 3: Existing wrong, new correct → ALLOW (healing)
        if existing_lang != target_lang and detected_lang == target_lang:
            logger.info(
                f"HEALING OVERWRITE: Replacing incorrect {existing_lang} "
                f"({existing_conf:.2%}) with correct {detected_lang} "
                f"({confidence:.2%}). Quality improvement for {output_path.name}."
            )
            return

        # CASE 4: Both wrong → BLOCK + queue
        # HT-QUALITY-GATES-001 Part 25: CASE 1 (above) already checks
        # are_similar() before treating a language mismatch as real -- CASE 4
        # never did, despite the identical reasoning applying. Confirmed real
        # via direct reproduction: ms (Malay) retranslation output, genuinely
        # correct, gets detected as `id` (Indonesian) by FastText (an
        # already-configured similarity pair, config/global.yaml's
        # malay_indonesian group) -- existing was also stale/wrong, so this
        # unconditionally blocked forever, leaving the OLD wrong content (and
        # its wrong title) in place no matter how many times you retranslate.
        _case4_similar = False
        if self._similarity_tracker:
            _case4_similar = self._similarity_tracker.are_similar(target_lang, detected_lang)
        if existing_lang != target_lang and detected_lang != target_lang:
            if _case4_similar:
                logger.info(
                    f"HEALING OVERWRITE (similarity-adjusted): new content detected as "
                    f"{detected_lang}, treated as an acceptable {target_lang} equivalent "
                    f"(learned/configured similarity) rather than genuinely wrong. "
                    f"Existing was {existing_lang} ({existing_conf:.2%}). Allowing "
                    f"overwrite for {output_path.name}."
                )
                return
            result.passed = False
            result.error = (
                f"Blocked overwrite: both translations wrong "
                f"(existing={existing_lang}, new={detected_lang})"
            )
            result.retranslate_queued = True
            result.retranslate_paths.append((output_path, target_lang))
            logger.error(
                f"OVERWRITE BLOCKED: Both existing ({existing_lang}) and new "
                f"({detected_lang}) are wrong language. Expected {target_lang}. "
                f"Blocking to prevent further corruption of {output_path.name}."
            )

    # ------------------------------------------------------------------
    # Gate 4: File-level purity (B-7.5)
    # ------------------------------------------------------------------

    def _gate_file_purity(
        self,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        detector: FastTextDetector,
        result: WriteGateResult,
    ) -> None:
        if self._force_accept:
            result._purity_result = {  # type: ignore[attr-defined]
                "passed": True,
                "reason": "Skipped by force_accept; governed verifier remains authoritative",
                "wrong_lang_percentage": 0.0,
                "detected_languages": {},
            }
            return
        purity_result = self._verify_final_file_purity(translated_content, target_lang, detector)
        if not purity_result["passed"]:
            result.passed = False
            result.error = f"Final purity check failed: {purity_result['reason']}"
            result.clear_tm_buffer = True
            logger.error(
                f"FINAL PURITY CHECK FAILED: Assembled file contains "
                f"{purity_result['wrong_lang_percentage']:.1%} wrong-language content. "
                f"Detected languages: {purity_result['detected_languages']}. "
                f"Blocking write to prevent corruption of {output_path.name}."
            )
        else:
            # Store purity result for soft contamination gate
            result._purity_result = purity_result  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Gate 5: Soft contamination (TC-MLD-01) — does NOT block write
    # ------------------------------------------------------------------

    def _gate_soft_contamination(
        self,
        target_lang: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        purity_result = getattr(result, "_purity_result", None)
        if purity_result is None:
            return

        _wrong_pct = purity_result.get("wrong_lang_percentage", 0.0)
        _soft_threshold = 0.02  # 2% floor
        _purity_override = self._get_purity_threshold(target_lang)
        if _wrong_pct > _soft_threshold and _purity_override <= 0.10 and output_path is not None:
            result.contamination_queued = True
            result.retranslate_paths.append((output_path, target_lang))
            if self._zero_defect:
                result.passed = False
                result.error = (
                    f"Gate 5 soft contamination: {_wrong_pct:.1%} wrong-language paragraphs"
                )
            logger.info(
                f"SOFT_CONTAMINATION: {_wrong_pct:.1%} wrong-language "
                f"paragraphs in {output_path.name} — passes purity gate "
                f"but queued for cleanup on next worker run."
            )

    # ------------------------------------------------------------------
    # Gate 6: Code block count
    # ------------------------------------------------------------------

    def _gate_code_block(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        _src_body = (
            source_content.split("---", 2)[2]
            if source_content.count("---") >= 2
            else source_content
        )
        _tgt_body = (
            translated_content.split("---", 2)[2]
            if translated_content.count("---") >= 2
            else translated_content
        )
        _src_cb = len(re.findall(r"^```", _src_body, re.MULTILINE)) // 2
        _tgt_cb = len(re.findall(r"^```", _tgt_body, re.MULTILINE)) // 2
        if _src_cb > 0 and _tgt_cb < _src_cb:
            result.passed = False
            result.error = (
                f"Code block gate: source has {_src_cb} code blocks but translation has {_tgt_cb}"
            )
            logger.error("CODE BLOCK GATE FAILED for %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 7: Heading surplus / TITLE hallucination
    # ------------------------------------------------------------------

    def _gate_heading_surplus(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        _src_body = (
            source_content.split("---", 2)[2]
            if source_content.count("---") >= 2
            else source_content
        )
        _tgt_body = (
            translated_content.split("---", 2)[2]
            if translated_content.count("---") >= 2
            else translated_content
        )
        # Strip fenced code blocks before counting -- a single `#` followed by
        # space is also Python's comment marker and C/C++'s preprocessor
        # directive marker, both common inside ```code``` fences. Without this,
        # a `# comment` line inside a fence gets miscounted as a heading,
        # inflating the surplus count against fence-free source bodies.
        _src_hd = len(
            re.findall(r"^#{1,6}\s", _FENCED_CODE_BLOCK_RE.sub("", _src_body), re.MULTILINE)
        )
        _tgt_hd = len(
            re.findall(r"^#{1,6}\s", _FENCED_CODE_BLOCK_RE.sub("", _tgt_body), re.MULTILINE)
        )
        if _tgt_hd >= _src_hd + 3:
            result.passed = False
            result.error = (
                f"Heading surplus gate: source has {_src_hd} headings "
                f"but translation has {_tgt_hd} (+{_tgt_hd - _src_hd})"
            )
            logger.error("HEADING SURPLUS GATE FAILED for %s: %s", output_path.name, result.error)
            return

        if _tgt_body.lstrip().startswith("TITLE:"):
            result.passed = False
            result.error = "Hallucination marker: body starts with 'TITLE:'"
            logger.error("TITLE GATE FAILED for %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 8: YAML frontmatter structural (RC-5/RC-6)
    # ------------------------------------------------------------------

    def _gate_yaml_frontmatter(
        self,
        translated_content: str,
        output_path: Path,
        target_lang: str,
        source_doc: Any,
        result: WriteGateResult,
    ) -> None:
        try:
            import yaml as _pre_write_yaml

            _fm_parts = translated_content.split("---", 2)
            if len(_fm_parts) >= 3:
                _fm_candidate = _fm_parts[1]
                _fm_parsed = _pre_write_yaml.safe_load(_fm_candidate)
                if _fm_parsed is None or not isinstance(_fm_parsed, dict):
                    raise ValueError(f"Frontmatter parsed as {type(_fm_parsed).__name__}, not dict")
                if (
                    source_doc is not None
                    and hasattr(source_doc, "frontmatter")
                    and source_doc.frontmatter
                ):
                    _src_fm_keys = set(source_doc.frontmatter.keys())
                    _out_fm_keys = set(_fm_parsed.keys())
                    if _src_fm_keys != _out_fm_keys:
                        _diff = _src_fm_keys ^ _out_fm_keys
                        raise ValueError(
                            f"Frontmatter key integrity violated: mismatched keys {_diff}"
                        )
            else:
                raise ValueError("Translated content missing YAML frontmatter delimiters")
        except Exception as _fm_gate_err:
            result.passed = False
            result.error = f"Frontmatter structural gate: {_fm_gate_err}"
            result.clear_tm_buffer = True
            result.quarantine_content = translated_content
            result.quarantine_error = str(result.error)
            logger.error(
                "FRONTMATTER STRUCTURAL GATE FAILED for %s: %s",
                output_path.name,
                result.error,
            )

    # ==================================================================
    # Gates 9-17: Content quality gates (unconditional — no force_accept)
    # ==================================================================

    # Latin-script target languages: gate 14 (mixed lang) skips these
    _LATIN_SCRIPT_LANGS: frozenset[str] = frozenset(
        {
            "af",
            "az",
            "bs",
            "ca",
            "cs",
            "cy",
            "da",
            "de",
            "en",
            "es",
            "et",
            "eu",
            "fi",
            "fr",
            "ga",
            "hr",
            "hu",
            "id",
            "it",
            "lt",
            "lv",
            "ms",
            "mt",
            "nl",
            "no",
            "nb",
            "pl",
            "pt",
            "ro",
            "sk",
            "sl",
            "sq",
            "sr",
            "sv",
            "sw",
            "tr",
            "vi",
        }
    )

    # Mission heading-i18n-governance-20260723 (TC-HT-I18N-004 completion):
    # the old shape-only single-capitalized-word-of-4+-letters _IDENTIFIER_RE
    # (matched any such word, not just real multi-hump identifiers) has been
    # retired -- Gate 11 (_gate_frontmatter_id_corruption) now calls the
    # canonical should_protect_as_identifier() from terminology.classification
    # instead.

    # EU/GDPR hallucination patterns
    _EU_HALLUCINATION_PATTERNS: list[re.Pattern[str]] = [
        re.compile(
            r"(?:cookie|GDPR|General Data Protection|privacy policy|data protection)", re.IGNORECASE
        ),
        re.compile(r"(?:European Union|EU regulation|DSGVO|Datenschutz)", re.IGNORECASE),
    ]

    @staticmethod
    def _get_body(content: str) -> str:
        """Extract body (after frontmatter) from a markdown file."""
        parts = content.split("---", 2)
        return parts[2] if len(parts) >= 3 else content

    @staticmethod
    def _contains_corruption(text: str, source_text: str | None = None) -> bool:
        """Universal corruption detector — model-agnostic.

        Detects:
          1. Shortcode leaks: {{< or {{%
          2. Artifact wrappers: { followed by non-ASCII char
          3. Hallucination padding: translation >3x longer than source
        """
        if "{{<" in text or "{{%" in text:
            return True
        if re.search(r"\{[^\x00-\x7F]", text):
            return True
        if source_text is not None and len(source_text) > 0 and len(text) > 3 * len(source_text):
            return True
        return False

    # ------------------------------------------------------------------
    # Registry-driven content gate runner (gates 9+)
    # ------------------------------------------------------------------

    def _build_content_gate_dispatch(
        self,
        target_lang: str,
        output_path: Path,
        source_doc: object,
        translation_stats: object = None,
    ) -> dict[str, object]:
        """Build the signature-normalizing dispatch table shared by
        ``_run_content_gates`` (production write path) and
        ``run_all_content_gates`` (offline audit / healer entry point).

        HT-QUALITY-GATES-001 Phase 8 (F1/F3): this table used to be built
        inline inside ``_run_content_gates`` only, which meant any caller
        that wanted per-gate results outside the production write path
        (an audit sweep, the healer) had no way to invoke a gate by id
        without re-deriving its call signature from scratch -- exactly the
        pattern that produced scripts/quality/audit_all_content.py's
        hand-written per-gate ``WriteGateResult(passed=True)`` blocks,
        which then had to be hand-edited every time a new gate was added
        (root cause RC1: a new registry entry was invisible to the audit
        sweep and the healer until someone remembered a second edit).
        Extracting this table lets every caller share one place where
        signature differences are encoded.

        Each gate has a different signature.  We normalize all of them to the
        common interface ``(src, working, path, result) -> str | None`` via
        explicit lambdas so callers stay uniform.  Auto-clean gates return
        the (possibly modified) content string; blocking/warn gates return
        None.
        """
        return {
            "_gate_heading_integrity": lambda src, w, path, res: self._gate_heading_integrity(
                src, w, path, source_doc, res, target_lang
            ),
            "_gate_frontmatter_backticks": lambda src,
            w,
            path,
            res: self._gate_frontmatter_backticks(w, path, source_doc, res),
            "_gate_frontmatter_id_corruption": lambda src,
            w,
            path,
            res: self._gate_frontmatter_id_corruption(w, path, source_doc, res, target_lang),
            "_gate_double_periods": lambda src, w, path, res: self._gate_double_periods(
                src, w, path, res
            ),
            "_gate_eu_hallucination": lambda src, w, path, res: self._gate_eu_hallucination(
                src, w, path, res
            ),
            "_gate_mixed_language": lambda src, w, path, res: self._gate_mixed_language(
                w, target_lang, path, res
            ),
            "_gate_table_row_integrity": lambda src, w, path, res: self._gate_table_row_integrity(
                src, w, path, res
            ),
            "_gate_duplicate_content": lambda src, w, path, res: self._gate_duplicate_content(
                w, path, res
            ),
            "_gate_newline_explosion": lambda src, w, path, res: self._gate_newline_explosion(
                src, w, path, res
            ),
            "_gate_description_hallucination": lambda src,
            w,
            path,
            res: self._gate_description_hallucination(src, w, path, res),
            "_gate_code_fence_count": lambda src, w, path, res: self._gate_code_fence_count(
                src, w, path, res
            ),
            "_gate_empty_body": lambda src, w, path, res: self._gate_empty_body(src, w, path, res),
            "_gate_shortcode_body_leak": lambda src, w, path, res: self._gate_shortcode_body_leak(
                src, w, path, res
            ),
            "_gate_inline_code_integrity": lambda src,
            w,
            path,
            res: self._gate_inline_code_integrity(src, w, path, res),
            "_gate_encoding_clean": lambda src, w, path, res: self._gate_encoding_clean(
                src, w, path, res
            ),
            "_gate_description_reverted_to_english": lambda src,
            w,
            path,
            res: self._gate_description_reverted_to_english(src, w, target_lang, path, res),
            "_gate_code_block_content_truncated": lambda src,
            w,
            path,
            res: self._gate_code_block_content_truncated(src, w, path, res),
            "_gate_fence_parity": lambda src, w, path, res: self._gate_fence_parity(
                src, w, path, res
            ),
            "_gate_multiline_scalar_preservation": lambda src,
            w,
            path,
            res: self._gate_multiline_scalar_preservation(src, w, target_lang, path, res),
            "_gate_title_identity": lambda src, w, path, res: self._gate_title_identity(
                w, path, target_lang, source_doc, res
            ),
            "_gate_refusal_artifact": lambda src, w, path, res: self._gate_refusal_artifact(
                w, path, res, target_lang
            ),
            "_gate_placeholder_leak": lambda src, w, path, res: self._gate_placeholder_leak(
                w, path, res, target_lang
            ),
            "_gate_partial_script_contamination": lambda src,
            w,
            path,
            res: self._gate_partial_script_contamination(w, path, target_lang, res),
            "_gate_content_hash_staleness": lambda src,
            w,
            path,
            res: self._gate_content_hash_staleness(src, w, path, res),
            "_gate_brand_token_presence": lambda src, w, path, res: self._gate_brand_token_presence(
                src, w, path, res
            ),
            "_gate_heading_deficit": lambda src, w, path, res: self._gate_heading_deficit(
                src, w, path, res
            ),
            "_gate_dropped_trailing_link": lambda src,
            w,
            path,
            res: self._gate_dropped_trailing_link(src, w, path, res),
            "_gate_fidelity_judge": lambda src, w, path, res: self._gate_fidelity_judge(
                src, w, target_lang, path, res, translation_stats
            ),
            "_gate_tm_collision": lambda src, w, path, res: self._gate_tm_collision(
                src, w, path, res
            ),
            "_gate_prose_before_code_dropped": lambda src,
            w,
            path,
            res: self._gate_prose_before_code_dropped(src, w, path, res),
            "_gate_dash_range_collapsed": lambda src, w, path, res: self._gate_dash_range_collapsed(
                src, w, path, res
            ),
            "_gate_seo_metadata_corruption": lambda src,
            w,
            path,
            res: self._gate_seo_metadata_corruption(src, w, path, res),
            "_gate_seo_length_sanity": lambda src, w, path, res: self._gate_seo_length_sanity(
                src, w, path, res
            ),
            "_gate_homoglyph_in_code": lambda src, w, path, res: self._gate_homoglyph_in_code(
                src, w, path, res
            ),
            "_gate_whole_page_language_mismatch": lambda src,
            w,
            path,
            res: self._gate_whole_page_language_mismatch(w, target_lang, path, res),
            "_gate_block_scalar_key_leak": lambda src,
            w,
            path,
            res: self._gate_block_scalar_key_leak(src, w, path, res),
        }

    def _run_content_gates(
        self,
        source_content: str,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        source_doc: object,
        result: WriteGateResult,
        translation_stats: object = None,
    ) -> str:
        """Run all content quality gates (GATE_REGISTRY entries with action
        'auto_clean', 'block', or 'warn') against the production write path's
        single shared ``result``.  Returns the (possibly cleaned) content.

        Short-circuits remaining "block" gates once ``result.passed`` is
        False (no point paying for further checks on a write that's already
        rejected) — this is a production-path optimization NOT shared by
        ``run_all_content_gates`` (offline audit/healer), which always wants
        every gate's independent verdict rather than the first failure.
        """
        dispatch = self._build_content_gate_dispatch(
            target_lang, output_path, source_doc, translation_stats
        )
        working = translated_content

        for gate_id, method_name, _, action in self.GATE_REGISTRY:
            if action not in ("auto_clean", "block", "warn"):
                continue  # skip early_return / no_op entries (handled elsewhere)

            fn = dispatch.get(method_name)
            if fn is None:
                # Method exists (verified by _verify_gate_registry) but has no
                # dispatch entry — call it with the standard signature and log.
                logger.warning(
                    "WriteGate: no dispatch entry for %s — calling with standard args",
                    method_name,
                )
                fn = lambda src, w, path, res, _m=method_name: getattr(self, _m)(src, w, path, res)  # noqa: E731

            gate_result = WriteGateResult(passed=True) if self._zero_defect else result

            if action == "auto_clean":
                new_working = fn(source_content, working, output_path, gate_result)
                if new_working is not None:
                    working = new_working
            elif action == "warn":
                # Log-only: run against a disposable result so a bug in a
                # log-only gate can never flip the real result.passed and
                # accidentally become blocking. See HT-QUALITY-GATES-001
                # plan Part 8 — every new gate ships log-only first.
                warn_result = gate_result if self._zero_defect else WriteGateResult(passed=True)
                fn(source_content, working, output_path, warn_result)
                gate_result = warn_result
            else:  # "block"
                if not result.passed:
                    continue  # short-circuit: stop on first blocking failure
                fn(source_content, working, output_path, gate_result)

            if self._zero_defect:
                # A rollout-tier warn gate is still evaluated independently,
                # but campaign policy promotes it to a blocking acceptance
                # gate.  Record the promoted action as well: a final receipt
                # must never describe any gate as a warning.
                receipt_action = "block" if action == "warn" else action
                result.gate_results[gate_id] = {
                    "passed": gate_result.passed,
                    "action": receipt_action,
                    "error": gate_result.error,
                }
                if gate_id == 36 and hasattr(gate_result, "_fidelity_result"):
                    # Preserve the independent judge evidence on the aggregate
                    # fixed-point result.  The per-gate result is otherwise
                    # disposable, which previously retained only its boolean
                    # and made a model-bound fidelity PASS impossible to prove
                    # in an acceptance receipt or receipt recovery.
                    result._fidelity_result = dict(  # type: ignore[attr-defined]
                        gate_result._fidelity_result  # type: ignore[attr-defined]
                    )
                if not gate_result.passed:
                    result.passed = False
                    result.error = gate_result.error or f"Gate {gate_id} failed"
                    result.clear_tm_buffer = result.clear_tm_buffer or gate_result.clear_tm_buffer
                    result.retranslate_paths.extend(gate_result.retranslate_paths)

        return working

    def run_all_content_gates(
        self,
        source_content: str,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        source_doc: object = None,
        translation_stats: object = None,
    ) -> tuple[dict[int, WriteGateResult], str]:
        """Run every GATE_REGISTRY content gate (action 'auto_clean',
        'block', or 'warn') against ``(source_content, translated_content)``
        and return ``({gate_id: WriteGateResult}, final_content)`` — one
        independent, REAL (never discarded) result per gate, so one gate's
        failure never masks or short-circuits another's, and — critically,
        unlike ``evaluate()``/``_run_content_gates()`` — a "warn"-action
        gate's verdict is NOT thrown away here. ``evaluate()`` intentionally
        discards warn-tier verdicts for the PRODUCTION write path (a bug in
        a brand-new gate must never start blocking real writes); this method
        exists precisely for callers that need the opposite guarantee —
        knowing whether a specific gate, warn-tier or not, actually still
        fails. ``final_content`` is ``translated_content`` with every
        ``auto_clean`` gate's fix applied, in registry order (mirrors
        ``_run_content_gates``'s ``working`` accumulator).

        HT-QUALITY-GATES-001 Phase 8 (F1/F3): this is the single shared
        entry point for anything that wants a per-gate finding list without
        hand-writing a ``WriteGateResult(passed=True)`` block per gate id —
        the offline audit sweep (scripts/quality/audit_all_content.py) and
        the healer's gate-rerun path (scripts/quality/unit_heal.py's
        ``_heal_via_gate_rerun``) both call this. A new GATE_REGISTRY entry
        is automatically visible to every caller of this method with zero
        edits elsewhere, closing root cause RC1 (a gate could be live in
        production/healing but invisible to the audit sweep unless someone
        remembered a second, hand-written edit).

        Using ``evaluate()`` instead of this method for a "does this gate
        STILL fail" check is a real bug, not a style choice: because
        ``evaluate()`` routes every warn-tier gate through a disposable
        result, a caller checking the returned ``WriteGateResult.passed``
        will ALWAYS see ``True`` regardless of whether a warn-tier gate
        (31-35, 37-43 as of this writing) still fails — silently
        reproducing RC2 ("gate finding never reaches an actual fix")
        through a different mechanism. Confirmed via direct reproduction
        during this session's independent verification pass and fixed by
        switching ``unit_heal.py``'s ``_heal_via_gate_rerun`` to this method.

        Gates 2-8 (action "early_return") and gate 5 (action "no_op") are
        deliberately excluded — they need cross-file state (an existing
        output-path comparison, ``force_overwrite``, ``site_profile``) that
        isn't meaningful outside the live write path, and were never part of
        the audit sweep's coverage either.
        """
        dispatch = self._build_content_gate_dispatch(
            target_lang, output_path, source_doc, translation_stats
        )
        results: dict[int, WriteGateResult] = {}
        working = translated_content

        for gate_id, method_name, _category, action in self.GATE_REGISTRY:
            if action not in ("auto_clean", "block", "warn"):
                continue

            fn = dispatch.get(method_name)
            if fn is None:
                fn = lambda src, w, path, res, _m=method_name: getattr(self, _m)(src, w, path, res)  # noqa: E731

            gate_result = WriteGateResult(passed=True)
            outcome = fn(source_content, working, output_path, gate_result)
            if action == "auto_clean" and outcome is not None:
                working = outcome
            results[gate_id] = gate_result

        return results, working

    # ------------------------------------------------------------------
    # Gate 9: Heading integrity (source-comparison, auto-clean)
    # ------------------------------------------------------------------

    def _gate_heading_integrity(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        source_doc: object,
        result: WriteGateResult,
        target_lang: str,
    ) -> str:
        """Auto-clean corrupted headings; flag untranslated known heading terms.

        Mission heading-i18n-governance-20260723 (TC-HT-I18N-004 completion):
        the known-term set is every id in the canonical i18n template-string
        registry (config/i18n/template_strings/) — replacing this gate's
        former locally-hardcoded 20-term frozenset, which never covered the
        "section heading" terms (Overview, Enumerations, Options, ...) at
        all, so this gate silently had zero visibility into corruption/
        untranslated-status for those terms. The registry is a strict
        coverage expansion over that old list (verified superset), and any
        future review-cycle addition to the registry is picked up here
        automatically, with no code change needed.

        Also fixes the plan's §1 root-cause finding: an untranslated known
        heading term used to be accepted completely silently (debug-only
        log, no metric, no follow-up). Now logged at `warning` (visible)
        and queued via the same `result.retranslate_paths` mechanism every
        other auto-clean gate in this file already uses to request another
        translation pass -- this file's own established idiom for "flag
        for retry," not a new mechanism. Still deliberately non-blocking
        (`result.passed` is untouched): one bad heading should not fail an
        entire file's translation, per the plan's own tradeoff reasoning.

        Note: this cannot literally re-invoke the MT model here -- Gate 9
        runs on already-produced, static content with no model handle.
        A same-request retry would need to live upstream in
        segment_translator.py's translation loop; requeueing via
        `retranslate_paths` is the closest equivalent this gate can offer
        and is consistent with how every other gate in this file signals
        "this needs another pass."
        """
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        src_headings = re.findall(r"^(#{1,6})\s+(.+)$", src_body, re.MULTILINE)
        tgt_headings = re.findall(r"^(#{1,6})\s+(.+)$", tgt_body, re.MULTILINE)

        if len(src_headings) != len(tgt_headings):
            # Count mismatch already handled by gate 7; skip positional check
            return translated_content

        known_heading_terms = self._template_registry.by_en_text.keys()

        working = translated_content
        cleaned_count = 0
        untranslated_terms: list[str] = []
        for (s_level, s_text), (t_level, t_text) in zip(src_headings, tgt_headings):
            s_stripped = s_text.strip()
            t_stripped = t_text.strip()
            if s_stripped in known_heading_terms:
                if t_stripped == s_stripped:
                    # Model returned heading unchanged (failed to translate).
                    # Content is already English -- no modification needed,
                    # but this is now visible and queued for retry (see
                    # docstring), not silently swallowed at debug level.
                    untranslated_terms.append(s_stripped)
                elif self._contains_corruption(t_stripped, s_stripped):
                    old_line = f"{t_level} {t_text}"
                    new_line = f"{s_level} {s_text.strip()}"
                    working = working.replace(old_line, new_line, 1)
                    cleaned_count += 1

        if cleaned_count:
            logger.info(
                "GATE9 auto-cleaned %d corrupted heading(s) in %s",
                cleaned_count,
                output_path.name,
            )
        if untranslated_terms:
            logger.warning(
                "GATE9 %d known heading term(s) untranslated (model returned "
                "source) in %s for target_lang=%s — English retained, queued "
                "for retranslation: %s",
                len(untranslated_terms),
                output_path.name,
                target_lang,
                untranslated_terms,
            )
            result.retranslate_paths.append((output_path, target_lang))
        return working

    # ------------------------------------------------------------------
    # Gate 10: Frontmatter broken backticks (auto-clean)
    # ------------------------------------------------------------------

    def _gate_frontmatter_backticks(
        self,
        translated_content: str,
        output_path: Path,
        source_doc: object,
        result: WriteGateResult,
    ) -> str:
        """Auto-fix odd backtick counts in frontmatter title/description/summary/linkTitle.

        Parses the frontmatter into a CommentedMap and re-serializes via
        YAMLFormatter instead of string-slicing around a literal '---' split
        (TC-HT-001) — the old approach could not correctly handle multi-line/
        folded scalar values and produced malformed YAML on edge cases.
        """
        split = _fm_parser._split_frontmatter(translated_content)
        if split is None:
            return translated_content
        yaml_text, body = split
        data = _fm_parser._parse_yaml_content(yaml_text)
        if not isinstance(data, dict):
            return translated_content

        changed = False
        for field_name in ("title", "description", "summary", "linkTitle"):
            val = data.get(field_name)
            if not isinstance(val, str):
                continue
            if val.count("`") % 2 == 1:
                fixed_val = val + "`"
                data[field_name] = fixed_val
                changed = True
                logger.info(
                    "GATE10 fixed odd backtick in %s.%s: %r → %r",
                    output_path.name,
                    field_name,
                    val,
                    fixed_val,
                )

        if not changed:
            return translated_content
        try:
            return YAMLFormatter.format_frontmatter(data) + body
        except ValueError:
            # Re-serialization produced invalid YAML — leave content untouched
            # rather than risk writing a malformed file.
            logger.warning(
                "GATE10 re-serialization failed for %s; leaving content unmodified",
                output_path.name,
            )
            return translated_content

    # ------------------------------------------------------------------
    # Gate 11: Frontmatter ID/class corruption (auto-clean)
    # ------------------------------------------------------------------

    def _gate_frontmatter_id_corruption(
        self,
        translated_content: str,
        output_path: Path,
        source_doc: object,
        result: WriteGateResult,
        target_lang: str,
    ) -> str:
        """Restore English API identifier in title/linkTitle if translation corrupted it.

        Mission heading-i18n-governance-20260723 (TC-HT-I18N-004 completion):
        the shape-only `_IDENTIFIER_RE` check (matches any single capitalized
        word of 4+ letters, not just real multi-hump identifiers) is replaced
        by `should_protect_as_identifier()`, the canonical classifier used
        everywhere else this decision is made. This is strictly more
        accurate, not just a rename: `_IDENTIFIER_RE` alone could never
        distinguish "Camera" (protect) from "Overview" (a reviewed, approved
        translation) -- both match the same regex shape. The canonical
        classifier checks the i18n table first, so a frontmatter value that
        happens to equal an approved template-string term is no longer
        force-treated as an untouchable identifier.
        """
        if source_doc is None or not hasattr(source_doc, "frontmatter"):
            return translated_content

        fm = getattr(source_doc, "frontmatter", {}) or {}
        parts = translated_content.split("---", 2)
        if len(parts) < 3:
            return translated_content

        fm_text = parts[1]
        cleaned_fm = fm_text

        for field_name in ("title", "linkTitle"):
            en_val = fm.get(field_name, "")
            if not en_val or not isinstance(en_val, str):
                continue
            en_str = str(en_val).strip()
            if not should_protect_as_identifier(
                en_str, target_lang, registry=self._template_registry
            ):
                continue  # Not a protected identifier — don't force-restore

            # Find translated value
            m = re.search(
                r"^(" + re.escape(field_name) + r":\s*[\"']?)(.+?)([\"']?\s*)$",
                cleaned_fm,
                re.MULTILINE,
            )
            if not m:
                continue
            tr_val = m.group(2).strip().strip('"').strip("'")
            if tr_val == en_str:
                continue  # Already correct

            # Corrupted: replace with English value
            old_line = m.group(0)
            new_line = f"{field_name}: {en_str}"
            cleaned_fm = cleaned_fm.replace(old_line, new_line, 1)
            logger.info(
                "GATE11 restored %s in %s: %r → %r",
                field_name,
                output_path.name,
                tr_val,
                en_str,
            )

        if cleaned_fm == fm_text:
            return translated_content
        return parts[0] + "---" + cleaned_fm + "---" + parts[2]

    # ------------------------------------------------------------------
    # Gate 12: Double period detection (auto-clean)
    # ------------------------------------------------------------------

    def _gate_double_periods(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> str:
        """Replace .. (not ...) in body text outside code blocks."""
        body = self._get_body(translated_content)
        # Only process if source doesn't contain ".." (don't introduce bugs)
        if ".." in self._get_body(source_content):
            return translated_content

        # Split on code fences, only process non-code segments
        segments = re.split(r"(```[\s\S]*?```)", body)
        cleaned_segments = []
        changed = False
        for seg in segments:
            if seg.startswith("```"):
                cleaned_segments.append(seg)
            else:
                # Replace ".." not part of "..."
                fixed = re.sub(r"(?<!\.)\.\.(?!\.)", ".", seg)
                if fixed != seg:
                    changed = True
                cleaned_segments.append(fixed)

        if not changed:
            return translated_content

        cleaned_body = "".join(cleaned_segments)
        fm_prefix = translated_content[: len(translated_content) - len(body)]
        logger.info("GATE12 fixed double periods in %s", output_path.name)
        return fm_prefix + cleaned_body

    # ------------------------------------------------------------------
    # Gate 13: EU hallucination detection (BLOCKING)
    # ------------------------------------------------------------------

    def _gate_eu_hallucination(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block if EU/GDPR text appears in translation but not in source."""
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        for pattern in self._EU_HALLUCINATION_PATTERNS:
            if pattern.search(tgt_body) and not pattern.search(src_body):
                result.passed = False
                result.error = f"Gate 13 EU hallucination: pattern {pattern.pattern!r} in translation but not in source"
                logger.error("GATE13 BLOCKED %s: %s", output_path.name, result.error)
                return

    # ------------------------------------------------------------------
    # Gate 14: Mixed language line detection (BLOCKING)
    # ------------------------------------------------------------------

    def _gate_mixed_language(
        self,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block if >3 untranslated English-only lines found in non-Latin-script target."""
        if target_lang in self._LATIN_SCRIPT_LANGS:
            return  # Latin-script target — English lines are expected/acceptable

        body = self._get_body(translated_content)
        lines = body.splitlines()
        _ascii_word_re = re.compile(r"^[A-Za-z0-9\s.,;:!?\-'\"()\[\]{}@#$%^&*+=/<>|~`_\\]+$")
        _min_words = 5
        untranslated_count = 0
        in_code_block = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            # Check headings explicitly before length/word-count filters.
            # Short API headings like "## Methods" (10 chars, 2 words) are bypassed
            # by the < 20 char and < 5 word checks below, but they MUST be translated
            # in non-Latin-script locales.
            if stripped.startswith("#"):
                m = re.match(r"^#{1,6}\s+(.+)$", stripped)
                if m:
                    heading_text = m.group(1).strip()
                    # Pure ASCII heading in a non-Latin locale = untranslated
                    if re.fullmatch(r"[A-Za-z0-9\s.,\-_()'\"]+", heading_text):
                        untranslated_count += 1
                continue  # heading lines handled above; skip main loop
            if len(stripped) < 20:
                continue
            if stripped.startswith("|"):
                # Check table description cells for English prose
                # Pattern: | `ClassName` | Description sentence in English. |
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if len(cells) >= 2:
                    desc = cells[-1]
                    # Remove inline code spans from description
                    desc_clean = re.sub(r"`[^`]+`", "", desc).strip()
                    # Separator rows (| --- | --- |) and short cells are skipped
                    if (
                        len(desc_clean) >= 25
                        and not re.fullmatch(r":?-+:?", desc_clean)
                        and _ascii_word_re.fullmatch(desc_clean)
                    ):
                        # Count lowercase English words; skip if mostly identifiers
                        words = desc_clean.split()
                        lower_en = sum(1 for w in words if re.match(r"^[a-z]{3,}$", w))
                        if len(words) >= 4 and lower_en / len(words) >= 0.4:
                            untranslated_count += 1
                continue  # table row (description check done above)
            if stripped.startswith("{{"):
                continue  # shortcode
            if len(stripped.split()) < _min_words:
                continue
            if _ascii_word_re.fullmatch(stripped):
                untranslated_count += 1

        if untranslated_count > 3:
            result.passed = False
            result.error = (
                f"Gate 14 mixed language: {untranslated_count} untranslated English lines "
                f"in {target_lang} translation"
            )
            logger.error("GATE14 BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 15: Table row count integrity (BLOCKING)
    # ------------------------------------------------------------------

    def _gate_table_row_integrity(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block if table row count differs by >50% from source."""
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        def _count_table_rows(text: str) -> int:
            count = 0
            in_code = False
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("```"):
                    if in_code:
                        # Closing fence — exit code mode
                        in_code = False
                    elif stripped != "```":
                        # Opening fence with language tag — enter code mode
                        in_code = True
                    # else: bare ``` when not in code → stray/orphaned closer
                    # (e.g. model dropped opening fence but kept closer); ignore
                    # so it doesn't falsely suppress table rows that follow
                    continue
                if not in_code and stripped.startswith("|") and stripped.endswith("|"):
                    count += 1
            return count

        from src.translation_engine.parser.hugo_parser import normalize_table_cells

        src_rows = _count_table_rows(normalize_table_cells(src_body))
        tgt_rows = _count_table_rows(normalize_table_cells(tgt_body))

        if src_rows < 4:
            return  # Too few rows to be meaningful

        if tgt_rows < src_rows * 0.5 or tgt_rows > src_rows * 2:
            result.passed = False
            result.error = (
                f"Gate 15 table integrity: source={src_rows} rows, "
                f"translation={tgt_rows} rows (ratio={tgt_rows / max(src_rows, 1):.2f})"
            )
            logger.error("GATE15 BLOCKED %s: %s", output_path.name, result.error)
            if src_rows >= 4:
                # Dump full translated content to temp file for diagnosis
                import os as _os
                import tempfile

                _dump_path = _os.path.join(tempfile.gettempdir(), f"gate15_dump_{output_path.name}")
                try:
                    with open(_dump_path, "w", encoding="utf-8") as _f:
                        _f.write(f"=== tgt_rows={tgt_rows} src_rows={src_rows} ===\n")
                        _f.write(f"=== tgt_body (len={len(tgt_body)}) ===\n")
                        _f.write(tgt_body)
                        _f.write(f"\n=== translated_content (len={len(translated_content)}) ===\n")
                        _f.write(translated_content)
                except Exception as _e:
                    logger.debug("GATE15 DUMP FAILED: %s", _e)

    # ------------------------------------------------------------------
    # Gate 16: Duplicate content detection (auto-clean)
    # ------------------------------------------------------------------

    def _gate_duplicate_content(
        self,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> str:
        """Remove paragraphs that appear 3+ times (model repetition artifact).

        Two exclusions keep this from stripping legitimate content:

        - Paragraphs that overlap a fenced code block are never eligible:
          distinct code examples on the same page routinely share a short
          boilerplate opening line (an import/#include right after the
          fence, separated from the rest of the snippet by a blank line),
          and without this exclusion those shared lines get miscounted as
          "the same paragraph repeated" and stripped out of otherwise-
          correct, distinct examples.
        - A duplicate is also excluded if a heading appears between every
          consecutive pair of its occurrences: this is the signature of
          legitimate structural repetition (e.g. a "Returns: same X
          instance for chaining" note, or a "Key Properties" label,
          repeated once per distinct method/property/class section on a
          reference.aspose.org API-reference page) -- a genuine MT
          decoding-loop artifact has no such intervening structure between
          repeats. A code fence between occurrences is deliberately NOT
          treated as sufficient separation on its own: a decoding-loop
          repeat could plausibly interleave with unrelated code blocks, so
          only an actual section-heading change counts as evidence of
          distinct structural context (verified: all 20 known real
          legitimate cases from mission duplicate-content-fence-fix-20260723
          are heading-separated, not merely fence-separated).
        """
        body = self._get_body(translated_content)
        heading_spans = [(m.start(), m.end()) for m in re.finditer(r"^#{1,6}[ \t].*$", body, re.M)]

        def has_structural_boundary_between(a: int, b: int) -> bool:
            return any(a <= s < b for s, _ in heading_spans)

        # Split on fence boundaries first, then blank lines within each
        # non-fence chunk. Splitting on blank lines first and only
        # afterward checking fence overlap (the earlier approach) would
        # silently merge a paragraph that directly abuts a fence with no
        # blank line into the fence itself, losing it from detection
        # entirely -- either missing genuine 3x corruption that happens to
        # sit right after a fence, or (when protection is involved) failing
        # to recognize a legitimate fence-adjacent occurrence as one of the
        # structurally-separated repeats.
        paragraphs: list[tuple[str, int, int, bool]] = []  # (text, start, end, is_fence)
        offset = 0
        for chunk in re.split(r"(```[\s\S]*?```)", body):
            if chunk.startswith("```"):
                paragraphs.append((chunk, offset, offset + len(chunk), True))
            else:
                pos = 0
                for m in re.finditer(r"\n{2,}", chunk):
                    paragraphs.append(
                        (chunk[pos : m.start()], offset + pos, offset + m.start(), False)
                    )
                    pos = m.end()
                paragraphs.append((chunk[pos:], offset + pos, offset + len(chunk), False))
            offset += len(chunk)

        # Normalize, count, and track occurrence positions -- only paragraphs
        # outside code fences are eligible.
        seen: dict[str, int] = {}
        occurrence_starts: dict[str, list[int]] = {}
        for para, start, end, is_fence in paragraphs:
            if is_fence:
                continue
            key = re.sub(r"\s+", " ", para.strip())
            if len(key) > 30:  # Only meaningful paragraphs
                seen[key] = seen.get(key, 0) + 1
                occurrence_starts.setdefault(key, []).append(start)

        def structurally_separated(key: str) -> bool:
            starts = sorted(occurrence_starts.get(key, []))
            if len(starts) < 2:
                return False
            return all(
                has_structural_boundary_between(starts[i], starts[i + 1])
                for i in range(len(starts) - 1)
            )

        duplicates = {k for k, v in seen.items() if v >= 3 and not structurally_separated(k)}
        if not duplicates:
            return translated_content

        # Keep only first occurrence of each duplicate
        kept: set[str] = set()
        cleaned_paragraphs = []
        for para, start, end, is_fence in paragraphs:
            if is_fence:
                cleaned_paragraphs.append(para)
                continue
            key = re.sub(r"\s+", " ", para.strip())
            if key in duplicates:
                if key not in kept:
                    kept.add(key)
                    cleaned_paragraphs.append(para)
                # else: skip duplicate
            else:
                cleaned_paragraphs.append(para)

        cleaned_body = "\n\n".join(cleaned_paragraphs)
        fm_prefix = translated_content[: len(translated_content) - len(body)]
        logger.info(
            "GATE16 removed %d duplicate paragraph(s) in %s",
            len(duplicates),
            output_path.name,
        )
        return fm_prefix + cleaned_body

    # ------------------------------------------------------------------
    # Gate 17: Newline explosion detection (BLOCKING)
    # ------------------------------------------------------------------

    def _gate_newline_explosion(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block if translated body has >2.5x the newline count of source body."""
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        src_lines = src_body.count("\n")
        tgt_lines = tgt_body.count("\n")

        if src_lines < 10:
            return  # Too short to be meaningful

        ratio = tgt_lines / max(src_lines, 1)
        if ratio > 2.5:
            result.passed = False
            result.error = (
                f"Gate 17 newline explosion: source={src_lines} lines, "
                f"translation={tgt_lines} lines (ratio={ratio:.1f}x)"
            )
            logger.error("GATE17 BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 18: Description hallucination detection (BLOCKING)
    # ------------------------------------------------------------------

    def _gate_description_hallucination(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block if translated description is >3x longer than source description.

        Hallucinated descriptions balloon 3-10x because the model generates
        additional explanatory text instead of translating the original concisely.
        Short source descriptions (< 30 chars) are excluded to avoid false positives
        on brief stubs like 'Gets the value.' that may have verbose translations.

        Parses frontmatter via HugoParser rather than a first-line regex
        (TC-HT-001), so multi-line folded/literal scalars are compared by
        their full value instead of being truncated to the first line.
        """
        src_desc = _get_frontmatter_field(source_content, "description")
        tgt_desc = _get_frontmatter_field(translated_content, "description")
        if not src_desc or not tgt_desc:
            return
        if len(src_desc) < 30:
            return  # too short for reliable ratio
        ratio = len(tgt_desc) / len(src_desc)
        if ratio > 3.0:
            result.passed = False
            result.error = (
                f"Gate 18 description hallucination: tgt={len(tgt_desc)}ch "
                f"vs src={len(src_desc)}ch (ratio={ratio:.1f}x)"
            )
            logger.error("GATE18 BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 19: Code fence count check (BLOCKING)
    # ------------------------------------------------------------------

    def _gate_code_fence_count(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block if translated body has fewer fenced code blocks than source.

        Models in the legacy fallback path drop opening ``` fences, leaving
        code as plain paragraph text.  Require at least as many fences in the
        translation as in the source (allow one missing block as tolerance).
        Only fires when source has ≥4 fences (≥2 code blocks).
        """
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        # Count ``` fence lines (opening or closing)
        src_fences = sum(1 for ln in src_body.splitlines() if ln.strip().startswith("```"))
        tgt_fences = sum(1 for ln in tgt_body.splitlines() if ln.strip().startswith("```"))

        if src_fences < 4:
            return  # too few to be meaningful; single-block files are ok

        # Allow up to 1 missing fence pair (opening + closing = 2 fences)
        if tgt_fences < src_fences - 2:
            result.passed = False
            result.error = (
                f"Gate 19 code fence loss: src={src_fences} fences, "
                f"tgt={tgt_fences} fences (lost {src_fences - tgt_fences})"
            )
            logger.error("GATE19 BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 17 (TC-HDN-010): Shortcode body leak
    # ------------------------------------------------------------------

    def _gate_shortcode_body_leak(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block writes where {{< or {{% appear in tgt body but NOT in en source.

        Shortcodes that are correctly preserved should exist in both source and
        translation. If they appear ONLY in the translation, the model reproduced
        or corrupted a shortcode token.
        """
        tgt_body = self._get_body(translated_content)
        if not _SHORTCODE_GATE_RE.search(tgt_body):
            return
        src_body = self._get_body(source_content)
        if _SHORTCODE_GATE_RE.search(src_body):
            return  # shortcode exists in EN source — correctly preserved, not a leak
        result.passed = False
        result.error = (
            "Gate 20 shortcode body leak: {{< or {{% in translated body but not in EN source"
        )
        logger.error("GATE20 BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 18 (TC-HDN-010): Inline code integrity
    # ------------------------------------------------------------------

    def _gate_inline_code_integrity(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block writes where ASCII backtick spans in EN were translated to non-ASCII.

        Zero tolerance: any `code` span that was ASCII in English must remain
        ASCII in the translation. Only fires when EN has ≥3 inline code spans.

        HT-INLINE-CODE-001 TC-ICR-004: detection delegated to the shared
        src/translation_engine/quality/inline_code_repair.py primitive
        (single source of truth also used by audit_all_content.py,
        UnitQualityScorer, and audit_blog_bundle.py) instead of this gate's
        own copy of the fence-strip/newline-exclude logic, plus a new
        span-count-parity guard that copy never had: if EN and TR backtick
        span counts differ, positional pairing is unreliable and this gate
        now declines to fire rather than risk a false block on drifted
        pairing (other structural gates -- code block count, heading
        surplus -- independently catch genuine structural drift).
        """
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        # Strip stray leading backticks from table rows (m2m100 artifact: "` | Чтение |").
        # These cause the span regex to manufacture a cross-row "span" containing
        # Cyrillic table content, triggering a false positive against ASCII en_spans.
        # This is a real content fix, so it's applied to (and persisted from) the
        # fenced body -- unlike the fence stripping the shared primitive does
        # internally, which is comparison-only.
        tgt_body_clean = _STRAY_TABLE_BACKTICK_RE.sub(r"\1", tgt_body)
        if tgt_body_clean != tgt_body:
            result.cleaned_content = translated_content.replace(tgt_body, tgt_body_clean, 1)
            tgt_body = tgt_body_clean

        mismatches = find_inline_code_mismatches(src_body, tgt_body)
        if not mismatches:
            return  # clean, or too few spans, or count mismatch (see docstring)

        first = mismatches[0]
        result.passed = False
        result.error = (
            f"Gate 21 inline code translated: `{first.en_span[:40]}` → `{first.tr_span[:40]}`"
        )
        # HT-INLINE-CODE-001 TC-ICR-005: explicit defense-in-depth alongside
        # file_pipeline.py's TC-11 buffer, which already gates the flush of
        # `_tm_write_buffer` on `validation_passed` overall (this gate
        # failing already sets that False) -- matches the existing
        # precedent on Gates 4/8.
        result.clear_tm_buffer = True
        logger.error("GATE21 BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 19 (TC-HDN-010): Empty body
    # ------------------------------------------------------------------

    def _gate_empty_body(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block writes where translated body is near-empty while EN body is substantial."""
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)
        if len(tgt_body.strip()) < 50 and len(src_body.strip()) > 200:
            result.passed = False
            result.error = (
                f"Gate 19 empty body: tgt={len(tgt_body.strip())} chars "
                f"vs src={len(src_body.strip())} chars"
            )
            logger.error("GATE19b BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 22 (TC-HDN-002): Encoding clean / mojibake detector
    # ------------------------------------------------------------------

    def _gate_encoding_clean(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block writes where translated body contains cp1252 mojibake sequences.

        Even with repair_mojibake() in loader.py, this gate provides a second
        layer of defence for any patterns that slip through the repair map.
        """
        tgt_body = self._get_body(translated_content)
        m = _MOJIBAKE_GATE_RE.search(tgt_body)
        if m:
            result.passed = False
            result.error = (
                f"Gate 22 encoding corruption: mojibake pattern {m.group()!r} found in body"
            )
            logger.error("GATE22 BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 24: Description reverted to English
    # ------------------------------------------------------------------

    def _gate_description_reverted_to_english(
        self,
        source_content: str,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block writes where description: frontmatter is ASCII-only in non-Latin locales.

        If EN description is >30 chars and the target locale uses non-Latin script,
        a fully ASCII translated description means either (a) the model copied the EN
        value verbatim, or (b) a heal run wrote body only and left stale EN frontmatter.
        Both cases must be blocked so the shard retranslates properly.

        Parses frontmatter via HugoParser rather than a first-line regex
        (TC-HT-001), so multi-line folded/literal scalars are compared by
        their full value instead of being truncated to the first line.
        """
        if target_lang not in _NON_LATIN_SCRIPT_LOCALES:
            return
        src_desc = _get_frontmatter_field(source_content, "description")
        if not src_desc or len(src_desc.strip()) < 20:
            return  # short source description — not enough signal
        tgt_desc = _get_frontmatter_field(translated_content, "description")
        if not tgt_desc:
            return
        tgt_desc = tgt_desc.strip()
        if not tgt_desc:
            return
        if tgt_desc.isascii():
            result.passed = False
            result.error = (
                f"Gate 24 description reverted to English: "
                f"'{tgt_desc[:60]}' is ASCII-only in non-Latin locale {target_lang}"
            )
            logger.error("GATE24 BLOCKED %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 25: Code block content truncated
    # ------------------------------------------------------------------

    def _gate_code_block_content_truncated(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block writes where a translated code block lost >30% of its lines.

        Models truncate long code blocks at context limits, losing the last N lines.
        This causes rendered pages to show incomplete examples.  Only fires when
        source block has ≥10 lines (avoids noise on trivial snippets).
        """
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        src_blocks = _CODE_BLOCK_CONTENT_RE.findall(src_body)
        tgt_blocks = _CODE_BLOCK_CONTENT_RE.findall(tgt_body)

        for i, (src_block, tgt_block) in enumerate(zip(src_blocks, tgt_blocks)):
            src_lines = len([l for l in src_block.splitlines() if l.strip()])
            if src_lines < 10:
                continue  # too small to judge
            tgt_lines = len([l for l in tgt_block.splitlines() if l.strip()])
            if tgt_lines < src_lines * 0.70:
                result.passed = False
                result.error = (
                    f"Gate 25 code block truncated: block #{i + 1} "
                    f"has {tgt_lines} lines vs source {src_lines} lines "
                    f"({tgt_lines / max(src_lines, 1) * 100:.0f}% retained)"
                )
                logger.error("GATE25 BLOCKED %s: %s", output_path.name, result.error)
                return

    # ------------------------------------------------------------------
    # Gate 26: Fence parity (zero-tolerance code fence loss)
    # ------------------------------------------------------------------

    def _gate_fence_parity(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block when target fence-line count is odd, less than source, or a
        fence was reopened mid-snippet (HT-QUALITY-GATES-001 Phase 8, Tier
        A #7).

        TC-HT-005: Gate 19 only fires when src has >=4 fences AND target lost
        more than one fence pair — small files and small losses pass through.
        Gate 26 is zero-tolerance: any fence-line loss, or an odd fence-line
        count (an unterminated/dangling fence), blocks the write. This closes
        the wave-3 Bug B corruption class (silently dropped opening fences)
        independently of Gate 19's threshold. Gate 19 is kept alongside this
        gate (its condition is a strict subset) rather than removed, to avoid
        touching its own passing test suite for no functional gain.

        Phase 8 addition: a reopened fence (a duplicate opening marker
        emitted mid-snippet instead of a real close) is invisible to the
        line-COUNT checks above -- the total can come out even, or even
        equal to or greater than the source's count, so neither the odd-
        count nor the fence-loss condition fires. This is exactly why a
        naive count/toggle-based check (used elsewhere in this codebase,
        e.g. hugo_parser.normalize_table_cells) can never catch this shape;
        ``fence_spans.count_fence_open_reopens`` uses the real markdown-it
        tokenizer's own fence-matching to detect it directly (see that
        function's docstring for the CommonMark reasoning).
        """
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        src_fences = sum(1 for ln in src_body.splitlines() if ln.strip().startswith("```"))
        tgt_fences = sum(1 for ln in tgt_body.splitlines() if ln.strip().startswith("```"))

        if tgt_fences % 2 == 1 or tgt_fences < src_fences:
            result.passed = False
            result.error = (
                f"Gate 26 fence parity: src={src_fences} fences, tgt={tgt_fences} fences "
                f"({'odd count' if tgt_fences % 2 == 1 else 'fence loss'})"
            )
            logger.error("GATE26 BLOCKED %s: %s", output_path.name, result.error)
            return

        reopens = count_fence_open_reopens(tgt_body)
        if reopens > count_fence_open_reopens(src_body):
            result.passed = False
            result.error = (
                f"Gate 26 fence parity: target has a fence reopened mid-snippet "
                f"(duplicated opening marker with no intervening close) not present "
                f"in source ({reopens} vs {count_fence_open_reopens(src_body)})"
            )
            logger.error("GATE26 BLOCKED (reopened fence) %s: %s", output_path.name, result.error)

    # ------------------------------------------------------------------
    # Gate 27: Multi-line frontmatter scalar preservation
    # ------------------------------------------------------------------

    @staticmethod
    def _is_multiline_source_field(yaml_text: str, field_name: str) -> bool:
        """True if field_name's value spans more than one physical line in
        the RAW source YAML text (folded '>' scalars parse to a single joined
        string with no embedded '\\n', so this must scan raw text, not the
        parsed value, to catch them)."""
        lines = yaml_text.splitlines()
        start = None
        for i, line in enumerate(lines):
            if re.match(r"^" + re.escape(field_name) + r":", line):
                start = i
                break
        if start is None:
            return False
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if re.match(r"^[A-Za-z_][\w.-]*:", lines[j]):
                end = j
                break
        return (end - start) > 1

    def _gate_multiline_scalar_preservation(
        self,
        source_content: str,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Block writes that lose/corrupt a multi-line frontmatter scalar.

        TC-HT-005: for every translated field whose SOURCE value was written
        as a multi-line/folded YAML scalar, the target field must parse,
        be non-empty, retain at least half the source length, and (for
        non-English targets) not be byte-identical to the English source —
        the exact signature of the wave-3 description-truncation bug.

        HT-QUALITY-GATES-001 Part 25: the 0.5 ratio has no language
        awareness, and Chinese is logographically far more compact than
        English -- a complete, accurate `zh` translation legitimately runs
        well under half the English character count. Confirmed real via
        direct reproduction (not assumed): 25 blocks across a full
        products.aspose.org retranslation pass, overwhelmingly 35-55%
        ratios, blocking the ENTIRE file write (not just the over-short
        field) and leaving stale pre-mission content in place indefinitely.
        `ja`/`ko` (also logographic/syllabic, denser than English) confirmed
        to need the same lower bar via direct reproduction (Part 26) rather
        than assumed at the same time as `zh`.
        """
        src_split = _fm_parser._split_frontmatter(source_content)
        tgt_split = _fm_parser._split_frontmatter(translated_content)
        if src_split is None or tgt_split is None:
            return
        src_yaml_text, _ = src_split
        src_data = _fm_parser._parse_yaml_content(src_yaml_text)
        tgt_data = _fm_parser._parse_yaml_content(tgt_split[0])
        if not isinstance(src_data, dict) or not isinstance(tgt_data, dict):
            return

        for field_name, src_val in src_data.items():
            if not isinstance(src_val, str):
                continue
            if not self._is_multiline_source_field(src_yaml_text, field_name):
                continue

            tgt_val = tgt_data.get(field_name)
            # HT-QUALITY-GATES-001 Part 26: ja/ko added after direct
            # reproduction (not guessed) hit the identical false-positive
            # shape as zh -- e.g. a real ko/barcode plugin_description at
            # 52/107 chars (49%), ja/diagram at 41/97 (42%) -- both
            # legitimate, complete translations blocked by the same
            # English-centric character-count assumption.
            _min_ratio = 0.2 if target_lang in ("zh", "ja", "ko") else 0.5
            reason = None
            if not isinstance(tgt_val, str):
                reason = "target field missing or not a string"
            elif not tgt_val.strip():
                reason = "target field is empty"
            elif len(tgt_val) < _min_ratio * len(src_val):
                reason = f"target retained only {len(tgt_val)}/{len(src_val)} chars"
            elif target_lang != "en" and tgt_val == src_val:
                reason = "target is byte-identical to English source"

            if reason:
                result.passed = False
                result.error = (
                    f"Gate 27 multi-line scalar preservation: field '{field_name}' — {reason}"
                )
                logger.error("GATE27 BLOCKED %s: %s", output_path.name, result.error)
                return

    # ------------------------------------------------------------------
    # Gate 43: block-scalar key-line leak
    # HT-QUALITY-GATES-001 Phase 8 (Tier A #5)
    # ------------------------------------------------------------------

    _EMBEDDED_KEY_LINE_RE = re.compile(r"\n\s*[A-Za-z_][\w.-]*:\s")

    def _gate_block_scalar_key_leak(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Detect a translated multi-line/folded YAML scalar (same field
        scope as Gate 27) whose PARSED value contains an embedded pattern
        that looks like a YAML ``key:`` line, absent from the source
        field's own value -- evidence a subsequent frontmatter field's
        content bled INTO this scalar because of a block-scalar
        indentation problem, rather than being truncated OUT of it (Gate
        27's complementary "too short" failure mode). The document as a
        whole still parses cleanly (no YAMLError, no key-set drift
        `YAMLValidator`/`FrontmatterIntegrityValidator` would catch), which
        is exactly why this shape is silent: the file "looks fine" to every
        existing check, it just has the wrong content in the wrong field.
        """
        src_split = _fm_parser._split_frontmatter(source_content)
        tgt_split = _fm_parser._split_frontmatter(translated_content)
        if src_split is None or tgt_split is None:
            return
        src_yaml_text, _ = src_split
        src_data = _fm_parser._parse_yaml_content(src_yaml_text)
        tgt_data = _fm_parser._parse_yaml_content(tgt_split[0])
        if not isinstance(src_data, dict) or not isinstance(tgt_data, dict):
            return

        for field_name, src_val in src_data.items():
            if not isinstance(src_val, str):
                continue
            if not self._is_multiline_source_field(src_yaml_text, field_name):
                continue
            tgt_val = tgt_data.get(field_name)
            if not isinstance(tgt_val, str):
                continue
            if self._EMBEDDED_KEY_LINE_RE.search(src_val):
                continue  # source itself has this shape -- not a translation artifact
            leak_m = self._EMBEDDED_KEY_LINE_RE.search(tgt_val)
            if leak_m:
                result.passed = False
                result.error = (
                    f"GATE43 BLOCK-SCALAR KEY LEAK {output_path.name}: field "
                    f"'{field_name}' contains an embedded key-line-shaped "
                    f"fragment {leak_m.group().strip()!r} not present in source "
                    f"-- likely a subsequent field's content absorbed by a "
                    f"block-scalar indentation error"
                )
                logger.warning(
                    "GATE43 BLOCK-SCALAR KEY LEAK (warn-only, Phase 8 Tier A) %s: %s",
                    output_path.name,
                    result.error,
                )
                return

    # ------------------------------------------------------------------
    # Gate 28: Title identity on family/platform index pages (warn-only)
    # HT-QUALITY-GATES-001 TC-QG-005
    # ------------------------------------------------------------------

    def _gate_title_identity(
        self,
        translated_content: str,
        output_path: Path,
        target_lang: str,
        source_doc: object,
        result: WriteGateResult,
    ) -> None:
        """Warn if `title` drifted from the English source on a family/platform
        index page ({locale}/{family}/{platform}/_index.md), where project
        convention requires it to stay byte-identical across every locale.

        Independent, write-time, defense-in-depth check. Does NOT replace the
        extraction-time skip in text_unit_extractor's
        force_protected_fields={"title"} (built via is_family_platform_index())
        — it verifies that mechanism actually held, since the audit behind
        HT-QUALITY-GATES-001 found title drift on the large majority of
        translated family/platform pages despite that skip existing.
        `linkTitle` is intentionally not checked here: confirmed (2026-07-20
        casing precheck against real products.aspose.org content) that this
        site's `family`/`plugin` layouts have no `linkTitle` field at all.

        Promoted to "block" (Part 21) after the canary confirmed 100% title
        match with RC1-RC4 live and the dropped-placeholder fallback fixed the
        only other residual defect found — blocking is cheap insurance at
        this point (RC1-RC4 already removed the root cause), not a premature
        bet made before evidence existed.

        `include_family_root` is scoped to sites directly confirmed to need
        it. products.aspose.org: the audit's single most severe finding, a
        title corrupted to the Serbian word for "Death", was on exactly this
        page shape (family-root, no platform sub-pages). kb.aspose.org and
        docs.aspose.org added (Part 22) after direct sampling of real live
        content found the identical failure pattern already present at
        near-universal scale — e.g. kb hr/cells/_index.md's title corrupted
        to "Sljedeći članakFOSS" ("Next article" + "FOSS", a leaked UI
        string), the same class of defect as products, not a different
        content policy. reference.aspose.org excluded (title is
        `mode: passthrough`, never sent to the model — not vulnerable).
        blog.aspose.org excluded: `per_language_folders: false` means this
        gate's path-part site-matching and `is_family_platform_index()`'s
        locale-as-folder-segment detection don't apply the same way there —
        needs its own investigation, not a guess.
        """
        if source_doc is None or not hasattr(source_doc, "frontmatter"):
            return
        _FAMILY_ROOT_SITES = ("products.aspose.org", "kb.aspose.org", "docs.aspose.org")
        _include_family_root = any(site in output_path.parts for site in _FAMILY_ROOT_SITES)
        if not is_family_platform_index(
            output_path, source_lang=target_lang, include_family_root=_include_family_root
        ):
            return

        fm = getattr(source_doc, "frontmatter", {}) or {}
        en_title = fm.get("title")
        if not en_title or not isinstance(en_title, str):
            return
        en_title = en_title.strip()

        tr_title = _get_frontmatter_field(translated_content, "title")
        if tr_title is None:
            return
        tr_title = tr_title.strip()

        if tr_title == en_title:
            return

        result.passed = False
        result.error = (
            f"GATE28 TITLE DRIFT {output_path.name}: family/platform index title "
            f"must stay byte-identical to English — expected {en_title!r}, got {tr_title!r}"
        )
        result.retranslate_queued = True
        result.retranslate_paths.append((output_path, target_lang))
        logger.error(
            "GATE28 TITLE DRIFT (blocking, TC-QG-005) %s: family/platform index "
            "title must stay byte-identical to English — expected %r, got %r",
            output_path.name,
            en_title,
            tr_title,
        )

    # ------------------------------------------------------------------
    # Gate 29: LLM refusal / meta-commentary artifact leak (blocking)
    # HT-QUALITY-GATES-001 TC-QG-001, promoted to "block" in Part 22 (1.6)
    # ------------------------------------------------------------------

    def _gate_refusal_artifact(
        self,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
        target_lang: str = "",
    ) -> None:
        """Block if raw LLM refusal/meta-commentary text ("Please provide the
        English text you want translated.", "Ich habe keine Ahnung.", "I'm
        sorry, but I can't access...", etc.) appears to have been shipped as
        page content instead of an actual translation.

        Two detection layers: the curated, already-production-validated
        exact-phrase list (REFUSAL_RE, shared with
        scripts/quality/audit_llm_artifacts.py via
        src/translation_engine/quality/refusal_patterns.py) plus a broader
        shape-based pattern (CONVERSATIONAL_SHAPE_RE) for generic first/
        second-person conversational register that doesn't happen to contain
        one of the curated phrases -- added because a real confirmed leak
        ("I'm sorry, but I can't access or read any attached files...")
        matched neither this gate nor any other check and shipped untouched.

        No auto-fix exists for either shape (there's nothing to auto-clean a
        refusal into), so a hit blocks the write and queues the file for
        retranslation, mirroring Gate 28's pattern.
        """
        split = _fm_parser._split_frontmatter(translated_content)
        fm_text = split[0] if split else ""

        hits: list[str] = []
        for pattern in (REFUSAL_RE, CONVERSATIONAL_SHAPE_RE):
            for m in pattern.finditer(fm_text):
                line_start = fm_text.rfind("\n", 0, m.start()) + 1
                line_end = fm_text.find("\n", m.end())
                line = fm_text[line_start : line_end if line_end != -1 else None].strip()
                if line not in hits:
                    hits.append(line[:160])

        body = split[1] if split else translated_content
        in_code = False
        for line in body.splitlines():
            s = line.strip()
            if s.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not s:
                continue
            if (REFUSAL_RE.search(s) or CONVERSATIONAL_SHAPE_RE.search(s)) and s[:160] not in hits:
                hits.append(s[:160])

        if not hits:
            return

        result.passed = False
        result.error = (
            f"GATE29 REFUSAL ARTIFACT {output_path.name}: {len(hits)} probable "
            f"LLM refusal/meta-commentary line(s) found in shipped content"
        )
        result.retranslate_queued = True
        result.retranslate_paths.append((output_path, target_lang))
        logger.error(
            "GATE29 REFUSAL ARTIFACT (blocking, TC-QG-001/Part 22) %s: %d probable "
            "LLM refusal/meta-commentary line(s) found in shipped content: %s",
            output_path.name,
            len(hits),
            hits[:5],
        )

    # ------------------------------------------------------------------
    # Gate 30: universal placeholder-leak detection (blocking)
    # HT-QUALITY-GATES-001 Part 22 (1.1 root cause B)
    # ------------------------------------------------------------------

    def _gate_placeholder_leak(
        self,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
        target_lang: str = "",
    ) -> None:
        """Block if a literal PLACEHOLDER_N token (braced or bare) survives
        into content about to be written.

        By this point PlaceholderManager.restore() has already run its full
        multi-pass repair strategy (exact, bare-digit, fuzzy-brace, ALL-CAPS
        cleanup, bare-brace-wrapped-value, fuzzy-variant substitution) --
        every corrupted SHAPE it knows how to recognize is already gone. A
        literal "PLACEHOLDER_N" surviving to this point isn't a shape
        restore() failed to fix; it's direct evidence restore() never ran on
        this content at all. Confirmed root cause for the one large-scale
        instance found this session: a content-refresh batch authored by an
        entirely separate process (git commit co-authored by OpenAI Codex)
        writing straight into the content repository, bypassing this
        pipeline's protect()/restore() cycle entirely.

        Deliberately process-agnostic: this gate blocks the shape regardless
        of which writer produced it. It cannot compel an external writer to
        route through safe_io.save() (see Part 7's honest limit on that), but
        it does close this codebase's own remaining exposure -- previously
        there was no check anywhere in the 29-gate registry for this shape at
        all, on any write, from any source.

        Reuses PlaceholderManager.extract_placeholders()'s own pattern
        (`\\{?PLACEHOLDER_\\d+\\}?`) rather than a second, potentially-drifting
        copy of it.
        """
        split = _fm_parser._split_frontmatter(translated_content)
        fm_text, body = (split[0], split[1]) if split else ("", translated_content)

        hits: list[str] = _PLACEHOLDER_LEAK_RE.findall(fm_text)
        hits += _PLACEHOLDER_LEAK_RE.findall(_FENCED_CODE_BLOCK_RE.sub("", body))

        if not hits:
            return

        result.passed = False
        result.error = (
            f"GATE30 PLACEHOLDER LEAK {output_path.name}: {len(hits)} literal "
            f"placeholder token(s) survived into shipped content: {hits[:5]}"
        )
        result.retranslate_queued = True
        result.retranslate_paths.append((output_path, target_lang))
        logger.error(
            "GATE30 PLACEHOLDER LEAK (blocking, Part 22) %s: %d literal "
            "placeholder token(s) survived into shipped content: %s",
            output_path.name,
            len(hits),
            hits[:5],
        )

    # ------------------------------------------------------------------
    # Gate 31: partial foreign-script contamination (warn-only)
    # HT-QUALITY-GATES-001 Part 22 addendum
    # ------------------------------------------------------------------

    def _gate_partial_script_contamination(
        self,
        translated_content: str,
        output_path: Path,
        target_lang: str,
        result: WriteGateResult,
    ) -> None:
        """Warn if a non-Latin-script translation contains a multi-word run
        of Latin-script prose -- a different (usually wrong) language's
        words mixed into otherwise-correct text.

        Confirmed live and deterministically reproducible (professionalize_llm
        runs at temperature=0.0): reference.aspose.org he/pdf/net/
        ColumnInfo.md came back with real Spanish phrases embedded in Hebrew
        body prose, table headers, and its closing link -- "las propiedades",
        "el tamaño de columna preciso", "Referencia de API Enterprise" -- on
        two independent, identical live translation runs. Gate 24 above
        cannot see this: it only checks whether the WHOLE description field
        is ASCII-only (total reversion), and a whole-file FastText detector
        (Gates 2/4) still correctly classifies a majority-Hebrew page as
        Hebrew even with a few Spanish phrases mixed in -- neither check
        operates at fine enough granularity.

        Deliberately conservative to avoid false-flagging legitimate
        preserved multi-word technical phrases (e.g. ".NET Framework",
        "Microsoft Office", "PDF FOSS"): a matched Latin-word run must ALSO
        contain a common Spanish/French/German/etc. function word to count
        -- see the module-level comment on `_ROMANCE_GERMANIC_FUNCTION_WORDS`
        for why, and the false-positive data that motivated it. Scanning
        itself runs after stripping fenced code blocks, inline code spans,
        and URLs (markdown link anchor TEXT is still scanned -- that's real
        page content, and is exactly where one of the confirmed examples
        appeared).

        Frontmatter scanning is scoped to a known set of translatable prose
        fields (title/description/summary/subtitle) via
        `_get_frontmatter_field()`'s real YAML parsing, NOT the raw
        frontmatter block -- confirmed necessary during testing: scanning
        the whole block false-positived on deliberately-untranslated
        metadata (`grade_reasons: ["No findings -> grade A"]`,
        `evidence.*` fields) that legitimately stays in English by site-
        profile design, the same passthrough-field problem
        `_build_language_detection_text()` already had to solve for the
        language-mismatch gates above.
        """
        if target_lang not in _GATE31_NON_LATIN_LOCALES:
            return

        split = _fm_parser._split_frontmatter(translated_content)
        body = split[1] if split else translated_content

        def _strip_non_prose(text: str) -> str:
            text = _FENCED_CODE_BLOCK_RE.sub("", text)
            text = _BACKTICK_SPAN_RE.sub("", text)
            text = _MARKDOWN_LINK_URL_RE.sub("]", text)
            text = _BARE_URL_RE.sub("", text)
            return text

        regions = [_strip_non_prose(body)]
        for field_name in ("title", "description", "summary", "subtitle"):
            value = _get_frontmatter_field(translated_content, field_name)
            if value:
                regions.append(value)

        hits: list[str] = []
        for region in regions:
            for m in _LATIN_WORD_RUN_RE.finditer(region):
                span = m.group(0)
                words = {w.lower() for w in span.split()}
                if not (words & _ROMANCE_GERMANIC_FUNCTION_WORDS):
                    continue  # looks like a brand/technical phrase, not leaked prose
                if span not in hits:
                    hits.append(span)

        if not hits:
            return

        result.passed = False
        result.error = (
            f"GATE31 PARTIAL SCRIPT CONTAMINATION {output_path.name}: "
            f"{len(hits)} multi-word Latin-script run(s) found in {target_lang} "
            f"(non-Latin-script locale) content: {hits[:5]}"
        )
        logger.warning(
            "GATE31 PARTIAL SCRIPT CONTAMINATION (warn-only, Part 22) %s: "
            "%d multi-word Latin-script run(s) found in %s content: %s",
            output_path.name,
            len(hits),
            target_lang,
            hits[:5],
        )

    # ------------------------------------------------------------------
    # Gate 32: content-hash staleness (warn-only)
    # HT-QUALITY-GATES-001 Part 22 (plan 5.1 item 8)
    # ------------------------------------------------------------------

    def _gate_content_hash_staleness(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Warn when a translation's recorded `provenance.content_hash`
        doesn't match its current EN source's hash -- a zero-cost (no model
        call, pure metadata comparison) signal that the translation was
        generated from a since-changed source and may describe a stale API
        surface.

        Confirmed real, consequential instance: reference.aspose.org/de/
        words/python/Document.md's translation states "3 methods and 1
        property" against the current EN source's actual "2 methods and 13
        properties" -- directly traceable to a stale `content_hash`/
        `content_created_at`/`model_version` left over from before the
        current EN content was generated.

        Diagnostic, not a correctness guarantee in either direction: EN can
        change in ways that don't invalidate an existing translation (e.g. a
        typo fix), and this check has no way to tell "cosmetic EN change"
        from "meaningful API change" -- it only tells you the pairing is
        worth checking. That's also why this stays "warn" even after a
        canary, unlike gates with an unambiguous defect signature.
        """
        en_hash = _get_nested_frontmatter_field(source_content, "provenance", "content_hash")
        if not en_hash:
            return  # EN source doesn't carry provenance tracking -- nothing to compare
        tgt_hash = _get_nested_frontmatter_field(translated_content, "provenance", "content_hash")
        if not tgt_hash:
            return  # translation predates provenance tracking or never had it
        if en_hash == tgt_hash:
            return

        result.passed = False
        result.error = (
            f"GATE32 CONTENT HASH STALE {output_path.name}: translation's "
            f"provenance.content_hash={tgt_hash[:12]}... does not match current "
            f"EN source's {en_hash[:12]}... -- translation may describe a "
            f"stale API surface"
        )
        logger.warning(
            "GATE32 CONTENT HASH STALE (warn-only, Part 22) %s: tgt_hash=%s en_hash=%s",
            output_path.name,
            tgt_hash[:12],
            en_hash[:12],
        )

    # ------------------------------------------------------------------
    # Gate 33: brand-token presence (warn-only)
    # HT-QUALITY-GATES-001 Part 22 (plan 5.1 item 9)
    # ------------------------------------------------------------------

    def _gate_brand_token_presence(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Warn when the EN source's title/head_title/seoTitle contains the
        literal brand token "Aspose" but the translated field does not --
        confirmed real MT failure mode where the brand name itself gets
        mistranslated as an ordinary word because it superficially resembles
        one. Confirmed independently across 4+ sites and 6+ locales this
        session: "Aspose" -> Arabic "أفترض" (I suppose/assume, a phonetic
        collision), -> Polish "Wykorzystanie danych osobowych" (a GDPR legal
        phrase), -> Russian "Апсоц...ФОС" (garbled non-word), "for Go" ->
        Romanian "pentru a merge" (the verb "to go/walk").

        Structural presence check, not semantic -- cheap and unambiguous:
        there is no legitimate reason for "Aspose" to vanish from a title
        that has it in EN, so this is a low-false-positive check by
        construction (unlike Gate 31's fuzzier prose-contamination heuristic).
        """
        for field_name in ("title", "head_title", "seoTitle"):
            en_value = _get_frontmatter_field(source_content, field_name)
            if not en_value or "aspose" not in en_value.lower():
                continue
            tgt_value = _get_frontmatter_field(translated_content, field_name)
            if tgt_value and "aspose" in tgt_value.lower():
                continue  # present and correct

            result.passed = False
            result.error = (
                f"GATE33 BRAND TOKEN MISSING {output_path.name}: EN {field_name} "
                f"contains 'Aspose' but translated {field_name} "
                f"{'is empty' if not tgt_value else f'does not: {tgt_value[:60]!r}'}"
            )
            logger.warning(
                "GATE33 BRAND TOKEN MISSING (warn-only, Part 22) %s: field=%s en=%r tgt=%r",
                output_path.name,
                field_name,
                en_value[:60],
                (tgt_value or "")[:60],
            )
            return  # one hit is enough to warn; don't spam multiple fields

    # ------------------------------------------------------------------
    # Gate 34: heading/section-count deficit (warn-only)
    # HT-QUALITY-GATES-001 Part 22 (plan 5.2 item 1)
    # ------------------------------------------------------------------

    def _gate_heading_deficit(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Warn when the translation has FEWER top-level headings than the
        source -- the deficit-side mirror of Gate 7's surplus check, which
        this registry never had for the trailing-section-loss defect class
        (Part 2.3's structural finding: "there is no 'fewer headings than
        source' check anywhere in the 29-gate registry").

        Fires on ANY deficit (tgt_hd < src_hd), not a tolerance band like
        Gate 7's +3 surplus allowance -- the confirmed real failure mode is
        losing exactly one section (almost always the last one), so a
        looser threshold would silently pass the exact defect this gate
        exists to catch. Reuses the same fence-stripped heading-count logic
        as Gate 7 (_TOP_HEADING_RE is `##` specifically, matching Gate 7's
        `#{1,6}` count restricted to level-2 -- the level almost every
        family/platform/API page uses for its top-level sections).
        """
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)
        src_hd = len(_TOP_HEADING_RE.findall(_FENCED_CODE_BLOCK_RE.sub("", src_body)))
        tgt_hd = len(_TOP_HEADING_RE.findall(_FENCED_CODE_BLOCK_RE.sub("", tgt_body)))

        if src_hd == 0 or tgt_hd >= src_hd:
            return

        result.passed = False
        result.error = (
            f"GATE34 HEADING DEFICIT {output_path.name}: source has {src_hd} "
            f"top-level headings but translation has only {tgt_hd} "
            f"(-{src_hd - tgt_hd})"
        )
        logger.warning(
            "GATE34 HEADING DEFICIT (warn-only, Part 22) %s: src=%d tgt=%d",
            output_path.name,
            src_hd,
            tgt_hd,
        )

    # ------------------------------------------------------------------
    # Gate 35: dropped trailing link (warn-only)
    # HT-QUALITY-GATES-001 Part 22 (plan 5.2 item 2)
    # ------------------------------------------------------------------

    def _gate_dropped_trailing_link(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Warn when the source body's LAST top-level section contains a
        link and none of that section's URL(s) survive anywhere in the
        translated body.

        This is a pragmatic, language-agnostic proxy for true heading-
        identity diffing (comparing WHICH sections exist, not just how
        many). True text-identity comparison is not possible here -- a
        correctly-translated heading has different text by definition ("See
        Also" -> "Voir aussi") -- but URLs are never translated, so a URL
        present in EN's trailing section that's absent from the translation
        entirely is strong, language-invariant evidence that section was
        dropped rather than merely retitled. Directly targets the confirmed
        real pattern: this session's investigation found the dropped
        trailing section is *always* a "See Also"/"Related Resources"/
        Enterprise-link section whose content is just links, at every one
        of the 5 sites -- catches the case Gate 34 alone would miss (an
        earlier merge/rename coincidentally keeps the raw heading count
        equal while the last section is still gone).
        """
        src_body = self._get_body(source_content)
        headings = list(_TOP_HEADING_RE.finditer(_FENCED_CODE_BLOCK_RE.sub("", src_body)))
        if not headings:
            return

        last_heading_start = headings[-1].start()
        last_section = src_body[last_heading_start:]
        section_urls = _MARKDOWN_LINK_CAPTURE_RE.findall(last_section)
        if not section_urls:
            return  # last section isn't link-shaped -- outside this gate's scope

        tgt_body = self._get_body(translated_content)
        if any(url in tgt_body for url in section_urls):
            return  # at least one URL survived -- section is present

        result.passed = False
        result.error = (
            f"GATE35 DROPPED TRAILING LINK {output_path.name}: source's last "
            f"section links to {section_urls[:2]}, none of which appear "
            f"anywhere in the translated body"
        )
        logger.warning(
            "GATE35 DROPPED TRAILING LINK (warn-only, Part 22) %s: missing URL(s) %s",
            output_path.name,
            section_urls[:2],
        )

    # ------------------------------------------------------------------
    # Gate 36: LLM meaning-fidelity judge (HT-QUALITY-GATES-001 Part 22,
    # plan 5.4 items 3+5)
    # ------------------------------------------------------------------

    _FIDELITY_MIN_BODY_CHARS = 50

    @staticmethod
    def _gate36_is_high_risk(output_path: Path, translation_stats: object) -> bool:
        """Tiered coverage (plan 5.4 item 4): the fidelity judge is a real,
        costed LLM call, so it only runs synchronously for content classified
        high-risk. Two independent signals, either is sufficient:

        1. Site/depth heuristic from this session's own evidence (kb.aspose.org
           family-root _index.md pages; reference.aspose.org leaf/class pages)
           -- derived purely from output_path, no instrumentation needed.
        2. This specific file actually used LLM-backend translation for at
           least one unit (llm_units_translated > 0) -- the per-unit fact
           TranslationStats now records (see segment_translator.py), which
           the plan explicitly calls for in place of a locale-only proxy
           ("was this unit LLM-escalated... a recorded fact per-unit").

        Everything else is left to the periodic/sampled audit tier
        (scripts/audit_translation_quality.py), not synchronous write-time
        judging -- see Part 5.4 item 4's tiered-coverage design.
        """
        parts = {p.lower() for p in output_path.parts}
        is_kb_root = "kb.aspose.org" in parts and output_path.stem == "_index"
        is_reference_leaf = "reference.aspose.org" in parts and output_path.stem != "_index"
        if is_kb_root or is_reference_leaf:
            return True
        if (
            translation_stats is not None
            and getattr(translation_stats, "llm_units_translated", 0) > 0
        ):
            return True
        return False

    def _gate_fidelity_judge(
        self,
        source_content: str,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        result: WriteGateResult,
        translation_stats: object = None,
    ) -> str:
        """LLM meaning-fidelity judge -- catches what SemanticSimilarityValidator's
        cosine similarity structurally cannot: systematic homonym mistranslation,
        inverted getter/method semantics, factual reversals, and hallucinated
        content all read as fluent, on-topic, embeddings-close text (root cause
        for building this gate at all -- see plan Part 5.4 item 3).

        Ships in shadow mode by default (config key
        translation_engine.fidelity_judge.enforce: false): always computes and
        writes a `translation_fidelity` frontmatter field for high-risk-tier
        files, but only flips result.passed when explicitly enforced --
        matching Part 6 item 3's rollout discipline (measure agreement with
        human close-reading before trusting this to block). See
        validation/fidelity_judge.py for the judge itself; it fails open (returns
        None) on any error, so a judge outage never blocks a write on its own.
        """
        try:
            _cfg = (
                self._config.get_config().get("translation_engine", {}).get("fidelity_judge", {})
                if self._config
                else {}
            )
        except Exception:
            _cfg = {}

        # Default to disabled (not enabled) when the config key is absent --
        # this gate can make a real, costed, network LLM call, so an absent
        # config must never be silently interpreted as opt-in. Matches this
        # codebase's established convention for correction_pass.enabled
        # (also defaults to disabled when absent). Every existing test that
        # doesn't explicitly set fidelity_judge.enabled: true stays a no-op
        # here, including the 13+ pre-existing write-gate tests that use
        # reference.aspose.org-shaped output_paths and would otherwise now
        # also satisfy Gate 36's high-risk classification.
        if not _cfg.get("enabled", False):
            if self._zero_defect:
                result.passed = False
                result.error = "GATE36 fidelity judge is disabled under zero-defect policy"
            return translated_content
        # Registered "auto_clean" (not "block"), so the dispatch loop does not
        # short-circuit this gate when an earlier block gate already failed
        # (that check only applies to the "block" branch). Without this guard,
        # a file already rejected for an unrelated reason would still pay for
        # a real LLM call, AND a fail verdict would overwrite the earlier
        # gate's result.error with Gate 36's message, hiding the actual root
        # cause of the block.
        if not result.passed:
            return translated_content
        if not self._zero_defect and not self._gate36_is_high_risk(output_path, translation_stats):
            return translated_content

        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)
        if not self._zero_defect and len(tgt_body.strip()) < self._FIDELITY_MIN_BODY_CHARS:
            return translated_content  # too short to judge meaningfully

        from .validation.fidelity_judge import judge_fidelity

        verdict = judge_fidelity(
            src_body,
            tgt_body,
            "en",
            target_lang,
            model_id=_cfg.get("model_id", "professionalize_llm"),
            warn_threshold=_cfg.get("warn_threshold", 0.7),
            fail_threshold=_cfg.get("block_threshold", 0.5),
        )
        if verdict is None:
            if self._zero_defect:
                result.passed = False
                result.error = f"GATE36 fidelity judge unavailable for {output_path.name}"
                return translated_content
            logger.info(
                "GATE36 fidelity judge unavailable/failed for %s — skipped",
                output_path.name,
            )
            return translated_content

        if self._zero_defect:
            result._fidelity_result = {  # type: ignore[attr-defined]
                "score": round(verdict.score, 3),
                "verdict": verdict.verdict,
                "issues": verdict.issues,
                "model": verdict.model,
            }
            if verdict.verdict != "pass":
                result.passed = False
                result.error = (
                    f"GATE36 FIDELITY JUDGE {output_path.name}: "
                    f"{verdict.verdict} score={verdict.score:.2f}"
                )
            return translated_content

        split = _fm_parser._split_frontmatter(translated_content)
        if split is None:
            return translated_content
        yaml_text, body = split
        data = _fm_parser._parse_yaml_content(yaml_text)
        if not isinstance(data, dict):
            return translated_content

        from datetime import datetime, timezone

        data["translation_fidelity"] = {
            "score": round(verdict.score, 3),
            "verdict": verdict.verdict,
            "issues": verdict.issues,
            "model": verdict.model,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        if verdict.verdict == "fail":
            logger.warning(
                "GATE36 fidelity judge FAIL (score=%.2f) for %s: %s",
                verdict.score,
                output_path.name,
                "; ".join(verdict.issues) or "(no details)",
            )
            if _cfg.get("enforce", False):
                result.passed = False
                result.error = (
                    f"GATE36 FIDELITY JUDGE {output_path.name}: score "
                    f"{verdict.score:.2f} below block threshold "
                    f"{_cfg.get('block_threshold', 0.5)} — "
                    f"{'; '.join(verdict.issues) or 'meaning divergence detected'}"
                )
                result.retranslate_queued = True
                result.retranslate_paths.append((output_path, target_lang))
        elif verdict.verdict == "warn":
            logger.info(
                "GATE36 fidelity judge WARN (score=%.2f) for %s: %s",
                verdict.score,
                output_path.name,
                "; ".join(verdict.issues) or "(no details)",
            )

        try:
            return YAMLFormatter.format_frontmatter(data) + body
        except ValueError:
            logger.warning(
                "GATE36 re-serialization failed for %s; leaving content unmodified",
                output_path.name,
            )
            return translated_content

    # ------------------------------------------------------------------
    # Gate 37: TM-collision cross-context metadata contamination
    # HT-QUALITY-GATES-001 Phase 8 (Tier C #12)
    # ------------------------------------------------------------------

    def _gate_tm_collision(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Warn when the translated `description`/`summary` frontmatter field
        names a DIFFERENT backtick-quoted class/enum/interface identifier
        than the file's own title -- the signature of a TM key collision
        (two files whose description reduced to an identical
        placeholder-protected template, e.g. "`{PLACEHOLDER_0}` enum",
        served each other's cached translation before TC-HT-TMKEY-001's
        tm_key_text fix stopped NEW collisions from forming).

        This is a real-time port of the proven, already-tested detection
        logic in scripts/quality/audit_tm_collision.py (which found this
        exact pattern across the historical corpus) -- ships as a
        production write-gate too so a NEW file can never ship with this
        specific contamination shape, not just be found after the fact.
        Scope matches that script's: reference/docs/kb/products.aspose.org's
        strict single-identifier API-reference template only (EN title is a
        bare identifier AND EN's own description already names it) -- other
        content types have no such template, so this is a real content-type
        scoping decision, not an artificially narrowed check.
        """
        en_title = (
            _get_frontmatter_field(source_content, "title")
            or _get_frontmatter_field(source_content, "linkTitle")
            or ""
        ).strip()
        if not en_title or not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", en_title):
            return  # not a simple single-identifier API page

        en_desc = _get_frontmatter_field(source_content, "description") or ""
        en_ids = set(_BACKTICK_ID_RE.findall(en_desc))
        if en_title not in en_ids:
            return  # EN source itself doesn't follow the expected template

        for field_name in ("description", "summary"):
            tr_val = _get_frontmatter_field(translated_content, field_name)
            if not tr_val:
                continue
            tr_ids = set(_BACKTICK_ID_RE.findall(tr_val))
            if not tr_ids or en_title in tr_ids:
                continue  # no identifier claim, or correctly matches

            other = sorted(tr_ids)[0]
            result.passed = False
            result.error = (
                f"GATE37 TM COLLISION {output_path.name}: field={field_name} "
                f"expected=`{en_title}` found=`{other}`"
            )
            logger.warning(
                "GATE37 TM COLLISION (warn-only, Phase 8 Tier C) %s: field=%s "
                "expected=`%s` found=`%s`",
                output_path.name,
                field_name,
                en_title,
                other,
            )
            return  # one hit is enough; don't spam multiple fields

    # ------------------------------------------------------------------
    # Gate 38: prose-before-code-block deletion
    # HT-QUALITY-GATES-001 Phase 8 (Tier A #14)
    # ------------------------------------------------------------------

    def _gate_prose_before_code_dropped(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Detect a dropped lead-in paragraph immediately before a fenced
        code block -- distinct from Gates 34/35's trailing-SECTION loss
        (which only covers the document's final ``##`` section) and from
        Gate 19/26's fence-count checks (which only see whether a fence
        exists, not what preceded it).

        Design note: ``ASTRenderer`` already detects a dropped node during
        reconstruction via its ``_missing_node_count``/``AST_FALLBACK``
        instrumentation, while the AST is still live -- but gates run after
        reconstruction, on flat strings only (see this class's docstring),
        and threading AST-level state through ``evaluate()``'s signature
        would be a much larger, riskier plumbing change than this specific
        gap warrants. Instead this reuses the F2 fence-segment primitive
        (``fence_spans.split_fenced_segments``) to pair source and target
        fenced blocks positionally and compare what immediately precedes
        each -- a flat-string check consistent with every other gate here.

        Only fires when fence COUNT matches between source and target (a
        mismatch is already Gate 19/26's job) -- positional pairing is only
        meaningful when fences align 1:1.
        """
        from .fence_spans import split_fenced_segments

        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        src_segments = split_fenced_segments(src_body)
        tgt_segments = split_fenced_segments(tgt_body)

        src_fence_idxs = [i for i, (is_fenced, _lines) in enumerate(src_segments) if is_fenced]
        tgt_fence_idxs = [i for i, (is_fenced, _lines) in enumerate(tgt_segments) if is_fenced]

        if not src_fence_idxs or len(src_fence_idxs) != len(tgt_fence_idxs):
            return

        for block_num, (src_idx, tgt_idx) in enumerate(
            zip(src_fence_idxs, tgt_fence_idxs), start=1
        ):
            if src_idx == 0 or tgt_idx == 0:
                continue  # fence is the very first segment -- no lead-in possible
            src_lead_in = "".join(src_segments[src_idx - 1][1]).strip()
            tgt_lead_in = "".join(tgt_segments[tgt_idx - 1][1]).strip()
            if len(src_lead_in) >= 20 and len(tgt_lead_in) < 5:
                result.passed = False
                result.error = (
                    f"GATE38 PROSE-BEFORE-CODE DROPPED {output_path.name}: "
                    f"code block #{block_num} lost its lead-in paragraph "
                    f"(source had {len(src_lead_in)} chars immediately before it)"
                )
                logger.warning(
                    "GATE38 PROSE-BEFORE-CODE DROPPED (warn-only, Phase 8 Tier A) %s: "
                    "block #%d src_lead_in=%r",
                    output_path.name,
                    block_num,
                    src_lead_in[:60],
                )
                return

    # ------------------------------------------------------------------
    # Gate 39: en-dash numeric-range collapse
    # HT-QUALITY-GATES-001 Phase 8 (Tier A #8)
    # ------------------------------------------------------------------

    def _gate_dash_range_collapsed(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Detect a numeric range whose separating dash vanished entirely
        during translation, fusing the two numbers into one digit run --
        e.g. "18-22" (pages/versions/years) becoming "1822" (a different,
        wrong number). No digit-dash-digit separator check existed anywhere
        in this codebase before this gate.

        Deliberately global (no positional correlation between source and
        target, since word order differs across languages): for every
        digit-dash-digit occurrence in the source, look for its exact
        concatenation as its own maximal digit run anywhere in the target.
        An exact match on a specific multi-digit concatenation is a narrow
        enough signature to be low-false-positive without needing to locate
        the corresponding sentence.

        False-positive guard (independent-verification MINOR finding,
        HT-QUALITY-GATES-001 Phase 8): an unrelated, coincidental digit run
        elsewhere in the target (a product code, page number, year) can
        happen to equal a range's concatenation even though that range was
        translated correctly and is still intact, dash and all, somewhere
        else in the document. Before flagging, check whether the source
        range's intact dash-digit pattern is ALSO separately present in the
        target -- if so, the range wasn't collapsed, so skip.
        """
        src_body = strip_fenced(self._get_body(source_content))
        tgt_body = strip_fenced(self._get_body(translated_content))

        tgt_digit_runs = {m.group() for m in _DIGIT_RUN_RE.finditer(tgt_body)}
        if not tgt_digit_runs:
            return

        tgt_intact_ranges = {
            (m.group(1), m.group(2)) for m in _DIGIT_DASH_DIGIT_RE.finditer(tgt_body)
        }

        for m in _DIGIT_DASH_DIGIT_RE.finditer(src_body):
            num1, num2 = m.group(1), m.group(2)
            if (num1, num2) in tgt_intact_ranges:
                continue  # range survived intact elsewhere -- not a collapse
            collapsed = num1 + num2
            if collapsed in tgt_digit_runs:
                result.passed = False
                result.error = (
                    f"GATE39 DASH RANGE COLLAPSED {output_path.name}: "
                    f'source range "{num1}-{num2}" appears to have collapsed '
                    f'to "{collapsed}" in the translation'
                )
                logger.warning(
                    "GATE39 DASH RANGE COLLAPSED (warn-only, Phase 8 Tier A) %s: %s-%s -> %s",
                    output_path.name,
                    num1,
                    num2,
                    collapsed,
                )
                return

    # ------------------------------------------------------------------
    # Gate 40: SEO metadata field corruption
    # HT-QUALITY-GATES-001 Phase 8 (Tier A #10)
    # ------------------------------------------------------------------

    # Independent-verification MINOR finding (HT-QUALITY-GATES-001 Phase 8):
    # includes the fullwidth pipe (｜) and fullwidth hyphen-minus (－) as
    # direct CJK-locale analogs of the already-recognized | and -- these are
    # the same separator shapes, not new ones, so this is a conservative
    # expansion. Broader additions (bare colon, middle dot, bullet,
    # guillemets) are deliberately NOT included without corpus evidence --
    # see the Phase 8 real-corpus sweep this expansion was informed by.
    _SEO_SEPARATOR_RE = re.compile(r"[|–—｜－]| - ")

    def _gate_seo_metadata_corruption(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Detect two SEO-metadata corruption shapes no prior check read at
        all: (a) `head_title`/`seoTitle` losing its "<page> - <brand>"
        separator entirely, and (b) a `keywords` list ballooning in the
        translation -- a structural proxy for fabricated entries, in the
        same spirit as Gate 18's length-ratio hallucination heuristic
        (this is a structural count check, not semantic keyword
        verification, which is out of scope for a gate).
        """
        for field_name in ("head_title", "seoTitle"):
            en_value = _get_frontmatter_field(source_content, field_name)
            if not en_value or not self._SEO_SEPARATOR_RE.search(en_value):
                continue
            tgt_value = _get_frontmatter_field(translated_content, field_name)
            if not tgt_value:
                continue  # empty/missing field is a different gate's concern
            if self._SEO_SEPARATOR_RE.search(tgt_value):
                continue  # separator preserved
            result.passed = False
            result.error = (
                f"GATE40 SEO METADATA {output_path.name}: EN {field_name} has a "
                f"'<page> - <brand>' separator but translated {field_name} "
                f"does not: {tgt_value[:60]!r}"
            )
            logger.warning(
                "GATE40 SEO METADATA separator dropped (warn-only, Phase 8 Tier A) "
                "%s: field=%s en=%r tgt=%r",
                output_path.name,
                field_name,
                en_value[:60],
                tgt_value[:60],
            )
            return

        en_keywords = _get_frontmatter_list_field(source_content, "keywords")
        if en_keywords:
            tgt_keywords = _get_frontmatter_list_field(translated_content, "keywords")
            if (
                tgt_keywords
                and len(tgt_keywords) >= len(en_keywords) + 2
                and (len(tgt_keywords) >= len(en_keywords) * 1.5)
            ):
                result.passed = False
                result.error = (
                    f"GATE40 SEO METADATA {output_path.name}: keywords list grew "
                    f"from {len(en_keywords)} to {len(tgt_keywords)} entries "
                    f"(likely fabricated additions)"
                )
                logger.warning(
                    "GATE40 SEO METADATA keywords ballooned (warn-only, Phase 8 "
                    "Tier A) %s: en=%d tgt=%d",
                    output_path.name,
                    len(en_keywords),
                    len(tgt_keywords),
                )

    # ------------------------------------------------------------------
    # Gate 44: SEO title/description SERP-length sanity
    # HT-QUALITY-GATES-001 Phase 8 (independent-verification finding):
    # no SEO field anywhere in the pipeline (extraction, prompting,
    # validation) has any length/SERP-convention awareness -- a short
    # English title/description can become a much longer translation with
    # nothing anywhere noticing. Reuses Gate 40's keyword-ballooning ratio
    # convention (>=+2 absolute AND >=1.5x relative) rather than inventing a
    # new heuristic. Ships "warn" pending a clean-sample false-positive
    # check, same rollout convention as gates 31-43.
    # ------------------------------------------------------------------

    def _gate_seo_length_sanity(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Flag a translated head_title/seoTitle whose character length
        ballooned past a conservative multiple of the English value -- a
        structural proxy for SERP-truncation risk (Google conventionally
        truncates title tags well before 90 characters), not a semantic
        translation-quality check.
        """
        for field_name in ("head_title", "seoTitle"):
            en_value = _get_frontmatter_field(source_content, field_name)
            if not en_value:
                continue
            tgt_value = _get_frontmatter_field(translated_content, field_name)
            if not tgt_value:
                continue  # empty/missing field is a different gate's concern
            if len(tgt_value) >= len(en_value) + 15 and (len(tgt_value) >= len(en_value) * 1.5):
                result.passed = False
                result.error = (
                    f"GATE44 SEO LENGTH {output_path.name}: {field_name} grew "
                    f"from {len(en_value)} to {len(tgt_value)} chars "
                    f"(SERP-truncation risk): {tgt_value[:60]!r}"
                )
                logger.warning(
                    "GATE44 SEO LENGTH ballooned (warn-only, Phase 8) %s: "
                    "field=%s en_len=%d tgt_len=%d",
                    output_path.name,
                    field_name,
                    len(en_value),
                    len(tgt_value),
                )
                return

    # ------------------------------------------------------------------
    # Gate 41: homoglyph substitution in code spans/identifiers
    # HT-QUALITY-GATES-001 Phase 8 (Tier A #4)
    # ------------------------------------------------------------------

    def _gate_homoglyph_in_code(
        self,
        source_content: str,
        translated_content: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Flag a Cyrillic/Greek confusable character (visually identical
        to an ASCII Latin letter) appearing inside an inline code span or
        fenced code block in the TRANSLATED content -- a literal spec/API
        identifier like ``foo()`` silently corrupted to ``fоo()`` (Cyrillic
        "о") reads identically to a human but is not the real identifier.
        Scoped to code spans/blocks only: legitimate non-Latin PROSE is not
        in scope here (that's Gates 2/4's job) -- an identifier context is
        specifically where a homoglyph is both plausible (MT substitutes a
        visually-similar character) and always wrong (code is never
        translated).
        """
        tgt_body = self._get_body(translated_content)

        # Fenced code block content.
        for start, end in get_fence_char_spans(tgt_body):
            span_text = tgt_body[start:end]
            m = _HOMOGLYPH_CHARS_RE.search(span_text)
            if m:
                self._flag_homoglyph(result, output_path, span_text, m.group())
                return

        # Inline code spans, outside fenced blocks (avoid double-scanning
        # fence content and avoid a lone backtick inside a fence being
        # misread as an inline-span delimiter).
        prose_only = strip_fenced(tgt_body)
        for span_m in _INLINE_CODE_SPAN_RE.finditer(prose_only):
            span_text = span_m.group(1)
            hg_m = _HOMOGLYPH_CHARS_RE.search(span_text)
            if hg_m:
                self._flag_homoglyph(result, output_path, span_text, hg_m.group())
                return

    @staticmethod
    def _flag_homoglyph(
        result: WriteGateResult, output_path: Path, span_text: str, char: str
    ) -> None:
        ascii_equiv = _HOMOGLYPH_TO_ASCII.get(char, "?")
        result.passed = False
        result.error = (
            f"GATE41 HOMOGLYPH IN CODE {output_path.name}: code span "
            f"{span_text[:40]!r} contains {char!r} (U+{ord(char):04X}), a "
            f"look-alike for ASCII {ascii_equiv!r}"
        )
        logger.warning(
            "GATE41 HOMOGLYPH IN CODE (warn-only, Phase 8 Tier A) %s: %s",
            output_path.name,
            result.error,
        )

    # ------------------------------------------------------------------
    # Gate 42: whole-page wrong-target-language contamination
    # HT-QUALITY-GATES-001 Phase 8 (Tier A #1)
    # ------------------------------------------------------------------

    def _gate_whole_page_language_mismatch(
        self,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        result: WriteGateResult,
    ) -> None:
        """Whole-body language-ID classification -- catches wholesale
        wrong-target-language contamination ("this Czech page is actually
        Chinese") that Gate 4/5's per-paragraph purity sampling can miss
        when EVERY paragraph looks equally foreign rather than a minority
        of English leaking through, and that `audit_all_content.py`'s own
        `purity_issue` check structurally cannot catch at all (it's a pure
        ASCII-ratio proxy, not a real language classifier, and only ever
        flags excess ENGLISH specifically).

        Reuses the same production FastTextDetector instance Gates 2-5
        already use -- not a 4th independent language-ID implementation.
        Gracefully no-ops when no detector is available (``self._detector
        is None``, e.g. a dependency-free offline audit context), matching
        Gates 2-5's own degrade behavior in ``evaluate()``.

        Distinct from Gate 2 (action "early_return", bypassed entirely by
        ``force_accept`` and never invoked when ``detector is None``, and
        excluded from the content-gate dispatch loop by its action tier):
        this is a content-tier gate (action "warn"/"block"-eligible,
        auto_clean/block/warn) that runs unconditionally alongside gates
        9-41, so callers that reach this content-gate loop without going
        through Gate 2's early-return path (any ``run_all_content_gates()``
        caller -- the audit sweep, the healer) still get this signal,
        provided they supply a real detector.
        """
        if self._detector is None:
            return
        body = self._get_body(translated_content)
        if len(body.strip()) < 50:
            return  # too short to classify reliably
        try:
            detected_lang, confidence = self._detector.detect(body)
        except Exception:
            return
        if detected_lang == target_lang or confidence < 0.85:
            return
        if self._similarity_tracker and self._similarity_tracker.are_similar(
            target_lang, detected_lang
        ):
            return

        result.passed = False
        result.error = (
            f"GATE42 WHOLE-PAGE LANGUAGE MISMATCH {output_path.name}: "
            f"expected {target_lang}, whole-body classification detected "
            f"{detected_lang} ({confidence:.0%} confidence)"
        )
        logger.warning(
            "GATE42 WHOLE-PAGE LANGUAGE MISMATCH (warn-only, Phase 8 Tier A) %s: %s",
            output_path.name,
            result.error,
        )

    # ------------------------------------------------------------------
    # OW-01 extension: check existing file when new translation failed
    # ------------------------------------------------------------------

    def _check_existing_for_ow01(
        self,
        target_lang: str,
        output_path: Path,
        detector: FastTextDetector,
        result: WriteGateResult,
    ) -> None:
        """When new translation failed validation, check if existing file is correct."""
        if not output_path.exists():
            return
        try:
            existing_content = output_path.read_text(encoding="utf-8")
            existing_lang, existing_conf = detector.detect(existing_content)
            if existing_lang == target_lang:
                result.overwrite_blocked = True
                result.error = (
                    f"Blocked overwrite: existing={existing_lang} "
                    f"({existing_conf:.2%}) preserved, new translation failed"
                )
                logger.info(
                    f"OVERWRITE PROTECTED: New translation failed but existing "
                    f"{target_lang} file ({existing_conf:.2%}) is preserved for {output_path.name}"
                )
            else:
                result.retranslate_queued = True
                result.retranslate_paths.append((output_path, target_lang))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helper: file purity verification
    # ------------------------------------------------------------------

    def _verify_final_file_purity(
        self, content: str, expected_lang: str, detector: FastTextDetector
    ) -> dict:
        """B-7.5: File-level language purity verification."""
        paragraphs = []
        in_code_block = False
        in_frontmatter = False

        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
            elif stripped == "---" and not paragraphs:
                in_frontmatter = not in_frontmatter
            elif not in_code_block and not in_frontmatter and stripped:
                paragraphs.append(stripped)

        if not paragraphs:
            return {"passed": True, "reason": "No content to validate"}

        try:
            _te_cfg = self._config.get_config().get("translation_engine", {})
            conf_threshold = _te_cfg.get("language_detection_confidence_threshold", 0.80)
        except Exception:
            conf_threshold = 0.80

        wrong_lang_count = 0
        total_count = 0
        detected_languages = {}

        for para in paragraphs:
            if len(para) < 20:
                continue
            if self._should_skip_purity_segment(para):
                continue

            try:
                detected, conf = detector.detect(para)
                total_count += 1
                detected_languages[detected] = detected_languages.get(detected, 0) + 1

                if detected != expected_lang and conf > conf_threshold:
                    is_similar = False
                    if self._similarity_tracker:
                        is_similar = self._similarity_tracker.are_similar(expected_lang, detected)
                    if not is_similar:
                        wrong_lang_count += 1
            except (ValueError, Exception) as e:
                logger.debug(f"Paragraph detection failed: {e}")
                continue

        if total_count == 0:
            return {"passed": True, "reason": "No content to validate"}

        wrong_percentage = wrong_lang_count / total_count
        purity_threshold = self._get_purity_threshold(expected_lang)

        # Short-file quorum: for files with ≤10 evaluatable paragraphs, a single wrong-
        # language paragraph produces 10-33% — far above the 6% threshold — causing false
        # failures on API stubs and index pages that legitimately contain English identifiers.
        # For short files, require at least 2 wrong-language paragraphs before blocking.
        # For longer files (>10 paragraphs), the percentage-based threshold handles this.
        if total_count <= 10 and wrong_lang_count <= 1:
            return {
                "passed": True,
                "wrong_lang_percentage": wrong_percentage,
                "detected_languages": detected_languages,
            }

        if wrong_percentage > purity_threshold:
            return {
                "passed": False,
                "wrong_lang_percentage": wrong_percentage,
                "detected_languages": detected_languages,
                "reason": (
                    f"{wrong_lang_count}/{total_count} paragraphs wrong language "
                    f"(threshold: {purity_threshold:.0%})"
                ),
            }

        return {
            "passed": True,
            "wrong_lang_percentage": wrong_percentage,
            "detected_languages": detected_languages,
        }

    def _get_purity_threshold(self, lang: str) -> float:
        """Per-language purity threshold. Falls back to 0.06 default."""
        try:
            overrides = (
                self._config.get_config()
                .get("translation_engine", {})
                .get("purity_threshold_overrides", {})
            )
            threshold = overrides.get(lang, 0.06)
            if not isinstance(threshold, int | float) or not (0.0 <= threshold <= 0.50):
                logger.warning("Invalid purity threshold %.2f for %s, using 0.06", threshold, lang)
                return 0.06
            return float(threshold)
        except Exception:
            return 0.06

    @staticmethod
    def _should_skip_purity_segment(line: str) -> bool:
        """Return True if a line should be excluded from FastText language detection."""
        if not line:
            return False
        if re.fullmatch(r"\{\{[<%].*?[>%]\}\}", line):
            return True
        if line.startswith("|") and line.endswith("|"):
            return True
        inline_code_count = len(re.findall(r"`[^`]+`", line))
        if inline_code_count >= 2:
            return True
        api_identifiers = re.findall(
            r"\b(?:[A-Z][A-Za-z0-9_]*\.)+[A-Z][A-Za-z0-9_]*\b"
            r"|\b[A-Z][a-zA-Z0-9_]+(?:Exception|Options|Builder|Factory|Collection|Renderer|Exporter|Importer|Constants)\b"
            r"|\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b"
            r"|\b[A-Za-z_][A-Za-z0-9_]*\([^)]*\)",
            line,
        )
        if api_identifiers:
            remaining = line
            for token in api_identifiers:
                remaining = remaining.replace(token, " ")
            prose_words = [
                word
                for word in re.findall(r"[A-Za-z]{4,}", remaining)
                if word.lower() not in {"class", "method", "property", "properties"}
            ]
            if len(prose_words) < 4:
                return True
        if re.match(r"^[A-Z][a-zA-Z0-9 ]+:\s*[0-9A-Za-z+\-,. /]+$", line):
            return True
        acronym_tokens = re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", line)
        prose_words = re.findall(r"[A-Za-z]{4,}", line)
        if len(acronym_tokens) >= 3 and len(prose_words) <= len(acronym_tokens) + 3:
            return True
        visible = [c for c in line if not c.isspace()]
        if visible:
            non_letter = sum(1 for c in visible if not c.isalpha())
            if non_letter / len(visible) > 0.60:
                return True
        if re.search(r"Aspose\.\w+", line):
            remaining = re.sub(r"Aspose\.\w+", "", line)
            prose_words = [word for word in remaining.split() if word.isalpha() and len(word) > 3]
            if len(prose_words) < 3:
                return True
        return False
