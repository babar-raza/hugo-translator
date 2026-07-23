"""
WS-COMP-2: Wrong-Language Output Scanner

Scans existing translated output files and detects those whose body text is in the
wrong language. This reveals the "invisible" completeness gap: files that pass the
mtime-based completion filter but contain wrong-language content.

How it works:
  1. Walks output files for the given site(s) and language(s)
  2. Strips frontmatter and code blocks from each output file
  3. Samples up to 3 body paragraphs
  4. Runs FastText language detection on the sample
  5. Flags files where detected lang != expected lang AND confidence >= threshold

Usage:
    python scripts/scan_wrong_language_outputs.py --site docs.aspose.net
    python scripts/scan_wrong_language_outputs.py --site docs.aspose.net --lang de
    python scripts/scan_wrong_language_outputs.py --site blog.aspose.net --threshold 0.85
    python scripts/scan_wrong_language_outputs.py --json > reports/wrong_lang_scan.json
    python scripts/scan_wrong_language_outputs.py --repair  # delete flagged files (use with caution)

Output:
    {output_path, expected_lang, detected_lang, confidence, sample_text}
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import iter_locale_pairs  # noqa: E402

_CONFIG = ConfigService(_PROJECT_ROOT / "config")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Default confidence threshold for flagging wrong-language files
DEFAULT_THRESHOLD = 0.80

# Minimum body text length to bother checking (avoid flagging stub/empty files)
MIN_TEXT_LENGTH = 30

# Max paragraphs to sample per file (keep it fast)
MAX_SAMPLE_PARAGRAPHS = 3

# Skip language pairs that are known to be similar (fasttext may confuse them)
# These pairs are legitimate near-misses and should not be flagged
SIMILAR_LANG_PAIRS: set[frozenset] = {
    frozenset({"hr", "sr"}),
    frozenset({"hr", "bs"}),
    frozenset({"sr", "bs"}),
    frozenset({"ms", "id"}),
    frozenset({"cs", "sk"}),
    frozenset({"nb", "no"}),
    frozenset({"no", "da"}),
}


def load_fasttext_model(model_path: Path):
    """Load FastText model. Returns model or None if unavailable."""
    try:
        import fasttext  # type: ignore

        if not model_path.exists():
            logger.error(f"FastText model not found: {model_path}")
            return None
        model = fasttext.load_model(str(model_path))
        return model
    except ImportError:
        logger.error("fasttext-predict not installed. Run: pip install fasttext-predict")
        return None
    except Exception as e:
        logger.error(f"Failed to load FastText model: {e}")
        return None


def detect_language(model, text: str) -> tuple[str, float]:
    """
    Detect language of text. Returns (lang_code, confidence).
    Returns ("unknown", 0.0) on failure.
    """
    try:
        text_clean = text.replace("\n", " ").strip()
        if not text_clean:
            return "unknown", 0.0
        predictions = model.predict(text_clean, k=1)
        label = predictions[0][0].replace("__label__", "")
        confidence = float(predictions[1][0])
        return label, confidence
    except Exception as e:
        logger.debug(f"Language detection error: {e}")
        return "unknown", 0.0


def strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from file content."""
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            return content[end + 4 :].lstrip("\n")
    return content


def extract_body_sample(content: str, max_paragraphs: int = MAX_SAMPLE_PARAGRAPHS) -> str:
    """
    Extract a sample of body text for language detection.
    Skips code blocks, shortcodes, and very short lines.
    Returns concatenated sample paragraphs.
    """
    body = strip_frontmatter(content)

    # Remove fenced code blocks (``` ... ```)
    body = re.sub(r"```[\s\S]*?```", "", body)
    # Remove indented code blocks (4+ spaces at line start)
    body = re.sub(r"(?m)^(    |\t).+$", "", body)
    # Remove Hugo shortcodes {{< >}} and {{% %}}
    body = re.sub(r"\{\{[<%][^}]*[>%]\}\}", "", body)
    # Remove HTML tags
    body = re.sub(r"<[^>]+>", "", body)
    # Remove markdown links but keep link text
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    # Remove markdown image syntax
    body = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body)
    # Remove URLs
    body = re.sub(r"https?://\S+", "", body)

    paragraphs = []
    for para in re.split(r"\n\n+", body):
        para = para.strip()
        # Skip headings (start with #)
        if para.startswith("#"):
            para = re.sub(r"^#+\s*", "", para)
        # Skip very short paragraphs (likely labels or code artifacts)
        if len(para) < MIN_TEXT_LENGTH:
            continue
        # Skip paragraphs that look like code (high ratio of non-letter chars)
        letter_ratio = sum(1 for c in para if c.isalpha()) / len(para)
        if letter_ratio < 0.5:
            continue
        paragraphs.append(para)
        if len(paragraphs) >= max_paragraphs:
            break

    return " ".join(paragraphs)


def is_similar_pair(lang_a: str, lang_b: str) -> bool:
    """Return True if the two languages are known to be similar (acceptable confusion)."""
    return frozenset({lang_a, lang_b}) in SIMILAR_LANG_PAIRS


# Durable-fix consolidation: this script already correctly read
# output_layout.per_language_folders (one of only 2 scripts found to do so
# independently, alongside measure_completeness.py) -- it wasn't broken,
# but it was a second, parallel implementation of logic that now lives
# canonically in src/utils/content_discovery.py. Consolidated onto that
# shared module so there is exactly one correct implementation.


def load_site_profiles(profiles_dir: Path, site_filter: str | None = None) -> list:
    """Load all production site profiles (*.aspose.net.yaml / *.aspose.org.yaml).

    Preserves this script's original scope: only "top-level" production
    profiles, not the `.words`-suffixed sub-profiles or test/disabled ones.
    Builds its own ConfigService from profiles_dir's parent rather than
    reusing the module-level _CONFIG singleton, so a custom --profiles-dir
    override is respected.
    """
    config_service = (
        _CONFIG if profiles_dir.resolve() == _CONFIG.site_profiles_dir.resolve()
        else ConfigService(profiles_dir.parent)
    )
    profiles = []
    for p in sorted(profiles_dir.glob("*.yaml")):
        name = p.stem
        if not (name.endswith(".aspose.net") or name.endswith(".aspose.org")):
            continue
        if site_filter and name != site_filter:
            continue
        try:
            profiles.append(config_service.get_site_profile(name))
        except Exception as e:
            logger.warning(f"Failed to load {p}: {e}")
    return profiles


def get_output_files_for_lang(
    profile,
    target_lang: str,
) -> list[tuple[Path, str]]:
    """
    Enumerate existing output files for a given site profile and target
    language. Registry-driven via content_discovery.iter_locale_pairs --
    works identically for per_language_folders=True and file-suffix sites.
    Returns list of (output_file_path, expected_lang).
    """
    output_files = []
    for root_raw in profile.content_roots:
        root_path = _CONFIG.resolve_content_root(root_raw)
        if not root_path.exists():
            continue
        for _en_path, locale, tr_path in iter_locale_pairs(profile, root_path):
            if locale == target_lang and tr_path.exists():
                output_files.append((tr_path, target_lang))

    return output_files


def scan_site_lang(
    profile: dict,
    target_lang: str,
    model,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[dict]:
    """
    Scan all output files for a given site+lang.
    Returns list of flagged file dicts.
    """
    site_id = profile.site_id
    output_files = get_output_files_for_lang(profile, target_lang)
    if not output_files:
        logger.debug(f"[{site_id}/{target_lang}] No output files found")
        return []

    flagged = []
    checked = 0

    for output_path, expected_lang in output_files:
        try:
            content = output_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"Failed to read {output_path}: {e}")
            continue

        sample = extract_body_sample(content)
        if not sample or len(sample) < MIN_TEXT_LENGTH:
            continue  # Not enough body text to make a judgment

        detected_lang, confidence = detect_language(model, sample)
        checked += 1

        if detected_lang == "unknown":
            continue

        if detected_lang == expected_lang:
            continue  # Correct

        if confidence < threshold:
            continue  # Not confident enough to flag

        if is_similar_pair(detected_lang, expected_lang):
            continue  # Known similar pair — acceptable

        # Flagged as wrong language
        flagged.append(
            {
                "site_id": site_id,
                "output_path": str(output_path),
                "expected_lang": expected_lang,
                "detected_lang": detected_lang,
                "confidence": round(confidence, 3),
                "sample_text": sample[:200],
            }
        )

    logger.info(
        f"[{site_id}/{target_lang}] Checked {checked} files, flagged {len(flagged)} wrong-language"
    )
    return flagged


def print_results_table(flagged: list[dict]) -> None:
    if not flagged:
        print("\nNo wrong-language outputs detected.")
        return

    # Group by site
    by_site: dict[str, list[dict]] = {}
    for item in flagged:
        by_site.setdefault(item["site_id"], []).append(item)

    total = 0
    for site_id, items in sorted(by_site.items()):
        by_lang: dict[str, int] = {}
        for item in items:
            by_lang[item["expected_lang"]] = by_lang.get(item["expected_lang"], 0) + 1

        print(f"\n{site_id}: {len(items)} wrong-language outputs")
        for lang, count in sorted(by_lang.items()):
            print(f"  {lang:<6}  {count} files")

        # Show sample of worst cases
        for item in items[:3]:
            print(
                f"  [{item['expected_lang']}→detected:{item['detected_lang']} conf:{item['confidence']:.2f}] {item['output_path']}"
            )
        if len(items) > 3:
            print(f"  ... and {len(items) - 3} more")

        total += len(items)

    print(f"\nTotal wrong-language files: {total}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan translated output files for wrong-language content"
    )
    parser.add_argument("--site", help="Filter to a specific site (e.g. docs.aspose.net)")
    parser.add_argument("--lang", help="Filter to a specific target language (e.g. de)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Confidence threshold for flagging (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--model",
        default="data/models/fasttext/lid.176.bin",
        help="Path to FastText lid.176.bin model",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="DELETE flagged wrong-language files (so they get retranslated on next run). USE WITH CAUTION.",
    )
    parser.add_argument(
        "--profiles-dir",
        default="config/site_profiles",
        help="Path to site profiles directory",
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    model = load_fasttext_model(model_path)
    if model is None:
        print("ERROR: FastText model could not be loaded. Aborting.", file=sys.stderr)
        sys.exit(1)

    profiles_dir = Path(args.profiles_dir)
    if not profiles_dir.exists():
        print(f"ERROR: Profiles directory not found: {profiles_dir}", file=sys.stderr)
        sys.exit(1)

    profiles = load_site_profiles(profiles_dir, site_filter=args.site)
    if not profiles:
        print("No profiles found" + (f" for '{args.site}'" if args.site else ""), file=sys.stderr)
        sys.exit(1)

    all_flagged: list[dict] = []

    for profile in profiles:
        target_langs = list(profile.target_langs)
        if args.lang:
            target_langs = [l for l in target_langs if l == args.lang]

        for lang in target_langs:
            flagged = scan_site_lang(profile, lang, model, threshold=args.threshold)
            all_flagged.extend(flagged)

    if args.json:
        output = [{k: v for k, v in item.items() if k != "sample_text"} for item in all_flagged]
        print(json.dumps(output, indent=2))
    else:
        print_results_table(all_flagged)

    if args.repair:
        if not all_flagged:
            print("Nothing to repair.")
            return
        print(f"\nREPAIR MODE: Deleting {len(all_flagged)} wrong-language output files...")
        deleted = 0
        for item in all_flagged:
            try:
                Path(item["output_path"]).unlink()
                deleted += 1
                print(f"  Deleted: {item['output_path']}")
            except Exception as e:
                print(f"  ERROR deleting {item['output_path']}: {e}")
        print(
            f"\nDeleted {deleted}/{len(all_flagged)} files. They will be retranslated on next worker run."
        )


if __name__ == "__main__":
    main()
