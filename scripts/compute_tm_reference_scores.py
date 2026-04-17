#!/usr/bin/env python3
"""
TM Reference Score Computation (chrF via sacrebleu)

For files where >80% of segments have L2 TM hits, the TM translations serve
as pseudo-references. This script computes chrF scores between current
translated output and TM references, surfacing regression signals.

Prerequisites:
    pip install sacrebleu lmdb

Usage:
    python scripts/compute_tm_reference_scores.py \\
        --content-root D:\\onedrive\\Documents\\GitHub\\aspose.net \\
        --tm-path data/tm \\
        --site-id reference.aspose.net \\
        --langs fr de \\
        --n-sample 10
"""

import argparse
import logging
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_ALL_LANGUAGE_CODES = frozenset([
    "af", "ar", "az", "bg", "ca", "cs", "da", "de", "el", "es", "et",
    "fa", "fi", "fr", "ga", "he", "hi", "hr", "hu", "id", "it", "ja", "ko",
    "lt", "lv", "ms", "nb", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl",
    "sr", "sv", "th", "tr", "uk", "vi", "zh",
])


@dataclass
class FileScoreResult:
    source_path: str
    translated_path: str
    lang: str
    total_segments: int
    tm_hit_segments: int
    tm_hit_rate: float
    chrf_score: Optional[float]
    note: str = ""


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def _strip_code_blocks(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


def _split_segments(text: str) -> List[str]:
    """Split text into paragraph-level segments."""
    text = _strip_frontmatter(text)
    text = _strip_code_blocks(text)
    segs = [p.strip() for p in re.split(r"\n\s*\n", text)]
    return [s for s in segs if len(s) > 15 and any(c.isalpha() for c in s)]


def _find_translated_path(source_path: Path, content_root: Path, lang: str) -> Optional[Path]:
    try:
        rel = source_path.relative_to(content_root)
        candidate = content_root / lang / rel
        if candidate.exists():
            return candidate
    except ValueError:
        pass
    candidate = source_path.parent / f"{source_path.stem}.{lang}{source_path.suffix}"
    return candidate if candidate.exists() else None


def score_file(
    source_path: Path,
    translated_path: Path,
    lang: str,
    tm: "L2PersistentTM",
    site_id: str,
    sacrebleu_chrf,
    min_tm_rate: float = 0.80,
) -> FileScoreResult:
    result = FileScoreResult(
        source_path=str(source_path),
        translated_path=str(translated_path),
        lang=lang,
        total_segments=0,
        tm_hit_segments=0,
        tm_hit_rate=0.0,
        chrf_score=None,
    )

    try:
        src_text = source_path.read_text(encoding="utf-8", errors="replace")
        tgt_text = translated_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        result.note = f"read error: {e}"
        return result

    src_segs = _split_segments(src_text)
    tgt_segs = _split_segments(tgt_text)

    if not src_segs:
        result.note = "no segments"
        return result

    result.total_segments = len(src_segs)

    # Look up each source segment in L2 TM
    tm_hypotheses: List[str] = []
    tm_references: List[str] = []

    for i, seg in enumerate(src_segs):
        try:
            entry = tm.exact_lookup(
                site_id=site_id,
                src_lang="en",
                tgt_lang=lang,
                text=seg,
            )
        except Exception:
            entry = None

        if entry is not None and entry.translated_text:
            result.tm_hit_segments += 1
            # Get corresponding translated segment (by index, best-effort)
            if i < len(tgt_segs):
                tm_hypotheses.append(tgt_segs[i])
                tm_references.append(entry.translated_text)

    result.tm_hit_rate = result.tm_hit_segments / result.total_segments

    if result.tm_hit_rate < min_tm_rate:
        result.note = f"TM hit rate {result.tm_hit_rate:.1%} < {min_tm_rate:.1%} threshold — skipped"
        return result

    if not tm_hypotheses:
        result.note = "no usable TM pairs after alignment"
        return result

    # Compute chrF score
    try:
        score = sacrebleu_chrf.corpus_score(tm_hypotheses, [tm_references])
        result.chrf_score = score.score
    except Exception as e:
        result.note = f"chrF scoring error: {e}"

    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Compute chrF scores vs TM pseudo-references")
    p.add_argument("--content-root", type=Path, required=True)
    p.add_argument("--tm-path", type=Path, default=_PROJECT_ROOT / "data" / "tm",
                   help="Path to L2 LMDB TM directory (default: data/tm)")
    p.add_argument("--site-id", type=str, default="reference.aspose.net",
                   help="Site ID used as TM key prefix (default: reference.aspose.net)")
    p.add_argument("--langs", nargs="+", default=["fr", "de"],
                   help="Target languages to check")
    p.add_argument("--n-sample", type=int, default=10,
                   help="Files to sample per language (default: 10)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--min-tm-rate", type=float, default=0.80,
                   help="Minimum TM hit rate for a file to be scored (default: 0.80)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check dependencies
    try:
        import sacrebleu
        chrf = sacrebleu.CHRF()
    except ImportError:
        logger.error("sacrebleu not installed. Run: pip install sacrebleu")
        return 1

    try:
        from src.tm.l2_persistent import L2PersistentTM
    except ImportError as e:
        logger.error("Cannot import L2PersistentTM: %s", e)
        return 1

    if not args.tm_path.exists():
        logger.error("TM path not found: %s", args.tm_path)
        return 1

    if not args.content_root.exists():
        logger.error("Content root not found: %s", args.content_root)
        return 1

    try:
        tm = L2PersistentTM(args.tm_path)
        logger.info("Opened L2 TM at %s", args.tm_path)
    except Exception as e:
        logger.error("Failed to open L2 TM: %s", e)
        return 1

    rng = random.Random(args.seed)

    # Collect source files
    source_files = []
    for f in args.content_root.rglob("*.md"):
        parts = f.stem.rsplit(".", 1)
        if len(parts) == 2 and parts[1] in _ALL_LANGUAGE_CODES:
            continue
        source_files.append(f)
    logger.info("Found %d source files", len(source_files))

    print(f"\n{'='*60}")
    print(f"TM REFERENCE SCORE REPORT (chrF)")
    print(f"Site: {args.site_id}  |  Min TM hit rate: {args.min_tm_rate:.0%}")
    print(f"{'='*60}\n")

    for lang in args.langs:
        pairs = []
        for src in source_files:
            tgt = _find_translated_path(src, args.content_root, lang)
            if tgt:
                pairs.append((src, tgt))

        if not pairs:
            print(f"  {lang}: no translated files found")
            continue

        sample = rng.sample(pairs, min(args.n_sample, len(pairs)))
        scored = []
        skipped = 0

        for src_path, tgt_path in sample:
            r = score_file(
                source_path=src_path,
                translated_path=tgt_path,
                lang=lang,
                tm=tm,
                site_id=args.site_id,
                sacrebleu_chrf=chrf,
                min_tm_rate=args.min_tm_rate,
            )
            if r.chrf_score is not None:
                scored.append(r)
                logger.debug(
                    "%s → chrF=%.1f  TM hits=%d/%d",
                    tgt_path.name, r.chrf_score, r.tm_hit_segments, r.total_segments
                )
            else:
                skipped += 1
                logger.debug("Skipped %s: %s", tgt_path.name, r.note)

        if scored:
            avg_chrf = sum(r.chrf_score for r in scored) / len(scored)
            avg_tm_rate = sum(r.tm_hit_rate for r in scored) / len(scored)
            print(f"  {lang:<6}  avg chrF={avg_chrf:.1f}  avg TM rate={avg_tm_rate:.1%}  ({len(scored)} files scored, {skipped} skipped)")
        else:
            print(f"  {lang:<6}  no files met the {args.min_tm_rate:.0%} TM hit rate threshold ({skipped} skipped)")

    print(f"\nNOTE: chrF scores are vs TM pseudo-references, not human translations.")
    print(f"      Lower scores may indicate model drift from established translations.")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
