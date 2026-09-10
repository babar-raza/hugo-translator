"""
TC-DECOMP-04: Segment-level translation logic.

Extracted from TranslationEngine: TM lookup, model call, batching,
placeholder/terminology restoration, multiline structure preservation,
and AST-based body translation.

The translator receives an engine reference for accessing shared state
(TM, model_loader, config, locks, etc.).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from src.model_runtime.campaign_llm_policy import llm_category

from ..observability.progress import get_progress_tracker
from ..utils.log_sanitizer import sanitize_for_log
from .engine import estimate_token_count
from .exceptions import TranslationRetryableError
from .extractor import SegmentExtractor, TextUnitKind
from .extractor.leaf_inventory import LeafClassification, classify_sole_leaf
from .models import TranslationStats, ValidationIssue, ValidationResult
from .reconstructor import MarkdownReconstructor
from .terminology.classification import get_default_protected_terms

if TYPE_CHECKING:
    from .engine import TranslationEngine

logger = logging.getLogger(__name__)


class _RetryFeedbackModel:
    """Inject governed retry instructions into every LLM translation call."""

    def __init__(self, backend, feedback: str) -> None:
        self._backend = backend
        self._feedback = feedback

    def translate(self, texts, src_lang: str, tgt_lang: str, **kwargs):
        kwargs.setdefault("retry_feedback", self._feedback)
        return self._backend.translate_with_retry_feedback(
            texts,
            src_lang,
            tgt_lang,
            **kwargs,
        )

    def translate_with_token_counts(self, texts, src_lang: str, tgt_lang: str, **kwargs):
        kwargs.setdefault("retry_feedback", self._feedback)
        return self._backend.translate_with_token_counts_and_retry_feedback(
            texts,
            src_lang,
            tgt_lang,
            **kwargs,
        )

    def translate_with_context(self, texts, src_lang: str, tgt_lang: str, **kwargs):
        # Keep campaign retry guidance attached to the field-aware LLM path
        # used for frontmatter escalation as well as to ordinary batches.
        # setdefault (not an unconditional override): a caller that already
        # built its own more specific retry_feedback -- e.g. TC-APT-042's
        # cross-field frontmatter repair, which names the exact residual
        # phrase and the sibling field's translation -- must win, not crash
        # with "got multiple values for keyword argument 'retry_feedback'"
        # (found live 2026-09-07, wave8: every retry pass silently ate the
        # TypeError and burned ~2 minutes re-hitting it).
        kwargs.setdefault("retry_feedback", self._feedback)
        return self._backend.translate_with_context(
            texts,
            src_lang,
            tgt_lang,
            **kwargs,
        )

    def __getattr__(self, name):
        return getattr(self._backend, name)


def _effective_same_as_source_tolerance(
    configured_tolerance: float, validation_policy: str
) -> float:
    """Campaign acceptance has no ratio-based untranslated-unit allowance."""
    return 0.0 if validation_policy == "zero-defect" else configured_tolerance


def _allow_legacy_ast_fallback(validation_policy: str) -> bool:
    """Managed zero-defect campaigns never leave the authoritative AST path."""
    return validation_policy != "zero-defect"


def _retry_original_frontmatter_value(
    model_id_override: str | None,
    retry_feedback: str | None,
    validation_policy: str,
) -> bool:
    """Whether an AST retry must bypass placeholder-wrapped frontmatter text.

    Placeholder protection is normally desirable, but short titles containing a
    product entity are a documented M2M100 failure mode: the model can copy the
    entire placeholder-bearing value unchanged.  A governed retry has already
    failed its gates, so send the immutable original value to the selected
    backend and let terminology/structure/language/fidelity gates validate its
    returned bytes.  The LLM escalation path always uses this behavior.
    """
    return model_id_override == "professionalize_llm" or (
        validation_policy == "zero-defect" and bool(retry_feedback)
    )


def _strict_frontmatter_retry_model_id(
    engine: Any,
    site_id: str,
    target_lang: str,
    field_name: str,
    default_model_id: str,
    retry_feedback: str | None,
) -> str:
    """Resolve a pinned, field-scoped strict retry backend.

    The override exists for short SEO fields where the campaign's primary MT
    backend has already failed language validation.  It is deliberately
    profile-and-field scoped, config-pinned, and only reachable after a
    zero-defect retry signal; every returned byte still traverses all gates.
    """
    if not retry_feedback or getattr(engine, "validation_policy", "standard") != "zero-defect":
        return default_model_id
    # Field routing qualifies a local MT retry.  It must not replace the
    # separately governed professional escalation, which is the final
    # independent recovery path for a persistent local-model failure.
    if default_model_id == "professionalize_llm":
        return default_model_id
    try:
        config = engine.config.get_config().get("translation_engine", {})
        overrides = config.get("zero_defect_frontmatter_retry_models", {})
        site_overrides = overrides.get(site_id, {})
        locale_overrides = site_overrides.get(target_lang, {})
        configured = locale_overrides.get(field_name) or site_overrides.get(field_name)
        return str(configured) if configured else default_model_id
    except Exception:
        return default_model_id


def _restore_required_seo_separator(
    field_name: str, source_value: str, translated_value: str
) -> str:
    """Restore only a dropped page/product separator in an SEO scalar.

    Gate 40 requires the delimiter when the English SEO field uses one.  This
    repair is deliberately lossless: it only inserts `` - `` immediately
    before an Aspose product token which is already present in the model
    output, so it cannot add prose, a product, or an untranslated suffix.
    """
    separator_pattern = re.compile(r"[|\u2013\u2014\uff5c\uff0d]| - ")
    source_separator = separator_pattern.search(source_value)
    if field_name not in {"seoTitle", "head_title"} or source_separator is None:
        return translated_value
    if separator_pattern.search(translated_value):
        return translated_value
    source_left = source_value[: source_separator.start()]
    source_right = source_value[source_separator.end() :]
    if not source_left.strip() or not re.search(r"\bAspose(?:\.[A-Za-z0-9.]+)?\b", source_right):
        return translated_value
    product = re.search(r"\bAspose(?:\.[A-Za-z0-9.]+)?\b", translated_value)
    if product is None or not translated_value[: product.start()].strip():
        return translated_value
    separator = source_separator.group()
    rendered_separator = separator if separator == " - " else f" {separator} "
    return (
        translated_value[: product.start()].rstrip()
        + rendered_separator
        + translated_value[product.start() :]
    )


_REVIEWED_IDENTICAL_TRANSLATIONS: dict[str, frozenset[str]] = {
    # "Introduction" is spelled identically in English and French.  This is
    # an exact reviewed equivalence, not an untranslated-unit tolerance.
    "fr": frozenset(
        {
            "introduction",
            # AST text unit following the protected FilterOperatorType name;
            # French uses the same noun and punctuation.
            "conditions.",
            # "Annotations" is spelled identically in English and French
            # (confirmed cognate; TC-SAS-01 hard-failed the identical heading
            # on two independent source pages: introducing-pdf-foss-typescript
            # and introducing-pdf-foss-cpp).
            "annotations",
        }
    ),
}


def _is_reviewed_identical_translation(source_text: str, target_lang: str) -> bool:
    """Return whether an exact same-as-source value is valid for this locale."""
    normalized = re.sub(r"\s+", " ", source_text).strip().casefold()
    return normalized in _REVIEWED_IDENTICAL_TRANSLATIONS.get(target_lang.lower(), frozenset())


def _has_translatable_residue(
    source_text: str, preserve_patterns: list[str] | None, min_word_len: int = 4
) -> bool:
    """Whether a unit still contains a real translatable word once protected spans are masked.

    TC-SAS-01 counts a unit as "unchanged" when the model returns it byte-identical.
    That is only evidence of a failure to translate if there was something translatable
    in the first place. Measured on words-document-net: the link text
    "Aspose.Words for .NET" masks to "{PH} for .NET", whose entire translatable residue
    is the preposition "for" -- so a model that leaves those three characters alone made
    a whole 54-unit cell fail a 0%-tolerance gate. The ar cell of the same page did
    localise it, so this is variance on three characters, not a quality signal.

    Deliberately conservative, so it cannot mask a genuine miss: a unit counts as
    judgeable if the masked residue holds ANY token of >= min_word_len alphabetic
    characters that is not ALL-CAPS (i.e. plausibly a word rather than an identifier or
    acronym). "The source code is available at" stays judgeable; "for .NET" does not.
    This is the same reasoning as TC-APT-040's short-signal floor, applied to a
    different gate, and it joins the exclusions this filter already carries for short
    units, reviewed cognates and table cells.
    """
    residue = source_text or ""
    for pattern in preserve_patterns or []:
        try:
            residue = re.sub(pattern, " ", residue)
        except re.error:
            continue
    # Preserve patterns are not the only governed source-language spans.  The
    # terminology registry is also the canonical protection source for file
    # formats, API identifiers, and product names.  A malformed Markdown row
    # can be parsed as ordinary text (for example ``| — | | glTF |``); without
    # masking the registered term, TC-SAS-01 mistakes that structural fragment
    # for untranslated prose and retries it forever.  Exact terms are escaped
    # deliberately: terminology is configuration, not executable regex.
    for term in get_default_protected_terms().terms:
        if term:
            residue = re.sub(re.escape(term), " ", residue, flags=re.IGNORECASE)
    for token in re.findall(r"[^\W\d_]+", residue, flags=re.UNICODE):
        if len(token) >= min_word_len and not token.isupper():
            return True
    return False


# TC-APT-073: the normalizer now lives in text_fidelity so the AST path can
# share it (see that module's docstring for the measurement and for why the
# AST renderer needs it too -- _translate_body_ast never reaches
# _restore_placeholders below). Re-exported here because callers and tests
# already import it from this module.
from .text_fidelity import normalize_injected_invisibles  # noqa: F401


def _same_as_source_fingerprints(units: list) -> str:
    """Return candidate-free source-unit metadata for autonomous diagnosis."""
    return ",".join(
        (
            f"{getattr(getattr(unit, 'kind', ''), 'value', getattr(unit, 'kind', ''))}:"
            f"{hashlib.sha256((unit.source_text or '').encode('utf-8')).hexdigest()[:16]}:"
            f"{len(unit.source_text or '')}"
        )
        for unit in units
    )


def _unapplied_frontmatter_keys(
    expected_by_key: dict[str, list[str]],
    translated_frontmatter: dict,
    yaml_formatter,
) -> list[str]:
    """Return fields whose rendered value matches no extracted translation."""
    return sorted(
        key
        for key, expected_values in expected_by_key.items()
        if yaml_formatter.get_nested_value(translated_frontmatter, key) not in expected_values
    )


def compute_force_protected_fields(doc, site_profile) -> set[str]:
    """Family/platform index pages (lang/family/platform/_index.md) must keep
    their `title` identical to EN even on sites that otherwise translate
    title on leaf content pages — see is_family_platform_index().

    HT-QUALITY-GATES-001 RC1: extracted from inline logic in
    `_translate_body_ast()` specifically so it's unit-testable against a real
    `HugoDocument` without needing to exercise the rest of that (expensive,
    model-loading) method. The original inline version read
    `getattr(doc, "file_path", None)` — HugoDocument has no `file_path`
    attribute (only `source_path`), so that always evaluated to `None` and
    this protection never actually activated for any file, for as long as
    this code existed. Existing tests only exercised
    `is_family_platform_index()` and `TextUnitExtractor` in isolation with
    the flag hand-set, never this glue — which is exactly why the bug went
    uncaught.
    """
    from .extractor.text_unit_extractor import is_family_platform_index

    source_path = doc.source_path if hasattr(doc, "source_path") and doc.source_path else None
    # include_family_root scoped to sites directly confirmed to need it — not
    # a blanket default, since it changes title-protection behavior. Initially
    # products.aspose.org only (e.g. psd/_index.md, a root-only family with no
    # platform sub-pages, whose title corrupted to the Serbian word for
    # "Death"). kb.aspose.org and docs.aspose.org added (Part 22) after direct
    # sampling of real live content found the identical defect already present
    # at near-universal scale (kb: 7/9 hr, 9/9 fr family-root titles
    # mismatched; docs: 6/9 hr, 9/9 fr) — e.g. kb hr/cells/_index.md's title
    # corrupted to "Sljedeći članakFOSS" ("Next article" + "FOSS", a leaked
    # UI string, not a translation). reference.aspose.org excluded: its
    # `title` field is `mode: passthrough` (never sent to the model), so this
    # vulnerability cannot occur there. blog.aspose.org excluded: it uses
    # `per_language_folders: false` (locale is a file suffix, not a folder),
    # a structurally different layout that `is_family_platform_index()`'s
    # path-part matching doesn't apply to the same way — needs its own
    # investigation before extending here, not a guess.
    _FAMILY_ROOT_SITES = {"products.aspose.org", "kb.aspose.org", "docs.aspose.org"}
    _include_family_root = getattr(site_profile, "site_id", "") in _FAMILY_ROOT_SITES
    if is_family_platform_index(
        source_path,
        getattr(site_profile, "default_source_lang", "en"),
        include_family_root=_include_family_root,
    ):
        return {"title"}
    return set()


class SegmentTranslator:
    """Owns TM lookup, model translation, batching, and reconstruction.

    Receives an engine reference for shared state access.
    """

    def __init__(self, engine: TranslationEngine) -> None:
        self._engine = engine

    @staticmethod
    def _can_reuse_ast_translation(
        segment: Any, translation: str, model_id_override: str | None
    ) -> bool:
        """Return whether a legacy segment result may seed the AST pass.

        An unchanged translatable result is a failed translation signal, not a
        usable translation. During controlled LLM escalation it must reach the
        AST translator again; otherwise the reuse map copies English into the
        AST plan and prevents the escalation backend from seeing the unit that
        the same-as-source or language gate rejected. Explicitly protected
        code and shortcode units are excluded before this reuse decision.
        """
        if model_id_override != "professionalize_llm":
            return True
        source = re.sub(r"\s+", " ", str(getattr(segment, "source_text", "")).strip())
        candidate = re.sub(r"\s+", " ", str(translation).strip())
        return not source or source != candidate

    @staticmethod
    def _should_preserve_multiline_line(text: str) -> bool:
        placeholders = re.findall(r"\{PLACEHOLDER_\d+\}", text)
        if len(placeholders) >= 3:
            return True
        if placeholders and len("".join(placeholders)) / max(len(text), 1) > 0.45:
            return True
        return False

    @staticmethod
    def _has_fenced_code(text: str) -> bool:
        return bool(re.search(r"```.*?```", text, flags=re.DOTALL))

    @staticmethod
    def _placeholder_is_fenced_code(token: str, placeholder_map: dict[str, str] | None) -> bool:
        if not placeholder_map:
            return False
        return SegmentTranslator._has_fenced_code(placeholder_map.get(token, ""))

    @staticmethod
    def _has_fenced_code_or_placeholder(text: str, placeholder_map: dict[str, str] | None) -> bool:
        if SegmentTranslator._has_fenced_code(text):
            return True
        return any(
            SegmentTranslator._placeholder_is_fenced_code(token, placeholder_map)
            for token in re.findall(r"\{PLACEHOLDER_\d+\}", text)
        )

    @staticmethod
    def _split_fenced_code(
        text: str, placeholder_map: dict[str, str] | None = None
    ) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        pos = 0
        pattern = r"```.*?```|\{PLACEHOLDER_\d+\}"
        for match in re.finditer(pattern, text, flags=re.DOTALL):
            token = match.group(0)
            is_code = token.startswith("```") or SegmentTranslator._placeholder_is_fenced_code(
                token, placeholder_map
            )
            if not is_code:
                continue
            if match.start() > pos:
                parts.append(("text", text[pos : match.start()]))
            parts.append(("code", token))
            pos = match.end()
        if pos < len(text):
            parts.append(("text", text[pos:]))
        return parts

    @staticmethod
    def _split_preserved_code(
        text: str, placeholder_map: dict[str, str] | None = None
    ) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        pos = 0
        pattern = r"```.*?```|`[^`\n]+`|\{PLACEHOLDER_\d+\}"
        for match in re.finditer(pattern, text, flags=re.DOTALL):
            token = match.group(0)
            is_code = (
                token.startswith("```")
                or token.startswith("`")
                or SegmentTranslator._placeholder_is_fenced_code(token, placeholder_map)
            )
            if not is_code:
                continue
            if match.start() > pos:
                parts.append(("text", text[pos : match.start()]))
            parts.append(("code", token))
            pos = match.end()
        if pos < len(text):
            parts.append(("text", text[pos:]))
        return parts

    @staticmethod
    def _is_effectively_untranslated(source: str, translated: str) -> bool:
        return source.strip() == translated.strip()

    @staticmethod
    def _product_title_suffix_parts(text: str) -> tuple[str, str, str] | None:
        match = re.match(
            r"^(Aspose\.[A-Za-z0-9.+#-]+(?:\s+FOSS)?)(\s+(?:[\u2013\u2014-])\s+)(.+)$",
            text.strip(),
        )
        if not match:
            return None
        suffix = match.group(3).strip()
        if not suffix or not re.search(r"[A-Za-z]{3,}", suffix):
            return None
        return match.group(1), match.group(2), suffix

    def _repair_untranslated_product_title(
        self,
        backend,
        source_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> str:
        if not self._is_effectively_untranslated(source_text, translated_text):
            return translated_text

        parts = self._product_title_suffix_parts(source_text)
        if not parts:
            return translated_text

        prefix, separator, suffix = parts
        logger.info("Retrying untranslated product title suffix while preserving identity prefix")
        if hasattr(backend, "translate_with_token_counts"):
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                [suffix], source_lang, target_lang
            )
            stats.tokens_input += input_tokens
            stats.tokens_output += output_tokens
        else:
            translations = backend.translate([suffix], source_lang, target_lang)
            stats.tokens_input += estimate_token_count(suffix)
            stats.tokens_output += sum(estimate_token_count(t) for t in translations)

        candidate = translations[0].strip() if translations else ""
        if not candidate or self._is_effectively_untranslated(suffix, candidate):
            return translated_text
        return f"{prefix}{separator}{candidate}"

    def _retry_untranslated_text_by_sentence(
        self,
        backend,
        source_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> str:
        if not self._is_effectively_untranslated(source_text, translated_text):
            return translated_text
        if len(source_text.strip()) >= 20 and not self._has_fenced_code(source_text):
            candidate = self._translate_core_with_residue_variants(
                backend,
                source_text.strip(),
                source_lang,
                target_lang,
                stats,
            )
            if candidate.strip() and not self._is_effectively_untranslated(source_text, candidate):
                return candidate
        if len(source_text.strip()) < 80:
            return translated_text
        if self._has_fenced_code(source_text):
            return translated_text

        pieces = re.findall(r"(.+?(?:[.!?]+|$))(\s*)", source_text, flags=re.DOTALL)
        sentence_items = []
        rendered = []
        for sentence, spacing in pieces:
            if not sentence.strip():
                rendered.append(sentence + spacing)
                continue
            rendered.append("")
            sentence_items.append((len(rendered) - 1, sentence, spacing))

        if len(sentence_items) < 2:
            return translated_text

        logger.info(
            "Retrying effectively untranslated text as sentence chunks "
            f"({len(sentence_items)} chunks, target={target_lang})"
        )
        cores = [sentence.strip() for _, sentence, _ in sentence_items]
        if hasattr(backend, "translate_with_token_counts"):
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                cores, source_lang, target_lang
            )
            stats.tokens_input += input_tokens
            stats.tokens_output += output_tokens
        else:
            translations = backend.translate(cores, source_lang, target_lang)
            stats.tokens_input += sum(estimate_token_count(t) for t in cores)
            stats.tokens_output += sum(estimate_token_count(t) for t in translations)

        for (rendered_idx, sentence, spacing), translation in zip(
            sentence_items, translations, strict=False
        ):
            rendered[rendered_idx] = (
                f"{translation.strip() if translation.strip() else sentence.strip()}{spacing}"
            )

        candidate = "".join(rendered)
        if not candidate.strip() or self._is_effectively_untranslated(source_text, candidate):
            return translated_text
        return candidate

    @staticmethod
    def _english_source_residue_count(source_text: str, translated_text: str) -> int:
        if not source_text or not translated_text:
            return 0
        if source_text.strip() == translated_text.strip():
            return 0

        def _strip_technical(text: str) -> str:
            text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
            return re.sub(
                r"Aspose\.[A-Za-z0-9.+#-]+|Aspose|FOSS|API|SDK|\.NET|Java|Python|TypeScript|"
                r"Node\.js|C\+\+|C#|HTML|PDF|CSV|JSON|TSV|XLSX|Excel|Markdown|NuGet|Maven|pip|GitHub|"
                r"Microsoft|Office|Outlook|Visio|AutoCAD|DWG|DXF|DGN|MSG|EML|CFB|GDI|"
                r"Workbook|Worksheet|Cell|Style|Font|Color|PageSetup",
                " ",
                text,
            )

        source_normalized = re.sub(r"\s+", " ", _strip_technical(source_text)).lower()
        target_text = _strip_technical(translated_text)
        english_function_words = {
            "the",
            "and",
            "for",
            "with",
            "without",
            "that",
            "which",
            "from",
            "into",
            "your",
            "you",
            "can",
            "are",
            "this",
            "these",
            "using",
            "support",
            "supports",
            "provides",
            "allows",
            "enables",
            "library",
            "developers",
            "operations",
            "options",
            "fully",
            "functional",
        }
        count = 0
        for match in re.finditer(r"\b(?:[A-Z]?[a-z]{3,}\s+){4,}[A-Z]?[a-z]{3,}\b", target_text):
            phrase = re.sub(r"\s+", " ", match.group(0).strip()).lower()
            words = set(re.findall(r"[a-z]{3,}", phrase))
            if len(words & english_function_words) < 2:
                continue
            if phrase in source_normalized:
                count += 1
        return count

    def _retry_english_residue_by_sentence(
        self,
        backend,
        source_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> str:
        residue_before = self._english_source_residue_count(source_text, translated_text)
        if residue_before == 0:
            return translated_text
        if len(source_text.strip()) < 40 or self._has_fenced_code(source_text):
            return translated_text

        pieces = re.findall(r"(.+?(?:[.!?]+|$))(\s*)", source_text, flags=re.DOTALL)
        sentence_items = []
        rendered = []
        for sentence, spacing in pieces:
            if not sentence.strip():
                rendered.append(sentence + spacing)
                continue
            rendered.append("")
            sentence_items.append((len(rendered) - 1, sentence, spacing))

        if not sentence_items:
            return translated_text

        logger.info(
            "Retrying text with English source residue as sentence chunks "
            f"(residue={residue_before}, chunks={len(sentence_items)}, target={target_lang})"
        )
        cores = [sentence.strip() for _, sentence, _ in sentence_items]
        if hasattr(backend, "translate_with_token_counts"):
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                cores, source_lang, target_lang
            )
            stats.tokens_input += input_tokens
            stats.tokens_output += output_tokens
        else:
            translations = backend.translate(cores, source_lang, target_lang)
            stats.tokens_input += sum(estimate_token_count(t) for t in cores)
            stats.tokens_output += sum(estimate_token_count(t) for t in translations)

        for (rendered_idx, sentence, spacing), translation in zip(
            sentence_items, translations, strict=False
        ):
            rendered[rendered_idx] = (
                f"{translation.strip() if translation.strip() else sentence.strip()}{spacing}"
            )

        candidate = "".join(rendered)
        if not candidate.strip():
            return translated_text
        if self._english_source_residue_count(source_text, candidate) < residue_before:
            return candidate
        if "`" in source_text or re.search(r"\{PLACEHOLDER_\d+\}", source_text):
            chunk_candidate = self._translate_fenced_code_prose_chunks(
                backend,
                source_text,
                source_lang,
                target_lang,
                stats,
            )
            if self._english_source_residue_count(source_text, chunk_candidate) < residue_before:
                return chunk_candidate
        return translated_text

    @llm_category("repair")
    def _repair_cross_field_frontmatter_residuals(
        self,
        engine,
        units: list,
        primary_model,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> int:
        """TC-APT-042: repair near-duplicate frontmatter fields that left a shared
        phrase untranslated while a sibling field translated the same phrase.

        The sibling's successful translation proves the phrase is translatable, so
        the asymmetric English fragment is retried with corrective feedback naming
        the fragment and the sibling's rendering for terminology consistency.  The
        repaired bytes still traverse every downstream gate before acceptance.
        """
        from .frontmatter_consistency import _normalize, find_cross_field_residuals

        residuals = find_cross_field_residuals(units)
        if not residuals:
            return 0
        if (getattr(engine, "campaign_context", {}) or {}).get("defer_llm_fallbacks"):
            logger.info(
                "TC-APT-042: deferred campaign leaves %d cross-field residual(s) "
                "for page-level retry handling",
                len(residuals),
            )
            return 0
        backend = primary_model if hasattr(primary_model, "translate_with_context") else None
        if backend is None:
            try:
                with engine._model_lock:
                    backend = engine.model_loader.load_model("professionalize_llm")
            except Exception as load_error:
                logger.warning(
                    "TC-APT-042: %d cross-field frontmatter residual(s) found but no "
                    "context-capable backend is available (%s); leaving for gate review",
                    len(residuals),
                    type(load_error).__name__,
                )
                return 0
            if not hasattr(backend, "translate_with_context"):
                return 0
        repaired = 0
        for residual in residuals[:4]:
            unit = residual.unit
            meta = unit.metadata or {}
            original = meta.get("original_text") or unit.source_text
            feedback = (
                f"A previous attempt left the English phrase '{residual.phrase}' "
                "untranslated. Translate the entire text into the target language, "
                "including that phrase. For consistent terminology, the sibling "
                f"frontmatter field '{residual.sibling_field}' translated "
                f"'{residual.sibling_source[:200]}' as "
                f"'{residual.sibling_translation[:200]}'."
            )
            try:
                result = backend.translate_with_context(
                    [str(original)],
                    source_lang,
                    target_lang,
                    context_hint=f"frontmatter_{residual.field_name}",
                    file_context=None,
                    retry_feedback=feedback,
                )
            except Exception as repair_error:
                logger.warning(
                    "TC-APT-042: cross-field repair call failed for field '%s' (%s)",
                    residual.field_name,
                    type(repair_error).__name__,
                )
                continue
            candidate = str(result[0]) if result and result[0] else ""
            if (
                not candidate.strip()
                or candidate.strip() == str(original).strip()
                or _normalize(residual.phrase) in _normalize(candidate)
            ):
                logger.info(
                    "TC-APT-042: cross-field repair did not remove residual phrase "
                    "'%s' from field '%s'; keeping prior candidate for gate review",
                    sanitize_for_log(residual.phrase, 80),
                    residual.field_name,
                )
                continue
            unit.translated_text = _restore_required_seo_separator(
                residual.field_name, str(original), candidate
            )
            if unit.metadata is None:
                unit.metadata = {}
            unit.metadata["cross_field_repair_phrase"] = residual.phrase
            unit.metadata["cross_field_repair_sibling"] = residual.sibling_field
            stats.llm_units_translated += 1
            repaired += 1
            logger.info(
                "TC-APT-042: repaired untranslated shared phrase '%s' in frontmatter "
                "field '%s' using sibling field '%s' as reference",
                sanitize_for_log(residual.phrase, 80),
                residual.field_name,
                residual.sibling_field,
            )
        return repaired

    @llm_category("repair")
    def _repair_duplicate_heading_translations(
        self,
        engine,
        units: list,
        primary_model,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> int:
        """Two DIFFERENT English headings translated independently sometimes
        converge on the identical rendering (confirmed recurring on 2 source
        pages for ja/zh: "Introduction" and "Getting Started" both render to
        the same phrase). Retry every losing heading in a collision with
        feedback naming the sibling's already-used rendering, so it produces
        a distinct-but-accurate translation instead.
        """
        from .heading_uniqueness import _normalize, find_duplicate_heading_translations

        collisions = find_duplicate_heading_translations(units)
        if not collisions:
            return 0
        if (getattr(engine, "campaign_context", {}) or {}).get("defer_llm_fallbacks"):
            logger.info(
                "heading-uniqueness: deferred campaign leaves %d collision(s) "
                "for page-level retry handling",
                len(collisions),
            )
            return 0
        backend = primary_model if hasattr(primary_model, "translate_with_context") else None
        if backend is None:
            try:
                with engine._model_lock:
                    backend = engine.model_loader.load_model("professionalize_llm")
            except Exception as load_error:
                logger.warning(
                    "heading-uniqueness: %d collision(s) found but no context-capable "
                    "backend is available (%s); leaving for gate review",
                    len(collisions),
                    type(load_error).__name__,
                )
                return 0
            if not hasattr(backend, "translate_with_context"):
                return 0
        repaired = 0
        retried = 0
        for collision in collisions:
            for loser in collision.losers:
                if retried >= 4:
                    break
                retried += 1
                feedback = (
                    f"A sibling heading elsewhere in this same document (English: "
                    f"'{collision.winner.source_text}') already uses the exact "
                    f"translation '{collision.shared_translation}'. Translate this "
                    f"DIFFERENT heading with a distinct, still accurate rendering — "
                    f"do not reuse that exact same translated phrase."
                )
                try:
                    result = backend.translate_with_context(
                        [str(loser.source_text)],
                        source_lang,
                        target_lang,
                        context_hint="heading_uniqueness",
                        file_context=None,
                        retry_feedback=feedback,
                    )
                except Exception as repair_error:
                    logger.warning(
                        "heading-uniqueness: repair call failed for heading '%s' (%s)",
                        sanitize_for_log(loser.source_text, 80),
                        type(repair_error).__name__,
                    )
                    continue
                candidate = str(result[0]) if result and result[0] else ""
                if (
                    not candidate.strip()
                    or candidate.strip() == str(loser.source_text).strip()
                    or _normalize(candidate) == _normalize(collision.shared_translation)
                ):
                    logger.info(
                        "heading-uniqueness: repair did not produce a distinct rendering "
                        "for heading '%s'; keeping prior candidate for gate review",
                        sanitize_for_log(loser.source_text, 80),
                    )
                    continue
                loser.translated_text = candidate
                if loser.metadata is None:
                    loser.metadata = {}
                loser.metadata["heading_uniqueness_repair_sibling"] = collision.winner.source_text
                stats.llm_units_translated += 1
                repaired += 1
                logger.info(
                    "heading-uniqueness: repaired duplicate heading translation for '%s' "
                    "(was colliding with sibling '%s')",
                    sanitize_for_log(loser.source_text, 80),
                    sanitize_for_log(collision.winner.source_text, 80),
                )
        return repaired

    def _translate_fenced_code_prose_chunks(
        self,
        backend,
        source_text: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
        placeholder_map: dict[str, str] | None = None,
    ) -> str:
        """Translate prose around fenced code blocks while preserving code exactly."""
        chunks = self._split_preserved_code(source_text, placeholder_map)
        prose_items: list[tuple[int, str]] = []
        rendered: list[str] = []

        for kind, value in chunks:
            if kind == "code" or not value.strip():
                rendered.append(value)
                continue
            rendered.append("")
            prose_items.append((len(rendered) - 1, value))

        for rendered_idx, prose in prose_items:
            leading_match = re.match(r"^\s*", prose)
            trailing_match = re.search(r"\s*$", prose)
            leading = leading_match.group(0) if leading_match else ""
            trailing = trailing_match.group(0) if trailing_match else ""
            core = prose[len(leading) : len(prose) - len(trailing) if trailing else len(prose)]
            if not core:
                rendered[rendered_idx] = prose
                continue
            candidate = self._translate_core_with_residue_variants(
                backend,
                core,
                source_lang,
                target_lang,
                stats,
            )
            rendered[rendered_idx] = (
                f"{leading}{candidate if candidate.strip() else core}{trailing}"
            )

        return "".join(rendered)

    @staticmethod
    def _residue_retry_variants(text: str) -> list[str]:
        variants = []
        normalized = text.replace("fit-to-page", "fit to page")
        normalized = normalized.replace("per-format", "per format")
        normalized = normalized.replace("Open-Source", "Open Source")
        normalized = normalized.replace("open-source", "open source")
        normalized = normalized.replace("Cross-Platform", "Cross Platform")
        normalized = normalized.replace("cross-platform", "cross platform")
        normalized = normalized.replace("CMake-based", "CMake based")
        normalized = normalized.replace("header-and-source", "header and source")
        normalized = normalized.replace("control formula visibility", "hide formulas")
        normalized = normalized.replace("Control formula visibility", "Hide formulas")
        normalized = normalized.replace(
            "Lock individual cells", "Protect cells by locking individual cells"
        )
        normalized = normalized.replace(
            "lock individual cells", "protect cells by locking individual cells"
        )
        normalized = normalized.replace("export styled workbooks", "export formatted workbooks")
        normalized = normalized.replace(
            "Library for Word Document Conversion",
            "Software library for converting Word documents",
        )
        normalized = normalized.replace(
            "library for Word Document Conversion",
            "software library for converting Word documents",
        )
        if normalized != text:
            variants.append(normalized)
        if re.match(r"^\s*Set\b", normalized):
            variants.append(re.sub(r"^\s*Set\b", "Configure", normalized, count=1))
        if re.match(r"^\s*set\b", normalized):
            variants.append(re.sub(r"^\s*set\b", "configure", normalized, count=1))
        return [
            variant
            for idx, variant in enumerate(variants)
            if variant and variant not in variants[:idx]
        ]

    def _translate_core_with_residue_variants(
        self,
        backend,
        core: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> str:
        if hasattr(backend, "translate_with_token_counts"):
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                [core], source_lang, target_lang
            )
            stats.tokens_input += input_tokens
            stats.tokens_output += output_tokens
        else:
            translations = backend.translate([core], source_lang, target_lang)
            stats.tokens_input += estimate_token_count(core)
            stats.tokens_output += sum(estimate_token_count(t) for t in translations)

        candidate = translations[0] if translations else core
        if (
            not self._is_effectively_untranslated(core, candidate)
            and self._english_source_residue_count(core, candidate) == 0
        ):
            return candidate

        for variant in self._residue_retry_variants(core):
            logger.info(
                "Retrying residue-prone short phrase with normalized source variant "
                f"(target={target_lang})"
            )
            if hasattr(backend, "translate_with_token_counts"):
                retry_translations, input_tokens, output_tokens = (
                    backend.translate_with_token_counts([variant], source_lang, target_lang)
                )
                stats.tokens_input += input_tokens
                stats.tokens_output += output_tokens
            else:
                retry_translations = backend.translate([variant], source_lang, target_lang)
                stats.tokens_input += estimate_token_count(variant)
                stats.tokens_output += sum(estimate_token_count(t) for t in retry_translations)
            retry_candidate = retry_translations[0] if retry_translations else ""
            if (
                retry_candidate
                and self._english_source_residue_count(variant, retry_candidate) == 0
            ):
                return retry_candidate
        return candidate

    def translate_to_language(
        self,
        site_id: str,
        site_profile,
        doc,
        segments: list,
        source_lang: str,
        target_lang: str,
        force: bool,
        stats: TranslationStats,
        retry_feedback: str | None = None,
        retry_count: int = 0,
        model_id_override: str | None = None,
        tm_write_buffer: list | None = None,
    ) -> str:
        """
        Translate document to a specific target language.

        INT-01: Returns translated content without writing.
        INT-02: Retry feedback integration and temperature variation.
        """
        engine = self._engine

        # Create translation map: segment text -> translation
        translations = {}
        segments_to_translate = []

        # Step 0 (reference-i18n-hardening-20260725): i18n-first short-string
        # resolution, BEFORE TM and BEFORE force-mode bypass. This is the
        # segment/legacy-path counterpart of the AST path's extraction-time
        # short-circuit (text_unit_extractor.py) — it closes the gap where
        # heading segments on this path never got an i18n lookup at all.
        # Resolved segments are prefilled into `translations` and excluded
        # from every step below (TM batch lookup, the TM-hit loop, the
        # force-mode bypass, and segments_to_translate) — i18n results are
        # therefore NEVER written to TM (stores only cover
        # segments_to_translate), which is deliberate: TM must never cache
        # a value that the resolver itself already serves authoritatively,
        # or a future registry correction would be shadowed by a stale
        # cached hit.
        from .terminology.classification import (  # noqa: PLC0415
            CATEGORIES_FOR_KIND,
            get_default_registry,
            resolve,
        )

        i18n_resolved_ids: set = set()
        _i18n_registry = get_default_registry()
        for _seg in segments:
            _ctx_type = str(_seg.context.context_type) if _seg.context else ""
            if "HEADING" not in _ctx_type:
                continue
            _text = getattr(_seg, "source_text", "") or ""
            if len(_text) > 80:
                continue
            _resolved = resolve(
                _text,
                target_lang,
                categories=CATEGORIES_FOR_KIND["heading_text"],
                registry=_i18n_registry,
                file=str(getattr(doc, "source_path", "")) if doc else None,
            )
            if _resolved.outcome == "table":
                translations[_seg.id] = _resolved.value
                i18n_resolved_ids.add(_seg.id)
                stats.i18n_hits += 1

        _tm_segments = (
            [s for s in segments if s.id not in i18n_resolved_ids]
            if i18n_resolved_ids
            else segments
        )

        # Create extractor instance for inline formatting restoration
        extractor = SegmentExtractor(site_profile, terminology_manager=engine.terminology_manager)

        # CT2-002: Get model_id with language-aware selection
        model_id = model_id_override or engine._get_model_id(
            site_profile, src_lang=source_lang, tgt_lang=target_lang
        )

        # Step 1: TM lookup (unless force=True)
        _tm_site_id = engine._tm_site_namespace(
            site_id,
            getattr(doc, "source_path", None),
        )
        if not force:
            # Batch TM lookup: L1+L2 per-request, then L3 for all misses in one GPU forward pass.
            # RC-4 FIX preserved: frontmatter segments use use_semantic=False (no L3).
            from ..tm.models import LookupRequest as _TMLookupRequest  # noqa: PLC0415

            def _is_fm_seg(seg):
                return bool(
                    seg.context
                    and hasattr(seg.context, "context_type")
                    and str(seg.context.context_type) == "SegmentContextType.FRONTMATTER"
                )

            def _make_tm_req(seg):
                # TC-HT-TMKEY-001: key on the pre-placeholder-protection text when
                # available (frontmatter segments), not the model-input protected
                # text. The protected text replaces identifying content (e.g. a
                # class name in backticks) with a generic positional placeholder,
                # so two unrelated documents sharing a short template (e.g.
                # "`X` class with N methods") would otherwise hash to the same TM
                # key and silently serve each other's cached translation.
                #
                # H2/TC-HDN-003: also scope by field_name (e.g. "description" vs
                # "title") -- narrower than tm_key_text's fix (which prevents
                # cross-DOCUMENT collisions within the same field template) and
                # complementary to it (prevents cross-FIELD-TYPE collisions when
                # two different fields happen to contain identical text).
                _field_name = (
                    seg.context.frontmatter_key
                    if seg.context and getattr(seg.context, "frontmatter_key", None)
                    else ""
                )
                return _TMLookupRequest(
                    site_id=_tm_site_id,
                    src_lang=source_lang,
                    tgt_lang=target_lang,
                    text=getattr(seg, "tm_key_text", None) or seg.source_text,
                    context=str(seg.context) if seg.context else None,
                    field_name=_field_name,
                )

            # reference-i18n-hardening-20260725: _tm_segments excludes
            # i18n-pre-resolved segments (Step 0 above) — they never reach
            # TM lookup at all, on either the exact or semantic path.
            _fm_idx = [i for i, s in enumerate(_tm_segments) if _is_fm_seg(s)]
            _body_idx = [i for i, s in enumerate(_tm_segments) if not _is_fm_seg(s)]
            _tm_batch_results: list = [None] * len(_tm_segments)
            if _fm_idx:
                _fm_res = engine.tm.batch_lookup(
                    [_make_tm_req(_tm_segments[i]) for i in _fm_idx], use_semantic=False
                )
                for _bi, _br in zip(_fm_idx, _fm_res):
                    _tm_batch_results[_bi] = _br
            if _body_idx:
                # HT-QUALITY-GATES-001 Part 22 (plan 5.1 item 5): site profiles
                # declare tm_prefs.min_similarity_score but nothing read it --
                # batch_lookup()'s semantic_threshold silently kept its
                # hardcoded 0.80 default for every site regardless of this
                # config. Wired here so the declared per-site value actually
                # takes effect for the one call site (body segments) that
                # uses L3 semantic search at all (frontmatter above passes
                # use_semantic=False, so threshold is moot there).
                _tm_prefs = getattr(site_profile, "tm_prefs", None)
                _semantic_threshold = getattr(_tm_prefs, "min_similarity_score", 0.80)
                _body_res = engine.tm.batch_lookup(
                    [_make_tm_req(_tm_segments[i]) for i in _body_idx],
                    use_semantic=True,
                    semantic_threshold=_semantic_threshold,
                )
                for _bi, _br in zip(_body_idx, _body_res):
                    _tm_batch_results[_bi] = _br

            for idx, segment in enumerate(_tm_segments, 1):
                # TMO-03: Build lookup context for override filtering
                lookup_context = {
                    "target_lang": target_lang,
                }
                if segment.context:
                    if (
                        hasattr(segment.context, "frontmatter_key")
                        and segment.context.frontmatter_key
                    ):
                        lookup_context["frontmatter_key"] = segment.context.frontmatter_key
                    if hasattr(segment.context, "context_type"):
                        lookup_context["context_type"] = str(segment.context.context_type)

                stats.total_lookups += 1

                # RC-4 FIX applied in pre-batch split above (frontmatter → use_semantic=False).
                tm_result = _tm_batch_results[idx - 1]

                if tm_result.hit:
                    restored = self._restore_placeholders(tm_result.translation or "", segment)
                    translations[segment.id] = restored
                    stats.tm_hits += 1

                    if tm_result.source == "l1_cache":
                        stats.l1_hits += 1
                    elif tm_result.source == "l2_exact":
                        stats.l2_hits += 1
                    elif tm_result.source == "l3_semantic":
                        _ctx_gate_rejected = False
                        try:
                            _tm_cfg = engine.config.get_config().get("tm_defaults", {})
                            if _tm_cfg.get("l3_context_gate_enabled", False):
                                _ctx_threshold = float(
                                    _tm_cfg.get("l3_context_similarity_threshold", 0.50)
                                )
                                _hit_ctx = (
                                    tm_result.candidates[0].context
                                    if tm_result.candidates and tm_result.candidates[0].context
                                    else ""
                                )
                                _seg_ctx = str(segment.context) if segment.context else ""
                                if _hit_ctx and _seg_ctx and engine._l3 is not None:
                                    _ctx_sim = engine._l3.context_similarity(_hit_ctx, _seg_ctx)
                                    if _ctx_sim < _ctx_threshold:
                                        logger.debug(
                                            "L3 context_mismatch: sim=%.2f < %.2f, rejecting hit for %s",
                                            _ctx_sim,
                                            _ctx_threshold,
                                            segment.id,
                                        )
                                        _ctx_gate_rejected = True
                                        del translations[segment.id]
                                        stats.tm_hits -= 1
                        except Exception:
                            pass
                        if not _ctx_gate_rejected:
                            stats.l3_hits += 1

                    # Track cached tokens
                    backend = engine.model_loader.get_tokenizer_for_counting(model_id)
                    if backend and hasattr(backend, "get_token_count"):
                        cached_input_tokens = backend.get_token_count(segment.source_text)
                        cached_output_tokens = backend.get_token_count(tm_result.translation)
                        stats.token_count_method = "actual"
                    else:
                        cached_input_tokens = estimate_token_count(segment.source_text)
                        cached_output_tokens = estimate_token_count(tm_result.translation)
                        stats.token_count_method = "estimated"

                    stats.tokens_cached += cached_input_tokens + cached_output_tokens

                    progress = get_progress_tracker()
                    if progress:
                        progress.cache_hit(
                            layer=tm_result.source.split("_")[0] if tm_result.source else "l1"
                        )
                        progress.segments_completed(1)
                else:
                    segments_to_translate.append(segment)
                    progress = get_progress_tracker()
                    if progress:
                        progress.cache_miss()

                # SR-02: Check for shutdown every 10 segments
                if idx % 10 == 0 and engine._check_shutdown():
                    from .exceptions import ShutdownRequested

                    raise ShutdownRequested(
                        file_path=(
                            str(doc.source_path)
                            if hasattr(doc, "source_path") and doc.source_path
                            else ""
                        ),
                        segments_completed=idx,
                    )

        else:
            # Force mode: translate everything EXCEPT i18n-pre-resolved
            # segments (Step 0 above already ran regardless of `force` —
            # forcing MT on an i18n table hit would defeat the whole point
            # of the resolver).
            logger.info(
                f"Force retranslate enabled: bypassing cache lookup for {len(_tm_segments)} segments "
                f"({source_lang} -> {target_lang})"
            )
            segments_to_translate = _tm_segments

            progress = get_progress_tracker()
            if progress:
                for _ in _tm_segments:
                    progress.cache_miss()

        # Step 1b (TC-HT-ROUTE-001): ContentTypeRouter — pre-translate LLM-routed
        # frontmatter segments before the uniform per-file MT batch call below.
        # Mirrors the AST path's "Step 2a" further down in this same module
        # (_translate_body_ast) — without this, every frontmatter field
        # (description, title, summary, ...) was translated exclusively via the
        # per-file MT backend regardless of the content_type_routing config, so
        # short decontextualized descriptions could hallucinate on MT instead of
        # being routed to professionalize_llm as configured.
        if segments_to_translate:
            try:
                from ..model_runtime.llm_backend import LLMModelBackend as _LLMBackend_seg
                from .content_type_router import ContentTypeRouter as _CTR_seg

                _te_cfg_ctr_seg = (
                    engine.config.get_config().get("translation_engine", {})
                    if hasattr(engine.config, "get_config")
                    else {}
                )
                _ctr_config_seg = _te_cfg_ctr_seg.get("content_type_routing", {})
                if _ctr_config_seg:
                    _router_seg = _CTR_seg(_ctr_config_seg)
                    _llm_segments: list = []
                    _llm_hints_seg: list = []
                    _llm_model_id_seg = None
                    _remaining_segments: list = []
                    for _seg in segments_to_translate:
                        _field_name = (
                            _seg.context.frontmatter_key
                            if _seg.context and getattr(_seg.context, "frontmatter_key", None)
                            else ""
                        )
                        if not _field_name:
                            _remaining_segments.append(_seg)
                            continue
                        _decision_seg = _router_seg.route(_seg, field_name=_field_name)
                        if _decision_seg.model_id:
                            _llm_segments.append(_seg)
                            _llm_hints_seg.append(_decision_seg.context_hint)
                            if _llm_model_id_seg is None:
                                _llm_model_id_seg = _decision_seg.model_id
                        else:
                            _remaining_segments.append(_seg)

                    if _llm_segments and _llm_model_id_seg:
                        logger.info(
                            f"ContentTypeRouter: {len(_llm_segments)}/{len(segments_to_translate)} "
                            f"frontmatter segments routed to LLM backend before MT batch"
                        )
                        segments_to_translate = _remaining_segments
                        try:
                            _llm_backend_seg = engine.model_loader.load_model(_llm_model_id_seg)
                            # HT-QUALITY-GATES-001: was `doc.output_path`, which doesn't
                            # exist on HugoDocument (always fell back to {}). Compute the
                            # real per-locale output path the same way file_pipeline.py does.
                            _output_path_seg = (
                                engine._get_output_path(doc.source_path, target_lang, site_profile)
                                if hasattr(doc, "source_path") and doc.source_path
                                else None
                            )
                            _file_ctx_seg = (
                                _LLMBackend_seg._derive_file_context(str(_output_path_seg))
                                if _output_path_seg
                                else {}
                            )
                        except Exception as _llm_load_err:
                            logger.warning(
                                f"ContentTypeRouter LLM backend load failed "
                                f"({type(_llm_load_err).__name__}): {_llm_load_err}; "
                                f"{len(_llm_segments)} frontmatter segments marked as "
                                f"passthrough (NOT routed to MT)"
                            )
                            _llm_backend_seg = None
                            _file_ctx_seg = {}

                        for _seg, _hint in zip(_llm_segments, _llm_hints_seg):
                            _seg_translation = None
                            _seg_via_llm = False
                            _llm_capable_seg = _llm_backend_seg is not None and hasattr(
                                _llm_backend_seg, "translate_with_context"
                            )
                            if _llm_capable_seg:
                                try:
                                    _llm_result_seg = _llm_backend_seg.translate_with_context(
                                        [_seg.source_text],
                                        source_lang,
                                        target_lang,
                                        context_hint=_hint,
                                        file_context=_file_ctx_seg,
                                        retry_feedback=retry_feedback,
                                    )
                                    if _llm_result_seg and _llm_result_seg[0]:
                                        _seg_translation = _llm_result_seg[0]
                                        _seg_via_llm = True
                                except Exception as _llm_err_seg:
                                    logger.warning(
                                        f"ContentTypeRouter LLM pre-translate failed for "
                                        f"segment ({type(_llm_err_seg).__name__}): {_llm_err_seg}; "
                                        f"segment marked as passthrough"
                                    )
                            elif _llm_backend_seg is not None:
                                # TC-HT-ROUTE-002: the circuit breaker can
                                # transparently substitute a non-LLM fallback
                                # (e.g. m2m100) for `_llm_model_id_seg` without
                                # raising -- it can't do context-aware
                                # translate_with_context(), but it CAN
                                # translate via its normal MT path. Reuse the
                                # same `_translate_with_multiline_support` call
                                # Step 2 below uses for ordinary segments
                                # instead of leaving this one as English
                                # passthrough.
                                try:
                                    _mt_fallback_result_seg = self._translate_with_multiline_support(
                                        backend=_llm_backend_seg,
                                        segments=[_seg],
                                        texts=[_seg.source_text],
                                        source_lang=source_lang,
                                        target_lang=target_lang,
                                        stats=stats,
                                    )
                                    if _mt_fallback_result_seg and _mt_fallback_result_seg[0]:
                                        _seg_translation = _mt_fallback_result_seg[0]
                                except Exception as _mt_fallback_err_seg:
                                    logger.warning(
                                        f"ContentTypeRouter MT-fallback translate failed "
                                        f"for segment "
                                        f"({type(_mt_fallback_err_seg).__name__}): "
                                        f"{_mt_fallback_err_seg}; segment marked as "
                                        f"passthrough"
                                    )

                            if _seg_translation:
                                _final_translation = self._restore_placeholders(
                                    _seg_translation, _seg
                                )
                                if _seg_via_llm:
                                    # HT-QUALITY-GATES-001 Part 22 (plan 5.4 item 4):
                                    # record the per-unit "actually LLM-translated"
                                    # fact (segment-path equivalent of the AST-path
                                    # instrumentation above). Only true when the
                                    # context-aware LLM call itself produced this
                                    # text -- not when the MT fallback above did.
                                    stats.llm_units_translated += 1
                            else:
                                # TC-LLM-AVAIL-001-style graceful degrade: keep the
                                # original text. This is now a true last resort --
                                # reached only when no backend could be loaded at
                                # all, the context-aware LLM call itself failed, or
                                # the MT-fallback attempt above also failed.
                                _final_translation = self._restore_placeholders(
                                    _seg.source_text, _seg
                                )
                                if _seg.metadata is None:
                                    _seg.metadata = {}
                                _seg.metadata["llm_passthrough_reason"] = (
                                    "professionalize_llm_unavailable"
                                )

                            translations[_seg.id] = _final_translation
                            stats.translated_segments += 1
                            stats.words_translated += len(_seg.source_text.split())

                            _store_context_seg = {"target_lang": target_lang}
                            if _seg.context:
                                if getattr(_seg.context, "frontmatter_key", None):
                                    _store_context_seg["frontmatter_key"] = (
                                        _seg.context.frontmatter_key
                                    )
                                if hasattr(_seg.context, "context_type"):
                                    _store_context_seg["context_type"] = str(
                                        _seg.context.context_type
                                    )

                            if engine.cache_write_mode != "never":
                                _force_update_seg = (
                                    True if engine.cache_write_mode == "always" else force
                                )
                                _tm_entry_seg = dict(
                                    site_id=_tm_site_id,
                                    src_lang=source_lang,
                                    tgt_lang=target_lang,
                                    text=getattr(_seg, "tm_key_text", None) or _seg.source_text,
                                    translation=_final_translation,
                                    context=str(_seg.context) if _seg.context else None,
                                    metadata={
                                        "model": _llm_model_id_seg,
                                        "campaign_id": (
                                            getattr(engine, "campaign_context", {}) or {}
                                        ).get("campaign_id"),
                                        "config_fingerprint": (
                                            getattr(engine, "campaign_context", {}) or {}
                                        ).get("config_fingerprint"),
                                        "source_file": (
                                            str(doc.source_path)
                                            if hasattr(doc, "source_path") and doc.source_path
                                            else None
                                        ),
                                    },
                                    store_context=_store_context_seg,
                                    force_update=_force_update_seg,
                                    field_name=_store_context_seg.get("frontmatter_key", ""),
                                )
                                if tm_write_buffer is not None:
                                    tm_write_buffer.append(_tm_entry_seg)
                                else:
                                    engine.tm.store(**_tm_entry_seg)
                                stats.tm_entries_stored += 1
            except Exception as _ctr_err_seg:
                logger.debug(f"ContentTypeRouter (segments) init skipped: {_ctr_err_seg}")

        # Step 2: Translate new segments via model
        if segments_to_translate:
            logger.info(
                f"Translating {len(segments_to_translate)} new segments "
                f"from {source_lang} to {target_lang}"
                + (f" (retry {retry_count} with feedback)" if retry_count > 0 else "")
            )

            with engine._model_lock:
                backend = engine.model_loader.load_model(model_id)
            # TC-APT-004: record the model ACTUALLY used (load_model may have rerouted an open LLM)
            stats.model_used = (
                getattr(getattr(backend, "model_info", None), "model_id", None) or model_id
            )

            texts = [seg.source_text for seg in segments_to_translate]

            # INT-02: Retry feedback — only for LLM backends
            if retry_feedback:
                from ..model_runtime.llm_backend import LLMModelBackend

                if isinstance(backend, LLMModelBackend):
                    backend = _RetryFeedbackModel(backend, retry_feedback)
                    logger.debug(f"Applied retry feedback to {len(texts)} segments")
                else:
                    logger.debug(
                        f"Skipping retry feedback injection for non-LLM backend "
                        f"{type(backend).__name__} -- MT models cannot follow instructions"
                    )

            # INT-02: Retry temperature variation — increase sampling diversity on retries
            #
            # HT-QUALITY-GATES-001 Part 22 (root cause B, retry-temperature
            # leak): `_provider._config.temperature` is shared, mutable state
            # on a cross-thread singleton backend instance (ModelLoader caches
            # one backend per model, reused by every concurrent worker
            # thread). The ORIGINAL bug: this write only happened inside the
            # `retry_count > 0` branch, so once ANY file anywhere retried and
            # raised the temperature, it stayed elevated forever afterward --
            # every subsequent call on that backend, retry or not, ran hotter
            # than intended, for the rest of the process. Fixed here by
            # writing the correct value on EVERY call, retry or not, so the
            # shared state can never be left stale from a previous call by
            # omission. This does not add per-call thread-isolation (that
            # would need `generate()` to accept temperature as an explicit
            # argument across every provider implementation, plumbed through
            # every `backend.translate()`/`translate_with_token_counts()`
            # call site in this file -- real surgery on a cost-incurring hot
            # path, not a surgical fix); a narrow residual risk remains where
            # two concurrent calls on the SAME backend could each observe the
            # other's transient write in the instant before their own
            # generate() call reads it. That residual is materially smaller
            # than the fixed bug (a multi-file-forever drift, now reduced to
            # a same-two-calls microsecond window) and is the honest
            # boundary of what this pass fixes -- see Part 7's stress-test
            # mitigation for verifying this under real concurrent load.
            base_temperature = 0.7
            if retry_count > 0:
                temperature_increment = 0.1
                max_temperature = 1.0
                temperature = min(
                    base_temperature + (retry_count * temperature_increment), max_temperature
                )
            else:
                temperature = base_temperature

            _provider = getattr(getattr(backend, "_provider", None), "_config", None)
            if _provider is not None and hasattr(_provider, "temperature"):
                _provider.temperature = temperature
                logger.debug(
                    f"Retry {retry_count}: applied temperature={temperature} to LLM backend"
                )
            else:
                logger.debug(
                    f"Retry {retry_count}: temperature={temperature} (backend does not support temperature)"
                )
            try:
                progress = get_progress_tracker()
                batch_start_time = time.time()
                if progress:
                    batches_for_lang = math.ceil(len(segments_to_translate) / engine.batch_size)
                    progress.add_batches(batches_for_lang)
                    progress.batch_started(len(segments_to_translate))

                # MSP-02: Translate with multiline structure preservation
                translated_texts = self._translate_with_multiline_support(
                    backend=backend,
                    segments=segments_to_translate,
                    texts=texts,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    stats=stats,
                )

                # SR-02: Check for shutdown after batch translation
                if engine._check_shutdown():
                    from .exceptions import ShutdownRequested

                    raise ShutdownRequested(
                        file_path=(
                            str(doc.source_path)
                            if hasattr(doc, "source_path") and doc.source_path
                            else ""
                        ),
                        segments_completed=len(translations),
                    )

                # Store results in translations map and TM
                for seg_idx, (segment, translation) in enumerate(
                    zip(segments_to_translate, translated_texts, strict=False), 1
                ):
                    translation = self._restore_placeholders(translation, segment)

                    if segment.placeholder_map:
                        missing = engine.placeholder_manager.find_missing_protected_values(
                            translation, segment.placeholder_map
                        )
                        if missing:
                            translation = self._retry_dropped_placeholders_via_llm(
                                segment, translation, missing, source_lang, target_lang
                            )

                    translations[segment.id] = translation
                    stats.translated_segments += 1
                    stats.words_translated += len(segment.source_text.split())

                    store_context = {
                        "target_lang": target_lang,
                    }
                    if segment.context:
                        if (
                            hasattr(segment.context, "frontmatter_key")
                            and segment.context.frontmatter_key
                        ):
                            store_context["frontmatter_key"] = segment.context.frontmatter_key
                        if hasattr(segment.context, "context_type"):
                            store_context["context_type"] = str(segment.context.context_type)

                    if engine.cache_write_mode != "never":
                        if engine.cache_write_mode == "always":
                            force_update = True
                        else:
                            force_update = force

                        _tm_entry = dict(
                            site_id=_tm_site_id,
                            src_lang=source_lang,
                            tgt_lang=target_lang,
                            # TC-HT-TMKEY-001: same rationale as _make_tm_req above —
                            # key on pre-protection text so unrelated documents that
                            # happen to share a short template cannot collide.
                            text=getattr(segment, "tm_key_text", None) or segment.source_text,
                            translation=translation,
                            context=str(segment.context) if segment.context else None,
                            metadata={
                                "model": model_id,
                                "campaign_id": (getattr(engine, "campaign_context", {}) or {}).get(
                                    "campaign_id"
                                ),
                                "config_fingerprint": (
                                    getattr(engine, "campaign_context", {}) or {}
                                ).get("config_fingerprint"),
                                "source_file": (
                                    str(doc.source_path)
                                    if hasattr(doc, "source_path") and doc.source_path
                                    else None
                                ),
                            },
                            store_context=store_context,
                            force_update=force_update,
                            field_name=store_context.get("frontmatter_key", ""),
                        )
                        if tm_write_buffer is not None:
                            tm_write_buffer.append(_tm_entry)
                        else:
                            engine.tm.store(**_tm_entry)
                        stats.tm_entries_stored += 1

                    if seg_idx % 10 == 0 and engine._check_shutdown():
                        from .exceptions import ShutdownRequested

                        raise ShutdownRequested(
                            file_path=(
                                str(doc.source_path)
                                if hasattr(doc, "source_path") and doc.source_path
                                else ""
                            ),
                            segments_completed=len(translations),
                        )

                batch_duration = time.time() - batch_start_time
                if progress:
                    progress.batch_completed(len(segments_to_translate))
                    progress.segments_completed(
                        len(segments_to_translate), duration_s=batch_duration
                    )
                    progress.add_tokens(
                        tokens_in=stats.tokens_input,
                        tokens_out=stats.tokens_output,
                        method=getattr(stats, "token_count_method", "actual"),
                    )

            except Exception as e:
                logger.error(f"Model translation failed: {e}")
                progress = get_progress_tracker()
                if progress:
                    for _ in range(len(segments_to_translate)):
                        progress.segment_failed()
                raise RuntimeError(f"Translation failed: {e}")

        # Step 3: Reconstruct document (AST-based or legacy)
        # TC-HT-004: legacy path retired -- default flipped to True. An
        # explicit `false` requires the allow_legacy_reconstruction escape
        # hatch (tests-only) or this raises immediately.
        use_ast = getattr(site_profile.body, "use_ast_body_reconstruction", True)
        if not use_ast and not getattr(site_profile.body, "allow_legacy_reconstruction", False):
            from .exceptions import SiteProfileConfigError

            raise SiteProfileConfigError(
                f"{getattr(site_profile, 'site_id', '<unknown>')}: "
                "use_ast_body_reconstruction=false requires allow_legacy_reconstruction=true "
                "(legacy path is retired; this is a tests-only escape hatch)."
            )

        if use_ast:
            logger.info("Using AST-based body reconstruction for translation")
            ast_body_rendered = False
            try:
                translated_body = self._translate_body_ast(
                    doc,
                    target_lang,
                    site_profile,
                    stats,
                    segments=segments,
                    translations=translations,
                    model_id_override=model_id_override,
                    retry_feedback=retry_feedback,
                )
                ast_body_rendered = True

                # `_translate_body_ast()` is authoritative for both the body
                # and frontmatter.  ASTRenderer has already applied its
                # candidate units directly to `doc.frontmatter`; applying the
                # legacy segment map again here can overwrite an escalated LLM
                # frontmatter value with an earlier unchanged MT result.
                translated_frontmatter = doc.frontmatter

                from .reconstructor import YAMLFormatter

                yaml_formatter = YAMLFormatter()

                # Structural invariant: verify every frontmatter field was applied
                # before YAMLFormatter performs governed scalar auto-cleaning.
                # The all-gate fixed-point rerun validates the serialized, cleaned
                # bytes; this check is only about reconstruction placement.
                # A field can legitimately have more than one extracted Segment
                # (the segment and AST unit paths overlap for some profiles).  The
                # reconstructed value therefore needs to match *one* authoritative
                # translation for the key, not every duplicate segment in turn.
                _fm_expected_by_key: dict[str, list[str]] = {}
                # Legacy segment results remain a useful placement invariant
                # for normal MT.  On LLM escalation they are explicitly
                # superseded by AST frontmatter units, so comparing against
                # the stale map would manufacture a false placement error.
                if not _retry_original_frontmatter_value(
                    model_id_override,
                    retry_feedback,
                    getattr(engine, "validation_policy", "standard"),
                ):
                    for _seg in segments:
                        if (
                            _seg.context
                            and hasattr(_seg.context, "context_type")
                            and str(_seg.context.context_type) == "SegmentContextType.FRONTMATTER"
                            and _seg.id in translations
                        ):
                            _fm_key = _seg.context.frontmatter_key
                            _expected = translations[_seg.id]
                            _fm_expected_by_key.setdefault(_fm_key, []).append(_expected)
                    # HT-QUALITY-GATES-001 RC2: a downstream AST-side repair
                    # (_repair_cross_field_frontmatter_residuals, TC-APT-042)
                    # may have legitimately overwritten a frontmatter unit's
                    # translated_text AFTER the legacy-segment snapshot above
                    # was taken -- the repair mutates the separate AST
                    # translated_units, never this `translations` dict, so
                    # the snapshot has no way to know about it on its own.
                    # `stats.fm_repair_overrides` was populated from this
                    # same `doc.frontmatter` (the check's own comparison
                    # target) via the same accessor the check uses, so this
                    # only widens acceptance for keys a repair actually
                    # touched -- a key the repair never touched, or a value
                    # the repair failed to actually fix, is still caught.
                    for _fm_repair_key, _fm_repair_values in stats.fm_repair_overrides.items():
                        _fm_expected_by_key.setdefault(_fm_repair_key, []).extend(
                            _fm_repair_values
                        )
                _fm_not_applied = _unapplied_frontmatter_keys(
                    _fm_expected_by_key,
                    translated_frontmatter,
                    yaml_formatter,
                )
                if _fm_not_applied:
                    _fm_error = f"frontmatter_segment_not_applied: keys={sorted(_fm_not_applied)}"
                    if getattr(engine, "validation_policy", "standard") == "zero-defect":
                        raise ValueError(_fm_error)
                    logger.warning(_fm_error)

                frontmatter_yaml = yaml_formatter.format_frontmatter(translated_frontmatter)

                # RC-3 FIX: Verify frontmatter keys were not translated
                _source_keys = set(doc.frontmatter.keys())
                _out_data = self._parse_formatted_frontmatter(frontmatter_yaml)
                _out_keys = set(_out_data.keys()) if isinstance(_out_data, dict) else set()
                if _source_keys != _out_keys:
                    _diff = _source_keys ^ _out_keys
                    raise ValueError(
                        f"Frontmatter key integrity check failed after translation. "
                        f"Mismatched keys: {_diff}"
                    )

                translated_content = f"{frontmatter_yaml}\n{translated_body}"
                logger.info("AST Translation: Successfully reconstructed document")

            except TranslationRetryableError:
                raise
            except Exception as e:
                if not _allow_legacy_ast_fallback(getattr(engine, "validation_policy", "standard")):
                    logger.error(
                        "AST reconstruction failed under zero-defect policy; "
                        "legacy fallback is prohibited",
                        exc_info=True,
                    )
                    raise
                if ast_body_rendered:
                    logger.error(
                        "AST reconstruction failed after body rendering; refusing legacy fallback "
                        "because the document may already be partially mutated",
                        exc_info=True,
                    )
                    raise
                logger.error(f"AST reconstruction failed: {e}", exc_info=True)
                logger.warning("AST translation failed, falling back to legacy reconstruction")
                use_ast = False

        if not use_ast:
            import re as _re_legacy_diag

            _src_ast_text = str(doc.ast) if doc.ast else ""
            _legacy_src_cb = (
                len(_re_legacy_diag.findall(r"^```", _src_ast_text, _re_legacy_diag.MULTILINE)) // 2
            )
            logger.info(
                f"LEGACY DIAG: Source has ~{_legacy_src_cb} code blocks, using legacy MarkdownReconstructor"
            )
            segment_map = {}
            for segment in segments:
                if segment.context and segment.context.node_id:
                    segment_map[segment.context.node_id] = segment.id

            reconstructor = MarkdownReconstructor(site_profile)
            translated_doc = reconstructor.reconstruct_document(
                doc, translations, target_lang, segment_map=segment_map
            )

            translated_content = str(translated_doc)

        # HT-INLINE-CODE-001 TC-ICR-007: structured, machine-parseable
        # instrumentation for which reconstruction path actually rendered
        # this file's body. Purely observational -- does not change
        # behavior. The AST path (TextUnitExtractor, do_not_translate-aware)
        # and the legacy path (MarkdownReconstructor, built from
        # SegmentExtractor's flattened segments) are known to disagree on
        # some content-protection guarantees; this measures how often the
        # legacy fallback actually fires in production before any future
        # decision about changing their precedence (deliberately not
        # decided by this instrumentation alone -- see the plan's
        # structural-roadmap notes).
        logger.info(
            "reconstruction_path_used site=%s lang=%s path=%s",
            getattr(site_profile, "site_id", "<unknown>"),
            target_lang,
            "ast" if use_ast else "legacy",
        )

        stats.tokens_total = stats.tokens_cached + stats.tokens_input + stats.tokens_output

        return translated_content

    @staticmethod
    def _parse_formatted_frontmatter(frontmatter_yaml: str) -> dict:
        """Parse YAMLFormatter output and require Hugo frontmatter delimiters."""
        import re

        import yaml

        match = re.match(r"^---\s*\n(.*?)\n?---\s*(?:\n)?$", frontmatter_yaml, re.DOTALL)
        if not match:
            raise ValueError("Frontmatter key integrity: missing YAML frontmatter delimiters")

        try:
            data = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Frontmatter key integrity: YAML parse failed: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"Frontmatter key integrity: parsed frontmatter is not a mapping "
                f"(got {type(data).__name__})"
            )
        return data

    def _translate_body_ast(
        self,
        doc,
        target_lang: str,
        site_profile,
        stats: TranslationStats,
        segments: list | None = None,
        translations: dict[str, str] | None = None,
        model_id_override: str | None = None,
        retry_feedback: str | None = None,
    ) -> str:
        """Translate document body using AST-based node-addressed translation."""
        engine = self._engine

        from .extractor import TextUnitExtractor
        from .reconstructor import ASTRenderer

        try:
            # The AST pass is the authoritative body reconstruction path. It
            # must use the same governed backend selected for the surrounding
            # attempt; otherwise LLM output is silently overwritten by the
            # profile's default MT backend during reconstruction.
            model_id = model_id_override or engine._get_model_id(site_profile, tgt_lang=target_lang)
            with engine._model_lock:
                mt_model = engine.model_loader.load_model(model_id)
            if retry_feedback:
                from ..model_runtime.llm_backend import LLMModelBackend

                if isinstance(mt_model, LLMModelBackend):
                    mt_model = _RetryFeedbackModel(mt_model, retry_feedback)

            terminology_file = Path("config/terminology/aspose_terms.txt")

            lang_detection_config = engine._load_language_detection_config()
            script_validation_config = lang_detection_config.get("script_validation", {})
            script_validation_thresholds = (
                script_validation_config.get("thresholds", {})
                if script_validation_config.get("enabled", True)
                else None
            )

            _batch_purity_skip_langs = None
            if engine.config:
                try:
                    if hasattr(engine.config, "get_config"):
                        _te_cfg = engine.config.get_config().get("translation_engine", {})
                        _batch_purity_skip_langs = (
                            _te_cfg.get("batch_purity_skip_langs") if _te_cfg else None
                        )
                    elif hasattr(engine.config, "global_config"):
                        _te_cfg = getattr(engine.config.global_config, "translation_engine", None)
                        if _te_cfg:
                            _batch_purity_skip_langs = (
                                _te_cfg.get("batch_purity_skip_langs")
                                if isinstance(_te_cfg, dict)
                                else getattr(_te_cfg, "batch_purity_skip_langs", None)
                            )
                except Exception:
                    pass

            force_protected_fields = compute_force_protected_fields(doc, site_profile)

            # Merge the global preserve_patterns baseline the same way SegmentExtractor
            # does (segment_extractor.py:125-127). Without this, a backtick-quoted
            # identifier gets placeholder-protected when SegmentExtractor builds
            # `segments` but stays raw here; the later reuse-match comparison at
            # ~line 1846 then normalizes two genuinely different strings, "not_matched"
            # sends the unit to an independent re-translation, and that translation
            # disagrees with the one already stored in `translations[]` for the same
            # source -- surfacing as a spurious `frontmatter_segment_not_applied` on
            # any zero-defect m2m100-primary field containing an inline code span
            # (found live 2026-09-07 on description/summary, 3/3 langs of one page).
            from .extractor.segment_extractor import _get_global_body_preserve_patterns

            _merged_preserve_patterns = _get_global_body_preserve_patterns() + (
                site_profile.body.preserve_patterns or []
            )

            extractor = TextUnitExtractor(
                segmentation_strategy=site_profile.body.ast_segmentation_strategy,
                terminology_file=terminology_file if terminology_file.exists() else None,
                mt_model=mt_model,
                preserve_patterns=_merged_preserve_patterns,
                site_profile=site_profile,
                batch_stats_tracker=engine.batch_stats_tracker,
                fasttext_detector=engine.fasttext_detector,
                similarity_tracker=engine.similarity_tracker,
                script_validation_thresholds=script_validation_thresholds,
                batch_purity_skip_langs=_batch_purity_skip_langs,
                force_protected_fields=force_protected_fields,
                target_lang=target_lang,
            )

            logger.info(
                f"AST Translation: Extracting TextUnits from AST (strategy: {site_profile.body.ast_segmentation_strategy})"
            )
            plan = extractor.extract_from_ast(doc.ast, frontmatter=doc.frontmatter)

            total_units = len(plan.units)
            translatable_units = len([u for u in plan.units if not u.do_not_translate])
            protected_units = len([u for u in plan.units if u.do_not_translate])
            logger.info(
                f"AST Translation: Extracted {total_units} units ({translatable_units} translatable, {protected_units} protected)"
            )

            _code_block_units = [u for u in plan.units if u.kind == "block_code"]
            logger.info(
                f"AST DIAG: {len(_code_block_units)} code block TextUnits extracted (do_not_translate={sum(1 for u in _code_block_units if u.do_not_translate)})"
            )

            stats.ast_translation_enabled = True
            stats.ast_units_extracted = total_units
            stats.ast_units_translatable = translatable_units
            stats.ast_units_protected = protected_units
            # HT-QUALITY-GATES-001 RC2: must not leak a previous retry
            # attempt's repair overrides into this attempt's frontmatter
            # placement check -- `stats` is the same object reused across
            # the retry loop in file_pipeline.translate_language().
            stats.fm_repair_overrides = {}

            # E2E FIX: Reuse existing translations if available
            #
            # HT-QUALITY-GATES-001 AST-reuse identity fix (2026-09-10): this
            # used to key `source_to_translation` by re-normalized,
            # placeholder-protected TEXT -- running `strip_markdown()` +
            # a FRESH `PlaceholderManager()` per segment/unit. That was
            # broken two ways:
            #   1. False match: `PlaceholderManager.protect()` resets its
            #      counter on every call, so ANY two single-span units
            #      anywhere on the page (e.g. a lone `.xlsx` code span in a
            #      table cell and an unrelated single-link nav paragraph)
            #      reduce to the identical literal key "{PLACEHOLDER_0}" and
            #      silently collide in the dict -- the wrong one's stored
            #      translation gets reused.
            #   2. False miss: the normalization here used only
            #      `site_profile.body.preserve_patterns`, while the legacy
            #      `segments` were originally built against the MERGED
            #      baseline (`_merged_preserve_patterns` above, mirroring
            #      SegmentExtractor's own `_get_global_body_preserve_patterns()
            #      + site profile` merge). A unit protected differently by
            #      the two normalizations missed its real match, fell into
            #      `unmatched_units`, and got independently retranslated --
            #      producing a second, different result for the same logical
            #      content, which then failed the frontmatter placement-
            #      consistency check under zero-defect policy
            #      (`frontmatter_segment_not_applied`).
            #
            # Fix: key by stable node identity instead of re-derived text.
            # Both legacy `Segment`s and AST `TextUnit`s are extracted from
            # the SAME `doc.ast` node instances (this method receives the
            # identical `doc` used to build `segments` earlier; there is no
            # reparse in between), so every node already carries a stable
            # address assigned once at parse time
            # (`ASTNode.assign_addresses()`). `TextUnit.node_addr` already
            # exposes this. Frontmatter `Segment`s already carry the matching
            # key as `context.frontmatter_key` (identical to the
            # `frontmatter.<key>` / `frontmatter.<key>[i]` addresses
            # `TextUnitExtractor._extract_frontmatter_units()` assigns).
            # Body `Segment`s (paragraph/heading/list-item granularity) did
            # not previously carry their own node's address at all --
            # `SegmentContext.node_addr` (segment_extractor.py) threads the
            # already-existing `ASTNode.node_addr` through instead of
            # inventing a new identity scheme.
            #
            # A body Segment's translation covers ALL of that node's
            # descendant text as one combined string, so reuse is only sound
            # when the node has EXACTLY ONE AST leaf descendant, period (the
            # segment truly IS that one leaf -- e.g. a paragraph that is just
            # a single link), AND that leaf is not do_not_translate. Otherwise
            # the combined translation cannot be correctly split across
            # multiple independent TextUnits, and each is left to translate
            # independently, same as before.
            #
            # TC-APT-105: the leaf count below MUST include do_not_translate
            # leaves. Excluding them (as this used to) makes a container with
            # one protected leaf + one ordinary leaf look like "exactly one"
            # leaf -- so the whole legacy flattened translation (markdown
            # syntax and all) gets assigned to the ordinary sibling, which
            # then renders adjacent to the protected leaf's own, independently
            # correct render, duplicating it. Confirmed live and root-caused
            # on content/docs.aspose.org/en/cells/go/getting-started/
            # quickstart.md's "Next Steps" list (`**[API Reference](url)**:
            # Full class and method documentation`): "API Reference" is a
            # config/terminology.yaml protect-mode term, so its LINK_TEXT leaf
            # is do_not_translate=True; the sibling ": Full class..." leaf is
            # not. Counting only the ordinary leaf made this container look
            # like a single-leaf reuse candidate when it has two.
            reused_count = 0
            not_matched_count = 0
            if segments and translations:
                source_to_translation: dict[str, str] = {}

                _body_units = [
                    u
                    for u in plan.units
                    if u.source_text
                    and not (u.node_addr or "").startswith("frontmatter.")
                ]

                for segment in segments:
                    if segment.id not in translations or not translations[segment.id]:
                        continue
                    translation = translations[segment.id]
                    if not self._can_reuse_ast_translation(
                        segment, translation, model_id_override
                    ):
                        continue

                    ctx = segment.context
                    if (
                        ctx
                        and str(ctx.context_type) == "SegmentContextType.FRONTMATTER"
                        and ctx.frontmatter_key
                    ):
                        source_to_translation[f"frontmatter.{ctx.frontmatter_key}"] = translation
                        continue

                    seg_addr = getattr(ctx, "node_addr", None) if ctx else None
                    if not seg_addr:
                        continue

                    # TD-02: shared reference implementation of this exact
                    # check (leaf_inventory.py) -- exactly one leaf total,
                    # AND that leaf not do_not_translate, or reusing the
                    # legacy segment's combined translation for it would
                    # overwrite a protected value with translated (or
                    # re-rendered) prose. Belt-and-suspenders: the downstream
                    # apply loop already skips do_not_translate units, but
                    # making the intent explicit here avoids populating the
                    # map with an entry that only looks reusable.
                    leaf_result = classify_sole_leaf(seg_addr, _body_units)
                    if leaf_result.classification == LeafClassification.ORDINARY_SOLE_LEAF:
                        source_to_translation[leaf_result.sole_unit.node_addr] = translation

                logger.debug(
                    f"E2E DEBUG: Built mapping with {len(source_to_translation)} segment translations"
                )
                logger.debug(
                    f"E2E DEBUG: First 3 mapped node addresses: {list(source_to_translation.keys())[:3]}"
                )

                unmatched_units = []
                for unit in plan.units:
                    if not unit.do_not_translate and unit.source_text:
                        if unit.node_addr in source_to_translation:
                            unit.translated_text = source_to_translation[unit.node_addr]
                            reused_count += 1
                        else:
                            not_matched_count += 1
                            unmatched_units.append(unit)
                            if not_matched_count <= 5:
                                logger.debug(
                                    f"E2E DEBUG: Unmatched unit [{unit.kind}]: node_addr={unit.node_addr}"
                                )

                logger.info(
                    f"AST Translation: Reused {reused_count} existing translations, {not_matched_count} units not matched"
                )

                if unmatched_units:
                    kind_counts = {}
                    for u in unmatched_units:
                        kind_counts[u.kind] = kind_counts.get(u.kind, 0) + 1
                    logger.debug(f"E2E DEBUG: Unmatched unit kinds: {kind_counts}")

            # Step 2a: ContentTypeRouter — pre-translate LLM-routed units
            # before the MT batch so batch_translate_units() skips them.
            try:
                from ..model_runtime.llm_backend import LLMModelBackend as _LLMBackend
                from .content_type_router import ContentTypeRouter as _CTR

                _te_cfg_ctr = (
                    engine.config.get_config().get("translation_engine", {})
                    if hasattr(engine.config, "get_config")
                    else {}
                )
                _ctr_config = _te_cfg_ctr.get("content_type_routing", {})
                if _ctr_config:
                    _router = _CTR(_ctr_config)
                    _llm_units = []
                    _llm_hints = []
                    _llm_model_id = None
                    for _u in plan.units:
                        if _u.do_not_translate or _u.translated_text:
                            continue
                        _decision = _router.route(
                            _u,
                            field_name=(
                                _u.metadata.get("frontmatter_key", "") if _u.metadata else ""
                            ),
                        )
                        if _decision.model_id:
                            _llm_units.append(_u)
                            _llm_hints.append(_decision.context_hint)
                            if _llm_model_id is None:
                                _llm_model_id = _decision.model_id

                    if _llm_units and _llm_model_id:
                        logger.info(
                            f"ContentTypeRouter: {len(_llm_units)}/{len(plan.units)} units "
                            f"routed to LLM backend before MT batch"
                        )
                        try:
                            _llm_backend = engine.model_loader.load_model(_llm_model_id)
                            # HT-QUALITY-GATES-001: was `doc.output_path` (doesn't exist on
                            # HugoDocument, always fell back to {}) — compute the real
                            # per-locale output path the same way file_pipeline.py does.
                            _output_path = (
                                engine._get_output_path(doc.source_path, target_lang, site_profile)
                                if hasattr(doc, "source_path") and doc.source_path
                                else None
                            )
                            _file_ctx = (
                                _LLMBackend._derive_file_context(str(_output_path))
                                if _output_path
                                else {}
                            )
                            if not hasattr(_llm_backend, "translate_with_context"):
                                # TC-HT-ROUTE-002: the circuit breaker can
                                # transparently substitute a non-LLM fallback
                                # (e.g. m2m100) for `_llm_model_id` without
                                # raising. That fallback can't do context-aware
                                # translate_with_context() -- calling it
                                # unconditionally would AttributeError on the
                                # very first unit and land every unit in this
                                # batch in the `except` below as English
                                # passthrough. Instead, leave these units'
                                # translated_text unset here and let them flow
                                # into `units_needing_translation` /
                                # `batch_translate_units()` below, which
                                # translates via that same fallback's normal
                                # (non-context-aware) MT path.
                                logger.info(
                                    f"ContentTypeRouter: LLM backend for "
                                    f"{_llm_model_id} was substituted with a "
                                    f"non-context-capable fallback "
                                    f"({type(_llm_backend).__name__}); leaving "
                                    f"{len(_llm_units)} unit(s) for the normal "
                                    f"MT batch-translate step instead of LLM "
                                    f"passthrough"
                                )
                            else:
                                for _llm_unit, _hint in zip(_llm_units, _llm_hints):
                                    _llm_result = _llm_backend.translate_with_context(
                                        [_llm_unit.source_text],
                                        site_profile.default_source_lang,
                                        target_lang,
                                        context_hint=_hint,
                                        file_context=_file_ctx,
                                        retry_feedback=retry_feedback,
                                    )
                                    if _llm_result and _llm_result[0]:
                                        _llm_unit.translated_text = _llm_result[0]
                                        # TC-HT-003: tag units the LLM backend
                                        # rejected as prompt-echo/refusal and
                                        # passed through as source text.
                                        if 0 in getattr(_llm_backend, "last_reject_reasons", {}):
                                            if _llm_unit.metadata is None:
                                                _llm_unit.metadata = {}
                                            _llm_unit.metadata["llm_passthrough_reason"] = (
                                                "llm_echo_reject"
                                            )
                                        else:
                                            # HT-QUALITY-GATES-001 Part 22 (plan
                                            # 5.4 item 4): record the per-unit
                                            # "actually LLM-translated" fact so
                                            # write-gate tiering can use it
                                            # directly instead of a locale proxy.
                                            stats.llm_units_translated += 1
                        except Exception as _llm_err:
                            logger.warning(
                                f"ContentTypeRouter LLM pre-translate failed "
                                f"({type(_llm_err).__name__}): {_llm_err}; "
                                f"{len(_llm_units)} units marked as English passthrough "
                                f"(NOT routed to MT — MT output for short API descriptions "
                                f"is worse than keeping English)"
                            )
                            for _u in _llm_units:
                                if not _u.translated_text:
                                    _u.translated_text = _u.source_text
                                    if _u.metadata is None:
                                        _u.metadata = {}
                                    _u.metadata["llm_passthrough_reason"] = (
                                        "professionalize_llm_unavailable"
                                    )
            except Exception as _ctr_err:
                logger.debug(f"ContentTypeRouter init skipped: {_ctr_err}")

            # A placeholder is normally the right representation for MT, but
            # short titles containing one are also copied unchanged by M2M100.
            # On an already-failed zero-defect retry (and always during the
            # controlled LLM escalation), translate the immutable original
            # frontmatter value.  The terminology, placeholder, structure,
            # language, and fidelity gates still validate the returned bytes
            # before acceptance.
            if _retry_original_frontmatter_value(
                model_id_override,
                retry_feedback,
                getattr(engine, "validation_policy", "standard"),
            ):
                try:
                    for _unit in plan.units:
                        _meta = _unit.metadata or {}
                        _original = _meta.get("original_text")
                        _field = _meta.get("field_name")
                        if (
                            _unit.do_not_translate
                            or not _original
                            or not _field
                            or not str(_unit.node_addr).startswith("frontmatter.")
                        ):
                            continue
                        _field_model_id = _strict_frontmatter_retry_model_id(
                            engine,
                            str(getattr(site_profile, "site_id", "")),
                            target_lang,
                            str(_field),
                            model_id,
                            retry_feedback,
                        )
                        _field_model = mt_model
                        if _field_model_id != model_id:
                            with engine._model_lock:
                                _field_model = engine.model_loader.load_model(_field_model_id)
                        if hasattr(_field_model, "translate_with_context"):
                            _result = _field_model.translate_with_context(
                                [str(_original)],
                                site_profile.default_source_lang,
                                target_lang,
                                context_hint=f"frontmatter_{_field}",
                                file_context={},
                            )
                        else:
                            _result = _field_model.translate(
                                [str(_original)],
                                site_profile.default_source_lang,
                                target_lang,
                            )
                        if _result and _result[0]:
                            _unit.translated_text = _restore_required_seo_separator(
                                str(_field), str(_original), _result[0]
                            )
                            stats.llm_units_translated += 1
                except Exception as _frontmatter_llm_error:
                    # Do not substitute source text: the subsequent gates
                    # must reject a failed escalation candidate naturally.
                    logger.warning(
                        "LLM frontmatter escalation unavailable (%s)",
                        type(_frontmatter_llm_error).__name__,
                    )

            # Step 2b: Translate remaining units (MT) with batching + fallback.
            # Units that were pre-translated by the LLM step already have
            # translated_text set and are skipped by batch_translate_units().
            batch_size = site_profile.body.ast_batch_size
            units_needing_translation = [
                u for u in plan.units if not u.do_not_translate and not u.translated_text
            ]
            logger.info(
                f"AST Translation: Translating {len(units_needing_translation)} new units via MT (batch_size: {batch_size}, reused: {reused_count})"
            )

            batch_calls_before = getattr(extractor, "_batch_calls", 0)
            fallbacks_before = getattr(extractor, "_individual_fallbacks", 0)

            translated_units = extractor.batch_translate_units(
                plan.units,
                mt_model,
                site_profile.default_source_lang,
                target_lang,
                batch_size=batch_size,
            )

            _cb_after_batch = [u for u in translated_units if u.kind == "block_code"]
            _cb_with_content = [
                u for u in _cb_after_batch if u.translated_text and u.translated_text.strip()
            ]
            logger.info(
                f"AST DIAG: After batch translate: {len(_cb_after_batch)} code block units, {len(_cb_with_content)} with content"
            )

            # TC-APT-042: near-duplicate frontmatter fields (description/summary)
            # are translated as independent units; when one leaves a shared phrase
            # in English while its sibling translated it, retry with the sibling
            # as reference before validation sees the asymmetric residual.
            try:
                self._repair_cross_field_frontmatter_residuals(
                    engine,
                    translated_units,
                    mt_model,
                    site_profile.default_source_lang,
                    target_lang,
                    stats,
                )
            except Exception as _xf_error:
                logger.warning(
                    "TC-APT-042: cross-field frontmatter repair pass skipped (%s)",
                    type(_xf_error).__name__,
                )

            # Recurrence 2026-09-08: two different English headings sometimes
            # translate to the identical rendering (confirmed ja/zh, 2 pages) --
            # retry the losing heading(s) with the sibling's rendering as the
            # thing to avoid, before validation/review sees the collision.
            try:
                self._repair_duplicate_heading_translations(
                    engine,
                    translated_units,
                    mt_model,
                    site_profile.default_source_lang,
                    target_lang,
                    stats,
                )
            except Exception as _hu_error:
                logger.warning(
                    "heading-uniqueness: repair pass skipped (%s)",
                    type(_hu_error).__name__,
                )

            # TC-SAS-01: Detect translatable units the model returned unchanged (source-lang leakage).
            # do_not_translate=True units are intentionally excluded — they are preserved YAML
            # passthrough fields, code blocks, and shortcodes that must not be translated.
            # TC-SAS-FIX-016: Merge global + site-specific config; site wins.
            # SiteProfile.translation_engine was previously silently dropped by Pydantic
            # (no field declared) so site overrides were never applied.
            _te_cfg_sas_global = (
                engine.config.get_config().get("translation_engine", {})
                if hasattr(engine.config, "get_config")
                else {}
            )
            _te_cfg_sas_site = getattr(site_profile, "translation_engine", None) or {}
            _te_cfg_sas = {**_te_cfg_sas_global, **_te_cfg_sas_site}
            _sas_min_len = int(_te_cfg_sas.get("same_as_source_min_length", 10))
            # The site profile owns the protected-span patterns, so the residue floor
            # sees exactly what the model saw after masking.
            _sas_preserve_patterns = list(
                getattr(site_profile.body, "preserve_patterns", None) or []
            )
            _validation_policy_sas = getattr(engine, "validation_policy", "standard")
            _zero_defect_sas = _validation_policy_sas == "zero-defect"
            _sas_tolerance = _effective_same_as_source_tolerance(
                float(_te_cfg_sas.get("same_as_source_tolerance", 0.0)),
                _validation_policy_sas,
            )
            _translatable_count = sum(1 for u in translated_units if not u.do_not_translate)
            _sas_units = [
                u
                for u in translated_units
                if not u.do_not_translate
                and u.source_text
                and u.translated_text is not None
                and u.translated_text.strip() == u.source_text.strip()
                and len(u.source_text.strip()) > _sas_min_len
                and not _is_reviewed_identical_translation(u.source_text, target_lang)
                # TC-SAS-01 residue floor: the raw-length floor above measures the unit
                # before protected spans are masked, so a unit made almost entirely of
                # governed technical tokens clears it while offering nothing to
                # translate. Judge only units that still hold a real word.
                and _has_translatable_residue(u.source_text, _sas_preserve_patterns)
                # TC-TBL-012 / Layer 2: Exclude table cells from SAS ratio.
                # A table cell the model fails to translate stays as English text —
                # bad for quality but handled by Gate 15 / purity check. Counting
                # them toward SAS ratio triggers legacy fallback which corrupts table
                # structure far more severely (3×+ row count expansion).
                and u.kind != TextUnitKind.TABLE_CELL_TEXT
            ]
            if _sas_units:
                _sas_ratio = (
                    len(_sas_units) / _translatable_count if _translatable_count > 0 else 0.0
                )
                if _sas_ratio > _sas_tolerance:
                    # TC-TBL-012 / Layer 2: Suppress legacy fallback for table-containing
                    # documents. MarkdownReconstructor corrupts tables (3×+ row expansion)
                    # when raw markdown pipe chars are sent to the model. A partial AST
                    # result (some cells in source language) is far better than structurally
                    # corrupted tables. Only suppress if the document actually has tables.
                    _ast_has_tables = False
                    if doc.ast:
                        from .parser.ast_nodes import NodeType as _NT_SAS

                        def _check_ast_tables(nodes: list) -> bool:
                            for _n in nodes:
                                if getattr(_n, "type", None) == _NT_SAS.TABLE:
                                    return True
                                if getattr(_n, "children", None) and _check_ast_tables(_n.children):
                                    return True
                            return False

                        _ast_nodes = doc.ast if isinstance(doc.ast, list) else [doc.ast]
                        _ast_has_tables = _check_ast_tables(_ast_nodes)

                    if _ast_has_tables and not _zero_defect_sas:
                        logger.warning(
                            f"TC-SAS-01: ratio {_sas_ratio:.1%} > {_sas_tolerance:.1%} but "
                            f"document contains tables — suppressing legacy fallback to preserve "
                            f"table structure. Proceeding with partial AST result "
                            f"({len(_sas_units)} untranslated units, "
                            f"{len(_sas_units)}/{_translatable_count})."
                        )
                    else:
                        from .exceptions import TranslationIncomplete

                        raise TranslationIncomplete(
                            f"TC-SAS-01: same-as-source ratio {_sas_ratio:.1%} exceeds tolerance "
                            f"{_sas_tolerance:.1%} ({len(_sas_units)}/{_translatable_count} units unchanged); "
                            f"unit_fingerprints={_same_as_source_fingerprints(_sas_units)}",
                            missing_count=len(_sas_units),
                            total_count=_translatable_count,
                            ratio=_sas_ratio,
                            tolerance=_sas_tolerance,
                        )
                else:
                    logger.info(
                        "TC-SAS-01 accepted within configured standard-policy tolerance: "
                        "%d/%d units (ratio=%.1f%%, tolerance=%.1f%%)",
                        len(_sas_units),
                        _translatable_count,
                        _sas_ratio * 100,
                        _sas_tolerance * 100,
                    )

            # AGENT B-7.3: Check batch-level purity failures
            batch_stats = extractor.batch_stats
            if (
                batch_stats.get("language_purity_failures", 0) > 0
                and target_lang not in (_batch_purity_skip_langs or [])
                and not getattr(engine, "_force_accept", False)
            ):
                # Use outer-batch counters so reactive sub-batch splitting doesn't
                # artificially inflate the failure rate.
                total_outer_batches = batch_stats.get("total_outer_batches", 0)
                failed_outer_batches = batch_stats.get("failed_outer_batches", 0)
                if total_outer_batches > 0 and failed_outer_batches > 0:
                    purity_failure_rate = failed_outer_batches / total_outer_batches

                    if purity_failure_rate > 0.10:
                        logger.error(
                            f"HIGH PURITY FAILURE RATE: {purity_failure_rate:.1%} of outer batches failed "
                            f"language validation. Blocking write to prevent corruption. "
                            f"Stats: {failed_outer_batches}/{total_outer_batches} outer batches failed."
                        )

                        issues = [
                            ValidationIssue(
                                severity="error",
                                rule="BatchLanguagePurity",
                                message=f"High batch purity failure rate: {purity_failure_rate:.1%} ({failed_outer_batches}/{total_outer_batches} outer batches)",
                                location=(
                                    str(doc.source_path)
                                    if hasattr(doc, "source_path") and doc.source_path
                                    else None
                                ),
                            )
                        ]
                        validation_result = ValidationResult(valid=False, issues=issues)
                        raise TranslationRetryableError(
                            message=f"Batch purity failure rate too high: {purity_failure_rate:.1%}",
                            file_path=(
                                str(doc.source_path)
                                if hasattr(doc, "source_path") and doc.source_path
                                else ""
                            ),
                            validation_result=validation_result,
                            retry_feedback=f"Batch language purity check failed for {purity_failure_rate:.1%} of outer batches. Ensure all translated units are in the target language {target_lang}.",
                        )

            empty_units = [
                u
                for u in translated_units
                if not u.do_not_translate
                and (u.translated_text is None or u.translated_text.strip() == "")
                and u.source_text
                and u.source_text.strip() != ""
                and len(u.source_text.strip()) > 2
            ]
            if empty_units:
                all_empty = [
                    u
                    for u in translated_units
                    if not u.do_not_translate
                    and (u.translated_text is None or u.translated_text.strip() == "")
                ]
                if len(all_empty) > len(empty_units):
                    logger.debug(
                        f"Skipped {len(all_empty) - len(empty_units)} empty translations "
                        f"for whitespace/short source text"
                    )

                issues = [
                    ValidationIssue(
                        severity="error",
                        rule="ASTTranslation",
                        message=f"{len(empty_units)} units with substantial source text returned empty translations",
                        location=(
                            str(doc.source_path)
                            if hasattr(doc, "source_path") and doc.source_path
                            else None
                        ),
                    )
                ]
                validation_result = ValidationResult(valid=False, issues=issues)
                raise TranslationRetryableError(
                    message="AST translation produced empty outputs for substantial text",
                    file_path=(
                        str(doc.source_path)
                        if hasattr(doc, "source_path") and doc.source_path
                        else ""
                    ),
                    validation_result=validation_result,
                    retry_feedback="All translated segments with substantial source text must return non-empty output.",
                )

            stats.ast_batch_calls = batch_calls_before - batch_calls_before  # intentional reset
            stats.ast_batch_calls = getattr(extractor, "_batch_calls", 0) - batch_calls_before
            stats.ast_individual_fallbacks = (
                getattr(extractor, "_individual_fallbacks", 0) - fallbacks_before
            )

            # Step 3: Apply translations to AST and frontmatter
            logger.info("AST Translation: Applying translations to AST and frontmatter")
            renderer = ASTRenderer()
            renderer.apply_translations(
                doc.ast, translated_units, frontmatter=doc.frontmatter, target_lang=target_lang
            )

            # HT-QUALITY-GATES-001 RC2 (follow-up to TC-APT-042/TC-APT-106):
            # _repair_cross_field_frontmatter_residuals (above) legitimately
            # mutates a frontmatter unit's translated_text to fix a near-
            # duplicate field's untranslated shared phrase -- AFTER
            # translate_to_language's placement-consistency snapshot
            # (_fm_expected_by_key, sourced from the separate legacy
            # segments/translations pass) has typically already been taken,
            # and that snapshot is never updated by this AST-side repair.
            # Record the ACTUAL rendered value for every frontmatter key a
            # repair touched, read via the exact accessor
            # (`YAMLFormatter.get_nested_value`) the placement check itself
            # uses against this same `doc.frontmatter`, so that check can
            # accept the legitimate repair as an additional valid expectation
            # instead of flagging it as frontmatter_segment_not_applied. Keys
            # the repair never touched are untouched here, so a genuinely
            # wrong/unapplied frontmatter translation is still caught.
            _repaired_fm_keys = {
                str(_u.node_addr)[len("frontmatter.") :]
                for _u in translated_units
                if str(getattr(_u, "node_addr", "") or "").startswith("frontmatter.")
                and "cross_field_repair_phrase" in (getattr(_u, "metadata", None) or {})
            }
            if _repaired_fm_keys:
                from .reconstructor.yaml_formatter import YAMLFormatter as _FmRepairYamlFormatter

                _fm_repair_yaml_formatter = _FmRepairYamlFormatter()
                for _fm_repair_key in _repaired_fm_keys:
                    _repaired_value = _fm_repair_yaml_formatter.get_nested_value(
                        doc.frontmatter, _fm_repair_key
                    )
                    if _repaired_value is not None:
                        stats.fm_repair_overrides.setdefault(_fm_repair_key, []).append(
                            _repaired_value
                        )

            # P0-D: Placeholder leak = blocking failure
            if renderer.placeholder_leak_count > 0:
                from .exceptions import TranslationIncomplete

                raise TranslationIncomplete(
                    f"PLACEHOLDER_LEAK: {renderer.placeholder_leak_count} unreplaced placeholder token(s) "
                    f"detected after AST reconstruction. File write blocked to prevent stray tokens in output.",
                    missing_count=renderer.placeholder_leak_count,
                    total_count=renderer.placeholder_leak_count,
                    ratio=1.0,
                    tolerance=0.0,
                )

            # TC-MLD-01: Expose missing node count
            stats.ast_missing_nodes = renderer._missing_node_count
            if renderer._missing_node_count > 0:
                total_checked = len(renderer.applied_units) + renderer._missing_node_count
                fallback_ratio = (
                    renderer._missing_node_count / total_checked if total_checked > 0 else 0.0
                )
                _te_cfg_ast01 = (
                    engine.config.get_config().get("translation_engine", {})
                    if hasattr(engine.config, "get_config")
                    else {}
                )
                _tolerance = float(_te_cfg_ast01.get("ast_fallback_node_tolerance", 0.0))
                logger.warning(
                    f"AST Translation: {renderer._missing_node_count}/{total_checked} nodes had no "
                    f"translation unit (ratio={fallback_ratio:.1%}, tolerance={_tolerance:.1%}) "
                    f"-- source text may appear in output."
                )
                if fallback_ratio > _tolerance:
                    from .exceptions import TranslationIncomplete

                    raise TranslationIncomplete(
                        f"AST fallback ratio {fallback_ratio:.1%} exceeds tolerance {_tolerance:.1%} "
                        f"({renderer._missing_node_count}/{total_checked} nodes missing translation unit)",
                        missing_count=renderer._missing_node_count,
                        total_count=total_checked,
                        ratio=fallback_ratio,
                        tolerance=_tolerance,
                    )

            # Step 4: Render to Markdown
            logger.info("AST Translation: Rendering AST to Markdown")
            translated_body = renderer.render_to_markdown(doc.ast)

            import re as _re_diag

            _rendered_cb = len(_re_diag.findall(r"^```", translated_body, _re_diag.MULTILINE)) // 2
            logger.info(f"AST DIAG: Rendered markdown contains {_rendered_cb} code blocks")

            logger.info(
                f"AST Translation: Successfully translated {translatable_units} units "
                f"({stats.ast_batch_calls} batches, {stats.ast_individual_fallbacks} fallbacks)"
            )

            return translated_body

        except TranslationRetryableError:
            raise
        except Exception as e:
            from .exceptions import TranslationIncomplete

            if isinstance(e, TranslationIncomplete):
                raise
            logger.error(f"AST-based translation failed: {e}", exc_info=True)
            raise RuntimeError(f"AST-based translation failed: {e}")

    @llm_category("repair")
    def _retry_dropped_placeholders_via_llm(
        self,
        segment,
        translation: str,
        missing: list[str],
        source_lang: str,
        target_lang: str,
    ) -> str:
        """
        HT-QUALITY-GATES-001 Part 20: one-shot fallback when the primary MT
        model silently drops a protected span. Confirmed directly against the
        real nllb_200_1.3b model: it doesn't just corrupt a placeholder's shape
        (restore()'s fuzzy pass already recovers those) -- it can drop the
        token entirely and hallucinate unrelated fluent prose in its place,
        leaving no trace to restore from. No regex fix is possible for that
        case; the only confirmed mitigation is re-translating via a stronger
        backend. `professionalize_llm` (a real, already-configured company LLM
        endpoint used elsewhere in this pipeline for CASE-4 escalation) was
        tested directly against the exact real segment that dropped 3/12
        placeholders under nllb_200_1.3b: it restored all 12 correctly.
        """
        engine = self._engine
        if (getattr(engine, "campaign_context", {}) or {}).get("defer_llm_fallbacks"):
            logger.info(
                "Dropped-placeholder fallback deferred to the campaign LLM queue for %s",
                target_lang,
            )
            return translation
        try:
            fallback_backend = engine.model_loader.load_model("professionalize_llm")
        except Exception as e:
            logger.warning(
                f"Dropped-placeholder fallback: could not load professionalize_llm "
                f"({type(e).__name__}): {e}; keeping original translation "
                f"(missing: {missing})"
            )
            return translation

        try:
            fallback_raw = fallback_backend.translate(
                [segment.source_text], source_lang, target_lang
            )
            fallback_raw = fallback_raw[0] if fallback_raw else ""
        except Exception as e:
            logger.warning(
                f"Dropped-placeholder fallback: professionalize_llm call failed "
                f"({type(e).__name__}): {e}; keeping original translation "
                f"(missing: {missing})"
            )
            return translation

        fallback_restored = engine.placeholder_manager.restore(
            fallback_raw, segment.placeholder_map
        )
        fallback_missing = engine.placeholder_manager.find_missing_protected_values(
            fallback_restored, segment.placeholder_map
        )

        if fallback_missing:
            logger.warning(
                f"Dropped-placeholder fallback via professionalize_llm still "
                f"missing {len(fallback_missing)} value(s): {fallback_missing} "
                f"-- keeping original MT translation (both incomplete)"
            )
            return translation

        logger.info(
            f"Dropped-placeholder fallback: professionalize_llm recovered "
            f"{len(missing)} value(s) the primary model dropped: {missing}"
        )
        return fallback_restored

    def _restore_placeholders(self, text: str, segment) -> str:
        """Restore placeholder content (links, shortcodes, etc.) in translated text."""
        engine = self._engine
        if not text:
            return text

        # TC-APT-073: normalize BEFORE restoring, so protected spans are still
        # masked and cannot be altered by it.
        result = normalize_injected_invisibles(getattr(segment, "source_text", "") or "", text)

        # TRM-05: Restore terminology placeholders first
        if engine.terminology_manager and getattr(segment, "protected_terms", None):
            try:
                for protected_segment in segment.protected_terms:
                    if protected_segment.term_mapping:
                        from .terminology.models import ProtectedSegment

                        translated_protected = ProtectedSegment(
                            original_text=protected_segment.original_text,
                            protected_text=result,
                            term_mapping=protected_segment.term_mapping,
                        )
                        result = engine.terminology_manager.restore(translated_protected)
                        logger.debug(
                            f"Restored {len(protected_segment.term_mapping)} terminology terms"
                        )
            except Exception as e:
                logger.warning(f"Terminology restore failed: {e}")

        # Restore shortcode/pattern placeholders
        if getattr(segment, "placeholder_map", None):
            try:
                result = engine.placeholder_manager.restore(result, segment.placeholder_map)
            except Exception as e:
                logger.warning(f"Placeholder restore failed: {e}")

        return result

    def _translate_with_multiline_support(
        self,
        backend,
        segments: list,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> list[str]:
        """Translate texts with multiline structure preservation (MSP-02)."""
        engine = self._engine
        batch_size = getattr(engine, "batch_size", 1)
        sort_by_length = getattr(engine, "sort_segments_by_length", False)

        multiline_indices = []
        singleline_indices = []
        singleline_texts = []

        for idx, (segment, text) in enumerate(zip(segments, texts, strict=False)):
            if engine.multiline_handler.is_multiline(segment.source_text):
                multiline_indices.append(idx)
            else:
                singleline_indices.append(idx)
                singleline_texts.append(text)

        translated_texts = [None] * len(texts)

        # Translate single-line texts in batches
        if singleline_texts:
            batch_translations = []
            total_texts = len(singleline_texts)

            if sort_by_length and total_texts > 1:
                sorted_indices = sorted(range(total_texts), key=lambda i: len(singleline_texts[i]))
                sorted_texts = [singleline_texts[i] for i in sorted_indices]
                logger.debug(
                    f"SR-01: Sorting {total_texts} segments by length "
                    f"(range: {len(sorted_texts[0])}-{len(sorted_texts[-1])} chars)"
                )
            else:
                sorted_indices = list(range(total_texts))
                sorted_texts = singleline_texts

            for chunk_start in range(0, total_texts, batch_size):
                chunk_end = min(chunk_start + batch_size, total_texts)
                chunk_texts = sorted_texts[chunk_start:chunk_end]

                if hasattr(backend, "translate_with_token_counts"):
                    chunk_translations, input_tokens, output_tokens = (
                        backend.translate_with_token_counts(chunk_texts, source_lang, target_lang)
                    )
                    stats.tokens_input += input_tokens
                    stats.tokens_output += output_tokens
                else:
                    chunk_translations = backend.translate(chunk_texts, source_lang, target_lang)
                    stats.tokens_input += sum(estimate_token_count(t) for t in chunk_texts)
                    stats.tokens_output += sum(estimate_token_count(t) for t in chunk_translations)

                batch_translations.extend(chunk_translations)

                if total_texts > batch_size:
                    logger.debug(
                        f"Translated batch {chunk_start // batch_size + 1}/"
                        f"{(total_texts + batch_size - 1) // batch_size} "
                        f"({len(chunk_texts)} texts)"
                    )

            unsorted_translations = [None] * total_texts
            for sorted_idx, original_list_idx in enumerate(sorted_indices):
                unsorted_translations[original_list_idx] = batch_translations[sorted_idx]

            for list_idx, original_idx in enumerate(singleline_indices):
                candidate = self._retry_untranslated_text_by_sentence(
                    backend,
                    texts[original_idx],
                    unsorted_translations[list_idx],
                    source_lang,
                    target_lang,
                    stats,
                )
                candidate = self._retry_english_residue_by_sentence(
                    backend,
                    texts[original_idx],
                    candidate,
                    source_lang,
                    target_lang,
                    stats,
                )
                translated_texts[original_idx] = self._repair_untranslated_product_title(
                    backend,
                    texts[original_idx],
                    candidate,
                    source_lang,
                    target_lang,
                    stats,
                )

        # Translate multiline texts with structure preservation
        if multiline_indices:
            logger.info(
                f"MSP-02: Processing {len(multiline_indices)} multiline segments "
                f"with structure preservation"
            )
            multiline_batch_size = 1
            logger.info("MSP-02: Using batch_size=1 for multiline lines")
            multiline_line_items = []
            multiline_line_info = {}
            fenced_code_indices = set()

            for original_idx in multiline_indices:
                text = texts[original_idx]
                segment = segments[original_idx]
                if self._has_fenced_code_or_placeholder(
                    segment.source_text, getattr(segment, "placeholder_map", None)
                ):
                    fenced_code_indices.add(original_idx)
                    translated_texts[original_idx] = self._translate_fenced_code_prose_chunks(
                        backend,
                        segment.source_text,
                        source_lang,
                        target_lang,
                        stats,
                        getattr(segment, "placeholder_map", None),
                    )
                    continue
                lines_info = engine.multiline_handler.parse_lines(text)
                multiline_line_info[original_idx] = lines_info
                for line_info in lines_info:
                    if line_info.is_empty:
                        continue
                    if not line_info.content.strip():
                        continue
                    if self._should_preserve_multiline_line(line_info.content):
                        logger.debug(
                            "MSP-02: Preserving placeholder-dense multiline line without MT"
                        )
                        continue
                    multiline_line_items.append(
                        (original_idx, line_info.line_index, line_info.content)
                    )

            stats.multiline_segments += len(multiline_indices)
            stats.multiline_lines += len(multiline_line_items)

            translated_line_map = {}
            multiline_backend_calls = 0

            if multiline_line_items:
                line_texts = [item[2] for item in multiline_line_items]

                if sort_by_length and len(line_texts) > 1:
                    sorted_indices = sorted(
                        range(len(line_texts)), key=lambda i: len(line_texts[i])
                    )
                    sorted_texts = [line_texts[i] for i in sorted_indices]
                    logger.debug(
                        f"MSP-02: Sorting {len(line_texts)} multiline lines by length "
                        f"(range: {len(sorted_texts[0])}-{len(sorted_texts[-1])} chars)"
                    )
                else:
                    sorted_indices = list(range(len(line_texts)))
                    sorted_texts = line_texts

                batch_translations = []
                total_lines = len(sorted_texts)

                for chunk_start in range(0, total_lines, multiline_batch_size):
                    chunk_end = min(chunk_start + multiline_batch_size, total_lines)
                    chunk_texts = sorted_texts[chunk_start:chunk_end]
                    multiline_backend_calls += 1

                    if hasattr(backend, "translate_with_token_counts"):
                        chunk_translations, input_tokens, output_tokens = (
                            backend.translate_with_token_counts(
                                chunk_texts, source_lang, target_lang
                            )
                        )
                        stats.tokens_input += input_tokens
                        stats.tokens_output += output_tokens
                    else:
                        chunk_translations = backend.translate(
                            chunk_texts, source_lang, target_lang
                        )
                        stats.tokens_input += sum(estimate_token_count(t) for t in chunk_texts)
                        stats.tokens_output += sum(
                            estimate_token_count(t) for t in chunk_translations
                        )

                    batch_translations.extend(chunk_translations)

                    if total_lines > multiline_batch_size:
                        logger.debug(
                            f"MSP-02: Translated multiline batch {chunk_start // multiline_batch_size + 1}/"
                            f"{(total_lines + multiline_batch_size - 1) // multiline_batch_size} "
                            f"({len(chunk_texts)} lines)"
                        )

                unsorted_translations = [None] * total_lines
                for sorted_idx, original_list_idx in enumerate(sorted_indices):
                    unsorted_translations[original_list_idx] = batch_translations[sorted_idx]

                for list_idx, (segment_idx, line_idx, _) in enumerate(multiline_line_items):
                    translated_line_map[(segment_idx, line_idx)] = unsorted_translations[list_idx]

            stats.multiline_backend_calls += multiline_backend_calls

            for original_idx in multiline_indices:
                if original_idx in fenced_code_indices:
                    continue
                segment = segments[original_idx]
                lines_info = multiline_line_info.get(original_idx, [])
                translated_lines = []

                for line_info in lines_info:
                    if line_info.is_empty:
                        translated_lines.append(line_info.original)
                        continue
                    if not line_info.content.strip():
                        translated_lines.append(
                            f"{line_info.indent}{line_info.prefix}{line_info.content}"
                        )
                        continue

                    translated_content = translated_line_map.get(
                        (original_idx, line_info.line_index), line_info.content
                    )
                    translated_content = self._retry_untranslated_text_by_sentence(
                        backend,
                        line_info.content,
                        translated_content,
                        source_lang,
                        target_lang,
                        stats,
                    )
                    translated_content = self._retry_english_residue_by_sentence(
                        backend,
                        line_info.content,
                        translated_content,
                        source_lang,
                        target_lang,
                        stats,
                    )
                    translated_lines.append(
                        f"{line_info.indent}{line_info.prefix}{translated_content}"
                    )

                translated_text = "\n".join(translated_lines)
                if self._has_fenced_code_or_placeholder(
                    segment.source_text, getattr(segment, "placeholder_map", None)
                ) and self._is_effectively_untranslated(segment.source_text, translated_text):
                    logger.info(
                        "MSP-02: Retrying fenced-code multiline segment as prose/code chunks"
                    )
                    translated_text = self._translate_fenced_code_prose_chunks(
                        backend,
                        segment.source_text,
                        source_lang,
                        target_lang,
                        stats,
                        getattr(segment, "placeholder_map", None),
                    )
                structure_preserved = len(translated_lines) == len(lines_info)

                if not structure_preserved:
                    logger.warning(
                        f"MSP-02: Structure drift in segment {segment.id}: "
                        f"{len(lines_info)} -> {len(translated_lines)} lines"
                    )

                translated_texts[original_idx] = translated_text

                logger.debug(
                    f"MSP-02: Multiline segment {segment.id} translated with "
                    f"{len(lines_info)} lines preserved"
                )

        return translated_texts
