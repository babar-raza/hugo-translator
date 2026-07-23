"""
audit_semantic.py — Tier 4 semantic audit via LLM scoring.

Scores short API description cells that pass T1/T2 structural checks
but may still contain hallucinations (e.g. "psychiatrist" for "shrink to fit").

Only targets:
  - reference.aspose.org TABLE_CELL_TEXT units ≤60 chars
  - Frontmatter description: fields that passed structural audits

LLM prompt: 0-10 quality score. Score < 5 → flagged as table_desc_hallucinated.

Output: data/audit/audit_semantic.jsonl

Usage:
    python scripts/quality/audit_semantic.py \\
        --sites reference.aspose.org \\
        --locales zh ja ko ar uk \\
        --max-calls 1000 \\
        --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import iter_locale_pairs  # noqa: E402

# TC-AUD-008 (superseded by the durable-fix consolidation): was env-var
# indirection (_SITE_ENV_MAP) mapping docs/kb to ASPOSE_NET_CONTENT -- wrong
# project entirely, and depended on an env var never actually loaded
# in-process. Then briefly a single hardcoded CONTENT_ROOT constant
# (correct for the 5 aspose.org sites this script has been run against so
# far, but wrong the moment anyone points it at an aspose.net site). Now
# resolved per-site via ConfigService.resolve_content_root, same as every
# other migrated audit script -- correct regardless of which real content
# root a given --sites value lives under.
_CONFIG = ConfigService(_PROJECT_ROOT / "config")

_NON_LATIN_LOCALES = frozenset(
    "ar bg el fa he hi ja ko ru th uk zh".split()
)

_SHORT_API_RE = re.compile(
    r"^(?:Gets?|Sets?|Indicates?|Enables?|Disables?|Represents?|Returns?)\s",
    re.IGNORECASE,
)

_SCORE_RE = re.compile(r'"score"\s*:\s*(\d+(?:\.\d+)?)')


def _get_site_profile_and_root(site_id: str):
    """Return (profile, content_root) for site_id, or (None, None) if the
    profile can't be loaded or its content root doesn't exist on disk."""
    try:
        profile = _CONFIG.get_site_profile(site_id)
    except Exception:
        return None, None
    content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
    return (profile, content_root) if content_root.exists() else (None, None)


def _derive_class_name(file_path: Path) -> str:
    """Extract class name from reference.aspose.org file path (last stem)."""
    stem = file_path.stem
    return stem if stem else ""


def _collect_candidates(
    profile,
    content_root: Path,
    site_id: str,
    locales: list[str],
) -> list[dict]:
    """
    Walk files and extract short API description units as scoring candidates.
    Returns list of dicts: {en_text, tr_text, locale, file_path, unit_idx, class_name}.

    Registry-driven via content_discovery.iter_locale_pairs -- works
    identically for per_language_folders=True and file-suffix sites, so this
    script produces correct (rather than silently empty) candidates if ever
    pointed at a file-suffix site via --sites.
    """
    from src.translation_engine.parser import HugoParser
    from src.translation_engine.extractor import TextUnitExtractor
    from src.translation_engine.extractor.text_unit import TextUnitKind

    parser = HugoParser()
    extractor = TextUnitExtractor(segmentation_strategy="sentence_only")
    candidates = []

    en_doc_cache: dict[Path, list] = {}

    for en_file, locale, tr_file in iter_locale_pairs(profile, content_root):
        if locale not in _NON_LATIN_LOCALES or locale not in locales:
            continue
        if not tr_file.exists():
            continue

        class_name = _derive_class_name(en_file)

        if en_file not in en_doc_cache:
            try:
                en_content = en_file.read_text(encoding="utf-8")
                en_doc = parser.parse_string(en_content)
                en_doc_cache[en_file] = extractor.extract_from_ast(
                    en_doc.ast, en_doc.frontmatter
                ).units
            except Exception:
                en_doc_cache[en_file] = None
        en_units = en_doc_cache[en_file]
        if en_units is None:
            continue

        try:
            tr_content = tr_file.read_text(encoding="utf-8")
            tr_doc = parser.parse_string(tr_content)
            tr_units = extractor.extract_from_ast(tr_doc.ast, tr_doc.frontmatter).units
        except Exception:
            continue

        for unit_idx, en_unit in enumerate(en_units):
            if en_unit.kind != TextUnitKind.TABLE_CELL_TEXT:
                continue
            en_text = (en_unit.source_text or "").strip()
            if not en_text or len(en_text) > 60:
                continue
            if not _SHORT_API_RE.match(en_text):
                continue
            if unit_idx >= len(tr_units):
                continue
            tr_unit = tr_units[unit_idx]
            tr_text = (tr_unit.source_text or "").strip()
            if not tr_text:
                continue

            candidates.append(
                {
                    "en_text": en_text,
                    "tr_text": tr_text,
                    "locale": locale,
                    "file_path": str(tr_file),
                    "en_path": str(en_file),
                    "unit_idx": unit_idx,
                    "class_name": class_name,
                    "site_id": site_id,
                }
            )

    return candidates


def _build_score_prompt(
    batch: list[dict],
    locale: str,
    class_name: str,
) -> tuple[str, str]:
    """Build system + user prompt for a batch of units."""
    system = (
        "You are a translation quality auditor for API documentation.\n"
        "You will receive numbered source (English) + translation pairs for "
        f"properties of the `{class_name}` class.\n"
        "Rate each translation 0-10: 10=perfect, 0=completely wrong/nonsensical.\n"
        "Reply with a JSON array: "
        '[{"idx": 1, "score": 9, "reason": "..."}, {"idx": 2, ...}]\n'
        "Only JSON, no prose."
    )
    lines = []
    for i, item in enumerate(batch, 1):
        lines.append(f"{i}. EN: {item['en_text']!r}")
        lines.append(f"   {locale.upper()}: {item['tr_text']!r}")
    user = "\n".join(lines)
    return system, user


def _call_llm(system: str, user: str, model_loader) -> str | None:
    """Call professionalize_llm with the scoring prompt. Returns raw text response."""
    try:
        # TC-AUD-009: was constructing LLMModelBackend(config=..., model_name=...)
        # directly -- neither kwarg exists on its real __init__(model_info, device)
        # signature (never caught because T4 had never actually been run end to
        # end). ModelLoader is the proven, correct way to obtain a backend by
        # model_id (matches heal_english_headings.py::_build_engine); it also
        # caches the loaded backend, so repeated calls across many units are cheap.
        backend = model_loader.load_model("professionalize_llm")
        # TC-AUD-009 (cont'd): provider.chat(messages=..., system=..., ...)
        # doesn't exist on the real provider classes (OpenAICompatibleProvider
        # etc.) -- the actual public interface is generate(system_prompt,
        # user_text) -> (text, input_tokens, output_tokens), per
        # BaseLLMProvider.generate() in llm_providers.py.
        provider = backend._provider
        text, _input_tokens, _output_tokens = provider.generate(system, user)
        return text
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return None


def _parse_scores(response: str, batch_size: int) -> list[float]:
    """Parse JSON array of scores from LLM response. Returns list of floats."""
    try:
        data = json.loads(response)
        if isinstance(data, list):
            scores = []
            for item in data:
                score = float(item.get("score", 5.0))
                scores.append(score)
            return scores
    except Exception:
        pass
    # Fallback: extract all numbers matching "score": N
    matches = _SCORE_RE.findall(response)
    if matches:
        return [float(m) for m in matches[:batch_size]]
    return [5.0] * batch_size  # neutral fallback


def run_audit(
    sites: list[str],
    locales: list[str],
    output_path: Path,
    max_calls: int,
    dry_run: bool,
    resume: bool,
    batch_size: int = 20,
) -> dict:
    # TC-AUD-009: ConfigService(config) was constructed with zero args
    # (its real signature requires config_root) and imported from a module
    # that doesn't exist (src.config.config_service). config was also never
    # actually needed here -- only a ModelLoader capable of resolving
    # "professionalize_llm" is. device="cuda" is inert for this model
    # (LLMModelBackend ignores it, always runs as "api"/HTTP).
    from src.model_runtime.loader import ModelLoader
    from src.model_runtime.registry import ModelRegistry

    registry = ModelRegistry(str(_PROJECT_ROOT / "config" / "model_registry.yaml"))
    model_loader = ModelLoader(registry=registry, device="cuda", max_memory_mb=7000)

    # Load done set
    done_files: set[str] = set()
    if resume and output_path.exists():
        with output_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    done_files.add(json.loads(line)["file_path"])
                except Exception:
                    pass

    output_path.parent.mkdir(parents=True, exist_ok=True)

    stats = {"calls_made": 0, "candidates_scored": 0, "hallucinations_found": 0}
    mode = "a" if resume and output_path.exists() else "w"

    with output_path.open(mode, encoding="utf-8") as out_fh:
        for site_id in sites:
            profile, content_root = _get_site_profile_and_root(site_id)
            if not profile:
                logger.error("Cannot resolve content root for site: %s", site_id)
                continue

            logger.info("Collecting candidates from %s", site_id)
            candidates = _collect_candidates(profile, content_root, site_id, locales)
            logger.info("Found %d short API description candidates", len(candidates))

            if dry_run:
                logger.info("DRY-RUN: would score %d candidates in ~%d API calls",
                            len(candidates), (len(candidates) + batch_size - 1) // batch_size)
                continue

            # Group by (locale, class_name) for batching
            from itertools import groupby
            sorted_cands = sorted(
                [c for c in candidates if c["file_path"] not in done_files],
                key=lambda c: (c["locale"], c["class_name"]),
            )

            for (locale, class_name), group in groupby(
                sorted_cands, key=lambda c: (c["locale"], c["class_name"])
            ):
                items = list(group)
                # Split into batches
                for batch_start in range(0, len(items), batch_size):
                    if stats["calls_made"] >= max_calls:
                        logger.info("Reached --max-calls limit (%d), stopping", max_calls)
                        break
                    batch = items[batch_start: batch_start + batch_size]
                    system, user = _build_score_prompt(batch, locale, class_name)

                    t0 = time.monotonic()
                    response = _call_llm(system, user, model_loader)
                    elapsed = time.monotonic() - t0
                    stats["calls_made"] += 1

                    if response is None:
                        continue

                    scores = _parse_scores(response, len(batch))
                    stats["candidates_scored"] += len(batch)

                    for item, score in zip(batch, scores):
                        if score < 5.0:
                            stats["hallucinations_found"] += 1
                            entry = {
                                "file_path": item["file_path"],
                                "en_path": item["en_path"],
                                "locale": item["locale"],
                                "site_id": item["site_id"],
                                "issues": [
                                    {
                                        "type": "table_desc_hallucinated",
                                        "unit_indices": [item["unit_idx"]],
                                        "priority": 1,
                                        "score": score,
                                        "en_text": item["en_text"],
                                        "tr_text": item["tr_text"],
                                    }
                                ],
                                "max_priority": 1,
                            }
                            out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

                    logger.debug(
                        "Scored %d units (locale=%s class=%s) in %.1fs",
                        len(batch), locale, class_name, elapsed,
                    )

                if stats["calls_made"] >= max_calls:
                    break

            if out_fh:
                out_fh.flush()

    return stats


def main() -> None:
    p = argparse.ArgumentParser(description="Semantic audit via LLM scoring")
    p.add_argument(
        "--sites", nargs="+",
        default=["reference.aspose.org"],
        help="Site IDs to audit",
    )
    p.add_argument("--locales", nargs="+", default=list(_NON_LATIN_LOCALES))
    p.add_argument(
        "--output",
        default="data/audit/audit_semantic.jsonl",
    )
    p.add_argument(
        "--max-calls", type=int, default=1000, dest="max_calls",
        help="Stop after this many LLM API calls (cost gate)",
    )
    p.add_argument(
        "--batch-size", type=int, default=20, dest="batch_size",
        help="Units per LLM call",
    )
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="Count candidates without calling LLM")
    p.add_argument("--resume", action="store_true",
                   help="Skip files already in output")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    result = run_audit(
        sites=args.sites,
        locales=args.locales,
        output_path=Path(args.output),
        max_calls=args.max_calls,
        dry_run=args.dry_run,
        resume=args.resume,
        batch_size=args.batch_size,
    )

    print("\n--- Audit Summary ---")
    for k, v in result.items():
        print(f"  {k}: {v}")
    if result.get("calls_made", 0) == 0 and not args.dry_run:
        print("\nNo LLM calls made. Is professionalize_llm configured?")


if __name__ == "__main__":
    main()
