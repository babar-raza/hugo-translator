"""
unit_heal.py — Unified unit-level file healer.

Processes a JSONL queue of files with quality issues and performs surgical
per-unit replacement rather than full-file retranslation. Only bad units
are retranslated; correct units are left untouched.

Usage:
    python scripts/quality/unit_heal.py \\
        --sites reference.aspose.org \\
        --locales zh ja ko ar uk \\
        --issue-types mojibake_detector language_purity_detector \\
        --input-queue data/audit/master_heal_queue.jsonl \\
        --max-files 500 \\
        --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root on sys.path
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# HT-QUALITY-GATES-001 Phase 8 (F3): canonical gate-id <-> issue-name lookup,
# shared with scripts/quality/audit_all_content.py's sweep (see
# src/translation_engine/write_gate.py's GATE_ISSUE_NAMES docstring).
from src.translation_engine.write_gate import gate_id_from_issue_name  # noqa: E402

# ---------------------------------------------------------------------------
# Unit-level translation validator
# ---------------------------------------------------------------------------

import re as _re

_MOJIBAKE_RE = _re.compile(
    r"â€[\"'''""—–]|Ã[©è¼½¾\xbf\xa0]|â€\x9c|â€\x9d|â€™|â€œ"
)
_SHORTCODE_RE = _re.compile(r"\{\{[<%].*?[>%]\}\}", _re.DOTALL)
_INLINE_CODE_RE = _re.compile(r"`([^`]+)`")


def _validate_unit_translation(en_text: str, new_text: str) -> tuple[bool, str]:
    """
    Lightweight per-unit quality check before accepting a new translation.
    Returns (accepted, reason). Rejects if new translation is worse than keeping original.
    """
    if not new_text.strip():
        return False, "empty_output"
    if _MOJIBAKE_RE.search(new_text):
        return False, "mojibake_in_output"
    en_stripped = en_text.strip()
    if en_stripped and len(new_text.strip()) < 0.10 * len(en_stripped):
        return False, "too_short"
    # Shortcode leak in output but not in source
    if _SHORTCODE_RE.search(new_text) and not _SHORTCODE_RE.search(en_text):
        return False, "shortcode_leak"
    return True, "ok"


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------

def _load_engine(site_id: str, locale: str, model_override: str | None):
    """Build a minimal TranslationEngine for unit retranslation."""
    from src.translation_engine.engine import TranslationEngine
    from src.config.config_service import ConfigService
    config = ConfigService()
    engine = TranslationEngine(config=config)
    return engine


def _get_content_root(site_id: str) -> Path | None:
    """Resolve content root for a site, respecting env var overrides."""
    _ENV_MAP = {
        "reference.aspose.org": "ASPOSE_ORG_CONTENT",
        "docs.aspose.org": "ASPOSE_NET_CONTENT",
        "kb.aspose.org": "ASPOSE_NET_CONTENT",
    }
    env_key = _ENV_MAP.get(site_id)
    if env_key:
        val = os.environ.get(env_key)
        if val:
            return Path(val)
    return None


def process_queue(
    queue_path: Path,
    sites: list[str],
    locales: list[str] | None,
    issue_types: list[str] | None,
    max_files: int,
    model_override: str | None,
    dry_run: bool,
    done_path: Path,
) -> dict:
    """
    Main processing loop. Returns summary statistics dict.
    """
    from src.translation_engine.unit_quality_scorer import UnitQualityScorer
    from src.translation_engine.file_reconstructor import FileReconstructor
    from src.utils.atomic_write import atomic_write

    # Load done set (resume support)
    done_set: set[str] = set()
    if done_path.exists():
        with done_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        done_set.add(json.loads(line)["file_path"])
                    except Exception:
                        pass
    logger.info("Resuming: %d files already done", len(done_set))

    stats = {
        "processed": 0,
        "skipped_done": 0,
        "skipped_clean": 0,
        "units_fixed": 0,
        "units_skipped": 0,
        "gates_failed": 0,
        "write_errors": 0,
    }

    done_fh = done_path.open("a", encoding="utf-8") if not dry_run else None
    try:
        with queue_path.open(encoding="utf-8") as qfh:
            for line in qfh:
                if stats["processed"] >= max_files:
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Malformed queue entry, skipping: %s", line[:80])
                    continue

                file_path = entry.get("file_path", "")
                en_path = entry.get("en_path", "")
                locale = entry.get("locale", "")
                site_id = entry.get("site_id", "")
                # TC-HLN-006: entry["issues"][*]["type"] values come from
                # merge_audit_queues.py's PRIORITY vocabulary (e.g.
                # "encoding_corruption"), which is a DIFFERENT, incompatible
                # vocabulary from UnitQualityScorer's own _detector-suffixed
                # issue_type values (e.g. "mojibake_detector") produced
                # below at line ~202. --issue-types is documented (see
                # module docstring) and always used with the _detector
                # vocabulary, so a queue-entry-level pre-filter comparing
                # against the wrong vocabulary silently skipped every file
                # whenever --issue-types was passed at all. The queue is
                # authoritative only for "which files might have issues";
                # which units are actually bad and what type they are is
                # always freshly determined by scorer.score() below, and
                # THAT result is correctly filtered by issue_types at
                # (see `if issue_types:` after scoring). No file-level
                # pre-filtering on issue type is done here anymore -- only
                # site/locale, which use the same vocabulary on both sides.
                if sites and site_id not in sites:
                    continue
                if locales and locale not in locales:
                    continue

                # Resume check
                if file_path in done_set:
                    stats["skipped_done"] += 1
                    continue

                # Read files
                tr_file = Path(file_path)
                en_file = Path(en_path)
                if not tr_file.exists() or not en_file.exists():
                    logger.warning("Missing file(s): %s / %s", file_path, en_path)
                    continue

                try:
                    tr_content = tr_file.read_text(encoding="utf-8")
                    en_content = en_file.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.error("Read error %s: %s", file_path, exc)
                    continue

                stats["processed"] += 1
                t0 = time.monotonic()

                # HT-QUALITY-GATES-001 Phase 8 (F3): entries whose issues
                # include a gate-registry-derived type (e.g.
                # "refusal_artifact_gate29", or the "gate{id}_..." fallback
                # for any newer gate) are invisible to UnitQualityScorer's
                # fixed 10-type vocabulary below -- scoring such a file
                # always finds nothing and would mark it "skipped_clean"
                # even when the gate issue is still genuinely present (root
                # cause RC2: the queue and the healer's scorer speak two
                # different, independently-drifted vocabularies). Re-run the
                # ORIGINATING gate directly instead: WriteGateEvaluator.
                # evaluate() already applies every auto_clean gate's own fix
                # and re-validates every block gate, so "healing" a
                # gate-derived finding is just re-running the real gate
                # machinery -- not a second, independently-invented fix.
                #
                # Scoping note: a file with BOTH a gate-type issue and a
                # UnitQualityScorer-vocabulary issue only gets the gate path
                # run this pass; its unit-level issue is picked up on a
                # later healer run once still-present in the next audit
                # sweep. This pipeline is already iterative/multi-pass by
                # design (queue -> heal -> re-sweep -> queue), so this is a
                # deferred fix, not a dropped one.
                gate_issue_types = {
                    iss["type"] for iss in entry.get("issues", [])
                    if gate_id_from_issue_name(iss["type"]) is not None
                }
                if gate_issue_types:
                    outcome = _heal_via_gate_rerun(
                        en_content=en_content,
                        tr_content=tr_content,
                        tr_file=tr_file,
                        locale=locale,
                        gate_issue_types=gate_issue_types,
                        dry_run=dry_run,
                        stats=stats,
                    )
                    # "needs_retranslation" is deliberately NOT marked done:
                    # the file still has a real, current defect this
                    # CPU-only healer can't fix mechanically (no auto_clean
                    # path exists for it) -- leaving it off done_set means a
                    # future run (e.g. once a model-based repair path exists
                    # for this issue type) can still pick it up. "fixed" and
                    # "clean" both mean there's genuinely nothing further to
                    # do for this queue entry.
                    if outcome in ("fixed", "clean") and not dry_run:
                        done_set.add(file_path)
                        if done_fh:
                            done_fh.write(json.dumps({"file_path": file_path}) + "\n")
                            done_fh.flush()
                    continue

                # Score the file
                scorer = UnitQualityScorer(config={}, locale=locale)
                try:
                    from src.translation_engine.parser import HugoParser
                    from src.translation_engine.extractor import TextUnitExtractor

                    parser = HugoParser()
                    tr_doc = parser.parse_string(tr_content)
                    en_doc = parser.parse_string(en_content)
                    ext = TextUnitExtractor(segmentation_strategy="sentence_only")
                    tr_units = ext.extract_from_ast(tr_doc.ast, tr_doc.frontmatter).units
                    en_units = ext.extract_from_ast(en_doc.ast, en_doc.frontmatter).units
                except Exception as exc:
                    logger.error("Parse error %s: %s", file_path, exc)
                    continue

                issues = scorer.score(en_units, tr_units)
                if issue_types:
                    issues = [i for i in issues if i.issue_type in issue_types]

                if not issues:
                    stats["skipped_clean"] += 1
                    continue

                bad_indices = list({i.unit_idx for i in issues})
                logger.info(
                    "[%s] %d bad unit(s) to fix (issues: %s)",
                    tr_file.name,
                    len(bad_indices),
                    ", ".join(sorted({i.issue_type for i in issues})),
                )

                if dry_run:
                    for issue in issues:
                        print(
                            f"  DRY-RUN unit[{issue.unit_idx}] "
                            f"{issue.issue_type} "
                            f"(conf={issue.confidence:.2f}): "
                            f"{(tr_units[issue.unit_idx].source_text or '')[:60]!r}"
                        )
                    continue

                # For each bad unit: re-translate (TM lookup first, then model)
                unit_replacements: dict[int, str] = {}
                for issue in issues:
                    uidx = issue.unit_idx
                    en_unit = issue.en_unit
                    en_text = en_unit.source_text if en_unit else ""
                    original_tr = tr_units[uidx].source_text or ""

                    new_text = _retranslate_unit(
                        en_text=en_text,
                        original_tr=original_tr,
                        locale=locale,
                        site_id=site_id,
                        issue_type=issue.issue_type,
                    )
                    if new_text is None:
                        stats["units_skipped"] += 1
                        logger.debug("  unit[%d]: no replacement found, keeping original", uidx)
                        continue

                    ok, reason = _validate_unit_translation(en_text, new_text)
                    if not ok:
                        stats["units_skipped"] += 1
                        logger.warning(
                            "  unit[%d]: new translation rejected (%s), keeping original", uidx, reason
                        )
                        continue

                    unit_replacements[uidx] = new_text
                    stats["units_fixed"] += 1

                if not unit_replacements:
                    logger.info("[%s] No units could be fixed, skipping write", tr_file.name)
                    continue

                # Reconstruct file with surgical replacements
                try:
                    reconstructor = FileReconstructor(site_profile=None)
                    new_content = reconstructor.reconstruct(
                        original_tr_content=tr_content,
                        en_content=en_content,
                        unit_replacements=unit_replacements,
                        site_id=site_id,
                        locale=locale,
                    )
                except Exception as exc:
                    logger.error("Reconstruction error %s: %s", file_path, exc)
                    stats["write_errors"] += 1
                    continue

                # Run write gates
                gate_result = _run_write_gates(
                    source_content=en_content,
                    translated_content=new_content,
                    output_path=tr_file,
                    locale=locale,
                    site_id=site_id,
                )
                if not gate_result:
                    logger.warning("[%s] Write gate failed, skipping", tr_file.name)
                    stats["gates_failed"] += 1
                    continue

                # Write
                try:
                    atomic_write(tr_file, new_content)
                except Exception as exc:
                    logger.error("Write error %s: %s", file_path, exc)
                    stats["write_errors"] += 1
                    continue

                # Mark done
                done_set.add(file_path)
                if done_fh:
                    done_fh.write(json.dumps({"file_path": file_path}) + "\n")
                    done_fh.flush()

                elapsed = time.monotonic() - t0
                logger.info(
                    "[%s] Done in %.1fs: %d units fixed",
                    tr_file.name,
                    elapsed,
                    len(unit_replacements),
                )

    finally:
        if done_fh:
            done_fh.close()

    return stats


def _retranslate_unit(
    en_text: str,
    original_tr: str,
    locale: str,
    site_id: str,
    issue_type: str,
) -> str | None:
    """
    Produce a new translation for a bad unit.

    For structural (CPU-fixable) issues, applies surgical fix without calling a model.
    For content issues, returns None (caller keeps original) — full model retranslation
    is handled by the heal_english_headings.py / unit_heal GPU path, not this script.

    Returns new translation string, or None to keep original.
    """
    # Mojibake: strip cp1252 artifacts (structural fix)
    if issue_type == "mojibake_detector":
        fixed = _repair_mojibake(original_tr)
        if fixed != original_tr:
            return fixed
        return None

    # Duplicate run: deduplicate paragraphs (structural fix)
    if issue_type == "duplicate_run_detector":
        fixed = _dedup_paragraphs(original_tr)
        if fixed != original_tr:
            return fixed
        return None

    # Link path corruption: restore EN path (structural fix)
    if issue_type == "link_path_detector":
        fixed = _restore_link_paths(en_text, original_tr)
        if fixed != original_tr:
            return fixed
        return None

    # Other issue types (language_purity_detector, hallucination, etc.) require
    # model retranslation — not handled here (use heal_english_headings.py or GPU queues)
    return None


_MOJIBAKE_MAP = {
    "â€“": "—",  # â€" → em-dash
    "â€•": "•",  # â€¢ → bullet
    "â€”": "–",  # â€" → en-dash
    "â€™": "’",  # â€™ → right single quote
    "â€œ": "“",  # â€œ → left double quote
    "â€\x9d": "”",   # â€ → right double quote
    "Ã©": "é",        # Ã© → é
    "Ã¨": "è",        # Ã¨ → è
    "Ã¼": "ü",        # Ã¼ → ü
    "Ã¶": "ö",        # Ã¶ → ö
    "Ã¤": "ä",        # Ã¤ → ä
}


def _repair_mojibake(text: str) -> str:
    for bad, good in _MOJIBAKE_MAP.items():
        text = text.replace(bad, good)
    return text


def _dedup_paragraphs(text: str) -> str:
    paragraphs = text.split("\n\n")
    result = []
    for p in paragraphs:
        if result and result[-1] == p:
            continue
        result.append(p)
    return "\n\n".join(result)


_LINK_URL_RE = _re.compile(r"(\[(?:[^\[\]]*)\])\(([^)]+)\)")


def _restore_link_paths(en_text: str, tr_text: str) -> str:
    en_urls = _LINK_URL_RE.findall(en_text)   # [(text, url), ...]
    tr_parts = list(_LINK_URL_RE.finditer(tr_text))
    if not en_urls or not tr_parts:
        return tr_text

    result = tr_text
    offset = 0
    for i, m in enumerate(tr_parts):
        if i >= len(en_urls):
            break
        en_url = en_urls[i][1]
        tr_url = m.group(2)
        if (en_url.startswith("..") or en_url.startswith("/")) and tr_url != en_url:
            old = m.group(0)
            new = m.group(1) + f"({en_url})"
            result = result[:m.start() + offset] + new + result[m.end() + offset:]
            offset += len(new) - len(old)
    return result


def _heal_via_gate_rerun(
    en_content: str,
    tr_content: str,
    tr_file: Path,
    locale: str,
    gate_issue_types: set[str],
    dry_run: bool,
    stats: dict,
) -> str:
    """HT-QUALITY-GATES-001 Phase 8 (F3): heal a queue entry whose issues
    are gate-registry-derived (not UnitQualityScorer-vocabulary) by
    re-running the real WriteGateEvaluator against the file's current
    content. Returns "fixed", "clean", or "needs_retranslation".

    Uses ``run_all_content_gates()``, NOT ``evaluate()`` -- this matters,
    not just a style choice. ``evaluate()`` (via ``_run_content_gates()``)
    routes every "warn"-action gate through a disposable, discarded result
    (correct for the PRODUCTION write path: a bug in a brand-new gate must
    never start blocking real writes). Checking ``evaluate()``'s returned
    ``result.passed`` here would therefore ALWAYS read ``True`` for a
    warn-tier gate regardless of whether it still fails -- silently
    reproducing root cause RC2 ("gate finding never reaches an actual
    fix") through a different mechanism. Confirmed via direct reproduction
    during this session's independent verification pass; this is the fix.
    ``run_all_content_gates()`` gives every gate a real, non-discarded
    per-gate result, so the SPECIFIC gate ids this queue entry actually
    named can be checked directly.

    force_accept=True mirrors safe_io.py's existing evaluator construction
    for offline/healing contexts (detector=None already skips gates 2-5,
    which need a real language detector and aren't meaningful for a
    same-locale re-check here).
    """
    from src.translation_engine.write_gate import WriteGateEvaluator, gate_id_from_issue_name

    relevant_gate_ids = {
        gid for gid in (gate_id_from_issue_name(name) for name in gate_issue_types)
        if gid is not None
    }
    if not relevant_gate_ids:
        # Caller (process_queue) only reaches this function when
        # gate_id_from_issue_name matched at least one issue type, so this
        # is a defensive fallback, not an expected path.
        stats["skipped_clean"] = stats.get("skipped_clean", 0) + 1
        return "clean"

    evaluator = WriteGateEvaluator(
        detector=None, similarity_tracker=None, config=None, force_accept=True,
    )
    gate_results, final_content = evaluator.run_all_content_gates(
        source_content=en_content,
        translated_content=tr_content,
        target_lang=locale,
        output_path=tr_file,
    )

    still_failing = {
        gid: gate_results[gid]
        for gid in relevant_gate_ids
        if gid in gate_results and not gate_results[gid].passed
    }

    if final_content != tr_content:
        # An auto_clean gate changed something -- write it. Applies
        # regardless of which specific gate id triggered the clean: an
        # auto_clean fix elsewhere in the file may incidentally resolve
        # the queued issue as a side effect of cleaning the content.
        if dry_run:
            print(
                f"  DRY-RUN [gate-fix] {tr_file.name}: auto_clean would change "
                f"content ({', '.join(sorted(gate_issue_types))})"
            )
            return "fixed"
        try:
            from src.utils.atomic_write import atomic_write
            atomic_write(tr_file, final_content)
            stats["units_fixed"] = stats.get("units_fixed", 0) + 1
            logger.info(
                "[%s] Gate auto-clean fixed: %s", tr_file.name, ", ".join(sorted(gate_issue_types))
            )
            return "fixed"
        except Exception as exc:
            logger.error("Write error %s: %s", tr_file, exc)
            stats["write_errors"] = stats.get("write_errors", 0) + 1
            return "needs_retranslation"

    if not still_failing:
        # Every SPECIFIC gate this queue entry named now genuinely passes
        # (checked against a REAL, non-discarded per-gate result) -- the
        # queue entry was stale (already fixed by something else since the
        # sweep that produced it ran, or a false positive that self-resolved).
        stats["skipped_clean"] = stats.get("skipped_clean", 0) + 1
        return "clean"

    # Still genuinely failing (confirmed via a real, non-discarded result,
    # not evaluate()'s warn-tier-discarding result.passed), and no
    # auto_clean path could fix it mechanically -- this needs real
    # re-translation (a model call), which this CPU-only healer doesn't
    # perform for whole-file gate failures (they're file-level, not
    # unit-indexed the way UnitQualityScorer's issues are). Correctly
    # reported as "needs retranslation" rather than silently mis-reported
    # as clean, which is what happened before this fix (root cause RC2).
    stats["gate_needs_retranslation"] = stats.get("gate_needs_retranslation", 0) + 1
    error_summary = "; ".join(r.error or "" for r in still_failing.values())
    logger.info(
        "[%s] Gate still failing, needs retranslation (not auto-fixable): %s -- %s",
        tr_file.name, ", ".join(sorted(gate_issue_types)), error_summary,
    )
    if dry_run:
        print(
            f"  DRY-RUN [gate-needs-retranslation] {tr_file.name}: "
            f"{', '.join(sorted(gate_issue_types))} -- {error_summary}"
        )
    return "needs_retranslation"


def _run_write_gates(
    source_content: str,
    translated_content: str,
    output_path: Path,
    locale: str,
    site_id: str,
) -> bool:
    """Run the standard write gate battery. Returns True if file can be written."""
    try:
        # TC-HLN-006-c: real class is WriteGateEvaluator, not WriteGate --
        # this import has been raising ImportError since unit_heal.py was
        # written (commit d55b42c), meaning EVERY fix attempt in every prior
        # run silently failed here and was counted as a gate rejection, not
        # an internal error. detector=None runs structural + content gates
        # (9-27) without language-mismatch/purity checks, matching
        # WriteGateEvaluator.evaluate()'s own documented graceful-degrade
        # path for a missing detector.
        from src.translation_engine.write_gate import WriteGateEvaluator
        gate = WriteGateEvaluator(detector=None, similarity_tracker=None, config=None)
        result = gate.evaluate(
            source_content=source_content,
            translated_content=translated_content,
            output_path=output_path,
            target_lang=locale,
        )
        if not result.passed:
            logger.warning("Gate failed: %s", result.error)
            return False
        return True
    except Exception as exc:
        logger.error("Gate evaluation error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unit-level file healer")
    p.add_argument("--sites", nargs="+", default=[], help="Site IDs to process")
    p.add_argument("--locales", nargs="+", default=[], help="Locales to process")
    p.add_argument(
        "--issue-types",
        nargs="+",
        default=[],
        dest="issue_types",
        help="Issue type filters (e.g. mojibake_detector duplicate_run_detector)",
    )
    p.add_argument(
        "--input-queue",
        default="data/audit/master_heal_queue.jsonl",
        dest="input_queue",
        help="JSONL queue file",
    )
    p.add_argument("--max-files", type=int, default=10000, dest="max_files")
    p.add_argument("--model", default=None, help="Model override (unused for CPU-only issues)")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main() -> None:
    # TC-HLN-006-b: this script's whole purpose is printing/logging
    # non-Latin translated text (dry-run previews, healed-unit summaries);
    # a plain print() or logging call crashes with UnicodeEncodeError the
    # first time it hits a Windows console's default cp1252 stdout encoding
    # -- same bug class fixed in .local/scheduler.py earlier today. Fail
    # soft instead of crashing the whole run over a display-only concern.
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    queue_path = Path(args.input_queue)
    if not queue_path.exists():
        logger.error("Queue file not found: %s", queue_path)
        sys.exit(1)

    done_path = queue_path.parent / (queue_path.stem + "_unit_heal_done.jsonl")

    logger.info(
        "unit_heal: sites=%s locales=%s issue_types=%s max_files=%d dry_run=%s",
        args.sites or "ALL",
        args.locales or "ALL",
        args.issue_types or "ALL",
        args.max_files,
        args.dry_run,
    )

    result = process_queue(
        queue_path=queue_path,
        sites=args.sites,
        locales=args.locales or None,
        issue_types=args.issue_types or None,
        max_files=args.max_files,
        model_override=args.model,
        dry_run=args.dry_run,
        done_path=done_path,
    )

    print("\n--- Summary ---")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
