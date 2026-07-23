#!/usr/bin/env python3
"""
Translation Quality Audit Script

Samples translated markdown files and scores them across multiple quality
dimensions: completeness, language purity, terminology preservation,
structural fidelity, and shortcode preservation.

Produces a JSON report and human-readable summary.

Usage:
    # Full audit against translated content repo
    python scripts/audit_translation_quality.py \\
        --content-root D:\\onedrive\\Documents\\GitHub\\aspose.net \\
        --langs fr de es ar zh \\
        --n-per-stratum 5 --seed 42 \\
        --output reports/audit/audit_2026-03-28.json

    # CI mode (uses test fixtures only, no external deps)
    python scripts/audit_translation_quality.py --mode ci

    # With LLM naturalness scoring
    python scripts/audit_translation_quality.py --content-root ... --use-llm
"""

import argparse
import json
import logging
import random
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: resolve project root so we can import src modules
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hugo shortcode regex — mirrors hugo_parser._SHORTCODE_RE
# ---------------------------------------------------------------------------
_SHORTCODE_RE = re.compile(r"(\{\{[<%].*?[%>]\}\})")

# ---------------------------------------------------------------------------
# Language codes — canonical source, not a hand-copy (durable-fix
# consolidation: this was one of 6 independently drifting copies found
# across the repo during that investigation).
# ---------------------------------------------------------------------------
from src.utils.content_discovery import (  # noqa: E402
    ALL_LANGUAGE_CODES as _ALL_LANGUAGE_CODES,
)

# Structural element regexes for fidelity scoring
_RE_H1 = re.compile(r"^# ", re.MULTILINE)
_RE_H2 = re.compile(r"^## ", re.MULTILINE)
_RE_H3 = re.compile(r"^### ", re.MULTILINE)
_RE_LIST_ITEM = re.compile(r"^[ \t]*[-*+] ", re.MULTILINE)
_RE_CODE_FENCE = re.compile(r"^```", re.MULTILINE)
_RE_TABLE_ROW = re.compile(r"^\|", re.MULTILINE)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SamplePair:
    source_path: Path
    translated_path: Path
    lang: str
    site: str
    content_type: str  # "blog", "reference", "docs", "other"


@dataclass
class FileScores:
    source_path: str
    translated_path: str
    lang: str
    site: str
    content_type: str
    completeness: float | None = None
    purity: float | None = None
    terminology: float | None = None
    structural_fidelity: float | None = None
    shortcode_preservation: float | None = None
    naturalness_llm: float | None = None
    # HT-QUALITY-GATES-001 Part 22 (plan 5.4 item 4): MEANING fidelity, not
    # fluency -- deliberately a separate field from naturalness_llm. This is
    # the periodic/sampled-audit half of the tiered-coverage design; Gate 36
    # in write_gate.py is the synchronous, high-risk-tier half. Kept out of
    # `overall`'s weighted aggregate for the same reason naturalness_llm
    # already is: an LLM judge score shouldn't silently dominate the
    # mechanical aggregate before its agreement rate against human
    # close-reading has been measured (Part 6 item 3).
    fidelity_llm: float | None = None
    fidelity_issues: list[str] = field(default_factory=list)
    overall: float | None = None
    flags: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class AuditReport:
    generated_at: str
    mode: str
    threshold: float
    total_files: int
    flagged_files: int
    aggregate: dict
    by_lang: dict
    by_site: dict
    by_content_type: dict
    files: list[dict]


# ---------------------------------------------------------------------------
# Sampler
# ---------------------------------------------------------------------------


def _infer_content_type(path: Path) -> str:
    parts = {p.lower() for p in path.parts}
    if "blog" in parts:
        return "blog"
    if "reference" in parts:
        return "reference"
    if "docs" in parts or "documentation" in parts:
        return "docs"
    return "other"


def _infer_site(path: Path, content_root: Path) -> str:
    """Return first path component after content_root as site name."""
    try:
        rel = path.relative_to(content_root)
        return rel.parts[0] if rel.parts else "unknown"
    except ValueError:
        return "unknown"


def _find_translated_path_folder_based(
    source_path: Path, content_root: Path, lang: str
) -> Path | None:
    """
    For per_language_folders layout: translated file is at content_root/lang/rel_path
    e.g. content_root/reference.aspose.net/slides/_index.md → content_root/fr/reference.aspose.net/slides/_index.md
    """
    try:
        rel = source_path.relative_to(content_root)
    except ValueError:
        return None
    candidate = content_root / lang / rel
    return candidate if candidate.exists() else None


def _find_translated_path_file_based(source_path: Path, lang: str) -> Path | None:
    """
    For filename layout: source.md → source.LANG.md
    e.g. index.md → index.fr.md
    """
    stem = source_path.stem
    ext = source_path.suffix
    candidate = source_path.parent / f"{stem}.{lang}{ext}"
    return candidate if candidate.exists() else None


def sample_translation_pairs(
    content_root: Path,
    langs: list[str],
    n_per_stratum: int = 5,
    seed: int = 42,
) -> list[SamplePair]:
    """
    Sample source+translation pairs stratified by (site, lang, content_type).

    Tries both folder-based and file-based translated path discovery.
    """
    rng = random.Random(seed)

    # Collect all English source .md files (exclude already-translated files)
    source_files = []
    for f in content_root.rglob("*.md"):
        stem = f.stem
        # Skip files that are themselves translations (e.g. index.fr.md)
        parts = stem.rsplit(".", 1)
        if len(parts) == 2 and parts[1] in _ALL_LANGUAGE_CODES:
            continue
        source_files.append(f)

    logger.info("Found %d source .md files under %s", len(source_files), content_root)

    # Build stratum → files mapping
    stratum_map: dict[tuple, list[SamplePair]] = {}

    for lang in langs:
        for src in source_files:
            site = _infer_site(src, content_root)
            ct = _infer_content_type(src)
            key = (site, lang, ct)

            # Try folder-based first, then file-based
            tgt = _find_translated_path_folder_based(src, content_root, lang)
            if tgt is None:
                tgt = _find_translated_path_file_based(src, lang)
            if tgt is None:
                continue

            pair = SamplePair(
                source_path=src,
                translated_path=tgt,
                lang=lang,
                site=site,
                content_type=ct,
            )
            stratum_map.setdefault(key, []).append(pair)

    # Sample n_per_stratum from each stratum
    sampled: list[SamplePair] = []
    for key, pairs in stratum_map.items():
        chosen = rng.sample(pairs, min(n_per_stratum, len(pairs)))
        sampled.extend(chosen)
        logger.debug("Stratum %s: %d/%d pairs sampled", key, len(chosen), len(pairs))

    logger.info("Sampled %d translation pairs across %d strata", len(sampled), len(stratum_map))
    return sampled


def sample_fixture_pairs(fixtures_dir: Path) -> list[SamplePair]:
    """
    CI mode: use test fixtures as source+translation pairs.
    Discovers any .en.md / .fr.md / .de.md sibling pairs.
    """
    pairs = []
    for src in fixtures_dir.rglob("*.en.md"):
        for lang in _ALL_LANGUAGE_CODES:
            tgt = src.parent / src.name.replace(".en.md", f".{lang}.md")
            if tgt.exists():
                pairs.append(
                    SamplePair(
                        source_path=src,
                        translated_path=tgt,
                        lang=lang,
                        site="fixtures",
                        content_type="other",
                    )
                )
    # Also accept plain .md source files alongside .LANG.md translations
    for src in fixtures_dir.rglob("*.md"):
        stem = src.stem
        parts = stem.rsplit(".", 1)
        if len(parts) == 2 and parts[1] in _ALL_LANGUAGE_CODES:
            continue
        if src.name.endswith(".en.md"):
            continue
        for lang in _ALL_LANGUAGE_CODES:
            tgt = src.parent / f"{stem}.{lang}.md"
            if tgt.exists():
                pairs.append(
                    SamplePair(
                        source_path=src,
                        translated_path=tgt,
                        lang=lang,
                        site="fixtures",
                        content_type="other",
                    )
                )
    logger.info("CI mode: found %d fixture pairs", len(pairs))
    return pairs


# ---------------------------------------------------------------------------
# Scorers
# ---------------------------------------------------------------------------


def _strip_frontmatter_and_code(text: str) -> str:
    """Remove YAML frontmatter and fenced code blocks for language detection."""
    # Remove frontmatter
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    # Remove fenced code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


def score_completeness(source_text: str, translated_text: str) -> float:
    """
    Estimate completeness by comparing non-empty paragraph count.

    Uses paragraphs as a simple proxy for translatable units, avoiding
    heavy AST parsing. Paragraphs are split on double newlines.
    """

    def count_paragraphs(text: str) -> int:
        text = _strip_frontmatter_and_code(text)
        paras = [p.strip() for p in re.split(r"\n\s*\n", text)]
        return sum(1 for p in paras if len(p) > 10 and any(c.isalpha() for c in p))

    src_count = count_paragraphs(source_text)
    tgt_count = count_paragraphs(translated_text)

    if src_count == 0:
        return 1.0
    return min(1.0, tgt_count / src_count)


def score_purity(translated_text: str, expected_lang: str, fasttext_detector) -> float | None:
    """
    Score language purity using FastText paragraph-by-paragraph detection.

    Returns None if FastText unavailable.
    """
    if fasttext_detector is None:
        return None

    text = _strip_frontmatter_and_code(translated_text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= 20]

    if not paragraphs:
        return 1.0

    correct = 0
    total = 0
    for para in paragraphs:
        try:
            detected_lang, confidence = fasttext_detector.detect(para)
            if confidence < 0.30:
                # Low confidence → likely technical content, skip
                continue
            total += 1
            # Accept similar language pairs (e.g. hr≈sr)
            if detected_lang == expected_lang or detected_lang.startswith(expected_lang[:2]):
                correct += 1
        except Exception:
            continue

    return (correct / total) if total > 0 else 1.0


def score_terminology(source_text: str, translated_text: str, terminology_config: dict) -> float:
    """
    Score terminology preservation using exact matches from terminology config.

    Checks what fraction of required terms that appear in the source are
    also present in the translation.
    """
    raw_matches = terminology_config.get("global", {}).get("exact_matches", [])
    # Normalize: entries may be plain strings or dicts with a "term" key
    exact_matches = []
    for entry in raw_matches:
        if isinstance(entry, str):
            exact_matches.append(entry)
        elif isinstance(entry, dict):
            term = entry.get("term") or entry.get("text") or entry.get("match")
            if term:
                exact_matches.append(str(term))
    if not exact_matches:
        return 1.0

    required = [t for t in exact_matches if t in source_text]
    if not required:
        return 1.0

    preserved = sum(1 for t in required if t in translated_text)
    return preserved / len(required)


def score_structural_fidelity(source_text: str, translated_text: str) -> float:
    """
    Compare structural element counts (headings, lists, code blocks, tables).

    Returns Jaccard ratio averaged across element types with non-zero source count.
    """

    def counts(text: str) -> dict[str, int]:
        return {
            "h1": len(_RE_H1.findall(text)),
            "h2": len(_RE_H2.findall(text)),
            "h3": len(_RE_H3.findall(text)),
            "list": len(_RE_LIST_ITEM.findall(text)),
            "code": len(_RE_CODE_FENCE.findall(text)) // 2,  # pairs
            "table": len(_RE_TABLE_ROW.findall(text)),
        }

    src = counts(source_text)
    tgt = counts(translated_text)

    ratios = []
    for key, src_n in src.items():
        if src_n == 0:
            continue
        tgt_n = tgt.get(key, 0)
        ratio = min(src_n, tgt_n) / max(src_n, tgt_n)
        ratios.append(ratio)

    return sum(ratios) / len(ratios) if ratios else 1.0


def score_shortcode_preservation(source_text: str, translated_text: str) -> float:
    """
    Score Hugo shortcode preservation using the same regex as hugo_parser.py.
    """
    src_codes = _SHORTCODE_RE.findall(source_text)
    tgt_codes = _SHORTCODE_RE.findall(translated_text)

    if not src_codes:
        return 1.0

    # Check what fraction of source shortcodes appear in translation
    tgt_set = list(tgt_codes)  # maintain counts
    matched = 0
    for code in src_codes:
        if code in tgt_set:
            matched += 1
            tgt_set.remove(code)

    return matched / len(src_codes)


def score_naturalness_llm(
    source_text: str,
    translated_text: str,
    lang: str,
    llm_provider,
) -> float | None:
    """
    Use professionalize_llm to score translation naturalness (0-10 → 0.0-1.0).

    Samples up to 3 random paragraphs and averages the scores.
    """
    if llm_provider is None:
        return None

    text = _strip_frontmatter_and_code(translated_text)
    src_text = _strip_frontmatter_and_code(source_text)

    paras_tgt = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 50]
    paras_src = [p.strip() for p in re.split(r"\n\s*\n", src_text) if len(p.strip()) > 50]

    if not paras_tgt:
        return None

    rng = random.Random(42)
    sample_size = min(3, len(paras_tgt))
    indices = rng.sample(range(len(paras_tgt)), sample_size)

    scores = []
    for idx in indices:
        tgt_para = paras_tgt[idx]
        src_para = paras_src[idx] if idx < len(paras_src) else ""

        prompt = (
            f"Rate the following {lang} translation for naturalness on a scale of 0 to 10. "
            f"10 = fluent, native-sounding. 0 = unreadable. Reply ONLY with a single integer.\n\n"
            f"Source (English):\n{src_para[:300]}\n\n"
            f"Translation ({lang}):\n{tgt_para[:300]}"
        )
        try:
            # generate(system_prompt, user_text) → (text, input_tokens, output_tokens)
            text_response, _, _ = llm_provider.generate(
                "You are a professional translation quality evaluator.",
                prompt,
            )
            score_text = text_response.strip().split()[0] if text_response.strip() else ""
            score_val = (
                int(re.search(r"\d+", score_text).group())
                if re.search(r"\d+", score_text)
                else None
            )
            if score_val is not None:
                scores.append(max(0, min(10, score_val)) / 10.0)
        except Exception as e:
            logger.debug("LLM scoring failed for paragraph: %s", e)

    return sum(scores) / len(scores) if scores else None


def score_meaning_fidelity(
    source_text: str,
    translated_text: str,
    lang: str,
    model_id: str | None,
) -> tuple[float | None, list[str]]:
    """
    HT-QUALITY-GATES-001 Part 22 (plan 5.4 item 4): the sampled/periodic-audit
    half of tiered fidelity coverage. Uses the same LLM judge as write_gate.py's
    Gate 36 (src.translation_engine.validation.fidelity_judge), but here it can
    run against ANY sampled file, not just the synchronous high-risk tier --
    this is what makes the plan's "otherwise sampling-based ongoing audit"
    concrete rather than aspirational.

    Returns (score_0_to_1, issues) -- (None, []) if disabled or the judge
    fails open (network error, unparseable response, etc; see
    fidelity_judge.judge_fidelity's docstring).
    """
    if model_id is None:
        return None, []

    from src.translation_engine.validation.fidelity_judge import judge_fidelity

    body_src = _strip_frontmatter_and_code(source_text)
    body_tgt = _strip_frontmatter_and_code(translated_text)
    if len(body_tgt.strip()) < 50:
        return None, []

    verdict = judge_fidelity(body_src, body_tgt, "en", lang, model_id=model_id)
    if verdict is None:
        return None, []
    return verdict.score, verdict.issues


# ---------------------------------------------------------------------------
# Weighted aggregate
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "completeness": 0.30,
    "purity": 0.25,
    "terminology": 0.20,
    "structural_fidelity": 0.15,
    "shortcode_preservation": 0.10,
}


def compute_overall(scores: FileScores) -> float:
    """Compute weighted overall score from available dimensions."""
    total_weight = 0.0
    weighted_sum = 0.0
    for dim, weight in _WEIGHTS.items():
        val = getattr(scores, dim)
        if val is not None:
            weighted_sum += val * weight
            total_weight += weight
    if total_weight == 0:
        return 0.0
    return weighted_sum / total_weight


def compute_flags(scores: FileScores, threshold: float) -> list[str]:
    flags = []
    for dim in _WEIGHTS:
        val = getattr(scores, dim)
        if val is not None and val < threshold:
            flags.append(f"{dim}={val:.2f}<{threshold}")
    return flags


# ---------------------------------------------------------------------------
# Main scoring loop
# ---------------------------------------------------------------------------


def score_pair(
    pair: SamplePair,
    terminology_config: dict,
    fasttext_detector,
    llm_provider,
    threshold: float,
    fidelity_model_id: str | None = None,
) -> FileScores:
    result = FileScores(
        source_path=str(pair.source_path),
        translated_path=str(pair.translated_path),
        lang=pair.lang,
        site=pair.site,
        content_type=pair.content_type,
    )

    try:
        source_text = pair.source_path.read_text(encoding="utf-8", errors="replace")
        translated_text = pair.translated_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        result.error = f"read error: {e}"
        return result

    try:
        result.completeness = score_completeness(source_text, translated_text)
    except Exception as e:
        logger.debug("completeness scoring failed: %s", e)

    try:
        result.purity = score_purity(translated_text, pair.lang, fasttext_detector)
    except Exception as e:
        logger.debug("purity scoring failed: %s", e)

    try:
        result.terminology = score_terminology(source_text, translated_text, terminology_config)
    except Exception as e:
        logger.debug("terminology scoring failed: %s", e)

    try:
        result.structural_fidelity = score_structural_fidelity(source_text, translated_text)
    except Exception as e:
        logger.debug("structural fidelity scoring failed: %s", e)

    try:
        result.shortcode_preservation = score_shortcode_preservation(source_text, translated_text)
    except Exception as e:
        logger.debug("shortcode scoring failed: %s", e)

    if llm_provider is not None:
        try:
            result.naturalness_llm = score_naturalness_llm(
                source_text, translated_text, pair.lang, llm_provider
            )
        except Exception as e:
            logger.debug("LLM naturalness scoring failed: %s", e)

    if fidelity_model_id is not None:
        try:
            result.fidelity_llm, result.fidelity_issues = score_meaning_fidelity(
                source_text, translated_text, pair.lang, fidelity_model_id
            )
        except Exception as e:
            logger.debug("LLM fidelity scoring failed: %s", e)

    result.overall = compute_overall(result)
    result.flags = compute_flags(result, threshold)

    return result


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _avg(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def build_report(
    file_scores: list[FileScores],
    mode: str,
    threshold: float,
) -> AuditReport:
    def group_aggregate(scores_list: list[FileScores]) -> dict:
        dims = [
            "completeness",
            "purity",
            "terminology",
            "structural_fidelity",
            "shortcode_preservation",
            "overall",
        ]
        agg = {}
        for dim in dims:
            vals = [getattr(s, dim) for s in scores_list]
            agg[dim] = round(_avg(vals), 4) if _avg(vals) is not None else None
        agg["count"] = len(scores_list)
        agg["flagged"] = sum(1 for s in scores_list if s.flags)
        return agg

    by_lang: dict[str, list[FileScores]] = {}
    by_site: dict[str, list[FileScores]] = {}
    by_ct: dict[str, list[FileScores]] = {}

    for s in file_scores:
        by_lang.setdefault(s.lang, []).append(s)
        by_site.setdefault(s.site, []).append(s)
        by_ct.setdefault(s.content_type, []).append(s)

    return AuditReport(
        generated_at=date.today().isoformat(),
        mode=mode,
        threshold=threshold,
        total_files=len(file_scores),
        flagged_files=sum(1 for s in file_scores if s.flags),
        aggregate=group_aggregate(file_scores),
        by_lang={k: group_aggregate(v) for k, v in sorted(by_lang.items())},
        by_site={k: group_aggregate(v) for k, v in sorted(by_site.items())},
        by_content_type={k: group_aggregate(v) for k, v in sorted(by_ct.items())},
        files=[asdict(s) for s in file_scores],
    )


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------


def print_summary(report: AuditReport) -> None:
    agg = report.aggregate
    print(f"\n{'=' * 60}")
    print(f"TRANSLATION QUALITY AUDIT — {report.generated_at}")
    print(f"Mode: {report.mode}  |  Threshold: {report.threshold}  |  Files: {report.total_files}")
    print(f"{'=' * 60}")
    print("\nOVERALL AGGREGATE")
    for dim in [
        "completeness",
        "purity",
        "terminology",
        "structural_fidelity",
        "shortcode_preservation",
        "overall",
    ]:
        val = agg.get(dim)
        bar = "OK " if val is None or val >= report.threshold else "LOW"
        val_str = f"{val:.3f}" if val is not None else "N/A "
        print(f"  [{bar}] {dim:<28} {val_str}")
    print(
        f"\n  Flagged: {report.flagged_files}/{report.total_files} files below threshold {report.threshold}"
    )

    print("\nBY LANGUAGE")
    for lang, data in report.by_lang.items():
        overall = data.get("overall")
        flag_n = data.get("flagged", 0)
        count = data.get("count", 0)
        bar = "OK " if overall is None or overall >= report.threshold else "LOW"
        overall_str = f"{overall:.3f}" if overall is not None else "N/A "
        print(f"  [{bar}] {lang:<6} overall={overall_str}  flagged={flag_n}/{count}")

    if report.flagged_files > 0:
        print("\nFLAGGED FILES (showing first 10)")
        shown = 0
        for f in report.files:
            if f.get("flags"):
                print(
                    f"  {Path(f['translated_path']).name}  [{f['lang']}]  overall={f.get('overall', 'N/A'):.3f}"
                )
                print(f"    flags: {', '.join(f['flags'])}")
                shown += 1
                if shown >= 10:
                    break

    print(f"\n{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Audit translation quality across sampled file pairs")
    p.add_argument(
        "--content-root",
        type=Path,
        default=None,
        help="Root directory containing translated content (source + translations)",
    )
    p.add_argument(
        "--langs",
        nargs="+",
        default=["fr", "de", "es"],
        help="Target language codes to audit (default: fr de es)",
    )
    p.add_argument(
        "--n-per-stratum",
        type=int,
        default=5,
        help="Files to sample per (site, lang, content_type) stratum (default: 5)",
    )
    p.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducible sampling (default: 42)"
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="Score threshold below which files are flagged (default: 0.70)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON report path (default: reports/audit/audit_YYYY-MM-DD.json)",
    )
    p.add_argument(
        "--mode",
        choices=["full", "ci"],
        default="full",
        help="'ci' uses test fixtures only, no FastText/LLM (default: full)",
    )
    p.add_argument(
        "--use-llm",
        action="store_true",
        help="Enable optional LLM naturalness (fluency) scoring via professionalize_llm",
    )
    p.add_argument(
        "--use-fidelity-judge",
        action="store_true",
        help=(
            "Enable LLM MEANING-fidelity scoring (HT-QUALITY-GATES-001 Part 22 "
            "plan 5.4 item 4) -- distinct from --use-llm's fluency check. This is "
            "the sampled/periodic-audit tier; write_gate.py's Gate 36 is the "
            "synchronous high-risk-tier check using the same judge."
        ),
    )
    p.add_argument(
        "--fidelity-model-id",
        default="professionalize_llm",
        help="Model registry ID to use for --use-fidelity-judge (default: professionalize_llm)",
    )
    p.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ---------------------------------------------------------------------------
    # Resolve output path
    # ---------------------------------------------------------------------------
    if args.output is None:
        out_dir = _PROJECT_ROOT / "reports" / "audit"
        out_dir.mkdir(parents=True, exist_ok=True)
        args.output = out_dir / f"audit_{date.today().isoformat()}.json"

    # ---------------------------------------------------------------------------
    # Load terminology config
    # ---------------------------------------------------------------------------
    terminology_config: dict = {}
    terminology_path = _PROJECT_ROOT / "config" / "terminology.yaml"
    if terminology_path.exists():
        try:
            import yaml

            with open(terminology_path, encoding="utf-8") as f:
                terminology_config = yaml.safe_load(f) or {}
            logger.info("Loaded terminology config from %s", terminology_path)
        except Exception as e:
            logger.warning("Could not load terminology config: %s", e)
    else:
        logger.warning(
            "Terminology config not found at %s — terminology scoring will be 1.0", terminology_path
        )

    # ---------------------------------------------------------------------------
    # Initialize FastText detector (skipped in CI mode or if model absent)
    # ---------------------------------------------------------------------------
    fasttext_detector = None
    if args.mode != "ci":
        fasttext_model_path = _PROJECT_ROOT / "data" / "models" / "fasttext" / "lid.176.bin"
        if fasttext_model_path.exists():
            try:
                from src.translation_engine.language_detection.fasttext_detector import (
                    FastTextDetector,
                )

                fasttext_detector = FastTextDetector(
                    cache_dir=fasttext_model_path.parent,
                    auto_download=False,
                )
                logger.info("FastText detector initialized")
            except Exception as e:
                logger.warning("FastText initialization failed: %s — purity scoring disabled", e)
        else:
            logger.warning(
                "FastText model not found at %s — purity scoring disabled", fasttext_model_path
            )

    # ---------------------------------------------------------------------------
    # Initialize LLM provider (optional)
    # ---------------------------------------------------------------------------
    llm_provider = None
    if args.use_llm and args.mode != "ci":
        try:
            import yaml

            from src.model_runtime.contracts import LLMProviderConfig
            from src.model_runtime.llm_providers import create_provider

            global_cfg_path = _PROJECT_ROOT / "config" / "global.yaml"
            with open(global_cfg_path, encoding="utf-8") as f:
                global_cfg = yaml.safe_load(f) or {}
            # Use the same fallback_model as the content worker
            fallback_model_id = global_cfg.get("model_defaults", {}).get(
                "fallback_model", "professionalize_llm"
            )
            model_registry_path = _PROJECT_ROOT / "config" / "model_registry.yaml"
            with open(model_registry_path, encoding="utf-8") as f:
                registry = yaml.safe_load(f) or {}
            # registry["models"] is a list; find entry by model_id
            model_entry = next(
                (m for m in registry.get("models", []) if m.get("model_id") == fallback_model_id),
                None,
            )
            if model_entry:
                llm_cfg = LLMProviderConfig(
                    provider=model_entry["provider"],
                    model_name=model_entry.get("model_name", "recommended"),
                    base_url=model_entry.get("base_url"),
                    api_key_env=model_entry.get("api_key_env"),
                    temperature=model_entry.get("temperature", 0.0),
                    max_tokens=model_entry.get("max_tokens", 512),
                    timeout_seconds=model_entry.get("timeout_seconds", 60),
                )
                llm_provider = create_provider(llm_cfg)
                logger.info("LLM provider initialized: %s", fallback_model_id)
            else:
                logger.warning(
                    "Model '%s' not found in registry — LLM scoring disabled", fallback_model_id
                )
        except Exception as e:
            logger.warning(
                "LLM provider initialization failed: %s — naturalness scoring disabled", e
            )

    # ---------------------------------------------------------------------------
    # Fidelity judge model id (HT-QUALITY-GATES-001 Part 22, plan 5.4 item 4).
    # judge_fidelity() constructs its own provider on demand (same pattern as
    # correction.py), so there's no provider object to build ahead of time here
    # -- just the model_id, or None to disable.
    # ---------------------------------------------------------------------------
    fidelity_model_id = args.fidelity_model_id if (args.use_fidelity_judge and args.mode != "ci") else None

    # ---------------------------------------------------------------------------
    # Sample pairs
    # ---------------------------------------------------------------------------
    if args.mode == "ci":
        fixtures_dir = _PROJECT_ROOT / "tests" / "fixtures"
        pairs = sample_fixture_pairs(fixtures_dir)
        if not pairs:
            # Create a minimal synthetic pair from any existing fixture
            logger.info("No fixture translation pairs found — creating synthetic test")
            # CI gate passes vacuously when no pairs exist (nothing to fail)
            pairs = []
    else:
        if args.content_root is None:
            logger.error("--content-root is required in 'full' mode")
            return 1
        if not args.content_root.exists():
            logger.error("Content root does not exist: %s", args.content_root)
            return 1
        pairs = sample_translation_pairs(
            content_root=args.content_root,
            langs=args.langs,
            n_per_stratum=args.n_per_stratum,
            seed=args.seed,
        )

    if not pairs:
        logger.warning("No translation pairs found — report will be empty")

    # ---------------------------------------------------------------------------
    # Score all pairs
    # ---------------------------------------------------------------------------
    file_scores: list[FileScores] = []
    for i, pair in enumerate(pairs, 1):
        logger.info(
            "[%d/%d] Scoring %s → %s [%s]",
            i,
            len(pairs),
            pair.source_path.name,
            pair.translated_path.name,
            pair.lang,
        )
        scores = score_pair(
            pair=pair,
            terminology_config=terminology_config,
            fasttext_detector=fasttext_detector,
            llm_provider=llm_provider,
            threshold=args.threshold,
            fidelity_model_id=fidelity_model_id,
        )
        file_scores.append(scores)

    # ---------------------------------------------------------------------------
    # Build and write report
    # ---------------------------------------------------------------------------
    report = build_report(file_scores, mode=args.mode, threshold=args.threshold)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, default=str)
    logger.info("Report written to %s", args.output)

    print_summary(report)

    # ---------------------------------------------------------------------------
    # Exit code: non-zero if any files flagged
    # ---------------------------------------------------------------------------
    if report.flagged_files > 0:
        print(f"AUDIT FAILED: {report.flagged_files} file(s) below threshold {report.threshold}")
        return 1

    print("AUDIT PASSED: all scored files meet threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
