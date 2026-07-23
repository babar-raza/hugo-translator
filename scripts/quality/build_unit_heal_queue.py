"""
build_unit_heal_queue.py — Walk content directories and run UnitQualityScorer
to produce a JSONL queue for unit_heal.py.

Output format (one JSON per line):
    {
      "file_path": "<TR file path>",
      "en_path": "<EN source path>",
      "locale": "zh",
      "site_id": "reference.aspose.org",
      "issues": [{"type": "mojibake_detector", "unit_indices": [3, 7], "priority": 1}],
      "max_priority": 1
    }

Usage:
    python scripts/quality/build_unit_heal_queue.py \\
        --sites reference.aspose.org docs.aspose.org kb.aspose.org \\
        --locales all \\
        --output data/audit/unit_heal_queue.jsonl \\
        --min-severity 0.5 \\
        --resume
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import iter_locale_pairs  # noqa: E402

_CONFIG = ConfigService(_PROJECT_ROOT / "config")

logger = logging.getLogger(__name__)

# Issue priority map (lower = more critical)
PRIORITY = {
    "mojibake_detector": 1,
    "shortcode_leak_detector": 1,
    "empty_unit_detector": 1,
    "language_purity_detector": 2,
    "inline_code_integrity_detector": 2,
    "hallucination_length_detector": 2,
    "short_api_desc_detector": 2,
    "link_path_detector": 3,
    "duplicate_run_detector": 3,
    "newline_ratio_detector": 3,
}

# Durable-fix consolidation: replaced _SITE_ENV_MAP (only covered 3 sites,
# and incorrectly mapped docs.aspose.org/kb.aspose.org to ASPOSE_NET_CONTENT
# -- the wrong project; those two live under ASPOSE_ORG_CONTENT per their
# own site profiles) + a hand-copied ALL_LOCALES list (had drifted: a stray
# extra "sl" not present in any real site's target_langs) with the same
# registry-driven ConfigService/content_discovery primitives used
# throughout this consolidation.


def _get_site_profile_and_root(site_id: str):
    """Return (profile, content_root) for site_id, or (None, None) if the
    profile can't be loaded or its content root doesn't exist on disk."""
    try:
        profile = _CONFIG.get_site_profile(site_id)
    except Exception:
        return None, None
    content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
    return (profile, content_root) if content_root.exists() else (None, None)


def _find_en_tr_pairs(
    profile,
    content_root: Path,
    locales: list[str],
) -> list[tuple[Path, Path, str]]:
    """Return (en_path, tr_path, locale) tuples for existing translations.
    Registry-driven via content_discovery -- works identically for
    directory-scheme and file-suffix-scheme sites."""
    pairs = []
    for en_path, locale, tr_path in iter_locale_pairs(profile, content_root):
        if locale in locales and tr_path.exists():
            pairs.append((en_path, tr_path, locale))
    return pairs


def build_queue(
    sites: list[str],
    locales: list[str],
    output_path: Path,
    min_severity: float,
    resume: bool,
) -> int:
    from src.translation_engine.unit_quality_scorer import UnitQualityScorer
    from src.translation_engine.parser import HugoParser
    from src.translation_engine.extractor import TextUnitExtractor

    # Load done set (resume)
    done_set: set[str] = set()
    if resume and output_path.exists():
        with output_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        done_set.add(json.loads(line)["file_path"])
                    except Exception:
                        pass
        logger.info("Resume: %d files already in queue", len(done_set))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if resume and output_path.exists() else "w"

    total_written = 0
    parser = HugoParser()
    extractor = TextUnitExtractor(segmentation_strategy="sentence_only")

    with output_path.open(mode, encoding="utf-8") as out_fh:
        for site_id in sites:
            profile, content_root = _get_site_profile_and_root(site_id)
            if not profile:
                logger.error("Cannot resolve content root for site: %s", site_id)
                continue

            # "all" resolves to THIS site's configured target_langs, not a
            # hand-copied global list -- avoids the ALL_LOCALES drift found
            # during the durable-fix investigation (a stray "sl" not in any
            # real site's target_langs).
            site_locales = (
                sorted(profile.target_langs) if "all" in locales else locales
            )

            logger.info("Scanning %s at %s", site_id, content_root)
            pairs = _find_en_tr_pairs(profile, content_root, site_locales)
            logger.info("Found %d EN/TR pairs for %s", len(pairs), site_id)

            for en_path, tr_path, locale in pairs:
                file_path = str(tr_path)
                if file_path in done_set:
                    continue

                try:
                    en_content = en_path.read_text(encoding="utf-8")
                    tr_content = tr_path.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.debug("Read error %s: %s", file_path, exc)
                    continue

                try:
                    en_doc = parser.parse_string(en_content)
                    tr_doc = parser.parse_string(tr_content)
                    en_units = extractor.extract_from_ast(en_doc.ast, en_doc.frontmatter).units
                    tr_units = extractor.extract_from_ast(tr_doc.ast, tr_doc.frontmatter).units
                except Exception as exc:
                    logger.debug("Parse error %s: %s", file_path, exc)
                    continue

                scorer = UnitQualityScorer(config={}, locale=locale)
                issues = scorer.score(en_units, tr_units)

                # Apply severity threshold (confidence < threshold = bad)
                issues = [i for i in issues if i.confidence <= min_severity]
                if not issues:
                    continue

                # Group by issue type
                type_map: dict[str, list[int]] = {}
                for issue in issues:
                    type_map.setdefault(issue.issue_type, []).append(issue.unit_idx)

                issue_list = [
                    {
                        "type": itype,
                        "unit_indices": sorted(set(indices)),
                        "priority": PRIORITY.get(itype, 5),
                    }
                    for itype, indices in type_map.items()
                ]
                max_priority = min(item["priority"] for item in issue_list)

                entry = {
                    "file_path": file_path,
                    "en_path": str(en_path),
                    "locale": locale,
                    "site_id": site_id,
                    "issues": issue_list,
                    "max_priority": max_priority,
                }
                out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                total_written += 1
                done_set.add(file_path)

                if total_written % 500 == 0:
                    out_fh.flush()
                    logger.info("  %d entries written so far...", total_written)

    return total_written


def main() -> None:
    p = argparse.ArgumentParser(description="Build unit heal queue from disk scan")
    p.add_argument("--sites", nargs="+", required=True, help="Site IDs to scan")
    p.add_argument(
        "--locales",
        nargs="+",
        default=["all"],
        help="Locales to scan (use 'all' for all known locales)",
    )
    p.add_argument(
        "--output",
        default="data/audit/unit_heal_queue.jsonl",
        help="Output JSONL path",
    )
    p.add_argument(
        "--min-severity",
        type=float,
        default=0.5,
        dest="min_severity",
        help="Include units with confidence <= this value (0=definitely bad, 1=ok)",
    )
    p.add_argument("--resume", action="store_true", help="Skip files already in output")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # "all" is resolved per-site inside build_queue (each site's own
    # target_langs), not to a single hand-copied global list -- see
    # _find_en_tr_pairs's docstring / the durable-fix consolidation notes
    # above _get_site_profile_and_root.
    locales = args.locales
    output_path = Path(args.output)

    logger.info(
        "build_unit_heal_queue: sites=%s locales=%s min_severity=%.2f",
        args.sites,
        "all (per-site target_langs)" if "all" in locales else locales,
        args.min_severity,
    )

    count = build_queue(
        sites=args.sites,
        locales=locales,
        output_path=output_path,
        min_severity=args.min_severity,
        resume=args.resume,
    )
    logger.info("Done: %d queue entries written to %s", count, output_path)


if __name__ == "__main__":
    main()
