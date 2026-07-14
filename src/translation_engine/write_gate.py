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

from .parser.hugo_parser import HugoParser
from .reconstructor.yaml_formatter import YAMLFormatter

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

# Gate 22: mojibake / encoding corruption patterns
_MOJIBAKE_GATE_RE = re.compile(r"\u00e2\u20ac|\u00c3\u00a9|\u00c3\u00a8|\u00c3\u00bc|\u00c3\u00b6")

# Gate 20: shortcode leak patterns
_SHORTCODE_GATE_RE = re.compile(r"\{\{[<%]")

# Gate 17 (inline code integrity) helper
_BACKTICK_SPAN_RE = re.compile(r"`([^`]+)`")
# m2m100 inserts a stray `` ` `` before table rows (e.g. "` | Чтение | …").
# Matches only at line-start followed by optional space + pipe — unambiguous artifact.
_STRAY_TABLE_BACKTICK_RE = re.compile(r"(?m)^\s*`(\s*\|)")

# Gate 24: description reverted to English (non-Latin locales only)
_NON_LATIN_SCRIPT_LOCALES = frozenset({
    "ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh",
})

# Gate 25: code block content truncated
_CODE_BLOCK_CONTENT_RE = re.compile(
    r"```[^\n]*\n(.*?)```", re.DOTALL
)


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
        (2,  "_gate_language_mismatch",           "structural",  "early_return"),
        (3,  "_gate_overwrite_protection",        "safety",      "early_return"),
        (4,  "_gate_file_purity",                 "content",     "early_return"),
        (5,  "_gate_soft_contamination",          "content",     "no_op"),
        (6,  "_gate_code_block",                  "structural",  "early_return"),
        (7,  "_gate_heading_surplus",             "structural",  "early_return"),
        (8,  "_gate_yaml_frontmatter",            "structural",  "early_return"),
        (9,  "_gate_heading_integrity",           "content",     "auto_clean"),
        (10, "_gate_frontmatter_backticks",       "content",     "auto_clean"),
        (11, "_gate_frontmatter_id_corruption",   "content",     "auto_clean"),
        (12, "_gate_double_periods",              "cosmetic",    "auto_clean"),
        (13, "_gate_eu_hallucination",            "content",     "block"),
        (14, "_gate_mixed_language",              "content",     "block"),
        (15, "_gate_table_row_integrity",         "structural",  "block"),
        (16, "_gate_duplicate_content",           "content",     "auto_clean"),
        (17, "_gate_newline_explosion",           "structural",  "block"),
        (18, "_gate_description_hallucination",   "content",     "block"),
        (19, "_gate_code_fence_count",            "structural",  "block"),
        (20, "_gate_empty_body",                  "content",     "block"),
        (21, "_gate_shortcode_body_leak",         "structural",  "block"),
        (22, "_gate_inline_code_integrity",       "content",     "auto_clean"),
        (23, "_gate_encoding_clean",              "structural",  "block"),
        (24, "_gate_description_reverted_to_english", "content", "block"),
        (25, "_gate_code_block_content_truncated", "structural", "block"),
    ]

    def __init__(
        self,
        detector: FastTextDetector | None,
        similarity_tracker: SimilarityTracker | None,
        config: ConfigService | None,
        force_accept: bool = False,
    ) -> None:
        self._detector = detector
        self._similarity_tracker = similarity_tracker
        self._config = config
        self._force_accept = force_accept
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
    ) -> WriteGateResult:
        """Run gates 2-8 on translated content.

        Args:
            translated_content: The full translated markdown.
            source_content: The original source markdown.
            target_lang: Expected target language code.
            output_path: Where the file would be written.
            source_doc: Parsed HugoDocument (for frontmatter key check).

        Returns:
            WriteGateResult indicating pass/fail and any side-effect requests.
        """
        result = WriteGateResult(passed=True)
        detector = self._detector

        if detector is None:
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
                source_content, translated_content, target_lang, output_path, source_doc, result
            )
            if working != translated_content:
                result.cleaned_content = working
            return result

        # Gate 2: Language detection mismatch (B-7.1)
        self._gate_language_mismatch(translated_content, target_lang, output_path, detector, result)
        if not result.passed:
            return result

        # Gate 3: Overwrite protection (B-7.4, 4 CASEs)
        self._gate_overwrite_protection(
            translated_content, target_lang, output_path, detector, result,
            force_overwrite=force_overwrite,
        )
        if not result.passed:
            return result

        # Gate 4: Final file purity (B-7.5)
        detected_lang, confidence = detector.detect(translated_content)
        self._gate_file_purity(translated_content, target_lang, output_path, detector, result)
        if not result.passed:
            return result

        # Gate 5: Soft contamination queue (TC-MLD-01) — does NOT block
        self._gate_soft_contamination(target_lang, output_path, result)

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
            source_content, translated_content, target_lang, output_path, source_doc, result
        )
        if working != translated_content:
            result.cleaned_content = working

        return result

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
        except (ValueError, Exception) as e:
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
    ) -> None:
        if self._force_accept:
            return
        if not output_path.exists():
            return

        try:
            detected_lang, confidence = detector.detect(translated_content)
        except (ValueError, Exception):
            return

        try:
            existing_content = output_path.read_text(encoding="utf-8")
            existing_lang, existing_conf = detector.detect(existing_content)
        except OSError as e:
            logger.warning(f"Could not read existing file for comparison (allowing write): {e}")
            return
        except ValueError as e:
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
        if existing_lang != target_lang and detected_lang != target_lang:
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
        _src_hd = len(re.findall(r"^#{1,6}\s", _src_body, re.MULTILINE))
        _tgt_hd = len(re.findall(r"^#{1,6}\s", _tgt_body, re.MULTILINE))
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

    # API heading terms that must never be translated
    _API_HEADING_TERMS: frozenset[str] = frozenset({
        "Name", "Type", "Description", "Returns", "Parameters",
        "Properties", "Methods", "Fields", "Constructors", "Events",
        "Exceptions", "Remarks", "Examples", "See Also", "Inheritance",
        "Implements", "Namespace", "Assembly", "Syntax", "Value",
    })

    # Latin-script target languages: gate 14 (mixed lang) skips these
    _LATIN_SCRIPT_LANGS: frozenset[str] = frozenset({
        "af", "az", "bs", "ca", "cs", "cy", "da", "de", "en", "es", "et",
        "eu", "fi", "fr", "ga", "hr", "hu", "id", "it", "lt", "lv", "ms",
        "mt", "nl", "no", "nb", "pl", "pt", "ro", "sk", "sl", "sq", "sr",
        "sv", "sw", "tr", "vi",
    })

    # PascalCase / dotted identifier — must not be translated in frontmatter
    _IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[A-Z][a-zA-Z0-9_.]+$")

    # EU/GDPR hallucination patterns
    _EU_HALLUCINATION_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"(?:cookie|GDPR|General Data Protection|privacy policy|data protection)", re.IGNORECASE),
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

    def _run_content_gates(
        self,
        source_content: str,
        translated_content: str,
        target_lang: str,
        output_path: Path,
        source_doc: object,
        result: WriteGateResult,
    ) -> str:
        """Run all content quality gates (GATE_REGISTRY entries with action
        'auto_clean' or 'block').  Returns the (possibly cleaned) content.

        Each gate has a different signature.  We normalize all of them to the
        common interface ``(src, working, path, result) -> str | None`` via
        explicit lambdas so the loop body stays uniform.  Auto-clean gates
        return the (possibly modified) content string; blocking gates return None.
        """
        # Normalize all gate signatures to (src, working, path, result) -> str | None
        # This table is the single place where signature differences are encoded.
        _dispatch: dict[str, object] = {
            "_gate_heading_integrity":
                lambda src, w, path, res: self._gate_heading_integrity(src, w, path, source_doc, res),
            "_gate_frontmatter_backticks":
                lambda src, w, path, res: self._gate_frontmatter_backticks(w, path, source_doc, res),
            "_gate_frontmatter_id_corruption":
                lambda src, w, path, res: self._gate_frontmatter_id_corruption(w, path, source_doc, res),
            "_gate_double_periods":
                lambda src, w, path, res: self._gate_double_periods(src, w, path, res),
            "_gate_eu_hallucination":
                lambda src, w, path, res: self._gate_eu_hallucination(src, w, path, res),
            "_gate_mixed_language":
                lambda src, w, path, res: self._gate_mixed_language(w, target_lang, path, res),
            "_gate_table_row_integrity":
                lambda src, w, path, res: self._gate_table_row_integrity(src, w, path, res),
            "_gate_duplicate_content":
                lambda src, w, path, res: self._gate_duplicate_content(w, path, res),
            "_gate_newline_explosion":
                lambda src, w, path, res: self._gate_newline_explosion(src, w, path, res),
            "_gate_description_hallucination":
                lambda src, w, path, res: self._gate_description_hallucination(src, w, path, res),
            "_gate_code_fence_count":
                lambda src, w, path, res: self._gate_code_fence_count(src, w, path, res),
            "_gate_empty_body":
                lambda src, w, path, res: self._gate_empty_body(src, w, path, res),
            "_gate_shortcode_body_leak":
                lambda src, w, path, res: self._gate_shortcode_body_leak(src, w, path, res),
            "_gate_inline_code_integrity":
                lambda src, w, path, res: self._gate_inline_code_integrity(src, w, path, res),
            "_gate_encoding_clean":
                lambda src, w, path, res: self._gate_encoding_clean(src, w, path, res),
            "_gate_description_reverted_to_english":
                lambda src, w, path, res: self._gate_description_reverted_to_english(src, w, target_lang, path, res),
            "_gate_code_block_content_truncated":
                lambda src, w, path, res: self._gate_code_block_content_truncated(src, w, path, res),
        }

        working = translated_content

        for _, method_name, _, action in self.GATE_REGISTRY:
            if action not in ("auto_clean", "block"):
                continue  # skip early_return / no_op entries (handled elsewhere)

            fn = _dispatch.get(method_name)
            if fn is None:
                # Method exists (verified by _verify_gate_registry) but has no
                # dispatch entry — call it with the standard signature and log.
                logger.warning(
                    "WriteGate: no dispatch entry for %s — calling with standard args",
                    method_name,
                )
                fn = lambda src, w, path, res, _m=method_name: getattr(self, _m)(src, w, path, res)  # noqa: E731

            if action == "auto_clean":
                new_working = fn(source_content, working, output_path, result)
                if new_working is not None:
                    working = new_working
            else:  # "block"
                if not result.passed:
                    continue  # short-circuit: stop on first blocking failure
                fn(source_content, working, output_path, result)

        return working

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
    ) -> str:
        """Auto-clean corrupted headings that are in _API_HEADING_TERMS."""
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        src_headings = re.findall(r"^(#{1,6})\s+(.+)$", src_body, re.MULTILINE)
        tgt_headings = re.findall(r"^(#{1,6})\s+(.+)$", tgt_body, re.MULTILINE)

        if len(src_headings) != len(tgt_headings):
            # Count mismatch already handled by gate 7; skip positional check
            return translated_content

        working = translated_content
        cleaned_count = 0
        untranslated_count = 0
        for (s_level, s_text), (t_level, t_text) in zip(src_headings, tgt_headings):
            s_stripped = s_text.strip()
            t_stripped = t_text.strip()
            if s_stripped in self._API_HEADING_TERMS:
                if t_stripped == s_stripped:
                    # Model returned heading unchanged (failed to translate).
                    # Content is already English — no modification needed, but log for monitoring.
                    # TC-HDG-TRANS-019: these terms are now sent to model; model failure is expected
                    # occasionally. Gate 9 accepts English fallback (same as pre-fix behavior).
                    untranslated_count += 1
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
        if untranslated_count:
            logger.debug(
                "GATE9 %d API heading(s) untranslated (model returned source) in %s — "
                "English retained",
                untranslated_count,
                output_path.name,
            )
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
                    output_path.name, field_name, val, fixed_val,
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
    ) -> str:
        """Restore English API identifier in title/linkTitle if translation corrupted it."""
        if source_doc is None or not hasattr(source_doc, "frontmatter"):
            return translated_content

        fm = getattr(source_doc, "frontmatter", {}) or {}
        parts = translated_content.split("---", 2)
        if len(parts) < 3:
            return translated_content

        fm_text = parts[1]
        cleaned_fm = fm_text

        for field in ("title", "linkTitle"):
            en_val = fm.get(field, "")
            if not en_val or not isinstance(en_val, str):
                continue
            en_str = str(en_val).strip()
            if not self._IDENTIFIER_RE.match(en_str):
                continue  # Not a pure API identifier — don't force-restore

            # Find translated value
            m = re.search(
                r"^(" + re.escape(field) + r":\s*[\"']?)(.+?)([\"']?\s*)$",
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
            new_line = f"{field}: {en_str}"
            cleaned_fm = cleaned_fm.replace(old_line, new_line, 1)
            logger.info(
                "GATE11 restored %s in %s: %r → %r",
                field, output_path.name, tr_val, en_str,
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
                f"translation={tgt_rows} rows (ratio={tgt_rows/max(src_rows,1):.2f})"
            )
            logger.error("GATE15 BLOCKED %s: %s", output_path.name, result.error)
            if src_rows >= 4:
                # Dump full translated content to temp file for diagnosis
                import tempfile, os as _os
                _dump_path = _os.path.join(
                    tempfile.gettempdir(),
                    f"gate15_dump_{output_path.name}"
                )
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
        """Remove paragraphs that appear 3+ times (model repetition artifact)."""
        body = self._get_body(translated_content)
        paragraphs = re.split(r"\n{2,}", body)

        # Normalize and count
        seen: dict[str, int] = {}
        for para in paragraphs:
            key = re.sub(r"\s+", " ", para.strip())
            if len(key) > 30:  # Only meaningful paragraphs
                seen[key] = seen.get(key, 0) + 1

        duplicates = {k for k, v in seen.items() if v >= 3}
        if not duplicates:
            return translated_content

        # Keep only first occurrence of each duplicate
        kept: set[str] = set()
        cleaned_paragraphs = []
        for para in paragraphs:
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
        result.error = "Gate 20 shortcode body leak: {{< or {{% in translated body but not in EN source"
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
        """
        src_body = self._get_body(source_content)
        tgt_body = self._get_body(translated_content)

        en_spans = _BACKTICK_SPAN_RE.findall(src_body)
        if len(en_spans) < 3:
            return  # too few spans to fire (avoids noise on trivial files)

        # Strip stray leading backticks from table rows (m2m100 artifact: "` | Чтение |").
        # These cause _BACKTICK_SPAN_RE to manufacture a cross-row "span" containing
        # Cyrillic table content, triggering a false positive against ASCII en_spans.
        tgt_body_clean = _STRAY_TABLE_BACKTICK_RE.sub(r"\1", tgt_body)
        if tgt_body_clean != tgt_body:
            result.cleaned_content = translated_content.replace(tgt_body, tgt_body_clean, 1)
            tgt_body = tgt_body_clean

        tr_spans = _BACKTICK_SPAN_RE.findall(tgt_body)
        for en_span, tr_span in zip(en_spans, tr_spans):
            if en_span.isascii() and not tr_span.isascii():
                result.passed = False
                result.error = (
                    f"Gate 21 inline code translated: `{en_span[:40]}` → `{tr_span[:40]}`"
                )
                logger.error("GATE21 BLOCKED %s: %s", output_path.name, result.error)
                return

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
                word for word in re.findall(r"[A-Za-z]{4,}", remaining)
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
            prose_words = [
                word for word in remaining.split() if word.isalpha() and len(word) > 3
            ]
            if len(prose_words) < 3:
                return True
        return False
