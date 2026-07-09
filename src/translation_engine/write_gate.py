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

if TYPE_CHECKING:
    from ..utils.config_loader import ConfigService
    from .language_detection.fasttext_detector import FastTextDetector
    from .language_detection.similarity_tracker import SimilarityTracker

logger = logging.getLogger(__name__)


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
    """

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

    def evaluate(
        self,
        translated_content: str,
        source_content: str,
        target_lang: str,
        output_path: Path,
        source_doc: Any = None,
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
            working = translated_content
            working = self._gate_heading_integrity(
                source_content, working, output_path, source_doc, result
            )
            working = self._gate_frontmatter_backticks(working, output_path, source_doc, result)
            working = self._gate_frontmatter_id_corruption(working, output_path, source_doc, result)
            working = self._gate_double_periods(source_content, working, output_path, result)
            working = self._gate_duplicate_content(working, output_path, result)
            if working != translated_content:
                result.cleaned_content = working
            if result.passed:
                self._gate_eu_hallucination(source_content, working, output_path, result)
            if result.passed:
                self._gate_mixed_language(working, target_lang, output_path, result)
            if result.passed:
                self._gate_table_row_integrity(source_content, working, output_path, result)
            if result.passed:
                self._gate_newline_explosion(source_content, working, output_path, result)
            return result

        # Gate 2: Language detection mismatch (B-7.1)
        self._gate_language_mismatch(translated_content, target_lang, output_path, detector, result)
        if not result.passed:
            return result

        # Gate 3: Overwrite protection (B-7.4, 4 CASEs)
        self._gate_overwrite_protection(
            translated_content, target_lang, output_path, detector, result
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
        # Gates 9-17: Content quality gates — run UNCONDITIONALLY regardless
        # of force_accept. These protect against corruption that gates 1-8
        # do not cover (content quality, not just structure).
        # ------------------------------------------------------------------
        # Auto-clean gates (9, 10, 11, 12, 16): set cleaned_content if changed.
        working = translated_content
        working = self._gate_heading_integrity(
            source_content, working, output_path, source_doc, result
        )
        working = self._gate_frontmatter_backticks(working, output_path, source_doc, result)
        working = self._gate_frontmatter_id_corruption(working, output_path, source_doc, result)
        working = self._gate_double_periods(source_content, working, output_path, result)
        working = self._gate_duplicate_content(working, output_path, result)
        if working != translated_content:
            result.cleaned_content = working

        # Blocking gates (13, 14, 15, 17): short-circuit on first failure.
        if result.passed:
            self._gate_eu_hallucination(source_content, working, output_path, result)
        if result.passed:
            self._gate_mixed_language(working, target_lang, output_path, result)
        if result.passed:
            self._gate_table_row_integrity(source_content, working, output_path, result)
        if result.passed:
            self._gate_newline_explosion(source_content, working, output_path, result)

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
        if (
            existing_lang == target_lang
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
        for (s_level, s_text), (t_level, t_text) in zip(src_headings, tgt_headings):
            s_stripped = s_text.strip()
            t_stripped = t_text.strip()
            if s_stripped in self._API_HEADING_TERMS and t_stripped != s_stripped:
                if self._contains_corruption(t_stripped, s_stripped):
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
        """Auto-fix odd backtick counts in frontmatter title/description/summary/linkTitle."""
        parts = translated_content.split("---", 2)
        if len(parts) < 3:
            return translated_content
        fm_text = parts[1]
        cleaned_fm = fm_text

        for field in ("title", "description", "summary", "linkTitle"):
            m = re.search(r"^(" + re.escape(field) + r":\s*)(.+?)(\s*)$", cleaned_fm, re.MULTILINE)
            if not m:
                continue
            val = m.group(2).strip()
            if val.count("`") % 2 == 1:
                # Odd backticks — try to fix by adding a closing backtick
                fixed_val = val + "`"
                cleaned_fm = cleaned_fm[:m.start(2)] + fixed_val + cleaned_fm[m.end(2):]
                logger.info(
                    "GATE10 fixed odd backtick in %s.%s: %r → %r",
                    output_path.name, field, val, fixed_val,
                )

        if cleaned_fm == fm_text:
            return translated_content
        return parts[0] + "---" + cleaned_fm + "---" + parts[2]

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
            if len(stripped) < 20:
                continue
            if stripped.startswith("|"):
                continue  # table row
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
                    in_code = not in_code
                    continue
                if not in_code and stripped.startswith("|") and stripped.endswith("|"):
                    count += 1
            return count

        from src.translation_engine.parser.hugo_parser import normalize_table_cells

        src_rows = _count_table_rows(normalize_table_cells(src_body))
        tgt_rows = _count_table_rows(tgt_body)

        if src_rows < 4:
            return  # Too few rows to be meaningful

        if tgt_rows < src_rows * 0.5 or tgt_rows > src_rows * 2:
            result.passed = False
            result.error = (
                f"Gate 15 table integrity: source={src_rows} rows, "
                f"translation={tgt_rows} rows (ratio={tgt_rows/max(src_rows,1):.2f})"
            )
            logger.error("GATE15 BLOCKED %s: %s", output_path.name, result.error)

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
